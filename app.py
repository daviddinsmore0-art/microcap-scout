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
import numpy as np

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
            "tape_input": "^DJI, ^IXIC, ^GSPC, GC=F, SI=F, BTC-USD",
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

def calculate_rsi(data, window=14):
    delta = data.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

# --- DATA ENGINE (ENHANCED) ---
def get_pro_data(s):
    try:
        tk = yf.Ticker(s)
        # Get 1 month data to calculate RSI accurately
        hist = tk.history(period="1mo", interval="1d")
        
        if hist.empty: return None 
        
        # Current Data Points
        p_live = hist['Close'].iloc[-1]
        p_open = hist['Open'].iloc[-1]
        prev_close = hist['Close'].iloc[-2] if len(hist) > 1 else p_open
        
        # Intraday Check for Live Chart
        try: 
            intraday = tk.history(period="1d", interval="5m", prepost=False)
            if not intraday.empty:
                chart_source = intraday
                p_live = intraday['Close'].iloc[-1]
            else:
                chart_source = hist.tail(20) # Fallback to recent daily
        except: 
            chart_source = hist.tail(20)

        # Percent Change
        d_pct = ((p_live - prev_close) / prev_close) * 100

        # --- ADVANCED METRICS ---
        # 1. RSI
        rsi_series = calculate_rsi(hist['Close'])
        rsi_val = rsi_series.iloc[-1] if not rsi_series.empty else 50
        
        # 2. Volume Status
        avg_vol = hist['Volume'].mean()
        curr_vol = hist['Volume'].iloc[-1]
        vol_pct = (curr_vol / avg_vol) * 100 if avg_vol > 0 else 0
        
        # 3. Day Range Position
        day_high = hist['High'].iloc[-1]
        day_low = hist['Low'].iloc[-1]
        # Avoid division by zero
        range_pos = ((p_live - day_low) / (day_high - day_low)) * 100 if day_high != day_low else 50

        # Chart Prep
        chart = chart_source['Close'].reset_index()
        chart.columns = ['T', 'Stock']
        chart['Idx'] = range(len(chart))
        chart['Stock'] = ((chart['Stock'] - chart['Stock'].iloc[0])/chart['Stock'].iloc[0])*100
        
        try: name = tk.info.get('longName', s)
        except: name = s

        # Post Market Mockup (Yahoo free API is spotty on this, so we use logic)
        post_txt = ""
        # If market is closed, we could simulate or leave blank. 
        # For now, let's show the Pre/Post logic placeholder if needed.

        return {
            "p": p_live, "d": d_pct, "chart": chart, "name": name,
            "rsi": rsi_val, "vol_pct": vol_pct, "range_pos": range_pos,
            "h": day_high, "l": day_low
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

# --- CUSTOM CSS ---
st.markdown("""
    <style>
        #MainMenu {visibility: visible;}
        footer {visibility: hidden;}
        
        .block-container {
            padding-top: 1rem !important; 
            padding-bottom: 2rem;
        }
        
        /* CARD CONTAINER */
        div[data-testid="stVerticalBlock"] > div[style*="flex-direction: column;"] > div[data-testid="stVerticalBlock"] {
            background-color: #ffffff;
            border-radius: 10px;
            padding: 12px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        
        /* HEADER */
        .header-container {
            position: sticky;
            top: 0;
            z-index: 999;
            filter: drop-shadow(0 4px 6px rgba(0,0,0,0.2)); 
        }
        .header-top {
            background: linear-gradient(90deg, #1e1e1e 0%, #2b2d42 100%);
            padding: 10px 15px;
            padding-top: 3.5rem; 
            color: white;
            border-radius: 0; 
        }
        .ticker-wrap {
            width: 100%;
            overflow: hidden;
            background-color: #111; 
            border-top: 1px solid #333;
            white-space: nowrap;
            box-sizing: border-box;
            padding: 8px 0;
            color: white;
            border-radius: 0 0 15px 15px; 
        }
        .ticker {
            display: inline-block;
            padding-left: 100%;
            animation: ticker 30s linear infinite;
        }
        @keyframes ticker {
            0%   { transform: translate3d(0, 0, 0); }
            100% { transform: translate3d(-100%, 0, 0); }
        }

        /* CUSTOM METRIC BARS CSS */
        .bar-bg { background: #eee; height: 6px; border-radius: 3px; width: 100%; margin-top: 4px; overflow: hidden; }
        .bar-fill { height: 100%; border-radius: 3px; transition: width 0.5s; }
        .metric-label { font-size: 11px; color: #666; font-weight: 600; display: flex; justify-content: space-between; margin-top: 8px; }
        .tag { font-size: 10px; padding: 2px 6px; border-radius: 4px; font-weight: bold; color: white; }
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

# LOGIN
if not st.session_state['logged_in']:
    c1, c2, c3 = st.columns([1,2,1])
    with c2:
        if os.path.exists(LOGO_PATH):
            lc1, lc2, lc3 = st.columns([1,2,1])
            with lc2: st.image(LOGO_PATH, use_container_width=True)
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
                else: st.error("Access Denied.")

# DASHBOARD
else:
    def push(): save_user(st.session_state['username'], st.session_state['user_data'])

    with st.sidebar:
        if os.path.exists(LOGO_PATH): st.image(LOGO_PATH, width=150)
        else: st.title("⚡ Penny Pulse")
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
        with st.expander("💼 Portfolio & Admin"):
            if st.text_input("Password", type="password") == ADMIN_PASSWORD:
                st.caption("SCROLLING TICKER TAPE")
                curr_tape = st.session_state['user_data'].get('tape_input', "^DJI, ^IXIC, GC=F")
                new_tape = st.text_input("Tape Symbols", value=curr_tape)
                if new_tape != curr_tape:
                    st.session_state['user_data']['tape_input'] = new_tape
                    push()
                    st.rerun()
                st.divider()
                new_t = st.text_input("Ticker Symbol").upper()
                c1, c2 = st.columns(2)
                new_p = c1.number_input("Avg Price")
                new_q = c2.number_input("Quantity", step=1)
                if st.button("Save Trade", type="primary") and new_t: 
                    if 'portfolio' not in st.session_state['user_data']: st.session_state['user_data']['portfolio'] = {}
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

    # HEADER
    t_str = (datetime.utcnow()-timedelta(hours=5)+timedelta(minutes=1)).strftime('%I:%M %p')
    img_b64 = get_base64_image(LOGO_PATH)
    logo_html = f'<img src="data:image/png;base64,{img_b64}" style="height:35px; vertical-align:middle; margin-right:10px;">' if img_b64 else "⚡ "
    tape_content = get_tape_data(st.session_state['user_data'].get('tape_input', "^DJI, ^IXIC, GC=F"))

    st.markdown(f"""
        <div class="header-container">
            <div class="header-top">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <div style="display:flex; align-items:center; font-size:22px; font-weight:900; letter-spacing:-1px;">
                        {logo_html} Penny Pulse
                    </div>
                    <div style="font-family:monospace; font-size:14px; background:rgba(255,255,255,0.1); padding:4px 8px; border-radius:5px;">● {t_str} ET</div>
                </div>
            </div>
            <div class="ticker-wrap"><div class="ticker">{tape_content} {tape_content} {tape_content}</div></div>
        </div>
        <br>
    """, unsafe_allow_html=True)

    t1, t2 = st.tabs(["📊 Live Market", "🚀 Portfolio"])

    # --- ADVANCED CARD DRAWING ---
    def draw(t, port=None):
        d = get_pro_data(t)
        if not d:
            st.warning(f"⚠️ {t}: Fetching...")
            return
        
        # Colors
        border_col = "#4caf50" if d['d'] >= 0 else "#ff4b4b"
        
        # Container
        with st.container():
            st.markdown(f"<div style='height:4px; width:100%; background-color:{border_col}; border-radius: 4px 4px 0 0;'></div>", unsafe_allow_html=True)
            
            # 1. TOP ROW: Name & Price
            c1, c2 = st.columns([1.5, 1])
            with c1:
                st.markdown(f"<h3 style='margin:0; padding:0;'>{t}</h3>", unsafe_allow_html=True)
                st.caption(d['name'][:25])
            with c2:
                arrow = "▲" if d['d'] >= 0 else "▼"
                st.markdown(f"<div style='text-align:right; font-size:20px; font-weight:bold;'>${d['p']:,.2f}</div>", unsafe_allow_html=True)
                st.markdown(f"<div style='text-align:right; color:{border_col}; font-weight:bold; font-size:14px;'>{arrow} {d['d']:.2f}%</div>", unsafe_allow_html=True)
            
            # 2. MARKET STRIP (The Divider Line)
            # Example text for Pre/Post market or Trend
            trend_txt = "BULLISH BIAS" if d['d'] >= 0 else "BEARISH PRESSURE"
            trend_icon = "🟢" if d['d'] >= 0 else "🔴"
            st.markdown(f"""
            <div style="border-top: 1px solid #eee; margin-top:5px; margin-bottom:10px; padding-top:2px; font-size:11px; color:#888; text-align:right;">
               {trend_icon} {trend_txt} 
            </div>
            """, unsafe_allow_html=True)

            # 3. SPARKLINE CHART
            chart = alt.Chart(d['chart']).mark_area(
                line={'color':border_col},
                color=alt.Gradient(gradient='linear', stops=[alt.GradientStop(color=border_col, offset=0), alt.GradientStop(color='white', offset=1)], x1=1, x2=1, y1=1, y2=0)
            ).encode(
                x=alt.X('Idx', axis=None), 
                y=alt.Y('Stock', scale=alt.Scale(domain=[d['chart']['Stock'].min(), d['chart']['Stock'].max()]), axis=None)
            ).configure_view(strokeWidth=0).properties(height=45)
            st.altair_chart(chart, use_container_width=True)

            # 4. DEEP DATA BARS (The new stuff)
            
            # A. DAY RANGE
            # range_pos is 0 to 100
            st.markdown(f"""
            <div class="metric-label">
                <span>Day Range</span>
                <span style="color:#555">${d['l']:,.2f} - ${d['h']:,.2f}</span>
            </div>
            <div class="bar-bg">
                <div class="bar-fill" style="width:{d['range_pos']}%; background: linear-gradient(90deg, #ff4b4b, #f1c40f, #4caf50);"></div>
            </div>
            """, unsafe_allow_html=True)

            # B. RSI
            rsi = d['rsi']
            rsi_col = "#ff4b4b" if rsi > 70 else "#4caf50" if rsi < 30 else "#888"
            rsi_tag = "HOT" if rsi > 70 else "COLD" if rsi < 30 else "NEUTRAL"
            rsi_bg = "#ff4b4b" if rsi > 70 else "#4caf50" if rsi < 30 else "#999"
            
            st.markdown(f"""
            <div class="metric-label">
                <span>RSI ({int(rsi)})</span>
                <span class="tag" style="background:{rsi_bg}">{rsi_tag}</span>
            </div>
            <div class="bar-bg">
                <div class="bar-fill" style="width:{rsi}%; background:{rsi_col};"></div>
            </div>
            """, unsafe_allow_html=True)

            # C. VOLUME
            vol_stat = "HEAVY" if d['vol_pct'] > 120 else "LIGHT" if d['vol_pct'] < 80 else "NORMAL"
            vol_col = "#3498db"
            st.markdown(f"""
            <div class="metric-label">
                <span>Volume ({d['vol_pct']:.0f}%)</span>
                <span style="color:{vol_col}; font-weight:bold;">{vol_stat}</span>
            </div>
            <div class="bar-bg">
                <div class="bar-fill" style="width:{min(d['vol_pct'], 100)}%; background:{vol_col};"></div>
            </div>
            """, unsafe_allow_html=True)

            # Portfolio Footer
            if port:
                gain = (d['p'] - port['e']) * port['q']
                gain_col = "#4caf50" if gain >= 0 else "#ff4b4b"
                st.markdown(f"""<div style="background:#f9f9f9; padding:5px; margin-top:10px; border-radius:5px; display:flex; justify-content:space-between; font-size:12px;">
                    <span>Qty: <b>{port['q']}</b></span>
                    <span>Avg: <b>${port['e']}</b></span>
                    <span style="color:{gain_col}; font-weight:bold;">${gain:+,.0f}</span>
                </div>""", unsafe_allow_html=True)
            
            st.divider()

    with t1:
        tickers = [x.strip().upper() for x in st.session_state['user_data'].get('w_input', "").split(",") if x.strip()]
        cols = st.columns(3) 
        for i, t in enumerate(tickers):
            with cols[i%3]: draw(t)

    with t2:
        port = st.session_state['user_data'].get('portfolio', {})
        if not port: st.info("Portfolio Empty.")
        else:
            tv = sum(get_pro_data(k)['p']*v['q'] for k,v in port.items() if get_pro_data(k))
            tc = sum(v['e']*v['q'] for v in port.values())
            diff = tv - tc
            diff_col = "#4caf50" if diff >= 0 else "#ff4b4b"
            st.markdown(f"""
                <div style="text-align:center; padding:20px; background:linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%); border-radius:10px; margin-bottom:20px; box-shadow:0 4px 6px rgba(0,0,0,0.1);">
                    <div style="color:#555; font-size:12px;">NET LIQUIDATION VALUE</div>
                    <div style="font-size:42px; font-weight:900; color:#2c3e50;">${tv:,.2f}</div>
                    <div style="color:{diff_col}; font-size:18px; font-weight:bold;">{'+' if diff>=0 else ''}${diff:,.2f} ({((tv-tc)/tc)*100:.2f}%)</div>
                </div>
            """, unsafe_allow_html=True)
            cols = st.columns(3)
            for i, (k, v) in enumerate(port.items()):
                with cols[i%3]: draw(k, v)

    time.sleep(30)
    st.rerun()
