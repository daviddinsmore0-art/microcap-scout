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

# --- 2. MEMORY & PERSISTENCE ---
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
    
    # Check URL
    qp = st.query_params
    if 'w' in qp: defaults['w_input'] = qp['w']
    if 'at' in qp: defaults['a_tick_input'] = qp['at']
    if 'ap' in qp: defaults['a_price_input'] = float(qp['ap'])
    if 'ao' in qp: defaults['a_on_input'] = (qp['ao'].lower() == 'true')
    if 'fo' in qp: defaults['flip_on_input'] = (qp['fo'].lower() == 'true')
    
    for k, v in defaults.items():
        st.session_state[k] = v
        
    # Internal
    st.session_state['news_results'] = []
    st.session_state['alert_log'] = []
    st.session_state['last_trends'] = {}
    st.session_state['mem_ratings'] = {}
    st.session_state['mem_meta'] = {}
    st.session_state['banner_msg'] = None
    st.session_state['storm_cooldown'] = {}
    st.session_state['spy_cache'] = None
    st.session_state['spy_last_fetch'] = datetime.min

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
    const KEY="penny_pulse_v78"; const d={config_json}; const s=localStorage.getItem(KEY);
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
NAMES = {"TSLA":"Tesla", "NVDA":"Nvidia", "BTC-USD":"Bitcoin", "AMD":"AMD", "PLTR":"Palantir", "AAPL":"Apple", "SPY":"S&P 500", "^IXIC":"Nasdaq", "^DJI":"Dow Jones", "GC=F":"Gold", "TD.TO":"TD Bank", "IVN.TO":"Ivanhoe", "BN.TO":"Brookfield", "JNJ":"J&J", "^GSPTSE": "TSX"} 
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

sync_js(json.dumps(export))
inject_wake_lock(keep_on)

# --- 5. LOGIC & DATA FETCHING ---
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

# Helpers for Rich UI
def get_meta(s):
    if s in st.session_state['mem_meta']: return st.session_state['mem_meta'][s]
    try:
        tk = yf.Ticker(s)
        sec = tk.info.get('sector', 'N/A')
        # Map or truncate sector
        sec_code = sec[:4].upper() if sec != 'N/A' else ""
        
        # Earnings
        earn_html = "N/A"
        cal = tk.calendar
        dates = []
        if isinstance(cal, dict) and 'Earnings Date' in cal: dates = cal['Earnings Date']
        elif hasattr(cal, 'iloc') and not cal.empty: dates = [cal.iloc[0,0]]
        
        if len(dates) > 0:
            nxt = dates[0]
            if hasattr(nxt, "date"): nxt = nxt.date()
            days = (nxt - datetime.now().date()).days
            if 0 <= days <= 7: earn_html = f"⚠️ {days}d"
            elif days > 0: earn_html = f"📅 {nxt.strftime('%b %d')}"
            
        res = (sec_code, earn_html)
        st.session_state['mem_meta'][s] = res
        return res
    except: return "", "N/A"

def get_rating(s):
    if s in st.session_state['mem_ratings']: return st.session_state['mem_ratings'][s]
    try:
        r = yf.Ticker(s).info.get('recommendationKey', 'none').upper().replace('_',' ')
        # Add emoji
        if "STRONG BUY" in r: r = "🌟 STRONG BUY"
        elif "BUY" in r: r = "✅ BUY"
        elif "HOLD" in r: r = "✋ HOLD"
        elif "SELL" in r: r = "🔻 SELL"
        
        col = "#00C805" if "BUY" in r else ("#FFC107" if "HOLD" in r else "#FF4B4B")
        res = (r, col)
        st.session_state['mem_ratings'][s] = res
        return res
    except: return "N/A", "#888"

# SPY Benchmark
def get_spy():
    now = datetime.now()
    if st.session_state['spy_cache'] is not None:
        if (now - st.session_state['spy_last_fetch']).seconds < 60: return st.session_state['spy_cache']
    try:
        s = yf.Ticker("SPY").history(period="1d", interval="5m", prepost=True)
        if not s.empty:
            st.session_state['spy_cache'] = s[['Close']]
            st.session_state['spy_last_fetch'] = now
            return s[['Close']]
    except: pass
    return None

@st.cache_data(ttl=60, show_spinner=False)
def get_data_rich(s):
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
        d_pct = ((p-pv)/pv)*100
        
        # --- FIX: Duplicate Column Protection ---
        chart_data = h[['Close']].copy()
        chart_data.index.name = 'Time' # Rename index to be safe
        # ----------------------------------------
        
        hm = tk.history(period="1mo")
        rsi, trend, tr_html = 50, "NEUTRAL", "NEUTRAL"
        vol_ratio = 1.0
        golden_cross = ""
        
        if len(hm)>14:
            d = hm['Close'].diff()
            u, dw = d.clip(lower=0), -1*d.clip(upper=0)
            rsi = 100 - (100/(1 + (u.rolling(14).mean()/dw.rolling(14).mean()).iloc[-1]))
            
            m12 = hm['Close'].ewm(span=12).mean()
            m26 = hm['Close'].ewm(span=26).mean()
            mac = m12 - m26
            if mac.iloc[-1] > 0: 
                trend = "BULL"
                tr_html = "<span style='color:#00C805;font-weight:bold'>BULL</span>"
            else: 
                trend = "BEAR"
                tr_html = "<span style='color:#FF4B4B;font-weight:bold'>BEAR</span>"
                
            v = hm['Volume'].iloc[-1]; a = hm['Volume'].mean()
            if a > 0: vol_ratio = v/a
            
            # Golden Cross Check (Approx)
            if len(hm) > 200:
                ma50 = hm['Close'].rolling(50).mean().iloc[-1]
                ma200 = hm['Close'].rolling(200).mean().iloc[-1]
                if ma50 > ma200: golden_cross = " <span style='background:#FFD700;color:black;padding:1px 4px;border-radius:3px;font-size:10px;font-weight:bold'>🌟 GOLDEN CROSS</span>"

        return {"p":p, "d":d_pct, "rsi":rsi, "tr":trend, "tr_h":tr_html, "gc":golden_cross, "chart":chart_data, "vr":vol_ratio}
    except: return None

# Price Alert
if a_on:
    d = get_data_rich(a_tick)
    if d and d['p'] >= a_price and not st.session_state['alert_triggered']:
        log_alert(f"{a_tick} hit ${a_price:,.2f}!", "Price Alert")
        st.session_state['alert_triggered'] = True

# --- 6. UI: HEADER & MARQUEE ---
if st.session_state['banner_msg']:
    st.markdown(f"<div style='background:#900;color:white;padding:10px;text-align:center;font-weight:bold;position:fixed;top:0;left:0;width:100%;z-index:99;'>{st.session_state['banner_msg']}</div>", unsafe_allow_html=True)
    if st.button("Dismiss"): st.session_state['banner_msg'] = None; st.rerun()

est = datetime.utcnow() - timedelta(hours=5)
c1, c2 = st.columns([1,1])
with c1:
    st.title("⚡ Penny Pulse")
    st.caption(f"Last Updated: {est.strftime('%H:%M:%S EST')}")
with c2:
    components.html("""<div style="font-family:'Helvetica';background:#0E1117;padding:5px;text-align:center;display:flex;justify-content:center;align-items:center;height:100%;"><span style="color:#BBBBBB;font-weight:bold;font-size:14px;margin-right:5px;">Next Update: </span><span id="c" style="color:#FF4B4B;font-weight:900;font-size:18px;">--</span><span style="color:#BBBBBB;font-size:14px;margin-left:2px;"> s</span></div><script>setInterval(function(){document.getElementById("c").innerHTML=60-new Date().getSeconds();},1000);</script>""", height=60)

# Scroller
@st.cache_data(ttl=60, show_spinner=False)
def get_marquee():
    txt = ""
    for t in ["SPY","^IXIC","^DJI","BTC-USD"]:
        d = get_data_rich(t)
        if d:
            c, a = ("#4caf50","▲") if d['d']>=0 else ("#f44336","▼")
            txt += f"<span style='margin-right:30px;font-weight:900;font-size:22px;color:white;'>{NAMES.get(t,t)}: <span style='color:{c};'>${d['p']:,.2f} {a} {d['d']:.2f}%</span></span>"
    return txt

st.markdown(f"""<div style="background:#0E1117;padding:10px 0;border-top:2px solid #333;border-bottom:2px solid #333;"><marquee scrollamount="6" style="width:100%;">{get_marquee()*5}</marquee></div>""", unsafe_allow_html=True)

# --- 7. DASHBOARD (PRO UI RESTORED) ---
def render_card(t, inf=None):
    d = get_data_rich(t)
    spy = get_spy()
    
    if d:
        check_flip(t, d['tr'], flip_on)
        
        # UI Elements
        rt, rc = get_rating(t)
        sec, earn = get_meta(t)
        nm = NAMES.get(t, t)
        if t.endswith(".TO"): nm += " (TSX)"
        elif t.endswith(".V"): nm += " (TSXV)"
        elif t.endswith(".CN"): nm += " (CSE)"
        
        u = f"https://finance.yahoo.com/quote/{t}"
        sec_tag = f" <span style='color:#777;font-size:14px;'>[{sec}]</span>" if sec else ""
        
        # Header
        st.markdown(f"<h3 style='margin:0;padding:0;'><a href='{u}' target='_blank' style='text-decoration:none;color:inherit'>{nm}</a>{sec_tag}</h3>", unsafe_allow_html=True)
        
        # Metrics
        if inf:
            v = d['p']*inf['q']
            pl = v-(inf['e']*inf['q'])
            st.caption(f"{inf['q']} Sh @ ${inf['e']} | P/L: ${pl:+,.0f}")
            st.metric("Price", f"${d['p']:,.2f}", f"{d['d']:.2f}%")
        else:
            st.metric("Price", f"${d['p']:,.2f}", f"{d['d']:.2f}%")
            
        # Rich Metadata
        st.markdown(f"""
        <div style='font-size:14px;line-height:1.8;margin-bottom:10px;color:#444;'>
            <div><b style='color:black;margin-right:8px;'>TREND:</b> {d['tr_h']}{d['gc']}</div>
            <div><b style='color:black;margin-right:8px;'>RATING:</b> <span style='color:{rc};font-weight:bold;'>{rt}</span></div>
            <div><b style='color:black;margin-right:8px;'>EARNINGS:</b> {earn}</div>
        </div>
        """, unsafe_allow_html=True)
        
        # Chart (Intraday + SPY)
        st.markdown("<div style='font-size:11px;font-weight:bold;color:#555;margin-bottom:2px;'>INTRADAY vs SPY (Orange/Dotted)</div>", unsafe_allow_html=True)
        
        # Prepare Data
        c_df = d['chart'].reset_index()
        # Normalize
        start_p = c_df['Close'].iloc[0]
        c_df['Stock'] = ((c_df['Close'] - start_p)/start_p)*100
        
        # Add SPY if available
        has_spy = False
        if spy is not None:
            try:
                # Align indices roughly
                spy_aligned = spy.reindex(d['chart'].index, method='nearest', tolerance=timedelta(minutes=10))
                spy_vals = spy_aligned['Close']
                if not spy_vals.isna().all():
                    s_start = spy_vals.dropna().iloc[0]
                    c_df['SPY'] = ((spy_vals.values - s_start)/s_start)*100
                    has_spy = True
            except: pass
            
        # Plot
        base = alt.Chart(c_df).encode(x=alt.X('Time', axis=None))
        l1 = base.mark_line(color="#4caf50" if d['d']>=0 else "#ff4b4b").encode(y=alt.Y('Stock', axis=None))
        final = l1
        if has_spy:
            l2 = base.mark_line(color='orange', strokeDash=[2,2]).encode(y='SPY')
            final = l1 + l2
            
        st.altair_chart(final.properties(height=50, width='container'), use_container_width=True)
        st.divider()
    else: st.warning(f"{t}: No Data")

t1, t2, t3 = st.tabs(["🏠 Dashboard", "🚀 My Picks", "📰 News"])
with t1:
    cols = st.columns(3)
    for i, t in enumerate(WATCH):
        with cols[i%3]: render_card(t)
with t2:
    cols = st.columns(3)
    for i, (t, inf) in enumerate(PORT.items()):
        with cols[i%3]: render_card(t, inf)

# --- 8. NEWS (Restored) ---
@st.cache_data(ttl=300)
def get_feed():
    MY_FEEDS = ["https://finance.yahoo.com/news/rssindex", "https://www.cnbc.com/id/10000664/device/rss/rss.html"]
    MY_LINKS = [] 
    items = []
    for l in MY_LINKS: items.append({"title":"Manual Link", "link":l, "date":"Now"})
    head = {"User-Agent":"Mozilla/5.0"}
    for u in MY_FEEDS:
        try:
            r = requests.get(u, headers=head, timeout=5)
            root = ET.fromstring(r.content)
            for i in root.findall('.//item')[:10]:
                l = i.find('link').text
                if not l: l = i.find('guid').text
                items.append({"title":i.find('title').text, "link":l, "date":""})
        except: continue
    return items

with t3:
    if st.button("Deep Scan (AI)"):
        with st.spinner("Reading..."):
            raw = get_feed()
            if raw and KEY:
                from openai import OpenAI
                cl = OpenAI(api_key=KEY)
                txt = "\n".join([f"{x['title']} - {x['link']}" for x in raw[:15]])
                p = "Analyze financial news. JSON: [{'ticker':'TSLA', 'signal':'🟢', 'reason':'...', 'time':'2h ago', 'title':'...', 'link':'...'}]"
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
