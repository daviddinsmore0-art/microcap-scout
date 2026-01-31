import streamlit as st
import pandas as pd
import mysql.connector
import yfinance as yf
import uuid
import time

# ---------------------------------------------------------
# 1. CONFIG & DATABASE
# ---------------------------------------------------------
st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="centered")

# *** DATABASE CREDENTIALS ***
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
# 2. AUTHENTICATION
# ---------------------------------------------------------
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

# ---------------------------------------------------------
# 3. DATA ENGINE
# ---------------------------------------------------------
def update_stock_data(tickers):
    if not tickers: return
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
            
            delta = df['Close'].diff()
            up, down = delta.clip(lower=0), -1 * delta.clip(upper=0)
            rs = up.ewm(com=13, adjust=False).mean() / down.ewm(com=13, adjust=False).mean()
            rsi = 100 - (100 / (1 + rs)).iloc[-1]
            
            ma50 = df['Close'].rolling(50).mean().iloc[-1]
            trend = "UPTREND" if price > ma50 else "DOWNTREND"
            
            sql = """INSERT INTO stock_cache (ticker, current_price, day_change, rsi, trend_status) 
                     VALUES (%s, %s, %s, %s, %s)
                     ON DUPLICATE KEY UPDATE current_price=%s, day_change=%s, rsi=%s, trend_status=%s"""
            cursor.execute(sql, (t, price, change, rsi, trend, price, change, rsi, trend))
        except: continue
    conn.commit()
    conn.close()

def get_cached_data(tickers):
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
    
    if trend == 'DOWNTREND': score += 20
    if trend == 'UPTREND': score -= 15
    if rsi > 70: score += 20
    if rsi < 30: score -= 10
    
    final = max(0, min(100, int(score)))
    if final > 60: return final, "HIGH", "#ef4444", "badge-high"
    if final > 40: return final, "MEDIUM", "#fbbf24", "badge-med"
    return final, "LOW", "#4ade80", "badge-low"

# ---------------------------------------------------------
# 4. UI & APP FLOW
# ---------------------------------------------------------
init_db()

# --- CSS INJECTION (Dark Mode) ---
st.markdown("""
<style>
    .stApp { background-color: #0f1219; color: #e0e6ed; }
    .card { background-color: #1a1f2b; border-radius: 12px; padding: 15px; margin-bottom: 10px; border: 1px solid #2d3748; }
    .big-score { font-size: 3.5rem; font-weight: 800; color: white; line-height: 1; }
    .badge { padding
