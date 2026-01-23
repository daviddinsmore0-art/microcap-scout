import streamlit as st
import yfinance as yf
import pandas as pd
import altair as alt
import time
import json
import mysql.connector
from mysql.connector import Error
from datetime import datetime, timedelta, timezone
import streamlit.components.v1 as components
import os
import base64
import uuid

# --- SETUP & STYLING ---
try: st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="wide")
except: pass 

# *** CONFIG ***
ADMIN_PASSWORD = "admin123"
LOGO_PATH = "logo.png"

# *** DATABASE CONFIG ***
DB_CONFIG = {
    "host": "72.55.168.16",
    "user": "penny_user",
    "password": "123456",
    "database": "penny_pulse",
    "connect_timeout": 10
}

# --- DATABASE ENGINE ---
def get_connection():
    return mysql.connector.connect(**DB_CONFIG)

def init_db():
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS user_profiles (username VARCHAR(255) PRIMARY KEY, user_data TEXT)")
        cursor.execute("CREATE TABLE IF NOT EXISTS user_sessions (token VARCHAR(255) PRIMARY KEY, username VARCHAR(255), created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
        conn.close()
        return True
    except Error: return False

def create_session(username):
    token = str(uuid.uuid4())
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM user_sessions WHERE username = %s", (username,))
        cursor.execute("INSERT INTO user_sessions (token, username) VALUES (%s, %s)", (token, username))
        conn.commit()
        conn.close()
        return token
    except: return None

def validate_session(token):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT username FROM user_sessions WHERE token = %s", (token,))
        res = cursor.fetchone()
        conn.close()
        return res[0] if res else None
    except: return None

def logout_session(token):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM user_sessions WHERE token = %s", (token,))
        conn.commit()
        conn.close()
    except: pass

def load_user(username):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_data FROM user_profiles WHERE username = %s", (username,))
        res = cursor.fetchone()
        conn.close()
        if res: return json.loads(res[0])
        else: return {"w_input": "TD.TO, NKE, SPY", "tape_input": "^DJI, ^IXIC, GC=F", "portfolio": {}}
    except: return None

def save_user(username, data):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        j_str = json.dumps(data)
        sql = "INSERT INTO user_profiles (username, user_data) VALUES (%s, %s) ON DUPLICATE KEY UPDATE user_data = %s"
        cursor.execute(sql, (username, j_str, j_str))
        conn.commit()
        conn.close()
    except: pass

# --- HELPERS ---
def get_base64_image(path):
    if os.path.exists(path):
        with open(path, "rb") as f: return base64.b64encode(f.read()).decode()
    return None

def inject_wake_lock(enable):
    if enable: components.html("""<script>navigator.wakeLock.request('screen').catch(console.log);</script>""", height=0) 

def calculate_rsi(data, window=14):
    delta = data.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

# --- DATA ENGINE ---
@st.cache_data(ttl=600) 
def get_fundamentals(s):
    try:
        tk = yf.Ticker(s)
        inf = tk.info
        rating = inf.get('recommendationKey', 'N/A').replace('_', ' ').upper()
        if rating == "NONE": rating = "N/A"
        
        earn_str = "N/A"
        try:
            cal = tk.calendar
            if hasattr(cal, 'iloc') and not cal.empty: earn_str = cal.iloc[0][0].strftime('%b %d')
            elif isinstance(cal, dict): earn_str = cal.get('Earnings Date', [None])[0].strftime('%b %d')
        except: pass
        return {"rating": rating, "earn": earn_str}
    except: return {"rating": "N/A", "earn": "N/A"}

def get_pro_data(s):
    try:
        tk = yf.Ticker(s)
        hist = tk.history(period="1mo", interval="1d")
        if hist.empty: return None 
        
        p_live = hist['Close'].iloc[-1]
        prev_close = hist['Close'].iloc[-2] if len(hist) > 1 else p_live
        d_pct = ((p_live - prev_close) / prev_close) * 100

        pre_post_html = ""
        try:
            rt_price = tk.fast_info.get('last_price', p_live)
            if rt_price and abs(rt_price - p_live) > 0.001:
                pp_pct = ((rt_price - p_live) / p_live) * 100
                now = datetime.now(timezone.utc) - timedelta(hours=5)
                lbl = "POST" if now.hour >= 16 else "PRE" if now.hour < 9 else "LIVE"
                col = "#4caf50" if pp_pct >= 0 else "#ff4b4b"
                pct_fmt = f"{pp_pct:+.2f}%"
                pre_post_html = f"<span style='color:#ccc; margin:0 4px;'>|</span> <span style='font-size:11px; color:#888;'>{lbl}: <span style='color:{col};'>${rt_price:,.2f} ({pct_fmt})</span></span>"
        except: pass

        sma20 = hist['Close'].tail(20).mean()
        rsi_val = 50 
        try:
            rsi_series = calculate_rsi(hist['Close'])
            if not rsi_series.empty: rsi_val = rsi_series.iloc[-1]
        except: pass

        return {
            "p": p_live, "d": d_pct, "name": tk.info.get('longName', s),
            "rsi": rsi_val,
            "vol_pct": (hist['Volume'].iloc[-1] / hist['Volume'].mean()) * 100,
            "range_pos": ((p_live - hist['Low'].iloc[-1]) / (hist['High'].iloc[-1] - hist['Low'].iloc[-1])) * 100 if hist['High'].iloc[-1] != hist['Low'].iloc[-1] else 50,
            "h": hist['High'].iloc[-1], "l": hist['Low'].iloc[-1], 
            "ai": "BULLISH" if p_live > sma20 else "BEARISH", 
            "trend": "UPTREND" if p_live > sma20 else "DOWNTREND", "pp": pre_post_html,
            "chart": hist['Close'].tail(20).reset_index()
        }
    except: return None

@st.cache_data(ttl=300)
def get_tape_data(symbol_string):
    items = []
    symbols = [x.strip() for x in symbol_string.split(",") if x.strip()]
    for s in symbols:
        try:
            tk = yf.Ticker(s)
            hist = tk.history(period="1d")
            if not hist.empty:
                px = hist['Close'].iloc[-1]
                op = hist['Open'].iloc[-1]
                chg = ((px - op)/op)*100
                short_name = s.replace("^DJI", "DOW").replace("^IXIC", "NASDAQ").replace("^GSPC", "S&P500").replace("GC=F", "GOLD").replace("SI=F", "SILVER").replace("BTC-USD", "BTC")
                color = "#4caf50" if chg >= 0 else "#ff4b4b"
                arrow = "▲" if chg >= 0 else "▼"
                items.append(f"<span style='color:#ccc; font-weight:bold; margin-left:20px;'>{short_name}</span> <span style='color:{color}'>{arrow} {px:,.0f} ({chg:+.1f}%)</span>")
        except: pass
    return "   ".join(items)

# --- UI LOGIC ---
init_db()
if 'init' not in st.session_state:
    st.session_state['init'] = True
    st.session_state['logged_in'] = False
    url_token = st.query_params.get("token", None)
    if url_token:
        user = validate_session(url_token)
        if user:
            st.session_state['username'] = user
            st.session_state['user_data'] = load_user(user)
            st.session_state['logged_in'] = True

# --- CUSTOM CSS (THE FIX FOR THE CARDS) ---
st.markdown("""
    <style>
        #MainMenu {visibility: visible;}
        footer {visibility: hidden;}
        .block-container { padding-top: 9rem !important; padding-bottom: 2rem; }
        
        /* THIS RESTORES THE WHITE CARD STYLE */
        div[data-testid="stVerticalBlock"] > div[style*="flex-direction: column;"] > div[data-testid="stVerticalBlock"] {
            background-color: #ffffff;
            border-radius: 12px;
            padding: 15px;
            box-shadow: 0 4px 10px rgba(0,0,0,0.05);
            border: 1px solid #f0f0f0;
        }

        /* HEADER */
        .header-container { position: fixed; top: 0; left: 0; width: 100%; z-index: 99999; box-shadow: 0 4px 15px rgba(0,0,0,0.3); }
        .header-top { background: linear-gradient(90deg, #1e1e1e 0%, #2b2d42 100%); padding: 15px 20px; padding-top: max(15px, env(safe-area-inset-top)); color: white; display: flex; justify-content: space-between; align-items: center; }
        .ticker-wrap { width: 100%; overflow: hidden; background-color: #111; border-top: 1px solid #333; white-space: nowrap; padding: 8px 0; color: white; font-size: 14px; }
        .ticker { display: inline-block; animation: ticker 30s linear infinite; }
        @keyframes ticker { 0% { transform: translate3d(0, 0, 0); } 100% { transform: translate3d(-100%, 0, 0); } }

        /* ELEMENTS */
        .info-pill { font-size: 10px; color: #333; background: #f8f9fa; padding: 3px 8px; border-radius: 4px; font-weight: 600; margin-right: 6px; border: 1px solid #eee; }
        .bar-bg { background: #eee; height: 5px; border-radius: 3px; width: 100%; margin-top: 3px; overflow: hidden; }
        .bar-fill { height: 100%; border-radius: 3px; }
        .metric-label { font-size: 10px; color: #888; font-weight: 600; display: flex; justify-content: space-between; margin-top: 8px; text-transform: uppercase; }
        .tag { font-size: 9px; padding: 1px 5px; border-radius: 3px; font-weight: bold; color: white; }
    </style>
""", unsafe_allow_html=True)

if not st.session_state['logged_in']:
    c1, c2, c3 = st.columns(
