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
import streamlit.components.v1 as components
from datetime import datetime, timedelta

# =========================================================
# 1. CONFIGURATION & CSS
# =========================================================
st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="centered", initial_sidebar_state="collapsed")

st.markdown("""
    <style>
        .block-container { padding-top: 0rem !important; padding-bottom: 5rem !important; }
        .stApp { background-color: #0f1219 !important; color: #e0e6ed !important; }
        
        input[type="text"], input[type="password"], input[type="number"] { 
            background-color: #1e293b !important; 
            color: white !important; 
            border: 1px solid #4ade80 !important; 
            border-radius: 8px; 
            padding: 10px;
        }
        div[data-baseweb="input"] { background-color: transparent !important; border: none; }
        
        div[data-baseweb="select"] > div { 
            background-color: #1e293b !important; 
            color: white !important; 
            border: 1px solid #4ade80 !important; 
        }
        div[role="listbox"] ul { background-color: #1e293b !important; }
        li[role="option"] { color: white !important; background-color: #1e293b !important; }
        li[role="option"]:hover { background-color: #4ade80 !important; color: black !important; }
        
        .card { 
            background-color: #1a1f2b; 
            border-radius: 16px; 
            padding: 20px; 
            margin-bottom: 10px; 
            border: 1px solid #2d3748; 
            box-shadow: 0 4px 6px rgba(0,0,0,0.3); 
        }
        
        .metric-box {
            background-color: #1e293b;
            border: 1px solid #2d3748;
            border-radius: 12px;
            padding: 15px;
            text-align: center;
            margin-bottom: 10px;
        }
        
        div.stButton > button {
            background: linear-gradient(135deg, #4ade80, #16a34a) !important; 
            color: white !important; 
            border: none; 
            border-radius: 8px; 
            font-weight: bold;
            width: 100%;
            padding: 12px 20px;
        }

        h1, h2, h3, p, label, span, div { color: #e0e6ed; }
        a { color: #ffffff !important; text-decoration: none !important; }
        
        .nav-container { 
            position: fixed; bottom: 0; left: 0; width: 100%; height: 65px; 
            background-color: #0f1219; border-top: 1px solid #2d3748; 
            display: flex; justify-content: space-around; align-items: center; z-index: 99999; 
        }
        
        .scrolling-wrapper { 
            display: flex; 
            flex-wrap: nowrap; 
            overflow-x: auto; 
            gap: 12px; 
            padding-bottom: 20px; 
            margin-top: 10px;
            -ms-overflow-style: none; 
            scrollbar-width: none; 
        }
        .scrolling-wrapper::-webkit-scrollbar { display: none; }
        .scrolling-card { 
            flex: 0 0 auto; 
            width: 130px; 
            background-color: #1a1f2b; 
            border: 1px solid #2d3748; 
            border-radius: 12px; 
            padding: 15px; 
        }
        
        .risk-pill { padding: 4px 10px; border-radius: 20px; font-size: 0.75rem; font-weight: bold; text-transform: uppercase; }
        .pill-low { background: rgba(74, 222, 128, 0.2); color: #4ade80; }
        .pill-med { background: rgba(251, 191, 36, 0.2); color: #fbbf24; }
        .pill-high { background: rgba(239, 68, 68, 0.2); color: #ef4444; }
        .risk-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; border-bottom: 1px solid #2d3748; padding-bottom: 5px; }
        
        header {visibility: hidden;} footer {visibility: hidden;} 
    </style>
""", unsafe_allow_html=True)

# Global Constants
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
# 2. FUNCTIONS
# =========================================================

def get_connection():
    return mysql.connector.connect(**DB_CONFIG)

def init_db():
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS user_profiles (username VARCHAR(255) PRIMARY KEY, pin VARCHAR(50), display_name VARCHAR(100), email VARCHAR(255), paper_balance DECIMAL(20,2) DEFAULT 10000.00)")
        cursor.execute("CREATE TABLE IF NOT EXISTS user_sessions (token VARCHAR(255) PRIMARY KEY, username VARCHAR(255))")
        cursor.execute("CREATE TABLE IF NOT EXISTS user_portfolio (id INT NOT NULL AUTO_INCREMENT, username VARCHAR(255), ticker VARCHAR(20), shares DECIMAL(10,4) DEFAULT 0, entry_price DECIMAL(20,4) DEFAULT 0, portfolio_type VARCHAR(20) DEFAULT 'REAL', is_active BOOLEAN DEFAULT TRUE, realized_pl DECIMAL(20,2) DEFAULT 0.00, PRIMARY KEY (id))")
        cursor.execute("CREATE TABLE IF NOT EXISTS user_alerts (id INT NOT NULL AUTO_INCREMENT PRIMARY KEY, username VARCHAR(255), ticker VARCHAR(20), condition_type VARCHAR(10), target_price DECIMAL(20,4), is_triggered BOOLEAN DEFAULT FALSE)")
        cursor.execute("CREATE TABLE IF NOT EXISTS stock_cache (ticker VARCHAR(20) PRIMARY KEY, company_name VARCHAR(255), current_price DECIMAL(20,4), day_change DECIMAL(10,2), rsi DECIMAL(10,2), trend_status VARCHAR(20), volume_status VARCHAR(20), range_loc DECIMAL(10,2), volatility DECIMAL(10,2), debt_ratio DECIMAL(10,2), days_to_earnings INT, market_cap BIGINT, eps DECIMAL(10,2), signal_tag VARCHAR(50), next_earnings VARCHAR(50), last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)")
        cursor.execute("CREATE TABLE IF NOT EXISTS daily_briefing (id INT PRIMARY KEY, content TEXT, last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)")
        conn.close()
    except Exception as e:
        print(f"Database Error: {e}")

def parse_smart_date(date_str):
    if not date_str or str(date_str).lower() in ['n/a', 'none', '', '999']: return 999
    try:
        now = datetime.now()
        try:
            target = datetime.strptime(f"{date_str} {now.year}", "%b %d %Y")
            if target < now: target = datetime.strptime(f"{date_str} {now.year + 1}", "%b %d %Y")
        except ValueError:
            target = datetime.strptime(str(date_str), "%Y-%m-%d")
        return (target - now).days
    except: return 999

def login_user(u, p):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM user_profiles WHERE username=%s", (u,))
    row = cursor.fetchone()
    conn.close()
    if row and str(row['pin']) == str(p): return row
    return None

def create_session(u):
    t = str(uuid.uuid4())
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO user_sessions (token, username) VALUES (%s,%s)", (t, u))
    conn.commit(); conn.close()
    return t

def get_user_from_token(t):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT s.username, p.display_name, p.paper_balance, p.email FROM user_sessions s JOIN user_profiles p ON s.username=p.username WHERE s.token=%s", (t,))
    row = cursor.fetchone()
    conn.close()
    return row

def update_user_settings(username, display_name, email, new_pin=None):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        if new_pin: cursor.execute("UPDATE user_profiles SET display_name=%s, email=%s, pin=%s WHERE username=%s", (display_name, email, new_pin, username))
        else: cursor.execute("UPDATE user_profiles SET display_name=%s, email=%s WHERE username=%s", (display_name, email, username))
        conn.commit(); conn.close()
        return True
    except: return False

def get_news_data(ticker):
    news_results = []
    try:
        url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            root = ET.fromstring(resp.content)
            for item in root.findall('.//item')[:2]:
                news_results.append({'title': item.find('title').text, 'link': item.find('link').text, 'pub': "Yahoo", 'time': "Recent"})
    except: pass
    return news_results

def get_ai_analysis(ticker, headlines, current_data=None):
    if current_data:
        rsi = float(current_data.get('rsi') or 50)
        if rsi > 70: return "Technical: Overbought. Risk of pullback.", 30, "TECH"
        elif rsi < 30: return "Technical: Oversold. Potential bounce.", 80, "TECH"
        return "Market sentiment is neutral.", 50, "TECH"
    return "No Data Available", 50, "NONE"

def calculate_risk(row, ai_score=None):
    s = 50
    rsi = float(row.get('rsi') or 50)
    if rsi > 70: s += 10
    elif rsi < 30: s -= 10
    vol = float(row.get('volatility') or 0)
    if vol > 3.0: s += 15
    final = max(0, min(100, int(s)))
    color = "#4ade80" 
    label = "LOW"
    if final > 65: color = "#ef4444"; label="HIGH"
    elif final > 35: color = "#fbbf24"; label="MEDIUM"
    return final, label, color, "badge-mix", []

def get_watchlist_candidates():
    conn = get_connection(); cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM stock_cache ORDER BY ABS(day_change) DESC LIMIT 10")
    rows = cursor.fetchall(); conn.close()
    return rows[:3]

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
    conn = get_connection(); cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM user_portfolio WHERE username=%s AND portfolio_type=%s AND is_active=TRUE", (username, ptype))
    rows = cursor.fetchall(); conn.close()
    return rows

def get_portfolio_summary(username, ptype):
    conn = get_connection(); cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT SUM(realized_pl) as realized FROM user_portfolio WHERE username=%s AND portfolio_type=%s AND is_active=FALSE", (username, ptype))
    realized = float(cursor.fetchone()['realized'] or 0)
    cursor.execute("SELECT p.shares, p.entry_price, s.current_price, s.day_change FROM user_portfolio p LEFT JOIN stock_cache s ON p.ticker = s.ticker WHERE p.username=%s AND p.portfolio_type=%s AND p.is_active=TRUE", (username, ptype))
    active_rows = cursor.fetchall(); conn.close()
    unrealized = 0.0; day_pl = 0.0; active_cost = 0.0; curr_val = 0.0
    for r in active_rows:
        if r['current_price']:
            c = float(r['current_price']); e = float(r['entry_price']); s = float(r['shares'])
            unrealized += (c - e) * s; active_cost += (e * s); curr_val += (c * s)
            pct = float(r['day_change'] or 0); prev = c / (1 + (pct/100))
            day_pl += (c - prev) * s
    total_pl = realized + unrealized
    total_pct = (total_pl / active_cost) * 100 if active_cost > 0 else 0
    day_pct = (day_pl / (curr_val - day_pl)) * 100 if (curr_val - day_pl) > 0 else 0
    return total_pl, total_pct, day_pl, day_pct

def execute_paper_trade(username, ticker, action, qty, price):
    conn = get_connection(); cursor = conn.cursor()
    cursor.execute("SELECT paper_balance FROM user_profiles WHERE username=%s", (username,))
    balance = float(cursor.fetchone()[0])
    cost = float(qty) * float(price)
    if action == "BUY" and balance >= cost:
        cursor.execute("UPDATE user_profiles SET paper_balance = paper_balance - %s WHERE username=%s", (cost, username))
        cursor.execute("INSERT INTO user_portfolio (username, ticker, shares, entry_price, portfolio_type, is_active) VALUES (%s, %s, %s, %s, 'PAPER', 1)", (username, ticker, qty, price))
        conn.commit(); conn.close(); return True, "Success"
    conn.close(); return False, "Failed"

def add_ticker_to_db(username, ticker, shares, price, ptype):
    conn = get_connection(); cursor = conn.cursor()
    cursor.execute("INSERT INTO user_portfolio (username, ticker, shares, entry_price, portfolio_type, is_active) VALUES (%s,%s,%s,%s,%s, TRUE)", (username, ticker, shares, price, ptype))
    conn.commit(); conn.close()

def add_alert(username, ticker, condition, price):
    conn = get_connection(); cursor = conn.cursor()
    cursor.execute("INSERT INTO user_alerts (username, ticker, condition_type, target_price) VALUES (%s, %s, %s, %s)", (username, ticker, condition, price))
    conn.commit(); conn.close()

def get_user_alerts(username):
    conn = get_connection(); cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM user_alerts WHERE username = %s ORDER BY created_at DESC", (username,))
    rows = cursor.fetchall(); conn.close(); return rows

# --- UI Functions ---
def render_navbar(token, mode):
    m_arg = "&mode=PAPER" if mode == "PAPER" else ""
    st.markdown(f'<div class="nav-container"><a href="?token={token}&tab=home{m_arg}" class="nav-link">🏠</a><a href="?token={token}&tab=portfolio{m_arg}" class="nav-link">📂</a><a href="?token={token}&tab=alerts{m_arg}" class="nav-link">🔔</a><a href="?token={token}&tab=scanner{m_arg}" class="nav-link">📡</a><a href="?token={token}&tab=settings{m_arg}" class="nav-link">⚙️</a></div>', unsafe_allow_html=True)

# FIXED GAUGE HTML WITH COLORS
def create_gauge_html(score, label, color, size="big"):
    rad = 80 if size == "big" else 60
    vb = "0 0 200 120" if size == "big" else "0 0 160 100"
    fill = (score / 100) * (3.14159 * rad)
    header = f'<div style="text-align:center; color:#94a3b8; font-size:0.8rem; font-weight:bold; letter-spacing:1px; margin-bottom:5px;">PORTFOLIO RISK</div>' if size == "big" else ""
    svg = f"""
    <svg viewBox="{vb}" style="width:100%; height:auto;">
        <defs>
            <linearGradient id="gaugeGradient" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" style="stop-color:#4ade80;stop-opacity:1" />
                <stop offset="50%" style="stop-color:#fbbf24;stop-opacity:1" />
                <stop offset="100%" style="stop-color:#ef4444;stop-opacity:1" />
            </linearGradient>
        </defs>
        <path d="M 20 100 A {rad} {rad} 0 0 1 {20+rad*2} 100" fill="none" stroke="#334155" stroke-width="15" stroke-linecap="round"/>
        <path d="M 20 100 A {rad} {rad} 0 0 1 {20+rad*2} 100" fill="none" stroke="url(#gaugeGradient)" stroke-width="15" stroke-linecap="round" stroke-dasharray="{fill}, 1000"/>
        <text x="{20+rad}" y="80" font-family="sans-serif" font-size="38" font-weight="bold" fill="white" text-anchor="middle">{score}</text>
        <text x="{20+rad}" y="100" font-family="sans-serif" font-size="12" font-weight="bold" fill="{color}" text-anchor="middle" letter-spacing="2">{label}</text>
    </svg>
    """
    return f'<div class="card" style="padding-bottom:0; margin-bottom:0;">{header}{svg}</div>'

def render_horizontal_grid(rows_dict, current_token):
    h = '<div class="scrolling-wrapper">'
    for ticker, row in rows_dict.items():
        ch = float(row['day_change']); cc = "#4ade80" if ch>=0 else "#ef4444"; arr = "▲" if ch>=0 else "▼"
        link = f"?token={current_token}&ticker={ticker}"
        h += f'<a href="{link}" target="_self" style="text-decoration:none;"><div class="scrolling-card"><div style="font-weight:bold; font-size:1.1rem; color:white;">{ticker}</div><div style="font-size:0.85rem; color:{cc}; font-weight:bold;">{arr} {ch:.2f}%</div></div></a>'
    h += '</div>'; st.markdown(h, unsafe_allow_html=True)

# =========================================================
# 3. MAIN EXECUTION
# =========================================================
init_db()

if "token" not in st.query_params:
    st.markdown("<h1 style='text-align:center; color:#4ade80;'>⚡ Penny Pulse</h1>", unsafe_allow_html=True)
    with st.form("login"):
        u = st.text_input("Username"); p = st.text_input("PIN", type="password")
        if st.form_submit_button("Login"):
            user = login_user(u, p)
            if user: st.query_params["token"] = create_session(u); st.rerun()
    st.stop()

user = get_user_from_token(token)
current_mode = st.query_params.get("mode", "REAL")

# TABS
tab = st.query_params.get("tab", "home")

if tab == "home":
    # Morning Briefing
    try:
        conn = get_connection(); cursor = conn.cursor()
        cursor.execute("SELECT content FROM daily_briefing WHERE id=1")
        row = cursor.fetchone(); conn.close()
        if row: st.markdown(f'<div class="card" style="border-left: 4px solid #facc15;"><div style="color:#facc15; font-size:0.8rem; font-weight:bold;">AI MORNING BRIEFING</div><div style="font-size:0.95rem; color:#e0e6ed;">{row[0]}</div></div>', unsafe_allow_html=True)
    except: pass
    
    st.markdown("### Portfolio Overview")
    portfolio = get_portfolio_details(user['username'], current_mode)
    if not portfolio: st.info("Empty Portfolio")
    else:
        tickers = [r['ticker'] for r in portfolio]
        data_map = get_cached_data_map(tickers)
        valid_rows = [data_map[t] for t in tickers if t in data_map]
        if valid_rows:
            # 1. Gauge
            avg = sum([calculate_risk(x)[0] for x in valid_rows])/len(valid_rows)
            risk_val, risk_lbl, risk_col, _, _ = calculate_risk({'rsi': 50, 'volatility': 1.0, 'trend_status': 'NEUTRAL'}) # Placeholders
            st.markdown(create_gauge_html(int(avg), "MEDIUM" if avg<65 else "HIGH", "#fbbf24" if avg<65 else "#ef4444"), unsafe_allow_html=True)
            
            # 2. RESTORED BIG 3 BOXES
            riskiest = max(valid_rows, key=lambda x: calculate_risk(x)[0])
            volatile = max(valid_rows, key=lambda x: abs(float(x['day_change'])))
            
            # Find Next Earnings
            earnings_list = []
            for r in valid_rows:
                d = parse_smart_date(r.get('next_earnings'))
                if d < 365: earnings_list.append((r['ticker'], d))
            
            e_text = min(earnings_list, key=lambda x: x[1])[0] if earnings_list else "N/A"

            st.markdown(f"""
                <div style="display:flex; justify-content:space-between; background:#151922; padding:15px; border-radius:0 0 16px 16px; margin-top:-14px; margin-bottom:20px; border:1px solid #2d3748; border-top:none;">
                    <div style="text-align:center; width:33%; border-right:1px solid #2d3748;">
                        <div style="color:#94a3b8; font-size:0.6rem; text-transform:uppercase;">Highest Risk</div>
                        <div style="color:white; font-weight:bold; font-size:1rem;">{riskiest['ticker']}</div>
                    </div>
                    <div style="text-align:center; width:33%; border-right:1px solid #2d3748;">
                        <div style="color:#94a3b8; font-size:0.6rem; text-transform:uppercase;">Most Volatile</div>
                        <div style="color:white; font-weight:bold; font-size:1rem;">{volatile['ticker']}</div>
                    </div>
                    <div style="text-align:center; width:33%;">
                        <div style="color:#94a3b8; font-size:0.6rem; text-transform:uppercase;">Next Earnings</div>
                        <div style="color:white; font-weight:bold; font-size:1rem;">{e_text}</div>
                    </div>
                </div>
            """, unsafe_allow_html=True)
            
            # 3. Horizontal Grid
            render_horizontal_grid(data_map, token)
            
    st.markdown(f"### {datetime.now().strftime('%b %d')} Watchlist")
    candidates = get_watchlist_candidates()
    # Watchlist Rendering...

elif tab == "portfolio":
    st.markdown(f"### My Stocks ({current_mode})")
    # Portfolio Tab logic...

render_navbar(token, current_mode)
