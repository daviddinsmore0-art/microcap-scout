import streamlit as st
import mysql.connector
import yfinance as yf
import uuid
import os

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
        cursor.execute("CREATE TABLE IF NOT EXISTS user_profiles (username VARCHAR(255) PRIMARY KEY, user_data TEXT, pin VARCHAR(50))")
        cursor.execute("CREATE TABLE IF NOT EXISTS user_sessions (token VARCHAR(255) PRIMARY KEY, username VARCHAR(255), created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
        cursor.execute("CREATE TABLE IF NOT EXISTS user_portfolio (id INT NOT NULL AUTO_INCREMENT, username VARCHAR(255), ticker VARCHAR(20), PRIMARY KEY (id))")
        sql = "CREATE TABLE IF NOT EXISTS stock_cache (ticker VARCHAR(20) PRIMARY KEY, current_price DECIMAL(20, 4), day_change DECIMAL(10, 2), rsi DECIMAL(10, 2), trend_status VARCHAR(20), volume_status VARCHAR(20), last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)"
        cursor.execute(sql)
        conn.close()
    except Exception as e:
        st.error(f"DB Error: {e}")

# 2. AUTHENTICATION
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

# 3. PORTFOLIO & DATA
def add_ticker_to_db(username, ticker):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM user_portfolio WHERE username=%s AND ticker=%s", (username, ticker))
        if not cursor.fetchone():
            cursor.execute("INSERT INTO user_portfolio (username, ticker) VALUES (%s, %s)", (username, ticker))
            conn.commit()
        conn.close()
        return True
    except: return False

def remove_ticker_from_db(username, ticker):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM user_portfolio WHERE username=%s AND ticker=%s", (username, ticker))
        conn.commit()
        conn.close()
    except: pass

def get_user_portfolio(username):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT ticker FROM user_portfolio WHERE username=%s", (username,))
        rows = cursor.fetchall()
        conn.close()
        return [r[0] for r in rows]
    except: return []

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

            avg_vol = df['Volume'].rolling(20).mean().iloc[-1]
            curr_vol = df['Volume'].iloc[-1]
            vol_stat = "SPIKE" if curr_vol > (avg_vol * 1.5) else "NORMAL"
            
            sql = "INSERT INTO stock_cache (ticker, current_price, day_change, rsi, trend_status, volume_status) VALUES (%s, %s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE current_price=%s, day_change=%s, rsi=%s, trend_status=%s, volume_status=%s"
            cursor.execute(sql, (t, price, change, rsi, trend, vol_stat, price, change, rsi, trend, vol_stat))
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
    vol = row.get('volume_status', 'NORMAL')
    
    if trend == 'DOWNTREND': score += 20
    if trend == 'UPTREND': score -= 15
    if rsi > 70: score += 20
    if rsi < 30: score -= 10
    if vol == "SPIKE": score += 10 
    
    final = max(0, min(100, int(score)))
    if final > 60: return final, "HIGH", "#ef4444", "badge-high"
    if final > 40: return final, "MEDIUM", "#fbbf24", "badge-med"
    return final, "LOW", "#4ade80", "badge-low"

# 4. UI COMPONENTS
def create_gauge_html(score, label, color):
    # Fixed Text Position: Lifted 'y' from 105 to 100 to clear the bottom
    radius = 80
    circumference = 3.14159 * radius
    fill_amount = (score / 100) * circumference
    
    # ADDED: Top Label HTML
    header_html = f'<div style="text-align:center; color:#94a3b8; font-size:0.8rem; font-weight:bold; letter-spacing:1px; margin-bottom:5px;">PORTFOLIO RISK</div>'
    
    svg = f'<svg viewBox="0 0 200 120" style="width: 100%; height: auto;">'
    svg += '<defs><linearGradient id="grad1" x1="0%" y1="0%" x2="100%" y2="0%"><stop offset="0%" style="stop-color:#4ade80;stop-opacity:1" /><stop offset="50%" style="stop-color:#fbbf24;stop-opacity:1" /><stop offset="100%" style="stop-color:#ef4444;stop-opacity:1" /></linearGradient></defs>'
    svg += f'<path d="M 20 100 A 80 80 0 0 1 180 100" fill="none" stroke="#334155" stroke-width="15" stroke-linecap="round" />'
    svg += f'<path d="M 20 100 A 80 80 0 0 1 180 100" fill="none" stroke="url(#grad1)" stroke-width="15" stroke-linecap="round" stroke-dasharray="{fill_amount}, 1000" />'
    svg += f'<text x="100" y="80" font-family="sans-serif" font-size="38" font-weight="bold" fill="white" text-anchor="middle">{score}</text>'
    svg += f'<text x="100" y="100" font-family="sans-serif" font-size="12" font-weight="bold" fill="{color}" text-anchor="middle" letter-spacing="2">{label}</text></svg>'
    
    return f'<div class="card" style="padding-bottom:0; margin-bottom: 0px;">{header_html}{svg}</div>'

# Standard wide card for Portfolio/Scanner tabs
def render_stock_card(row):
    score, label, color, css = calculate_risk(row)
    price = float(row['current_price'])
    change = float(row['day_change'])
    c_color = "#4ade80" if change >= 0 else "#ef4444"
    arrow = "▲" if change >= 0 else "▼"
    ticker = row['ticker']
    trend = row.get('trend_status', 'N/A')
    
    html = f'<div class="card" style="display: flex; justify-content: space-between; align-items: center;"><div><div style="font-weight:bold; font-size:1.1rem; color:white;">{ticker}</div><div style="font-size:0.8rem; color:#94a3b8;">Trend: {trend}</div></div><div style="text-align: right; flex-grow:1; padding-right:15px;"><div style="color:white; font-weight:bold;">${price:,.2f}</div><div style="color:{c_color}; font-size:0.8rem;">{arrow} {change:.2f}%</div></div><div class="{css} badge">{label}</div></div>'
    st.markdown(html, unsafe_allow_html=True)

# NEW: Compact grid card for Home tab "At a Glance"
def render_small_stock_card(row):
    score, label, color, css = calculate_risk(row)
    price = float(row['current_price'])
    change = float(row['day_change'])
    c_color = "#4ade80" if change >= 0 else "#ef4444"
    arrow = "▲" if change >= 0 else "▼"
    ticker = row['ticker']
    
    html = f"""
    <div class="card" style="padding: 15px; height: 100%; display: flex; flex-direction: column; justify-content: space-between;">
        <div style="font-weight:bold; font-size:1.1rem; color:white; margin-bottom: 5px;">{ticker}</div>
        <div style="font-size:0.9rem; color:{c_color}; font-weight:bold; margin-bottom: 10px;">{arrow} {change:.2f}%</div>
         <div style="display: flex; align-items: center;">
            <div style="width: 8px; height: 8px; border-radius: 50%; background-color: {color}; margin-right: 6px;"></div>
            <div style="font-size:0.75rem; color:#94a3b8;">Risk: {label}</div>
        </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)

init_db()

# GLOBAL CSS
st.markdown("""<style>
    .stApp { background-color: #0f1219; color: #e0e6ed; } 
    .card { background-color: #1a1f2b; border-radius: 16px; padding: 20px; margin-bottom: 12px; border: 1px solid #2d3748; box-shadow: 0 4px 6px rgba(0,0,0,0.3); } 
    .badge { padding: 4px 8px; border-radius: 6px; font-size: 0.75rem; font-weight: bold; } 
    .badge-high { background: rgba(239, 68, 68, 0.2); color: #ef4444; } 
    .badge-med { background: rgba(251, 191, 36, 0.2); color: #fbbf24; } 
    .badge-low { background: rgba(74, 222, 128, 0.2); color: #4ade80; } 
    .block-container { padding-top: 1rem; padding-bottom: 5rem; } 
    input { color: black !important; }
    
    header {visibility: hidden;}
    footer {visibility: hidden;}
</style>""", unsafe_allow_html=True)

# LOGIN
if "token" not in st.query_params:
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        if os.path.exists("logo.png"):
            st.image("logo.png", width=200)
        else:
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

# MAIN APP
username = get_user_from_token(st.query_params["token"])
if not username:
    st.error("Session Expired")
    st.stop()

# --- CUSTOM NAVIGATION STATE ---
active_tab = st.query_params.get("tab", "home")

# 1. HOME SCREEN
if active_tab == "home":
    # Custom Smaller Header
    st.markdown(f"<div style='font-size: 24px; font-weight: 800; color: white; margin-bottom: 15px;'>Hi, {username}</div>", unsafe_allow_html=True)
    
    my_portfolio = get_user_portfolio(username)
    if not my_portfolio:
        st.info("No stocks. Go to Portfolio tab.")
    else:
        if st.button("🔄 Refresh", key="ref_home"):
            with st.spinner("Checking market..."):
                update_stock_data(my_portfolio)
        
        data = get_cached_data(my_portfolio)
        
        if data:
            avg_risk = sum([calculate_risk(x)[0] for x in data]) / len(data)
            r_score, r_label, r_color, _ = calculate_risk({'trend_status':'N', 'rsi':50})
            if avg_risk > 60: r_label, r_color = "HIGH", "#ef4444"
            elif avg_risk > 40: r_label, r_color = "MEDIUM", "#fbbf24"
            else: r_label, r_color = "LOW", "#4ade80"

            st.markdown(create_gauge_html(int(avg_risk), r_label, r_color), unsafe_allow_html=True)
            
            # --- SUMMARY STATS ---
            highest_risk_stock = max(data, key=lambda x: calculate_risk(x)[0])
            most_volatile_stock = max(data, key=lambda x: abs(float(x['day_change'])))
            
            st.markdown(f"""
            <div style="display:flex; justify-content:space-between; background:#151922; padding:15px; border-radius:0 0 16px 16px; margin-top:-14px; margin-bottom:20px; border:1px solid #2d3748; border-top:none;">
                <div style="text-align:center; width:50%; border-right:1px solid #2d3748;">
                    <div style="color:#94a3b8; font-size:0.7rem; text-transform:uppercase;">Highest Risk</div>
                    <div style="color:white; font-weight:bold; font-size:1.1rem;">{highest_risk_stock['ticker']}</div>
                </div>
                <div style="text-align:center; width:50%;">
                    <div style="color:#94a3b8; font-size:0.7rem; text-transform:uppercase;">Most Volatile</div>
                    <div style="color:white; font-weight:bold; font-size:1.1rem;">{most_volatile_stock['ticker']}</div>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            st.write("### At a Glance")
            # New Horizontal Grid Layout for Top 3
            c1, c2, c3 = st.columns(3)
            top_3 = data[:3]
            
            if len(top_3) > 0:
                with c1: render_small_stock_card(top_3[0])
            if len(top_3) > 1:
                with c2: render_small_stock_card(top_3[1])
            if len(top_3) > 2:
                with c3: render_small_stock_card(top_3[2])


# 2. PORTFOLIO SCREEN
elif active_tab == "portfolio":
    st.markdown(f"<div style='font-size: 24px; font-weight: 800; color: white; margin-bottom: 15px;'>Manage Portfolio</div>", unsafe_allow_html=True)
    
    col1, col2 = st.columns([2, 1])
    with col1:
        new_ticker = st.text_input("Ticker Symbol").upper()
    with col2:
        st.write("") 
        st.write("") 
        if st.button("Add"):
            if new_ticker and add_ticker_to_db(username, new_ticker):
                st.success(f"Added {new_ticker}")
                st.rerun()
    
    st.divider()
    my_stocks = get_user_portfolio(username)
    if my_stocks:
        for t in my_stocks:
            c1, c2 = st.columns([3, 1])
            with c1:
                st.markdown(f"<div style='font-size:1.2rem; font-weight:bold; color:white; padding:5px;'>{t}</div>", unsafe_allow_html=True)
            with c2:
                if st.button("🗑️", key=f"del_{t}"):
                    remove_ticker_from_db(username, t)
                    st.rerun()

# 3. SCANNER SCREEN
elif active_tab == "scanner":
    st.markdown(f"<div style='font-size: 24px; font-weight: 800; color: white; margin-bottom: 5px;'>Scanner</div>", unsafe_allow_html=True)
    st.caption("Auto-generated from your portfolio")
    
    my_portfolio = get_user_portfolio(username)
    data = get_cached_data(my_portfolio)
    
    if not data:
        st.info("No data to scan.")
    else:
        found_any = False
        st.markdown("**📉 Oversold (RSI < 35)**")
        for row in data:
            if float(row['rsi']) < 35: 
                render_stock_card(row)
                found_any = True
        
        st.markdown("**🔊 Volume Spikes**")
        for row in data:
            if row.get('volume_status') == "SPIKE":
                render_stock_card(row)
                found_any = True

        if not found_any:
            st.success("No alerts found.")

# --- CUSTOM HTML BOTTOM NAV (High Contrast & Fixed Color) ---
current_token = st.query_params.get("token", "")

nav_html = f"""
<style>
    .nav-container {{
        position: fixed;
        bottom: 0;
        left: 0;
        width: 100%;
        height: 60px;
        background-color: #1a1f2b;
        border-top: 1px solid #2d3748;
        display: flex;
        justify-content: space-around;
        align-items: center;
        z-index: 9999;
    }}
    .nav-link {{
        text-decoration: none;
        color: #94a3b8 !important; /* Force inactive color */
        font-family: sans-serif;
        font-size: 12px;
        text-align: center;
        width: 100%;
        padding: 5px 0;
    }}
    .nav-link:hover {{
        color: white !important;
    }}
    .nav-icon {{
        font-size: 20px;
        display: block;
        margin-bottom: 2px;
    }}
    .active {{
        color: #3b82f6 !important; /* Force active color */
        font-weight: bold;
    }}
</style>
<div class="nav-container">
    <a href="?token={current_token}&tab=home" class="nav-link {'active' if active_tab == 'home' else ''}">
        <span class="nav-icon">🏠</span>Home
    </a>
    <a href="?token={current_token}&tab=portfolio" class="nav-link {'active' if active_tab == 'portfolio' else ''}">
        <span class="nav-icon">📂</span>Stocks
    </a>
    <a href="?token={current_token}&tab=scanner" class="nav-link {'active' if active_tab == 'scanner' else ''}">
        <span class="nav-icon">📡</span>Scan
    </a>
</div>
"""
st.markdown(nav_html, unsafe_allow_html=True)
