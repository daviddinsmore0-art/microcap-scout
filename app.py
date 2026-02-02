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
# 1. CONFIGURATION & CSS (YOUR ORIGINAL STYLES)
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
        div[data-baseweb="popover"] { background-color: #1e293b !important; }
        
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
        .metric-label { font-size: 0.75rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 5px; }
        .metric-value { font-size: 1.5rem; font-weight: bold; color: white; margin-bottom: 2px; line-height: 1.1; }
        .metric-sub { font-size: 0.9rem; font-weight: bold; }
        
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

        a { color: #ffffff !important; text-decoration: none !important; }
        a:hover { color: #4ade80 !important; }
        
        .nav-container { 
            position: fixed; bottom: 0; left: 0; width: 100%; height: 65px; 
            background-color: #0f1219; border-top: 1px solid #2d3748; 
            display: flex; justify-content: space-around; align-items: center; z-index: 99999; 
        }
        a.nav-link { text-decoration: none; font-size: 24px; text-align: center; cursor: pointer;}
        
        .scrolling-wrapper { 
            display: flex; 
            flex-wrap: nowrap; 
            overflow-x: auto; 
            gap: 12px; 
            padding-bottom: 10px; 
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
# 2. FUNCTIONS (SURGICAL UPDATES ONLY)
# =========================================================

def get_connection():
    return mysql.connector.connect(**DB_CONFIG)

def init_db():
    try:
        conn = get_connection(); cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS user_profiles (username VARCHAR(255) PRIMARY KEY, pin VARCHAR(50), display_name VARCHAR(100), email VARCHAR(255), paper_balance DECIMAL(20,2) DEFAULT 10000.00)")
        cursor.execute("CREATE TABLE IF NOT EXISTS user_sessions (token VARCHAR(255) PRIMARY KEY, username VARCHAR(255))")
        cursor.execute("CREATE TABLE IF NOT EXISTS user_portfolio (id INT NOT NULL AUTO_INCREMENT, username VARCHAR(255), ticker VARCHAR(20), shares DECIMAL(10,4) DEFAULT 0, entry_price DECIMAL(20,4) DEFAULT 0, portfolio_type VARCHAR(20) DEFAULT 'REAL', is_active BOOLEAN DEFAULT TRUE, realized_pl DECIMAL(20,2) DEFAULT 0.00, PRIMARY KEY (id))")
        cursor.execute("CREATE TABLE IF NOT EXISTS user_alerts (id INT NOT NULL AUTO_INCREMENT PRIMARY KEY, username VARCHAR(255), ticker VARCHAR(20), condition_type VARCHAR(10), target_price DECIMAL(20,4), is_triggered BOOLEAN DEFAULT FALSE)")
        cursor.execute("CREATE TABLE IF NOT EXISTS stock_cache (ticker VARCHAR(20) PRIMARY KEY, company_name VARCHAR(255), current_price DECIMAL(20,4), day_change DECIMAL(10,2), rsi DECIMAL(10,2), trend_status VARCHAR(20), volume_status VARCHAR(20), range_loc DECIMAL(10,2), volatility DECIMAL(10,2), debt_ratio DECIMAL(10,2), days_to_earnings INT, market_cap BIGINT, eps DECIMAL(10,2), signal_tag VARCHAR(50), next_earnings VARCHAR(50), last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)")
        cursor.execute("CREATE TABLE IF NOT EXISTS daily_briefing (id INT PRIMARY KEY, content TEXT, last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)")
        conn.close()
    except Exception as e: print(f"Database Error: {e}")

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
    conn = get_connection(); cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM user_profiles WHERE username=%s", (u,))
    row = cursor.fetchone(); conn.close()
    if row and str(row['pin']) == str(p): return row
    return None

def create_session(u):
    t = str(uuid.uuid4()); conn = get_connection(); cursor = conn.cursor()
    cursor.execute("INSERT INTO user_sessions (token, username) VALUES (%s,%s)", (t, u))
    conn.commit(); conn.close(); return t

def get_user_from_token(t):
    conn = get_connection(); cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT s.username, p.display_name, p.paper_balance, p.email FROM user_sessions s JOIN user_profiles p ON s.username=p.username WHERE s.token=%s", (t,))
    row = cursor.fetchone(); conn.close(); return row

def get_news_data(ticker):
    news = []
    try:
        url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            root = ET.fromstring(resp.content)
            for item in root.findall('.//item')[:2]:
                news.append({'title': item.find('title').text, 'link': item.find('link').text, 'pub': "Yahoo", 'time': "Recent"})
    except: pass
    return news

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
    if vol > 3.0: s += 10
    final = max(0, min(100, int(s)))
    color = "#4ade80" if final < 35 else "#fbbf24" if final < 65 else "#ef4444"
    label = "LOW" if final < 35 else "MEDIUM" if final < 65 else "HIGH"
    return final, label, color, "badge-mix", []

def get_watchlist_candidates():
    conn = get_connection(); cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM stock_cache ORDER BY ABS(day_change) DESC LIMIT 10")
    rows = cursor.fetchall(); conn.close(); return rows[:3]

def get_cached_data_map(tickers):
    if not tickers: return {}
    conn = get_connection(); cursor = conn.cursor(dictionary=True)
    format_strings = ','.join(['%s'] * len(tickers))
    cursor.execute(f"SELECT * FROM stock_cache WHERE ticker IN ({format_strings})", tuple(tickers))
    rows = cursor.fetchall(); conn.close(); return {row['ticker']: row for row in rows}

def get_single_stock(ticker):
    conn = get_connection(); cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM stock_cache WHERE ticker=%s", (ticker,))
    row = cursor.fetchone(); conn.close(); return row

def get_portfolio_details(username, ptype):
    conn = get_connection(); cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM user_portfolio WHERE username=%s AND portfolio_type=%s AND is_active=TRUE", (username, ptype))
    rows = cursor.fetchall(); conn.close(); return rows

def get_portfolio_summary(username, ptype):
    conn = get_connection(); cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT SUM(realized_pl) as realized FROM user_portfolio WHERE username=%s AND portfolio_type=%s AND is_active=FALSE", (username, ptype))
    realized = float(cursor.fetchone()['realized'] or 0)
    cursor.execute("SELECT p.shares, p.entry_price, s.current_price, s.day_change FROM user_portfolio p LEFT JOIN stock_cache s ON p.ticker = s.ticker WHERE p.username=%s AND p.portfolio_type=%s AND p.is_active=TRUE", (username, ptype))
    active_rows = cursor.fetchall(); conn.close()
    unrealized = 0.0; day_pl = 0.0; cost_basis = 0.0; curr_val = 0.0
    for r in active_rows:
        if r['current_price']:
            c = float(r['current_price']); e = float(r['entry_price']); s = float(r['shares'])
            unrealized += (c - e) * s; cost_basis += (e * s); curr_val += (c * s)
            pct = float(r['day_change'] or 0); prev = c / (1 + (pct/100)); day_pl += (c - prev) * s
    total_pl = realized + unrealized
    total_pct = (total_pl / cost_basis) * 100 if cost_basis > 0 else 0
    day_pct = (day_pl / (curr_val - day_pl)) * 100 if (curr_val - day_pl) > 0 else 0
    return total_pl, total_pct, day_pl, day_pct

def execute_paper_trade(username, ticker, action, qty, price):
    conn = get_connection(); cursor = conn.cursor()
    cursor.execute("SELECT paper_balance FROM user_profiles WHERE username=%s", (username,))
    bal = float(cursor.fetchone()[0]); cost = float(qty) * float(price)
    if action == "BUY" and bal >= cost:
        cursor.execute("UPDATE user_profiles SET paper_balance = paper_balance - %s WHERE username=%s", (cost, username))
        cursor.execute("INSERT INTO user_portfolio (username, ticker, shares, entry_price, portfolio_type, is_active) VALUES (%s, %s, %s, %s, 'PAPER', 1)", (username, ticker, qty, price))
        conn.commit(); conn.close(); return True, "Trade Success"
    conn.close(); return False, "Insufficient Balance"

def deactivate_stock(username, ticker, ptype):
    conn = get_connection(); cursor = conn.cursor()
    cursor.execute("SELECT shares, entry_price FROM user_portfolio WHERE username=%s AND ticker=%s AND portfolio_type=%s", (username, ticker, ptype))
    row = cursor.fetchone()
    if row: cursor.execute("UPDATE user_portfolio SET is_active=FALSE WHERE username=%s AND ticker=%s AND portfolio_type=%s", (username, ticker, ptype))
    conn.commit(); conn.close()

# --- UI FUNCTIONS (FIXED GAUGE) ---

def create_gauge_html(score, label, color, size="big"):
    rad = 80 if size == "big" else 60
    vb = "0 0 200 120" if size == "big" else "0 0 160 100"
    fill = (score / 100) * (3.14159 * rad)
    header = f'<div style="text-align:center; color:#94a3b8; font-size:0.8rem; font-weight:bold; letter-spacing:1px; margin-bottom:5px;">PORTFOLIO RISK</div>' if size == "big" else ""
    svg = f"""
    <svg viewBox="{vb}" style="width:100%; height:auto;">
        <defs>
            <linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" style="stop-color:#4ade80"/><stop offset="50%" style="stop-color:#fbbf24"/><stop offset="100%" style="stop-color:#ef4444"/>
            </linearGradient>
        </defs>
        <path d="M 20 100 A {rad} {rad} 0 0 1 {20+rad*2} 100" fill="none" stroke="#334155" stroke-width="15" stroke-linecap="round"/>
        <path d="M 20 100 A {rad} {rad} 0 0 1 {20+rad*2} 100" fill="none" stroke="url(#g)" stroke-width="15" stroke-linecap="round" stroke-dasharray="{fill}, 1000"/>
        <text x="{20+rad}" y="80" font-family="sans-serif" font-size="38" font-weight="bold" fill="white" text-anchor="middle">{score}</text>
        <text x="{20+rad}" y="100" font-family="sans-serif" font-size="12" font-weight="bold" fill="{color}" text-anchor="middle" letter-spacing="2">{label}</text>
    </svg>
    """
    return f'<div class="card" style="padding-bottom:0; margin-bottom:0;">{header}{svg}</div>'

def render_portfolio_row(row, data, token):
    risk, label, color, _, _ = calculate_risk(data)
    p = float(data['current_price']); ch = float(data['day_change']); cc = "#4ade80" if ch>=0 else "#ef4444"
    s = float(row['shares']); e = float(row['entry_price'])
    pl_html = f"<div style='color:{'#4ade80' if p>=e else '#ef4444'}; font-size:0.75rem;'>{int(s)} @ ${e:.2f} • ${ (p-e)*s:,.2f} ({((p-e)/e)*100 if e>0 else 0:.1f}%)</div>"
    html = f'<a href="?token={token}&ticker={row["ticker"]}" target="_self" style="text-decoration:none;"><div class="card" style="display:flex; justify-content:space-between; align-items:center; border-left:4px solid {color};"><div><div style="font-weight:bold; color:white;">{row["ticker"]}</div>{pl_html}</div><div style="text-align:right;"><div style="color:white; font-weight:bold;">${p:,.2f}</div><div style="color:{cc}; font-size:0.8rem;">{ch:.2f}%</div></div></div></a>'
    st.markdown(html, unsafe_allow_html=True)

def render_horizontal_grid(rows_dict, current_token):
    h = '<div class="scrolling-wrapper">'
    for t, row in rows_dict.items():
        ch = float(row['day_change']); cc = "#4ade80" if ch>=0 else "#ef4444"
        h += f'<a href="?token={current_token}&ticker={t}" target="_self" style="text-decoration:none;"><div class="scrolling-card"><div style="font-weight:bold; color:white;">{t}</div><div style="color:{cc}; font-size:0.85rem;">{ch:.2f}%</div></div></a>'
    h += '</div>'; st.markdown(h, unsafe_allow_html=True)

def render_compact_watchlist(rows_list, token):
    h = '<div class="scrolling-wrapper">'
    for r in rows_list:
        risk, _, color, _, _ = calculate_risk(r)
        h += f'<a href="?token={token}&ticker={r["ticker"]}" target="_self" style="text-decoration:none;"><div class="scrolling-card"><div style="font-weight:bold; color:white;">{r["ticker"]}</div><div style="font-size:0.65rem; color:{color};">Risk: {risk}</div></div></a>'
    h += '</div>'; st.markdown(h, unsafe_allow_html=True)

def render_navbar(token, mode):
    m = "&mode=PAPER" if mode == "PAPER" else ""
    st.markdown(f'<div class="nav-container"><a href="?token={token}&tab=home{m}" class="nav-link">🏠</a><a href="?token={token}&tab=portfolio{m}" class="nav-link">📂</a><a href="?token={token}&tab=alerts{m}" class="nav-link">🔔</a><a href="?token={token}&tab=scanner{m}" class="nav-link">📡</a><a href="?token={token}&tab=settings{m}" class="nav-link">⚙️</a></div>', unsafe_allow_html=True)

# =========================================================
# 3. EXECUTION
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
tab = st.query_params.get("tab", "home")

if tab == "home":
    try:
        conn = get_connection(); cur = conn.cursor()
        cur.execute("SELECT content FROM daily_briefing WHERE id=1")
        row = cur.fetchone(); conn.close()
        if row: st.markdown(f'<div class="card" style="border-left:4px solid #facc15;"><div style="color:#facc15; font-size:0.8rem; font-weight:bold;">AI BRIEFING</div>{row[0]}</div>', unsafe_allow_html=True)
    except: pass

    st.markdown("### Portfolio Overview")
    port = get_portfolio_details(user['username'], current_mode)
    if port:
        ticks = [r['ticker'] for r in port]; d_map = get_cached_data_map(ticks)
        valid = [d_map[t] for t in ticks if t in d_map]
        if valid:
            avg = sum([calculate_risk(x)[0] for x in valid])/len(valid)
            st.markdown(create_gauge_html(int(avg), "LOW" if avg<35 else "MEDIUM" if avg<65 else "HIGH", "#4ade80" if avg<35 else "#fbbf24" if avg<65 else "#ef4444"), unsafe_allow_html=True)
            
            # --- BIG 3 METRICS ROW ---
            risk_t = max(valid, key=lambda x: calculate_risk(x)[0])['ticker']
            vol_t = max(valid, key=lambda x: abs(float(x['day_change'])))['ticker']
            e_list = [(r['ticker'], parse_smart_date(r.get('next_earnings'))) for r in valid]
            earn_t = min(e_list, key=lambda x: x[1])[0] if e_list else "N/A"
            st.markdown(f'<div style="display:flex; justify-content:space-between; background:#151922; padding:15px; border-radius:0 0 16px 16px; margin-top:-14px; margin-bottom:30px; border:1px solid #2d3748; border-top:none;"><div style="text-align:center; width:33%; border-right:1px solid #2d3748;"><div style="color:#94a3b8; font-size:0.6rem;">RISKIEST</div><div style="color:white; font-weight:bold;">{risk_t}</div></div><div style="text-align:center; width:33%; border-right:1px solid #2d3748;"><div style="color:#94a3b8; font-size:0.6rem;">VOLATILE</div><div style="color:white; font-weight:bold;">{vol_t}</div></div><div style="text-align:center; width:33%;"><div style="color:#94a3b8; font-size:0.6rem;">EARNINGS</div><div style="color:white; font-weight:bold;">{earn_t}</div></div></div>', unsafe_allow_html=True)
            
            render_horizontal_grid(d_map, token)
    
    st.markdown(f"### {datetime.now().strftime('%b %d')} Watchlist")
    render_compact_watchlist(get_watchlist_candidates(), token)

elif tab == "portfolio":
    st.markdown(f"### My Stocks ({current_mode})")
    total_pl, total_pct, day_pl, day_pct = get_portfolio_summary(user['username'], current_mode)
    c_pl = "#4ade80" if total_pl >= 0 else "#ef4444"
    st.markdown(f'<div style="display:flex; gap:10px; margin-bottom:20px;"><div class="metric-box" style="flex:1;"><div class="metric-label">Total P/L</div><div class="metric-value" style="color:{c_pl}">${total_pl:,.2f}</div><div class="metric-sub" style="color:{c_pl}">({total_pct:+.2f}%)</div></div><div class="metric-box" style="flex:1;"><div class="metric-label">Today</div><div class="metric-value">${day_pl:,.2f}</div></div></div>', unsafe_allow_html=True)
    
    # Portfolio display logic...
    port = get_portfolio_details(user['username'], current_mode)
    if port:
        d_map = get_cached_data_map([r['ticker'] for r in port])
        for r in port: 
            if r['ticker'] in d_map: render_portfolio_row(r, d_map[r['ticker']], token)

# DETAIL VIEW CRASH FIX
if "ticker" in st.query_params:
    t = st.query_params["ticker"]; stock = get_single_stock(t)
    if st.button("← Back"): del st.query_params["ticker"]; st.rerun()
    if stock:
        s, l, c, _, _ = calculate_risk(stock)
        p = float(stock['current_price']); ch = float(stock['day_change'])
        st.markdown(f"<h1>{t}</h1><h2 style='color:{'#4ade80' if ch>=0 else '#ef4444'}'>${p:,.2f} ({ch:.2f}%)</h2>", unsafe_allow_html=True)
        st.markdown(create_gauge_html(s, l, c, "big"), unsafe_allow_html=True)
        
        # KEYERROR SURGERY
        v_cls, v_txt = ("pill-low", "LOW") if float(stock.get('volatility', 0)) < 2 else ("pill-high", "HIGH")
        st.markdown(f"<div class='card'><div class='risk-row'><div>Volatility</div><div class='risk-pill {v_cls}'>{v_txt}</div></div></div>", unsafe_allow_html=True)
    st.stop()

render_navbar(token, current_mode)
