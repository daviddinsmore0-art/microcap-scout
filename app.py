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

# Custom CSS for "Dressing it up"
st.markdown("""
    <style>
        /* Only hide the footer, KEEP the header so mobile users can see the menu */
        #MainMenu {visibility: visible;}
        footer {visibility: hidden;}
        /* header {visibility: hidden;}  <-- I REMOVED THIS LINE SO YOU CAN SEE THE MENU */
        
        /* tighten up the top spacing */
        .block-container {padding-top: 1rem; padding-bottom: 1rem;}
        
        /* Make metrics stand out */
        [data-testid="stMetricValue"] {
            font-size: 1.5rem;
        }
    </style>
""", unsafe_allow_html=True)

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

# --- DATA ENGINE ---
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
        # Normalize chart to start at 0%
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

# LOGIN SCREEN
if not st.session_state['logged_in']:
    c1, c2, c3 = st.columns([1,2,1])
    with c2:
        img = get_base64_image(LOGO_PATH)
        if img: st.markdown(f'<img src="data:image/png;base64,{img}" style="max-height:120px; display:block; margin:0 auto;">', unsafe_allow_html=True)
        else: st.markdown("<h1 style='text-align:center;'>⚡ Penny Pulse</h1>", unsafe_allow_html=True)
        
        st.markdown("<br>", unsafe_allow_html=True)
        with st.form("login"):
            st.markdown("<h3 style='text-align:center;'>Secure Login</h3>", unsafe_allow_html=True)
            user = st.text_input("Username", placeholder="Enter your ID")
            if st.form_submit_button("Access Terminal", type="primary") and user:
                data = load_user(user.strip())
                if data:
                    st.session_state['username'] = user.strip()
                    st.session_state['user_data'] = data
                    st.session_state['logged_in'] = True
                    st.rerun()
                else:
                    st.error("Connection Failed. Check Database.")

# MAIN DASHBOARD
else:
    def push(): save_user(st.session_state['username'], st.session_state['user_data'])

    # -- SIDEBAR --
    with st.sidebar:
        st.header(f"👤 {st.session_state['username']}")
        if st.button("Logout"):
            st.session_state['logged_in'] = False
            st.rerun()
        st.divider()
        
        st.caption("WATCHLIST")
        curr_w = st.session_state['user_data'].get('w_input', "")
        new_w = st.text_area("Tickers (Comma separated)", value=curr_w, height=100)
        if new_w != curr_w:
            st.session_state['user_data']['w_input'] = new_w
            push()
            st.rerun()

        st.divider()
        if st.text_input("Admin", type="password") == ADMIN_PASSWORD:
            with st.expander("💼 Edit Portfolio", expanded=True):
                new_t = st.text_input("Sym").upper()
                c1, c2 = st.columns(2)
                new_p = c1.number_input("Px")
                new_q = c2.number_input("Qty", step=1)
                
                if 'portfolio' not in st.session_state['user_data']: st.session_state['user_data']['portfolio'] = {}
                if st.button("Add / Update") and new_t: 
                    st.session_state['user_data']['portfolio'][new_t] = {"e": new_p, "q": int(new_q)}
                    push()
                    st.rerun()
                
                rem = st.selectbox("Delete Asset", [""] + list(st.session_state['user_data']['portfolio'].keys()))
                if st.button("🗑️ Remove") and rem: 
                    del st.session_state['user_data']['portfolio'][rem]
                    push()
                    st.rerun()
        
        st.checkbox("Keep Screen On", key="keep_on")
    
    inject_wake_lock(st.session_state['keep_on'])

    # -- TOP HEADER --
    t_str = (datetime.utcnow()-timedelta(hours=5)+timedelta(minutes=1)).strftime('%I:%M %p')
    st.markdown(f"""
        <div style="display:flex; justify-content:space-between; align-items:center; background:#0e1117; padding:10px; border-bottom: 2px solid #262730; margin-bottom:20px;">
            <div style="font-size:24px; font-weight:bold;">⚡ Penny Pulse</div>
            <div style="color:#4caf50; font-family:monospace; font-size:18px;">● LIVE {t_str} ET</div>
        </div>
    """, unsafe_allow_html=True)

    t1, t2 = st.tabs(["📊 Market Dashboard", "🚀 My Portfolio"])

    # -- DRAW FUNCTION (The Visuals) --
    def draw(t, port=None):
        # Create a container with a border for the "Card" look
        with st.container(border=True):
            d = get_pro_data(t)
            if not d:
                st.warning(f"⚠️ {t}: Loading...")
                return
            
            # Header Row
            c1, c2 = st.columns([1.8, 1])
            with c1:
                st.markdown(f"**{t}**")
                st.caption(d['name'][:20] + "..." if len(d['name'])>20 else d['name'])
            with c2:
                # Color code the metric
                color = "green" if d['d'] >= 0 else "red"
                st.markdown(f"<div style='text-align:right; font-size:18px; font-weight:bold;'>${d['p']:,.2f}</div>", unsafe_allow_html=True)
                st.markdown(f"<div style='text-align:right; color:{color}; font-size:14px;'>{d['d']:+.2f}%</div>", unsafe_allow_html=True)
            
            # Portfolio Details (if any)
            if port: 
                gain = (d['p'] - port['e']) * port['q']
                gain_col = "green" if gain >= 0 else "red"
                st.markdown(f"""<div style="background:#262730; padding:5px; border-radius:5px; font-size:12px; margin-top:5px; text-align:center;">
                    {port['q']} @ ${port['e']} <span style="color:#888">|</span> <span style="color:{gain_col}"><b>${gain:+,.0f}</b></span>
                    </div>""", unsafe_allow_html=True)
            
            # The Chart
            col_chart = "#4caf50" if d['d']>=0 else "#ff4b4b"
            chart = alt.Chart(d['chart']).mark_line(
                color=col_chart, 
                strokeWidth=2
            ).encode(
                x=alt.X('Idx', axis=None), 
                y=alt.Y('Stock', axis=None)
            ).configure_view(strokeWidth=0).properties(height=60)
            
            st.altair_chart(chart, use_container_width=True)

    # -- TAB 1: WATCHLIST --
    with t1:
        tickers = [x.strip().upper() for x in st.session_state['user_data'].get('w_input', "").split(",") if x.strip()]
        
        # Responsive Grid (3 columns)
        cols = st.columns(3)
        for i, t in enumerate(tickers):
            with cols[i%3]: draw(t)

    # -- TAB 2: PORTFOLIO --
    with t2:
        port = st.session_state['user_data'].get('portfolio', {})
        if not port:
            st.info("Your portfolio is empty. Add stocks via the Sidebar (Admin Password required).")
        else:
            # Calculate Totals
            tv = sum(get_pro_data(k)['p']*v['q'] for k,v in port.items() if get_pro_data(k))
            tc = sum(v['e']*v['q'] for v in port.values())
            diff = tv - tc
            diff_col = "#4caf50" if diff >= 0 else "#ff4b4b"
            
            # Big Total Banner
            st.markdown(f"""
                <div style="text-align:center; padding:20px; background:#1e1e1e; border-radius:10px; margin-bottom:20px; border:1px solid #333;">
                    <div style="color:#888; font-size:14px;">TOTAL PORTFOLIO VALUE</div>
                    <div style="font-size:36px; font-weight:bold;">${tv:,.2f}</div>
                    <div style="color:{diff_col}; font-size:18px; font-weight:bold;">{'+' if diff>=0 else ''}${diff:,.2f} ({((tv-tc)/tc)*100:.2f}%)</div>
                </div>
            """, unsafe_allow_html=True)

            # Portfolio Grid
            cols = st.columns(3)
            for i, (k, v) in enumerate(port.items()):
                with cols[i%3]: draw(k, v)

    # Auto Refresh
    time.sleep(60)
    st.rerun()
