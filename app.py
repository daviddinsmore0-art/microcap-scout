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

# --- FUNDAMENTAL DATA ---
@st.cache_data(ttl=600) 
def get_fundamentals(s):
    try:
        tk = yf.Ticker(s)
        rating = "N/A"
        # Try multiple keys for rating
        keys = ['recommendationKey', 'targetMeanPrice'] 
        info = tk.info
        if 'recommendationKey' in info and info['recommendationKey'] != 'none':
             rating = info['recommendationKey'].replace('_', ' ').upper()
        
        earn_str = "N/A"
        try: 
            cal = tk.calendar
            if cal is not None and not cal.empty:
                if isinstance(cal, dict): next_earn = cal.get('Earnings Date', [None])[0]
                else: next_earn = cal.iloc[0][0]
                if next_earn: earn_str = next_earn.strftime('%b %d')
        except: pass
        
        return {"rating": rating, "earn": earn_str}
    except:
        return {"rating": "N/A", "earn": "N/A"}

# --- LIVE DATA ENGINE ---
def get_pro_data(s):
    try:
        tk = yf.Ticker(s)
        hist = tk.history(period="1mo", interval="1d")
        if hist.empty: return None 
        
        p_live = hist['Close'].iloc[-1]
        prev_close = hist['Close'].iloc[-2] if len(hist) > 1 else p_live
        d_pct = ((p_live - prev_close) / prev_close) * 100

        # --- SMART PRE/POST MARKET LOGIC ---
        pre_post_html = ""
        
        # 1. Check if CAD stock (Force Hide)
        if not (s.endswith('.TO') or s.endswith('.V') or s.endswith('.CN')):
            
            # 2. Check Time (ET)
            # UTC is 4 or 5 hours ahead of ET. We use a simple offset.
            now_utc = datetime.now(timezone.utc)
            now_et = now_utc - timedelta(hours=5) # Approx ET (Standard time)
            
            mode = "OFF"
            # Pre-Market: 4:00 AM - 9:30 AM
            if (now_et.hour == 4) or (now_et.hour > 4 and now_et.hour < 9) or (now_et.hour == 9 and now_et.minute < 30):
                mode = "PRE"
            # Post-Market: 4:00 PM - 8:00 PM
            elif (now_et.hour >= 16 and now_et.hour < 20):
                mode = "POST"
            
            if mode != "OFF":
                try:
                    rt_price = tk.fast_info.get('last_price', None)
                    if rt_price:
                        # Calculate change vs CLOSE
                        pp_pct = ((rt_price - p_live) / p_live) * 100
                        col = "#4caf50" if pp_pct >= 0 else "#ff4b4b"
                        pct_fmt = f"{pp_pct:+.2f}%"
                        # INLINE HTML
                        pre_post_html = f"<span style='color:#ccc; margin:0 4px;'>|</span> <span style='font-size:11px; color:#888;'>{mode}: <span style='color:{col};'>${rt_price:,.2f} ({pct_fmt})</span></span>"
                except: pass

        # Metrics
        rsi_series = calculate_rsi(hist['Close'])
        rsi_val = rsi_series.iloc[-1] if not rsi_series.empty else 50
        
        avg_vol = hist['Volume'].mean()
        curr_vol = hist['Volume'].iloc[-1]
        vol_pct = (curr_vol / avg_vol) * 100 if avg_vol > 0 else 0
        
        day_high = hist['High'].iloc[-1]
        day_low = hist['Low'].iloc[-1]
        range_pos = ((p_live - day_low) / (day_high - day_low)) * 100 if day_high != day_low else 50
        
        # Trend
        sma20 = hist['Close'].tail(20).mean()
        ai_trend = "BULLISH" if p_live > sma20 else "BEARISH"
        trend_txt = "UPTREND" if p_live > sma20 else "DOWNTREND"

        chart = hist['Close'].tail(20).reset_index()
        chart.columns = ['T', 'Stock']
        chart['Idx'] = range(len(chart))
        chart['Stock'] = ((chart['Stock'] - chart['Stock'].iloc[0])/chart['Stock'].iloc[0])*100
        
        try: name = tk.info.get('longName', s)
        except: name = s

        return {
            "p": p_live, "d": d_pct, "chart": chart, "name": name,
            "rsi": rsi_val, "vol_pct": vol_pct, "range_pos": range_pos,
            "h": day_high, "l": day_low, "ai": ai_trend, "trend": trend_txt, "pp": pre_post_html
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
        .block-container { padding-top: 1rem !important; padding-bottom: 2rem; }
        
        /* CARD STYLING */
        div[data-testid="stVerticalBlock"] > div[style*="flex-direction: column;"] > div[data-testid="stVerticalBlock"] {
            background-color: #ffffff;
            border-radius: 12px;
            padding: 15px;
            box-shadow: 0 4px 10px rgba(0,0,0,0.05);
            border: 1px solid #f0f0f0;
        }
        
        /* HEADER & TICKER */
        .header-container { position: sticky; top: 0; z-index: 999; filter: drop-shadow(0 4px 6px rgba(0,0,0,0.2)); }
        .header-top { background: linear-gradient(90deg, #1e1e1e 0%, #2b2d42 100%); padding: 10px 15px; padding-top: 3.5rem; color: white; border-radius: 0; }
        .ticker-wrap { width: 100%; overflow: hidden; background-color: #111; border-top: 1px solid #333; white-space: nowrap; box-sizing: border-box; padding: 8px 0; color: white; border-radius: 0 0 15px 15px; }
        .ticker { display: inline-block; padding-left: 100%; animation: ticker 30s linear infinite; }
        @keyframes ticker { 0% { transform: translate3d(0, 0, 0); } 100% { transform: translate3d(-100%, 0, 0); } }

        /* METRIC BARS & INFO PILLS */
        .bar-bg { background: #eee; height: 5px; border-radius: 3px; width: 100%; margin-top: 3px; overflow: hidden; }
        .bar-fill { height: 100%; border-radius: 3px; }
        .metric-label { font-size: 10px; color: #888; font-weight: 600; display: flex; justify-content: space-between; margin-top: 8px; text-transform: uppercase; }
        .tag { font-size: 9px; padding: 1px 5px; border-radius: 3px; font-weight: bold; color: white; }
        
        .info-pill {
            font-size: 10px; 
            color: #333; 
            background: #f8f9fa; 
            padding: 3px 8px; 
            border-radius: 4px; 
            font-weight: 600;
            margin-right: 6px;
            display: inline-block;
            border: 1px solid #eee;
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

# LOGIN
if not st.session_state['logged_in']:
    c1, c2, c3 = st.columns([1,2,1])
    with c2:
        if os.path.exists(LOGO_PATH):
            lc1, lc2, lc3 = st.columns([1,2,1])
            with lc2: st.image(LOGO_PATH, use_container_width=True)
        else: st.markdown("<h1 style='text-align:center;'>⚡ Penny Pulse</h1>", unsafe_allow_html=True)
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

    # HEADER WITH JS CLOCK
    img_b64 = get_base64_image(LOGO_PATH)
    logo_html = f'<img src="data:image/png;base64,{img_b64}" style="height:35px; vertical-align:middle; margin-right:10px;">' if img_b64 else "⚡ "
    tape_content = get_tape_data(st.session_state['user_data'].get('tape_input', "^DJI, ^IXIC, GC=F"))

    # JAVASCRIPT CLOCK INJECTION
    clock_js = """
    <script>
    function updateClock() {
        var now = new Date();
        var time = now.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', timeZone: 'America/New_York' });
        document.getElementById('live_clock').innerHTML = '● ' + time + ' ET';
    }
    setInterval(updateClock, 1000);
    </script>
    """
    
    st.components.v1.html(clock_js, height=0)

    st.markdown(f"""
        <div class="header-container">
            <div class="header-top">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <div style="display:flex; align-items:center; font-size:22px; font-weight:900; letter-spacing:-1px;">
                        {logo_html} Penny Pulse
                    </div>
                    <div id="live_clock" style="font-family:monospace; font-size:14px; background:rgba(255,255,255,0.1); padding:4px 8px; border-radius:5px;">● --:--:-- ET</div>
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
        
        fund = get_fundamentals(t)
        
        border_col = "#4caf50" if d['d'] >= 0 else "#ff4b4b"
        arrow = "▲" if d['d'] >= 0 else "▼"
        
        # Colors for pills
        ai_col = "#4caf50" if d['ai'] == "BULLISH" else "#ff4b4b"
        trend_col = "#4caf50" if d['trend'] == "UPTREND" else "#ff4b4b"
        
        # Rating Color
        r_up = fund['rating'].upper()
        if "BUY" in r_up or "OUTPERFORM" in r_up: rating_col = "#4caf50"
        elif "SELL" in r_up or "UNDERPERFORM" in r_up: rating_col = "#ff4b4b"
        else: rating_col = "#f1c40f"

        header_html = f"""<div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:5px;"><div><div style="font-size:22px; font-weight:bold; margin-right:8px; color:#2c3e50;">{t}</div><div style="font-size:12px; color:#888; margin-top:-2px;">{d['name'][:25]}...</div></div><div style="text-align:right;"><div style="font-size:22px; font-weight:bold; color:#2c3e50;">${d['p']:,.2f}</div><div style="font-size:13px; font-weight:bold; color:{border_col}; margin-top:-4px;">{arrow} {d['d']:.2f}% {d['pp']}</div></div></div>"""
        
        # Intelligence Row
        pills_html = f'<span class="info-pill" style="border-left: 3px solid {ai_col}">AI: {d["ai"]}</span>'
        pills_html += f'<span class="info-pill" style="border-left: 3px solid {trend_col}">{d["trend"]}</span>'
        
        if fund['rating'] != "N/A":
            pills_html += f'<span class="info-pill" style="border-left: 3px solid {rating_col}">RATING: {fund["rating"]}</span>'
        
        if fund['earn'] != "N/A":
            pills_html += f'<span class="info-pill" style="border-left: 3px solid #333">EARN: {fund["earn"]}</span>'

        with st.container():
            st.markdown(f"<div style='height:4px; width:100%; background-color:{border_col}; border-radius: 4px 4px 0 0;'></div>", unsafe_allow_html=True)
            st.markdown(header_html, unsafe_allow_html=True)
            st.markdown(f'<div style="margin-bottom:10px; display:flex; flex-wrap:wrap; gap:4px;">{pills_html}</div>', unsafe_allow_html=True)
            
            # SPARKLINE CHART
            chart = alt.Chart(d['chart']).mark_area(
                line={'color':border_col},
                color=alt.Gradient(gradient='linear', stops=[alt.GradientStop(color=border_col, offset=0), alt.GradientStop(color='white', offset=1)], x1=1, x2=1, y1=1, y2=0)
            ).encode(
                x=alt.X('Idx', axis=None), 
                y=alt.Y('Stock', scale=alt.Scale(domain=[d['chart']['Stock'].min(), d['chart']['Stock'].max()]), axis=None),
                tooltip=[]
            ).configure_view(strokeWidth=0).properties(height=45)
            st.altair_chart(chart, use_container_width=True)

            # METRIC BARS
            st.markdown(f"""<div class="metric-label"><span>Day Range</span><span style="color:#555">${d['l']:,.2f} - ${d['h']:,.2f}</span></div><div class="bar-bg"><div class="bar-fill" style="width:{d['range_pos']}%; background: linear-gradient(90deg, #ff4b4b, #f1c40f, #4caf50);"></div></div>""", unsafe_allow_html=True)
            
            rsi = d['rsi']
            rsi_tag = "HOT" if rsi > 70 else "COLD" if rsi < 30 else "NEUTRAL"
            rsi_bg = "#ff4b4b" if rsi > 70 else "#4caf50" if rsi < 30 else "#999"
            rsi_fill = "#ff4b4b" if rsi > 70 else "#4caf50" if rsi < 30 else "#888"
            st.markdown(f"""<div class="metric-label"><span>RSI ({int(rsi)})</span><span class="tag" style="background:{rsi_bg}">{rsi_tag}</span></div><div class="bar-bg"><div class="bar-fill" style="width:{rsi}%; background:{rsi_fill};"></div></div>""", unsafe_allow_html=True)
            
            vol_stat = "HEAVY" if d['vol_pct'] > 120 else "LIGHT" if d['vol_pct'] < 80 else "NORMAL"
            st.markdown(f"""<div class="metric-label"><span>Volume ({d['vol_pct']:.0f}%)</span><span style="color:#3498db; font-weight:bold;">{vol_stat}</span></div><div class="bar-bg"><div class="bar-fill" style="width:{min(d['vol_pct'], 100)}%; background:#3498db;"></div></div>""", unsafe_allow_html=True)

            if port:
                gain = (d['p'] - port['e']) * port['q']
                gain_col = "#4caf50" if gain >= 0 else "#ff4b4b"
                st.markdown(f"""<div style="background:#f9f9f9; padding:5px; margin-top:10px; border-radius:5px; display:flex; justify-content:space-between; font-size:12px;"><span>Qty: <b>{port['q']}</b></span><span>Avg: <b>${port['e']}</b></span><span style="color:{gain_col}; font-weight:bold;">${gain:+,.0f}</span></div>""", unsafe_allow_html=True)
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
