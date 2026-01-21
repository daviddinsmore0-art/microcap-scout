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

# --- 2. AUTO-SAVE & MEMORY (The "Brain") ---
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
        'notify_input': False,
        'base_url_input': ""
    }
    
    # URL Overrides
    qp = st.query_params
    if 'w' in qp: defaults['w_input'] = qp['w']
    if 'at' in qp: defaults['a_tick_input'] = qp['at']
    if 'ap' in qp: defaults['a_price_input'] = float(qp['ap'])
    if 'ao' in qp: defaults['a_on_input'] = (qp['ao'].lower() == 'true')
    if 'fo' in qp: defaults['flip_on_input'] = (qp['fo'].lower() == 'true')
    
    for k, v in defaults.items():
        st.session_state[k] = v
        
    # Internal State
    st.session_state['news_results'] = []
    st.session_state['alert_log'] = []
    st.session_state['last_trends'] = {}
    st.session_state['banner_msg'] = None
    st.session_state['storm_cooldown'] = {}

# --- 3. FUNCTIONS ---
def update_params():
    st.query_params["w"] = st.session_state.w_input
    st.query_params["at"] = st.session_state.a_tick_input
    st.query_params["ap"] = str(st.session_state.a_price_input)
    st.query_params["ao"] = str(st.session_state.a_on_input).lower()
    st.query_params["fo"] = str(st.session_state.flip_on_input).lower()

def load_profile_callback():
    uploaded = st.session_state.get('uploader_key')
    if uploaded:
        try:
            data = json.load(uploaded)
            mapping = {'w':'w_input', 'at':'a_tick_input', 'ap':'a_price_input', 'ao':'a_on_input', 'fo':'flip_on_input'}
            for j,s in mapping.items():
                if j in data: st.session_state[s] = data[j]
            update_params()
            st.toast("Restored!", icon="✅")
        except: st.error("File Error")

def sync_js(config_json):
    js = f"""<script>
    const KEY="penny_pulse_v77"; const d={config_json}; const s=localStorage.getItem(KEY);
    const p=new URLSearchParams(window.location.search);
    if(!p.has("w")&&s){{try{{const c=JSON.parse(s);if(c.w&&c.w!=="SPY"){{
    const u=new URL(window.location);u.searchParams.set("w",c.w);u.searchParams.set("at",c.at);
    u.searchParams.set("ap",c.ap);u.searchParams.set("ao",c.ao);u.searchParams.set("fo",c.fo);
    window.location.href=u.toString();}}}}catch(e){{}}}}
    if(d.w){{localStorage.setItem(KEY,JSON.stringify(d));}}
    </script>"""
    components.html(js, height=0, width=0)

def inject_wake_lock(enable):
    if enable: components.html("""<script>navigator.wakeLock.request('screen').catch(console.log);</script>""", height=0)

# --- 4. SIDEBAR ---
st.sidebar.header("⚡ Pulse")
if "OPENAI_KEY" in st.secrets: KEY = st.secrets["OPENAI_KEY"]
else: KEY = st.sidebar.text_input("OpenAI Key", type="password") 

st.sidebar.text_input("Tickers", key="w_input", on_change=update_params)

# Lists
PORT = {"HIVE": {"e": 3.19, "d": "Dec 01", "q": 50}, "BAER": {"e": 1.86, "d": "Jan 10", "q": 100}, "TX": {"e": 38.10, "d": "Nov 05", "q": 40}, "IMNN": {"e": 3.22, "d": "Aug 20", "q": 100}, "RERE": {"e": 5.31, "d": "Oct 12", "q": 100}}
WATCH = [x.strip().upper() for x in st.session_state.w_input.split(",") if x.strip()]
ALL = list(set(WATCH + list(PORT.keys())))

# Controls
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
flip_on = st.sidebar.toggle("Flip Alert", key="flip_on_input", on_change=update_params)
keep_on = st.sidebar.toggle("Keep Screen On", key="keep_on_input", on_change=update_params)
notify_on = st.sidebar.checkbox("Desktop Notify", key="notify_input", on_change=update_params)

# Backup
st.sidebar.divider()
with st.sidebar.expander("📦 Backup"):
    export = {'w': st.session_state.w_input, 'at': a_tick, 'ap': a_price, 'ao': a_on, 'fo': flip_on}
    st.download_button("Download", json.dumps(export), "pulse_config.json", "application/json")
    st.file_uploader("Restore", type=["json"], key="uploader_key", on_change=load_profile_callback)

# Save to Browser
sync_js(json.dumps(export))
inject_wake_lock(keep_on)

# --- 5. DATA LOGIC ---
def log_alert(msg, title="Alert"):
    st.session_state['alert_log'].insert(0, f"[{datetime.now().strftime('%H:%M')}] {msg}")
    components.html("""<audio autoplay><source src="https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3"></audio>""", height=0)
    st.session_state['banner_msg'] = f"🚨 {msg} 🚨"
    if notify_on: components.html(f"<script>new Notification('{title}', {{body: '{msg}'}});</script>", height=0)

if st.session_state['alert_log']:
    st.sidebar.divider()
    for m in st.session_state['alert_log'][:5]: st.sidebar.caption(m)
    if st.sidebar.button("Clear Log"): st.session_state['alert_log'] = []; st.rerun()

def check_flip(ticker, current_trend, enabled):
    if not enabled: return
    prev = st.session_state['last_trends'].get(ticker, "NEUTRAL")
    if prev != "NEUTRAL" and current_trend != "NEUTRAL" and prev != current_trend:
        log_alert(f"{ticker} FLIPPED to {current_trend}", "Trend Flip")
    st.session_state['last_trends'][ticker] = current_trend

def calc_storm(ticker, rsi, vol_ratio, trend, change):
    score = 0
    if vol_ratio >= 2.0: score += 30
    elif vol_ratio >= 1.5: score += 15
    if trend == "BULL" and change > 0:
        if rsi <= 35: score += 25
        if change > 2.0: score += 20
        if score >= 70: return score, "BULL"
    elif trend == "BEAR" and change < 0:
        if rsi >= 65: score += 25
        if change < -2.0: score += 25
        if score >= 70: return score, "BEAR"
    return score, "NEUTRAL"

@st.cache_data(ttl=60, show_spinner=False)
def get_data(s):
    if not s: return None
    s = s.strip().upper()
    try:
        tk = yf.Ticker(s)
        # Price
        h = tk.history(period="1d", interval="5m", prepost=True)
        if h.empty: h = tk.history(period="5d", interval="1h", prepost=True)
        if h.empty: return None
        p = h['Close'].iloc[-1]
        try: pv = tk.fast_info['previous_close']
        except: pv = h['Open'].iloc[0]
        d_pct = ((p-pv)/pv)*100
        
        # Stats
        hm = tk.history(period="1mo")
        rsi, trend = 50, "NEUTRAL"
        vol_ratio = 1.0
        if len(hm)>14:
            diff = hm['Close'].diff()
            u, d = diff.clip(lower=0), -1*diff.clip(upper=0)
            rsi = 100 - (100/(1 + (u.rolling(14).mean()/d.rolling(14).mean()).iloc[-1]))
            m = hm['Close'].ewm(span=12).mean() - hm['Close'].ewm(span=26).mean()
            trend = "BULL" if m.iloc[-1] > 0 else "BEAR"
            vol = hm['Volume'].iloc[-1]
            avg = hm['Volume'].mean()
            if avg > 0: vol_ratio = vol/avg
            
        s_score, s_mode = calc_storm(s, rsi, vol_ratio, trend, d_pct)
        return {"p":p, "d":d_pct, "rsi":rsi, "tr":trend, "chart":h, "storm":s_score, "mode":s_mode}
    except: return None

# Price Alert
if a_on:
    d = get_data(a_tick)
    if d and d['p'] >= a_price and not st.session_state['alert_triggered']:
        log_alert(f"{a_tick} hit ${a_price:,.2f}!", "Price Alert")
        st.session_state['alert_triggered'] = True

# --- 6. UI RESTORATION (Header & Marquee) ---
if st.session_state['banner_msg']:
    st.markdown(f"<div style='background:#900;color:white;padding:10px;text-align:center;font-weight:bold;position:fixed;top:0;left:0;width:100%;z-index:99;'>{st.session_state['banner_msg']}</div>", unsafe_allow_html=True)
    if st.button("Dismiss"): st.session_state['banner_msg'] = None; st.rerun()

# The "Next Update" Bar
c1, c2 = st.columns([1,1])
with c1: 
    st.title("⚡ Penny Pulse")
    st.caption(f"Last Updated: {datetime.now().strftime('%H:%M:%S')}")
with c2:
    components.html("""
    <div style="background-color:#0E1117; color:#FF4B4B; padding:10px; border-radius:5px; text-align:center; font-family:sans-serif; font-weight:bold; font-size:24px; border: 1px solid #333;">
    Next Update: <span id="timer">--</span>s
    </div>
    <script>setInterval(function(){document.getElementById("timer").innerHTML=60-new Date().getSeconds();},1000);</script>
    """, height=70)

# The Scroller (HTML Marquee)
@st.cache_data(ttl=60, show_spinner=False)
def get_marquee():
    txt = ""
    for t in ["SPY","^IXIC","^DJI","BTC-USD"]:
        d = get_data(t)
        if d:
            c = "#4caf50" if d['d']>=0 else "#ff4b4b"
            a = "▲" if d['d']>=0 else "▼"
            txt += f"<span style='margin-right:20px; font-weight:bold; font-size:20px; color:white;'>{t}: <span style='color:{c};'>${d['p']:,.2f} {a} {d['d']:.2f}%</span></span>"
    return txt

mq = get_marquee()
st.markdown(f"""
<div style="background-color:#0E1117; padding:10px; border-top:2px solid #333; border-bottom:2px solid #333; margin-bottom:20px;">
<marquee scrollamount="10">{mq * 5}</marquee>
</div>
""", unsafe_allow_html=True)

# --- 7. DASHBOARD CARDS (Restored) ---
t1, t2, t3 = st.tabs(["🏠 Board", "🚀 My Picks", "📰 News"])

def draw_card(t, shares=None, cost=None):
    d = get_data(t)
    if d:
        check_flip(t, d['tr'], flip_on)
        if d['storm'] >= 70:
            last = st.session_state['storm_cooldown'].get(t, datetime.min)
            if (datetime.now()-last).seconds > 300:
                log_alert(f"STORM ALERT: {t}", d['mode'])
                st.session_state['storm_cooldown'][t] = datetime.now()

        # The Card UI
        color = "green" if d['d']>=0 else "red"
        st.markdown(f"""
        <div style="border:1px solid #333; border-radius:10px; padding:15px; margin-bottom:10px;">
            <h3 style="margin:0;">{t}</h3>
            <h2 style="margin:0;">${d['p']:,.2f} <span style="color:{color}; font-size:20px;">{d['d']:+.2f}%</span></h2>
        </div>
        """, unsafe_allow_html=True)
        
        if shares:
            v = d['p']*shares
            pl = v-(cost*shares)
            st.caption(f"Net: ${v:,.0f} | P/L: ${pl:+,.0f}")

        # Chart
        cd = d['chart'].reset_index()
        cd.columns = ['Time','Price'] + list(cd.columns[2:])
        ch = alt.Chart(cd.tail(30)).mark_line(color=color).encode(x=alt.X('Time',axis=None), y=alt.Y('Price',scale=alt.Scale(zero=False),axis=None)).properties(height=50)
        st.altair_chart(ch, use_container_width=True)
        
        r_c = "red" if d['rsi']>70 or d['rsi']<30 else "gray"
        st.caption(f"Trend: {d['tr']} | RSI: :{r_c}[{d['rsi']:.0f}]")
        st.divider()
    else: st.warning(f"No Data: {t}")

with t1:
    cols = st.columns(3)
    for i, t in enumerate(WATCH):
        with cols[i%3]: draw_card(t)
with t2:
    cols = st.columns(3)
    for i, (t, inf) in enumerate(PORT.items()):
        with cols[i%3]: draw_card(t, inf['q'], inf['e'])

# --- 8. NEWS ---
@st.cache_data(ttl=300)
def get_feed():
    # CUSTOMIZE LINKS HERE
    FEEDS = ["https://finance.yahoo.com/news/rssindex", "https://www.cnbc.com/id/10000664/device/rss/rss.html"]
    LINKS = [] 
    
    items = []
    for l in LINKS: items.append({"title":"Manual Link", "link":l, "date":"Now"})
    
    for u in FEEDS:
        try:
            r = requests.get(u, headers={"User-Agent":"Mozilla/5.0"}, timeout=5)
            root = ET.fromstring(r.content)
            for i in root.findall('.//item')[:10]:
                l = i.find('link').text
                if not l: l = i.find('guid').text
                pub = i.find('pubDate')
                d_str = pub.text if pub is not None else ""
                items.append({"title":i.find('title').text, "link":l, "date":d_str})
        except: continue
    return items

with t3:
    if st.button("Deep Scan"):
        with st.spinner("Reading..."):
            raw = get_feed()
            if raw and KEY:
                from openai import OpenAI
                cl = OpenAI(api_key=KEY)
                txt = "\n".join([f"{x['title']} ({x['date']}) - {x['link']}" for x in raw[:15]])
                p = "Analyze. JSON: [{'ticker':'TSLA', 'signal':'🟢', 'reason':'...', 'time':'2h ago', 'title':'...', 'link':'...'}]"
                try:
                    res = cl.chat.completions.create(model="gpt-4o-mini", messages=[{"role":"system","content":p},{"role":"user","content":txt}], response_format={"type":"json_object"})
                    st.session_state['news_results'] = json.loads(res.choices[0].message.content).get('articles', [])
                except: st.error("AI Error")
    
    for n in st.session_state['news_results']:
        st.markdown(f"**{n.get('ticker','')} {n.get('signal','')}** | {n.get('time','')} | [{n.get('title','')}]({n.get('link','')})")
        st.caption(n.get('reason',''))
        st.divider()

time.sleep(1)
if not st.session_state.get('stop_refresh'): st.rerun()
