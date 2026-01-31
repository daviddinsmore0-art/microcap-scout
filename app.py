import streamlit as st
import pandas as pd
import mysql.connector
import yfinance as yf
import json
import uuid
import time
from datetime import datetime

# ---------------------------------------------------------
# 1. CONFIG & DATABASE
# ---------------------------------------------------------
st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="centered")

# *** YOUR DATABASE CREDENTIALS ***
DB_CONFIG = {
    "host": "atlanticcanadaschoice.com",
    "user": "atlantic",                 
    "password": "1q2w3e4R!!",   
    "database": "atlantic_pennypulse",    
    "connect_timeout": 30,
}

def get_connection():
    return mysql.connector.connect(**DB_CONFIG)

# Initialize DB tables if they don't exist
def init_db():
    try:
        conn = get_connection()
        cursor = conn.cursor()
        # User Tables
        cursor.execute("CREATE TABLE IF NOT EXISTS user_profiles (username VARCHAR(255) PRIMARY KEY, user_data TEXT, pin VARCHAR(50))")
        cursor.execute("CREATE TABLE IF NOT EXISTS user_sessions (token VARCHAR(255) PRIMARY KEY, username VARCHAR(255), created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
        
        # Data Cache (For Historical & Speed)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stock_cache (
                ticker VARCHAR(20) PRIMARY KEY,
                current_price DECIMAL(20, 4),
                day_change DECIMAL(10, 2),
                rsi DECIMAL(10, 2),
                trend_status VARCHAR(20),
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
        """)
        conn.close()
    except Exception as e:
        st.error(f"DB Init Error: {e}")

# ---------------------------------------------------------
# 2. AUTHENTICATION (Restored)
# ---------------------------------------------------------
def check_login(username, pin):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT pin FROM user_profiles WHERE username = %s", (username,))
        row = cursor.fetchone()
        conn.close()
        
        if row: return row[0] == pin # Check PIN
        return True # If user doesn't exist, allow (Auto-Signup)
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

# ---------------------------------------------------------
# 3. DATA ENGINE (MySQL + Yahoo Fallback)
# ---------------------------------------------------------
def update_stock_data(tickers):
    """
    Fetches fresh data from Yahoo and saves to MySQL 'stock_cache'.
    This ensures we have history without calling API every refresh.
    """
    if not tickers: return
    
    # Batch download
    data = yf.download(" ".join(tickers), period="3mo", group_by='ticker', threads=True, progress=False)
    
    conn = get_connection()
    cursor = conn.cursor()
    
    for t in tickers:
        try:
            df = data[t] if len(tickers) > 1 else data
            df = df.dropna()
            if df.empty: continue

            price = float(df['Close'].iloc[-1])
            prev = float(df['Close'].iloc[-2])
            change = ((price - prev) / prev) * 100
            
            # RSI Calc
            delta = df['Close'].diff()
            up, down = delta.clip(lower=0), -1 * delta.clip(upper=0)
            rs = up.ewm(com=13, adjust=False).mean() / down.ewm(com=13, adjust=False).mean()
            rsi = 100 - (100 / (1 + rs)).iloc[-1]
            
            # Trend Calc (Simple MA)
            ma50 = df['Close'].rolling(50).mean().iloc[-1]
            trend = "UPTREND" if price > ma50 else "DOWNTREND"
            
            # Save to MySQL
            sql = """INSERT INTO stock_cache (ticker, current_price, day_change, rsi, trend_status) 
                     VALUES (%s, %s, %s, %s, %s)
                     ON DUPLICATE KEY UPDATE current_price=%s, day_change=%s, rsi=%s, trend_status=%s"""
            cursor.execute(sql, (t, price, change, rsi, trend, price, change, rsi, trend))
            
        except: continue
    
    conn.commit()
    conn.close()

def get_cached_data(tickers):
    """ Reads data from MySQL so the UI loads instantly. """
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    format_strings = ','.join(['%s'] * len(tickers))
    cursor.execute(f"SELECT * FROM stock_cache WHERE ticker IN ({format_strings})", tuple(tickers))
    rows = cursor.fetchall()
    conn.close()
    return rows

# ---------------------------------------------------------
# 4. LOGIC ENGINE (Replaces AI)
# ---------------------------------------------------------
def calculate_risk(row):
    score = 50
    trend = row['trend_status']
    rsi = float(row['rsi'])
    
    if trend == 'DOWNTREND': score += 20
    if trend == 'UPTREND': score -= 15
    if rsi > 70: score += 20
    if rsi < 30: score -= 10
    
    final = max(0, min(100, int(score)))
    
    if final > 60: return final, "HIGH", "#ef4444", "badge-high"
    if final > 40: return final, "MEDIUM", "#fbbf24", "badge-med"
    return final, "LOW", "#4ade80", "badge-low"

# ---------------------------------------------------------
# 5. UI & APP FLOW
# ---------------------------------------------------------
init_db()

# CSS INJECTION (Dark Mode)
st.markdown("""
<style>
    .stApp { background-color: #0f1219; color: #e0e6ed; }
    .card { background-color: #1a1f2b; border-radius: 12px; padding: 15px; margin-bottom: 10px; border: 1px solid #2d3748; }
    .big-score { font-size: 3.5rem; font-weight: 800; color: white; line-height: 1; }
    .badge { padding: 4px 8px; border-radius: 6px; font-size: 0.75rem; font-weight: bold; }
    .badge-high { background: rgba(239, 68, 68, 0.2); color: #ef4444; }
    .badge-med { background: rgba(251, 191, 36, 0.2); color: #fbbf24; }
    .badge-low { background: rgba(74, 222, 128, 0.2); color: #4ade80; }
    .block-container { padding-top: 2rem; }
    input { color: black !important; } 
</style>
""", unsafe_allow_html=True)

# --- LOGIN SCREEN ---
if "token" not in st.query_params:
    st.markdown("<h1 style='text-align:center;'>⚡ Penny Pulse</h1>", unsafe_allow_html=True)
    with st.form("login"):
        user = st.text_input("Username")
        pin = st.text_input("PIN (Create one if new)", type="password")
        if st.form_submit_button("Login"):
            if check_login(user, pin):
                token = create_session(user)
                st.query_params["token"] = token
                st.rerun()
            else:
                st.error("Invalid PIN")
    st.stop()

# --- MAIN DASHBOARD ---
username = get_user_from_token(st.query_params["token"])
if not username:
    st.error("Session Expired"); st.stop()

# 1. Refresh Data
my_portfolio = ["TD.TO", "TSLA", "NVDA", "AAPL", "PLTR"] # Replace with DB fetch if needed
if st.button("🔄 Refresh Data"):
    with st.spinner("Updating Market Data..."):
        update_stock_data(my_portfolio)

# 2. Get Data from DB
data = get_cached_data(my_portfolio)

if not data:
    st.info("New account? Click Refresh to pull data.")
    st.stop()

# 3. Calculate Portfolio Risk
avg_risk = sum([calculate_risk(x)[0] for x in data]) / len(data)
r_score, r_label, r_color, _ = calculate_risk({'trend_status':'N', 'rsi':50}) # Dummy for styling
if avg_risk > 60: r_label, r_color = "HIGH", "#ef4444"
elif avg_risk > 40: r_label, r_color = "MEDIUM", "#fbbf24"
else: r_label, r_color = "LOW", "#4ade80"

# --- RENDER UI ---
st.title(f"Good Evening, {username}")

# Widget 1: Risk Gauge
st.markdown(f"""
<div class="card" style="text-align: center;">
    <div style="color: #94a3b8; font-size: 0.8rem; margin-bottom:10px;">PORTFOLIO RISK</div>
    <div class="big-score">{int(avg_risk)}</div>
    <div style="color: {r_color}; font-weight: bold; letter-spacing: 2px;">{r_label}</div>
    <div style="height: 8px; background: #334155; border-radius: 4px; margin-top: 10px; overflow:hidden;">
        <div style="width: {avg_risk}%; height:100%; background: linear-gradient(90deg, #4ade80, #fbbf24, #ef4444);"></div>
    </div>
</div>
""", unsafe_allow_html=True)

# Widget 2: Portfolio List
st.subheader("My Portfolio")
for row in data:
    score, label, color, css = calculate_risk(row)
    price = float(row['current_price'])
    change = float(row['day_change'])
    c_color = "#4ade80" if change >= 0 else "#ef4444"
    arrow = "▲" if change >= 0 else "▼"
    
    st.markdown(f"""
    <div class="card" style="display: flex; justify-content: space-between; align-items: center;">
        <div>
            <div style="font-weight:bold; font-size:1.1rem; color:white;">{row['ticker']}</div>
            <div style="font-size:0.8rem; color:#94a3b8;">Trend: {row['trend_status']}</div>
        </div>
        <div style="text-align:
