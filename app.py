import streamlit as st
import mysql.connector
import yfinance as yf
import requests
import uuid
import os
import pandas as pd
import pytz
import json
from datetime import datetime

# =========================================================
# 1. CONFIGURATION & CSS (Must be at the very top)
# =========================================================
st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="centered", initial_sidebar_state="collapsed")

# Force Dark Theme & clean UI elements
st.markdown("""
    <style>
        .stApp { background-color: #0f1219 !important; color: #e0e6ed !important; }
        
        /* Form Inputs */
        input[type="text"], input[type="password"], input[type="number"] { 
            background-color: #1e293b !important; 
            color: white !important; 
            border: 1px solid #4ade80 !important; 
            border-radius: 8px; 
        }
        
        /* Cards */
        .card { 
            background-color: #1a1f2b; 
            border-radius: 16px; 
            padding: 20px; 
            margin-bottom: 10px; 
            border: 1px solid #2d3748; 
        }
        
        /* Buttons */
        div.stButton > button {
            background: linear-gradient(135deg, #4ade80, #16a34a) !important; 
            color: white !important; 
            border: none; 
            border-radius: 8px; 
            font-weight: bold;
            width: 100%;
        }
        
        h1, h2, h3, p, label, span, div { color: #e0e6ed; }
        
        /* Navigation */
        .nav-container { 
            position: fixed; bottom: 0; left: 0; width: 100%; height: 60px; 
            background-color: #0f1219; border-top: 1px solid #2d3748; 
            display: flex; justify-content: space-around; align-items: center; z-index: 999; 
        }
        a.nav-link { text-decoration: none; font-size: 20px; text-align: center; cursor: pointer;}
    </style>
""", unsafe_allow_html=True)

# Global Constants
MARKET_UNIVERSE = ["TSLA", "NVDA", "AMD", "AAPL", "PLTR", "SOFI", "MARA", "GME", "AMC", "COIN", "MSFT", "GOOG", "AMZN", "META", "NFLX"]
DB_CONFIG = {
    "host": "atlanticcanadaschoice.com", 
    "user": "atlantic", 
    "password": "1q2w3e4R!!", 
    "database": "atlantic_pennypulse", 
    "connect_timeout": 30
}

# =========================================================
# 2. FUNCTIONS (DEFINED HERE SO PYTHON SEES THEM)
# =========================================================

def get_connection():
    return mysql.connector.connect(**DB_CONFIG)

def init_db():
    # Expanded try/except blocks to prevent SyntaxError on older Python
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # Create Tables
        cursor.execute("CREATE TABLE IF NOT EXISTS user_profiles (username VARCHAR(255) PRIMARY KEY, pin VARCHAR(50), display_name VARCHAR(100), email VARCHAR(255), paper_balance DECIMAL(20,2) DEFAULT 10000.00)")
        cursor.execute("CREATE TABLE IF NOT EXISTS user_sessions (token VARCHAR(255) PRIMARY KEY, username VARCHAR(255))")
        cursor.execute("CREATE TABLE IF NOT EXISTS user_portfolio (id INT NOT NULL AUTO_INCREMENT, username VARCHAR(255), ticker VARCHAR(20), shares DECIMAL(10,4) DEFAULT 0, entry_price DECIMAL(20,4) DEFAULT 0, portfolio_type VARCHAR(20) DEFAULT 'REAL', PRIMARY KEY (id))")
        cursor.execute("CREATE TABLE IF NOT EXISTS user_alerts (id INT NOT NULL AUTO_INCREMENT PRIMARY KEY, username VARCHAR(255), ticker VARCHAR(20), condition_type VARCHAR(10), target_price DECIMAL(20,4), is_triggered BOOLEAN DEFAULT FALSE)")
        cursor.execute("CREATE TABLE IF NOT EXISTS stock_cache (ticker VARCHAR(20) PRIMARY KEY, company_name VARCHAR(255), current_price DECIMAL(20,4), day_change DECIMAL(10,2), rsi DECIMAL(10,2), trend_status VARCHAR(20), volume_status VARCHAR(20), range_loc DECIMAL(10,2), volatility DECIMAL(10,2), debt_ratio DECIMAL(10,2), days_to_earnings INT, market_cap BIGINT, eps DECIMAL(10,2), signal_tag VARCHAR(50), last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)")
        
        # Migrations (Separated for safety)
        try:
            cursor.execute("ALTER TABLE user_profiles ADD COLUMN paper_balance DECIMAL(20,2) DEFAULT 10000.00")
        except:
            pass
        
        try:
            cursor.execute("ALTER TABLE user_portfolio ADD COLUMN portfolio_type VARCHAR(20) DEFAULT 'REAL'")
        except:
            pass

        conn.close()
    except Exception as e:
        st.error(f"Database Error: {e}")

# --- Auth Functions ---
def login_user(u, p):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM user_profiles WHERE username=%s", (u,))
    row = cursor.fetchone()
    conn.close()
    if row and str(row['pin']) == str(p):
        return row
    return None

def register_user(u, p, d, e):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT username FROM user_profiles WHERE username=%s", (u,))
    if cursor.fetchone():
        conn.close()
        return False
    cursor.execute("INSERT INTO user_profiles (username, pin, display_name, email) VALUES (%s,%s,%s,%s)", (u, p, d, e))
    conn.commit()
    conn.close()
    return True

def create_session(u):
    t = str(uuid.uuid4())
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO user_sessions (token, username) VALUES (%s,%s)", (t, u))
    conn.commit()
    conn.close()
    return t

def get_user_from_token(t):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT s.username, p.display_name, p.paper_balance FROM user_sessions s JOIN user_profiles p ON s.username=p.username WHERE s.token=%s", (t,))
    row = cursor.fetchone()
    conn.close()
    return row

# --- Data Functions ---
def calculate_risk(row):
    s = 50
    if row.get('trend_status') == 'DOWNTREND': s += 10
    else: s -= 10
    
    rsi = float(row.get('rsi') or 50)
    if rsi > 70: s += 10
    elif rsi < 30: s -= 10
    
    vol = float(row.get('volatility') or 0)
    if vol > 3.0: s += 10
    
    final = max(0, min(100, int(s)))
    color = "#4ade80" # Low (Green)
    if final > 65: color = "#ef4444" # High (Red)
    elif final > 35: color = "#fbbf24" # Med (Yellow)
    
    return final, color

def get_watchlist_candidates():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM stock_cache WHERE signal_tag IS NOT NULL ORDER BY ABS(day_change) DESC LIMIT 3")
    rows = cursor.fetchall()
    conn.close()
    # Filter out gold/silver
    return [r for r in rows if "GC" not in r['ticker'] and "SI" not in r['ticker']]

def get_portfolio_details(username, ptype):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM user_portfolio WHERE username=%s AND portfolio_type=%s", (username, ptype))
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_cached_data_map(tickers):
    if not tickers: return {}
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    # Safe formatting for IN clause
    format_strings = ','.join(['%s'] * len(tickers))
    cursor.execute(f"SELECT * FROM stock_cache WHERE ticker IN ({format_strings})", tuple(tickers))
    rows = cursor.fetchall()
    conn.close()
    return {row['ticker']: row for row in rows}

# --- UI Functions ---
def render_navbar(token, mode):
    mode_arg = "&mode=PAPER" if mode == "PAPER" else ""
    st.markdown(f"""
    <div class="nav-container">
        <a href="?token={token}&tab=home{mode_arg}" class="nav-link">🏠</a>
        <a href="?token={token}&tab=stocks{mode_arg}" class="nav-link">📂</a>
        <a href="?token={token}&tab=alerts{mode_arg}" class="nav-link">🔔</a>
        <a href="?token={token}&tab=settings{mode_arg}" class="nav-link">⚙️</a>
    </div>
    """, unsafe_allow_html=True)

def render_portfolio_row(row, data, token):
    risk, color = calculate_risk(data)
    price = float(data['current_price'])
    change = float(data['day_change'])
    change_color = "#4ade80" if change >= 0 else "#ef4444"
    arrow = "▲" if change >= 0 else "▼"
    
    shares = float(row['shares'])
    entry = float(row['entry_price'])
    
    # Logic to fix the "Raw HTML" issue: Apply color to the div, not a span
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

# =========================================================
# 3. MAIN EXECUTION
# =========================================================

# Initialize Database on Load
init_db()

# --- LOGIN FLOW ---
if "token" not in st.query_params:
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        if os.path.exists("logo.png"):
            st.image("logo.png", width=200)
        else:
            st.markdown("<h1 style='text-align:center; color:#4ade80;'>⚡ Penny Pulse</h1>", unsafe_allow_html=True)
            
    tab1, tab2 = st.tabs(["Login", "Register"])
    
    with tab1:
        with st.form("login_form"):
            u = st.text_input("Username")
            p = st.text_input("PIN", type="password")
            if st.form_submit_button("Login"):
                user = login_user(u, p)
                if user:
                    token = create_session(u)
                    st.query_params["token"] = token
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
    st.stop()

# --- MAIN APP FLOW ---
user = get_user_from_token(token)
if not user:
    st.error("Session Expired")
    st.stop()

# Mode Toggle
current_mode = st.query_params.get("mode", "REAL")
if current_mode not in ["REAL", "PAPER"]: current_mode = "REAL"

# Header
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

# Routing
tab = st.query_params.get("tab", "home")

if tab == "home":
    st.markdown("### Portfolio Overview")
    portfolio = get_portfolio_details(user['username'], current_mode)
    if not portfolio:
        st.info(f"Your {current_mode} portfolio is empty.")
    else:
        tickers = [r['ticker'] for r in portfolio]
        data_map = get_cached_data_map(tickers)
        for row in portfolio:
            if row['ticker'] in data_map:
                render_portfolio_row(row, data_map[row['ticker']], token)
            else:
                st.warning(f"Loading data for {row['ticker']}... Refresh if stuck.")
                
    st.markdown("### Watchlist Candidates")
    candidates = get_watchlist_candidates()
    cols = st.columns(3)
    for i, stock in enumerate(candidates):
        with cols[i % 3]:
            risk, color = calculate_risk(stock)
            st.markdown(f"""
                <div class="card" style="padding:10px; text-align:center;">
                    <div style="font-weight:bold; font-size:1.1rem;">{stock['ticker']}</div>
                    <div style="color:{color}; font-size:0.8rem;">{stock.get('signal_tag', 'Active')}</div>
                </div>
            """, unsafe_allow_html=True)

elif tab == "stocks":
    st.markdown("### All Stocks")
    # Add stock management logic here if needed

render_navbar(token, current_mode)
