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
    "connect_timeout": 30
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
        if not conn.is_connected(): conn.reconnect(attempts=3, delay=1)
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
        else: return {
            "w_input": "TD.TO, NKE, SPY",
            "tape_input": "^DJI, ^IXIC, ^GSPTSE, GC=F",
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
            next_earn = None
            if hasattr(cal, 'iloc') and not cal.empty: 
                next_earn = cal.iloc[0][0]
            elif isinstance(cal, dict): 
                dates = cal.get('Earnings Date', [])
                if dates: next_earn = dates[0]
            
            if next_earn:
                ts = pd.Timestamp(next_earn)
                if ts.date() >= datetime.now().date():
                    earn_str = ts.strftime('%b %d')
                else:
                    earn_str = "N/A"
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

        # --- PRE/POST MARKET LOGIC ---
        pre_post_html = ""
        try:
            rt_price = tk.fast_info.get('last_price', p_live)
            # Only show if there is a real price difference (> 1 cent)
            if rt_price and abs(rt_price - p_live) > 0.01:
                pp_pct = ((rt_price - p_live) / p_live) * 100
                
                # Determine label based on UTC time (approximate)
                now = datetime.now(timezone.utc) - timedelta(hours=5) # EST
                lbl = "POST" if now.hour >= 16 else "PRE" if now.hour < 9 else "LIVE"
                
                col = "#4caf50" if pp_pct >= 0 else "#ff4b4b"
                pct_fmt = f"{pp_pct:+.2f}%"
                
                # New Format: Small separate line
                pre_post_html = f"<div style='font-size:11px; color:#888; margin-top:2px;'>{lbl}: <span style='color:{col}; font-weight:bold;'>${rt_price:,.2f} ({pct_fmt})</span></div>"
        except: pass

        sma20 = hist['Close'].tail(20).mean()
        rsi_val = 50 
        try:
            rsi_series = calculate_rsi(hist['Close'])
            if not rsi_series.empty: rsi_val = rsi_series.iloc[-1]
        except: pass
        
        vol_pct = 0
        if not hist['Volume'].empty:
             vol_pct = (hist['Volume'].iloc[-1] / hist['Volume'].mean()) * 100

        range_pos = 50
        day_h = hist['High'].iloc[-1]
        day_l = hist['Low'].iloc[-1]
        if day_h != day_l:
            range_pos = ((p_live - day_l) / (day_h - day_l)) * 100

        chart = hist['Close'].tail(20).reset_index()
        chart.columns = ['T', 'Stock']
        chart['Idx'] = range(len(chart))
        chart['Stock'] = ((chart['Stock'] - chart['Stock'].iloc[0])/chart['Stock'].iloc[0])*100

        return {
            "p": p_live, "d": d_pct, "name": tk.info.get('longName', s),
            "rsi": rsi_val,
            "vol_pct": vol_pct,
            "range_pos": range_pos,
            "h": day_h, "l": day_l, 
            "ai": "BULLISH" if p_live > sma20 else "BEARISH", 
            "trend": "UPTREND" if p_live > sma20 else "DOWNTREND", "pp": pre_post_html,
            "chart": chart
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
                short_name = s.replace("^DJI", "DOW").replace("^IXIC", "NASDAQ").replace("^GSPC", "S&P500").replace("^GSPTSE", "TSX").replace("GC=F", "GOLD").replace("SI=F", "SILVER").replace("BTC-USD", "BTC")
                color = "#4caf50" if chg >= 0 else "#ff4b4b"
                arrow = "▲" if chg >= 0 else "▼"
                items.append(f"<span style='color:#ccc; margin-left:20px;'>{short_name}</span> <span style='color:{color}'>{arrow} {px:,.0f} ({chg:+.1f}%)</span>")
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

# --- CUSTOM CSS ---
st.markdown("""
    <style>
        #MainMenu {visibility: visible;}
        footer {visibility: hidden;}
        .block-container { padding-top: 3.5rem !important; padding-bottom: 2rem; }
        
        div[data-testid="stVerticalBlock"] > div[style*="flex-direction: column;"] > div[data-testid="stVerticalBlock"] {
            background-color: #ffffff;
            border-radius: 12px;
            padding: 15px;
            box-shadow: 0 4px 10px rgba(0,0,0,0.05);
            border: 1px solid #f0f0f0;
        }
        
        .metric-label { font-size: 10px; color: #888; font-weight: 600; display: flex; justify-content: space-between; margin-top: 8px; text-transform: uppercase; }
        .bar-bg { background: #eee; height: 5px; border-radius: 3px; width: 100%; margin-top: 3px; overflow: hidden; }
        .bar-fill { height: 100%; border-radius: 3px; }
        .tag { font-size: 9px; padding: 1px 5px; border-radius: 3px; font-weight: bold; color: white; }
        .info-pill { font-size: 10px; color: #333; background: #f8f9fa; padding: 3px 8px; border-radius: 4px; font-weight: 600; margin-right: 6px; display: inline-block; border: 1px solid #eee; }
    </style>
""", unsafe_allow_html=True)

if not st.session_state['logged_in']:
    c1, c2, c3 = st.columns([1,2,1])
    with c2:
        if os.path.exists(LOGO_PATH):
            st.image(LOGO_PATH, width=150)
        else:
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
    
    tape_content = get_tape_data(st.session_state['user_data'].get('tape_input', "^DJI, ^IXIC, ^GSPTSE, GC=F"))
    
    header_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
    <style>
        body {{ margin: 0; padding: 0; background: transparent; overflow: hidden; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }}
        .ticker-container {{
            width: 100%; height: 45px; background: #111;
            display: flex; align-items: center;
            border-bottom: 1px solid #333;
            border-radius: 0 0 15px 15px; 
            box-shadow: 0 4px 10px rgba(0,0,0,0.3);
        }}
        .ticker-wrap {{ width: 100%; overflow: hidden; white-space: nowrap; }}
        .ticker-move {{ display: inline-block; animation: ticker 15s linear infinite; }}
        @keyframes ticker {{ 0% {{ transform: translate3d(0, 0, 0); }} 100% {{ transform: translate3d(-25%, 0, 0); }} }}
        
        .ticker-item {{ 
            display: inline-block; 
            color: white; 
            font-weight: 900; 
            font-size: 16px; 
            padding: 0 20px; 
        }}
    </style>
    </head>
    <body>
        <div class="ticker-container">
            <div class="ticker-wrap">
                <div class="ticker-move">
                    <span class="ticker-item">{tape_content} &nbsp;|&nbsp; {tape_content} &nbsp;|&nbsp; {tape_content} &nbsp;|&nbsp; {tape_content}</span>
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    components.html(header_html, height=50)

    with st.sidebar:
        st.markdown(f"<div style='background:#f0f2f6; padding:10px; border-radius:5px; margin-bottom:10px; text-align:center;'>👤 <b>User: {st.session_state['username']}</b></div>", unsafe_allow_html=True)
        st.subheader("Operator Control")
        new_w = st.text_area("Watchlist", value=st.session_state['user_data'].get('w_input', ""), height=150)
        if new_w != st.session_state['user_data']['w_input']:
            st.session_state['user_data']['w_input'] = new_w
            push()
            st.rerun()
        st.divider()
        
        with st.expander("Tape Settings"):
            curr_tape = st.session_state['user_data'].get('tape_input', "^DJI, ^IXIC, ^GSPTSE, GC=F")
            new_tape = st.text_input("Symbols", value=curr_tape)
            if new_tape != curr_tape:
                st.session_state['user_data']['tape_input'] = new_tape
                push()
                st.rerun()

        with st.expander("💼 Portfolio & Admin"):
            if st.text_input("Password", type="password") == ADMIN_PASSWORD:
                st.divider()
                st.caption("ADD HOLDING")
                new_t = st.text_input("Ticker Symbol").upper()
                c1, c2 = st.columns(2)
                new_p = c1.number_input("Avg Price")
                new_q = c2.number_input("Quantity", step=1)
                if st.button("Save Trade", type="primary") and new_t: 
                    if 'portfolio' not in st.session_state['user_data']: st.session_state['user_data']['portfolio'] = {}
                    st.session_state['user_data']['portfolio'][new_t] = {"e": new_p, "q": int(new_q)}
                    push()
                    st.rerun()
                
                st.divider()
                st.caption("REMOVE HOLDING")
                port_keys = list(st.session_state['user_data'].get('portfolio', {}).keys())
                rem = st.selectbox("Select Asset", [""] + port_keys)
                if st.button("Delete Asset") and rem: 
                    del st.session_state['user_data']['portfolio'][rem]
                    push()
                    st.rerun()
        
        st.checkbox("Always On Display", key="keep_on")
        if st.button("Logout"):
            logout_session(st.query_params.get("token"))
            st.query_params.clear()
            st.session_state['logged_in'] = False
            st.rerun()
            
    inject_wake_lock(st.session_state.get('keep_on', False))

    t1, t2 = st.tabs(["📊 Live Market", "🚀 Portfolio"])

    def draw(t, port=None):
        d = get_pro_data(t)
        if not d: return
        f = get_fundamentals(t)
        b_col = "#4caf50" if d['d'] >= 0 else "#ff4b4b"
        arrow = "▲" if d['d'] >= 0 else "▼"
        
        r_up = f['rating'].upper()
        if "BUY" in r_up or "OUT" in r_up: r_col = "#4caf50"
        elif "SELL" in r_up or "UNDER" in r_up: r_col = "#ff4b4b"
        else: r_col = "#f1c40f"

        ai_col = "#4caf50" if d['ai'] == "BULLISH" else "#ff4b4b"
        tr_col = "#4caf50" if d['trend'] == "UPTREND" else "#ff4b4b"

        # Pre/Post is now d['pp'], which is a full DIV string that sits below this block
        header_html = f"""<div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:5px;"><div><div style="font-size:22px; font-weight:bold; margin-right:8px; color:#2c3e50;">{t}</div><div style="font-size:12px; color:#888; margin-top:-2px;">{d['name'][:25]}...</div></div><div style="text-align:right;"><div style="font-size:22px; font-weight:bold; color:#2c3e50;">${d['p']:,.2f}</div><div style="font-size:13px; font-weight:bold; color:{b_col}; margin-top:-4px;">{arrow} {d['d']:.2f}%</div>{d['pp']}</div></div>"""
        
        pills_html = f'<span class="info-pill" style="border-left: 3px solid {ai_col}">AI: {d["ai"]}</span>'
        pills_html += f'<span class="info-pill" style="border-left: 3px solid {tr_col}">{d["trend"]}</span>'
        if f['rating'] != "N/A": pills_html += f'<span class="info-pill" style="border-left: 3px solid {r_col}">RATING: {f["rating"]}</span>'
        if f['earn'] != "N/A": pills_html += f'<span class="info-pill" style="border-left: 3px solid #333">EARN: {f["earn"]}</span>'

        with st.container():
            st.markdown(f"<div style='height:4px; width:100%; background-color:{b_col}; border-radius: 4px 4px 0 0;'></div>", unsafe_allow_html=True)
            st.markdown(header_html, unsafe_allow_html=True)
            st.markdown(f'<div style="margin-bottom:10px; display:flex; flex-wrap:wrap; gap:4px;">{pills_html}</div>', unsafe_allow_html=True)
            
            chart = alt.Chart(d['chart']).mark_area(
                line={'color':b_col},
                color=alt.Gradient(gradient='linear', stops=[alt.GradientStop(color=b_col, offset=0), alt.GradientStop(color='white', offset=1)], x1=1, x2=1, y1=1, y2=0)
            ).encode(
                x=alt.X('Idx', axis=None), 
                y=alt.Y('Stock', scale=alt.Scale(domain=[d['chart']['Stock'].min(), d['chart']['Stock'].max()]), axis=None),
                tooltip=[]
            ).configure_view(strokeWidth=0).properties(height=45)
            st.altair_chart(chart, use_container_width=True)
            
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
            total_val = 0
            for k, v in port.items():
                d = get_pro_data(k)
                if d: total_val += d['p'] * v['q']
            st.markdown(f"""<div style="text-align:center; padding:15px; background:#f0f2f6; border-radius:10px; margin-bottom:15px;"><div style="font-size:12px; color:#555;">NET ASSETS</div><div style="font-size:32px; font-weight:bold;">${total_val:,.2f}</div></div>""", unsafe_allow_html=True)
            cols = st.columns(3)
            for i, (k, v) in enumerate(port.items()):
                with cols[i%3]: draw(k, v)

    time.sleep(30)
    st.rerun()
