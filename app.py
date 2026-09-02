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

# --- POMOCNÁ FUNKCE PRO MĚNOVÉ SYMBOLY ---
def get_sym(curr):
    if curr == "EUR": return "€"
    elif curr == "CZK": return "Kč"
    return "$"

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
    
    # Bezpečné rozšíření stávající databáze o nové sloupce
    # Pro zpětnou kompatibilitu se staršími obchody dáme status 'Closed' (uzavřeno)
    try: cursor.execute("ALTER TABLE trades ADD COLUMN status TEXT DEFAULT 'Closed';")
    except sqlite3.OperationalError: pass
    
    try: cursor.execute("ALTER TABLE trades ADD COLUMN risk_amount REAL DEFAULT 0.0;")
    except sqlite3.OperationalError: pass
    
    try: cursor.execute("ALTER TABLE trades ADD COLUMN sl_to_be BOOLEAN DEFAULT 0;")
    except sqlite3.OperationalError: pass
    
    try: cursor.execute("ALTER TABLE trades ADD COLUMN partials_log TEXT DEFAULT '';")
    except sqlite3.OperationalError: pass

    try: cursor.execute("ALTER TABLE trades ADD COLUMN account_id INTEGER;")
    except sqlite3.OperationalError: pass
        
    try: cursor.execute("ALTER TABLE trades ADD COLUMN inverted_chart BOOLEAN DEFAULT 0;")
    except sqlite3.OperationalError: pass
    
    try: cursor.execute("ALTER TABLE trades ADD COLUMN partial_pnl REAL DEFAULT 0.0;")
    except sqlite3.OperationalError: pass
    
    try: cursor.execute("ALTER TABLE accounts ADD COLUMN currency TEXT DEFAULT 'USD';")
    except sqlite3.OperationalError: pass
        
    try: cursor.execute("ALTER TABLE trades ADD COLUMN currency TEXT DEFAULT 'USD';")
    except sqlite3.OperationalError: pass

    try: cursor.execute("ALTER TABLE trades ADD COLUMN initial_lots REAL DEFAULT 0.0;")
    except sqlite3.OperationalError: pass
    
    try: cursor.execute("ALTER TABLE trades ADD COLUMN closed_lots REAL DEFAULT 0.0;")
    except sqlite3.OperationalError: pass
        
    conn.commit()
    conn.close()

init_db()

# --- 2. KONFIGURACE AI (Bezpečné načítání klíče ze schránky) ---
try:
    API_KEY = st.secrets["API_KEY"]
except Exception:
    API_KEY = ""

if API_KEY:
    genai.configure(api_key=API_KEY)
    model = genai.GenerativeModel('models/gemini-3.6-flash')
else:
    model = None

st.set_page_config(page_title="AI Trading Journal", layout="wide")

# CSS styly
st.markdown("""
    <style>
    .cal-card-green { background-color: rgba(46, 160, 67, 0.15); border: 1px solid #2ea043; border-radius: 8px; padding: 12px; text-align: center; height: 95px; margin-bottom: 8px; }
    .cal-card-red { background-color: rgba(218, 54, 51, 0.15); border: 1px solid #da3633; border-radius: 8px; padding: 12px; text-align: center; height: 95px; margin-bottom: 8px; }
    .cal-card-empty { background-color: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 12px; text-align: center; height: 95px; margin-bottom: 8px; opacity: 0.4; }
    .cal-day-header { font-weight: bold; text-align: center; color: #8b949e; padding-bottom: 5px; }
    .metric-card { background-color: #161b22; border: 1px solid #30363d; border-radius: 10px; padding: 18px; text-align: center; margin-bottom: 15px; }
    </style>
""", unsafe_allow_html=True)

st.title("📈 Můj AI Obchodní Deník")

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "➕ Nový obchod (Vstup)", 
    "⚙️ Řízení & Historie", 
    "💼 Správa účtů", 
    "📊 Dashboard & Kalendář",
    "🌍 Ekonomický kalendář"
])

# ==========================================
# ZÁLOŽKA 1: Nový obchod (Čistě vstup)
# ==========================================
with tab1:
    
    with st.expander("🧮 Kalkulačka velikosti pozice (Risk Management)"):
        c_col1, c_col2, c_col3, c_col4 = st.columns(4)
        with c_col1:
            calc_acc_bal = st.number_input("Zůstatek na účtu", value=200000.0, step=1000.0)
        with c_col2:
            calc_curr = st.selectbox("Měna kalkulačky", ["USD", "EUR", "CZK"])
        with c_col3:
            calc_risk_pct = st.number_input("Risk na obchod (%)", value=1.0, step=0.1)
        with c_col4:
            calc_sl_pips = st.number_input("Stop Loss (pips)", value=10.0, step=1.0)
        
        risk_amt = calc_acc_bal * (calc_risk_pct / 100)
        if calc_sl_pips > 0:
            calc_lots = risk_amt / (calc_sl_pips * 10)
            st.info(f"🛡️ **Riskovaná částka:** `{get_sym(calc_curr)}{risk_amt:,.2f}` | 📉 **Doporučená velikost pozice:** `{calc_lots:.2f} Lotů`")
    
    st.markdown("---")
    st.write(" Nahraj screenshot grafu a zadej parametry svého **vstupu do obchodu**. Žádné R ani PnL zde ještě nezadáváš – obchod se uloží jako **Otevřený** a budeš ho moci řídit v další záložce.")
    
    conn = sqlite3.connect('trading_journal.db')
    accounts_df = pd.read_sql_query("SELECT id, name, initial_balance, COALESCE(currency, 'USD') as currency FROM accounts", conn)
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
        st.subheader("📝 Vstupní detaily obchodu")
        
        with st.form("trade_entry_form"):
            account_options = {f"{str(name).strip()} ({curr})": (acc_id, init_bal, curr) for name, acc_id, init_bal, curr in zip(accounts_df['name'], accounts_df['id'], accounts_df['initial_balance'], accounts_df['currency'])}
            selected_account_name = st.selectbox("Obchodní účet", list(account_options.keys()))
            selected_acc_id, selected_acc_init, selected_acc_curr = account_options[selected_account_name]
            
            c1, c2, c3 = st.columns(3)
            with c1:
                ticker = st.text_input("Ticker / Pár", value="GBP/JPY")
                direction = st.selectbox("Směr", ["Long", "Short"])
            with c2:
                risk_input = st.number_input("Riskovaná částka", value=2000.0, step=100.0)
                lots_input = st.number_input("Celková velikost pozice (Loty)", value=15.0, step=0.1)
            with c3:
                curr_list = ["USD", "EUR", "CZK"]
                def_idx = curr_list.index(selected_acc_curr) if selected_acc_curr in curr_list else 0
                trade_currency = st.selectbox("Měna obchodu", curr_list, index=def_idx)
                
            st.markdown("---")
            htf_check = st.checkbox("Generals' check (EMA 5, 10, 20 & daily MB)", value=data.get("htf_context", False))
            market_phase = st.text_input("Fáze trhu", value=data.get("market_phase", "Contain line"))
            engine_check = st.checkbox("Engine check (MA Fan tyrkysová/červená/modrá)", value=data.get("engine_ma_fan", False))
            signature_check = st.checkbox("Signature search (MB1 -> Flush -> MB2)", value=data.get("signature_entry", False))
            zone_check = st.checkbox("Zone qualification (Fresh & Swept liquidity)", value=data.get("zone_qualified", False))
            
            st.markdown("---")
            inverted_chart_check = st.checkbox("🔄 Inverted chart setup (Byl analyzován přes obrácený graf?)", value=False)
            notes = st.text_area("Psychologie a poznámky k VSTUPU", value="Vstup přesně podle plánu.")
            
            submit_entry = st.form_submit_button(label="🚀 Otevřít obchod (Uložit pro následné řízení)")
            
            if submit_entry:
                conn = sqlite3.connect('trading_journal.db')
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO trades (
                        account_id, ticker, direction, entry_time, actual_r, pnl_amount,
                        htf_generals_check, market_phase, engine_ma_fan, 
                        signature_entry, fresh_zone, notes_emotions, image_data, inverted_chart, 
                        partial_pnl, currency, initial_lots, closed_lots, status, risk_amount, sl_to_be, partials_log
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    selected_acc_id, ticker, direction, datetime.now().strftime("%Y-%m-%d %H:%M"), 
                    0.0, 0.0,  # Zpočátku nulové R a nulový finální PnL
                    htf_check, market_phase, engine_check, signature_check, 
                    zone_check, notes, st.session_state.saved_image_bytes, inverted_chart_check, 
                    0.0, trade_currency, lots_input, 0.0, 'Open', risk_input, 0, ""
                ))
                conn.commit()
                conn.close()
                st.success("🎉 Obchod otevřen! Najdeš ho v záložce 'Řízení & Historie' pod Otevřenými obchody.")

# ==========================================
# ZÁLOŽKA 2: Řízení & Historie
# ==========================================
with tab2:
    
    conn = sqlite3.connect('trading_journal.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT t.id, a.name, a.initial_balance, t.ticker, t.direction, t.entry_time, 
               t.actual_r, t.pnl_amount, t.htf_generals_check, t.market_phase, t.engine_ma_fan, 
               t.signature_entry, t.fresh_zone, t.notes_emotions, t.image_data, t.account_id, t.inverted_chart, 
               COALESCE(t.partial_pnl, 0.0), COALESCE(t.currency, 'USD'), COALESCE(t.initial_lots, 0.0), 
               COALESCE(t.closed_lots, 0.0), COALESCE(t.status, 'Closed'), COALESCE(t.risk_amount, 0.0), 
               COALESCE(t.sl_to_be, 0), COALESCE(t.partials_log, '')
        FROM trades t
        LEFT JOIN accounts a ON t.account_id = a.id
        ORDER BY t.id DESC
    ''')
    trades = cursor.fetchall()
    conn.close()

    conn = sqlite3.connect('trading_journal.db')
    acc_filter_df = pd.read_sql_query("SELECT name FROM accounts", conn)
    conn.close()
    
    account_list = ["Všechny účty"] + [str(n).strip() for n in acc_filter_df['name']]
    col_f1, col_f2 = st.columns([1,2])
    with col_f1:
        selected_filter = st.selectbox("Filtrovat účet", account_list, key="hist_filter")
    
    filtered_trades = trades if selected_filter == "Všechny účty" else [t for t in trades if t[1] and str(t[1]).strip() == selected_filter]
    
    open_trades = [t for t in filtered_trades if t[21] == 'Open']
    closed_trades = [t for t in filtered_trades if t[21] == 'Closed']
    
    # --- SEKCE A: OTEVŘENÉ OBCHODY ---
    st.markdown("---")
    st.markdown("### 🔥 Aktivní / Otevřené Obchody (Řízení pozice)")
    
    if not open_trades:
        st.info("Momentálně nemáš žádné otevřené obchody.")
    else:
        for t in open_trades:
            (t_id, t_acc_name, t_acc_init, t_ticker, t_dir, t_time, t_r, t_pnl, 
             t_htf, t_phase, t_eng, t_sig, t_zone, t_notes, t_img, t_acc_id, t_inv, 
             t_part_pnl, t_curr, t_init_lots, t_closed_lots, t_status, t_risk, t_sl_be, t_part_log) = t
            
            clean_acc_name = str(t_acc_name).strip() if t_acc_name else "Neznámý účet"
            rem_lots = t_init_lots - t_closed_lots
            sym = get_sym(t_curr)
            
            header = f"🟡 #{t_id} [{clean_acc_name}] | {t_time} | {t_ticker} ({t_dir}) | Zbývá: {rem_lots:g} z {t_init_lots:g} Lotů | Zajištěno: {sym}{t_part_pnl:+,.2f}"
            
            with st.expander(header):
                
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Původní Risk", f"{sym}{t_risk:,.2f}")
                m2.metric("Vstupní Loty", f"{t_init_lots:g}")
                m3.metric("Zbývající Loty", f"{rem_lots:g}")
                m4.metric("Zajištěný Zisk", f"{sym}{t_part_pnl:,.2f}")
                
                st.markdown("---")
                col_mng1, col_mng2 = st.columns(2)
                
                with col_mng1:
                    st.markdown("#### ✂️ Vybrat Partial")
                    with st.form(f"partial_form_{t_id}"):
                        p_lots = st.number_input(f"Kolik lotů chceš zavřít? (Max {rem_lots:g})", min_value=0.01, max_value=float(rem_lots) if rem_lots > 0 else 0.01, step=0.1)
                        p_money = st.number_input(f"Zisk/Ztráta z tohoto partialu ({t_curr})", value=0.0)
                        submit_p = st.form_submit_button("Potvrdit výběr Partialu")
                        
                        if submit_p:
                            new_closed = t_closed_lots + p_lots
                            new_part_pnl = t_part_pnl + p_money
                            now_str = datetime.now().strftime("%d.%m. %H:%M")
                            log_entry = f"[{now_str}] Vybráno {p_lots} lotů | Hodnota: {p_money:+.2f} {t_curr}\n"
                            new_log = t_part_log + log_entry
                            
                            conn_p = sqlite3.connect('trading_journal.db')
                            c_p = conn_p.cursor()
                            c_p.execute("UPDATE trades SET closed_lots = ?, partial_pnl = ?, partials_log = ? WHERE id = ?", (new_closed, new_part_pnl, new_log, t_id))
                            conn_p.commit()
                            conn_p.close()
                            st.success("Partial uložen!")
                            st.rerun()
                            
                    st.markdown("#### 🛡️ Řízení rizika")
                    sl_state_str = "✅ Posunut" if t_sl_be else "❌ Na původní hodnotě"
                    st.write(f"Stop Loss na BE: **{sl_state_str}**")
                    if st.button("Přepnout stav SL (na BE / Původní)", key=f"be_btn_{t_id}"):
                        new_be_state = 0 if t_sl_be else 1
                        conn_be = sqlite3.connect('trading_journal.db')
                        c_be = conn_be.cursor()
                        c_be.execute("UPDATE trades SET sl_to_be = ? WHERE id = ?", (new_be_state, t_id))
                        conn_be.commit()
                        conn_be.close()
                        st.rerun()

                with col_mng2:
                    st.markdown("#### 🏁 Kompletně Uzavřít Obchod")
                    st.info("Když zavřeš zbytek pozice (nebo Tě vyhodí na SL/BE/TP), doplň sem finální čísla pro zařazení do statistik.")
                    with st.form(f"close_form_{t_id}"):
                        f_pnl = st.number_input(f"Zisk/Ztráta ze ZBYTKU pozice ({t_curr})", value=0.0)
                        f_r = st.number_input("Konečné dosažené R (např. 2.5)", value=0.0)
                        submit_c = st.form_submit_button("Uzavřít celý obchod")
                        
                        if submit_c:
                            conn_c = sqlite3.connect('trading_journal.db')
                            c_c = conn_c.cursor()
                            c_c.execute("UPDATE trades SET status = 'Closed', pnl_amount = ?, actual_r = ? WHERE id = ?", (f_pnl, f_r, t_id))
                            conn_c.commit()
                            conn_c.close()
                            st.success("Obchod přesunut do Historie!")
                            st.rerun()
                            
                    if t_part_log:
                        st.markdown("**Deník Partials:**")
                        st.text(t_part_log)

                if st.button("🗑️ Smazat tento otevřený obchod (Zrušit)", key=f"del_open_{t_id}"):
                    conn_d = sqlite3.connect('trading_journal.db')
                    c_d = conn_d.cursor()
                    c_d.execute("DELETE FROM trade_images WHERE trade_id = ?", (t_id,))
                    c_d.execute("DELETE FROM trades WHERE id = ?", (t_id,))
                    conn_d.commit()
                    conn_d.close()
                    st.rerun()

    # --- SEKCE B: UZAVŘENÉ OBCHODY ---
    st.markdown("---")
    st.markdown("### 📚 Historie Uzavřených Obchodů")
    
    if not closed_trades:
        st.info("Zatím nemáš žádné uzavřené obchody.")
    else:
        for t in closed_trades:
            (t_id, t_acc_name, t_acc_init, t_ticker, t_dir, t_time, t_r, t_pnl, 
             t_htf, t_phase, t_eng, t_sig, t_zone, t_notes, t_img, t_acc_id, t_inv, 
             t_part_pnl, t_curr, t_init_lots, t_closed_lots, t_status, t_risk, t_sl_be, t_part_log) = t
            
            clean_acc_name = str(t_acc_name).strip() if t_acc_name else "Neznámý účet"
            init_b = t_acc_init if t_acc_init and t_acc_init > 0 else 200000.0
            
            total_trade_pnl = t_pnl + t_part_pnl
            trade_pct = (total_trade_pnl / init_b) * 100
            sym = get_sym(t_curr)
            
            badge = "🟢" if total_trade_pnl >= 0 else "🔴"
            header = f"{badge} #{t_id} [{clean_acc_name}] | {t_time} | {t_ticker} ({t_dir}) | Celkový PnL: {sym}{total_trade_pnl:+,.2f} ({trade_pct:+.2f}%) | {t_r} R"
            
            with st.expander(header):
                if st.button("🗑️ Smazat tento obchod natrvalo", key=f"del_hist_{t_id}"):
                    conn_d = sqlite3.connect('trading_journal.db')
                    c_d = conn_d.cursor()
                    c_d.execute("DELETE FROM trade_images WHERE trade_id = ?", (t_id,))
                    c_d.execute("DELETE FROM trades WHERE id = ?", (t_id,))
                    conn_d.commit()
                    conn_d.close()
                    st.rerun()
                    
                col_left, col_right = st.columns([1, 1])
                
                with col_left:
                    st.markdown("### 📋 Výsledek a parametry")
                    st.write(f"**Hlavní PnL ze zbytku:** {sym}{t_pnl:,.2f}")
                    st.write(f"**Zisk z Partials:** {sym}{t_part_pnl:,.2f}")
                    if t_part_log:
                        st.write("**Log Partials:**")
                        st.text(t_part_log)
                        
                    st.write("---")
                    st.write(f"**Fáze trhu:** `{t_phase}`")
                    st.write(f"- Generals' check: {'✅ Splněno' if t_htf else '❌ Nesplněno'}")
                    st.write(f"- Engine MA Fan: {'✅ Splněno' if t_eng else '❌ Nesplněno'}")
                    st.write(f"- Signature: {'✅ Splněno' if t_sig else '❌ Nesplněno'}")
                    st.write(f"- Kvalifikace zóny: {'✅ Splněno' if t_zone else '❌ Nesplněno'}")
                    st.write(f"- Inverted Chart: {'✅ Použito' if t_inv else '❌ Běžný graf'}")
                    st.info(f"**Poznámky ke vstupu:** {t_notes}")
                
                with col_right:
                    st.markdown("### 🖼️ Galerie obrázků")
                    if t_img is not None:
                        img_obj = Image.open(io.BytesIO(t_img))
                        st.image(img_obj, caption=f"Vstupní graf #{t_id}", use_container_width=True)
                    else:
                        st.caption("Hlavní screenshot nebyl uložen.")
                    
                    conn_img = sqlite3.connect('trading_journal.db')
                    cursor_img = conn_img.cursor()
                    cursor_img.execute("SELECT id, image_data FROM trade_images WHERE trade_id = ?", (t_id,))
                    extra_images = cursor_img.fetchall()
                    conn_img.close()
                    
                    if extra_images:
                        st.write("---")
                        st.write("**Dodatečné screenshoty (např. výstup):**")
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
            col_a1, col_a2, col_a3 = st.columns(3)
            with col_a1:
                acc_name = st.text_input("Název účtu (např. Mentfunding)")
            with col_a2:
                acc_initial = st.number_input("Základní / Počáteční kapitál", value=200000.0)
            with col_a3:
                acc_currency = st.selectbox("Měna účtu", ["USD", "EUR", "CZK"])
                
            acc_submit = st.form_submit_button("Vytvořit účet")
            if acc_submit:
                clean_name = acc_name.strip()
                if clean_name == "":
                    st.error("Zadej platný název účtu!")
                else:
                    try:
                        conn = sqlite3.connect('trading_journal.db')
                        cursor = conn.cursor()
                        cursor.execute("INSERT INTO accounts (name, initial_balance, currency) VALUES (?, ?, ?)", (clean_name, acc_initial, acc_currency))
                        conn.commit()
                        conn.close()
                        st.success(f"Účet '{clean_name}' byl úspěšně vytvořen v {acc_currency}!")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error("Účet s tímto názvem již existuje!")

    st.markdown("---")
    st.subheader("📊 Seznam účtů a úprava základů")
    
    conn = sqlite3.connect('trading_journal.db')
    accounts_summary_query = '''
        SELECT a.id, a.name, a.initial_balance, COALESCE(a.currency, 'USD') as currency,
               COALESCE(SUM(t.pnl_amount + COALESCE(t.partial_pnl, 0.0)), 0) as total_pnl,
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
            acc_curr = row['currency']
            total_pnl = row['total_pnl']
            calculated_balance = current_initial + total_pnl
            sym = get_sym(acc_curr)
            
            with st.container():
                st.markdown(f"### 🏦 Účet: {acc_name} ({acc_curr})")
                col_m1, col_m2, col_m3, col_m4 = st.columns(4)
                col_m1.metric("Základní vklad", f"{sym}{current_initial:,.2f}")
                col_m2.metric("Celkový PnL (vč. Otevřených)", f"{sym}{total_pnl:+,.2f}")
                col_m3.metric("Aktuální stav", f"{sym}{calculated_balance:,.2f}")
                col_m4.metric("Počet obchodů", row['trade_count'])
                
                with st.form(key=f"edit_acc_{acc_id}"):
                    c_ed1, c_ed2 = st.columns(2)
                    with c_ed1:
                        new_base = st.number_input(f"Upravit základ:", value=float(current_initial), key=f"val_{acc_id}")
                    with c_ed2:
                        curr_opts = ["USD", "EUR", "CZK"]
                        new_acc_curr = st.selectbox("Změnit měnu účtu:", curr_opts, index=curr_opts.index(acc_curr) if acc_curr in curr_opts else 0, key=f"curr_acc_{acc_id}")
                    
                    update_btn = st.form_submit_button(f"💾 Uložit změny pro {acc_name}")
                    if update_btn:
                        conn_up = sqlite3.connect('trading_journal.db')
                        cursor_up = conn_up.cursor()
                        cursor_up.execute("UPDATE accounts SET initial_balance = ?, currency = ? WHERE id = ?", (new_base, new_acc_curr, acc_id))
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
    acc_dash_df = pd.read_sql_query("SELECT id, name, initial_balance, COALESCE(currency, 'USD') as currency FROM accounts", conn)
    conn.close()
    
    if acc_dash_df.empty:
        st.info("Nejprve si vytvoř alespoň jeden účet v záložce 'Správa účtů'.")
    else:
        acc_dash_df['clean_name'] = acc_dash_df['name'].str.strip()
        dash_account_name = st.selectbox("Vyber účet pro zobrazení detailu", acc_dash_df['clean_name'], key="dash_acc_select")
        
        selected_acc_row = acc_dash_df[acc_dash_df['clean_name'] == dash_account_name].iloc[0]
        selected_acc_id = selected_acc_row['id']
        selected_acc_init = selected_acc_row['initial_balance']
        selected_acc_curr = selected_acc_row['currency']
        sym = get_sym(selected_acc_curr)
        
        conn_d = sqlite3.connect('trading_journal.db')
        dash_trades = pd.read_sql_query(
            "SELECT id, ticker, direction, entry_time, actual_r, pnl_amount, htf_generals_check, market_phase, engine_ma_fan, signature_entry, fresh_zone, notes_emotions, image_data, inverted_chart, COALESCE(initial_lots, 0.0) as initial_lots, COALESCE(closed_lots, 0.0) as closed_lots, COALESCE(partial_pnl, 0.0) as partial_pnl, COALESCE(currency, 'USD') as currency, COALESCE(status, 'Closed') as status FROM trades WHERE account_id = ? ORDER BY id ASC", 
            conn_d, params=(selected_acc_id,)
        )
        if dash_trades.empty:
            fallback_query = '''
                SELECT t.id, t.ticker, t.direction, t.entry_time, t.actual_r, t.pnl_amount, t.htf_generals_check, t.market_phase, t.engine_ma_fan, t.signature_entry, t.fresh_zone, t.notes_emotions, t.image_data, t.inverted_chart, COALESCE(t.initial_lots, 0.0) as initial_lots, COALESCE(t.closed_lots, 0.0) as closed_lots, COALESCE(t.partial_pnl, 0.0) as partial_pnl, COALESCE(t.currency, 'USD') as currency, COALESCE(t.status, 'Closed') as status
                FROM trades t
                LEFT JOIN accounts a ON t.account_id = a.id
                WHERE TRIM(a.name) = ? ORDER BY t.id ASC
            '''
            dash_trades = pd.read_sql_query(fallback_query, conn_d, params=(dash_account_name,))
        conn_d.close()
        
        # Filtrování pro statistiky - metriky (Rko, WinRate) počítáme jen z UZAVŘENÝCH obchodů
        closed_dash_trades = dash_trades[dash_trades['status'] == 'Closed'].copy()
        total_closed_trades = len(closed_dash_trades)
        
        if not dash_trades.empty:
            dash_trades['total_trade_pnl'] = dash_trades['pnl_amount'] + dash_trades['partial_pnl'].fillna(0)
            total_pnl_all = dash_trades['total_trade_pnl'].sum() # Včetně otevřených partials
        else:
            total_pnl_all = 0.0
            
        if not closed_dash_trades.empty:
            closed_dash_trades['total_trade_pnl'] = closed_dash_trades['pnl_amount'] + closed_dash_trades['partial_pnl'].fillna(0)
            winning_trades = closed_dash_trades[closed_dash_trades['total_trade_pnl'] > 0]
            losing_trades = closed_dash_trades[closed_dash_trades['total_trade_pnl'] < 0]
            
            win_rate = (len(winning_trades) / total_closed_trades) * 100 if total_closed_trades > 0 else 0
            avg_win = winning_trades['total_trade_pnl'].mean() if not winning_trades.empty else 0.0
            avg_loss = losing_trades['total_trade_pnl'].mean() if not losing_trades.empty else 0.0
            best_trade = closed_dash_trades['total_trade_pnl'].max() if not closed_dash_trades.empty else 0.0
            worst_trade = closed_dash_trades['total_trade_pnl'].min() if not closed_dash_trades.empty else 0.0
        else:
            win_rate = 0.0; avg_win = 0.0; avg_loss = 0.0; best_trade = 0.0; worst_trade = 0.0
            
        current_equity = selected_acc_init + total_pnl_all
        total_pct_return = (total_pnl_all / selected_acc_init) * 100 if selected_acc_init > 0 else 0.0
        
        st.markdown("---")
        d1, d2, d3, d4 = st.columns(4)
        d1.metric("Net PnL (Účet)", f"{sym}{total_pnl_all:,.2f} ({total_pct_return:+.2f}%)")
        d2.metric("Aktuální stav účtu", f"{sym}{current_equity:,.2f}")
        d3.metric("Win Rate (Uzavřené)", f"{win_rate:.1f}%")
        d4.metric("Uzavřených obchodů", total_closed_trades)
        
        # --- KARIÉRNÍ KARTY ---
        st.markdown("### 🏆 Detailní statistiky výkonu (z Uzavřených obchodů)")
        c1, c2, c3, c4 = st.columns(4)
        
        with c1:
            st.markdown(f"""
                <div class="metric-card">
                    <div style="font-size: 13px; color: #8b949e; font-weight: bold;">Průměrný zisk (Avg Win)</div>
                    <div style="font-size: 20px; font-weight: bold; color: #2ea043; margin-top: 6px;">{sym}{avg_win:,.2f}</div>
                    <div style="font-size: 11px; color: #8b949e;">({(avg_win/selected_acc_init)*100:+.2f}% kapitálu)</div>
                </div>
            """, unsafe_allow_html=True)
            
        with c2:
            st.markdown(f"""
                <div class="metric-card">
                    <div style="font-size: 13px; color: #8b949e; font-weight: bold;">Průměrná ztráta (Avg Loss)</div>
                    <div style="font-size: 20px; font-weight: bold; color: #da3633; margin-top: 6px;">{sym}{avg_loss:,.2f}</div>
                    <div style="font-size: 11px; color: #8b949e;">({(avg_loss/selected_acc_init)*100:+.2f}% kapitálu)</div>
                </div>
            """, unsafe_allow_html=True)
            
        with c3:
            st.markdown(f"""
                <div class="metric-card">
                    <div style="font-size: 13px; color: #8b949e; font-weight: bold;">Nejlepší obchod (Best Trade)</div>
                    <div style="font-size: 20px; font-weight: bold; color: #2ea043; margin-top: 6px;">{sym}{best_trade:,.2f}</div>
                    <div style="font-size: 11px; color: #8b949e;">({(best_trade/selected_acc_init)*100:+.2f}% kapitálu)</div>
                </div>
            """, unsafe_allow_html=True)
            
        with c4:
            st.markdown(f"""
                <div class="metric-card">
                    <div style="font-size: 13px; color: #8b949e; font-weight: bold;">Nejhorší obchod (Worst Trade)</div>
                    <div style="font-size: 20px; font-weight: bold; color: #da3633; margin-top: 6px;">{sym}{worst_trade:,.2f}</div>
                    <div style="font-size: 11px; color: #8b949e;">({(worst_trade/selected_acc_init)*100:+.2f}% kapitálu)</div>
                </div>
            """, unsafe_allow_html=True)
            
        st.markdown("---")
        
        # --- POKROČILÉ GRAFY ---
        if total_closed_trades > 0:
            st.markdown("### 🎯 Detailní Win-Rate a rozložení obchodů")
            graph_c1, graph_c2 = st.columns(2)
            
            with graph_c1:
                pair_stats = closed_dash_trades.groupby('ticker').apply(
                    lambda x: pd.Series({'Wins': (x['total_trade_pnl'] > 0).sum(), 'Losses': (x['total_trade_pnl'] <= 0).sum()})
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
                dir_stats = closed_dash_trades.groupby('direction')['id'].count().reset_index()
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
            if model and total_closed_trades > 0:
                with st.spinner("AI analyzuje tvá data a hledá klíčové patterny pro vylepšení..."):
                    recent_trades = closed_dash_trades.tail(20)
                    data_str = recent_trades[['ticker', 'direction', 'actual_r', 'total_trade_pnl', 'currency', 'htf_generals_check', 'engine_ma_fan', 'inverted_chart']].to_json(orient='records')
                    
                    prompt_coach = f"""
                    Jsi profesionální trading kouč zaměřený na strategii MentFX. Analyzuj těchto posledních pár uzavřených obchodů klienta (data v JSON: {data_str}).
                    Tvůj úkol:
                    1. Dej mu stručnou, údernou a motivační zpětnou vazbu v češtině.
                    2. Vypíchni, co funguje dobře (např. dodržování pravidel jako MA fan).
                    3. Upozorni na to, kde ztrácí.
                    4. Zhodnoť také vliv použití 'inverted_chart' (obráceného grafu).
                    Max 3-4 odstavce.
                    """
                    try:
                        resp = model.generate_content(prompt_coach)
                        st.info(resp.text)
                    except Exception as e:
                        st.error(f"Chyba při komunikaci s AI: {e}")
            else:
                st.warning("Potřebuješ alespoň 1 UZAVŘENÝ obchod a nastavený API klíč, aby mohl kouč fungovat.")
        st.markdown("---")
        
        # --- HLADKÁ ZAOBLENÁ PLOTLY EQUITY KŘIVKA (SPLINE) ---
        if not closed_dash_trades.empty:
            
            closed_dash_trades['date_parsed'] = pd.to_datetime(closed_dash_trades['entry_time'])
            closed_dash_trades = closed_dash_trades.sort_values('date_parsed', ascending=True).reset_index(drop=True)
            closed_dash_trades['cumulative_pnl'] = closed_dash_trades['total_trade_pnl'].cumsum()
            
            x_vals = ['Start'] + [f"Obchod #{i+1} ({t.strftime('%d.%m.')})" for i, t in enumerate(closed_dash_trades['date_parsed'])]
            y_vals = [0.0] + closed_dash_trades['cumulative_pnl'].tolist()
            
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
                title=f"Equity Křivka účtu z Uzavřených obchodů: {dash_account_name}",
                template='plotly_dark',
                margin=dict(l=20, r=20, t=40, b=20),
                height=350,
                xaxis=dict(title='Časová osa uzavřených obchodů'),
                yaxis=dict(title=f'Kumulativní PnL ({sym})')
            )
            st.plotly_chart(fig, use_container_width=True)
            st.markdown("---")
        
        # Zpracování dat pro mřížku kalendáře
        if 'cal_year' not in st.session_state:
            st.session_state.cal_year = date.today().year
        if 'cal_month' not in st.session_state:
            st.session_state.cal_month = date.today().month

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

        if not closed_dash_trades.empty:
            daily_agg = closed_dash_trades.groupby(closed_dash_trades['date_parsed'].dt.date).agg(
                daily_pnl=('total_trade_pnl', 'sum'),
                trade_count=('id', 'count'),
                wins=('total_trade_pnl', lambda x: (x > 0).sum())
            ).reset_index()
            daily_agg['win_rate'] = (daily_agg['wins'] / daily_agg['trade_count']) * 100
            pnl_by_date = {row['date_parsed']: row for _, row in daily_agg.iterrows()}
        else:
            pnl_by_date = {}

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
                            znamenko = "+" if dpnl >= 0 else ""
                            
                            st.markdown(f"""
                                <div class="{card_class}">
                                    <div style="font-size: 12px; color: #8b949e; font-weight: bold;">{formatted_date_cz}</div>
                                    <div style="font-size: 17px; font-weight: bold; margin: 4px 0;">{znamenko}{sym}{dpnl:,.2f}</div>
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

        # --- ZÁLOHA DAT (Tlačítko pro stažení) ---
        st.markdown("---")
        st.markdown("### 💾 Export a záloha dat")
        if not dash_trades.empty:
            csv_data = dash_trades.drop(columns=['image_data']).to_csv(index=False).encode('utf-8')
            st.download_button(
                label="⬇️ Stáhnout kompletní zálohu účtu v CSV (Excel)",
                data=csv_data,
                file_name=f'trading_backup_{dash_account_name}_{date.today()}.csv',
                mime='text/csv'
            )

# ==========================================
# ZÁLOŽKA 5: Ekonomický kalendář
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