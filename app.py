import streamlit as st, yfinance as yf, requests, time, re
from datetime import datetime, timedelta
import streamlit.components.v1 as components
import pandas as pd
import altair as alt 
import json
import xml.etree.ElementTree as ET

# --- 1. CONFIG & SETUP ---
try: st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="wide")
except: pass 

# --- 2. INTELLIGENT STARTUP (Fixes Refresh & Defaults) ---
# This block runs once. It prioritizes: URL > Defaults.
if 'initialized' not in st.session_state:
    st.session_state['initialized'] = True
    
    # 1. Default Settings
    defaults = {
        'w_input': "SPY, BTC-USD, TD.TO, PLUG.CN, VTX.V",
        'a_tick_input': "SPY",
        'a_price_input': 0.0,
        'a_on_input': False,
        'flip_on_input': False,
        'keep_on_input': False,
        'notify_input': False,
        'base_url_input': ""
    }
    
    # 2. Check URL for Overrides (The Refresh Fix)
    qp = st.query_params
    if 'w' in qp: defaults['w_input'] = qp['w']
    if 'at' in qp: defaults['a_tick_input'] = qp['at']
    if 'ap' in qp: defaults['a_price_input'] = float(qp['ap'])
    if 'ao' in qp: defaults['a_on_input'] = (qp['ao'].lower() == 'true')
    if 'fo' in qp: defaults['flip_on_input'] = (qp['fo'].lower() == 'true')
    if 'no' in defaults: defaults['notify_input'] = (qp['no'].lower() == 'true')
    if 'ko' in qp: defaults['keep_on_input'] = (qp['ko'].lower() == 'true')
    if 'bu' in qp: defaults['base_url_input'] = qp['bu']

    # 3. Apply to Memory
    for k, v in defaults.items():
        st.session_state[k] = v
        
    # 4. internal state
    st.session_state['news_results'] = []
    st.session_state['scanned_count'] = 0
    st.session_state['market_mood'] = None
    st.session_state['alert_triggered'] = False
    st.session_state['alert_log'] = []
    st.session_state['last_trends'] = {}
    st.session_state['mem_ratings'] = {}
    st.session_state['mem_meta'] = {}
    st.session_state['spy_cache'] = None
    st.session_state['spy_last_fetch'] = datetime.min
    st.session_state['banner_msg'] = None
    st.session_state['storm_cooldown'] = {}

# --- 3. CORE FUNCTIONS ---
def update_params():
    # Sync memory to URL
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
    # Immediate File Loading
    uploaded = st.session_state.get('uploader_key')
    if uploaded is not None:
        try:
            data = json.load(uploaded)
            mapping = {
                'w': 'w_input', 'at': 'a_tick_input', 'ap': 'a_price_input',
                'ao': 'a_on_input', 'fo': 'flip_on_input', 'no': 'notify_input',
                'ko': 'keep_on_input', 'bu': 'base_url_input'
            }
            for json_k, state_k in mapping.items():
                if json_k in data:
                    st.session_state[state_k] = data[json_k]
            update_params()
            st.toast("Profile Loaded!", icon="✅")
        except Exception as e:
            st.error(f"Error: {e}")

# --- 4. JAVASCRIPT ---
def sync_js(config_json):
    js = f"""
    <script>
        const KEY = "penny_pulse_v69_data";
        const fromPython = {config_json};
        const saved = localStorage.getItem(KEY);
        const urlParams = new URLSearchParams(window.location.search);
        if (!urlParams.has("w") && saved) {{
            try {{
                const c = JSON.parse(saved);
                if (c.w && c.w !== "SPY") {{
                    const newUrl = new URL(window.location);
                    newUrl.searchParams.set("w", c.w);
                    // ... (rest of sync logic implied)
                    window.location.href = newUrl.toString();
                }}
            }} catch(e) {{}}
        }}
        if (fromPython.w) {{ localStorage.setItem(KEY, JSON.stringify(fromPython)); }}
    </script>
    """
    components.html(js, height=0, width=0)

def inject_wake_lock(enable):
    if enable:
        js = """<script>navigator.wakeLock.request('screen').catch(console.log);</script>"""
        components.html(js, height=0, width=0)

# --- 5. SIDEBAR (The "NameError" Fix) ---
# We define widgets AND assign them to variables immediately.
# This ensures 'flip_on' exists for the rest of the script.
st.sidebar.header("⚡ Pulse")
if "OPENAI_KEY" in st.secrets: KEY = st.secrets["OPENAI_KEY"]
else: KEY = st.sidebar.text_input("OpenAI Key (Optional)", type="password") 

st.sidebar.text_input("Add Tickers (Comma Sep)", key="w_input", on_change=update_params)

# Define Lists
PORT = {"HIVE": {"e": 3.19, "d": "Dec 01", "q": 50}, "BAER": {"e": 1.86, "d": "Jan 10", "q": 100}, "TX": {"e": 38.10, "d": "Nov 05", "q": 40}, "IMNN": {"e": 3.22, "d": "Aug 20", "q": 100}, "RERE": {"e": 5.31, "d": "Oct 12", "q": 100}}
NAMES = {"TSLA":"Tesla", "NVDA":"Nvidia", "BTC-USD":"Bitcoin", "AMD":"AMD", "PLTR":"Palantir", "AAPL":"Apple", "SPY":"S&P 500", "^IXIC":"Nasdaq", "^DJI":"Dow Jones", "GC=F":"Gold", "TD.TO":"TD Bank", "IVN.TO":"Ivanhoe", "BN.TO":"Brookfield", "JNJ":"J&J", "^GSPTSE": "TSX"} 
WATCH = [x.strip().upper() for x in st.session_state.w_input.split(",") if x.strip()]
ALL = list(set(WATCH + list(PORT.keys())))

# Buttons
c1, c2 = st.sidebar.columns(2)
with c1:
    if st.button("💾 Save Settings"):
        update_params()
        st.toast("Settings Saved!", icon="💾")
with c2:
    if st.button("🔊 Test Audio"):
        components.html("""<audio autoplay><source src="https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3"></audio>""", height=0)
        st.toast("Audio Armed!", icon="🔊")

st.sidebar.divider()
st.sidebar.subheader("🔔 Smart Alerts") 

# Logic for dropdown index
curr_tick = st.session_state.a_tick_input
idx = 0
if curr_tick in ALL: 
    temp_list = sorted(ALL)
    if curr_tick in temp_list: idx = temp_list.index(curr_tick)

# WIDGET DEFINITIONS (Assigned to variables to prevent crashes)
a_tick = st.sidebar.selectbox("Price Target Asset", sorted(ALL), index=idx, key="a_tick_input", on_change=update_params)
a_price = st.sidebar.number_input("Target ($)", step=0.5, key="a_price_input", on_change=update_params)
a_on = st.sidebar.toggle("Active Price Alert", key="a_on_input", on_change=update_params)
flip_on = st.sidebar.toggle("Alert on Trend Flip", key="flip_on_input", on_change=update_params) 
keep_on = st.sidebar.toggle("💡 Keep Screen On", key="keep_on_input", on_change=update_params, help="Prevents sleep.")
notify_on = st.sidebar.checkbox("Desktop Notifications", key="notify_input", on_change=update_params)

# Backup & Share
st.sidebar.divider()
with st.sidebar.expander("📦 Backup & Restore"):
    config_export = {k: st.session_state[k] for k in ['w_input','a_tick_input','a_price_input','a_on_input','flip_on_input','notify_input','keep_on_input','base_url_input']}
    # Rename keys for JSON compatibility
    json_export = {'w': config_export['w_input'], 'at': config_export['a_tick_input'], 'ap': config_export['a_price_input'], 'ao': config_export['a_on_input'], 'fo': config_export['flip_on_input'], 'no': config_export['notify_input'], 'ko': config_export['keep_on_input'], 'bu': config_export['base_url_input']}
    st.download_button("📥 Download Profile", data=json.dumps(json_export, indent=2), file_name="my_pulse_config.json", mime="application/json")
    st.file_uploader("📤 Restore Profile", type=["json"], key="uploader_key", on_change=load_profile_callback)

with st.sidebar.expander("🔗 Share & Invite"):
    base_url = st.text_input("App URL", key="base_url_input", on_change=update_params)
    if base_url:
        clean = base_url.split("?")[0].strip("/")
        link = f"{clean}?w={st.session_state.w_input}&at={a_tick}&ap={a_price}&ao={str(a_on).lower()}&fo={str(flip_on).lower()}"
        st.code(link, language="text")

# --- 6. ALERT LOGIC ---
def send_notify(title, body):
    components.html(f"<script>new Notification('{title}', {{body: '{body}'}});</script>", height=0)

def log_alert(msg, title="Alert"):
    st.session_state['alert_log'].insert(0, f"[{datetime.now().strftime('%H:%M')}] {msg}")
    components.html("""<audio autoplay><source src="https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3"></audio>""", height=0)
    st.session_state['banner_msg'] = f"🚨 {msg.upper()} 🚨"
    if notify_on: send_notify(title, msg)

if st.session_state['alert_log']:
    st.sidebar.divider()
    for m in st.session_state['alert_log'][:5]: st.sidebar.caption(m)
    if st.sidebar.button("Clear Log"): st.session_state['alert_log'] = []; st.rerun()

# --- 7. ANALYSIS FUNCTIONS ---
def check_flip(ticker, current_trend):
    # Uses the variable 'flip_on' defined in Step 5
    if not flip_on: return
    if ticker in st.session_state['last_trends']:
        prev = st.session_state['last_trends'][ticker]
        if prev != "NEUTRAL" and current_trend != "NEUTRAL" and prev != current_trend:
            log_alert(f"{ticker} flipped to {current_trend}", "Trend Flip")
    st.session_state['last_trends'][ticker] = current_trend 

@st.cache_data(ttl=60, show_spinner=False)
def get_data(s):
    try:
        tk = yf.Ticker(s)
        h = tk.history(period="1d", interval="5m")
        if h.empty: h = tk.history(period="5d", interval="1h")
        if h.empty: return None
        
        p = h['Close'].iloc[-1]
        try: pv = tk.fast_info['previous_close']
        except: pv = h['Open'].iloc[0]
        
        d = ((p - pv)/pv)*100
        
        # Trend Logic
        hm = tk.history(period="1mo")
        rsi = 50
        trend = "NEUTRAL"
        if len(hm) > 14:
            delta = hm['Close'].diff()
            u, d_val = delta.clip(lower=0), -1*delta.clip(upper=0)
            rsi = 100 - (100/(1 + (u.rolling(14).mean()/d_val.rolling(14).mean()).iloc[-1]))
            macd = hm['Close'].ewm(span=12).mean() - hm['Close'].ewm(span=26).mean()
            if macd.iloc[-1] > 0: trend = "BULL"
            else: trend = "BEAR"
            
        return {"p":p, "d":d, "rsi":rsi, "trend":trend, "chart": h}
    except: return None

# --- 8. DASHBOARD ---
if st.session_state['banner_msg']:
    st.markdown(f"<div style='background:#900;color:white;padding:10px;text-align:center;font-weight:bold;position:fixed;top:0;left:0;width:100%;z-index:99;'>{st.session_state['banner_msg']}</div>", unsafe_allow_html=True)
    if st.button("Dismiss"): st.session_state['banner_msg'] = None; st.rerun()

c1, c2 = st.columns([1,1])
with c1: st.title("⚡ Penny Pulse")
with c2: components.html(f"<div style='text-align:center;color:#888;'>Updated: {datetime.now().strftime('%H:%M:%S')}</div>", height=40)

# Check Price Alert
if a_on:
    d = get_data(a_tick)
    if d and d['p'] >= a_price and not st.session_state['alert_triggered']:
        log_alert(f"{a_tick} hit ${a_price}!", "Price Target")
        st.session_state['alert_triggered'] = True

# Main Tabs
t1, t2, t3 = st.tabs(["🏠 Dashboard", "🚀 My Picks", "📰 News"])

def draw_card(t, shares=None, entry=None):
    d = get_data(t)
    if d:
        check_flip(t, d['trend'])
        nm = NAMES.get(t, t)
        color = "green" if d['d'] >= 0 else "red"
        st.markdown(f"**{nm}**")
        st.markdown(f"## ${d['p']:,.2f} <span style='color:{color};font-size:18px;'>{d['d']:+.2f}%</span>", unsafe_allow_html=True)
        if shares:
            val = d['p'] * shares
            pl = val - (entry * shares)
            st.caption(f"{shares} @ ${entry} | Net: ${val:,.0f} | P/L: ${pl:+,.0f}")
        
        # Chart
        c_data = d['chart'].reset_index()
        c_data.columns = ['Time', 'Close'] + list(c_data.columns[2:]) # normalize
        chart = alt.Chart(c_data[-30:]).mark_line(color=color).encode(x=alt.X('Time', axis=None), y=alt.Y('Close', scale=alt.Scale(zero=False), axis=None)).properties(height=50)
        st.altair_chart(chart, use_container_width=True)
        
        # Stats
        r_col = "red" if d['rsi'] > 70 or d['rsi'] < 30 else "grey"
        st.markdown(f"**Trend:** {d['trend']} | **RSI:** <span style='color:{r_col}'>{d['rsi']:.0f}</span>", unsafe_allow_html=True)
    else:
        st.warning(f"No data for {t}")
    st.divider()

with t1:
    cols = st.columns(3)
    for i, t in enumerate(WATCH):
        with cols[i%3]: draw_card(t)

with t2:
    cols = st.columns(3)
    for i, (t, info) in enumerate(PORT.items()):
        with cols[i%3]: draw_card(t, info['q'], info['e'])

# --- 9. NEWS (Fixed Links & Time) ---
def get_news():
    try:
        url = "https://finance.yahoo.com/news/rssindex"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
        root = ET.fromstring(r.content)
        items = []
        for i in root.findall('.//item')[:20]:
            link = i.find('link').text
            # GUID fallback for links
            if not link: 
                guid = i.find('guid')
                if guid is not None: link = guid.text
            items.append({
                "title": i.find('title').text,
                "link": link,
                "desc": i.find('description').text if i.find('description') is not None else "",
                "pub": i.find('pubDate').text if i.find('pubDate') is not None else ""
            })
        return items
    except: return []

with t3:
    if st.button("Deep Scan (AI)"):
        with st.spinner("Analyzing..."):
            raw = get_news()
            if not raw or not KEY:
                st.error("No news or No API Key")
            else:
                from openai import OpenAI
                client = OpenAI(api_key=KEY)
                txt = "\n".join([f"{i+1}. {n['title']} ({n['pub']}) - {n['link']}" for i, n in enumerate(raw[:10])])
                # Prompt asks for relative time explicitly
                prompt = "Analyze financial news. Format as JSON list: [{'ticker': 'TSLA', 'signal': '🟢', 'reason': 'Rates cut', 'time': '2h ago', 'title': '...', 'link': '...'}]"
                res = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role":"system", "content": prompt}, {"role":"user", "content": txt}], response_format={"type": "json_object"})
                st.session_state['news_results'] = json.loads(res.choices[0].message.content).get('articles', [])
    
    for n in st.session_state['news_results']:
        st.markdown(f"**{n.get('ticker','')} {n.get('signal','')}** | {n.get('time','')} | [{n.get('title','')}]({n.get('link','')})")
        st.caption(n.get('reason',''))
        st.divider()

inject_wake_lock(keep_on)
sync_js(json.dumps(json_export)) # Sync valid config to JS for local storage backup
time.sleep(1)
if not st.session_state.get('stop_refresh'): st.rerun()
