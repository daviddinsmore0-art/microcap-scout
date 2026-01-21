import streamlit as st, yfinance as yf, requests, time, re
from datetime import datetime, timedelta
import streamlit.components.v1 as components
import pandas as pd
import altair as alt 
import json
import xml.etree.ElementTree as ET

# --- 1. CONFIG ---
try: st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="wide")
except: pass 

# --- 2. MEMORY SETUP ---
# Initialize session state keys if they don't exist
default_keys = {
    'w_input': "SPY, BTC-USD, TD.TO, PLUG.CN, VTX.V",
    'a_tick_input': "SPY",
    'a_price_input': 0.0,
    'a_on_input': False,
    'flip_on_input': False,
    'keep_on_input': False,
    'notify_input': False,
    'base_url_input': "",
    'news_results': [],
    'alert_log': [],
    'last_trends': {},
    'mem_ratings': {},
    'mem_meta': {},
    'spy_cache': None,
    'spy_last_fetch': datetime.min,
    'banner_msg': None,
    'storm_cooldown': {}
}
for k, v in default_keys.items():
    if k not in st.session_state: st.session_state[k] = v

# --- 3. FUNCTIONS ---
def update_params():
    # Save to URL
    st.query_params["w"] = st.session_state.w_input
    st.query_params["at"] = st.session_state.a_tick_input
    st.query_params["ap"] = str(st.session_state.a_price_input)
    st.query_params["ao"] = str(st.session_state.a_on_input).lower()
    st.query_params["fo"] = str(st.session_state.flip_on_input).lower()
    st.query_params["no"] = str(st.session_state.notify_input).lower()
    st.query_params["ko"] = str(st.session_state.keep_on_input).lower()
    if st.session_state.base_url_input:
        st.query_params["bu"] = st.session_state.base_url_input

def load_profile_callback():
    # Runs on file upload
    uploaded = st.session_state.get('uploader_key')
    if uploaded:
        try:
            data = json.load(uploaded)
            mapping = {'w':'w_input', 'at':'a_tick_input', 'ap':'a_price_input', 'ao':'a_on_input', 'fo':'flip_on_input', 'no':'notify_input', 'ko':'keep_on_input', 'bu':'base_url_input'}
            for j_key, s_key in mapping.items():
                if j_key in data: st.session_state[s_key] = data[j_key]
            update_params()
            st.toast("Restored!", icon="✅")
        except: st.error("File Error")

def play_sound():
    components.html("""<audio autoplay><source src="https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3"></audio>""", height=0)

def inject_wake_lock(enable):
    if enable:
        components.html("""<script>navigator.wakeLock.request('screen').catch(console.log);</script>""", height=0)

# --- 4. SIDEBAR (Create Variables FIRST) ---
st.sidebar.header("⚡ Pulse")
if "OPENAI_KEY" in st.secrets: KEY = st.secrets["OPENAI_KEY"]
else: KEY = st.sidebar.text_input("OpenAI Key", type="password") 

st.sidebar.text_input("Tickers", key="w_input", on_change=update_params)

# Lists
PORT = {"HIVE": {"e": 3.19, "d": "Dec 01", "q": 50}, "BAER": {"e": 1.86, "d": "Jan 10", "q": 100}, "TX": {"e": 38.10, "d": "Nov 05", "q": 40}, "IMNN": {"e": 3.22, "d": "Aug 20", "q": 100}, "RERE": {"e": 5.31, "d": "Oct 12", "q": 100}}
WATCH = [x.strip().upper() for x in st.session_state.w_input.split(",") if x.strip()]
ALL_TICKS = list(set(WATCH + list(PORT.keys())))

# Controls
c1, c2 = st.sidebar.columns(2)
with c1: 
    if st.button("💾 Save"): update_params(); st.toast("Saved!")
with c2: 
    if st.button("🔊 Test"): play_sound()

st.sidebar.divider()
st.sidebar.subheader("🔔 Alerts")

# Create Variables DIRECTLY from Session State (No NameError possible)
# We use these variables later in the code.
curr_tick = st.session_state.a_tick_input
idx = 0
if curr_tick in sorted(ALL_TICKS): idx = sorted(ALL_TICKS).index(curr_tick)

sel_tick = st.sidebar.selectbox("Asset", sorted(ALL_TICKS), index=idx, key="a_tick_input", on_change=update_params)
sel_price = st.sidebar.number_input("Target ($)", step=0.5, key="a_price_input", on_change=update_params)
price_active = st.sidebar.toggle("Price Alert", key="a_on_input", on_change=update_params)
flip_active = st.sidebar.toggle("Trend Flip Alert", key="flip_on_input", on_change=update_params)
keep_screen = st.sidebar.toggle("Keep Screen On", key="keep_on_input", on_change=update_params)
desktop_notify = st.sidebar.checkbox("Desktop Notify", key="notify_input", on_change=update_params)

# Backup
st.sidebar.divider()
with st.sidebar.expander("📦 Backup"):
    json_out = json.dumps({'w': st.session_state.w_input, 'at': st.session_state.a_tick_input, 'ap': st.session_state.a_price_input, 'ao': st.session_state.a_on_input, 'fo': st.session_state.flip_on_input, 'no': st.session_state.notify_input, 'ko': st.session_state.keep_on_input, 'bu': st.session_state.base_url_input})
    st.download_button("Download", json_out, "pulse_config.json", "application/json")
    st.file_uploader("Restore", type=["json"], key="uploader_key", on_change=load_profile_callback)

# --- 5. LOGIC & DASHBOARD ---
def log_alert(msg):
    st.session_state['alert_log'].insert(0, f"[{datetime.now().strftime('%H:%M')}] {msg}")
    play_sound()
    st.session_state['banner_msg'] = f"🚨 {msg} 🚨"
    if desktop_notify:
        components.html(f"<script>new Notification('Pulse Alert', {{body: '{msg}'}});</script>", height=0)

if st.session_state['banner_msg']:
    st.error(st.session_state['banner_msg'])
    if st.button("Dismiss"): st.session_state['banner_msg'] = None; st.rerun()

# Logic Fix: Pass 'flip_active' as argument
def check_trend_flip(ticker, trend, is_enabled):
    if not is_enabled: return
    prev = st.session_state['last_trends'].get(ticker, "NEUTRAL")
    if prev != "NEUTRAL" and trend != "NEUTRAL" and prev != trend:
        log_alert(f"{ticker} FLIPPED to {trend}")
        st.toast(f"{ticker} -> {trend}", icon="⚠️")
    st.session_state['last_trends'][ticker] = trend

# Chart Fix: Simple extraction
@st.cache_data(ttl=60, show_spinner=False)
def get_stock_data(t):
    try:
        tk = yf.Ticker(t)
        # 1. Price
        h = tk.history(period="1d", interval="5m")
        if h.empty: h = tk.history(period="5d", interval="1h")
        if h.empty: return None
        curr = h['Close'].iloc[-1]
        
        # 2. Change
        try: prev = tk.fast_info['previous_close']
        except: prev = h['Open'].iloc[0]
        pct = ((curr - prev)/prev)*100
        
        # 3. Trend/RSI
        hm = tk.history(period="1mo")
        rsi, trend = 50, "NEUTRAL"
        if len(hm) > 14:
            delta = hm['Close'].diff()
            u = delta.clip(lower=0)
            d = -1 * delta.clip(upper=0)
            rsi = 100 - (100/(1 + (u.rolling(14).mean()/d.rolling(14).mean()).iloc[-1]))
            macd = hm['Close'].ewm(span=12).mean() - hm['Close'].ewm(span=26).mean()
            trend = "BULL" if macd.iloc[-1] > 0 else "BEAR"
            
        # 4. Chart Data (Clean)
        # Fix for DuplicateError: explicitly select only what we need
        chart_df = h[['Close']].reset_index()
        chart_df.columns = ['Time', 'Price'] # Renaming specifically to avoid duplicates
        
        return {"p": curr, "d": pct, "rsi": rsi, "tr": trend, "chart": chart_df}
    except: return None

# Price Alert Logic
if price_active:
    d = get_stock_data(sel_tick)
    if d and d['p'] >= sel_price and not st.session_state['alert_triggered']:
        log_alert(f"{sel_tick} HIT ${sel_price}")
        st.session_state['alert_triggered'] = True

# UI
t1, t2, t3 = st.tabs(["🏠 Board", "🚀 My Picks", "📰 News"])

def draw_card(t, shares=0, cost=0):
    d = get_stock_data(t)
    if d:
        # Pass flip_active explicitly
        check_trend_flip(t, d['tr'], flip_active)
        
        color = "green" if d['d'] >= 0 else "red"
        st.markdown(f"**{t}**")
        st.markdown(f"### ${d['p']:,.2f} :{color}[{d['d']:+.2f}%]")
        
        if shares > 0:
            val = d['p'] * shares
            pl = val - (cost * shares)
            st.caption(f"Net: ${val:,.0f} | P/L: ${pl:+,.0f}")
            
        # Chart
        c = alt.Chart(d['chart'].tail(30)).mark_line(color=color).encode(
            x=alt.X('Time', axis=None), 
            y=alt.Y('Price', scale=alt.Scale(zero=False), axis=None)
        ).properties(height=50)
        st.altair_chart(c, use_container_width=True)
        
        r_col = "red" if d['rsi']>70 or d['rsi']<30 else "grey"
        st.caption(f"Trend: {d['tr']} | RSI: :{r_col}[{d['rsi']:.0f}]")
    else: st.warning(f"{t}: No Data")
    st.divider()

with t1:
    cols = st.columns(3)
    for i, t in enumerate(WATCH):
        with cols[i%3]: draw_card(t)

with t2:
    cols = st.columns(3)
    for i, (t, i_d) in enumerate(PORT.items()):
        with cols[i%3]: draw_card(t, i_d['q'], i_d['e'])

# --- 6. NEWS (Link Fix) ---
@st.cache_data(ttl=300)
def get_news_xml():
    try:
        r = requests.get("https://finance.yahoo.com/news/rssindex", headers={"User-Agent":"Mozilla/5.0"})
        root = ET.fromstring(r.content)
        items = []
        for i in root.findall('.//item')[:15]:
            # Link Logic
            l = i.find('link').text if i.find('link') is not None else None
            if not l: 
                g = i.find('guid')
                if g is not None: l = g.text
            
            items.append({
                "title": i.find('title').text,
                "link": l,
                "desc": i.find('description').text if i.find('description') is not None else ""
            })
        return items
    except: return []

with t3:
    if st.button("Analyze News (AI)"):
        raw = get_news_xml()
        if raw and KEY:
            from openai import OpenAI
            cl = OpenAI(api_key=KEY)
            txt = "\n".join([f"{x['title']} - {x['link']}" for x in raw])
            p = "List financial news. JSON format: [{'ticker':'TSLA', 'signal':'🟢', 'text':'...', 'link':'...'}]"
            try:
                res = cl.chat.completions.create(model="gpt-4o-mini", messages=[{"role":"system","content":p},{"role":"user","content":txt}], response_format={"type":"json_object"})
                st.session_state['news_results'] = json.loads(res.choices[0].message.content).get('articles', [])
            except: st.error("AI Error")
    
    for n in st.session_state['news_results']:
        st.markdown(f"**{n.get('ticker','')} {n.get('signal','')}** - [{n.get('text','')}]({n.get('link','')})")
        st.divider()

inject_wake_lock(keep_screen)
time.sleep(1)
if not st.session_state.get('stop_refresh'): st.rerun()
