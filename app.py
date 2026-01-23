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

# --- 1. SETUP ---
try: st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="wide")
except: pass 

# *** CONFIG ***
ADMIN_PASSWORD = "admin123"
LOGO_PATH = "logo.png"

# *** DATABASE CONFIG (EDIT THIS) ***
# If hosting on Streamlit Cloud, 'host' must be your server's PUBLIC IP.
# If running locally on the same machine as MySQL, 'localhost' is fine.
DB_CONFIG = {
    "host": "localhost",       # CHANGE THIS if not running locally
    "user": "root",            # Your MySQL Username
    "password": "",            # Your MySQL Password
    "database": "penny_pulse"
}

# --- 2. DATABASE ENGINE ---
def get_connection():
    """Connects to the MySQL server."""
    return mysql.connector.connect(**DB_CONFIG)

def load_user_profile(username):
    """Fetches user data. If new, returns defaults."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_data FROM user_profiles WHERE username = %s", (username,))
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return json.loads(result[0])
        else:
            # New User Defaults
            return {
                "w_input": "TD.TO, CCO.TO, IVN.TO, BN.TO, HIVE, SPY, NKE, VCIG, AIRE, IMNN, BAER, RERE",
                "portfolio": {},
                "settings": {"active": False}
            }
    except Error as e:
        st.error(f"❌ Database Error: {e}")
        return None

def save_user_profile(username, data):
    """Saves current state to MySQL."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        json_str = json.dumps(data)
        # Upsert Logic (Insert, or Update if exists)
        sql = """
            INSERT INTO user_profiles (username, user_data) 
            VALUES (%s, %s) 
            ON DUPLICATE KEY UPDATE user_data = %s
        """
        cursor.execute(sql, (username, json_str, json_str))
        conn.commit()
        conn.close()
    except Error as e:
        st.error(f"❌ Save Failed: {e}")

# --- 3. HELPERS ---
def get_base64_image(image_path):
    if os.path.exists(image_path):
        with open(image_path, "rb") as img_file: return base64.b64encode(img_file.read()).decode()
    return None

def inject_wake_lock(enable):
    if enable: components.html("""<script>navigator.wakeLock.request('screen').catch(console.log);</script>""", height=0) 

# --- 4. DATA ENGINE (Heavy Lifter) ---
@st.cache_data(ttl=300)
def get_spy_data():
    try: return yf.Ticker("SPY").history(period="1d", interval="5m")['Close']
    except: return None 

def get_pro_data(s):
    try:
        tk = yf.Ticker(s)
        
        # 1. Price First (Guaranteed)
        daily = tk.history(period="1d")
        if daily.empty: return None 
        
        p_live = daily['Close'].iloc[-1]
        p_open = daily['Open'].iloc[-1]
        
        # 2. Chart Second (Best Effort)
        try: intraday = tk.history(period="1d", interval="5m", prepost=False)
        except: intraday = pd.DataFrame()
            
        if not intraday.empty:
            chart_source = intraday
            p_live = intraday['Close'].iloc[-1]
            prev_close = intraday['Close'].iloc[0] 
        else:
            chart_source = daily
            prev_close = p_open

        d_val = p_live - prev_close
        d_pct = (d_val / prev_close) * 100 if prev_close != 0 else 0
        
        try: name = tk.info.get('longName', s)
        except: name = s
        
        chart = chart_source['Close'].reset_index()
        chart.columns = ['T', 'Stock']
        chart['Idx'] = range(len(chart))
        chart['Stock'] = ((chart['Stock'] - chart['Stock'].iloc[0])/chart['Stock'].iloc[0])*100
        
        trend = "BULL" if d_pct >= 0 else "BEAR"
        
        return {
            "p": p_live, "d": d_pct, "tr": trend, "chart": chart, "name": name,
            "ai": f"{'🟢' if trend=='BULL' else '🔴'} {trend} BIAS"
        }
    except: return None

# --- 5. APP LOGIC ---

# Initialize Session State
if 'init' not in st.session_state:
    st.session_state['init'] = True
    st.session_state['logged_in'] = False
    st.session_state['username'] = ""
    st.session_state['user_data'] = {}
    st.session_state['keep_on'] = False

# >>> LOGIN SCREEN <<<
if not st.session_state['logged_in']:
    
    # Logo
    img_code = get_base64_image(LOGO_PATH)
    if img_code:
        img_html = f'<img src="data:image/png;base64,{img_code}" style="max-height:120px; display:block; margin:0 auto;">'
    else:
        img_html = "<h1 style='text-align:center;'>⚡ Penny Pulse</h1>"
    st.markdown(f"{img_html}", unsafe_allow_html=True)
    
    st.markdown("<h3 style='text-align:center;'>Professional Market Intelligence</h3>", unsafe_allow_html=True)
    st.info("🔒 Secure Login: Connects to Enterprise Database")

    with st.form("login_form"):
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            user_input = st.text_input("Enter Full Name / ID:")
            submitted = st.form_submit_button("Access Terminal", use_container_width=True)
            
            if submitted and user_input:
                clean_user = user_input.strip()
                with st.spinner("Authenticating..."):
                    data = load_user_profile(clean_user)
                    if data:
                        st.session_state['username'] = clean_user
                        st.session_state['user_data'] = data
                        st.session_state['logged_in'] = True
                        st.rerun()

# >>> MAIN DASHBOARD <<<
else:
    # Save Trigger
    def push_update():
        save_user_profile(st.session_state['username'], st.session_state['user_data'])

    # Sidebar
    with st.sidebar:
        st.header(f"👤 {st.session_state['username']}")
        if st.button("Logout"):
            st.session_state['logged_in'] = False
            st.rerun()
        st.divider()
        
        # Watchlist
        curr_w = st.session_state['user_data'].get('w_input', "")
        new_w = st.text_input("Tickers", value=curr_w)
        if new_w != curr_w:
            st.session_state['user_data']['w_input'] = new_w
            push_update()
            st.rerun()

        # Admin
        if st.text_input("Admin Key", type="password") == ADMIN_PASSWORD:
            with st.expander("💼 Portfolio Admin", expanded=True):
                c1, c2, c3 = st.columns([2,2,2])
                new_t = c1.text_input("Sym").upper(); new_p = c2.number_input("Px", 0.0); new_q = c3.number_input("Qty", 0)
                
                # Ensure portfolio exists
                if 'portfolio' not in st.session_state['user_data']:
                    st.session_state['user_data']['portfolio'] = {}

                if st.button("➕ Add") and new_t: 
                    st.session_state['user_data']['portfolio'][new_t] = {"e": new_p, "q": int(new_q)}
                    push_update()
                    st.rerun()
                    
                rem_t = st.selectbox("Remove", [""] + list(st.session_state['user_data']['portfolio'].keys()))
                if st.button("🗑️ Del") and rem_t: 
                    del st.session_state['user_data']['portfolio'][rem_t]
                    push_update()
                    st.rerun()
        
        st.divider()
        st.checkbox("Keep Screen On", key="keep_on")

    inject_wake_lock(st.session_state['keep_on'])

    # Header
    t_str = (datetime.utcnow()-timedelta(hours=5)+timedelta(minutes=1)).strftime('%H:%M:%S')
    st.markdown(f"""<div style="background:black;border:1px solid #333;border-radius:10px;padding:15px;text-align:center;margin-bottom:20px;"><h2 style='margin:0;color:white;'>⚡ Penny Pulse</h2><div style="color:#888;font-size:12px;">LIVE FEED: <span style="color:#4caf50; font-weight:bold;">{t_str} ET</span></div></div>""", unsafe_allow_html=True)

    t1, t2 = st.tabs(["🏠 Dashboard", "🚀 My Picks"])

    def draw_card(t, port=None):
        d = get_pro_data(t)
        if not d:
            st.warning(f"⚠️ {t}: Data N/A")
            return

        col_hex = "#4caf50" if d['d']>=0 else "#ff4b4b"
        col_str = "green" if d['d']>=0 else "red"
        
        c_head, c_price = st.columns([2, 1])
        with c_head:
            st.markdown(f"### {d['name']}")
            st.caption(f"{t}")
        with c_price:
            st.metric(label="", value=f"${d['p']:,.2f}", delta=f"{d['d']:.2f}%")

        if port:
            gain = (d['p'] - port['e']) * port['q']
            st.info(f"Qty: {port['q']} | Avg: ${port['e']} | Gain: ${gain:,.2f}")

        st.markdown(f"**TREND:** :{col_str}[**{d['tr']}**]", unsafe_allow_html=True)
        
        chart = alt.Chart(d['chart']).mark_line(color=col_hex).encode(x=alt.X('Idx', axis=None), y=alt.Y('Stock', axis=None)).properties(height=70)
        st.altair_chart(chart, use_container_width=True)
        st.divider()

    with t1:
        cols = st.columns(3)
        raw_w = st.session_state['user_data'].get('w_input', "")
        W = [x.strip().upper() for x in raw_w.split(",") if x.strip()]
        for i, t in enumerate(W):
            with cols[i%3]: draw_card(t)

    with t2:
        PORT = st.session_state['user_data'].get('portfolio', {})
        tv = sum(get_pro_data(tk)['p']*inf['q'] for tk, inf in PORT.items() if get_pro_data(tk))
        tc = sum(inf['e']*inf['q'] for inf in PORT.values())
        profit = tv - tc
        st.markdown(f"""<h2 style='text-align:center; color:{'#4caf50' if profit>=0 else '#ff4b4b'}'>TOTAL RETURN: ${profit:+,.2f}</h2>""", unsafe_allow_html=True)
        
        cols = st.columns(3)
        for i, (t, inf) in enumerate(PORT.items()):
            with cols[i%3]: draw_card(t, inf)

    time.sleep(60)
    st.rerun()
