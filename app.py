import streamlit as st
import google.generativeai as genai
import json
from PIL import Image
import sqlite3
from datetime import datetime, date
import pandas as pd
import io
import calendar
import plotly.graph_objects as go
import plotly.express as px
import streamlit.components.v1 as components

# --- 1. DATABÁZE (SQLite) ---
def init_db():
    conn = sqlite3.connect('trading_journal.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            initial_balance REAL NOT NULL
        );
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER,
            ticker TEXT NOT NULL,
            direction TEXT NOT NULL,
            entry_time TEXT NOT NULL,
            actual_r REAL,
            pnl_amount REAL,
            htf_generals_check BOOLEAN,
            market_phase TEXT,
            engine_ma_fan BOOLEAN,
            signature_entry BOOLEAN,
            fresh_zone BOOLEAN,
            notes_emotions TEXT,
            image_data BLOB,
            FOREIGN KEY (account_id) REFERENCES accounts (id)
        );
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trade_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id INTEGER NOT NULL,
            image_data BLOB NOT NULL,
            FOREIGN KEY (trade_id) REFERENCES trades (id) ON DELETE CASCADE
        );
    ''')
    
    # Bezpečné rozšíření stávající databáze o nové sloupce (pokud ještě neexistují)
    try:
        cursor.execute("ALTER TABLE trades ADD COLUMN account_id INTEGER;")
    except sqlite3.OperationalError:
        pass
        
    try:
        cursor.execute("ALTER TABLE trades ADD COLUMN inverted_chart BOOLEAN DEFAULT 0;")
    except sqlite3.OperationalError:
        pass
        
    conn.commit()
    conn.close()

init_db()

# --- 2. KONFIGURACE AI (Bezpečné načítání klíče ze schránky) ---
try:
    API_KEY = st.secrets["API_KEY"]
except Exception:
    API_KEY = ""  # Prázdné pro bezpečný GitHub upload

if API_KEY:
    genai.configure(api_key=API_KEY)
    model = genai.GenerativeModel('models/gemini-3.6-flash')
else:
    model = None

st.set_page_config(page_title="AI Trading Journal", layout="wide")

# CSS styly pro karty a metriky
st.markdown("""
    <style>
    .cal-card-green {
        background-color: rgba(46, 160, 67, 0.15);
        border: 1px solid #2ea043;
        border-radius: 8px;
        padding: 12px;
        text-align: center;
        height: 95px;
        margin-bottom: 8px;
    }
    .cal-card-red {
        background-color: rgba(218, 54, 51, 0.15);
        border: 1px solid #da3633;
        border-radius: 8px;
        padding: 12px;
        text-align: center;
        height: 95px;
        margin-bottom: 8px;
    }
    .cal-card-empty {
        background-color: #161b22;
        border: 1px solid #30363d;
        border-radius: 8px;
        padding: 12px;
        text-align: center;
        height: 95px;
        margin-bottom: 8px;
        opacity: 0.4;
    }
    .cal-day-header {
        font-weight: bold;
        text-align: center;
        color: #8b949e;
        padding-bottom: 5px;
    }
    .metric-card {
        background-color: #161b22;
        border: 1px solid #30363d;
        border-radius: 10px;
        padding: 18px;
        text-align: center;
        margin-bottom: 15px;
    }
    </style>
""", unsafe_allow_html=True)

st.title("📈 Můj AI Obchodní Deník")

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "➕ Nový obchod & AI", 
    "🔍 Historie obchodů", 
    "💼 Správa účtů", 
    "📊 Dashboard & Kalendář",
    "🌍 Ekonomický kalendář"
])

# ==========================================
# ZÁLOŽKA 1: Nový obchod, AI & Kalkulačka
# ==========================================
with tab1:
    
    with st.expander("🧮 Kalkulačka velikosti pozice (Risk Management)"):
        c_col1, c_col2, c_col3 = st.columns(3)
        with c_col1:
            calc_acc_bal = st.number_input("Zůstatek na účtu ($)", value=200000.0, step=1000.0)
        with c_col2:
            calc_risk_pct = st.number_input("Risk na obchod (%)", value=1.0, step=0.1)
        with c_col3:
            calc_sl_pips = st.number_input("Velikost Stop Lossu (pips)", value=10.0, step=1.0)
        
        risk_amt = calc_acc_bal * (calc_risk_pct / 100)
        if calc_sl_pips > 0:
            calc_lots = risk_amt / (calc_sl_pips * 10)  # Kalkulace pro standardní páry USD
            st.info(f"🛡️ **Riskovaná částka:** `${risk_amt:,.2f}` | 📉 **Doporučená velikost pozice (odhad na 10$/pip):** `{calc_lots:.2f} Lotů`")
    
    st.markdown("---")
    st.write("Nahraj screenshot grafu, nechej AI vyhodnotit checklist a ulož obchod na vybraný účet.")
    
    conn = sqlite3.connect('trading_journal.db')
    accounts_df = pd.read_sql_query("SELECT id, name, initial_balance FROM accounts", conn)
    conn.close()
    
    if accounts_df.empty:
        st.warning("⚠️ Nejdříve si musíš vytvořit alespoň jeden obchodní účet v záložce 'Správa účtů'!")
    
    uploaded_file = st.file_uploader("Nahraj hlavní obrázek grafu (PNG, JPG)", type=["png", "jpg", "jpeg"], key="main_upload")

    if "ai_data" not in st.session_state:
        st.session_state.ai_data = None
    if "saved_image_bytes" not in st.session_state:
        st.session_state.saved_image_bytes = None

    if uploaded_file is not None:
        st.session_state.saved_image_bytes = uploaded_file.getvalue()
        image = Image.open(io.BytesIO(st.session_state.saved_image_bytes))
        st.image(image, caption="Nahraný hlavní graf pro analýzu", use_container_width=True)
        
        if st.button("🤖 Analyzovat graf pomocí AI"):
            if not model:
                st.error("⚠️ Model AI není nakonfigurován. Zkontroluj, zda máš nastavený API klíč ve Streamlit Secrets.")
            else:
                with st.spinner("AI studuje strukturu trhu a MA vějíř..."):
                    prompt = """
                    Analyzuj tento tradingový graf a vrať POUZE formát JSON s následujícími klíči (hodnoty true/false nebo přesný text):
                    1. "htf_context": (true/false) Je na grafu vidět správný sklon EMA (5, 10, 20) a validovaný MB?
                    2. "market_phase": (text) Je cena v "Accumulation MB" nebo došlo k průrazu "Contain line"? Vypiš jednu z těchto dvou možností.
                    3. "engine_ma_fan": (true/false) Je 1H MA vějíř (tyrkysová 5, červená 10, modrá 20) správně seřazen s displacementem?
                    4. "signature_entry": (true/false) Vidíš formaci MB1 -> Flush -> MB2?
                    5. "zone_qualified": (true/false) Je zóna fresh a vybrala likviditu?
                    """
                    try:
                        response = model.generate_content([prompt, image])
                        clean_json = response.text.strip().removeprefix('```json').removesuffix('```')
                        st.session_state.ai_data = json.loads(clean_json)
                        st.success("Analýza dokončena! Zkontroluj formulář níže.")
                    except Exception as e:
                        st.error(f"Chyba při komunikaci s AI: {e}")

    if st.session_state.saved_image_bytes is not None and not accounts_df.empty:
        data = st.session_state.ai_data if st.session_state.ai_data else {}
        
        st.markdown("---")
        st.subheader("📝 Detaily obchodu a kontrola")
        
        with st.form("trade_form"):
            account_options = {str(name).strip(): (acc_id, init_bal) for name, acc_id, init_bal in zip(accounts_df['name'], accounts_df['id'], accounts_df['initial_balance'])}
            selected_account_name = st.selectbox("Obchodní účet", list(account_options.keys()))
            selected_acc_id, selected_acc_init = account_options[selected_account_name]
            
            col1, col2 = st.columns(2)
            with col1:
                ticker = st.text_input("Ticker / Pár", value="GBP/JPY")
                direction = st.selectbox("Směr", ["Long", "Short"])
            with col2:
                actual_r = st.number_input("Dosažené R (např. 2.0)", value=2.0)
                pnl = st.number_input("Zisk (+) / Ztráta (-) v penězích", value=250.0)
                
            pct_preview = (pnl / selected_acc_init) * 100 if selected_acc_init > 0 else 0.0
            st.info(f"📊 **Dopad na účet:** `{pct_preview:+.2f}%` z celkového kapitálu (${selected_acc_init:,.2f})")
                
            htf_check = st.checkbox("Generals' check (EMA 5, 10, 20 & daily MB)", value=data.get("htf_context", False))
            market_phase = st.text_input("Fáze trhu", value=data.get("market_phase", "Contain line"))
            engine_check = st.checkbox("Engine check (MA Fan tyrkysová/červená/modrá)", value=data.get("engine_ma_fan", False))
            signature_check = st.checkbox("Signature search (MB1 -> Flush -> MB2)", value=data.get("signature_entry", False))
            zone_check = st.checkbox("Zone qualification (Fresh & Swept liquidity)", value=data.get("zone_qualified", False))
            
            st.markdown("---")
            inverted_chart_check = st.checkbox("🔄 Inverted chart setup (Byl analyzován přes obrácený graf?)", value=False)
            
            notes = st.text_area("Psychologie a poznámky k obchodu", value="Vše podle plánu.")
            
            submit_button = st.form_submit_button(label="💾 Uložit obchod do zvoleného účtu")
            
            if submit_button:
                conn = sqlite3.connect('trading_journal.db')
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO trades (
                        account_id, ticker, direction, entry_time, actual_r, pnl_amount,
                        htf_generals_check, market_phase, engine_ma_fan, 
                        signature_entry, fresh_zone, notes_emotions, image_data, inverted_chart
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    selected_acc_id, ticker, direction, datetime.now().strftime("%Y-%m-%d %H:%M"), 
                    actual_r, pnl, htf_check, market_phase, engine_check, signature_check, 
                    zone_check, notes, st.session_state.saved_image_bytes, inverted_chart_check
                ))
                conn.commit()
                conn.close()
                st.success(f"🎉 Obchod s výsledkem {pnl:+,.2f} USD ({pct_preview:+.2f}%) byl úspěšně zapsán!")

# ==========================================
# ZÁLOŽKA 2: Historie a rozklikávání obchodů
# ==========================================
with tab2:
    st.subheader("📚 Deník obchodů s přehledem po účtech")
    
    conn = sqlite3.connect('trading_journal.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT t.id, a.name, a.initial_balance, t.ticker, t.direction, t.entry_time, t.actual_r, t.pnl_amount, 
               t.htf_generals_check, t.market_phase, t.engine_ma_fan, 
               t.signature_entry, t.fresh_zone, t.notes_emotions, t.image_data, t.account_id, t.inverted_chart 
        FROM trades t
        LEFT JOIN accounts a ON t.account_id = a.id
        ORDER BY t.id DESC
    ''')
    trades = cursor.fetchall()
    conn.close()
    
    if not trades:
        st.info("Zatím tu nemáš uložené žádné obchody.")
    else:
        conn = sqlite3.connect('trading_journal.db')
        acc_filter_df = pd.read_sql_query("SELECT name FROM accounts", conn)
        conn.close()
        
        account_list = ["Všechny účty"] + [str(n).strip() for n in acc_filter_df['name']]
        selected_filter = st.selectbox("Filtrovat historii podle účtu", account_list, key="hist_filter")
        
        filtered_trades = trades if selected_filter == "Všechny účty" else [t for t in trades if t[1] and str(t[1]).strip() == selected_filter]
        
        st.markdown("---")
        
        for t in filtered_trades:
            # Rozbalení rozšířených hodnot
            (t_id, t_acc_name, t_acc_init, t_ticker, t_dir, t_time, t_r, t_pnl, 
             t_htf, t_phase, t_eng, t_sig, t_zone, t_notes, t_img, t_acc_id, t_inv) = t
            
            clean_acc_name = str(t_acc_name).strip() if t_acc_name else "Neznámý účet"
            init_b = t_acc_init if t_acc_init and t_acc_init > 0 else 200000.0
            pnl_val = t_pnl if t_pnl is not None else 0.0
            trade_pct = (pnl_val / init_b) * 100
            
            badge = "🟢" if pnl_val >= 0 else "🔴"
            header = f"{badge} #{t_id} [{clean_acc_name}] | {t_time} | {t_ticker} ({t_dir}) | PnL: {pnl_val:+,.2f} USD ({trade_pct:+.2f}%) | {t_r} R"
            
            with st.expander(header):
                with st.form(key=f"edit_trade_{t_id}"):
                    st.write(f"✏️ **Rychlá úprava (Dopad na účet: {trade_pct:+.2f}%):**")
                    col_e1, col_e2 = st.columns(2)
                    with col_e1:
                        new_pnl = st.number_input("Zisk (+) / Ztráta (-) v penězích", value=float(pnl_val), key=f"pnl_{t_id}")
                    with col_e2:
                        new_r = st.number_input("Dosažené R", value=float(t_r) if t_r is not None else 0.0, key=f"r_{t_id}")
                    
                    update_trade_btn = st.form_submit_button("💾 Uložit změnu obchodu")
                    if update_trade_btn:
                        conn_ut = sqlite3.connect('trading_journal.db')
                        cursor_ut = conn_ut.cursor()
                        cursor_ut.execute("UPDATE trades SET pnl_amount = ?, actual_r = ? WHERE id = ?", (new_pnl, new_r, t_id))
                        conn_ut.commit()
                        conn_ut.close()
                        st.success("Obchod byl úspěšně aktualizován!")
                        st.rerun()

                st.markdown("---")
                col_left, col_right = st.columns([1, 1])
                
                with col_left:
                    st.markdown("### 📋 Vyhodnocení parametrů")
                    st.write(f"**Účet:** `{clean_acc_name}` (Základ: ${init_b:,.2f})")
                    st.write(f"**Dopad obchodu:** `{trade_pct:+.2f}%`")
                    st.write(f"**Fáze trhu:** `{t_phase}`")
                    st.write(f"- Generals' check: {'✅ Splněno' if t_htf else '❌ Nesplněno'}")
                    st.write(f"- Engine MA Fan (5/10/20): {'✅ Splněno' if t_eng else '❌ Nesplněno'}")
                    st.write(f"- Signature (MB1 -> Flush -> MB2): {'✅ Splněno' if t_sig else '❌ Nesplněno'}")
                    st.write(f"- Kvalifikace zóny: {'✅ Splněno' if t_zone else '❌ Nesplněno'}")
                    st.write(f"- Inverted Chart: {'✅ Použito' if t_inv else '❌ Běžný graf'}")
                    
                    st.markdown("### 🧠 Poznámky a emoce")
                    st.info(t_notes if t_notes else "Žádné poznámky nebyly zadány.")
                
                with col_right:
                    st.markdown("### 🖼️ Galerie obrázků k obchodu")
                    if t_img is not None:
                        img_obj = Image.open(io.BytesIO(t_img))
                        st.image(img_obj, caption=f"Hlavní vstupní graf #{t_id}", use_container_width=True)
                    else:
                        st.caption("Hlavní screenshot nebyl uložen.")
                    
                    conn_img = sqlite3.connect('trading_journal.db')
                    cursor_img = conn_img.cursor()
                    cursor_img.execute("SELECT id, image_data FROM trade_images WHERE trade_id = ?", (t_id,))
                    extra_images = cursor_img.fetchall()
                    conn_img.close()
                    
                    if extra_images:
                        st.write("---")
                        st.write("**Dodatečné screenshoty v paměti:**")
                        for ex_id, ex_blob in extra_images:
                            ex_img_obj = Image.open(io.BytesIO(ex_blob))
                            st.image(ex_img_obj, caption=f"Dodatečný záznam #{ex_id}", use_container_width=True)
                    
                    st.write("---")
                    extra_upload = st.file_uploader(f"Přidat další obrázek k obchodu #{t_id}", type=["png", "jpg", "jpeg"], key=f"extra_up_{t_id}")
                    if extra_upload is not None:
                        if st.button(f"💾 Uložit nový obrázek k # {t_id}", key=f"btn_save_{t_id}"):
                            extra_bytes = extra_upload.getvalue()
                            conn_in = sqlite3.connect('trading_journal.db')
                            cursor_in = conn_in.cursor()
                            cursor_in.execute("INSERT INTO trade_images (trade_id, image_data) VALUES (?, ?)", (t_id, extra_bytes))
                            conn_in.commit()
                            conn_in.close()
                            st.success("Obrázek přidán!")
                            st.rerun()

# ==========================================
# ZÁLOŽKA 3: Správa účtů
# ==========================================
with tab3:
    st.subheader("💼 Správa obchodních účtů")
    
    with st.expander("➕ Vytvořit nový účet"):
        with st.form("new_account_form"):
            col_a1, col_a2 = st.columns(2)
            with col_a1:
                acc_name = st.text_input("Název účtu (např. Mentfunding)")
            with col_a2:
                acc_initial = st.number_input("Základní / Počáteční kapitál ($/EUR)", value=200000.0)
                
            acc_submit = st.form_submit_button("Vytvořit účet")
            if acc_submit:
                clean_name = acc_name.strip()
                if clean_name == "":
                    st.error("Zadej platný název účtu!")
                else:
                    try:
                        conn = sqlite3.connect('trading_journal.db')
                        cursor = conn.cursor()
                        cursor.execute("INSERT INTO accounts (name, initial_balance) VALUES (?, ?)", (clean_name, acc_initial))
                        conn.commit()
                        conn.close()
                        st.success(f"Účet '{clean_name}' byl úspěšně vytvořen!")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error("Účet s tímto názvem již existuje!")

    st.markdown("---")
    st.subheader("📊 Seznam účtů a úprava základů")
    
    conn = sqlite3.connect('trading_journal.db')
    accounts_summary_query = '''
        SELECT a.id, a.name, a.initial_balance, 
               COALESCE(SUM(t.pnl_amount), 0) as total_pnl,
               COUNT(t.id) as trade_count
        FROM accounts a
        LEFT JOIN trades t ON a.id = t.account_id
        GROUP BY a.id
    '''
    acc_df = pd.read_sql_query(accounts_summary_query, conn)
    conn.close()
    
    if acc_df.empty:
        st.info("Zatím tu nemáš vytvořené žádné účty.")
    else:
        for index, row in acc_df.iterrows():
            acc_id = row['id']
            acc_name = str(row['name']).strip()
            current_initial = row['initial_balance']
            total_pnl = row['total_pnl']
            calculated_balance = current_initial + total_pnl
            
            with st.container():
                st.markdown(f"### 🏦 Účet: {acc_name}")
                col_m1, col_m2, col_m3, col_m4 = st.columns(4)
                col_m1.metric("Základní vklad", f"{current_initial:,.2f}")
                col_m2.metric("Celkový PnL", f"{total_pnl:+,.2f}")
                col_m3.metric("Aktuální stav", f"{calculated_balance:,.2f}")
                col_m4.metric("Počet obchodů", row['trade_count'])
                
                with st.form(key=f"edit_acc_{acc_id}"):
                    new_base = st.number_input(f"Upravit základ pro '{acc_name}':", value=float(current_initial), key=f"val_{acc_id}")
                    update_btn = st.form_submit_button(f"💾 Uložit nový základ pro {acc_name}")
                    
                    if update_btn:
                        conn_up = sqlite3.connect('trading_journal.db')
                        cursor_up = conn_up.cursor()
                        cursor_up.execute("UPDATE accounts SET initial_balance = ? WHERE id = ?", (new_base, acc_id))
                        conn_up.commit()
                        conn_up.close()
                        st.success(f"Základ pro účet '{acc_name}' byl aktualizován!")
                        st.rerun()
                st.markdown("---")

# ==========================================
# ZÁLOŽKA 4: Dashboard, Statistiky & Kalendář
# ==========================================
with tab4:
    st.subheader("📊 Výkonnostní Dashboard & Statistiky")
    
    conn = sqlite3.connect('trading_journal.db')
    acc_dash_df = pd.read_sql_query("SELECT id, name, initial_balance FROM accounts", conn)
    conn.close()
    
    if acc_dash_df.empty:
        st.info("Nejprve si vytvoř alespoň jeden účet v záložce 'Správa účtů'.")
    else:
        acc_dash_df['clean_name'] = acc_dash_df['name'].str.strip()
        dash_account_name = st.selectbox("Vyber účet pro zobrazení detailu", acc_dash_df['clean_name'], key="dash_acc_select")
        
        selected_acc_row = acc_dash_df[acc_dash_df['clean_name'] == dash_account_name].iloc[0]
        selected_acc_id = selected_acc_row['id']
        selected_acc_init = selected_acc_row['initial_balance']
        
        conn_d = sqlite3.connect('trading_journal.db')
        dash_trades = pd.read_sql_query(
            "SELECT id, ticker, direction, entry_time, actual_r, pnl_amount, htf_generals_check, market_phase, engine_ma_fan, signature_entry, fresh_zone, notes_emotions, image_data, inverted_chart FROM trades WHERE account_id = ? ORDER BY id ASC", 
            conn_d, params=(selected_acc_id,)
        )
        if dash_trades.empty:
            fallback_query = '''
                SELECT t.id, t.ticker, t.direction, t.entry_time, t.actual_r, t.pnl_amount, t.htf_generals_check, t.market_phase, t.engine_ma_fan, t.signature_entry, t.fresh_zone, t.notes_emotions, t.image_data, t.inverted_chart 
                FROM trades t
                LEFT JOIN accounts a ON t.account_id = a.id
                WHERE TRIM(a.name) = ? ORDER BY t.id ASC
            '''
            dash_trades = pd.read_sql_query(fallback_query, conn_d, params=(dash_account_name,))
        conn_d.close()
        
        # Výpočty pro metriky
        total_trades = len(dash_trades)
        total_pnl = dash_trades['pnl_amount'].sum() if not dash_trades.empty else 0.0
        current_equity = selected_acc_init + total_pnl
        total_pct_return = (total_pnl / selected_acc_init) * 100 if selected_acc_init > 0 else 0.0
        
        if not dash_trades.empty:
            winning_trades = dash_trades[dash_trades['pnl_amount'] > 0]
            losing_trades = dash_trades[dash_trades['pnl_amount'] < 0]
            
            win_rate = (len(winning_trades) / total_trades) * 100 if total_trades > 0 else 0
            avg_win = winning_trades['pnl_amount'].mean() if not winning_trades.empty else 0.0
            avg_loss = losing_trades['pnl_amount'].mean() if not losing_trades.empty else 0.0
            best_trade = dash_trades['pnl_amount'].max() if not dash_trades.empty else 0.0
            worst_trade = dash_trades['pnl_amount'].min() if not dash_trades.empty else 0.0
        else:
            win_rate = 0.0
            avg_win = 0.0
            avg_loss = 0.0
            best_trade = 0.0
            worst_trade = 0.0
        
        st.markdown("---")
        d1, d2, d3, d4 = st.columns(4)
        d1.metric("Net PnL", f"${total_pnl:,.2f} ({total_pct_return:+.2f}%)")
        d2.metric("Aktuální stav účtu", f"${current_equity:,.2f}")
        d3.metric("Úspěšnost (Win Rate)", f"{win_rate:.1f}%")
        d4.metric("Celkem obchodů", total_trades)
        
        # --- KARIÉRNÍ KARTY ---
        st.markdown("### 🏆 Detailní statistiky výkonu")
        c1, c2, c3, c4 = st.columns(4)
        
        with c1:
            st.markdown(f"""
                <div class="metric-card">
                    <div style="font-size: 13px; color: #8b949e; font-weight: bold;">Průměrný zisk (Avg Win)</div>
                    <div style="font-size: 20px; font-weight: bold; color: #2ea043; margin-top: 6px;">${avg_win:,.2f}</div>
                    <div style="font-size: 11px; color: #8b949e;">({(avg_win/selected_acc_init)*100:+.2f}% kapitálu)</div>
                </div>
            """, unsafe_allow_html=True)
            
        with c2:
            st.markdown(f"""
                <div class="metric-card">
                    <div style="font-size: 13px; color: #8b949e; font-weight: bold;">Průměrná ztráta (Avg Loss)</div>
                    <div style="font-size: 20px; font-weight: bold; color: #da3633; margin-top: 6px;">${avg_loss:,.2f}</div>
                    <div style="font-size: 11px; color: #8b949e;">({(avg_loss/selected_acc_init)*100:+.2f}% kapitálu)</div>
                </div>
            """, unsafe_allow_html=True)
            
        with c3:
            st.markdown(f"""
                <div class="metric-card">
                    <div style="font-size: 13px; color: #8b949e; font-weight: bold;">Nejlepší obchod (Best Trade)</div>
                    <div style="font-size: 20px; font-weight: bold; color: #2ea043; margin-top: 6px;">${best_trade:,.2f}</div>
                    <div style="font-size: 11px; color: #8b949e;">({(best_trade/selected_acc_init)*100:+.2f}% kapitálu)</div>
                </div>
            """, unsafe_allow_html=True)
            
        with c4:
            st.markdown(f"""
                <div class="metric-card">
                    <div style="font-size: 13px; color: #8b949e; font-weight: bold;">Nejhorší obchod (Worst Trade)</div>
                    <div style="font-size: 20px; font-weight: bold; color: #da3633; margin-top: 6px;">${worst_trade:,.2f}</div>
                    <div style="font-size: 11px; color: #8b949e;">({(worst_trade/selected_acc_init)*100:+.2f}% kapitálu)</div>
                </div>
            """, unsafe_allow_html=True)
            
        st.markdown("---")
        
        # --- POKROČILÉ GRAFY (Win-rate podle Párů a Směru) ---
        if total_trades > 0:
            st.markdown("### 🎯 Detailní Win-Rate a rozložení obchodů")
            graph_c1, graph_c2 = st.columns(2)
            
            with graph_c1:
                # Výpočet Win-rate podle Tickerů
                pair_stats = dash_trades.groupby('ticker').apply(
                    lambda x: pd.Series({'Wins': (x['pnl_amount'] > 0).sum(), 'Losses': (x['pnl_amount'] <= 0).sum()})
                ).reset_index()
                
                fig_pairs = px.bar(
                    pair_stats, x='ticker', y=['Wins', 'Losses'], 
                    title="Výhry a Prohry podle Párů", 
                    barmode='group',
                    color_discrete_map={'Wins': '#2ea043', 'Losses': '#da3633'}
                )
                fig_pairs.update_layout(template='plotly_dark', margin=dict(l=20, r=20, t=40, b=20))
                st.plotly_chart(fig_pairs, use_container_width=True)
                
            with graph_c2:
                # Rozložení Long vs Short a Inverted
                dir_stats = dash_trades.groupby('direction')['id'].count().reset_index()
                fig_dir = go.Figure(data=[go.Pie(
                    labels=dir_stats['direction'], 
                    values=dir_stats['id'], 
                    hole=.4, 
                    marker_colors=['#2ea043' if d=='Long' else '#da3633' for d in dir_stats['direction']]
                )])
                fig_dir.update_layout(title="Rozložení Směru Obchodů (Long vs Short)", template='plotly_dark', margin=dict(l=20, r=20, t=40, b=20))
                st.plotly_chart(fig_dir, use_container_width=True)
                
        st.markdown("---")

        # --- AI TRADING KOUČ ---
        st.markdown("### 🤖 AI Trading Kouč (Zhodnocení obchodování)")
        if st.button("Zhodnotit moje statistiky pomocí AI"):
            if model and total_trades > 0:
                with st.spinner("AI analyzuje tvá data a hledá klíčové patterny pro vylepšení..."):
                    recent_trades = dash_trades.tail(20) # Posledních 20 obchodů kvůli limitům AI
                    data_str = recent_trades[['ticker', 'direction', 'actual_r', 'pnl_amount', 'htf_generals_check', 'engine_ma_fan', 'inverted_chart']].to_json(orient='records')
                    
                    prompt_coach = f"""
                    Jsi profesionální trading kouč zaměřený na strategii MentFX. Analyzuj těchto posledních pár obchodů klienta (data v JSON: {data_str}).
                    Tvůj úkol:
                    1. Dej mu stručnou, údernou a motivační zpětnou vazbu v češtině.
                    2. Vypíchni, co funguje dobře (např. dodržování pravidel jako MA fan).
                    3. Upozorni na to, kde ztrácí (jaké páry, jestli u long/short, nebo když nedodrží checklist).
                    4. Zhodnoť také vliv použití 'inverted_chart' (obráceného grafu), pokud ho využívá.
                    Max 3-4 odstavce.
                    """
                    try:
                        resp = model.generate_content(prompt_coach)
                        st.info(resp.text)
                    except Exception as e:
                        st.error(f"Chyba při komunikaci s AI: {e}")
            else:
                st.warning("Potřebuješ alespoň 1 uložený obchod a nastavený API klíč, aby mohl kouč fungovat.")
        st.markdown("---")
        
        # --- HLADKÁ ZAOBLENÁ PLOTLY EQUITY KŘIVKA (SPLINE) ---
        if not dash_trades.empty:
            
            x_vals = ['Start'] + [f"Obchod #{i+1} ({t.strftime('%d.%m.')})" for i, t in enumerate(dash_trades['date_parsed'])]
            y_vals = [0.0] + dash_trades['cumulative_pnl'].tolist()
            
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=x_vals,
                y=y_vals,
                mode='lines+markers',
                line=dict(shape='spline', smoothing=1.3, color='#2ea043' if y_vals[-1] >= 0 else '#da3633', width=3),
                marker=dict(size=8),
                name='Net PnL'
            ))
            fig.update_layout(
                title=f"Equity Křivka účtu: {dash_account_name}",
                template='plotly_dark',
                margin=dict(l=20, r=20, t=40, b=20),
                height=350,
                xaxis=dict(title='Časová osa obchodů'),
                yaxis=dict(title='Kumulativní PnL ($)')
            )
            st.plotly_chart(fig, use_container_width=True)
            st.markdown("---")
        
        st.markdown(f"### 📅 Obchodní kalendář – {dash_account_name}")
        
        with st.expander("➕ Přidat nový obchod do tohoto účtu"):
            with st.form("quick_cal_trade_form"):
                q_col1, q_col2 = st.columns(2)
                with q_col1:
                    q_ticker = st.text_input("Ticker / Pár", value="EUR/USD")
                    q_dir = st.selectbox("Směr", ["Long", "Short"], key="q_dir")
                with q_col2:
                    q_date = st.date_input("Datum obchodu", value=date.today())
                    q_pnl = st.number_input("Zisk (+) / Ztráta (-) v penězích", value=150.0)
                    q_pct_prev = (q_pnl / selected_acc_init) * 100 if selected_acc_init > 0 else 0.0
                    st.caption(f"📊 Dopad: **{q_pct_prev:+.2f}%** z kapitálu (${selected_acc_init:,.2f})")
                    q_r = st.number_input("Dosažené R", value=2.0)
                
                q_submit = st.form_submit_button("💾 Uložit obchod")
                if q_submit:
                    conn_q = sqlite3.connect('trading_journal.db')
                    cursor_q = conn_q.cursor()
                    cursor_q.execute('''
                        INSERT INTO trades (
                            account_id, ticker, direction, entry_time, actual_r, pnl_amount,
                            htf_generals_check, market_phase, engine_ma_fan, 
                            signature_entry, fresh_zone, notes_emotions, inverted_chart
                        ) VALUES (?, ?, ?, ?, ?, ?, 1, 'Kalendářní zápis', 1, 1, 1, 'Zapsáno přes kalendář', 0)
                    ''', (
                        selected_acc_id, q_ticker, q_dir, q_date.strftime("%Y-%m-%d %H:%M"), q_r, q_pnl
                    ))
                    conn_q.commit()
                    conn_q.close()
                    st.success("Obchod úspěšně zapsán!")
                    st.rerun()

        # Inicializace stavu pro překlikávání měsíců
        if 'cal_year' not in st.session_state:
            st.session_state.cal_year = date.today().year
        if 'cal_month' not in st.session_state:
            st.session_state.cal_month = date.today().month

        # Ovládací panel s tlačítky pro překlikávání
        col_nav1, col_nav2, col_nav3 = st.columns([1, 2, 1])
        with col_nav1:
            if st.button("◀ Předchozí měsíc", use_container_width=True):
                if st.session_state.cal_month == 1:
                    st.session_state.cal_month = 12
                    st.session_state.cal_year -= 1
                else:
                    st.session_state.cal_month -= 1
                st.rerun()
        
        months_cz = {
            1: "Leden", 2: "Únor", 3: "Březen", 4: "Duben", 
            5: "Květen", 6: "Červen", 7: "Červenec", 8: "Srpen", 
            9: "Září", 10: "Říjen", 11: "Listopad", 12: "Prosinec"
        }
        with col_nav2:
            st.markdown(f"<h3 style='text-align: center; margin: 0;'>{months_cz[st.session_state.cal_month]} {st.session_state.cal_year}</h3>", unsafe_allow_html=True)

        with col_nav3:
            if st.button("Následující měsíc ▶", use_container_width=True):
                if st.session_state.cal_month == 12:
                    st.session_state.cal_month = 1
                    st.session_state.cal_year += 1
                else:
                    st.session_state.cal_month += 1
                st.rerun()

        st.markdown("---")

        # Zpracování dat pro mřížku
        if not dash_trades.empty:
            daily_agg = dash_trades.groupby(dash_trades['date_parsed'].dt.date).agg(
                daily_pnl=('pnl_amount', 'sum'),
                trade_count=('id', 'count'),
                wins=('pnl_amount', lambda x: (x > 0).sum())
            ).reset_index()
            daily_agg['win_rate'] = (daily_agg['wins'] / daily_agg['trade_count']) * 100
            pnl_by_date = {row['date_parsed']: row for _, row in daily_agg.iterrows()}
        else:
            pnl_by_date = {}

        # Hlavička dnů v týdnu (Pondělí až Neděle)
        days_header = ["Pondělí", "Úterý", "Středa", "Čtvrtek", "Pátek", "Sobota", "Neděle"]
        header_cols = st.columns(7)
        for idx, day_name in enumerate(days_header):
            header_cols[idx].markdown(f"<div class='cal-day-header'>{day_name}</div>", unsafe_allow_html=True)

        cal = calendar.Calendar(firstweekday=0)
        month_weeks = cal.monthdayscalendar(st.session_state.cal_year, st.session_state.cal_month)

        for week in month_weeks:
            week_cols = st.columns(7)
            for idx, day_num in enumerate(week):
                with week_cols[idx]:
                    if day_num == 0:
                        st.markdown("<div class='cal-card-empty'></div>", unsafe_allow_html=True)
                    else:
                        current_date = date(st.session_state.cal_year, st.session_state.cal_month, day_num)
                        formatted_date_cz = current_date.strftime("%d.%m.%Y")
                        
                        if current_date in pnl_by_date:
                            data = pnl_by_date[current_date]
                            dpnl = data['daily_pnl']
                            tcount = data['trade_count']
                            wrate = data['win_rate']
                            
                            card_class = "cal-card-green" if dpnl >= 0 else "cal-card-red"
                            sign = "+" if dpnl >= 0 else ""
                            
                            st.markdown(f"""
                                <div class="{card_class}">
                                    <div style="font-size: 12px; color: #8b949e; font-weight: bold;">{formatted_date_cz}</div>
                                    <div style="font-size: 17px; font-weight: bold; margin: 4px 0;">{sign}${dpnl:,.2f}</div>
                                    <div style="font-size: 11px; color: #c9d1d9;">{tcount} obchod{'y' if tcount > 1 else ''} | {wrate:.1f}%</div>
                                </div>
                            """, unsafe_allow_html=True)
                        else:
                            st.markdown(f"""
                                <div style="background-color: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 12px; text-align: center; height: 95px; margin-bottom: 8px;">
                                    <div style="font-size: 12px; color: #8b949e; font-weight: bold;">{formatted_date_cz}</div>
                                    <div style="font-size: 14px; color: #484f58; margin-top: 15px;">–</div>
                                </div>
                            """, unsafe_allow_html=True)

        # --- INTERAKTIVNÍ DETAIL DNE S MOŽNOSTÍ ÚPRAVY DATA ---
        st.markdown("---")
        st.subheader("🔍 Detail obchodů pro vybraný den")
        
        selected_detail_date = st.date_input("Vyber datum pro zobrazení a úpravu obchodů v tento den", value=date.today(), key="detail_date_picker")
        
        if not dash_trades.empty:
            dash_trades['date_only'] = dash_trades['date_parsed'].dt.date
            day_trades = dash_trades[dash_trades['date_only'] == selected_detail_date]
            
            if not day_trades.empty:
                st.success(f"Nalezeno obchodů pro den {selected_detail_date.strftime('%d.%m.%Y')}: {len(day_trades)}")
                
                for _, dt in day_trades.iterrows():
                    dt_id = dt['id']
                    dt_ticker = dt['ticker']
                    dt_dir = dt['direction']
                    dt_time_str = dt['entry_time']
                    dt_pnl = dt['pnl_amount']
                    dt_r = dt['actual_r']
                    
                    try:
                        parsed_dt = datetime.strptime(dt_time_str, "%Y-%m-%d %H:%M")
                    except ValueError:
                        parsed_dt = datetime.now()
                    
                    trade_pct_item = (dt_pnl / selected_acc_init) * 100 if selected_acc_init > 0 else 0.0
                    badge = "🟢" if dt_pnl >= 0 else "🔴"
                    header_str = f"{badge} Obchod #{dt_id} | Čas: {dt_time_str} | Pár: {dt_ticker} ({dt_dir}) | PnL: {dt_pnl:+,.2f} USD ({trade_pct_item:+.2f}%) | {dt_r} R"
                    
                    with st.expander(header_str):
                        # --- FORMULÁŘ PRO ÚPRAVU DATA, PnL A PARAMETRŮ OBCHODU ---
                        with st.form(key=f"edit_day_trade_{dt_id}"):
                            st.write("✏️ **Úprava detailů a data obchodu:**")
                            e_col1, e_col2, e_col3 = st.columns(3)
                            with e_col1:
                                new_trade_date = st.date_input("Datum obchodu", value=parsed_dt.date(), key=f"date_{dt_id}")
                                new_ticker = st.text_input("Ticker / Pár", value=dt_ticker, key=f"tck_{dt_id}")
                            with e_col2:
                                new_pnl = st.number_input("Zisk (+) / Ztráta (-) v penězích", value=float(dt_pnl), key=f"pnl_d_{dt_id}")
                                edit_pct = (new_pnl / selected_acc_init) * 100 if selected_acc_init > 0 else 0.0
                                st.caption(f"📊 Dopad: **{edit_pct:+.2f}%** z kapitálu")
                                new_r = st.number_input("Dosažené R", value=float(dt_r), key=f"r_d_{dt_id}")
                            with e_col3:
                                new_dir = st.selectbox("Směr", ["Long", "Short"], index=0 if dt_dir=="Long" else 1, key=f"dir_{dt_id}")
                                
                            update_full_btn = st.form_submit_button("💾 Uložit změny (včetně nového data)")
                            if update_full_btn:
                                original_time_part = parsed_dt.strftime("%H:%M")
                                new_full_datetime_str = f"{new_trade_date.strftime('%Y-%m-%d')} {original_time_part}"
                                
                                conn_upd = sqlite3.connect('trading_journal.db')
                                cur_upd = conn_upd.cursor()
                                cur_upd.execute('''
                                    UPDATE trades 
                                    SET entry_time = ?, ticker = ?, direction = ?, pnl_amount = ?, actual_r = ? 
                                    WHERE id = ?
                                ''', (new_full_datetime_str, new_ticker, new_dir, new_pnl, new_r, dt_id))
                                conn_upd.commit()
                                conn_upd.close()
                                st.success("Obchod byl úspěšně upraven a přesunut na nové datum!")
                                st.rerun()

                        st.markdown("---")
                        col_l, col_r = st.columns(2)
                        with col_l:
                            st.write(f"**Dopad na účet:** `{trade_pct_item:+.2f}%`")
                            st.write(f"**Fáze trhu:** `{dt.get('market_phase', 'N/A')}`")
                            st.write(f"- Generals' check: {'✅' if dt.get('htf_generals_check') else '❌'}")
                            st.write(f"- Engine MA Fan: {'✅' if dt.get('engine_ma_fan') else '❌'}")
                            st.write(f"- Signature: {'✅' if dt.get('signature_entry') else '❌'}")
                            st.write(f"- Zóna: {'✅' if dt.get('fresh_zone') else '❌'}")
                            st.write(f"- Inverted Chart: {'✅' if dt.get('inverted_chart') else '❌'}")
                            st.info(f"**Poznámka:** {dt.get('notes_emotions', 'Žádné poznámky')}")
                        
                        with col_r:
                            if dt.get('image_data') is not None:
                                try:
                                    img_obj = Image.open(io.BytesIO(dt['image_data']))
                                    st.image(img_obj, caption=f"Graf k obchodu #{dt_id}", use_container_width=True)
                                except Exception:
                                    st.caption("Obrázek se nepodařilo načíst.")
                            else:
                                st.caption("K tomuto obchodu není uložen hlavní screenshot.")
            else:
                st.info(f"Pro den {selected_detail_date.strftime('%d.%m.%Y')} nebyly zapsány žádné obchody.")
                
        # --- ZÁLOHA DAT (Tlačítko pro stažení) ---
        st.markdown("---")
        st.markdown("### 💾 Export a záloha dat")
        if not dash_trades.empty:
            csv_data = dash_trades.drop(columns=['image_data']).to_csv(index=False).encode('utf-8')
            st.download_button(
                label="⬇️ Stáhnout kompletní zálohu účtu v CSV (Excel)",
                data=csv_data,
                file_name=f'trading_backup_{dash_account_name}_{date.today()}.csv',
                mime='text/csv',
                help="Stáhne ti všechna data kromě obrázků pro další analýzu v Excelu."
            )
        else:
            st.info("Zatím nejsou zapsané žádné obchody pro export.")

# ==========================================
# ZÁLOŽKA 5: Ekonomický kalendář (CZ + Místní čas)
# ==========================================
with tab5:
    st.subheader("🌍 Živý ekonomický kalendář")
    st.write("Přehled makroekonomických zpráv v češtině, přizpůsobený na tvůj místní čas (Evropa/Praha).")
    
    calendar_html = """
    <div class="tradingview-widget-container">
      <div class="tradingview-widget-container__widget"></div>
      <script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-events.js" async>
      {
      "colorTheme": "dark",
      "isTransparent": true,
      "width": "100%",
      "height": "650",
      "locale": "cs",
      "importanceFilter": "-1,0,1",
      "currencyFilter": "USD,EUR,GBP,JPY,AUD,CAD,CHF,NZD",
      "timezone": "Europe/Prague"
    }
      </script>
    </div>
    """
    
    components.html(calendar_html, height=670)