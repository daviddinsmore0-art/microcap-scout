import streamlit as st
import mysql.connector
import yfinance as yf
import uuid
import json

# 1. CONFIG & DATABASE
st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="centered")

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
        
        # User Tables
        cursor.execute("CREATE TABLE IF NOT EXISTS user_profiles (username VARCHAR(255) PRIMARY KEY, user_data TEXT, pin VARCHAR(50))")
        cursor.execute("CREATE TABLE IF NOT EXISTS user_sessions (token VARCHAR(255) PRIMARY KEY, username VARCHAR(255), created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
        
        # New Portfolio Table (Fixed Syntax)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_portfolio (
                id INT NOT NULL AUTO_INCREMENT, 
                username VARCHAR(255), 
                ticker VARCHAR(20), 
                PRIMARY KEY (id)
            )
        """)
        
        # Cache Table
        sql = "CREATE TABLE IF NOT EXISTS stock_cache (ticker VARCHAR(20) PRIMARY KEY, current_price DECIMAL(20, 4), day_change DECIMAL(10, 2), rsi DECIMAL(10, 2), trend_status VARCHAR(20), last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)"
        cursor.execute(sql)
        conn.close()
    except Exception as e:
        st.error(f"DATABASE INIT ERROR: {e}")

# 2. DATA MIGRATION (The Fix for 'List already in DB')
def migrate_old_data(username):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # 1. Check if new portfolio is empty
        cursor.execute("SELECT count(*) FROM user_portfolio WHERE username=%s", (username,))
        if cursor.fetchone()[0] > 0:
            conn.close()
            return # Already has data, don't overwrite
            
        # 2. Fetch old JSON data
        cursor.execute("SELECT user_data FROM user_profiles WHERE username=%s", (username,))
        row = cursor.fetchone()
        if row and row[0]:
            data = json.loads(row[0])
            old_list = data.get("w_input", "").split(",")
            
            # 3. Insert into new table
            for t in old_list:
                clean_t = t.strip().upper()
                if clean_t:
                    cursor.execute("INSERT INTO user_portfolio (username, ticker) VALUES (%s, %s)", (username, clean_t))
            
            conn.commit()
            st.toast(f"Migrated {len(old_list)} stocks from old database!")
            
        conn.close()
    except Exception as e:
        st.error(f"Migration Failed: {e}")

# 3. AUTHENTICATION & PORTFOLIO
def check_login(username, pin):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT pin FROM user_profiles WHERE username = %s", (username,))
        row = cursor.fetchone()
        conn.close()
        if row: return row[0] == pin
        return True 
    except: return False

def create_session(username):
    token = str(uuid.uuid4())
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO user_sessions (token, username) VALUES (%s, %s)", (token, username))
    conn.commit()
    conn.close()
    return token

def get_user_from_token(token):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT username FROM user_sessions WHERE token = %s", (token,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None
    except: return None

def add_ticker_to_db(username, ticker):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        # Check duplicate
        cursor.execute("SELECT id FROM user_portfolio WHERE username=%s AND ticker=%s", (username, ticker))
        if not cursor.fetchone():
            cursor.execute("INSERT INTO user_portfolio (username, ticker) VALUES (%s, %s)", (username, ticker))
            conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"ADD ERROR: {e}")
        return False

def remove_ticker_from_db(username, ticker):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM user_portfolio WHERE username=%s AND ticker=%s", (username, ticker))
        conn.commit()
        conn.close()
    except Exception as e:
        st.error(f"DELETE ERROR: {e}")

def get_user_portfolio(username):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT ticker FROM user_portfolio WHERE username=%s", (username,))
        rows = cursor.fetchall()
        conn.close()
        return [r[0] for r in rows]
    except Exception as e:
        st.error(f"FETCH ERROR: {e}")
        return []

# 4. DATA ENGINE
def update_stock_data(tickers):
    if not tickers: return
    try:
        data = yf.download(" ".join(tickers), period="3mo", group_by='ticker', threads=True, progress=False)
    except: return

    conn = get_connection()
    cursor = conn.cursor()
    
    for t in tickers:
        try:
            if len(tickers) > 1: df = data[t]
            else: df = data
            
            df = df.dropna()
            if df.empty: continue

            price = float(df['Close'].iloc[-1])
            prev = float(df['Close'].iloc[-2])
            change = ((price - prev) / prev) * 100
            
            delta = df['Close'].diff()
            up, down = delta.clip(lower=0), -1 * delta.clip(upper=0)
            rs = up.ewm(com=13, adjust=False).mean() / down.ewm(com=13, adjust=False).mean()
            rsi = 100 - (100 / (1 + rs)).iloc[-1]
            
            ma50 = df['Close'].rolling(50).mean().iloc[-1]
            trend = "UPTREND" if price > ma50 else "DOWNTREND"
            
            sql = "INSERT INTO stock_cache (ticker, current_price, day_change, rsi, trend_status) VALUES (%s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE current_price=%s, day_change=%s, rsi=%s, trend_status=%s"
            cursor.execute(sql, (t, price, change, rsi, trend, price, change, rsi, trend))
        except: continue
    conn.commit()
    conn.close()

def get_cached_data(tickers):
    if not tickers: return []
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    format_strings = ','.join(['%s'] * len(tickers))
    cursor.execute(f"SELECT * FROM stock_cache WHERE ticker IN ({format_strings})", tuple(tickers))
    rows = cursor.fetchall()
    conn.close()
    return rows

def calculate_risk(row):
    score = 50
    trend = row.get('trend_status', 'NEUTRAL')
    rsi = float(row.get('rsi', 50))
    
    if trend == 'DOWNTREND': score += 20
    if trend == 'UPTREND': score -= 15
    if rsi > 70: score += 20
    if rsi < 30: score -= 10
    
    final = max(0, min(100, int(score)))
    if final > 60: return final, "HIGH", "#ef4444", "badge-high"
    if final > 40: return final, "MEDIUM", "#fbbf24", "badge-med"
    return final, "LOW", "#4ade80", "badge-low"

# 5. UI COMPONENTS
def create_gauge_html(score, label, color):
    radius = 80
    circumference = 3.14159 * radius
    fill_amount = (score / 100) * circumference
    svg = f'<svg viewBox="0 0 200 110" style="width: 100%; height: auto;">'
    svg += '<defs><linearGradient id="grad1" x1="0%" y1="0%" x2="100%" y2="0%"><stop offset="0%" style="stop-color:#4ade80;stop-opacity:1" /><stop offset="50%" style="stop-color:#fbbf24;stop-opacity:1" /><stop offset="100%" style="stop-color:#ef4444;stop-opacity:1" /></linearGradient></defs>'
    svg += f'<path d="M 20 100 A 80 80 0 0 1 180 100" fill="none" stroke="#334155" stroke-width="15" stroke-linecap="round" />'
    svg += f'<path d="M 20 100 A 80 80 0 0 1 180 100" fill="none" stroke="url(#grad1)" stroke-width="15" stroke-linecap="round" stroke-dasharray="{fill_amount}, 1000" />'
    svg += f'<text x="100" y="85" font-family="sans-serif" font-size="40" font-weight="bold" fill="white" text-anchor="middle">{score}</text>'
    svg += f'<text x="100" y="105" font-family="sans-serif" font-size="12" font-weight="bold" fill="{color}" text-anchor="middle" letter-spacing="2">{label}</text></svg>'
    return f'<div class="card" style="padding-bottom:0;">{svg}</div>'

init_db()

# CSS 
st.markdown("<style>.stApp { background-color: #0f1219; color: #e0e6ed; } .card { background-color: #1a1f2b; border-radius: 16px; padding: 20px; margin-bottom: 12px; border: 1px solid #2d3748; box-shadow: 0 4px 6px rgba(0,0,0,0.3); } .badge { padding: 4px 8px; border-radius: 6px; font-size: 0.75rem; font-weight: bold; } .badge-high { background: rgba(239, 68, 68, 0.2); color: #ef4444; } .badge-med { background: rgba(251, 191, 36, 0.2); color: #fbbf24; } .badge-low { background: rgba(74, 222, 128, 0.2); color: #4ade80; } .block-container { padding-top: 2rem; } input { color: black !important; }</style>", unsafe_allow_html=True)

# LOGIN
if "token" not in st.query_params:
    st.markdown("<h1 style='text-align:center;'>⚡ Penny Pulse</h1>", unsafe_allow_html=True)
    with st.form("login"):
        user = st.text_input("Username")
        pin = st.text_input("PIN", type="password")
        if st.form_submit_button("Login"):
            if check_login(user, pin):
                token = create_session(user)
                st.query_params["token"] = token
                st.rerun()
            else:
                st.error("Invalid PIN")
    st.stop()

# DASHBOARD
username = get_user_from_token(st.query_params["token"])
if not username:
    st.error("Session Expired")
    st.stop()

# Attempt Migration (Only runs if new table is empty)
migrate_old_data(username)

# --- SIDEBAR MANAGER ---
with st.sidebar:
    st.header(f"👤 {username}")
    st.write("### Manage Portfolio")
    new_ticker = st.text_input("Add Ticker (e.g. AMZN)").upper()
    if st.button("Add Stock"):
        if new_ticker:
            if add_ticker_to_db(username, new_ticker):
                st.success(f"Added {new_ticker}")
                st.rerun()
    
    st.divider()
    st.write("### Remove Stock")
    my_stocks = get_user_portfolio(username)
    if my_stocks:
        rem_ticker = st.selectbox("Select to Delete", my_stocks)
        if st.button("Delete Selected"):
            remove_ticker_from_db(username, rem_ticker)
            st.success(f"Removed {rem_ticker}")
            st.rerun()

# --- MAIN APP ---
my_portfolio = get_user_portfolio(username)

if not my_portfolio:
    st.info("Your portfolio is empty. Add a stock in the sidebar!")
    if st.button("Load Default Portfolio"):
        for t in ["TD.TO", "TSLA", "NVDA"]: add_ticker_to_db(username, t)
        st.rerun()
    st.stop()

if st.button("🔄 Refresh Prices"):
    with st.spinner("Updating..."):
        update_stock_data(my_portfolio)

data = get_cached_data(my_portfolio)

if data:
    avg_risk = sum([calculate_risk(x)[0] for x in data]) / len(data)
    r_score, r_label, r_color, _ = calculate_risk({'trend_status':'N', 'rsi':50})
    if avg_risk > 60: r_label, r_color = "HIGH", "#ef4444"
    elif avg_risk > 40: r_label, r_color = "MEDIUM", "#fbbf24"
    else: r_label, r_color = "LOW", "#4ade80"

    st.title(f"Good Evening, {username}")
    st.markdown(create_gauge_html(int(avg_risk), r_label, r_color), unsafe_allow_html=True)

    st.subheader("My Portfolio")
    for row in data:
        score, label, color, css = calculate_risk(row)
        price = float(row['current_price'])
        change = float(row['day_change'])
        c_color = "#4ade80" if change >= 0 else "#ef4444"
        arrow = "▲" if change >= 0 else "▼"
        ticker = row['ticker']
        trend = row.get('trend_status', 'N/A')
        
        card_html = f'<div class="card" style="display: flex; justify-content: space-between; align-items: center;"><div><div style="font-weight:bold; font-size:1.1rem; color:white;">{ticker}</div><div style="font-size:0.8rem; color:#94a3b8;">Trend: {trend}</div></div><div style="text-align: right; flex-grow:1; padding-right:15px;"><div style="color:white; font-weight:bold;">${price:,.2f}</div><div style="color:{c_color}; font-size:0.8rem;">{arrow} {change:.2f}%</div></div><div class="{css} badge">{label}</div></div>'
        st.markdown(card_html, unsafe_allow_html=True)
else:
    st.info("Click 'Refresh Prices' to load data.")
