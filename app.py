import streamlit as st, yfinance as yf, requests, time, re
from datetime import datetime, timedelta
import streamlit.components.v1 as components
import pandas as pd
import altair as alt 
import json
import xml.etree.ElementTree as ET

# --- 1. SETUP ---
try: st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="wide")
except: pass 

# --- 2. PERSISTENCE ENGINE (Restored from v76) ---
if 'initialized' not in st.session_state:
    st.session_state['initialized'] = True
    
    # Defaults
    defaults = {
        'w_input': "SPY, BTC-USD, TD.TO, PLUG.CN, VTX.V",
        'a_tick_input': "SPY",
        'a_price_input': 0.0,
        'a_on_input': False,
        'flip_on_input': False,
        'keep_on_input': False,
        'notify_input': False
    }
    
    # Pull from URL parameters
    qp = st.query_params
    if 'w' in qp: defaults['w_input'] = qp['w']
    if 'at' in qp: defaults['a_tick_input'] = qp['at']
    if 'ap' in qp: defaults['a_price_input'] = float(qp['ap'])
    if 'ao' in qp: defaults['a_on_input'] = (qp['ao'].lower() == 'true')
    
    for k, v in defaults.items():
        st.session_state[k] = v
        
    # CRITICAL: Initialize memory to prevent KeyErrors
    st.session_state['news_results'] = []
    st.session_state['alert_log'] = []
    st.session_state['last_trends'] = {}
    st.session_state['banner_msg'] = None
    st.session_state['storm_cooldown'] = {}
    st.session_state['mem_ratings'] = {}

# --- 3. FUNCTIONS ---
def update_params():
    st.query_params["w"] = st.session_state.w_input
    st.query_params["at"] = st.session_state.a_tick_input
    st.query_params["ap"] = str(st.session_state.a_price_input)
    st.query_params["ao"] = str(st.session_state.a_on_input).lower()

def inject_wake_lock(enable):
    if enable: components.html("""<script>navigator.wakeLock.request('screen').catch(console.log);</script>""", height=0)

def get_rating_and_meta(s):
    # Caching logic for Analyst Ratings & Earnings
    search_ticker = s.replace(".TO","").replace(".V","").replace(".CN","")
    if search_ticker in st.session_state['mem_ratings']: return st.session_state['mem_ratings'][search_ticker]
    try:
        tk = yf.Ticker(search_ticker)
        inf = tk.info
        r = inf.get('recommendationKey', 'N/A').upper().replace('_',' ')
        r_col = "#00C805" if "BUY" in r else ("#FFC107" if "HOLD" in r else "#FF4B4B")
        if r == "N/A": r = "NONE"
        
        earn = "N/A"
        try:
            cal = tk.calendar
            if cal is not None and not (isinstance(cal, list) and len(cal)==0):
                dt = cal.iloc[0,0] if hasattr(cal, 'iloc') else cal.get('Earnings Date', [None])[0]
                if dt: earn = dt.strftime('%b %d')
        except: pass
        
        res = (r, r_col, earn)
        st.session_state['mem_ratings'][search_ticker] = res
        return res
    except: return ("NONE", "#888", "N/A")

# --- 4. SIDEBAR (Restored Full Options) ---
st.sidebar.header("⚡ Penny Pulse")
if "OPENAI_KEY" in st.secrets: KEY = st.secrets["OPENAI_KEY"]
else: KEY = st.sidebar.text_input("OpenAI Key", type="password") 

st.sidebar.text_input("Tickers", key="w_input", on_change=update_params)

# PORTFOLIO DICTIONARY (Restored)
PORT = {"HIVE": {"e": 3.19, "d": "Dec 01", "q": 50}, "BAER": {"e": 1.86, "d": "Jan 10", "q": 100}, "TX": {"e": 38.10, "d": "Nov 05", "q": 40}, "IMNN": {"e": 3.22, "d": "Aug 20", "q": 100}, "RERE": {"e": 5.31, "d": "Oct 12", "q": 100}}
WATCH = [x.strip().upper() for x in st.session_state.w_input.split(",") if x.strip()]
ALL = list(set(WATCH + list(PORT.keys())))

c1, c2 = st.sidebar.columns(2)
with c1: 
    if st.button("💾 Save"): update_params(); st.toast("Saved!")
with c2: 
    if st.button("🔊 Test"): components.html("""<audio autoplay><source src="https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3"></audio>""", height=0)

st.sidebar.divider()
st.sidebar.subheader("🔔 Alerts")
curr = st.session_state.a_tick_input
idx = 0
if curr in sorted(ALL): idx = sorted(ALL).index(curr)
a_tick = st.sidebar.selectbox("Asset", sorted(ALL), index=idx, key="a_tick_input", on_change=update_params)
a_price = st.sidebar.number_input("Target ($)", step=0.5, key="a_price_input", on_change=update_params)
a_on = st.sidebar.toggle("Price Alert", key="a_on_input", on_change=update_params)
st.sidebar.toggle("Flip Alert", key="flip_on_input")
keep_on = st.sidebar.toggle("Keep Screen On", key="keep_on_input", on_change=update_params)

inject_wake_lock(keep_on)

# --- 5. DATA ENGINE ---
def log_alert(msg):
    st.session_state['alert_log'].insert(0, f"[{datetime.now().strftime('%H:%M')}] {msg}")
    components.html("""<audio autoplay><source src="https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3"></audio>""", height=0)
    st.session_state['banner_msg'] = f"🚨 {msg} 🚨"

@st.cache_data(ttl=60, show_spinner=False)
def get_data(s):
    if not s: return None
    s = s.strip().upper()
    try:
        tk = yf.Ticker(s)
        
        # CLEAN TSX FIX: Disable prepost for Canadian stocks
        use_prepost = not any(x in s for x in [".TO", ".V", ".CN"])
        h = tk.history(period="1d", interval="5m", prepost=use_prepost)
        if h.empty: h = tk.history(period="5d", interval="1h", prepost=use_prepost)
        if h.empty: return None
        
        p = h['Close'].iloc[-1]
        try: pv = tk.fast_info['previous_close']
        except: pv = h['Open'].iloc[0]
        d_pct = ((p-pv)/pv)*100
        
        hm = tk.history(period="1mo")
        rsi, trend, vol_ratio = 50, "NEUTRAL", 1.0
        if len(hm)>14:
            diff = hm['Close'].diff()
            u, d = diff.clip(lower=0), -1*diff.clip(upper=0)
            rsi = 100 - (100/(1 + (u.rolling(14).mean()/d.rolling(14).mean()).iloc[-1]))
            m = hm['Close'].ewm(span=12).mean() - hm['Close'].ewm(span=26).mean()
            trend = "BULL" if m.iloc[-1] > 0 else "BEAR"
            vol = hm['Volume'].iloc[-1]; avg = hm['Volume'].mean()
            if avg > 0: vol_ratio = vol/avg
        
        # Fetch Rating/Earnings for Bold UI
        rating, r_col, earn = get_rating_and_meta(s)
            
        return {"p":p, "d":d_pct, "rsi":rsi, "tr":trend, "chart":h, "vol":vol_ratio, "r":rating, "rc":r_col, "e":earn}
    except: return None

# --- 6. UI ---
if st.session_state['banner_msg']:
    st.markdown(f"<div style='background:#900;color:white;padding:10px;text-align:center;font-weight:bold;'>{st.session_state['banner_msg']}</div>", unsafe_allow_html=True)
    if st.button("Dismiss"): st.session_state['banner_msg'] = None; st.rerun()

st.title("⚡ Penny Pulse")
st.caption(f"Last Sync: {datetime.now().strftime('%H:%M:%S')}")

t1, t2, t3 = st.tabs(["🏠 Board", "🚀 My Picks", "📰 News"])

def draw_card(t, shares=None, cost=None):
    d = get_data(t)
    if d:
        # Storm Tracker logic (Restored)
        if d['vol'] >= 2.0 and ((d['tr']=="BULL" and d['rsi']<=35) or (d['tr']=="BEAR" and d['rsi']>=65)):
            last = st.session_state['storm_cooldown'].get(t, datetime.min)
            if (datetime.now()-last).seconds > 300:
                log_alert(f"STORM DETECTED: {t}")
                st.session_state['storm_cooldown'][t] = datetime.now()

        color = "green" if d['d']>=0 else "red"
        st.markdown(f"### {t} | ${d['p']:,.2f}")
        st.markdown(f"<span style='color:{color}'>{d['d']:+.2f}%</span>", unsafe_allow_html=True)
        
        # BOLD UI FIX
        st.markdown(f"""
        <div style='font-size:14px;line-height:1.5;margin-bottom:10px;'>
            <b>TREND:</b> <span style='color:{'#00C805' if d['tr']=='BULL' else '#FF4B4B'}'><b>{d['tr']}</b></span><br>
            <b>RATING:</b> <span style='color:{d['rc']}'><b>{d['r']}</b></span><br>
            <b>EARNINGS:</b> 📅 <b>{d['e']}</b>
        </div>
        """, unsafe_allow_html=True)
        
        # P/L MATH (Restored)
        if shares:
            v = d['p']*shares; pl = v-(cost*shares)
            st.caption(f"Net: ${v:,.0f} | P/L: ${pl:+,.0f}")
            
        cd = d['chart'].reset_index()
        cd.columns = ['Time','Price'] + list(cd.columns[2:])
        ch = alt.Chart(cd.tail(30)).mark_line(color=color).encode(x=alt.X('Time',axis=None), y=alt.Y('Price',scale=alt.Scale(zero=False),axis=None)).properties(height=50)
        st.altair_chart(ch, use_container_width=True)
        st.caption(f"RSI: {d['rsi']:.0f} | Vol: {d['vol']:.1f}x")
        st.divider()

with t1:
    cols = st.columns(3)
    for i, t in enumerate(WATCH):
        with cols[i%3]: draw_card(t)

# MY PICKS LOOP (Restored)
with t2:
    cols = st.columns(3)
    for i, (t, inf) in enumerate(PORT.items()):
        with cols[i%3]: draw_card(t, inf['q'], inf['e'])

# NEWS LOGIC (Restored with Key Check)
with t3:
    if st.button("Analyze Market Context"):
        if KEY:
            from openai import OpenAI
            cl = OpenAI(api_key=KEY)
            FEEDS = ["https://finance.yahoo.com/news/rssindex"]
            items = []
            for f in FEEDS:
                try:
                    r = requests.get(f)
                    root = ET.fromstring(r.content)
                    for i in root.findall('.//item')[:10]:
                        items.append(f"{i.find('title').text} - {i.find('link').text}")
                except: continue
            
            p = "Analyze financial news. Return JSON: [{'ticker':'TSLA', 'signal':'🟢', 'reason':'...', 'time':'2h ago', 'title':'...', 'link':'...'}]"
            try:
                res = cl.chat.completions.create(model="gpt-4o-mini", messages=[{"role":"system","content":p},{"role":"user","content":"\n".join(items)}], response_format={"type":"json_object"})
                st.session_state['news_results'] = json.loads(res.choices[0].message.content).get('articles', [])
            except: st.error("AI Error")
        else: st.info("Enter OpenAI Key in Sidebar")

    for n in st.session_state['news_results']:
        st.markdown(f"**{n.get('ticker','')} {n.get('signal','')}** | {n.get('time','')} | [{n.get('title','')}]({n.get('link','')})")
        st.caption(n.get('reason',''))
        st.divider()

# --- 7. REFRESH ---
time.sleep(2)
st.rerun()
