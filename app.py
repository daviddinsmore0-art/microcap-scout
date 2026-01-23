import streamlit as st
import yfinance as yf
import pandas as pd
import altair as alt
import time
import json
import mysql.connector
from mysql.connector import Error
from datetime import datetime, timedelta
import streamlit.components.v1 as components
import os
import base64

# --- SETUP ---
try: st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="wide")
except: pass 

# *** CONFIG ***
ADMIN_PASSWORD = "admin123"
LOGO_PATH = "logo.png"

# *** DATABASE CONFIG ***
DB_CONFIG = {
    "host": "72.55.168.16",    # Your Public IP
    "user": "penny_user",      # Your User
    "password": "123456",      # <--- We just set this in SQL!
    "database": "penny_pulse",
    "connect_timeout": 10
}

# --- DATABASE ENGINE ---
def get_connection():
    return mysql.connector.connect(**DB_CONFIG)

def init_db():
    """Checks connection on startup."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_profiles (
                username VARCHAR(255) PRIMARY KEY,
                user_data TEXT
            )
        """)
        conn.close()
        return True
    except Error as e:
        print(f"DB Error: {e}")
        return False

def load_user(username):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_data FROM user_profiles WHERE username = %s", (username,))
        res = cursor.fetchone()
        conn.close()
        if res: return json.loads(res[0])
        else: return {
            "w_input": "TD.TO, CCO.TO, IVN.TO, BN.TO, HIVE, SPY, NKE, VCIG, AIRE, IMNN, BAER, RERE",
            "portfolio": {},
            "settings": {"active": False}
        }
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

# --- DATA ENGINE ---
@st.cache_data(ttl=300)
def get_spy():
    try: return yf.Ticker("SPY").history(period="1d", interval="5m")['Close']
    except: return None 

def get_pro_data(s):
    try:
        tk = yf.Ticker(s)
        daily = tk.history(period="1d")
        if daily.empty: return None 
        
        p_live = daily['Close'].iloc[-1]
        p_open = daily['Open'].iloc[-1]
        
        try: intraday = tk.history(period="1d", interval="5m", prepost=False)
        except: intraday = pd.DataFrame()
            
        if not intraday.empty:
            chart_source = intraday
            p_live = intraday['Close'].iloc[-1]
            prev_close = intraday['Close'].iloc[0] 
        else:
            chart_source = daily
            prev_close = p_open

        d_pct = ((p_live - prev_close) / prev_close) * 100 if prev_close != 0 else 0
        try: name = tk.info.get('longName', s)
        except: name = s
        
        chart = chart_source['Close'].reset_index()
        chart.columns = ['T', 'Stock']
        chart['Idx'] = range(len(chart))
        chart['Stock'] = ((chart['Stock'] - chart['Stock'].iloc[0])/chart['Stock'].iloc[0])*100
        
        trend = "BULL" if d_pct >= 0 else "BEAR"
        return {"p": p_live, "d": d_pct, "tr": trend, "chart": chart, "name": name}
    except: return None

# --- APP LOGIC ---
if 'init' not in st.session_state:
    st.session_state['init'] = True
    st.session_state['logged_in'] = False
    st.session_state['username'] = ""
    st.session_state['user_data'] = {}
    st.session_state['keep_on'] = False
    init_db() 

# LOGIN
if not st.session_state['logged_in']:
    img = get_base64_image(LOGO_PATH)
    if img: st.markdown(f'<img src="data:image/png;base64,{img}" style="max-height:100px; display:block; margin:0 auto;">', unsafe_allow_html=True)
    else: st.markdown("<h1 style='text-align:center;'>⚡ Penny Pulse</h1>", unsafe_allow_html=True)
    
    st.info("🔒 Secure Enterprise Login")
    with st.form("login"):
        user = st.text_input("Username:")
        if st.form_submit_button("Login") and user:
            data = load_user(user.strip())
            if data:
                st.session_state['username'] = user.strip()
                st.session_state['user_data'] = data
                st.session_state['logged_in'] = True
                st.rerun()
            else:
                st.error("Connection Failed. 1. Check WHM Firewall (%) 2. Check Password.")

# DASHBOARD
else:
    def push(): save_user(st.session_state['username'], st.session_state['user_data'])

    with st.sidebar:
        st.header(f"👤 {st.session_state['username']}")
        if st.button("Logout"):
            st.session_state['logged_in'] = False
            st.rerun()
        st.divider()
        
        curr_w = st.session_state['user_data'].get('w_input', "")
        new_w = st.text_input("Tickers", value=curr_w)
        if new_w != curr_w:
            st.session_state['user_data']['w_input'] = new_w
            push()
            st.rerun()

        if st.text_input("Admin", type="password") == ADMIN_PASSWORD:
            with st.expander("💼 Portfolio", expanded=True):
                c1, c2, c3 = st.columns([2,2,2])
                new_t = c1.text_input("Sym").upper(); new_p = c2.number_input("Px"); new_q = c3.number_input("Qty", step=1)
                
                if 'portfolio' not in st.session_state['user_data']: st.session_state['user_data']['portfolio'] = {}
                if st.button("➕") and new_t: 
                    st.session_state['user_data']['portfolio'][new_t] = {"e": new_p, "q": int(new_q)}
                    push()
                    st.rerun()
                
                rem = st.selectbox("Del", [""] + list(st.session_state['user_data']['portfolio'].keys()))
                if st.button("🗑️") and rem: 
                    del st.session_state['user_data']['portfolio'][rem]
                    push()
                    st.rerun()
        
        st.divider()
        st.checkbox("Screen On", key="keep_on")
    
    inject_wake_lock(st.session_state['keep_on'])

    t_str = (datetime.utcnow()-timedelta(hours=5)+timedelta(minutes=1)).strftime('%H:%M:%S')
    st.markdown(f"""<div style="background:black;border:1px solid #333;border-radius:10px;padding:15px;text-align:center;margin-bottom:20px;"><h2 style='margin:0;color:white;'>⚡ Penny Pulse</h2><div style="color:#888;font-size:12px;">LIVE: <span style="color:#4caf50; font-weight:bold;">{t_str} ET</span></div></div>""", unsafe_allow_html=True)

    t1, t2 = st.tabs(["🏠 Dashboard", "🚀 My Picks"])

    def draw(t, port=None):
        d = get_pro_data(t)
        if not d:
            st.warning(f"⚠️ {t}: Data N/A")
            return
        
        c1, c2 = st.columns([2, 1])
        with c1:
            st.markdown(f"### {d['name']}")
            st.caption(t)
        with c2:
            st.metric("", f"${d['p']:,.2f}", f"{d['d']:.2f}%")
        
        if port: st.info(f"Qty: {port['q']} | Avg: ${port['e']} | Gain: ${(d['p'] - port['e']) * port['q']:,.2f}")
        
        col = "#4caf50" if d['d']>=0 else "#ff4b4b"
        chart = alt.Chart(d['chart']).mark_line(color=col).encode(x=alt.X('Idx', axis=None), y=alt.Y('Stock', axis=None)).properties(height=70)
        st.altair_chart(chart, use_container_width=True)
        st.divider()

    with t1:
        cols = st.columns(3)
        for i, t in enumerate([x.strip().upper() for x in st.session_state['user_data'].get('w_input', "").split(",") if x.strip()]):
            with cols[i%3]: draw(t)

    with t2:
        port = st.session_state['user_data'].get('portfolio', {})
        tv = sum(get_pro_data(k)['p']*v['q'] for k,v in port.items() if get_pro_data(k))
        tc = sum(v['e']*v['q'] for v in port.values())
        st.markdown(f"<h3 style='text-align:center'>Total Return: <span style='color:{'green' if tv>=tc else 'red'}'>${tv-tc:+,.2f}</span></h3>", unsafe_allow_html=True)
        cols = st.columns(3)
        for i, (k, v) in enumerate(port.items()):
            with cols[i%3]: draw(k, v)

    time.sleep(60)
    st.rerun()
