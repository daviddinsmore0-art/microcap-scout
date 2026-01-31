import streamlit as st
import mysql.connector
import yfinance as yf
import requests
import uuid
import os
import pandas as pd
import pytz
from datetime import datetime, timedelta

# 1. CONFIG & DATABASE
st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="centered", initial_sidebar_state="collapsed")

DB_CONFIG = {
    "host": "atlanticcanadaschoice.com",
    "user": "atlantic",                 
    "password": "1q2w3e4R!!",   
    "database": "atlantic_pennypulse",    
    "connect_timeout": 30,
}

def get_connection():
    return mysql.connector.connect(**DB_CONFIG)

def init_db():
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""CREATE TABLE IF NOT EXISTS user_profiles (
            username VARCHAR(255) PRIMARY KEY, 
            pin VARCHAR(50),
            display_name VARCHAR(100),
            email VARCHAR(255),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )""")
        
        cursor.execute("CREATE TABLE IF NOT EXISTS user_sessions (token VARCHAR(255) PRIMARY KEY, username VARCHAR(255), created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
        cursor.execute("CREATE TABLE IF NOT EXISTS user_portfolio (id INT NOT NULL AUTO_INCREMENT, username VARCHAR(255), ticker VARCHAR(20), PRIMARY KEY (id))")
        
        cursor.execute("""CREATE TABLE IF NOT EXISTS user_alerts (
            id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(255),
            ticker VARCHAR(20),
            condition_type VARCHAR(10), 
            target_price DECIMAL(20, 4),
            is_triggered BOOLEAN DEFAULT FALSE,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )""")

        sql = """CREATE TABLE IF NOT EXISTS stock_cache (
            ticker VARCHAR(20) PRIMARY KEY, 
            current_price DECIMAL(20, 4), day_change DECIMAL(10, 2), rsi DECIMAL(10, 2), 
            trend_status VARCHAR(20), volume_status VARCHAR(20), range_loc DECIMAL(10, 2),
            volatility DECIMAL(10, 2), debt_ratio DECIMAL(10, 2), days_to_earnings INT,
            market_cap BIGINT, eps DECIMAL(10, 2),
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        )"""
        cursor.execute(sql)
        
        # Silent Migrations
        try: cursor.execute("ALTER TABLE user_profiles ADD COLUMN display_name VARCHAR(100)")
        except: pass
        try: cursor.execute("ALTER TABLE user_profiles ADD COLUMN email VARCHAR(255)")
        except: pass
        try: cursor.execute("ALTER TABLE stock_cache ADD COLUMN market_cap BIGINT DEFAULT 0")
        except: pass
        try: cursor.execute("ALTER TABLE stock_cache ADD COLUMN eps DECIMAL(10, 2) DEFAULT 0")
        except: pass
        try: cursor.execute("ALTER TABLE stock_cache ADD COLUMN days_to_earnings INT DEFAULT 999")
        except: pass
            
        conn.close()
    except Exception as e:
        st.error(f"DB Error: {e}")

# 2. DATA ENGINE
def check_alerts(username):
    conn = get_connection(); cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM user_alerts WHERE username = %s AND is_triggered = FALSE", (username,))
    alerts = cursor.fetchall()
    if not alerts: conn.close(); return

    triggered_count = 0
    for alert in alerts:
        cursor.execute("SELECT day_change FROM stock_cache WHERE ticker = %s", (alert['ticker'],))
        stock = cursor.fetchone()
        if stock:
            pct_move = float(stock['day_change'])
            target_pct = float(alert['target_price']) 
            condition = alert['condition_type'] 
            hit = False
            if condition == 'UP' and pct_move >= target_pct: hit = True
            elif condition == 'DOWN' and pct_move <= (target_pct * -1): hit = True
            if hit:
                cursor.execute("UPDATE user_alerts SET is_triggered = TRUE WHERE id = %s", (alert['id'],))
                triggered_count += 1
    conn.commit(); conn.close()
    return triggered_count

def update_stock_data(tickers, username):
    if not tickers: return
    try: data = yf.download(" ".join(tickers), period="3mo", group_by='ticker', threads=True, progress=False)
    except: return

    conn = get_connection(); cursor = conn.cursor()
    finnhub_key = None
    if "finnhub" in st.secrets and "api_key" in st.secrets["finnhub"]:
        finnhub_key = st.secrets["finnhub"]["api_key"]
    
    for t in tickers:
        try:
            if len(tickers) > 1: df = data[t]
            else: df = data
            df = df.dropna()
            if df.empty: continue

            price = float(df['Close'].iloc[-1]); prev = float(df['Close'].iloc[-2]); change = ((price - prev) / prev) * 100
            delta = df['Close'].diff(); up, down = delta.clip(lower=0), -1 * delta.clip(upper=0)
            rs = up.ewm(com=13, adjust=False).mean() / down.ewm(com=13, adjust=False).mean()
            rsi = 100 - (100 / (1 + rs)).iloc[-1]
            ma50 = df['Close'].rolling(50).mean().iloc[-1]; trend = "UPTREND" if price > ma50 else "DOWNTREND"
            volatility = df['Close'].pct_change().std() * 100
            high_3m = df['Close'].max(); low_3m = df['Close'].min(); range_loc = 50
            if high_3m != low_3m: range_loc = ((price - low_3m) / (high_3m - low_3m)) * 100
            avg_vol = df['Volume'].rolling(20).mean().iloc[-1]; curr_vol = df['Volume'].iloc[-1]
            vol_stat = "SPIKE" if curr_vol > (avg_vol * 1.5) else "NORMAL"

            debt_ratio = 0; market_cap = 0; eps = 0; days_to_earnings = 999 
            finnhub_success = False
            if finnhub_key:
                try:
                    start_date = datetime.now().strftime('%Y-%m-%d'); end_date = (datetime.now() + timedelta(days=90)).strftime('%Y-%m-%d')
                    url = f"https://finnhub.io/api/v1/calendar/earnings?from={start_date}&to={end_date}&symbol={t}&token={finnhub_key}"
                    r = requests.get(url).json()
                    if "earningsCalendar" in r and len(r["earningsCalendar"]) > 0:
                        earnings_list = r["earningsCalendar"]; earnings_list.sort(key=lambda x: x['date'])
                        next_date = datetime.strptime(earnings_list[0]['date'], '%Y-%m-%d')
                        delta = (next_date - datetime.now()).days
                        if delta >= 0: days_to_earnings = delta; finnhub_success = True
                except: pass

            if not finnhub_success:
                try:
                    ticker_obj = yf.Ticker(t); info = ticker_obj.info
                    debt_ratio = info.get('debtToEquity', 0) or 0; market_cap = info.get('marketCap', 0) or 0; eps = info.get('trailingEps', 0) or 0
                    cal = ticker_obj.calendar
                    if cal is not None and not cal.empty:
                        if isinstance(cal, pd.DataFrame): earnings_date = cal.iloc[0, 0]
                        elif isinstance(cal, dict): earnings_date = cal.get('Earnings Date', [None])[0]
                        else: earnings_date = None
                        if isinstance(earnings_date, (datetime, pd.Timestamp)):
                             delta_days = (earnings_date - datetime.now()).days
                             if delta_days >= 0: days_to_earnings = delta_days
                except: pass 

            sql = """INSERT INTO stock_cache 
                     (ticker, current_price, day_change, rsi, trend_status, volume_status, range_loc, volatility, debt_ratio, days_to_earnings, market_cap, eps) 
                     VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) 
                     ON DUPLICATE KEY UPDATE 
                     current_price=%s, day_change=%s, rsi=%s, trend_status=%s, volume_status=%s, range_loc=%s, volatility=%s, debt_ratio=%s, 
                     days_to_earnings = CASE WHEN %s < 999 THEN %s ELSE days_to_earnings END, 
                     market_cap=%s, eps=%s"""
            vals = (t, price, change, rsi, trend, vol_stat, range_loc, volatility, debt_ratio, days_to_earnings, market_cap, eps,
                    price, change, rsi, trend, vol_stat, range_loc, volatility, debt_ratio, days_to_earnings, days_to_earnings, market_cap, eps)
            cursor.execute(sql, vals)
        except: continue
    conn.commit(); conn.close()
    check_alerts(username)

def get_cached_data(tickers):
    if not tickers: return []
    conn = get_connection(); cursor = conn.cursor(dictionary=True)
    format_strings = ','.join(['%s'] * len(tickers))
    cursor.execute(f"SELECT * FROM stock_cache WHERE ticker IN ({format_strings})", tuple(tickers))
    rows = cursor.fetchall(); conn.close()
    return rows

def get_single_stock(ticker):
    conn = get_connection(); cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM stock_cache WHERE ticker = %s", (ticker,))
    row = cursor.fetchone(); conn.close()
    return row

# 3. AUTH & UTILS
def login_user(username, pin):
    try:
        conn = get_connection(); cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM user_profiles WHERE username = %s", (username,))
        user = cursor.fetchone(); conn.close()
        if user and user['pin'] == pin: return user
        return None
    except: return None

def register_user(username, pin, display_name, email):
    try:
        conn = get_connection(); cursor = conn.cursor()
        cursor.execute("SELECT username FROM user_profiles WHERE username = %s", (username,))
        if cursor.fetchone(): conn.close(); return False
        cursor.execute("INSERT INTO user_profiles (username, pin, display_name, email) VALUES (%s, %s, %s, %s)", (username, pin, display_name, email))
        conn.commit(); conn.close(); return True
    except: return False

def update_user_settings(username, display_name, email, new_pin=None):
    try:
        conn = get_connection(); cursor = conn.cursor()
        if new_pin: cursor.execute("UPDATE user_profiles SET display_name=%s, email=%s, pin=%s WHERE username=%s", (display_name, email, new_pin, username))
        else: cursor.execute("UPDATE user_profiles SET display_name=%s, email=%s WHERE username=%s", (display_name, email, username))
        conn.commit(); conn.close(); return True
    except: return False

def create_session(username):
    token = str(uuid.uuid4()); conn = get_connection(); cursor = conn.cursor()
    cursor.execute("INSERT INTO user_sessions (token, username) VALUES (%s, %s)", (token, username))
    conn.commit(); conn.close(); return token

def get_user_from_token(token):
    try:
        conn = get_connection(); cursor = conn.cursor(dictionary=True)
        cursor.execute("""SELECT s.username, p.display_name, p.email FROM user_sessions s JOIN user_profiles p ON s.username = p.username WHERE s.token = %s""", (token,))
        row = cursor.fetchone(); conn.close()
        return row if row else None
    except: return None

# 4. ALERTS & PORTFOLIO OPS
def add_alert(username, ticker, condition, price):
    try:
        conn = get_connection(); cursor = conn.cursor()
        cursor.execute("INSERT INTO user_alerts (username, ticker, condition_type, target_price) VALUES (%s, %s, %s, %s)", (username, ticker, condition, price))
        conn.commit(); conn.close(); return True
    except: return False

def delete_alert(alert_id):
    try:
        conn = get_connection(); cursor = conn.cursor()
        cursor.execute("DELETE FROM user_alerts WHERE id = %s", (alert_id,)); conn.commit(); conn.close()
    except: pass

def get_user_alerts(username):
    try:
        conn = get_connection(); cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM user_alerts WHERE username = %s ORDER BY is_triggered ASC, created_at DESC", (username,))
        rows = cursor.fetchall(); conn.close(); return rows
    except: return []

def add_ticker_to_db(username, ticker):
    try:
        conn = get_connection(); cursor = conn.cursor()
        cursor.execute("SELECT id FROM user_portfolio WHERE username=%s AND ticker=%s", (username, ticker))
        if not cursor.fetchone():
            cursor.execute("INSERT INTO user_portfolio (username, ticker) VALUES (%s, %s)", (username, ticker))
            conn.commit()
        conn.close(); return True
    except: return False

def remove_ticker_from_db(username, ticker):
    try:
        conn = get_connection(); cursor = conn.cursor()
        cursor.execute("DELETE FROM user_portfolio WHERE username=%s AND ticker=%s", (username, ticker))
        conn.commit(); conn.close()
    except: pass

def get_user_portfolio(username):
    try:
        conn = get_connection(); cursor = conn.cursor()
        cursor.execute("SELECT ticker FROM user_portfolio WHERE username=%s", (username,))
        rows = cursor.fetchall(); conn.close()
        return [r[0] for r in rows]
    except: return []

def calculate_risk(row):
    score = 50; reasons = [] 
    if row.get('trend_status') == 'DOWNTREND': score += 10
    else: score -= 10
    rsi = float(row.get('rsi', 50))
    if rsi > 70: score += 10; reasons.append("Overbought")
    if rsi < 30: score -= 10; reasons.append("Oversold")
    vol = float(row.get('volatility', 0))
    if vol > 3.0: score += 10; reasons.append("High Volatility")
    debt = float(row.get('debt_ratio', 0))
    if debt > 150: score += 5; reasons.append("High Debt")
    days = int(row.get('days_to_earnings', 999))
    if days < 10: score += 15; reasons.append("Earnings Soon")
    loc = float(row.get('range_loc', 50))
    if loc > 90: score += 10
    elif loc < 10: score -= 10
    if row.get('volume_status') == 'SPIKE': score += 5; reasons.append("Vol Spike")
    mcap = float(row.get('market_cap', 0))
    if 0 < mcap < 250000000: score += 15; reasons.append("Micro Cap")
    elif 0 < mcap < 2000000000: score += 5
    eps = float(row.get('eps', 0))
    if eps < 0: score += 10; reasons.append("Unprofitable")
    
    final = max(0, min(100, int(score)))
    css, color, label = "badge-low", "#4ade80", "LOW"
    if final > 65: label, color, css = "HIGH", "#ef4444", "badge-high"
    elif final > 35: label, color, css = "MEDIUM", "#fbbf24", "badge-med"
    return final, label, color, css, reasons

# 5. UI GENERATORS
def create_gauge_html(score, label, color, size="big"):
    radius = 80 if size == "big" else 60
    viewbox = "0 0 200 120" if size == "big" else "0 0 160 100"
    font_s = "38" if size == "big" else "28"
    font_l = "12" if size == "big" else "10"
    
    circumference = 3.14159 * radius
    fill_amount = (score / 100) * circumference
    
    header = f'<div style="text-align:center; color:#94a3b8; font-size:0.8rem; font-weight:bold; letter-spacing:1px; margin-bottom:5px;">PORTFOLIO RISK</div>' if size == "big" else ""
    
    svg = f'<svg viewBox="{viewbox}" style="width: 100%; height: auto;"><defs><linearGradient id="grad1" x1="0%" y1="0%" x2="100%" y2="0%"><stop offset="0%" style="stop-color:#4ade80;stop-opacity:1" /><stop offset="50%" style="stop-color:#fbbf24;stop-opacity:1" /><stop offset="100%" style="stop-color:#ef4444;stop-opacity:1" /></linearGradient></defs><path d="M 20 100 A {radius} {radius} 0 0 1 {20 + (radius*2)} 100" fill="none" stroke="#334155" stroke-width="15" stroke-linecap="round" /><path d="M 20 100 A {radius} {radius} 0 0 1 {20 + (radius*2)} 100" fill="none" stroke="url(#grad1)" stroke-width="15" stroke-linecap="round" stroke-dasharray="{fill_amount}, 1000" /><text x="{20+radius}" y="{80 if size=="big" else 85}" font-family="sans-serif" font-size="{font_s}" font-weight="bold" fill="white" text-anchor="middle">{score}</text><text x="{20+radius}" y="100" font-family="sans-serif" font-size="{font_l}" font-weight="bold" fill="{color}" text-anchor="middle" letter-spacing="2">{label}</text></svg>'
    
    if size == "big":
        return f'<div class="card" style="padding-bottom:0; margin-bottom: 0px;">{header}{svg}</div>'
    else:
        return f'<div style="margin-bottom:15px;">{svg}</div>'

def render_stock_card(row, is_clickable=True):
    score, label, color, css, reasons = calculate_risk(row)
    price = float(row['current_price']); change = float(row['day_change']); c_color = "#4ade80" if change >= 0 else "#ef4444"; arrow = "▲" if change >= 0 else "▼"; ticker = row['ticker']; trend = row.get('trend_status', 'N/A')
    
    # We use a button to simulate the "Clickable Card" behavior for Detail View
    if is_clickable:
        if st.button(f"{ticker}   {arrow} {change:.2f}%", key=f"btn_{ticker}", use_container_width=True):
            st.session_state["selected_ticker"] = ticker
            st.rerun()
        return

    reason_html = f"<div style='font-size:0.65rem; color:#94a3b8; margin-top:4px;'>⚠️ {', '.join(reasons[:2])}</div>" if reasons else ""
    html = f'<div class="card" style="display: flex; justify-content: space-between; align-items: center;"><div><div style="font-weight:bold; font-size:1.1rem; color:white;">{ticker}</div><div style="font-size:0.8rem; color:#94a3b8;">Trend: {trend}</div>{reason_html}</div><div style="text-align: right; flex-grow:1; padding-right:15px;"><div style="color:white; font-weight:bold;">${price:,.2f}</div><div style="color:{c_color}; font-size:0.8rem;">{arrow} {change:.2f}%</div></div><div class="{css} badge">{label}</div></div>'
    st.markdown(html, unsafe_allow_html=True)

def render_horizontal_grid(rows):
    html_content = '<div class="scrolling-wrapper">'
    for row in rows:
        change = float(row['day_change']); c_color = "#4ade80" if change >= 0 else "#ef4444"; arrow = "▲" if change >= 0 else "▼"; ticker = row['ticker']
        # Note: Making these clickable via pure HTML in Streamlit is hard without components. 
        # For now, these are visual snapshots. The Portfolio list is the main navigation.
        card = f'<div class="scrolling-card"><div style="font-weight:bold; font-size:1.1rem; color:white; margin-bottom: 4px;">{ticker}</div><div style="font-size:0.85rem; color:{c_color}; font-weight:bold; margin-bottom: 8px;">{arrow} {change:.2f}%</div><div style="display: flex; align-items: center;"><div style="width: 8px; height: 8px; border-radius: 50%; background-color: {c_color}; margin-right: 6px;"></div><div style="font-size:0.75rem; color:#94a3b8;">Daily Move</div></div></div>'
        html_content += card
    html_content += '</div>'; st.markdown(html_content, unsafe_allow_html=True)

def get_greeting(name):
    hour = datetime.now(pytz.timezone('America/Halifax')).hour
    if hour < 12: return f"Good Morning, {name}"
    elif 12 <= hour < 18: return f"Good Afternoon, {name}"
    else: return f"Good Evening, {name}"

init_db()
# CSS 
st.markdown("""<style> 
    .stApp { background-color: #0f1219; color: #e0e6ed; } 
    .block-container { padding-top: 0rem !important; padding-bottom: 5rem !important; }
    
    .card { background-color: #1a1f2b; border-radius: 16px; padding: 20px; margin-bottom: 12px; border: 1px solid #2d3748; box-shadow: 0 4px 6px rgba(0,0,0,0.3); } 
    .badge { padding: 4px 8px; border-radius: 6px; font-size: 0.75rem; font-weight: bold; } 
    .badge-high { background: rgba(239, 68, 68, 0.2); color: #ef4444; } 
    .badge-med { background: rgba(251, 191, 36, 0.2); color: #fbbf24; } 
    .badge-low { background: rgba(74, 222, 128, 0.2); color: #4ade80; } 
    
    /* INPUTS & BUTTONS */
    input[type="text"], input[type="password"], input[type="number"] { background-color: #1e293b !important; color: #ffffff !important; border: 1px solid #3b82f6 !important; border-radius: 8px !important; }
    div[data-baseweb="input"] { background-color: #1e293b !important; border-color: #3b82f6 !important; border-radius: 8px !important; }
    div[data-baseweb="select"] > div { background-color: #1e293b !important; color: white !important; border-color: #3b82f6 !important; }
    div[data-baseweb="popover"], div[role="listbox"] { background-color: #1e293b !important; color: white !important; }
    div[role="option"] { color: white !important; }
    div[data-testid="stWidgetLabel"] p, label p, label { color: #e0e6ed !important; font-weight: bold; }
    button[data-baseweb="tab"] { color: #94a3b8 !important; }
    button[data-baseweb="tab"][aria-selected="true"] { color: #3b82f6 !important; border-bottom-color: #3b82f6 !important; font-weight: bold !important; }
    div.stButton > button, div[data-testid="stFormSubmitButton"] > button { background: linear-gradient(to right, #2563eb, #06b6d4) !important; color: white !important; border: none !important; border-radius: 8px !important; font-weight: bold !important; padding: 10px 20px !important; }
    div.stButton > button:hover { opacity: 0.9 !important; transform: scale(1.02); }

    /* STOCK LIST BUTTONS (Make them look like cards) */
    div.stButton > button[kind="secondary"] {
        background: #1a1f2b !important; 
        border: 1px solid #2d3748 !important;
        text-align: left !important;
        display: flex; justify-content: space-between;
        margin-bottom: 5px;
    }

    header {visibility: hidden;} footer {visibility: hidden;} 
    .scrolling-wrapper { display: flex; flex-wrap: nowrap; overflow-x: auto; -webkit-overflow-scrolling: touch; gap: 12px; padding-bottom: 10px; margin-bottom: 15px; -ms-overflow-style: none; scrollbar-width: none; } 
    .scrolling-wrapper::-webkit-scrollbar { display: none; } 
    .scrolling-card { flex: 0 0 auto; width: 130px; background-color: #1a1f2b; border: 1px solid #2d3748; border-radius: 12px; padding: 15px; } 
</style>""", unsafe_allow_html=True)

# --- LOGIN ---
if "token" not in st.query_params:
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        if os.path.exists("logo.png"): st.image("logo.png", width=200)
        else: st.markdown("<h1 style='text-align:center;'>⚡ Penny Pulse</h1>", unsafe_allow_html=True)
    tab1, tab2, tab3 = st.tabs(["Login", "Register", "Forgot PIN"])
    with tab1:
        with st.form("login_form"):
            user = st.text_input("Username"); pin = st.text_input("PIN", type="password")
            if st.form_submit_button("Login", use_container_width=True):
                user_data = login_user(user, pin)
                if user_data: token = create_session(user); st.query_params["token"] = token; st.rerun()
                else: st.error("Invalid Username or PIN")
    with tab2:
        with st.form("reg_form"):
            new_user = st.text_input("Choose Username"); new_pin = st.text_input("Choose PIN", type="password"); disp_name = st.text_input("Your Name (e.g. Dave)"); email = st.text_input("Recovery Email (Optional)")
            if st.form_submit_button("Create Account", use_container_width=True):
                if new_user and new_pin and disp_name:
                    if register_user(new_user, new_pin, disp_name, email): st.success("Account created! Please Login.")
                    else: st.error("Username taken.")
                else: st.error("Required fields missing.")
    with tab3:
        st.info("If you set an email, contact support to reset."); lost_user = st.text_input("Username", key="lost_u")
        if st.button("Request Reset"): st.warning("Reset link sent (Simulation).")
    st.stop()

# --- MAIN APP STATE ---
user_info = get_user_from_token(st.query_params["token"])
if not user_info: st.error("Session Expired"); st.stop()
username = user_info['username']; display_name = user_info['display_name'] or username

# NAVIGATION
if "selected_ticker" not in st.session_state: st.session_state.selected_ticker = None

if st.session_state.selected_ticker:
    # --- DETAIL PAGE ---
    ticker = st.session_state.selected_ticker
    
    # Back Button
    if st.button("← Back", key="back_btn"):
        st.session_state.selected_ticker = None
        st.rerun()
        
    stock = get_single_stock(ticker)
    if stock:
        score, label, color, css, reasons = calculate_risk(stock)
        price = float(stock['current_price'])
        change = float(stock['day_change'])
        c_color = "#4ade80" if change >= 0 else "#ef4444"
        
        st.markdown(f"<h1 style='margin-bottom:0;'>{ticker}</h1>", unsafe_allow_html=True)
        st.markdown(f"<h2 style='margin-top:0; color:{c_color};'>${price:,.2f} ({change:.2f}%)</h2>", unsafe_allow_html=True)
        
        # Risk Gauge
        st.markdown(create_gauge_html(score, label, color, size="big"), unsafe_allow_html=True)
        
        # Risk Factors List
        st.markdown(f"<div class='card' style='margin-top:20px;'><strong>Risk Factors:</strong>", unsafe_allow_html=True)
        if reasons:
            for r in reasons:
                st.markdown(f"- ⚠️ {r}")
        else:
            st.markdown("- ✅ No major risk flags detected.")
        st.markdown("</div>", unsafe_allow_html=True)
        
        # Fake News (Placeholder to match design)
        st.markdown("### Recent News")
        st.info("News API integration required for live headlines.")
        
        # Alerts Shortcut
        if st.button("🔔 Set Alert for " + ticker, use_container_width=True):
            st.query_params["tab"] = "alerts"
            st.session_state.selected_ticker = None # Reset so we go to alerts tab
            st.rerun()
            
    else:
        st.error("Data not found.")
        if st.button("Back"): st.session_state.selected_ticker = None; st.rerun()

else:
    # --- MAIN TABS ---
    active_tab = st.query_params.get("tab", "home")

    if active_tab == "home":
        st.markdown(f"<div style='font-size: 24px; font-weight: 800; color: white; margin-bottom: 5px;'>{get_greeting(display_name)}</div>", unsafe_allow_html=True)
        my_portfolio = get_user_portfolio(username)
        if not my_portfolio: st.info("No stocks. Go to Portfolio tab.")
        else:
            if st.button("🔄 Refresh", key="ref_home"):
                with st.spinner("Analyzing fundamentals..."): update_stock_data(my_portfolio, username)
            data = get_cached_data(my_portfolio)
            if data:
                avg_risk = sum([calculate_risk(x)[0] for x in data]) / len(data)
                r_score, r_label, r_color, _, _ = calculate_risk({'trend_status':'N', 'rsi':50})
                if avg_risk > 65: r_label, r_color = "HIGH", "#ef4444"
                elif avg_risk > 35: r_label, r_color = "MEDIUM", "#fbbf24"
                else: r_label, r_color = "LOW", "#4ade80"
                st.markdown(create_gauge_html(int(avg_risk), r_label, r_color), unsafe_allow_html=True)
                highest_risk_stock = max(data, key=lambda x: calculate_risk(x)[0])
                most_volatile_stock = max(data, key=lambda x: abs(float(x['day_change'])))
                earnings_candidates = [d for d in data if d.get('days_to_earnings', 999) < 999]
                earning_ticker = "-"
                if earnings_candidates:
                    next = min(earnings_candidates, key=lambda x: int(x.get('days_to_earnings', 999)))
                    earning_ticker = f"{next['ticker']} ({next['days_to_earnings']}d)"
                st.markdown(f"""<div style="display:flex; justify-content:space-between; background:#151922; padding:15px; border-radius:0 0 16px 16px; margin-top:-14px; margin-bottom:20px; border:1px solid #2d3748; border-top:none;"><div style="text-align:center; width:33.3%; border-right:1px solid #2d3748;"><div style="color:#94a3b8; font-size:0.6rem; text-transform:uppercase;">Highest Risk</div><div style="color:white; font-weight:bold; font-size:1rem;">{highest_risk_stock['ticker']}</div></div><div style="text-align:center; width:33.3%; border-right:1px solid #2d3748;"><div style="color:#94a3b8; font-size:0.6rem; text-transform:uppercase;">Most Volatile</div><div style="color:white; font-weight:bold; font-size:1rem;">{most_volatile_stock['ticker']}</div></div><div style="text-align:center; width:33.3%;"><div style="color:#94a3b8; font-size:0.6rem; text-transform:uppercase;">Next Earning</div><div style="color:white; font-weight:bold; font-size:1rem;">{earning_ticker}</div></div></div>""", unsafe_allow_html=True)
                st.write("### At a Glance")
                render_horizontal_grid(data)

    elif active_tab == "portfolio":
        st.markdown(f"<div style='font-size: 24px; font-weight: 800; color: white; margin-bottom: 15px;'>Manage Portfolio</div>", unsafe_allow_html=True)
        col1, col2 = st.columns([2, 1]); 
        with col1: new_ticker = st.text_input("Ticker Symbol").upper()
        with col2:
            st.write(""); st.write("")
            if st.button("Add"):
                if new_ticker and add_ticker_to_db(username, new_ticker): st.success(f"Added {new_ticker}"); st.rerun()
        
        st.divider()
        my_stocks = get_user_portfolio(username)
        data = get_cached_data(my_stocks)
        
        if data:
            # Custom Portfolio List Logic
            for row in data:
                c1, c2 = st.columns([4, 1])
                with c1:
                    # Renders a button that looks like a card (Click to view detail)
                    render_stock_card(row, is_clickable=True) 
                with c2:
                    # Small delete button on the right
                    st.write("")
                    st.write("")
                    if st.button("❌", key=f"del_{row['ticker']}"):
                        remove_ticker_from_db(username, row['ticker'])
                        st.rerun()

    elif active_tab == "alerts":
        st.markdown(f"<div style='font-size: 24px; font-weight: 800; color: white; margin-bottom: 15px;'>Volatility Alerts</div>", unsafe_allow_html=True)
        with st.expander("➕ Set New Alert", expanded=True):
            my_stocks = get_user_portfolio(username)
            if not my_stocks: st.info("Add stocks to your portfolio first.")
            else:
                c1, c2, c3 = st.columns([2, 2, 2])
                with c1: ticker = st.selectbox("Ticker", my_stocks)
                with c2: condition = st.selectbox("Move", ["DOWN", "UP"])
                with c3: price = st.number_input("Percent %", min_value=1.0, value=5.0, step=0.5)
                if st.button("Create Alert", use_container_width=True):
                    if add_alert(username, ticker, condition, price): st.success(f"Alert Set: {ticker} {condition} {price}%"); st.rerun()
        st.write("### Active Alerts")
        alerts = get_user_alerts(username)
        if alerts:
            for a in alerts:
                bg_color = "#3d1111" if a['is_triggered'] else "#1a1f2b"
                border_color = "#ef4444" if a['is_triggered'] else "#2d3748"
                status_icon = "🔔 TRIGGERED" if a['is_triggered'] else "👀 Watching"
                arrow = "📉 Drops" if a['condition_type'] == 'DOWN' else "📈 Rises"
                card_html = f"""<div style="background-color: {bg_color}; border: 1px solid {border_color}; border-radius: 12px; padding: 15px; margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center;"><div><div style="font-weight:bold; font-size:1.1rem; color:white;">{a['ticker']}</div><div style="font-size:0.85rem; color:#94a3b8;">{status_icon}: {arrow} {a['target_price']}%</div></div></div>"""
                st.markdown(card_html, unsafe_allow_html=True)
                if st.button("Delete", key=f"del_alert_{a['id']}"): delete_alert(a['id']); st.rerun()
        else: st.info("No alerts set.")

    elif active_tab == "scanner":
        st.markdown(f"<div style='font-size: 24px; font-weight: 800; color: white; margin-bottom: 5px;'>Scanner</div>", unsafe_allow_html=True)
        st.caption("Auto-generated from your portfolio")
        my_portfolio = get_user_portfolio(username); data = get_cached_data(my_portfolio)
        if not data: st.info("No data to scan.")
        else:
            found_any = False
            st.markdown("**📉 Oversold (RSI < 35)**")
            for row in data:
                if float(row['rsi']) < 35: render_stock_card(row, is_clickable=False); found_any = True
            st.markdown("**🔊 Volume Spikes**")
            for row in data:
                if row.get('volume_status') == "SPIKE": render_stock_card(row, is_clickable=False); found_any = True
            st.markdown("**📅 Earnings Coming Soon**")
            for row in data:
                if int(row.get('days_to_earnings', 999)) < 14: render_stock_card(row, is_clickable=False); found_any = True
            if not found_any: st.success("No alerts found.")

    elif active_tab == "settings":
        st.markdown(f"<div style='font-size: 24px; font-weight: 800; color: white; margin-bottom: 15px;'>Settings</div>", unsafe_allow_html=True)
        st.write("### Profile")
        with st.form("settings_form"):
            new_name = st.text_input("Display Name", value=display_name)
            new_email = st.text_input("Recovery Email", value=user_info.get('email', ''))
            new_pin = st.text_input("New PIN (Leave blank to keep current)", type="password")
            if st.form_submit_button("Save Changes"):
                pin_to_save = new_pin if new_pin else None
                if update_user_settings(username, new_name, new_email, pin_to_save): st.success("Settings saved! Reloading..."); st.rerun()
                else: st.error("Error saving settings.")
        st.divider()
        if st.button("Log Out"): st.query_params.clear(); st.rerun()

    # BOTTOM NAV
    current_token = st.query_params.get("token", "")
    nav_html = f"""<style>.nav-container {{ position: fixed; bottom: 0; left: 0; width: 100%; height: 60px; background-color: #1a1f2b; border-top: 1px solid #2d3748; display: flex; justify-content: space-around; align-items: center; z-index: 9999; }} a.nav-link, a.nav-link:visited, a.nav-link:hover, a.nav-link:active {{ text-decoration: none; color: #94a3b8; font-family: sans-serif; font-size: 12px; text-align: center; width: 100%; padding: 5px 0; }} a.nav-link:hover {{ color: white; }} .nav-icon {{ font-size: 20px; display: block; margin-bottom: 2px; }} a.active, a.active:visited {{ color: #3b82f6 !important; font-weight: bold; }}</style><div class="nav-container"><a href="?token={current_token}&tab=home" class="nav-link {'active' if active_tab == 'home' else ''}"><span class="nav-icon">🏠</span>Home</a><a href="?token={current_token}&tab=portfolio" class="nav-link {'active' if active_tab == 'portfolio' else ''}"><span class="nav-icon">📂</span>Stocks</a><a href="?token={current_token}&tab=alerts" class="nav-link {'active' if active_tab == 'alerts' else ''}"><span class="nav-icon">🔔</span>Alerts</a><a href="?token={current_token}&tab=scanner" class="nav-link {'active' if active_tab == 'scanner' else ''}"><span class="nav-icon">📡</span>Scan</a><a href="?token={current_token}&tab=settings" class="nav-link {'active' if active_tab == 'settings' else ''}"><span class="nav-icon">⚙️</span>Set</a></div>"""
    st.markdown(nav_html, unsafe_allow_html=True)
