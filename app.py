import streamlit as st
import mysql.connector
import yfinance as yf
import uuid
import os
import pandas as pd
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
        cursor.execute("CREATE TABLE IF NOT EXISTS user_profiles (username VARCHAR(255) PRIMARY KEY, user_data TEXT, pin VARCHAR(50))")
        cursor.execute("CREATE TABLE IF NOT EXISTS user_sessions (token VARCHAR(255) PRIMARY KEY, username VARCHAR(255), created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
        cursor.execute("CREATE TABLE IF NOT EXISTS user_portfolio (id INT NOT NULL AUTO_INCREMENT, username VARCHAR(255), ticker VARCHAR(20), PRIMARY KEY (id))")
        
        sql = """CREATE TABLE IF NOT EXISTS stock_cache (
            ticker VARCHAR(20) PRIMARY KEY, 
            current_price DECIMAL(20, 4), 
            day_change DECIMAL(10, 2), 
            rsi DECIMAL(10, 2), 
            trend_status VARCHAR(20), 
            volume_status VARCHAR(20), 
            range_loc DECIMAL(10, 2),
            volatility DECIMAL(10, 2),
            debt_ratio DECIMAL(10, 2),
            days_to_earnings INT,
            market_cap BIGINT,
            eps DECIMAL(10, 2),
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        )"""
        cursor.execute(sql)
        
        try: cursor.execute("ALTER TABLE stock_cache ADD COLUMN market_cap BIGINT DEFAULT 0")
        except: pass
        try: cursor.execute("ALTER TABLE stock_cache ADD COLUMN eps DECIMAL(10, 2) DEFAULT 0")
        except: pass
        try: cursor.execute("ALTER TABLE stock_cache ADD COLUMN days_to_earnings INT DEFAULT 999")
        except: pass
            
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

            # Technicals
            price = float(df['Close'].iloc[-1])
            prev = float(df['Close'].iloc[-2])
            change = ((price - prev) / prev) * 100
            
            delta = df['Close'].diff()
            up, down = delta.clip(lower=0), -1 * delta.clip(upper=0)
            rs = up.ewm(com=13, adjust=False).mean() / down.ewm(com=13, adjust=False).mean()
            rsi = 100 - (100 / (1 + rs)).iloc[-1]
            
            ma50 = df['Close'].rolling(50).mean().iloc[-1]
            trend = "UPTREND" if price > ma50 else "DOWNTREND"
            
            volatility = df['Close'].pct_change().std() * 100

            high_3m = df['Close'].max()
            low_3m = df['Close'].min()
            range_loc = 50
            if high_3m != low_3m:
                range_loc = ((price - low_3m) / (high_3m - low_3m)) * 100

            avg_vol = df['Volume'].rolling(20).mean().iloc[-1]
            curr_vol = df['Volume'].iloc[-1]
            vol_stat = "SPIKE" if curr_vol > (avg_vol * 1.5) else "NORMAL"

            # Fundamentals
            debt_ratio = 0
            days_to_earnings = 999 # Default high number so it doesn't show as "soon"
            market_cap = 0
            eps = 0
            
            try:
                ticker_obj = yf.Ticker(t)
                info = ticker_obj.info
                debt_ratio = info.get('debtToEquity', 0) or 0
                market_cap = info.get('marketCap', 0) or 0
                eps = info.get('trailingEps', 0) or 0
                
                cal = ticker_obj.calendar
                if cal is not None and not cal.empty:
                    # Look for earnings date
                    earnings_date = cal.iloc[0, 0]
                    if isinstance(earnings_date, (datetime, pd.Timestamp)):
                         delta_days = (earnings_date - datetime.now()).days
                         if delta_days >= 0:
                             days_to_earnings = delta_days
            except:
                pass 

            sql = """INSERT INTO stock_cache 
                     (ticker, current_price, day_change, rsi, trend_status, volume_status, range_loc, volatility, debt_ratio, days_to_earnings, market_cap, eps) 
                     VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) 
                     ON DUPLICATE KEY UPDATE 
                     current_price=%s, day_change=%s, rsi=%s, trend_status=%s, volume_status=%s, range_loc=%s, volatility=%s, debt_ratio=%s, days_to_earnings=%s, market_cap=%s, eps=%s"""
            
            vals = (t, price, change, rsi, trend, vol_stat, range_loc, volatility, debt_ratio, days_to_earnings, market_cap, eps,
                    price, change, rsi, trend, vol_stat, range_loc, volatility, debt_ratio, days_to_earnings, market_cap, eps)
            cursor.execute(sql, vals)
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
    reasons = [] 
    
    if row.get('trend_status') == 'DOWNTREND': score += 10
    else: score -= 10
    
    rsi = float(row.get('rsi', 50))
    if rsi > 70: score += 10
    if rsi < 30: score -= 10
    
    vol = float(row.get('volatility', 0))
    if vol > 3.0: 
        score += 10
        reasons.append("High Volatility")
        
    debt = float(row.get('debt_ratio', 0))
    if debt > 150: 
        score += 5
        reasons.append("High Debt")

    days = int(row.get('days_to_earnings', 999))
    if days < 10: 
        score += 15
        reasons.append("Earnings Soon")

    loc = float(row.get('range_loc', 50))
    if loc > 90: score += 10
    elif loc < 10: score -= 10
    
    if row.get('volume_status') == 'SPIKE':
        score += 5
        reasons.append("Vol Spike")

    mcap = float(row.get('market_cap', 0))
    if 0 < mcap < 250000000: 
        score += 15
        reasons.append("Micro Cap")
    elif 0 < mcap < 2000000000: 
        score += 5
    
    eps = float(row.get('eps', 0))
    if eps < 0:
        score += 10
        reasons.append("Unprofitable")

    final = max(0, min(100, int(score)))
    css, color, label = "badge-low", "#4ade80", "LOW"
    
    if final > 65: label, color, css = "HIGH", "#ef4444", "badge-high"
    elif final > 35: label, color, css = "MEDIUM", "#fbbf24", "badge-med"
        
    return final, label, color, css, reasons

# 4. UI GENERATORS
def create_gauge_html(score, label, color):
    radius = 80
    circumference = 3.14159 * radius
    fill_amount = (score / 100) * circumference
    header_html = f'<div style="text-align:center; color:#94a3b8; font-size:0.8rem; font-weight:bold; letter-spacing:1px; margin-bottom:5px;">PORTFOLIO RISK</div>'
    svg = f'<svg viewBox="0 0 200 120" style="width: 100%; height: auto;"><defs><linearGradient id="grad1" x1="0%" y1="0%" x2="100%" y2="0%"><stop offset="0%" style="stop-color:#4ade80;stop-opacity:1" /><stop offset="50%" style="stop-color:#fbbf24;stop-opacity:1" /><stop offset="100%" style="stop-color:#ef4444;stop-opacity:1" /></linearGradient></defs><path d="M 20 100 A 80 80 0 0 1 180 100" fill="none" stroke="#334155" stroke-width="15" stroke-linecap="round" /><path d="M 20 100 A 80 80 0 0 1 180 100" fill="none" stroke="url(#grad1)" stroke-width="15" stroke-linecap="round" stroke-dasharray="{fill_amount}, 1000" /><text x="100" y="80" font-family="sans-serif" font-size="38" font-weight="bold" fill="white" text-anchor="middle">{score}</text><text x="100" y="100" font-family="sans-serif" font-size="12" font-weight="bold" fill="{color}" text-anchor="middle" letter-spacing="2">{label}</text></svg>'
    return f'<div class="card" style="padding-bottom:0; margin-bottom: 0px;">{header_html}{svg}</div>'

def render_stock_card(row):
    score, label, color, css, reasons = calculate_risk(row)
    price = float(row['current_price'])
    change = float(row['day_change'])
    c_color = "#4ade80" if change >= 0 else "#ef4444"
    arrow = "▲" if change >= 0 else "▼"
    ticker = row['ticker']
    trend = row.get('trend_status', 'N/A')
    
    reason_html = ""
    if reasons:
        reason_html = f"<div style='font-size:0.65rem; color:#94a3b8; margin-top:4px;'>⚠️ {', '.join(reasons[:2])}</div>"
    
    html = f'<div class="card" style="display: flex; justify-content: space-between; align-items: center;"><div><div style="font-weight:bold; font-size:1.1rem; color:white;">{ticker}</div><div style="font-size:0.8rem; color:#94a3b8;">Trend: {trend}</div>{reason_html}</div><div style="text-align: right; flex-grow:1; padding-right:15px;"><div style="color:white; font-weight:bold;">${price:,.2f}</div><div style="color:{c_color}; font-size:0.8rem;">{arrow} {change:.2f}%</div></div><div class="{css} badge">{label}</div></div>'
    st.markdown(html, unsafe_allow_html=True)

def render_horizontal_grid(rows):
    html_content = '<div class="scrolling-wrapper">'
    for row in rows:
        score, label, color, css, reasons = calculate_risk(row)
        change = float(row['day_change'])
        c_color = "#4ade80" if change >= 0 else "#ef4444"
        arrow = "▲" if change >= 0 else "▼"
        ticker = row['ticker']
        card = f'<div class="scrolling-card"><div style="font-weight:bold; font-size:1.1rem; color:white; margin-bottom: 4px;">{ticker}</div><div style="font-size:0.85rem; color:{c_color}; font-weight:bold; margin-bottom: 8px;">{arrow} {change:.2f}%</div><div style="display: flex; align-items: center;"><div style="width: 8px; height: 8px; border-radius: 50%; background-color: {color}; margin-right: 6px;"></div><div style="font-size:0.75rem; color:#94a3b8;">{label}</div></div></div>'
        html_content += card
    html_content += '</div>'
    st.markdown(html_content, unsafe_allow_html=True)

init_db()

st.markdown("""<style>
    .stApp { background-color: #0f1219; color: #e0e6ed; } 
    .card { background-color: #1a1f2b; border-radius: 16px; padding: 20px; margin-bottom: 12px; border: 1px solid #2d3748; box-shadow: 0 4px 6px rgba(0,0,0,0.3); } 
    .badge { padding: 4px 8px; border-radius: 6px; font-size: 0.75rem; font-weight: bold; } 
    .badge-high { background: rgba(239, 68, 68, 0.2); color: #ef4444; } 
    .badge-med { background: rgba(251, 191, 36, 0.2); color: #fbbf24; } 
    .badge-low { background: rgba(74, 222, 128, 0.2); color: #4ade80; } 
    .block-container { padding-top: 1rem; padding-bottom: 5rem; } 
    input { color: black !important; }
    header {visibility: hidden;} footer {visibility: hidden;}
    .scrolling-wrapper { display: flex; flex-wrap: nowrap; overflow-x: auto; -webkit-overflow-scrolling: touch; gap: 12px; padding-bottom: 10px; margin-bottom: 15px; -ms-overflow-style: none; scrollbar-width: none; }
    .scrolling-wrapper::-webkit-scrollbar { display: none; }
    .scrolling-card { flex: 0 0 auto; width: 130px; background-color: #1a1f2b; border: 1px solid #2d3748; border-radius: 12px; padding: 15px; }
</style>""", unsafe_allow_html=True)

# LOGIN
if "token" not in st.query_params:
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        if os.path.exists("logo.png"): st.image("logo.png", width=200)
        else: st.markdown("<h1 style='text-align:center;'>⚡ Penny Pulse</h1>", unsafe_allow_html=True)
    with st.form("login"):
        user = st.text_input("Username")
        pin = st.text_input("PIN", type="password")
        if st.form_submit_button("Login"):
            if check_login(user, pin):
                token = create_session(user)
                st.query_params["token"] = token
                st.rerun()
            else: st.error("Invalid PIN")
    st.stop()

username = get_user_from_token(st.query_params["token"])
if not username: st.error("Session Expired"); st.stop()

active_tab = st.query_params.get("tab", "home")

if active_tab == "home":
    st.markdown(f"<div style='font-size: 24px; font-weight: 800; color: white; margin-bottom: 15px;'>Hi, {username}</div>", unsafe_allow_html=True)
    my_portfolio = get_user_portfolio(username)
    if not my_portfolio: st.info("No stocks. Go to Portfolio tab.")
    else:
        if st.button("🔄 Refresh", key="ref_home"):
            with st.spinner("Analyzing fundamentals..."):
                update_stock_data(my_portfolio)
        data = get_cached_data(my_portfolio)
        if data:
            avg_risk = sum([calculate_risk(x)[0] for x in data]) / len(data)
            r_score, r_label, r_color, _, _ = calculate_risk({'trend_status':'N', 'rsi':50})
            if avg_risk > 65: r_label, r_color = "HIGH", "#ef4444"
            elif avg_risk > 35: r_label, r_color = "MEDIUM", "#fbbf24"
            else: r_label, r_color = "LOW", "#4ade80"
            st.markdown(create_gauge_html(int(avg_risk), r_label, r_color), unsafe_allow_html=True)
            
            # --- SUMMARY STATS (Adjusted Order) ---
            highest_risk_stock = max(data, key=lambda x: calculate_risk(x)[0])
            most_volatile_stock = max(data, key=lambda x: abs(float(x['day_change'])))
            
            # Find closest earning date (Anything positive)
            earnings_candidates = [d for d in data if d.get('days_to_earnings', 999) < 999]
            if earnings_candidates:
                next_earnings_stock = min(earnings_candidates, key=lambda x: int(x.get('days_to_earnings', 999)))
                earning_ticker = next_earnings_stock['ticker']
            else:
                earning_ticker = "-"

            st.markdown(f"""
            <div style="display:flex; justify-content:space-between; background:#151922; padding:15px; border-radius:0 0 16px 16px; margin-top:-14px; margin-bottom:20px; border:1px solid #2d3748; border-top:none;">
                <div style="text-align:center; width:33.3%; border-right:1px solid #2d3748;">
                    <div style="color:#94a3b8; font-size:0.6rem; text-transform:uppercase;">Highest Risk</div>
                    <div style="color:white; font-weight:bold; font-size:1rem;">{highest_risk_stock['ticker']}</div>
                </div>
                <div style="text-align:center; width:33.3%; border-right:1px solid #2d3748;">
                    <div style="color:#94a3b8; font-size:0.6rem; text-transform:uppercase;">Most Volatile</div>
                    <div style="color:white; font-weight:bold; font-size:1rem;">{most_volatile_stock['ticker']}</div>
                </div>
                <div style="text-align:center; width:33.3%;">
                    <div style="color:#94a3b8; font-size:0.6rem; text-transform:uppercase;">Next Earning</div>
                    <div style="color:white; font-weight:bold; font-size:1rem;">{earning_ticker}</div>
                </div>
            </div>
            """, unsafe_allow_html=True)
            st.write("### At a Glance")
            render_horizontal_grid(data)

elif active_tab == "portfolio":
    st.markdown(f"<div style='font-size: 24px; font-weight: 800; color: white; margin-bottom: 15px;'>Manage Portfolio</div>", unsafe_allow_html=True)
    col1, col2 = st.columns([2, 1])
    with col1: new_ticker = st.text_input("Ticker Symbol").upper()
    with col2:
        st.write(""); st.write("")
        if st.button("Add"):
            if new_ticker and add_ticker_to_db(username, new_ticker):
                st.success(f"Added {new_ticker}")
                st.rerun()
    st.divider()
    my_stocks = get_user_portfolio(username)
    if my_stocks:
        for t in my_stocks:
            c1, c2 = st.columns([3, 1])
            with c1: st.markdown(f"<div style='font-size:1.2rem; font-weight:bold; color:white; padding:5px;'>{t}</div>", unsafe_allow_html=True)
            with c2:
                if st.button("🗑️", key=f"del_{t}"):
                    remove_ticker_from_db(username, t)
                    st.rerun()

elif active_tab == "scanner":
    st.markdown(f"<div style='font-size: 24px; font-weight: 800; color: white; margin-bottom: 5px;'>Scanner</div>", unsafe_allow_html=True)
    st.caption("Auto-generated from your portfolio")
    my_portfolio = get_user_portfolio(username)
    data = get_cached_data(my_portfolio)
    if not data: st.info("No data to scan.")
    else:
        found_any = False
        st.markdown("**📉 Oversold (RSI < 35)**")
        for row in data:
            if float(row['rsi']) < 35: render_stock_card(row); found_any = True
        st.markdown("**🔊 Volume Spikes**")
        for row in data:
            if row.get('volume_status') == "SPIKE": render_stock_card(row); found_any = True
        st.markdown("**📅 Earnings Coming Soon**")
        for row in data:
            if int(row.get('days_to_earnings', 99)) < 14: render_stock_card(row); found_any = True
        if not found_any: st.success("No alerts found.")

current_token = st.query_params.get("token", "")
nav_html = f"""
<style>
    .nav-container {{ position: fixed; bottom: 0; left: 0; width: 100%; height: 60px; background-color: #1a1f2b; border-top: 1px solid #2d3748; display: flex; justify-content: space-around; align-items: center; z-index: 9999; }}
    a.nav-link, a.nav-link:visited, a.nav-link:hover, a.nav-link:active {{ text-decoration: none; color: #94a3b8; font-family: sans-serif; font-size: 12px; text-align: center; width: 100%; padding: 5px 0; }}
    a.nav-link:hover {{ color: white; }}
    .nav-icon {{ font-size: 20px; display: block; margin-bottom: 2px; }}
    a.active, a.active:visited {{ color: #3b82f6 !important; font-weight: bold; }}
</style>
<div class="nav-container">
    <a href="?token={current_token}&tab=home" class="nav-link {'active' if active_tab == 'home' else ''}"><span class="nav-icon">🏠</span>Home</a>
    <a href="?token={current_token}&tab=portfolio" class="nav-link {'active' if active_tab == 'portfolio' else ''}"><span class="nav-icon">📂</span>Stocks</a>
    <a href="?token={current_token}&tab=scanner" class="nav-link {'active' if active_tab == 'scanner' else ''}"><span class="nav-icon">📡</span>Scan</a>
</div>
"""
st.markdown(nav_html, unsafe_allow_html=True)
