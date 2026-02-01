import streamlit as st
import mysql.connector
import yfinance as yf
import requests
import uuid
import os
import pandas as pd
import pytz
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

# =========================================================
# 1. CONFIGURATION & CSS (MUST BE FIRST)
# =========================================================
st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="centered", initial_sidebar_state="collapsed")

# STRICT CSS: Dark Theme + Dropdown Fixes + Clean UI
st.markdown("""
    <style>
        /* 1. Reset & Layout */
        .block-container { padding-top: 0rem !important; padding-bottom: 5rem !important; }
        .stApp { background-color: #0f1219 !important; color: #e0e6ed !important; }
        
        /* 2. Form Inputs (Text, Number, Password) */
        input[type="text"], input[type="password"], input[type="number"] { 
            background-color: #1e293b !important; 
            color: white !important; 
            border: 1px solid #4ade80 !important; 
            border-radius: 8px; 
            padding: 10px;
        }
        div[data-baseweb="input"] { background-color: transparent !important; border: none; }
        
        /* 3. Dropdowns & Select Boxes (The Fix) */
        div[data-baseweb="select"] > div { 
            background-color: #1e293b !important; 
            color: white !important; 
            border: 1px solid #4ade80 !important; 
        }
        div[role="listbox"] ul { background-color: #1e293b !important; }
        li[role="option"] { color: white !important; background-color: #1e293b !important; }
        li[role="option"]:hover { background-color: #4ade80 !important; color: black !important; }
        div[data-baseweb="popover"] { background-color: #1e293b !important; }
        
        /* 4. Cards */
        .card { 
            background-color: #1a1f2b; 
            border-radius: 16px; 
            padding: 20px; 
            margin-bottom: 10px; 
            border: 1px solid #2d3748; 
            box-shadow: 0 4px 6px rgba(0,0,0,0.3); 
        }
        
        /* 5. Metrics Badge */
        .metric-box {
            background-color: #1e293b;
            border: 1px solid #2d3748;
            border-radius: 12px;
            padding: 15px;
            text-align: center;
            margin-bottom: 10px;
        }
        .metric-label { font-size: 0.8rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 1px; }
        .metric-value { font-size: 1.4rem; font-weight: bold; color: white; }
        .metric-sub { font-size: 0.85rem; }
        
        /* 6. Buttons */
        div.stButton > button {
            background: linear-gradient(135deg, #4ade80, #16a34a) !important; 
            color: white !important; 
            border: none; 
            border-radius: 8px; 
            font-weight: bold;
            width: 100%;
            padding: 12px 20px;
        }
        button[kind="secondary"] {
            background: #334155 !important;
            border: 1px solid #ef4444 !important;
            color: #ef4444 !important;
        }

        h1, h2, h3, p, label, span, div { color: #e0e6ed; }
        
        /* 7. Links */
        a { color: #ffffff !important; text-decoration: none !important; }
        a:hover { color: #4ade80 !important; }
        
        /* 8. Navigation */
        .nav-container { 
            position: fixed; bottom: 0; left: 0; width: 100%; height: 65px; 
            background-color: #0f1219; border-top: 1px solid #2d3748; 
            display: flex; justify-content: space-around; align-items: center; z-index: 99999; 
        }
        a.nav-link { text-decoration: none; font-size: 24px; text-align: center; cursor: pointer;}
        a.nav-link:hover { transform: scale(1.1); }
        
        /* 9. Scroller */
        .scrolling-wrapper { 
            display: flex; flex-wrap: nowrap; overflow-x: auto; gap: 12px; padding-bottom: 10px; 
            -ms-overflow-style: none; scrollbar-width: none; 
        }
        .scrolling-wrapper::-webkit-scrollbar { display: none; }
        
        /* Hide Default Header */
        header {visibility: hidden;} footer {visibility: hidden;} 
    </style>
""", unsafe_allow_html=True)

# Global Constants
MARKET_UNIVERSE = ["TSLA", "NVDA", "AMD", "AAPL", "PLTR", "SOFI", "MARA", "GME", "AMC", "COIN", "MSFT", "GOOG", "AMZN", "META", "NFLX", "RIVN", "LCID", "NIO", "DKNG", "HOOD", "PYPL", "SQ", "ROKU", "SHOP", "SPOT", "UBER", "ABNB", "RIOT", "CLSK", "HUT"]
DB_CONFIG = {
    "host": "atlanticcanadaschoice.com", 
    "user": "atlantic", 
    "password": "1q2w3e4R!!", 
    "database": "atlantic_pennypulse", 
    "connect_timeout": 30
}
OPENAI_KEY = st.secrets["openai"]["api_key"] if "openai" in st.secrets else None
token = st.query_params.get("token", None)

# =========================================================
# 2. FUNCTIONS (DEFINED BEFORE EXECUTION)
# =========================================================

def get_connection():
    return mysql.connector.connect(**DB_CONFIG)

def init_db():
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # Base Tables
        cursor.execute("CREATE TABLE IF NOT EXISTS user_profiles (username VARCHAR(255) PRIMARY KEY, pin VARCHAR(50), display_name VARCHAR(100), email VARCHAR(255), paper_balance DECIMAL(20,2) DEFAULT 10000.00)")
        cursor.execute("CREATE TABLE IF NOT EXISTS user_sessions (token VARCHAR(255) PRIMARY KEY, username VARCHAR(255))")
        cursor.execute("CREATE TABLE IF NOT EXISTS user_portfolio (id INT NOT NULL AUTO_INCREMENT, username VARCHAR(255), ticker VARCHAR(20), shares DECIMAL(10,4) DEFAULT 0, entry_price DECIMAL(20,4) DEFAULT 0, portfolio_type VARCHAR(20) DEFAULT 'REAL', is_active BOOLEAN DEFAULT TRUE, realized_pl DECIMAL(20,2) DEFAULT 0.00, PRIMARY KEY (id))")
        cursor.execute("CREATE TABLE IF NOT EXISTS user_alerts (id INT NOT NULL AUTO_INCREMENT PRIMARY KEY, username VARCHAR(255), ticker VARCHAR(20), condition_type VARCHAR(10), target_price DECIMAL(20,4), is_triggered BOOLEAN DEFAULT FALSE)")
        cursor.execute("CREATE TABLE IF NOT EXISTS stock_cache (ticker VARCHAR(20) PRIMARY KEY, company_name VARCHAR(255), current_price DECIMAL(20,4), day_change DECIMAL(10,2), rsi DECIMAL(10,2), trend_status VARCHAR(20), volume_status VARCHAR(20), range_loc DECIMAL(10,2), volatility DECIMAL(10,2), debt_ratio DECIMAL(10,2), days_to_earnings INT, market_cap BIGINT, eps DECIMAL(10,2), signal_tag VARCHAR(50), last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)")
        
        # Safe Migrations (EXPANDED TO PREVENT SYNTAX ERRORS)
        try: 
            cursor.execute("ALTER TABLE user_profiles ADD COLUMN paper_balance DECIMAL(20,2) DEFAULT 10000.00")
        except: pass
        try: 
            cursor.execute("ALTER TABLE user_portfolio ADD COLUMN portfolio_type VARCHAR(20) DEFAULT 'REAL'")
        except: pass
        try: 
            cursor.execute("ALTER TABLE user_portfolio ADD COLUMN is_active BOOLEAN DEFAULT TRUE")
        except: pass
        try: 
            cursor.execute("ALTER TABLE user_portfolio ADD COLUMN realized_pl DECIMAL(20,2) DEFAULT 0.00")
        except: pass
        try: 
            cursor.execute("ALTER TABLE stock_cache ADD COLUMN days_to_earnings INT DEFAULT 999")
        except: pass
        try: 
            cursor.execute("ALTER TABLE stock_cache ADD COLUMN company_name VARCHAR(255)")
        except: pass
        try: 
            cursor.execute("ALTER TABLE stock_cache ADD COLUMN signal_tag VARCHAR(50)")
        except: pass

        conn.close()
    except Exception as e:
        st.error(f"Database Error: {e}")

# --- Auth Functions ---
def login_user(u, p):
    conn = get_connection(); cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM user_profiles WHERE username=%s", (u,))
    row = cursor.fetchone(); conn.close()
    if row and str(row['pin']) == str(p): return row
    return None

def register_user(u, p, d, e):
    conn = get_connection(); cursor = conn.cursor()
    cursor.execute("SELECT username FROM user_profiles WHERE username=%s", (u,))
    if cursor.fetchone(): conn.close(); return False
    cursor.execute("INSERT INTO user_profiles (username, pin, display_name, email) VALUES (%s,%s,%s,%s)", (u, p, d, e))
    conn.commit(); conn.close(); return True

def create_session(u):
    t = str(uuid.uuid4()); conn = get_connection(); cursor = conn.cursor()
    cursor.execute("INSERT INTO user_sessions (token, username) VALUES (%s,%s)", (t, u))
    conn.commit(); conn.close(); return t

def get_user_from_token(t):
    conn = get_connection(); cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT s.username, p.display_name, p.paper_balance, p.email FROM user_sessions s JOIN user_profiles p ON s.username=p.username WHERE s.token=%s", (t,))
    row = cursor.fetchone(); conn.close()
    return row

def update_user_settings(username, display_name, email, new_pin=None):
    try:
        conn = get_connection(); cursor = conn.cursor()
        if new_pin: cursor.execute("UPDATE user_profiles SET display_name=%s, email=%s, pin=%s WHERE username=%s", (display_name, email, new_pin, username))
        else: cursor.execute("UPDATE user_profiles SET display_name=%s, email=%s WHERE username=%s", (display_name, email, username))
        conn.commit(); conn.close(); return True
    except: return False

# --- Data Functions ---
def get_news_data(ticker):
    news_results = []
    try:
        # RSS Direct Fetch
        url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            root = ET.fromstring(resp.content)
            for item in root.findall('.//item')[:4]:
                title = item.find('title').text if item.find('title') is not None else "No Title"
                link = item.find('link').text if item.find('link') is not None else "#"
                pub = "Yahoo Finance"
                news_results.append({'title': title, 'link': link, 'pub': pub, 'time': "Recent"})
    except: pass
    
    if not news_results:
        try:
            stock = yf.Ticker(ticker)
            for n in stock.news[:3]:
                news_results.append({'title': n.get('title', 'News'), 'link': n.get('link', '#'), 'pub': n.get('publisher', 'Yahoo'), 'time': 'Recent'})
        except: pass
    return news_results

def get_ai_analysis(ticker, headlines, current_data=None):
    if OPENAI_KEY and headlines and len(headlines) > 10:
        try:
            prompt = f"Analyze these headlines for {ticker}: {headlines} Return JSON: {{'summary': '1 sentence', 'score': 50}}"
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {OPENAI_KEY}"}
            data = {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": prompt}], "temperature": 0.3}
            response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=data, timeout=10)
            if response.status_code == 200:
                content = response.json()['choices'][0]['message']['content']
                if "```" in content: content = content.split("```")[1].replace("json", "").strip()
                parsed = json.loads(content)
                return parsed.get('summary'), parsed.get('score'), "AI"
        except: pass

    if current_data:
        rsi = float(current_data.get('rsi') or 50)
        trend = current_data.get('trend_status', 'NEUTRAL')
        if rsi > 70: return "Technical: Overbought (RSI > 70). Risk of pullback.", 30, "TECH"
        elif rsi < 30: return "Technical: Oversold (RSI < 30). Potential bounce.", 80, "TECH"
        elif trend == "UPTREND": return "Technical: Strong Uptrend detected.", 75, "TECH"
        return "Market sentiment is neutral. Monitor volume.", 50, "TECH"
    return "No Data Available", 50, "NONE"

def calculate_risk(row, ai_score=None):
    s = 50; reasons = []
    if row.get('trend_status') == 'DOWNTREND': s += 10
    else: s -= 10
    rsi = float(row.get('rsi') or 50)
    if rsi > 70: s += 10
    elif rsi < 30: s -= 10
    vol = float(row.get('volatility') or 0)
    if vol > 3.0: s += 10
    if ai_score is not None:
        adj = (50 - ai_score) * 0.5
        s += adj
    final = max(0, min(100, int(s)))
    color = "#4ade80" 
    label = "LOW"
    if final > 65: color = "#ef4444"; label="HIGH"
    elif final > 35: color = "#fbbf24"; label="MEDIUM"
    return final, label, color, "badge-mix", reasons

def calculate_signal(df):
    try:
        price = float(df['Close'].iloc[-1]); vol = float(df['Volume'].iloc[-1])
        avg_vol = float(df['Volume'].rolling(20).mean().iloc[-1]); high_3m = float(df['Close'].max())
        prev = float(df['Close'].iloc[-2])
        
        delta = df['Close'].diff(); up, down = delta.clip(lower=0), -1 * delta.clip(upper=0)
        rs = up.ewm(com=13, adjust=False).mean() / down.ewm(com=13, adjust=False).mean()
        rsi = 100 - (100 / (1 + rs)).iloc[-1]

        if price >= (high_3m * 0.95): return "🔥 Near Breakout"
        if vol > (avg_vol * 1.5): return "📊 Unusual Volume"
        if ((price-prev)/prev > 0.03) and rsi > 50: return "⚡ Momentum Gainer"
        if rsi < 40: return "📉 Oversold Watch"
    except: return None
    return None

def update_stock_data(tickers, username):
    all_tickers = list(set(tickers + MARKET_UNIVERSE))
    if not all_tickers: return
    try: data = yf.download(" ".join(all_tickers), period="3mo", group_by='ticker', threads=True, progress=False)
    except: return

    conn = get_connection(); cursor = conn.cursor()
    for t in all_tickers:
        try:
            if len(all_tickers) > 1: df = data[t]
            else: df = data
            df = df.dropna()
            if df.empty: continue
            
            price = float(df['Close'].iloc[-1]); prev = float(df['Close'].iloc[-2])
            change = ((price - prev)/prev)*100
            
            delta = df['Close'].diff(); up, down = delta.clip(lower=0), -1 * delta.clip(upper=0)
            rs = up.ewm(com=13, adjust=False).mean() / down.ewm(com=13, adjust=False).mean()
            rsi = 100 - (100 / (1 + rs)).iloc[-1]
            
            ma50 = df['Close'].rolling(50).mean().iloc[-1] if len(df) >= 50 else df['Close'].mean()
            trend = "UPTREND" if price > ma50 else "DOWNTREND"
            vol = df['Close'].pct_change().std() * 100
            
            avg_v = df['Volume'].rolling(20).mean().iloc[-1]; cur_v = df['Volume'].iloc[-1]
            v_stat = "SPIKE" if cur_v > (avg_v * 1.5) else "NORMAL"
            
            high3 = df['Close'].max(); low3 = df['Close'].min(); r_loc = 50
            if high3 != low3: r_loc = ((price-low3)/(high3-low3))*100

            signal = calculate_signal(df)
            debt=0; mcap=0; eps=0; days=999; name=t
            try:
                io = yf.Ticker(t).info
                name = io.get('shortName') or t
                try:
                    cal = io.get('calendar', {})
                    if 'Earnings Date' in cal:
                        e_date = cal['Earnings Date'][0] 
                        days = (e_date.date() - datetime.now().date()).days
                except: pass
            except: pass

            sql = """INSERT INTO stock_cache (ticker, company_name, current_price, day_change, rsi, trend_status, volume_status, range_loc, volatility, debt_ratio, days_to_earnings, market_cap, eps, signal_tag) 
                     VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE 
                     company_name=%s, current_price=%s, day_change=%s, rsi=%s, trend_status=%s, volume_status=%s, range_loc=%s, volatility=%s, debt_ratio=%s, 
                     days_to_earnings=%s, market_cap=%s, eps=%s, signal_tag=%s"""
            vals = (t, name, price, change, rsi, trend, v_stat, r_loc, vol, debt, days, mcap, eps, signal,
                    name, price, change, rsi, trend, v_stat, r_loc, vol, debt, days, mcap, eps, signal)
            cursor.execute(sql, vals)
        except: continue
    conn.commit(); conn.close()

def get_watchlist_candidates():
    conn = get_connection(); cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM stock_cache WHERE signal_tag IS NOT NULL AND signal_tag != 'None' ORDER BY ABS(day_change) DESC LIMIT 10")
    rows = cursor.fetchall()
    filtered = [r for r in rows if "GC" not in r['ticker'] and "SI" not in r['ticker']][:3]
    if not filtered:
        cursor.execute("SELECT * FROM stock_cache ORDER BY ABS(day_change) DESC LIMIT 10")
        rows = cursor.fetchall()
        filtered = [r for r in rows if "GC" not in r['ticker'] and "SI" not in r['ticker']][:3]
        for r in filtered: r['signal_tag'] = "High Volatility" 
    conn.close()
    return filtered

def get_cached_data_map(tickers):
    if not tickers: return {}
    conn = get_connection(); cursor = conn.cursor(dictionary=True)
    format_strings = ','.join(['%s'] * len(tickers))
    cursor.execute(f"SELECT * FROM stock_cache WHERE ticker IN ({format_strings})", tuple(tickers))
    rows = cursor.fetchall(); conn.close()
    return {row['ticker']: row for row in rows}

def get_single_stock(ticker):
    conn = get_connection(); cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM stock_cache WHERE ticker=%s", (ticker,))
    row = cursor.fetchone(); conn.close()
    return row

def get_portfolio_details(username, ptype):
    # Only return ACTIVE stocks for the list
    conn = get_connection(); cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM user_portfolio WHERE username=%s AND portfolio_type=%s AND is_active=TRUE", (username, ptype))
    rows = cursor.fetchall(); conn.close()
    return rows

def get_portfolio_summary(username, ptype):
    # Calculate Total Unrealized + Realized P/L
    conn = get_connection(); cursor = conn.cursor(dictionary=True)
    
    # 1. Get Realized P/L from inactive stocks
    cursor.execute("SELECT SUM(realized_pl) as realized FROM user_portfolio WHERE username=%s AND portfolio_type=%s AND is_active=FALSE", (username, ptype))
    realized_row = cursor.fetchone()
    realized = float(realized_row['realized'] or 0)
    
    # 2. Get Unrealized P/L from active stocks
    cursor.execute("SELECT p.ticker, p.shares, p.entry_price, s.current_price, s.day_change FROM user_portfolio p LEFT JOIN stock_cache s ON p.ticker = s.ticker WHERE p.username=%s AND p.portfolio_type=%s AND p.is_active=TRUE", (username, ptype))
    active_rows = cursor.fetchall()
    
    unrealized = 0.0
    day_pl = 0.0
    
    for r in active_rows:
        if r['current_price']:
            curr = float(r['current_price'])
            entry = float(r['entry_price'])
            shares = float(r['shares'])
            unrealized += (curr - entry) * shares
            
            # Day P/L approximation
            pct = float(r['day_change'])
            prev_close = curr / (1 + (pct/100))
            day_pl += (curr - prev_close) * shares
            
    conn.close()
    total_pl = realized + unrealized
    return total_pl, day_pl

def deactivate_stock(username, ticker, ptype):
    # "Soft Delete": Mark inactive and calculate final P/L
    conn = get_connection(); cursor = conn.cursor()
    
    # Get current details to freeze P/L
    cursor.execute("SELECT p.shares, p.entry_price, s.current_price FROM user_portfolio p LEFT JOIN stock_cache s ON p.ticker = s.ticker WHERE p.username=%s AND p.ticker=%s AND p.portfolio_type=%s", (username, ticker, ptype))
    row = cursor.fetchone()
    
    if row:
        shares, entry, curr = row
        if curr:
            final_pl = (float(curr) - float(entry)) * float(shares)
            cursor.execute("UPDATE user_portfolio SET is_active=FALSE, realized_pl=%s WHERE username=%s AND ticker=%s AND portfolio_type=%s", (final_pl, username, ticker, ptype))
        else:
            # Fallback if no price available, just mark inactive
            cursor.execute("UPDATE user_portfolio SET is_active=FALSE WHERE username=%s AND ticker=%s AND portfolio_type=%s", (username, ticker, ptype))
            
    conn.commit(); conn.close()

def add_ticker_to_db(username, ticker, shares, price, ptype):
    conn = get_connection(); cursor = conn.cursor()
    # Check if exists (reactivate if so)
    cursor.execute("SELECT id FROM user_portfolio WHERE username=%s AND ticker=%s AND portfolio_type=%s", (username, ticker, ptype))
    existing = cursor.fetchone()
    
    if existing:
        cursor.execute("UPDATE user_portfolio SET shares=%s, entry_price=%s, is_active=TRUE WHERE id=%s", (shares, price, existing[0]))
    else:
        cursor.execute("INSERT INTO user_portfolio (username, ticker, shares, entry_price, portfolio_type, is_active) VALUES (%s,%s,%s,%s,%s, TRUE)", (username, ticker, shares, price, ptype))
    conn.commit(); conn.close()

def update_ticker_in_db(username, ticker, shares, price, ptype):
    conn = get_connection(); cursor = conn.cursor()
    cursor.execute("UPDATE user_portfolio SET shares=%s, entry_price=%s WHERE username=%s AND ticker=%s AND portfolio_type=%s", (shares, price, username, ticker, ptype))
    conn.commit(); conn.close()

def add_alert(username, ticker, condition, price):
    conn = get_connection(); cursor = conn.cursor()
    if ticker == "ALL STOCKS":
        # Add alert for ALL active stocks
        cursor.execute("SELECT ticker FROM user_portfolio WHERE username=%s AND is_active=TRUE", (username,))
        rows = cursor.fetchall()
        for r in rows:
            t = r[0]
            # Get current price to calculate target
            cursor.execute("SELECT current_price FROM stock_cache WHERE ticker=%s", (t,))
            p_row = cursor.fetchone()
            if p_row and p_row[0]:
                curr = float(p_row[0])
                # Calculate target based on % movement logic if input is small (e.g. 5 means 5%)
                # Assuming user input is % move if < 50, else explicit price. 
                # Simplification: If Price < 100, treat as Target Price.
                target = price 
                try: cursor.execute("INSERT INTO user_alerts (username, ticker, condition_type, target_price) VALUES (%s, %s, %s, %s)", (username, t, condition, target))
                except: pass
    else:
        try: cursor.execute("INSERT INTO user_alerts (username, ticker, condition_type, target_price) VALUES (%s, %s, %s, %s)", (username, ticker, condition, price))
        except: pass
    conn.commit(); conn.close()

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

# --- UI Functions ---
def render_navbar(token, mode):
    mode_arg = "&mode=PAPER" if mode == "PAPER" else ""
    st.markdown(f"""
    <div class="nav-container">
        <a href="?token={token}&tab=home{mode_arg}" class="nav-link">🏠</a>
        <a href="?token={token}&tab=portfolio{mode_arg}" class="nav-link">📂</a>
        <a href="?token={token}&tab=alerts{mode_arg}" class="nav-link">🔔</a>
        <a href="?token={token}&tab=scanner{mode_arg}" class="nav-link">📡</a>
        <a href="?token={token}&tab=settings{mode_arg}" class="nav-link">⚙️</a>
    </div>
    """, unsafe_allow_html=True)

def create_gauge_html(score, label, color, size="big"):
    rad = 80 if size == "big" else 60
    vb = "0 0 200 120" if size == "big" else "0 0 160 100"
    fs = "38" if size == "big" else "28"
    fill = (score / 100) * (3.14159 * rad)
    header = f'<div style="text-align:center; color:#94a3b8; font-size:0.8rem; font-weight:bold; letter-spacing:1px; margin-bottom:5px;">PORTFOLIO RISK</div>' if size == "big" else ""
    svg = f'<svg viewBox="{vb}" style="width:100%; height:auto;"><defs><linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="0%"><stop offset="0%" style="stop-color:#4ade80"/><stop offset="50%" style="stop-color:#fbbf24"/><stop offset="100%" style="stop-color:#ef4444"/></linearGradient></defs><path d="M 20 100 A {rad} {rad} 0 0 1 {20+rad*2} 100" fill="none" stroke="#334155" stroke-width="15" stroke-linecap="round"/><path d="M 20 100 A {rad} {rad} 0 0 1 {20+rad*2} 100" fill="none" stroke="url(#g)" stroke-width="15" stroke-linecap="round" stroke-dasharray="{fill}, 1000"/><text x="{20+rad}" y="{80 if size=="big" else 85}" font-family="sans-serif" font-size="{fs}" font-weight="bold" fill="white" text-anchor="middle">{score}</text><text x="{20+rad}" y="100" font-family="sans-serif" font-size="12" font-weight="bold" fill="{color}" text-anchor="middle" letter-spacing="2">{label}</text></svg>'
    return f'<div class="card" style="padding-bottom:0; margin-bottom:0;">{header}{svg}</div>' if size=="big" else f'<div style="margin-bottom:15px;">{svg}</div>'

def render_portfolio_row(row, data, token):
    risk, label, color, _, _ = calculate_risk(data)
    price = float(data['current_price'])
    change = float(data['day_change'])
    change_color = "#4ade80" if change >= 0 else "#ef4444"
    arrow = "▲" if change >= 0 else "▼"
    
    shares = float(row['shares'])
    entry = float(row['entry_price'])
    
    pl_html = ""
    if shares > 0 and entry > 0:
        val = shares * price
        cost = shares * entry
        pl = val - cost
        pl_pct = (pl / cost) * 100 if cost > 0 else 0
        pl_color = "#4ade80" if pl >= 0 else "#ef4444"
        pl_html = f"<div style='color:{pl_color}; font-size:0.75rem; margin-top:2px;'>{int(shares)} @ ${entry:.2f} • ${pl:,.2f} ({pl_pct:.1f}%)</div>"
    elif shares > 0:
        pl_html = f"<div style='color:#94a3b8; font-size:0.75rem; margin-top:2px;'>{int(shares)} Shares</div>"

    link = f"?token={token}&ticker={row['ticker']}"
    
    html = f"""
    <a href="{link}" target="_self" style="text-decoration:none;">
        <div class="card" style="display:flex; justify-content:space-between; align-items:center; border-left: 4px solid {color};">
            <div>
                <div style="display:flex; align-items:center; gap:8px;">
                    <div style="font-weight:bold; font-size:1.1rem; color:white;">{row['ticker']}</div>
                    <div style="font-size:0.6rem; background:{color}; color:black; padding:2px 6px; border-radius:4px; font-weight:bold;">RISK: {risk}</div>
                </div>
                <div style="font-size:0.8rem; color:#94a3b8;">{data.get('company_name', row['ticker'])}</div>
                {pl_html}
            </div>
            <div style="text-align:right;">
                <div style="color:white; font-weight:bold;">${price:,.2f}</div>
                <div style="color:{change_color}; font-size:0.8rem;">{arrow} {change:.2f}%</div>
            </div>
        </div>
    </a>
    """
    st.markdown(html, unsafe_allow_html=True)

def render_compact_watchlist(rows_list, current_token):
    h = '<div class="scrolling-wrapper">'
    for row in rows_list:
        signal = row.get('signal_tag') or "Active"
        risk, _, color, _, _ = calculate_risk(row)
        link = f"?token={current_token}&ticker={row['ticker']}"
        h += f"<a href='{link}' target='_self' style='text-decoration:none; color:inherit; flex: 1; min-width: 0;'><div style='background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); border: 1px solid #334155; border-radius: 8px; padding: 10px; height: 100%; display: flex; flex-direction: column; justify-content: space-between;'><div style='font-weight:bold; font-size:0.95rem; color:white; margin-bottom:4px;'>{row['ticker']}</div><div style='font-size:0.65rem; color:#facc15; font-weight:bold; margin-bottom:4px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;'>{signal}</div><div style='font-size:0.65rem; color:#94a3b8;'>Risk: <span style='color:{color}'>{risk}</span></div></div></a>"
    h += '</div>'
    st.markdown(h, unsafe_allow_html=True)

def render_simple_card(row, current_token):
    p = float(row['current_price']); ch = float(row['day_change']); cc = "#4ade80" if ch>=0 else "#ef4444"; arr = "▲" if ch>=0 else "▼"
    link = f"?token={current_token}&ticker={row['ticker']}"
    risk, _, _, _, _ = calculate_risk(row)
    html = f'<a href="{link}" target="_self" style="text-decoration:none; color:inherit; display:block;"><div class="card clickable-card" style="display:flex; justify-content:space-between; align-items:center; padding:15px;"><div><div style="font-weight:bold; font-size:1.1rem; color:white;">{row["ticker"]}</div><div style="font-size:0.8rem; color:#94a3b8;">Risk: {risk}</div></div><div style="text-align:right;"><div style="color:white; font-weight:bold;">${p:,.2f}</div><div style="color:{cc}; font-size:0.8rem;">{arr} {ch:.2f}%</div></div></div></a>'
    st.markdown(html, unsafe_allow_html=True)

def render_horizontal_grid(rows_dict, current_token):
    h = '<div class="scrolling-wrapper">'
    for ticker, row in rows_dict.items():
        ch = float(row['day_change']); cc = "#4ade80" if ch>=0 else "#ef4444"; arr = "▲" if ch>=0 else "▼"
        status = row.get('trend_status', 'Move')
        if row.get('volume_status') == 'SPIKE': status = "VOL SPIKE"
        link = f"?token={current_token}&ticker={ticker}"
        h += f'<a href="{link}" target="_self" style="text-decoration:none; color:inherit;"><div class="scrolling-card"><div style="font-weight:bold; font-size:1.1rem; color:white; margin-bottom:4px;">{ticker}</div><div style="font-size:0.85rem; color:{cc}; font-weight:bold; margin-bottom:8px;">{arr} {ch:.2f}%</div><div style="display:flex; align-items:center;"><div style="width:8px; height:8px; border-radius:50%; background-color:{cc}; margin-right:6px;"></div><div style="font-size:0.65rem; color:#94a3b8; text-transform:uppercase;">{status}</div></div></div></a>'
    h += '</div>'; st.markdown(h, unsafe_allow_html=True)

def get_greeting(name):
    hour = datetime.now(pytz.timezone('America/Halifax')).hour
    if hour < 12: return f"Good Morning, {name}"
    elif 12 <= hour < 18: return f"Good Afternoon, {name}"
    else: return f"Good Evening, {name}"

# =========================================================
# 3. MAIN EXECUTION (STARTS HERE)
# =========================================================

init_db()

# --- LOGIN SCREEN ---
if "token" not in st.query_params:
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        if os.path.exists("logo.png"):
            st.image("logo.png", width=200)
        else:
            st.markdown("<h1 style='text-align:center; color:#4ade80;'>⚡ Penny Pulse</h1>", unsafe_allow_html=True)
            
    tab1, tab2, tab3 = st.tabs(["Login", "Register", "Forgot PIN"])
    
    with tab1:
        with st.form("login_form"):
            u = st.text_input("Username")
            p = st.text_input("PIN", type="password")
            if st.form_submit_button("Login"):
                user_record = login_user(u, p)
                if user_record:
                    new_token = create_session(u)
                    st.query_params["token"] = new_token
                    st.rerun()
                else:
                    st.error("Invalid Credentials")
                    
    with tab2:
        with st.form("reg_form"):
            u = st.text_input("New Username")
            p = st.text_input("New PIN", type="password")
            d = st.text_input("Display Name")
            if st.form_submit_button("Create Account"):
                if register_user(u, p, d, ""):
                    st.success("Account created! Please login.")
                else:
                    st.error("Username taken.")
    with tab3:
        st.info("Contact support to reset PIN.")
        st.text_input("Username", key="forgot_u")
        st.button("Request Reset")
    st.stop()

# --- APP LOGIC (LOGGED IN) ---
user = get_user_from_token(token)
if not user:
    st.error("Session Expired")
    st.stop()

current_mode = st.query_params.get("mode", "REAL")
if current_mode not in ["REAL", "PAPER"]: current_mode = "REAL"

c1, c2 = st.columns([2, 1])
with c1:
    st.markdown(f"### Hello, {user['display_name']}")
with c2:
    is_paper = st.checkbox("Paper Trading", value=(current_mode=="PAPER"))
    new_mode = "PAPER" if is_paper else "REAL"
    if new_mode != current_mode:
        st.query_params["mode"] = new_mode
        st.rerun()

if current_mode == "PAPER":
    st.markdown(f"<div style='background:#1e293b; padding:10px; border-radius:8px; color:#4ade80; font-weight:bold; text-align:center;'>💵 Balance: ${float(user['paper_balance']):,.2f}</div>", unsafe_allow_html=True)

# DETAIL VIEW
if "ticker" in st.query_params:
    ticker = st.query_params["ticker"]
    stock = get_single_stock(ticker)
    
    if st.button("← Back", key="back_btn"):
        del st.query_params["ticker"]; st.rerun()
        
    if stock:
        # 1. Fetch News (RSS Direct + YF Fallback)
        news_items = get_news_data(ticker)
        headlines_txt = "\n".join([f"- {n['title']}" for n in news_items]) if news_items else ""
        
        # 2. Get AI Analysis (or Technical Fallback)
        ai_summary, ai_score, ai_source = get_ai_analysis(ticker, headlines_txt, stock)
        
        s, l, c, _, r = calculate_risk(stock, ai_score)
        p = float(stock['current_price']); ch = float(stock['day_change']); cc = "#4ade80" if ch>=0 else "#ef4444"
        
        st.markdown(f"<h1 style='margin:0; font-size: 2.5rem;'>{ticker}</h1>", unsafe_allow_html=True)
        st.markdown(f"<h2 style='margin:0; color:{cc}; font-size: 1.5rem;'>${p:,.2f} <span style='font-size:1rem; opacity:0.8;'>({ch:.2f}%) Today</span></h2>", unsafe_allow_html=True)
        
        if current_mode == "PAPER":
            st.markdown("---")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Buy 10", use_container_width=True):
                    ok, msg = execute_paper_trade(username, ticker, "BUY", 10, p)
                    if ok: st.success("Bought 10!"); st.rerun()
                    else: st.error(msg)
            with c2:
                if st.button("Sell 10", use_container_width=True):
                    ok, msg = execute_paper_trade(username, ticker, "SELL", 10, p)
                    if ok: st.success("Sold 10!"); st.rerun()
                    else: st.error(msg)
            st.markdown("---")

        st.markdown(create_gauge_html(s, l, c, "big"), unsafe_allow_html=True)
        st.markdown(f"<div class='card' style='margin-top:15px; padding: 25px;'><div style='color:#94a3b8; font-size:0.8rem; font-weight:bold; letter-spacing:1px; margin-bottom:15px;'>RISK FACTORS</div>", unsafe_allow_html=True)
        def get_pill(val, type="risk"):
            if type=="vol": return "pill-high" if val > 3 else "pill-low", "HIGH" if val > 3 else "LOW"
            if type=="debt": return "pill-high" if val > 150 else "pill-low", "HIGH" if val > 150 else "LOW"
            if type=="rsi": return "pill-med" if val > 70 or val < 30 else "pill-low", "EXTREME" if val > 70 or val < 30 else "NORMAL"
            return "pill-low", "LOW"
        v_cls, v_txt = get_pill(float(stock['volatility']), "vol")
        st.markdown(f"<div class='risk-row'><div class='risk-label'>Volatility</div><div class='risk-pill {v_cls}'>{v_txt}</div></div>", unsafe_allow_html=True)
        d_cls, d_txt = get_pill(float(stock['debt_ratio']), "debt")
        st.markdown(f"<div class='risk-row'><div class='risk-label'>Debt / Equity</div><div class='risk-pill {d_cls}'>{d_txt}</div></div>", unsafe_allow_html=True)
        r_cls, r_txt = get_pill(float(stock['rsi']), "rsi")
        st.markdown(f"<div class='risk-row' style='border:none;'><div class='risk-label'>RSI Momentum</div><div class='risk-pill {r_cls}'>{r_txt}</div></div></div>", unsafe_allow_html=True)
        
        title_txt = "AI MARKET INSIGHT" if ai_source == "AI" else "TECHNICAL INSIGHT"
        if ai_summary:
            ai_html = f"<div class='card' style='margin-top:15px; border:1px solid #4ade80;'><div style='color:#4ade80; font-size:0.8rem; font-weight:bold; letter-spacing:1px; margin-bottom:5px;'>{title_txt} (Score: {ai_score})</div><div style='font-size:0.9rem; color:white; line-height:1.4;'>{ai_summary}</div></div>"
            st.markdown(ai_html, unsafe_allow_html=True)

        if news_items:
            st.markdown(f"<div class='card' style='margin-top:15px;'><div style='color:#94a3b8; font-size:0.8rem; font-weight:bold; letter-spacing:1px; margin-bottom:15px;'>RECENT NEWS</div>", unsafe_allow_html=True)
            for item in news_items:
                title = item.get('title') or item.get('headline', 'No Title')
                pub = item.get('publisher', 'Unknown')
                link = item.get('link', '#')
                time_str = item.get('time', 'Recently')
                st.markdown(f"<a href='{link}' target='_blank' style='text-decoration:none;'><div style='font-size:0.95rem; font-weight:bold; color:#e0e6ed; margin-bottom:5px;'>{title}</div><div style='font-size:0.75rem; color:#64748b; margin-bottom:15px;'>{time_str} • {pub}</div></a><div style='border-bottom:1px solid #2d3748; margin-bottom:15px;'></div>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)
        
        st.write("")
        if st.button(f"🔔 Set Alert for {ticker}", key="alert_action_btn"):
            st.query_params["tab"] = "alerts"; del st.query_params["ticker"]; st.rerun()
    else: st.error("Data missing. Refresh portfolio.")
    render_navbar(token, current_mode)
    st.stop()

# TABS
tab = st.query_params.get("tab", "home")

if tab == "home":
    st.markdown("### Portfolio Overview")
    portfolio = get_portfolio_details(user['username'], current_mode)
    
    if not portfolio:
        st.info(f"Your {current_mode} portfolio is empty.")
    else:
        tickers = [r['ticker'] for r in portfolio]
        if st.button("🔄 Refresh Data", key="ref_home"):
            with st.spinner("Scanning market & portfolio..."): update_stock_data(tickers, user['username'])
        
        data_map = get_cached_data_map(tickers)
        valid_rows = [data_map[t] for t in tickers if t in data_map]
        
        if valid_rows:
            avg = sum([calculate_risk(x)[0] for x in valid_rows])/len(valid_rows)
            riskiest = max(valid_rows, key=lambda x: calculate_risk(x)[0])
            volatile = max(valid_rows, key=lambda x: abs(float(x['day_change'])))
            earnings_stock = min([r for r in valid_rows if r['days_to_earnings'] > 0], key=lambda x: x['days_to_earnings'], default=None)
            earnings_text = f"{earnings_stock['ticker']} ({earnings_stock['days_to_earnings']}d)" if earnings_stock else "None Soon"
            
            st.markdown(create_gauge_html(int(avg), "MEDIUM" if avg<65 else "HIGH", "#fbbf24" if avg<65 else "#ef4444", "big"), unsafe_allow_html=True)
            st.markdown(f"""<div style="display:flex; justify-content:space-between; background:#151922; padding:15px; border-radius:0 0 16px 16px; margin-top:-14px; margin-bottom:20px; border:1px solid #2d3748; border-top:none;"><div style="text-align:center; width:33%; border-right:1px solid #2d3748;"><div style="color:#94a3b8; font-size:0.6rem; text-transform:uppercase;">Highest Risk</div><div style="color:white; font-weight:bold; font-size:1rem;">{riskiest['ticker']}</div></div><div style="text-align:center; width:33%; border-right:1px solid #2d3748;"><div style="color:#94a3b8; font-size:0.6rem; text-transform:uppercase;">Most Volatile</div><div style="color:white; font-weight:bold; font-size:1rem;">{volatile['ticker']}</div></div><div style="text-align:center; width:33%;"><div style="color:#94a3b8; font-size:0.6rem; text-transform:uppercase;">Next Earnings</div><div style="color:white; font-weight:bold; font-size:1rem;">{earnings_text}</div></div></div>""", unsafe_allow_html=True)
            render_horizontal_grid(data_map, token)
            
    st.markdown("### Watchlist Candidates")
    candidates = get_watchlist_candidates()
    render_compact_watchlist(candidates, token)

elif tab == "portfolio":
    st.markdown(f"### My Stocks ({current_mode})")
    
    # 1. Total Metrics Header
    total_pl, day_pl = get_portfolio_summary(user['username'], current_mode)
    c_pl = "#4ade80" if total_pl >= 0 else "#ef4444"
    c_day = "#4ade80" if day_pl >= 0 else "#ef4444"
    
    st.markdown(f"""
        <div style="display:flex; gap:10px; margin-bottom:20px;">
            <div class="metric-box" style="flex:1;">
                <div class="metric-label">Total P/L</div>
                <div class="metric-value" style="color:{c_pl}">${total_pl:,.2f}</div>
            </div>
            <div class="metric-box" style="flex:1;">
                <div class="metric-label">Today's P/L</div>
                <div class="metric-value" style="color:{c_day}">${day_pl:,.2f}</div>
            </div>
        </div>
    """, unsafe_allow_html=True)

    if current_mode == "REAL":
        with st.expander("Manage Holdings", expanded=False):
            t1, t2, t3 = st.tabs(["Add Stock", "Edit Position", "Remove Stock"])
            with t1:
                with st.form("add_stock"):
                    c1, c2, c3 = st.columns([2, 1, 1])
                    new_t = c1.text_input("Ticker", placeholder="e.g. AAPL")
                    shares = c2.number_input("Shares", min_value=0.0, step=1.0)
                    price = c3.number_input("Avg Price", min_value=0.0, step=0.01)
                    if st.form_submit_button("Add to Portfolio"):
                        if new_t: add_ticker_to_db(user['username'], new_t.upper(), shares, price, 'REAL'); st.rerun()
            with t2:
                port_rows = get_portfolio_details(user['username'], 'REAL')
                if port_rows:
                    with st.form("edit_pos"):
                        edit_t = st.selectbox("Select Stock", [r['ticker'] for r in port_rows])
                        c1, c2 = st.columns(2)
                        new_s = c1.number_input("New Shares", min_value=0.0, step=1.0)
                        new_p = c2.number_input("New Avg Price", min_value=0.0, step=0.01)
                        if st.form_submit_button("Update Position"):
                            update_ticker_in_db(user['username'], edit_t, new_s, new_p, 'REAL'); st.rerun()
                else: st.info("Empty Portfolio")
            with t3:
                port_rows = get_portfolio_details(user['username'], 'REAL')
                if port_rows:
                    to_remove = st.selectbox("Select Stock to Remove", [r['ticker'] for r in port_rows])
                    if st.button("Remove Selected", type="primary"):
                        deactivate_stock(user['username'], to_remove, 'REAL'); st.rerun()
                else: st.info("Portfolio is empty.")
    else:
        st.info("To add stocks in Paper Trading, search or select a stock from the Home or Scanner tabs and use the Buy/Sell buttons on the detail page.")
        
    st.divider()
    port_rows = get_portfolio_details(user['username'], current_mode)
    if port_rows:
        tickers = [r['ticker'] for r in port_rows]
        market_data = get_cached_data_map(tickers)
        for row in port_rows:
            t = row['ticker']
            if t in market_data: render_portfolio_row(row, market_data[t], token)
            else: st.warning(f"Loading data for {t}...")

elif tab == "alerts":
    st.markdown("### Volatility Alerts")
    with st.expander("New Alert", expanded=True):
        port_rows = get_portfolio_details(user['username'], current_mode)
        options = ["ALL STOCKS"] + [r['ticker'] for r in port_rows]
        if port_rows:
            t = st.selectbox("Ticker", options)
            c = st.selectbox("Trigger", ["DOWN", "UP"])
            v = st.number_input("Target Price (or % if ALL)", 0.0)
            if st.button("Set Alert"): add_alert(user['username'], t, c, v); st.rerun()
        else: st.info("Add stocks first.")
    st.divider()
    alerts = get_user_alerts(user['username'])
    for a in alerts:
        bg = "#3d1111" if a['is_triggered'] else "#1a1f2b"; border = "#ef4444" if a['is_triggered'] else "#2d3748"
        st.markdown(f"""<div style="background:{bg}; border:1px solid {border}; border-radius:12px; padding:15px; margin-bottom:10px; display:flex; justify-content:space-between;"><div><div style="font-weight:bold; color:white;">{a['ticker']}</div><div style="font-size:0.85rem; color:#94a3b8;">{a['condition_type']} {a['target_price']}</div></div></div>""", unsafe_allow_html=True)
        if st.button("Clear", key=f"del_al_{a['id']}"): delete_alert(a['id']); st.rerun()

elif tab == "scanner":
    st.markdown("### Market Scanner")
    port_rows = get_portfolio_details(user['username'], current_mode)
    tickers = [r['ticker'] for r in port_rows]
    market_data = get_cached_data_map(tickers)
    if market_data:
        st.markdown("**📉 Oversold (RSI < 40)**")
        for t, data in market_data.items(): 
            if data['rsi'] is not None and float(data['rsi']) < 40: render_simple_card(data, token)
        st.markdown("**📅 Earnings Soon**")
        for t, data in market_data.items():
            if int(data.get('days_to_earnings', 999)) < 14: render_simple_card(data, token)

elif tab == "settings":
    st.markdown("### Settings")
    with st.form("settings_form"):
        new_name = st.text_input("Display Name", value=display_name)
        new_email = st.text_input("Recovery Email", value=user.get('email', ''))
        new_pin = st.text_input("New PIN", type="password")
        if st.form_submit_button("Save Changes"):
            if update_user_settings(user['username'], new_name, new_email, new_pin if new_pin else None): st.success("Saved!"); st.rerun()
    if st.button("Log Out"): st.query_params.clear(); st.rerun()

render_navbar(token, current_mode)
