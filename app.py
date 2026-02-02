import streamlit as st
import mysql.connector
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
        
        .card { 
            background-color: #1a1f2b; border-radius: 16px; padding: 20px; 
            margin-bottom: 10px; border: 1px solid #2d3748; box-shadow: 0 4px 6px rgba(0,0,0,0.3); 
        }
        
        .metric-box {
            background-color: #1e293b; border: 1px solid #2d3748; border-radius: 12px;
            padding: 15px; text-align: center; margin-bottom: 10px;
        }
        .metric-label { font-size: 0.75rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 5px; }
        .metric-value { font-size: 1.5rem; font-weight: bold; color: white; margin-bottom: 2px; line-height: 1.1; }
        .metric-sub { font-size: 0.9rem; font-weight: bold; }
        
        div.stButton > button {
            background: linear-gradient(135deg, #4ade80, #16a34a) !important; 
            color: white !important; border: none; border-radius: 8px; 
            font-weight: bold; width: 100%; padding: 12px 20px;
        }
        
        button[kind="secondary"] {
            background: #334155 !important; border: 1px solid #ef4444 !important; color: #ef4444 !important;
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
            display: flex; flex-wrap: nowrap; overflow-x: auto; gap: 12px; padding-bottom: 10px; 
            -ms-overflow-style: none; scrollbar-width: none; 
        }
        .scrolling-wrapper::-webkit-scrollbar { display: none; }
        .scrolling-card { 
            flex: 0 0 auto; width: 130px; background-color: #1a1f2b; 
            border: 1px solid #2d3748; border-radius: 12px; padding: 15px; 
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
        
        # Ensure Briefing Table Exists (Prevents Crash)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_briefing (
                id INT PRIMARY KEY, 
                content TEXT, 
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
        """)
        
        # Ensure Stock Cache Exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stock_cache (
                ticker VARCHAR(20) PRIMARY KEY, 
                company_name VARCHAR(255), 
                current_price DECIMAL(20,4), 
                day_change DECIMAL(10,2), 
                rsi DECIMAL(10,2), 
                trend_status VARCHAR(20), 
                volatility DECIMAL(10,2), 
                next_earnings VARCHAR(50), 
                pre_post_price DECIMAL(20,4),
                rating VARCHAR(20),
                signal_tag VARCHAR(50), 
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"DB Init Error: {e}")

# --- FIX 2: ROBUST DATE PARSER ---
def parse_smart_date(date_str):
    """
    Parses 'Feb 12' or '2026-02-12'. Returns 999 if invalid.
    """
    if not date_str:
        return 999
    
    clean_str = str(date_str).strip() # Remove spaces!
    if clean_str.lower() in ['n/a', 'none', '', '999']:
        return 999
    
    try:
        now = datetime.now()
        # Try parsing "Feb 12" (Your DB format)
        try:
            target = datetime.strptime(f"{clean_str} {now.year}", "%b %d %Y")
            if target < now: 
                # If date passed this year, assume next year
                target = datetime.strptime(f"{clean_str} {now.year + 1}", "%b %d %Y")
        except ValueError:
            # Fallback to YYYY-MM-DD
            target = datetime.strptime(clean_str, "%Y-%m-%d")
            
        days = (target - now).days
        return days
    except:
        return 999

# --- FIX 3: GREETING LOGIC ---
def get_greeting(name):
    # Set to your time zone
    try:
        tz = pytz.timezone('America/Halifax')
        hour = datetime.now(tz).hour
    except:
        hour = datetime.now().hour # Fallback to server time
        
    if hour < 12: return f"Good Morning, {name}"
    elif 12 <= hour < 18: return f"Good Afternoon, {name}"
    else: return f"Good Evening, {name}"

# --- Auth Functions ---
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
    
    price = float(row.get('pre_post_price') or row.get('current_price') or 0)
    if price < 5: s += 5 
    
    final = max(0, min(100, int(s)))
    color = "#4ade80" 
    label = "LOW"
    if final > 65: color = "#ef4444"; label="HIGH"
    elif final > 35: color = "#fbbf24"; label="MEDIUM"
    return final, label, color

def get_watchlist_candidates():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM stock_cache ORDER BY ABS(day_change) DESC LIMIT 10")
    rows = cursor.fetchall()
    conn.close()
    return rows[:3]

def get_cached_data_map(tickers):
    if not tickers: return {}
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    format_strings = ','.join(['%s'] * len(tickers))
    cursor.execute(f"SELECT * FROM stock_cache WHERE ticker IN ({format_strings})", tuple(tickers))
    rows = cursor.fetchall()
    conn.close()
    return {row['ticker']: row for row in rows}

def get_portfolio_details(username, ptype):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM user_portfolio WHERE username=%s AND portfolio_type=%s AND is_active=TRUE", (username, ptype))
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_portfolio_summary(username, ptype):
    return 0.0, 0.0, 0.0, 0.0

def render_navbar(token):
    st.markdown(f"""
    <div class="nav-container">
        <a href="?token={token}&tab=home" class="nav-link">🏠</a>
        <a href="?token={token}&tab=portfolio" class="nav-link">📂</a>
        <a href="?token={token}&tab=alerts" class="nav-link">🔔</a>
    </div>
    """, unsafe_allow_html=True)

def create_gauge_html(score, label, color):
    rad = 80
    fill = (score / 100) * (3.14159 * rad)
    svg = f'<svg viewBox="0 0 200 120" style="width:100%;"><path d="M 20 100 A {rad} {rad} 0 0 1 {20+rad*2} 100" fill="none" stroke="#334155" stroke-width="15" stroke-linecap="round"/><path d="M 20 100 A {rad} {rad} 0 0 1 {20+rad*2} 100" fill="none" stroke="{color}" stroke-width="15" stroke-linecap="round" stroke-dasharray="{fill}, 1000"/><text x="{20+rad}" y="80" font-family="sans-serif" font-size="38" font-weight="bold" fill="white" text-anchor="middle">{score}</text><text x="{20+rad}" y="100" font-family="sans-serif" font-size="12" font-weight="bold" fill="{color}" text-anchor="middle" letter-spacing="2">{label}</text></svg>'
    return f'<div class="card" style="padding-bottom:0; margin-bottom:0;"><div style="text-align:center; color:#94a3b8; font-size:0.8rem; font-weight:bold; margin-bottom:5px;">PORTFOLIO RISK</div>{svg}</div>'

def render_compact_watchlist(rows_list, current_token):
    h = '<div class="scrolling-wrapper">'
    for row in rows_list:
        risk, _, color = calculate_risk(row)
        link = f"?token={current_token}&ticker={row['ticker']}"
        h += f"<a href='{link}' target='_self' style='text-decoration:none; color:inherit; flex: 0 0 auto;'><div class='scrolling-card'><div style='font-weight:bold; font-size:0.95rem; color:white; margin-bottom:4px;'>{row['ticker']}</div><div style='font-size:0.65rem; color:#facc15; font-weight:bold; margin-bottom:4px;'>{row.get('signal_tag', 'Active')}</div><div style='font-size:0.65rem; color:#94a3b8;'>Risk: <span style='color:{color}'>{risk}</span></div></div></a>"
    h += '</div>'
    st.markdown(h, unsafe_allow_html=True)

def render_horizontal_grid(rows_dict, current_token):
    h = '<div class="scrolling-wrapper">'
    for ticker, row in rows_dict.items():
        ch = float(row['day_change'] or 0); cc = "#4ade80" if ch>=0 else "#ef4444"; arr = "▲" if ch>=0 else "▼"
        link = f"?token={current_token}&ticker={ticker}"
        h += f'<a href="{link}" target="_self" style="text-decoration:none; color:inherit;"><div class="scrolling-card"><div style="font-weight:bold; font-size:1.1rem; color:white; margin-bottom:4px;">{ticker}</div><div style="font-size:0.85rem; color:{cc}; font-weight:bold; margin-bottom:8px;">{arr} {ch:.2f}%</div></div></a>'
    h += '</div>'; st.markdown(h, unsafe_allow_html=True)

# =========================================================
# 3. MAIN EXECUTION
# =========================================================

init_db()

# --- LOGIN ---
if "token" not in st.query_params:
    col1, col2, col3 = st.columns([1,2,1])
    with col2: st.markdown("<h1 style='text-align:center; color:#4ade80;'>⚡ Penny Pulse</h1>", unsafe_allow_html=True)
    with st.form("login_form"):
        u = st.text_input("Username")
        p = st.text_input("PIN", type="password")
        if st.form_submit_button("Login"):
            user_record = login_user(u, p)
            if user_record:
                st.query_params["token"] = create_session(u)
                st.rerun()
            else: st.error("Invalid Credentials")
    st.stop()

# --- APP LOGIC ---
user = get_user_from_token(token)
if not user: st.error("Session Expired"); st.stop()

tab = st.query_params.get("tab", "home")

if tab == "home":
    c1, c2 = st.columns([2, 1])
    with c1:
        # FIX 3: CALLING THE GREETING FUNCTION
        st.markdown(f"### {get_greeting(user['display_name'])}")
    
    # 1. SAFE BRIEFING FETCH
    try:
        conn = get_connection(); cursor = conn.cursor()
        cursor.execute("SELECT content FROM daily_briefing WHERE id=1")
        row = cursor.fetchone()
        conn.close()
        
        if row:
            st.markdown(f"""
                <div class="card" style="border-left: 4px solid #facc15; margin-bottom: 20px;">
                    <div style="color:#facc15; font-size:0.8rem; font-weight:bold; margin-bottom:5px;">AI MORNING BRIEFING</div>
                    <div style="font-size:0.95rem; line-height:1.5; color:#e0e6ed;">{row[0]}</div>
                </div>
            """, unsafe_allow_html=True)
    except Exception:
        pass
    
    portfolio = get_portfolio_details(user['username'], "REAL")
    if not portfolio:
        st.info("Portfolio is empty.")
    else:
        tickers = [r['ticker'] for r in portfolio]
        data_map = get_cached_data_map(tickers)
        valid_rows = [data_map[t] for t in tickers if t in data_map]
        
        if valid_rows:
            avg = sum([calculate_risk(x)[0] for x in valid_rows])/len(valid_rows)
            riskiest = max(valid_rows, key=lambda x: calculate_risk(x)[0])
            volatile = max(valid_rows, key=lambda x: abs(float(x['day_change'] or 0)))
            
            # 2. EARNINGS LOGIC
            earnings_candidates = []
            last_updated_time = None
            
            for r in valid_rows:
                # Capture freshness of data
                if r.get('last_updated'):
                    last_updated_time = r['last_updated']
                    
                # Parse date
                d_val = parse_smart_date(r.get('next_earnings'))
                # Only consider it if it's coming up within a year
                if d_val < 365: 
                    earnings_candidates.append((r['ticker'], d_val))
            
            if earnings_candidates:
                e_stock = min(earnings_candidates, key=lambda x: x[1])
                earnings_text = f"{e_stock[0]} ({e_stock[1]}d)"
            else:
                earnings_text = "N/A"
            
            st.markdown(create_gauge_html(int(avg), "MEDIUM" if avg<65 else "HIGH", "#fbbf24" if avg<65 else "#ef4444"), unsafe_allow_html=True)
            st.markdown(f"""<div style="display:flex; justify-content:space-between; background:#151922; padding:15px; border-radius:0 0 16px 16px; margin-top:-14px; margin-bottom:20px; border:1px solid #2d3748; border-top:none;"><div style="text-align:center; width:33%; border-right:1px solid #2d3748;"><div style="color:#94a3b8; font-size:0.6rem; text-transform:uppercase;">Highest Risk</div><div style="color:white; font-weight:bold; font-size:1rem;">{riskiest['ticker']}</div></div><div style="text-align:center; width:33%; border-right:1px solid #2d3748;"><div style="color:#94a3b8; font-size:0.6rem; text-transform:uppercase;">Most Volatile</div><div style="color:white; font-weight:bold; font-size:1rem;">{volatile['ticker']}</div></div><div style="text-align:center; width:33%;"><div style="color:#94a3b8; font-size:0.6rem; text-transform:uppercase;">Next Earnings</div><div style="color:white; font-weight:bold; font-size:1rem;">{earnings_text}</div></div></div>""", unsafe_allow_html=True)
            
            # --- FIX 4: SHOW DATA FRESHNESS ---
            if last_updated_time:
                st.caption(f"📉 Data last updated: {last_updated_time}")
            
            render_horizontal_grid(data_map, token)
            
    st.markdown("### Watchlist")
    candidates = get_watchlist_candidates()
    render_compact_watchlist(candidates, token)

elif tab == "portfolio":
    st.markdown("### My Stocks")
    port_rows = get_portfolio_details(user['username'], "REAL")
    if port_rows:
        for row in port_rows:
             st.markdown(f"<div class='card'>{row['ticker']} - {row['shares']} Shares</div>", unsafe_allow_html=True)

render_navbar(token)
