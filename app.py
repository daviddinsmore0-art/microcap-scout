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
            background-color: #1e293b !important; color: white !important; 
            border: 1px solid #4ade80 !important; border-radius: 8px; padding: 10px;
        }
        div[data-baseweb="input"] { background-color: transparent !important; border: none; }
        
        div[data-baseweb="select"] > div { 
            background-color: #1e293b !important; color: white !important; border: 1px solid #4ade80 !important; 
        }
        li[role="option"]:hover { background-color: #4ade80 !important; color: black !important; }
        
        /* THE BUTTON EFFECT */
        .card, .scrolling-card, .clickable-card { 
            background-color: #1a1f2b; border-radius: 16px; padding: 20px; 
            margin-bottom: 10px; border: 1px solid #2d3748; box-shadow: 0 4px 6px rgba(0,0,0,0.3); 
            transition: transform 0.1s ease, border-color 0.1s ease;
            cursor: pointer;
        }
        .card:active, .scrolling-card:active, .clickable-card:active {
            transform: scale(0.97);
            border-color: #4ade80 !important;
        }
        
        .metric-box {
            background-color: #1e293b; border: 1px solid #2d3748; border-radius: 12px;
            padding: 15px; text-align: center; margin-bottom: 10px;
        }
        .metric-label { font-size: 0.75rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 5px; }
        .metric-value { font-size: 1.5rem; font-weight: bold; color: white; margin-bottom: 2px; }
        
        div.stButton > button {
            background: linear-gradient(135deg, #4ade80, #16a34a) !important; 
            color: white !important; border: none; border-radius: 8px; 
            font-weight: bold; width: 100%; padding: 12px 20px;
        }
        
        h1, h2, h3, p, label, span, div { color: #e0e6ed; }
        a { color: #ffffff !important; text-decoration: none !important; }
        
        .nav-container { 
            position: fixed; bottom: 0; left: 0; width: 100%; height: 65px; 
            background-color: #0f1219; border-top: 1px solid #2d3748; 
            display: flex; justify-content: space-around; align-items: center; z-index: 99999; 
        }
        a.nav-link { text-decoration: none; font-size: 24px; text-align: center; }
        
        .scrolling-wrapper { 
            display: flex; flex-wrap: nowrap; overflow-x: auto; gap: 12px; 
            padding-bottom: 10px; -ms-overflow-style: none; scrollbar-width: none; 
        }
        .scrolling-wrapper::-webkit-scrollbar { display: none; }
        .scrolling-card { flex: 0 0 auto; width: 130px; padding: 15px; margin-bottom: 0; }
        
        .risk-pill { padding: 4px 10px; border-radius: 20px; font-size: 0.75rem; font-weight: bold; text-transform: uppercase; }
        .pill-low { background: rgba(74, 222, 128, 0.2); color: #4ade80; }
        .pill-med { background: rgba(251, 191, 36, 0.2); color: #fbbf24; }
        .pill-high { background: rgba(239, 68, 68, 0.2); color: #ef4444; }
        .risk-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; border-bottom: 1px solid #2d3748; padding-bottom: 5px; }
        
        header {visibility: hidden;} footer {visibility: hidden;} 
    </style>
""", unsafe_allow_html=True)

DB_CONFIG = {"host": "atlanticcanadaschoice.com", "user": "atlantic", "password": "1q2w3e4R!!", "database": "atlantic_pennypulse", "connect_timeout": 30}
OPENAI_KEY = st.secrets["openai"]["api_key"] if "openai" in st.secrets else None
token = st.query_params.get("token", None)

# =========================================================
# 2. FUNCTIONS
# =========================================================

def get_connection(): return mysql.connector.connect(**DB_CONFIG)

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
        target = datetime.strptime(f"{date_str} {now.year}", "%b %d %Y")
        if target < now: target = datetime.strptime(f"{date_str} {now.year + 1}", "%b %d %Y")
        return (target - now).days
    except: return 999

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
    row = cursor.fetchone(); conn.close(); return row

def calculate_risk(row, ai_score=None):
    s = 50
    rsi = float(row.get('rsi') or 50)
    if rsi > 70: s += 10
    elif rsi < 30: s -= 10
    vol = float(row.get('volatility') or 0)
    if vol > 3.0: s += 15
    final = max(0, min(100, int(s)))
    color = "#4ade80" if final < 35 else "#fbbf24" if final < 65 else "#ef4444"
    label = "LOW" if final < 35 else "MEDIUM" if final < 65 else "HIGH"
    return final, label, color, "badge", []

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

def get_watchlist_candidates():
    conn = get_connection(); cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM stock_cache ORDER BY ABS(day_change) DESC LIMIT 10")
    rows = cursor.fetchall(); conn.close(); return rows[:3]

# --- UI COMPONENTS ---

def get_greeting(name):
    hour = datetime.now(pytz.timezone('America/Halifax')).hour
    if hour < 12: return f"Good Morning, {name}"
    elif 12 <= hour < 18: return f"Good Afternoon, {name}"
    else: return f"Good Evening, {name}"

def create_gauge_html(score, label, color, size="big"):
    rad = 80 if size == "big" else 60
    vb = "0 0 200 120"
    fill = (score / 100) * (3.14159 * rad)
    header = f'<div style="text-align:center; color:#94a3b8; font-size:0.8rem; font-weight:bold; letter-spacing:1px; margin-bottom:5px;">PORTFOLIO RISK</div>' if size == "big" else ""
    svg = f"""<svg viewBox="{vb}" style="width:100%; height:auto;"><defs><linearGradient id="g"><stop offset="0%" stop-color="#4ade80"/><stop offset="50%" stop-color="#fbbf24"/><stop offset="100%" stop-color="#ef4444"/></linearGradient></defs><path d="M 20 100 A {rad} {rad} 0 0 1 {20+rad*2} 100" fill="none" stroke="#334155" stroke-width="15" stroke-linecap="round"/><path d="M 20 100 A {rad} {rad} 0 0 1 {20+rad*2} 100" fill="none" stroke="url(#g)" stroke-width="15" stroke-linecap="round" stroke-dasharray="{fill}, 1000"/><text x="{20+rad}" y="80" font-family="sans-serif" font-size="38" font-weight="bold" fill="white" text-anchor="middle">{score}</text><text x="{20+rad}" y="100" font-family="sans-serif" font-size="12" font-weight="bold" fill="{color}" text-anchor="middle" letter-spacing="2">{label}</text></svg>"""
    return f'<div class="card" style="padding-bottom:0; margin-bottom:0;">{header}{svg}</div>'

def render_horizontal_grid(rows_dict, current_token):
    h = '<div class="scrolling-wrapper">'
    for ticker, row in rows_dict.items():
        ch = float(row['day_change']); cc = "#4ade80" if ch>=0 else "#ef4444"
        h += f'<a href="?token={current_token}&ticker={ticker}" target="_self" style="text-decoration:none;"><div class="scrolling-card card"><div style="font-weight:bold; font-size:1.1rem; color:white;">{ticker}</div><div style="font-size:0.85rem; color:{cc}; font-weight:bold;">{"▲" if ch>=0 else "▼"} {abs(ch):.2f}%</div></div></a>'
    h += '</div>'; st.markdown(h, unsafe_allow_html=True)

def render_compact_watchlist(rows_list, current_token):
    h = '<div class="scrolling-wrapper">'
    for row in rows_list:
        risk, _, color, _, _ = calculate_risk(row)
        h += f"<a href='?token={current_token}&ticker={row['ticker']}' target='_self' style='text-decoration:none;'><div class='scrolling-card clickable-card' style='width: 140px;'><div style='font-weight:bold; font-size:0.95rem; color:white;'>{row['ticker']}</div><div style='font-size:0.65rem; color:#94a3b8; margin-top:5px;'>Risk: <span style='color:{color}'>{risk}</span></div></div></a>"
    h += '</div>'
    st.markdown(h, unsafe_allow_html=True)

def render_navbar(token, mode):
    m = "&mode=PAPER" if mode == "PAPER" else ""
    st.markdown(f'<div class="nav-container"><a href="?token={token}&tab=home{m}" class="nav-link">🏠</a><a href="?token={token}&tab=portfolio{m}" class="nav-link">📂</a><a href="?token={token}&tab=alerts{m}" class="nav-link">🔔</a><a href="?token={token}&tab=scanner{m}" class="nav-link">📡</a><a href="?token={token}&tab=settings{m}" class="nav-link">⚙️</a></div>', unsafe_allow_html=True)

# =========================================================
# 3. EXECUTION
# =========================================================
init_db()

if "token" not in st.query_params:
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        if os.path.exists("logo.png"): st.image("logo.png", width=150)
        else: st.markdown("<h1 style='text-align:center; color:#4ade80;'>⚡ Penny Pulse</h1>", unsafe_allow_html=True)
            
    tab1, tab2, tab3 = st.tabs(["Login", "Register", "Forgot PIN"])
    with tab1:
        with st.form("login_form"):
            u = st.text_input("Username"); p = st.text_input("PIN", type="password")
            if st.form_submit_button("Login"):
                user_rec = login_user(u, p)
                if user_rec: st.query_params["token"] = create_session(u); st.rerun()
                else: st.error("Invalid Login")
    with tab2:
        with st.form("reg_form"):
            u = st.text_input("New Username"); p = st.text_input("New PIN", type="password"); d = st.text_input("Display Name")
            if st.form_submit_button("Create Account"):
                if register_user(u, p, d, ""): st.success("Created! Please login.")
                else: st.error("Taken.")
    with tab3:
        st.info("Request a PIN reset via support.")
    st.stop()

user = get_user_from_token(token)
st.markdown(f"### {get_greeting(user['display_name'])}")

current_mode = st.query_params.get("mode", "REAL")
tab = st.query_params.get("tab", "home")

if "ticker" in st.query_params:
    ticker = st.query_params["ticker"]; stock = get_single_stock(ticker)
    if st.button("← Back"): del st.query_params["ticker"]; st.rerun()
    if stock:
        # SURGICAL FIX: ALL 3 FACTORS RESTORED + CRASH PREVENTION
        rsi_val = float(stock.get('rsi') or 50)
        vol_val = float(stock.get('volatility') or 0)
        debt_val = float(stock.get('debt_ratio') or 0)
        s, l, c, _, _ = calculate_risk(stock)
        st.markdown(f"<h1>{ticker}</h1>", unsafe_allow_html=True)
        st.markdown(create_gauge_html(s, l, c), unsafe_allow_html=True)
        st.markdown(f"<div class='card' style='margin-top:15px;'><div style='color:#94a3b8; font-size:0.8rem; font-weight:bold;'>RISK FACTORS</div>", unsafe_allow_html=True)
        def get_pill(val, type="risk"):
            if type=="vol": return ("pill-high", "HIGH") if val > 3 else ("pill-low", "LOW")
            if type=="debt": return ("pill-high", "HIGH") if val > 150 else ("pill-low", "LOW")
            if type=="rsi": return ("pill-med", "EXTREME") if val > 70 or val < 30 else ("pill-low", "NORMAL")
            return ("pill-low", "LOW")
        v_cls, v_txt = get_pill(vol_val, "vol")
        st.markdown(f"<div class='risk-row'><div>Volatility</div><div class='risk-pill {v_cls}'>{v_txt}</div></div>", unsafe_allow_html=True)
        d_cls, d_txt = get_pill(debt_val, "debt")
        st.markdown(f"<div class='risk-row'><div>Debt / Equity</div><div class='risk-pill {d_cls}'>{d_txt}</div></div>", unsafe_allow_html=True)
        r_cls, r_txt = get_pill(rsi_val, "rsi")
        st.markdown(f"<div class='risk-row' style='border:none;'><div>RSI Momentum</div><div class='risk-pill {r_cls}'>{r_txt}</div></div></div>", unsafe_allow_html=True)
    st.stop()

if tab == "home":
    portfolio = get_portfolio_details(user['username'], current_mode)
    if portfolio:
        ticks = [r['ticker'] for r in portfolio]; d_map = get_cached_data_map(ticks)
        valid = [d_map[t] for t in ticks if t in d_map]
        if valid:
            avg = sum([calculate_risk(x)[0] for x in valid])/len(valid)
            st.markdown(create_gauge_html(int(avg), "MEDIUM" if avg<65 else "HIGH", "#fbbf24"), unsafe_allow_html=True)
            risk_t = max(valid, key=lambda x: calculate_risk(x)[0])['ticker']
            vol_t = max(valid, key=lambda x: abs(float(x['day_change'])))['ticker']
            st.markdown(f"""<div style="display:flex; justify-content:space-between; background:#151922; padding:15px; border-radius:0 0 16px 16px; margin-top:-14px; margin-bottom:30px; border:1px solid #2d3748; border-top:none;"><div style="text-align:center; width:50%; border-right:1px solid #2d3748;"><div style="color:#94a3b8; font-size:0.6rem;">RISKIEST</div><div style="color:white; font-weight:bold;">{risk_t}</div></div><div style="text-align:center; width:50%;"><div style="color:#94a3b8; font-size:0.6rem;">VOLATILE</div><div style="color:white; font-weight:bold;">{vol_t}</div></div></div>""", unsafe_allow_html=True)
            render_horizontal_grid(d_map, token)
    render_compact_watchlist(get_watchlist_candidates(), token)

render_navbar(token, current_mode)
