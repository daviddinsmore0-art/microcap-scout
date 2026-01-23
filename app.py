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

# --- AUTHENTICATION ---
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

# --- FUNDAMENTAL DATA (AGGRESSIVE RETRY) ---
@st.cache_data(ttl=600) 
def get_fundamentals(s):
    try:
        tk = yf.Ticker(s)
        inf = tk.info
        rating = inf.get('recommendationKey', 'N/A').replace('_', ' ').upper()
        if rating == "NONE": rating = "N/A"
        
        earn_str = "N/A"
        cal = tk.calendar
        if cal is not None:
            try:
                if hasattr(cal, 'iloc'): earn_str = cal.iloc[0][0].strftime('%b %d')
                elif isinstance(cal, dict): earn_str = cal.get('Earnings Date', [None])[0].strftime('%b %d')
            except: pass
        return {"rating": rating, "earn": earn_str}
    except: return {"rating": "N/A", "earn": "N/A"}

# --- LIVE DATA ENGINE ---
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
                now_et = datetime.now(timezone.utc) - timedelta(hours=5)
                lbl = "POST" if now_et.hour >= 16 else "PRE"
                col = "#4caf50" if pp_pct >= 0 else "#ff4b4b"
                pre_post_html = f"<span style='color:#ccc; margin:0 4px;'>|</span> <span style='font-size:11px; color:#888;'>{lbl}: <span style='color:{col};'>${rt_price:,.2f}</span></span>"
        except: pass

        sma20 = hist['Close'].tail(20).mean()
        rsi_val = 50 # Default
        try:
            delta = hist['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rsi_val = 100 - (100 / (1 + (gain/loss))).iloc[-1]
        except: pass

        return {
            "p": p_live, "d": d_pct, "name": tk.info.get('longName', s),
            "rsi": rsi_val, "vol_pct": (hist['Volume'].iloc[-1] / hist['Volume'].mean()) * 100,
            "range_pos": ((p_live - hist['Low'].iloc[-1]) / (hist['High'].iloc[-1] - hist['Low'].iloc[-1])) * 100 if hist['High'].iloc[-1] != hist['Low'].iloc[-1] else 50,
            "h": hist['High'].iloc[-1], "l": hist['Low'].iloc[-1], 
            "ai": "BULLISH" if p_live > sma20 else "BEARISH", 
            "trend": "UPTREND" if p_live > sma20 else "DOWNTREND", "pp": pre_post_html,
            "chart": hist['Close'].tail(20).reset_index()
        }
    except: return None

# --- UI STARTUP ---
init_db()
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
    url_token = st.query_params.get("token", None)
    if url_token:
        user = validate_session(url_token)
        if user:
            st.session_state['username'] = user
            st.session_state['logged_in'] = True

# --- CSS ---
st.markdown("""
    <style>
        .block-container { padding-top: 10rem !important; }
        .header-container {
            position: fixed; top: 0; left: 0; width: 100%; z-index: 9999;
            box-shadow: 0 4px 15px rgba(0,0,0,0.3);
        }
        .header-top {
            background: linear-gradient(90deg, #1e1e1e 0%, #2b2d42 100%);
            padding: 15px 20px; padding-top: max(15px, env(safe-area-inset-top));
            color: white; display: flex; justify-content: space-between; align-items: center;
        }
        .info-pill { font-size: 10px; color: #333; background: #f8f9fa; padding: 3px 8px; border-radius: 4px; font-weight: 600; margin-right: 6px; border: 1px solid #eee; }
        .bar-bg { background: #eee; height: 5px; border-radius: 3px; width: 100%; margin-top: 3px; overflow: hidden; }
        .bar-fill { height: 100%; border-radius: 3px; }
    </style>
""", unsafe_allow_html=True)

if not st.session_state['logged_in']:
    user = st.text_input("Username")
    if st.button("Authenticate") and user:
        st.query_params["token"] = create_session(user)
        st.session_state['logged_in'] = True
        st.rerun()
else:
    # --- HEADER ---
    t_str = (datetime.utcnow()-timedelta(hours=5)).strftime('%I:%M:%S %p')
    tape = "^DJI, ^IXIC, GC=F" # Static for demo
    st.markdown(f"""
        <div class="header-container">
            <div class="header-top">
                <div style="font-size:22px; font-weight:900;">⚡ Penny Pulse</div>
                <div style="font-family:monospace; font-size:14px; background:rgba(255,255,255,0.1); padding:4px 8px; border-radius:5px;">● {t_str} ET</div>
            </div>
            <div style="background:#111; color:white; padding:8px; overflow:hidden; white-space:nowrap; border-top:1px solid #333;">
                <marquee scrollamount="5">{tape}</marquee>
            </div>
        </div>
    """, unsafe_allow_html=True)

    def draw(t):
        d = get_pro_data(t)
        if not d: return
        f = get_fundamentals(t)
        b_col = "#4caf50" if d['d'] >= 0 else "#ff4b4b"
        
        with st.container():
            st.markdown(f"<div style='height:4px; width:100%; background-color:{b_col}; border-radius: 4px 4px 0 0;'></div>", unsafe_allow_html=True)
            st.markdown(f"""<div style="display:flex; justify-content:space-between; align-items:flex-start;"><div><div style="font-size:22px; font-weight:bold;">{t}</div><div style="font-size:12px; color:#888;">{d['name'][:25]}</div></div><div style="text-align:right;"><div style="font-size:22px; font-weight:bold;">${d['p']:,.2f}</div><div style="font-size:13px; font-weight:bold; color:{b_col};">{d['d']:+.2f}% {d['pp']}</div></div></div>""", unsafe_allow_html=True)
            
            p_html = f'<span class="info-pill" style="border-left: 3px solid {b_col}">AI: {d["ai"]}</span>'
            if f['rating'] != "N/A": p_html += f'<span class="info-pill" style="border-left: 3px solid {b_col}">RATING: {f["rating"]}</span>'
            if f['earn'] != "N/A": p_html += f'<span class="info-pill" style="border-left: 3px solid #333">EARN: {f["earn"]}</span>'
            st.markdown(f'<div style="margin: 10px 0;">{p_html}</div>', unsafe_allow_html=True)

            st.markdown(f'<div class="bar-bg"><div class="bar-fill" style="width:{d["range_pos"]}%; background:{b_col};"></div></div>', unsafe_allow_html=True)
            st.divider()

    tickers = ["TD.TO", "NKE", "SPY"]
    for t in tickers: draw(t)
    time.sleep(30)
    st.rerun()
