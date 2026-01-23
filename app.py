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
            "w_input": "TD.TO, CCO.TO, IVN.TO, BN.TO, HIVE, SPY, NKE",
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

# --- CUSTOM CSS ---
st.markdown("""
    <style>
        #MainMenu {visibility: visible;}
        footer {visibility: hidden;}
        
        /* 1. Reset padding to normal since we aren't using fixed positioning anymore */
        .block-container {
            padding-top: 3rem !important; 
            padding-bottom: 2rem;
        }
        
        /* Card Styling */
        div[data-testid="stVerticalBlock"] > div[style*="flex-direction: column;"] > div[data-testid="stVerticalBlock"] {
            background-color: #ffffff;
            border-radius: 10px;
            padding: 10px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        
        /* Metric Styling */
        [data-testid="stMetricValue"] {
            font-size: 1.8rem !important;
            font-weight: 700 !important;
        }
        
        /* 2. USE STICKY INSTEAD OF FIXED (Much Safer) */
        .main-header {
            position: sticky;  /* <--- This is the key change */
            top: 0;
            z-index: 999;
            background: linear-gradient(90deg, #1e1e1e 0%, #2b2d42 100%);
            padding: 10px 15px;
            border-radius: 0 0 15px 15px;
            color: white;
            margin-bottom: 20px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.2);
        }
        
        /* 3. Ensure Sidebar Icon is visible */
        [data-testid="stSidebarCollapsedControl"] {
            z-index: 1000 !important;
            color: white !important;
            background-color: rgba(0,0,0,0.2);
            border-radius: 5px;
        }
    </style>
""", unsafe_allow_html=True)

# --- APP LOGIC ---
if 'init' not in st.session_state:
    st.session_state['init'] = True
    st.session_state['logged_in'] = False
    st.session_state['username'] = ""
    st.session_state['user_data'] = {}
    st.session_state['keep_on'] = False
    init_db() 

# LOGIN SCREEN
if not st.session_state['logged_in']:
    c1, c2, c3 = st.columns([1,2,1])
    with c2:
        if os.path.exists(LOGO_PATH):
            lc1, lc2, lc3 = st.columns([1,2,1])
            with lc2:
                st.image(LOGO_PATH, use_container_width=True)
        else:
            st.markdown("<h1 style='text-align:center;'>⚡ Penny Pulse</h1>", unsafe_allow_html=True)
        
        st.markdown("<h3 style='text-align:center; color:#666; margin-top:-10px;'>Market Intelligence</h3>", unsafe_allow_html=True)
        
        with st.form("login"):
            user = st.text_input("Identity Access", placeholder="Enter Username")
            if st.form_submit_button("Authenticate", type="primary") and user:
                data = load_user(user.strip())
                if data:
                    st.session_state['username'] = user.strip()
                    st.session_state['user_data'] = data
                    st.session_state['logged_in'] = True
                    st.rerun()
                else:
                    st.error("Access Denied: Check Database Connection.")

# MAIN DASHBOARD
else:
    def push(): save_user(st.session_state['username'], st.session_state['user_data'])

    # -- SIDEBAR --
    with st.sidebar:
        if os.path.exists(LOGO_PATH):
            st.image(LOGO_PATH, width=150)
        else:
            st.title("⚡ Penny Pulse")

        st.markdown(f"**Operator:** {st.session_state['username']}")
        if st.button("Logout", type="secondary"):
            st.session_state['logged_in'] = False
            st.rerun()
        st.divider()
        
        st.subheader("Watchlist")
        curr_w = st.session_state['user_data'].get('w_input', "")
        new_w = st.text_area("Edit Tickers", value=curr_w, height=150)
        if new_w != curr_w:
            st.session_state['user_data']['w_input'] = new_w
            push()
            st.rerun()

        st.divider()
        with st.expander("💼 Portfolio Admin"):
            if st.text_input("Password", type="password") == ADMIN_PASSWORD:
                new_t = st.text_input("Ticker Symbol").upper()
                c1, c2 = st.columns(2)
                new_p = c1.number_input("Avg Price")
                new_q = c2.number_input("Quantity", step=1)
                
                if 'portfolio' not in st.session_state['user_data']: st.session_state['user_data']['portfolio'] = {}
                if st.button("Save Trade", type="primary") and new_t: 
                    st.session_state['user_data']['portfolio'][new_t] = {"e": new_p, "q": int(new_q)}
                    push()
                    st.rerun()
                
                rem = st.selectbox("Remove Asset", [""] + list(st.session_state['user_data']['portfolio'].keys()))
                if st.button("Delete") and rem: 
                    del st.session_state['user_data']['portfolio'][rem]
                    push()
                    st.rerun()
        
        st.checkbox("Always On Display", key="keep_on")
    
    inject_wake_lock(st.session_state['keep_on'])

    # -- TOP HEADER WITH LOGO --
    t_str = (datetime.utcnow()-timedelta(hours=5)+timedelta(minutes=1)).strftime('%I:%M %p')
    
    img_b64 = get_base64_image(LOGO_PATH)
    if img_b64:
        logo_html = f'<img src="data:image/png;base64,{img_b64}" style="height:40px; vertical-align:middle; margin-right:10px;">'
    else:
        logo_html = "⚡ "

    st.markdown(f"""
        <div class="main-header">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <div style="display:flex; align-items:center; font-size:24px; font-weight:900; letter-spacing:-1px;">
                    {logo_html} Penny Pulse
                </div>
                <div style="font-family:monospace; font-size:16px; background:rgba(255,255,255,0.1); padding:5px 10px; border-radius:5px;">● {t_str} ET</div>
            </div>
        </div>
    """, unsafe_allow_html=True)

    t1, t2 = st.tabs(["📊 Live Market", "🚀 Portfolio"])

    # -- DRAW FUNCTION --
    def draw(t, port=None):
        d = get_pro_data(t)
        if not d:
            st.warning(f"⚠️ {t}: Fetching...")
            return
        
        border_col = "#4caf50" if d['d'] >= 0 else "#ff4b4b"
        
        with st.container():
            st.markdown(f"<div style='height:4px; width:100%; background-color:{border_col}; border-radius: 4px 4px 0 0;'></div>", unsafe_allow_html=True)
            
            c1, c2 = st.columns([1.5, 1])
            with c1:
                st.markdown(f"<h3 style='margin:0; padding:0;'>{t}</h3>", unsafe_allow_html=True)
                st.caption(d['name'][:25] + "..." if len(d['name'])>25 else d['name'])
            with c2:
                arrow = "▲" if d['d'] >= 0 else "▼"
                st.markdown(f"<div style='text-align:right; font-size:22px; font-weight:bold;'>${d['p']:,.2f}</div>", unsafe_allow_html=True)
                st.markdown(f"<div style='text-align:right; color:{border_col}; font-weight:bold;'>{arrow} {d['d']:.2f}%</div>", unsafe_allow_html=True)
            
            chart = alt.Chart(d['chart']).mark_area(
                line={'color':border_col},
                color=alt.Gradient(
                    gradient='linear',
                    stops=[alt.GradientStop(color=border_col, offset=0),
                           alt.GradientStop(color='white', offset=1)],
                    x1=1, x2=1, y1=1, y2=0
                )
            ).encode(
                x=alt.X('Idx', axis=None), 
                y=alt.Y('Stock', scale=alt.Scale(domain=[d['chart']['Stock'].min(), d['chart']['Stock'].max()]), axis=None)
            ).configure_view(strokeWidth=0).properties(height=50)
            
            st.altair_chart(chart, use_container_width=True)
            
            if port:
                gain = (d['p'] - port['e']) * port['q']
                gain_col = "#4caf50" if gain >= 0 else "#ff4b4b"
                st.markdown(f"""
                <div style="background:#f9f9f9; padding:8px; border-radius:5px; display:flex; justify-content:space-between; font-size:13px;">
                    <span>Qty: <b>{port['q']}</b></span>
                    <span>Avg: <b>${port['e']}</b></span>
                    <span style="color:{gain_col}; font-weight:bold;">${gain:+,.0f}</span>
                </div>
                """, unsafe_allow_html=True)
            
            st.divider()

    # -- TAB 1: WATCHLIST --
    with t1:
        tickers = [x.strip().upper() for x in st.session_state['user_data'].get('w_input', "").split(",") if x.strip()]
        cols = st.columns(3) 
        for i, t in enumerate(tickers):
            with cols[i%3]: draw(t)

    # -- TAB 2: PORTFOLIO --
    with t2:
        port = st.session_state['user_data'].get('portfolio', {})
        if not port:
            st.info("Portfolio Empty. Use Sidebar to add assets.")
        else:
            tv = sum(get_pro_data(k)['p']*v['q'] for k,v in port.items() if get_pro_data(k))
            tc = sum(v['e']*v['q'] for v in port.values())
            diff = tv - tc
            diff_col = "#4caf50" if diff >= 0 else "#ff4b4b"
            
            st.markdown(f"""
                <div style="text-align:center; padding:20px; background:linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%); border-radius:10px; margin-bottom:20px; box-shadow:0 4px 6px rgba(0,0,0,0.1);">
                    <div style="color:#555; font-size:12px; text-transform:uppercase; letter-spacing:1px;">Net Liquidation Value</div>
                    <div style="font-size:42px; font-weight:900; color:#2c3e50;">${tv:,.2f}</div>
                    <div style="color:{diff_col}; font-size:18px; font-weight:bold; background:rgba(255,255,255,0.5); display:inline-block; padding:2px 10px; border-radius:10px;">
                        {'+' if diff>=0 else ''}${diff:,.2f} ({((tv-tc)/tc)*100:.2f}%)
                    </div>
                </div>
            """, unsafe_allow_html=True)

            cols = st.columns(3)
            for i, (k, v) in enumerate(port.items()):
                with cols[i%3]: draw(k, v)

    time.sleep(60)
    st.rerun()
