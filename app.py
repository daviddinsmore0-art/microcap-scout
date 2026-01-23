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
        
        pre_post = ""
        try:
            rt = tk.fast_info.get('last_price', p_live)
            if rt and abs(rt - p_live) > 0.001:
                pp_pct = ((rt - p_live) / p_live) * 100
                now = datetime.now(timezone.utc) - timedelta(hours=5)
                lbl = "POST" if now.hour >= 16 else "PRE" if now.hour < 9 else "LIVE"
                col = "#4caf50" if pp_pct >= 0 else "#ff4b4b"
                pre_post = f"<span style='color:#ccc; margin:0 4px;'>|</span> <span style='font-size:11px; color:#888;'>{lbl}: <span style='color:{col};'>${rt:,.2f}</span></span>"
        except: pass

        sma20 = hist['Close'].tail(20).mean()
        return {
            "p": p_live, "d": d_pct, "name": tk.info.get('longName', s),
            "vol_pct": (hist['Volume'].iloc[-1] / hist['Volume'].mean()) * 100,
            "range_pos": ((p_live - hist['Low'].iloc[-1]) / (hist['High'].iloc[-1] - hist['Low'].iloc[-1])) * 100 if hist['High'].iloc[-1] != hist['Low'].iloc[-1] else 50,
            "h": hist['High'].iloc[-1], "l": hist['Low'].iloc[-1], 
            "ai": "BULLISH" if p_live > sma20 else "BEARISH", 
            "trend": "UPTREND" if p_live > sma20 else "DOWNTREND", "pp": pre_post,
            "chart": hist['Close'].tail(20).reset_index()
        }
    except: return None

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

# --- CSS ---
st.markdown("""
    <style>
        .block-container { padding-top: 10rem !important; }
        .header-container { position: fixed; top: 0; left: 0; width: 100%; z-index: 9999; box-shadow: 0 4px 15px rgba(0,0,0,0.3); }
        .header-top { background: linear-gradient(90deg, #1e1e1e 0%, #2b2d42 100%); padding: 15px 20px; padding-top: max(15px, env(safe-area-inset-top)); color: white; display: flex; justify-content: space-between; align-items: center; }
        div[data-testid="stVerticalBlock"] > div[style*="flex-direction: column;"] > div[data-testid="stVerticalBlock"] { background-color: #ffffff; border-radius: 12px; padding: 15px; box-shadow: 0 4px 10px rgba(0,0,0,0.05); border: 1px solid #f0f0f0; }
        .info-pill { font-size: 10px; color: #333; background: #f8f9fa; padding: 3px 8px; border-radius: 4px; font-weight: 600; margin-right: 6px; border: 1px solid #eee; }
        .bar-bg { background: #eee; height: 5px; border-radius: 3px; width: 100%; margin-top: 3px; overflow: hidden; }
        .bar-fill { height: 100%; border-radius: 3px; }
    </style>
""", unsafe_allow_html=True)

if not st.session_state['logged_in']:
    c1, c2, c3 = st.columns([1,2,1])
    with c2:
        st.markdown("<h1 style='text-align:center;'>⚡ Penny Pulse</h1>", unsafe_allow_html=True)
        user = st.text_input("Identity Access")
        if st.button("Authenticate", type="primary") and user:
            st.query_params["token"] = create_session(user.strip())
            st.session_state['username'] = user.strip()
            st.session_state['user_data'] = load_user(user.strip())
            st.session_state['logged_in'] = True
            st.rerun()
else:
    def push(): save_user(st.session_state['username'], st.session_state['user_data'])
    
    # --- HEADER ---
    t_str = (datetime.utcnow()-timedelta(hours=5)).strftime('%I:%M:%S %p')
    st.markdown(f"""<div class="header-container"><div class="header-top"><div style="font-size:22px; font-weight:900;">⚡ Penny Pulse</div><div style="font-family:monospace; font-size:14px; background:rgba(255,255,255,0.1); padding:4px 8px; border-radius:5px;">● {t_str} ET</div></div><div style="background:#111; color:white; padding:8px; overflow:hidden; white-space:nowrap; border-top:1px solid #333;"><marquee scrollamount="5">{st.session_state['user_data'].get('tape_input', '^DJI')}</marquee></div></div>""", unsafe_allow_html=True)

    with st.sidebar:
        st.subheader("Operator Control")
        new_w = st.text_area("Watchlist", value=st.session_state['user_data'].get('w_input', ""))
        if new_w != st.session_state['user_data']['w_input']:
            st.session_state['user_data']['w_input'] = new_w
            push()
            st.rerun()
        if st.button("Logout"):
            logout_session(st.query_params.get("token"))
            st.query_params.clear()
            st.session_state['logged_in'] = False
            st.rerun()

    def draw(t):
        d = get_pro_data(t)
        if not d: return
        f = get_fundamentals(t)
        b_col = "#4caf50" if d['d'] >= 0 else "#ff4b4b"
        
        with st.container():
            st.markdown(f"<div style='height:4px; width:100%; background-color:{b_col}; border-radius: 4px 4px 0 0;'></div>", unsafe_allow_html=True)
            # Unified Price Line
            st.markdown(f"""<div style="display:flex; justify-content:space-between; align-items:flex-start;"><div><div style="font-size:20px; font-weight:bold;">{t}</div><div style="font-size:11px; color:#888;">{d['name'][:25]}</div></div><div style="text-align:right;"><div style="font-size:20px; font-weight:bold;">${d['p']:,.2f}</div><div style="font-size:12px; font-weight:bold; color:{b_col};">{d['d']:+.2f}% {d['pp']}</div></div></div>""", unsafe_allow_html=True)
            
            # Intelligence Pills
            p_html = f'<span class="info-pill" style="border-left: 3px solid {b_col}">AI: {d["ai"]}</span>'
            p_html += f'<span class="info-pill" style="border-left: 3px solid {b_col}">TREND: {d["trend"]}</span>'
            if f['rating'] != "N/A": p_html += f'<span class="info-pill" style="border-left: 3px solid {b_col}">RAT: {f["rating"]}</span>'
            if f['earn'] != "N/A": p_html += f'<span class="info-pill" style="border-left: 3px solid #333">EARN: {f["earn"]}</span>'
            st.markdown(f'<div style="margin: 8px 0;">{p_html}</div>', unsafe_allow_html=True)

            # Sparkline
            chart = alt.Chart(d['chart']).mark_area(line={'color':b_col}, color=alt.Gradient(gradient='linear', stops=[alt.GradientStop(color=b_col, offset=0), alt.GradientStop(color='white', offset=1)], x1=1, x2=1, y1=1, y2=0)).encode(x=alt.X('Idx:Q', axis=None), y=alt.Y('Stock:Q', scale=alt.Scale(zero=False), axis=None), tooltip=[]).properties(height=40)
            st.altair_chart(chart, use_container_width=True)
            
            # Range Bar
            st.markdown(f'<div style="font-size:10px; color:#888; margin-top:5px;">DAY RANGE</div><div class="bar-bg"><div class="bar-fill" style="width:{d["range_pos"]}%; background:{b_col};"></div></div>', unsafe_allow_html=True)
            st.divider()

    # Dynamic Watchlist Loop (Restored)
    tickers = [x.strip().upper() for x in st.session_state['user_data'].get('w_input', "").split(",") if x.strip()]
    cols = st.columns(3)
    for i, t in enumerate(tickers):
        with cols[i%3]: draw(t)

    time.sleep(30)
    st.rerun()
