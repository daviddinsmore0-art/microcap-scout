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

# --- 2. MEMORY & CRASH PROTECTION ---
# This block runs FIRST to prevent the KeyError seen in your screenshots
if 'initialized' not in st.session_state:
    st.session_state['initialized'] = True
    
    # Load URL Parameters or Defaults
    defaults = {
        'w_input': "SPY, BTC-USD, TD.TO, PLUG.CN, VTX.V",
        'a_tick_input': "SPY", 'a_price_input': 0.0,
        'a_on_input': False, 'flip_on_input': False,
        'keep_on_input': False, 'notify_input': False
    }
    qp = st.query_params
    for k in defaults:
        pk = k.replace('_input','')
        if pk in qp:
            val = qp[pk]
            if val.lower() in ['true','false']: defaults[k] = val.lower() == 'true'
            else:
                try: defaults[k] = float(val) if '.' in val and not any(x in val for x in ['TO','V','CN']) else val
                except: defaults[k] = val
    for k, v in defaults.items(): st.session_state[k] = v
    
    # Initialize ALL memory keys to stop crashes
    st.session_state.update({
        'news_results': [], 
        'alert_log': [], 
        'last_trends': {}, 
        'mem_ratings': {}, 
        'banner_msg': None, 
        'storm_cooldown': {}
    })

# --- 3. FUNCTIONS ---
def update_params():
    for k in ['w','at','ap','ao','fo','no','ko']:
        kn = f"{k if len(k)>2 else k+'_input'}"
        if kn in st.session_state: st.query_params[k] = str(st.session_state[kn]).lower()

def inject_wake_lock(enable):
    if enable: components.html("""<script>navigator.wakeLock.request('screen').catch(console.log);</script>""", height=0)

# --- 4. SIDEBAR (Restored v76 Features) ---
st.sidebar.header("⚡ Penny Pulse")
if "OPENAI_KEY" in st.secrets: KEY = st.secrets["OPENAI_KEY"]
else: KEY = st.sidebar.text_input("OpenAI Key", type="password") 

st.sidebar.text_input("Tickers", key="w_input", on_change=update_params)

# v76 Buttons
c1, c2 = st.sidebar.columns(2)
with c1: 
    if st.button("💾 Save"): update_params(); st.toast("Profile Saved!")
with c2: 
    if st.button("🔊 Test"): components.html("""<audio autoplay><source src="https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3"></audio>""", height=0)

# Portfolio Definition
PORT = {"HIVE": {"e": 3.19, "d": "Dec 01", "q": 50}, "BAER": {"e": 1.86, "d": "Jan 10", "q": 100}, "TX": {"e": 38.10, "d": "Nov 05", "q": 40}, "IMNN": {"e": 3.22, "d": "Aug 20", "q": 100}, "RERE": {"e": 5.31, "d": "Oct 12", "q": 100}}
ALL_T = list(set([x.strip().upper() for x in st.session_state.w_input.split(",") if x.strip()] + list(PORT.keys())))

st.sidebar.divider()
st.sidebar.subheader("🔔 Alerts")
curr = st.session_state.a_tick_input
idx = sorted(ALL_T).index(curr) if curr in sorted(ALL_T) else 0
st.sidebar.selectbox("Asset", sorted(ALL_T), index=idx, key="a_tick_input", on_change=update_params)
st.sidebar.number_input("Target ($)", step=0.5, key="a_price_input", on_change=update_params)
st.sidebar.toggle("Price Alert", key="a_on_input", on_change=update_params)
st.sidebar.toggle("Flip Alert", key="flip_on_input", on_change=update_params)
st.sidebar.toggle("Keep Screen On", key="keep_on_input", on_change=update_params)
inject_wake_lock(st.session_state.keep_on_input)

# --- 5. DATA ENGINE (v89 Accuracy + v76 Logic) ---
def get_rating_and_meta(s):
    # Caching logic
    clean_s = s.replace(".TO","").replace(".V","").replace(".CN","")
    if clean_s in st.session_state['mem_ratings']: return st.session_state['mem_ratings'][clean_s]
    try:
        tk = yf.Ticker(clean_s)
        inf = tk.info
        r = inf.get('recommendationKey', 'N/A').upper().replace('_',' ')
        r_col = "#00C805" if "BUY" in r else ("#FFC107" if "HOLD" in r else "#FF4B4B")
        if r == "N/A": r = "NONE"
        
        earn = "N/A"
        try:
            cal = tk.calendar
            if cal is not None:
                dt = cal.iloc[0,0] if hasattr(cal, 'iloc') else cal.get('Earnings Date', [None])[0]
                if dt: earn = dt.strftime('%b %d')
        except: pass
        
        res = (r, r_col, earn)
        st.session_state['mem_ratings'][clean_s] = res
        return res
    except: return ("NONE", "#888", "N/A")

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
        # CLEAN TSX FIX
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
        # Storm Tracker Logic (Restored)
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
            v = d['p']*shares
            pl = v-(cost*shares)
            st.caption(f"Net: ${v:,.0f} | P/L: ${pl:+,.0f}")
            
        cd = d['chart'].reset_index()
        cd.columns = ['Time','Price'] + list(cd.columns[2:])
        ch = alt.Chart(cd.tail(30)).mark_line(color=color).encode(x=alt.X('Time',axis=None), y=alt.Y('Price',scale=alt.Scale(zero=False),axis=None)).properties(height=50)
        st.altair_chart(ch, use_container_width=True)
        st.caption(f"RSI: {d['rsi']:.0f} | Vol: {d['vol']:.1f}x")
        st.divider()

with t1:
    cols = st.columns(3)
    W = [x.strip().upper() for x in st.session_state.w_input.split(",") if x.strip()]
    for i, t in enumerate(W):
        with cols[i%3]: draw_card(t)

with t2:
    cols = st.columns(3)
    for i, (t, inf) in enumerate(PORT.items()):
        with cols[i%3]: draw_card(t, inf['q'], inf['e'])

with t3:
    if st.button("Analyze Market Context"):
        if KEY:
            with st.spinner("Analyzing..."):
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

time.sleep(2)
st.rerun()
