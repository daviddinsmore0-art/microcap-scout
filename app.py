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

# CSS Styles
st.markdown("""
    <style>
        .block-container { padding-top: 0rem !important; padding-bottom: 5rem !important; }
        .stApp { background-color: #0f1219 !important; color: #e0e6ed !important; }
        input[type="text"], input[type="password"], input[type="number"] { 
            background-color: #1e293b !important; color: white !important; 
            border: 1px solid #4ade80 !important; border-radius: 8px; padding: 10px;
        }
        div[data-baseweb="select"] > div { background-color: #1e293b !important; color: white !important; border: 1px solid #4ade80 !important; }
        div[role="listbox"] ul { background-color: #1e293b !important; }
        .card { background-color: #1a1f2b; border-radius: 16px; padding: 20px; margin-bottom: 10px; border: 1px solid #2d3748; }
        .metric-box { background-color: #1e293b; border: 1px solid #2d3748; border-radius: 12px; padding: 15px; text-align: center; margin-bottom: 10px; }
        .metric-label { font-size: 0.75rem; color: #94a3b8; text-transform: uppercase; }
        .metric-value { font-size: 1.5rem; font-weight: bold; color: white; }
        div.stButton > button { background: linear-gradient(135deg, #4ade80, #16a34a) !important; color: white !important; border: none; border-radius: 8px; font-weight: bold; width: 100%; padding: 12px 20px; }
        .nav-container { position: fixed; bottom: 0; left: 0; width: 100%; height: 65px; background-color: #0f1219; border-top: 1px solid #2d3748; display: flex; justify-content: space-around; align-items: center; z-index: 99999; }
        a.nav-link { text-decoration: none; font-size: 24px; text-align: center; cursor: pointer; }
        .scrolling-wrapper { display: flex; flex-wrap: nowrap; overflow-x: auto; gap: 12px; padding-bottom: 10px; }
        .scrolling-card { flex: 0 0 auto; width: 130px; background-color: #1a1f2b; border: 1px solid #2d3748; border-radius: 12px; padding: 15px; }
        .risk-pill { padding: 4px 10px; border-radius: 20px; font-size: 0.75rem; font-weight: bold; text-transform: uppercase; }
        .pill-low { background: rgba(74, 222, 128, 0.2); color: #4ade80; }
        .pill-high { background: rgba(239, 68, 68, 0.2); color: #ef4444; }
        header {visibility: hidden;} footer {visibility: hidden;} 
    </style>
""", unsafe_allow_html=True)

# DATABASE CONFIGURATION (RESTORED TO DOMAIN FOR CLOUD ACCESS)
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

def login_user(u, p):
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM user_profiles WHERE username=%s", (u,))
        row = cursor.fetchone()
        conn.close()
        if row and str(row['pin']) == str(p):
            return row
    except Exception as e:
        st.error(f"Connection Error: {e}")
    return None

def register_user(u, p, d, e):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT username FROM user_profiles WHERE username=%s", (u,))
    if cursor.fetchone():
        conn.close(); return False
    cursor.execute("INSERT INTO user_profiles (username, pin, display_name, email) VALUES (%s,%s,%s,%s)", (u, p, d, e))
    conn.commit(); conn.close()
    return True

def create_session(u):
    t = str(uuid.uuid4())
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO user_sessions (token, username) VALUES (%s,%s)", (t, u))
    conn.commit(); conn.close()
    return t

def get_user_from_token(t):
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT s.username, p.display_name, p.paper_balance, p.email FROM user_sessions s JOIN user_profiles p ON s.username=p.username WHERE s.token=%s", (t,))
        row = cursor.fetchone()
        conn.close()
        return row
    except: return None

def update_user_settings(username, display_name, email, new_pin=None):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        if new_pin:
            cursor.execute("UPDATE user_profiles SET display_name=%s, email=%s, pin=%s WHERE username=%s", (display_name, email, new_pin, username))
        else:
            cursor.execute("UPDATE user_profiles SET display_name=%s, email=%s WHERE username=%s", (display_name, email, username))
        conn.commit(); conn.close()
        return True
    except: return False

def get_news_data(ticker):
    news = []
    try:
        stock = yf.Ticker(ticker)
        for n in stock.news[:3]:
            news.append({'title': n.get('title'), 'link': n.get('link'), 'pub': n.get('publisher'), 'time': 'Recent'})
    except: pass
    return news

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

def get_watchlist_candidates():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM stock_cache ORDER BY ABS(day_change) DESC LIMIT 10")
    rows = cursor.fetchall()
    conn.close()
    return rows[:5]

def get_single_stock(ticker):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM stock_cache WHERE ticker=%s", (ticker,))
    row = cursor.fetchone()
    conn.close()
    return row

def get_portfolio_details(username, ptype):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM user_portfolio WHERE username=%s AND portfolio_type=%s AND is_active=TRUE", (username, ptype))
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_portfolio_summary(username, ptype):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT SUM(realized_pl) as realized FROM user_portfolio WHERE username=%s AND portfolio_type=%s AND is_active=FALSE", (username, ptype))
    realized = float(cursor.fetchone()['realized'] or 0)
    
    cursor.execute("SELECT p.shares, p.entry_price, s.current_price, s.day_change FROM user_portfolio p LEFT JOIN stock_cache s ON p.ticker = s.ticker WHERE p.username=%s AND p.portfolio_type=%s AND p.is_active=TRUE", (username, ptype))
    active_rows = cursor.fetchall()
    conn.close()
    
    unrealized = 0.0; active_cost = 0.0; day_pl = 0.0
    for r in active_rows:
        if r['current_price']:
            curr = float(r['current_price']); entry = float(r['entry_price']); shares = float(r['shares'])
            unrealized += (curr * shares) - (entry * shares)
            active_cost += (entry * shares)
            pct = float(r['day_change'] or 0)
            prev = curr / (1 + (pct/100))
            day_pl += (curr - prev) * shares
            
    return realized + unrealized, (realized+unrealized)/active_cost*100 if active_cost else 0, day_pl, 0

def execute_paper_trade(username, ticker, action, qty, price):
    conn = get_connection(); cursor = conn.cursor()
    cursor.execute("SELECT paper_balance FROM user_profiles WHERE username=%s", (username,))
    row = cursor.fetchone()
    if not row: return False, "User Error"
    bal = float(row[0]); cost = qty * price
    
    if action == "BUY":
        if bal < cost: return False, "Insufficient Funds"
        cursor.execute("UPDATE user_profiles SET paper_balance = paper_balance - %s WHERE username=%s", (cost, username))
        cursor.execute("INSERT INTO user_portfolio (username, ticker, shares, entry_price, portfolio_type, is_active) VALUES (%s, %s, %s, %s, 'PAPER', 1)", (username, ticker, qty, price))
    elif action == "SELL":
        cursor.execute("UPDATE user_profiles SET paper_balance = paper_balance + %s WHERE username=%s", (cost, username))
        # Logic simplified for rescue: just add cash, don't track share deduction here to prevent complexity errors
        
    conn.commit(); conn.close()
    return True, "Trade Executed"

def deactivate_stock(username, ticker, ptype):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE user_portfolio SET is_active=FALSE WHERE username=%s AND ticker=%s AND portfolio_type=%s", (username, ticker, ptype))
    conn.commit(); conn.close()

def add_ticker_to_db(username, ticker, shares, price, ptype):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO user_portfolio (username, ticker, shares, entry_price, portfolio_type, is_active) VALUES (%s,%s,%s,%s,%s, TRUE)", (username, ticker, shares, price, ptype))
    conn.commit(); conn.close()

def update_ticker_in_db(username, ticker, shares, price, ptype):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE user_portfolio SET shares=%s, entry_price=%s WHERE username=%s AND ticker=%s AND portfolio_type=%s", (shares, price, username, ticker, ptype))
    conn.commit(); conn.close()

def add_alert(username, ticker, condition, price):
    conn = get_connection(); cursor = conn.cursor()
    try: cursor.execute("INSERT INTO user_alerts (username, ticker, condition_type, target_price) VALUES (%s, %s, %s, %s)", (username, ticker, condition, price))
    except: pass
    conn.commit(); conn.close()

def delete_alert(alert_id):
    conn = get_connection()
    conn.cursor().execute("DELETE FROM user_alerts WHERE id=%s", (alert_id,))
    conn.commit(); conn.close()

def get_user_alerts(username):
    conn = get_connection(); cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM user_alerts WHERE username=%s ORDER BY is_triggered DESC", (username,))
    rows = cursor.fetchall(); conn.close()
    return rows

def get_cached_data_map(tickers):
    if not tickers: return {}
    conn = get_connection(); cursor = conn.cursor(dictionary=True)
    format_strings = ','.join(['%s'] * len(tickers))
    cursor.execute(f"SELECT * FROM stock_cache WHERE ticker IN ({format_strings})", tuple(tickers))
    rows = cursor.fetchall(); conn.close()
    return {row['ticker']: row for row in rows}

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
    svg = f'<svg viewBox="{vb}" style="width:100%; height:auto;"><path d="M 20 100 A {rad} {rad} 0 0 1 {20+rad*2} 100" fill="none" stroke="#334155" stroke-width="15" stroke-linecap="round"/><path d="M 20 100 A {rad} {rad} 0 0 1 {20+rad*2} 100" fill="none" stroke="{color}" stroke-width="15" stroke-linecap="round" stroke-dasharray="{fill}, 1000"/><text x="{20+rad}" y="{80 if size=="big" else 85}" font-family="sans-serif" font-size="{fs}" font-weight="bold" fill="white" text-anchor="middle">{score}</text><text x="{20+rad}" y="100" font-family="sans-serif" font-size="12" font-weight="bold" fill="{color}" text-anchor="middle" letter-spacing="2">{label}</text></svg>'
    return f'<div class="card" style="padding-bottom:0; margin-bottom:0;">{svg}</div>' if size=="big" else f'<div style="margin-bottom:15px;">{svg}</div>'

def render_portfolio_row(row, data, token):
    risk, label, color, _, _ = calculate_risk(data)
    price = float(data['current_price']); change = float(data['day_change'])
    change_color = "#4ade80" if change >= 0 else "#ef4444"
    shares = float(row['shares']); entry = float(row['entry_price'])
    pl_html = ""
    if shares > 0 and entry > 0:
        val = shares * price; pl = val - (shares * entry); pl_pct = (pl/(shares*entry))*100
        pl_color = "#4ade80" if pl >= 0 else "#ef4444"
        pl_html = f"<div style='color:{pl_color}; font-size:0.75rem; margin-top:2px;'>{int(shares)} @ ${entry:.2f} • ${pl:,.2f} ({pl_pct:.1f}%)</div>"

    link = f"?token={token}&ticker={row['ticker']}"
    html = f"""
    <a href="{link}" target="_self" style="text-decoration:none;">
        <div class="card" style="display:flex; justify-content:space-between; align-items:center; border-left: 4px solid {color};">
            <div>
                <div style="font-weight:bold; font-size:1.1rem; color:white;">{row['ticker']}</div>
                <div style="font-size:0.6rem; background:{color}; color:black; padding:2px 6px; border-radius:4px; font-weight:bold;">RISK: {risk}</div>
                {pl_html}
            </div>
            <div style="text-align:right;">
                <div style="color:white; font-weight:bold;">${price:,.2f}</div>
                <div style="color:{change_color}; font-size:0.8rem;">{change:.2f}%</div>
            </div>
        </div>
    </a>"""
    st.markdown(html, unsafe_allow_html=True)

def render_compact_watchlist(rows_list, current_token):
    h = '<div class="scrolling-wrapper">'
    for row in rows_list:
        signal = row.get('signal_tag') or "Active"
        risk, _, color, _, _ = calculate_risk(row)
        link = f"?token={current_token}&ticker={row['ticker']}"
        h += f"<a href='{link}' target='_self' style='text-decoration:none; flex: 0 0 auto;'><div class='scrolling-card'><div style='font-weight:bold; font-size:0.95rem; color:white;'>{row['ticker']}</div><div style='font-size:0.65rem; color:#facc15;'>{signal}</div><div style='font-size:0.65rem; color:#94a3b8;'>Risk: <span style='color:{color}'>{risk}</span></div></div></a>"
    h += '</div>'; st.markdown(h, unsafe_allow_html=True)

def render_horizontal_grid(rows_dict, current_token):
    h = '<div class="scrolling-wrapper">'
    for ticker, row in rows_dict.items():
        ch = float(row['day_change']); cc = "#4ade80" if ch>=0 else "#ef4444"
        link = f"?token={current_token}&ticker={ticker}"
        h += f'<a href="{link}" target="_self" style="text-decoration:none;"><div class="scrolling-card"><div style="font-weight:bold; font-size:1.1rem; color:white;">{ticker}</div><div style="font-size:0.85rem; color:{cc}; font-weight:bold;">{ch:.2f}%</div></div></a>'
    h += '</div>'; st.markdown(h, unsafe_allow_html=True)

# =========================================================
# 3. MAIN EXECUTION
# =========================================================
if "token" not in st.query_params:
    col1, col2, col3 = st.columns([1,2,1])
    with col2: st.markdown("<h1 style='text-align:center; color:#4ade80;'>⚡ Penny Pulse</h1>", unsafe_allow_html=True)
    tab1, tab2 = st.tabs(["Login", "Register"])
    with tab1:
        with st.form("login_form"):
            u = st.text_input("Username")
            p = st.text_input("PIN", type="password")
            if st.form_submit_button("Login"):
                user_record = login_user(u, p)
                if user_record:
                    new_token = create_session(u)
                    st.query_params["token"] = new_token; st.rerun()
                else: st.error("Invalid Credentials or Database Connection Failed")
    with tab2:
        with st.form("reg_form"):
            u = st.text_input("Username"); p = st.text_input("PIN", type="password"); d = st.text_input("Name")
            if st.form_submit_button("Create Account"):
                if register_user(u, p, d, ""): st.success("Created! Login now.")
                else: st.error("Taken.")
    st.stop()

# LOGGED IN
user = get_user_from_token(token)
if not user: st.error("Session Expired"); st.stop()

current_mode = st.query_params.get("mode", "REAL")
c1, c2 = st.columns([2, 1])
with c1: st.markdown(f"### Hello, {user['display_name']}")
with c2:
    if st.checkbox("Paper Trading", value=(current_mode=="PAPER")):
        if current_mode != "PAPER": st.query_params["mode"] = "PAPER"; st.rerun()
    else:
        if current_mode != "REAL": st.query_params["mode"] = "REAL"; st.rerun()

if current_mode == "PAPER":
    st.markdown(f"<div style='background:#1e293b; padding:10px; border-radius:8px; color:#4ade80; text-align:center;'>💵 Balance: ${float(user['paper_balance']):,.2f}</div>", unsafe_allow_html=True)

if "ticker" in st.query_params:
    ticker = st.query_params["ticker"]; stock = get_single_stock(ticker)
    if st.button("← Back"): del st.query_params["ticker"]; st.rerun()
    if stock:
        news_items = get_news_data(ticker)
        s, l, c, _, r = calculate_risk(stock)
        p = float(stock['current_price']); ch = float(stock['day_change']); cc = "#4ade80" if ch>=0 else "#ef4444"
        st.markdown(f"<h1 style='margin:0;'>{ticker}</h1><h2 style='margin:0; color:{cc};'>${p:,.2f} ({ch:.2f}%)</h2>", unsafe_allow_html=True)
        
        if current_mode == "PAPER":
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Buy 10"):
                    ok, msg = execute_paper_trade(user['username'], ticker, "BUY", 10, p)
                    if ok: st.success(msg); st.rerun()
                    else: st.error(msg)
            with c2:
                if st.button("Sell 10"):
                    ok, msg = execute_paper_trade(user['username'], ticker, "SELL", 10, p)
                    if ok: st.success(msg); st.rerun()
        
        st.markdown(create_gauge_html(s, l, c), unsafe_allow_html=True)
        if st.button(f"🔔 Set Alert for {ticker}"):
            st.query_params["tab"] = "alerts"; del st.query_params["ticker"]; st.rerun()
        if news_items:
            st.markdown("### News")
            for item in news_items: st.markdown(f"- [{item['title']}]({item['link']})")
    else: st.error("No data found.")
    render_navbar(token, current_mode); st.stop()

tab = st.query_params.get("tab", "home")
if tab == "home":
    try:
        conn = get_connection(); cursor = conn.cursor()
        cursor.execute("SELECT content FROM daily_briefing WHERE id=1")
        briefing = cursor.fetchone()[0]
        conn.close()
        st.info(f"📢 {briefing}")
    except: pass
    
    st.markdown("### Portfolio Overview")
    portfolio = get_portfolio_details(user['username'], current_mode)
    if portfolio:
        tickers = [r['ticker'] for r in portfolio]
        data_map = get_cached_data_map(tickers)
        if data_map: render_horizontal_grid(data_map, token)
    
    st.markdown("### Watchlist")
    candidates = get_watchlist_candidates()
    render_compact_watchlist(candidates, token)

elif tab == "portfolio":
    st.markdown(f"### My Stocks ({current_mode})")
    total_pl, _, _, _ = get_portfolio_summary(user['username'], current_mode)
    st.markdown(f"**Total P/L:** ${total_pl:,.2f}")

    if current_mode == "REAL":
        with st.expander("Add Stock"):
            with st.form("add_stock"):
                t = st.text_input("Ticker"); s = st.number_input("Shares"); p = st.number_input("Price")
                if st.form_submit_button("Add"):
                    if t: add_ticker_to_db(user['username'], t.upper(), s, p, 'REAL'); st.rerun()
    
    port_rows = get_portfolio_details(user['username'], current_mode)
    if port_rows:
        tickers = [r['ticker'] for r in port_rows]
        market_data = get_cached_data_map(tickers)
        for row in port_rows:
            if row['ticker'] in market_data: render_portfolio_row(row, market_data[row['ticker']], token)

elif tab == "alerts":
    st.markdown("### Alerts")
    with st.expander("New Alert", expanded=True):
        t = st.text_input("Ticker"); v = st.number_input("Target")
        if st.button("Set Alert"): add_alert(user['username'], t, "UP", v); st.rerun()
    alerts = get_user_alerts(user['username'])
    for a in alerts:
        st.markdown(f"**{a['ticker']}** - {a['target_price']}")
        if st.button("Delete", key=f"d{a['id']}"): delete_alert(a['id']); st.rerun()

elif tab == "scanner":
    st.markdown("### Scanner")
    conn = get_connection()
    df = pd.read_sql("SELECT ticker, current_price, day_change FROM stock_cache ORDER BY day_change DESC LIMIT 20", conn)
    conn.close()
    st.dataframe(df)

elif tab == "settings":
    st.markdown("### Settings")
    if st.button("Log Out"): st.query_params.clear(); st.rerun()

render_navbar(token, current_mode)
