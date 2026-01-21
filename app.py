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

# --- 2. MEMORY INITIALIZATION (The "Brain") ---
# This block runs before anything else to ensure variables exist.
if 'initialized' not in st.session_state:
    st.session_state['initialized'] = True
    
    # 1. Define Default Settings
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
    
    # 2. Check URL for Settings (Priority 1)
    qp = st.query_params
    if 'w' in qp: defaults['w_input'] = qp['w']
    if 'at' in qp: defaults['a_tick_input'] = qp['at']
    if 'ap' in qp: defaults['a_price_input'] = float(qp['ap'])
    if 'ao' in qp: defaults['a_on_input'] = (qp['ao'].lower() == 'true')
    if 'fo' in qp: defaults['flip_on_input'] = (qp['fo'].lower() == 'true')
    if 'no' in defaults: defaults['notify_input'] = (qp['no'].lower() == 'true')
    if 'ko' in qp: defaults['keep_on_input'] = (qp['ko'].lower() == 'true')
    if 'bu' in qp: defaults['base_url_input'] = qp['bu']

    # 3. Load into Session State
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v
            
    # 4. Internal Variables (Not saved)
    internal_defaults = {
        'news_results': [], 'scanned_count': 0, 'market_mood': None,
        'alert_triggered': False, 'alert_log': [], 'last_trends': {},
        'mem_ratings': {}, 'mem_meta': {}, 'spy_cache': None,
        'spy_last_fetch': datetime.min, 'banner_msg': None, 'storm_cooldown': {}
    }
    for k, v in internal_defaults.items():
        if k not in st.session_state: st.session_state[k] = v

# --- 3. CORE LOGIC FUNCTIONS ---
def update_params():
    # Save current state to URL
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
    # Handles File Uploads Instantly
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
            st.error(f"Error reading file: {e}")

# --- 4. JAVASCRIPT: AUTO-SAVE & RESTORE ---
def sync_js(config_json):
    js = f"""
    <script>
        const KEY = "penny_pulse_master_save";
        const fromPython = {config_json};
        const saved = localStorage.getItem(KEY);
        const urlParams = new URLSearchParams(window.location.search);
        
        // 1. If URL is empty but we have saved data, RESTORE IT (Redirect)
        if (!urlParams.has("w") && saved) {{
            try {{
                const c = JSON.parse(saved);
                if (c.w && c.w !== "SPY") {{
                    const newUrl = new URL(window.location);
                    newUrl.searchParams.set("w", c.w);
                    newUrl.searchParams.set("at", c.at);
                    newUrl.searchParams.set("ap", c.ap);
                    newUrl.searchParams.set("ao", c.ao);
                    newUrl.searchParams.set("fo", c.fo);
                    newUrl.searchParams.set("no", c.no);
                    window.location.href = newUrl.toString();
                }}
            }} catch(e) {{}}
        }}
        
        // 2. If we are running, SAVE current state to browser memory
        if (fromPython.w) {{
            localStorage.setItem(KEY, JSON.stringify(fromPython));
        }}
    </script>
    """
    components.html(js, height=0, width=0)

def inject_wake_lock(enable):
    if enable:
        js = """<script>navigator.wakeLock.request('screen').catch(console.log);</script>"""
        components.html(js, height=0, width=0)

# --- 5. SIDEBAR ---
st.sidebar.header("⚡ Pulse")
if "OPENAI_KEY" in st.secrets: KEY = st.secrets["OPENAI_KEY"]
else: KEY = st.sidebar.text_input("OpenAI Key (Optional)", type="password") 

# NOTE: 'key=' binds widget to session state. No 'value=' needed (fixes yellow warning).
st.sidebar.text_input("Add Tickers (Comma Sep)", key="w_input", on_change=update_params)

# Lists
PORT = {"HIVE": {"e": 3.19, "d": "Dec 01", "q": 50}, "BAER": {"e": 1.86, "d": "Jan 10", "q": 100}, "TX": {"e": 38.10, "d": "Nov 05", "q": 40}, "IMNN": {"e": 3.22, "d": "Aug 20", "q": 100}, "RERE": {"e": 5.31, "d": "Oct 12", "q": 100}}
NAMES = {"TSLA":"Tesla", "NVDA":"Nvidia", "BTC-USD":"Bitcoin", "AMD":"AMD", "PLTR":"Palantir", "AAPL":"Apple", "SPY":"S&P 500", "^IXIC":"Nasdaq", "^DJI":"Dow Jones", "GC=F":"Gold", "TD.TO":"TD Bank", "IVN.TO":"Ivanhoe", "BN.TO":"Brookfield", "JNJ":"J&J", "^GSPTSE": "TSX"} 
WATCH = [x.strip().upper() for x in st.session_state.w_input.split(",") if x.strip()]
ALL = list(set(WATCH + list(PORT.keys())))

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

# Widget Logic (Safe Variable Creation)
curr_tick = st.session_state.a_tick_input
idx = 0
if curr_tick in sorted(ALL): idx = sorted(ALL).index(curr_tick)

# WIDGETS
a_tick = st.sidebar.selectbox("Price Target Asset", sorted(ALL), index=idx, key="a_tick_input", on_change=update_params)
a_price = st.sidebar.number_input("Target ($)", step=0.5, key="a_price_input", on_change=update_params)
a_on = st.sidebar.toggle("Active Price Alert", key="a_on_input", on_change=update_params)
flip_on = st.sidebar.toggle("Alert on Trend Flip", key="flip_on_input", on_change=update_params) 
keep_on = st.sidebar.toggle("💡 Keep Screen On", key="keep_on_input", on_change=update_params, help="Prevents phone from sleeping.")
notify_on = st.sidebar.checkbox("Desktop Notifications", key="notify_input", on_change=update_params)

# Backup
st.sidebar.divider()
st.sidebar.subheader("📦 Backup & Restore")
export_data = {k: st.session_state[k] for k in ['w_input','a_tick_input','a_price_input','a_on_input','flip_on_input','notify_input','keep_on_input','base_url_input']}
# Remap to short keys for JSON
json_export = {'w': export_data['w_input'], 'at': export_data['a_tick_input'], 'ap': export_data['a_price_input'], 'ao': export_data['a_on_input'], 'fo': export_data['flip_on_input'], 'no': export_data['notify_input'], 'ko': export_data['keep_on_input'], 'bu': export_data['base_url_input']}
st.sidebar.download_button("📥 Download Profile", data=json.dumps(json_export, indent=2), file_name="my_pulse_config.json", mime="application/json")
st.sidebar.file_uploader("📤 Restore Profile", type=["json"], key="uploader_key", on_change=load_profile_callback)

st.sidebar.divider()
with st.sidebar.expander("🔗 Share & Invite"):
    st.text_input("App Web Address", key="base_url_input", on_change=update_params)
    if st.session_state.base_url_input:
        clean = st.session_state.base_url_input.split("?")[0].strip("/")
        params = f"?w={st.session_state.w_input}&at={a_tick}&ap={a_price}&ao={str(a_on).lower()}&fo={str(flip_on).lower()}"
        st.code(f"{clean}/{params}", language="text")

# --- 6. JS EXECUTION (Sync Memory) ---
sync_js(json.dumps(json_export))
inject_wake_lock(keep_on)

# --- 7. NOTIFICATION LOGIC ---
def send_notification(title, body):
    js_code = f"""<script>new Notification("{title}", {{ body: "{body}" }});</script>"""
    components.html(js_code, height=0, width=0)

def log_alert(msg, title="Penny Pulse Alert", is_crash=False):
    t_stamp = (datetime.utcnow() - timedelta(hours=5)).strftime('%H:%M')
    st.session_state['alert_log'].insert(0, f"[{t_stamp}] {msg}")
    components.html("""<audio autoplay><source src="https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3"></audio>""", height=0)
    st.session_state['banner_msg'] = f"<span style='color:{'#ff0000' if is_crash else '#ff4b4b'};'>🚨 {msg.upper()} 🚨</span>"
    if notify_on: send_notification(title, msg)

if st.session_state['alert_log']:
    st.sidebar.divider()
    st.sidebar.markdown("**📜 Recent Alerts**")
    for msg in st.session_state['alert_log'][:5]: st.sidebar.caption(msg)
    if st.sidebar.button("Clear Log"):
        st.session_state['alert_log'] = []
        st.rerun()

# --- 8. HEADER & MARQUEE ---
if st.session_state['banner_msg']:
    st.markdown(f"""
    <div style="background-color:#222;color:white;padding:15px;text-align:center;font-size:20px;font-weight:bold;position:fixed;top:50px;left:0;width:100%;z-index:9999;box-shadow:0px 4px 6px rgba(0,0,0,0.5);border-bottom:3px solid white;">
    {st.session_state['banner_msg']}
    </div>
    """, unsafe_allow_html=True)
    if st.button("❌ Dismiss Alarm"):
        st.session_state['banner_msg'] = None
        st.rerun()

est_now = datetime.utcnow() - timedelta(hours=5)
c1, c2 = st.columns([1, 1])
with c1:
    st.title("⚡ Penny Pulse")
    st.caption(f"Last Updated: {est_now.strftime('%H:%M:%S EST')}")
with c2:
    components.html("""<div style="font-family:'Helvetica';background-color:#0E1117;padding:5px;text-align:center;display:flex;justify-content:center;align-items:center;height:100%;"><span style="color:#BBBBBB;font-weight:bold;font-size:14px;margin-right:5px;">Next Update: </span><span id="countdown" style="color:#FF4B4B;font-weight:900;font-size:18px;">--</span><span style="color:#BBBBBB;font-size:14px;margin-left:2px;"> s</span></div><script>setInterval(function(){var s=60-new Date().getSeconds();document.getElementById("countdown").innerHTML=s;},1000);</script>""", height=60)

# Marquee Logic
@st.cache_data(ttl=60, show_spinner=False)
def get_marquee_data(t_list):
    res = ""
    for t in t_list:
        try:
            tk = yf.Ticker(t)
            p = tk.fast_info['last_price']
            prev = tk.fast_info['previous_close']
            if p and prev:
                d = ((p - prev) / prev) * 100
                c, a = ("#4caf50","▲") if d>=0 else ("#f44336","▼")
                nm = NAMES.get(t, t.replace("BTC-USD","BITCOIN"))
                res += f"<span style='margin-right:20px;font-weight:900;font-size:20px;color:white;'>{nm}: <span style='color:{c};'>${p:,.2f} {a} {d:.2f}%</span></span>"
        except: pass
    return res

marquee_html = get_marquee_data(["SPY","^IXIC","^DJI","BTC-USD"])
st.markdown(f"""<div style="background-color:#0E1117;padding:10px 0;border-top:2px solid #333;border-bottom:2px solid #333;"><marquee scrollamount="6" style="width:100%;">{marquee_html * 10}</marquee></div>""", unsafe_allow_html=True)

# --- 9. HELPERS ---
def check_flip(ticker, current_trend, flip_enabled):
    if not flip_enabled: return
    if ticker in st.session_state['last_trends']:
        prev = st.session_state['last_trends'][ticker]
        if prev != "NEUTRAL" and current_trend != "NEUTRAL" and prev != current_trend:
            log_alert(f"{ticker} flipped to {current_trend}", "Trend Flip")
    st.session_state['last_trends'][ticker] = current_trend 

@st.cache_data(ttl=60, show_spinner=False)
def get_data_cached(s):
    if not s: return None
    s = s.strip().upper()
    try:
        tk = yf.Ticker(s)
        h = tk.history(period="1d", interval="5m", prepost=True)
        if h.empty: h = tk.history(period="5d", interval="1h", prepost=True)
        if h.empty: return None
        
        p = h['Close'].iloc[-1]
        try: pv = tk.fast_info['previous_close']
        except: pv = h['Open'].iloc[0]
        
        d_pct = ((p - pv) / pv) * 100
        
        # Trend
        hm = tk.history(period="1mo")
        rsi, trend = 50, "NEUTRAL"
        if len(hm) > 14:
            d_diff = hm['Close'].diff()
            u, d_val = d_diff.clip(lower=0), -1 * d_diff.clip(upper=0)
            rsi = 100 - (100/(1 + (u.rolling(14).mean()/d_val.rolling(14).mean()).iloc[-1]))
            macd = hm['Close'].ewm(span=12).mean() - hm['Close'].ewm(span=26).mean()
            trend = "BULL" if macd.iloc[-1] > 0 else "BEAR"
            
        return {"p":p, "d":d_pct, "rsi":rsi, "tr":trend, "chart":h, "raw_trend": trend}
    except: return None

# Price Alert Check
if a_on:
    d = get_data_cached(a_tick)
    if d and d['p'] >= a_price:
        if not st.session_state['alert_triggered']:
            log_alert(f"{a_tick} hit ${a_price:,.2f}!", "Price Alert")
            st.session_state['alert_triggered'] = True
    else: st.session_state['alert_triggered'] = False

# --- 10. DASHBOARD RENDERING ---
def render_card(t, inf=None):
    d = get_data_cached(t)
    if d:
        check_flip(t, d['raw_trend'], st.session_state.flip_on_input)
        nm = NAMES.get(t, t)
        if t.endswith(".TO"): nm += " (TSX)"
        elif t.endswith(".V"): nm += " (TSXV)"
        elif t.endswith(".CN"): nm += " (CSE)"
        
        url = f"https://finance.yahoo.com/quote/{t}"
        st.markdown(f"<h3 style='margin:0;'><a href='{url}' target='_blank' style='text-decoration:none;color:inherit;'>{nm}</a></h3>", unsafe_allow_html=True)
        
        color = "green" if d['d'] >= 0 else "red"
        st.markdown(f"## ${d['p']:,.2f} <span style='color:{color};font-size:20px;'>{d['d']:+.2f}%</span>", unsafe_allow_html=True)
        
        if inf:
            q = inf.get("q", 100)
            val = d['p'] * q
            pl = val - (inf['e'] * q)
            st.caption(f"{q} Shares @ ${inf['e']} | Net: ${val:,.0f} | P/L: ${pl:+,.0f}")
        
        # Simple Chart
        c_data = d['chart'].reset_index()
        c_data.columns = ['Time', 'Price'] + list(c_data.columns[2:])
        chart = alt.Chart(c_data.tail(30)).mark_line(color=color).encode(x=alt.X('Time', axis=None), y=alt.Y('Price', scale=alt.Scale(zero=False), axis=None)).properties(height=50)
        st.altair_chart(chart, use_container_width=True)
        
        # Stats
        r_col = "red" if d['rsi']>70 or d['rsi']<30 else "gray"
        st.markdown(f"**Trend:** {d['tr']} | **RSI:** <span style='color:{r_col};'>{d['rsi']:.0f}</span>", unsafe_allow_html=True)
    else: st.warning(f"{t}: No Data")
    st.divider()

t1, t2, t3 = st.tabs(["🏠 Board", "🚀 My Picks", "📰 News"])
with t1:
    cols = st.columns(3)
    for i, t in enumerate(WATCH):
        with cols[i%3]: render_card(t)
with t2:
    cols = st.columns(3)
    for i, (t, inf) in enumerate(PORT.items()):
        with cols[i%3]: render_card(t, inf)

# --- 11. NEWS (Customizable) ---
@st.cache_data(ttl=300, show_spinner=False)
def get_news_cached():
    # --- PASTE YOUR RSS LINKS HERE ---
    MY_RSS_FEEDS = [
        "https://finance.yahoo.com/news/rssindex",
        "https://www.cnbc.com/id/10000664/device/rss/rss.html",
        "https://www.prnewswire.com/rss/news-releases-list.rss"
    ]
    # --- PASTE SPECIFIC ARTICLE LINKS HERE ---
    MY_CUSTOM_LINKS = [] 
    # ---------------------------------------

    items = []
    # 1. Custom Links
    for link in MY_CUSTOM_LINKS:
        items.append({"title": "Custom Article", "link": link, "desc": "Manual Input", "date_str": "Now"})
    
    # 2. RSS Feeds
    head = {'User-Agent': 'Mozilla/5.0'}
    for u in MY_RSS_FEEDS:
        try:
            r = requests.get(u, headers=head, timeout=5)
            root = ET.fromstring(r.content)
            for i in root.findall('.//item')[:15]:
                t = i.find('title').text
                l = i.find('link').text
                if not l: l = i.find('guid').text if i.find('guid') is not None else ""
                
                if t and l:
                    items.append({"title":t, "link":l, "desc":"", "date_str":""})
        except: continue
    return items

with t3:
    c_n1, c_n2 = st.columns([3, 1])
    with c_n1: st.subheader("Global Wire")
    with c_n2: 
        if st.session_state['market_mood']: st.markdown(f"**Mood:** {st.session_state['market_mood']}")
    
    if st.button("Deep Scan (AI)"):
        with st.spinner("Analyzing..."):
            raw = get_news_cached()
            if raw and KEY:
                from openai import OpenAI
                cl = OpenAI(api_key=KEY)
                txt = "\n".join([f"{x['title']} - {x['link']}" for x in raw[:15]])
                prompt = "Analyze financial news. JSON: [{'ticker':'TSLA', 'signal':'🟢', 'reason':'...', 'time':'2h ago', 'title':'...', 'link':'...'}]"
                try:
                    res = cl.chat.completions.create(model="gpt-4o-mini", messages=[{"role":"system","content":prompt},{"role":"user","content":txt}], response_format={"type":"json_object"})
                    st.session_state['news_results'] = json.loads(res.choices[0].message.content).get('articles', [])
                except: st.error("AI Error")
    
    for n in st.session_state['news_results']:
        st.markdown(f"**{n.get('ticker','')} {n.get('signal','')}** | {n.get('time','')} | [{n.get('title','')}]({n.get('link','')})")
        st.caption(n.get('reason',''))
        st.divider()

time.sleep(1)
if not st.session_state.get('stop_refresh'): st.rerun()
