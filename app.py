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

# --- 2. MEMORY ---
if 'initialized' not in st.session_state:
    st.session_state['initialized'] = True
    defaults = {
        'w_input': "SPY, BTC-USD, TD.TO, IVN.TO, PLUG.CN, VTX.V",
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
    st.session_state.update({'alert_log': [], 'last_trends': {}, 'mem_ratings': {}, 'mem_meta': {}, 'banner_msg': None, 'storm_cooldown': {}, 'spy_cache': None, 'spy_last_fetch': datetime.min})

# --- 3. FUNCTIONS ---
def update_params():
    for k in ['w','at','ap','ao','fo','no','ko']:
        kn = f"{k if len(k)>2 else k+'_input'}"
        if kn in st.session_state: st.query_params[k] = str(st.session_state[kn]).lower()

NAMES = {
    "TD.TO": "TD Bank", "TD": "TD Bank", "IVN.TO": "Ivanhoe", "IVN": "Ivanhoe",
    "BN.TO": "Brookfield", "BN": "Brookfield", "BTC-USD": "Bitcoin", 
    "SPY": "S&P 500", "^GSPTSE": "TSX Composite", "^IXIC": "Nasdaq", "^DJI": "Dow Jones"
}

def get_clean_name(t):
    if t in NAMES: return NAMES[t]
    return t.replace(".TO","").replace(".V","").replace(".CN","")

def inject_wake_lock(enable):
    if enable: components.html("""<script>navigator.wakeLock.request('screen').catch(console.log);</script>""", height=0)

# --- 4. SIDEBAR ---
st.sidebar.header("⚡ Pulse")
if "OPENAI_KEY" in st.secrets: KEY = st.secrets["OPENAI_KEY"]
else: KEY = st.sidebar.text_input("OpenAI Key", type="password") 

st.sidebar.text_input("Tickers", key="w_input", on_change=update_params)
st.sidebar.divider()
st.sidebar.subheader("🔔 Alerts")
ALL_T = list(set([x.strip().upper() for x in st.session_state.w_input.split(",") if x.strip()] + ["HIVE","BAER","TX","IMNN","RERE"]))
st.sidebar.selectbox("Asset", sorted(ALL_T), key="a_tick_input")
st.sidebar.number_input("Target ($)", step=0.5, key="a_price_input")
st.sidebar.toggle("Price Alert", key="a_on_input")
st.sidebar.toggle("Flip Alert", key="flip_on_input")
st.sidebar.toggle("Keep Screen On", key="keep_on_input")
inject_wake_lock(st.session_state.keep_on_input)

# --- 5. DATA LOGIC ---
def get_rating_and_meta(s):
    search_ticker = s
    if ".TO" in s: search_ticker = s.replace(".TO", "")
    if search_ticker in st.session_state['mem_ratings']: return st.session_state['mem_ratings'][search_ticker]
    try:
        tk = yf.Ticker(search_ticker)
        inf = tk.info
        r = inf.get('recommendationKey', 'N/A').upper().replace('_',' ')
        r_col = "#00C805" if "BUY" in r else ("#FFC107" if "HOLD" in r else "#FF4B4B")
        if r == "N/A": r = "NONE"
        sec = inf.get('sector', 'N/A')[:4].upper()
        earn = "N/A"
        cal = tk.calendar
        if cal is not None and not (isinstance(cal, list) and len(cal)==0):
            try:
                dt = cal.iloc[0,0] if hasattr(cal, 'iloc') else cal.get('Earnings Date', [None])[0]
                if dt: earn = dt.strftime('%b %d')
            except: pass
        res = (r, r_col, sec, earn)
        st.session_state['mem_ratings'][search_ticker] = res
        return res
    except: return ("NONE", "#888", "N/A", "N/A")

def get_data_accurate(s):
    try:
        tk = yf.Ticker(s)
        hd = tk.history(period="5d", interval="1d")
        if len(hd) < 2: return None
        
        is_today = hd.index[-1].date() == datetime.now().date()
        p_anchor = hd['Close'].iloc[-2] if is_today else hd['Close'].iloc[-1]
        p_prev = hd['Close'].iloc[-3] if is_today else hd['Close'].iloc[-2]
        d_static = ((p_anchor - p_prev) / p_prev) * 100
        
        # CLEAN TSX CHARTS
        use_prepost = not any(x in s for x in [".TO", ".V", ".CN"])
        h = tk.history(period="1d", interval="5m", prepost=use_prepost)
        if h.empty: h = tk.history(period="5d", interval="1h", prepost=use_prepost)
        p_live = h['Close'].iloc[-1]
        d_live = ((p_live - p_anchor) / p_anchor) * 100
        
        hm = tk.history(period="1mo")
        rsi = 50; trend = "NEUTRAL"; vol_ratio = 1.0
        if len(hm) > 14:
            diff = hm['Close'].diff(); u, d = diff.clip(lower=0), -1*diff.clip(upper=0)
            rsi = 100 - (100/(1 + (u.rolling(14).mean()/d.rolling(14).mean()).iloc[-1]))
            trend = "BULL" if (hm['Close'].ewm(span=12).mean() - hm['Close'].ewm(span=26).mean()).iloc[-1] > 0 else "BEAR"
            vol_ratio = hm['Volume'].iloc[-1] / hm['Volume'].mean() if hm['Volume'].mean() > 0 else 1.0

        dh, dl = h['High'].max(), h['Low'].min()
        rng_p = max(0, min(1, (p_live - dl) / (dh - dl))) * 100 if dh > dl else 50
        
        # INDICATORS
        v_tag = "⚡ Surge" if vol_ratio > 1.5 else ("🌊 Steady" if vol_ratio > 0.8 else "💤 Quiet")
        r_tag = "🔥 Hot" if rsi > 70 else ("❄️ Cold" if rsi < 30 else "⚖️ Calm")
        r_col = "#ff4b4b" if rsi > 70 or rsi < 30 else "#4caf50"
        
        rating, rating_col, sec, earn = get_rating_and_meta(s)

        bars = f"""
        <div style="font-size:11px;color:#666;margin-top:10px;"><b>Day Range</b></div>
        <div style="display:flex;align-items:center;font-size:10px;color:#888;"><span style="margin-right:4px;">L</span><div style="flex-grow:1;height:4px;background:#333;border-radius:2px;"><div style="width:{rng_p}%;height:100%;background:linear-gradient(90deg,#ff4b4b,#4caf50);"></div></div><span style="margin-left:4px;">H</span></div>
        <div style="font-size:11px;color:#666;margin-top:8px;"><b>Volume: {v_tag}</b> ({vol_ratio:.1f}x)</div>
        <div style="width:100%;height:6px;background:#333;border-radius:3px;"><div style="width:{min(100, vol_ratio*50)}%;height:100%;background:#2196F3;border-radius:3px;"></div></div>
        <div style="font-size:11px;color:#666;margin-top:8px;"><b>RSI: {r_tag}</b> ({rsi:.0f})</div>
        <div style="width:100%;height:6px;background:#333;border-radius:3px;"><div style="width:{rsi}%;height:100%;background:{r_col};border-radius:3px;"></div></div>
        """
        return {"p_anchor":p_anchor, "d_static":d_static, "p_live":p_live, "d_live":d_live, "rsi":rsi, "tr":trend, "chart":h, "rating":rating, "r_col":rating_col, "sec":sec, "earn":earn, "bars":bars}
    except: return None

# --- 6. UI HEADER (PRO VISUALS) ---
est = datetime.utcnow() - timedelta(hours=5)
status = "🔴 CLOSED"
hh, mm = est.hour, est.minute
if est.weekday() < 5:
    if 4 <= hh < 9 or (hh==9 and mm<30): status = "🟠 PRE-MARKET"
    elif (hh==9 and mm>=30) or (9 < hh < 16): status = "🟢 MARKET OPEN"
    elif 16 <= hh < 20: status = "🌙 POST-MARKET"

c1, c2 = st.columns([1,1])
with c1:
    st.title("⚡ Penny Pulse")
    st.caption(f"{status} | {est.strftime('%H:%M:%S EST')}")
with c2:
    # PRO FEATURE: Big Countdown Timer
    components.html("""<div style="font-family:'Helvetica';background:#0E1117;padding:5px;text-align:right;display:flex;justify-content:flex-end;align-items:center;height:100%;"><span style="color:#BBBBBB;font-weight:bold;font-size:14px;margin-right:5px;">Next Update: </span><span id="c" style="color:#FF4B4B;font-weight:900;font-size:24px;">--</span><span style="color:#BBBBBB;font-size:14px;margin-left:2px;"> s</span></div><script>setInterval(function(){document.getElementById("c").innerHTML=60-new Date().getSeconds();},1000);</script>""", height=60)

# PRO FEATURE: Marquee Scroller
@st.cache_data(ttl=60, show_spinner=False)
def get_marquee():
    txt = ""
    for t in ["SPY","^IXIC","^DJI","BTC-USD"]:
        d = get_data_accurate(t)
        if d:
            c, a = ("#4caf50","▲") if d['d_live']>=0 else ("#f44336","▼")
            txt += f"<span style='margin-right:30px;font-weight:900;font-size:22px;color:white;'>{NAMES.get(t,t)}: <span style='color:{c};'>${d['p_live']:,.2f} {a} {d['d_live']:.2f}%</span></span>"
    return txt

st.markdown(f"""<div style="background:#0E1117;padding:10px 0;border-top:2px solid #333;border-bottom:2px solid #333;"><marquee scrollamount="8" style="width:100%;">{get_marquee()*5}</marquee></div>""", unsafe_allow_html=True)

# --- 7. DASHBOARD ---
t1, t2, t3 = st.tabs(["🏠 Board", "🚀 My Picks", "📰 News"])

def draw_card(t):
    d = get_data_accurate(t)
    if d:
        name = get_clean_name(t)
        st.markdown(f"### {name} <span style='color:#777;font-size:14px;'>[{d['sec']}]</span>", unsafe_allow_html=True)
        st.metric("Prev Close", f"${d['p_anchor']:,.2f}", f"{d['d_static']:+.2f}%")
        st.markdown(f"<div style='margin-top:-15px;margin-bottom:10px;font-weight:bold;'>⚡ LIVE: ${d['p_live']:,.2f} <span style='color:{'#4caf50' if d['d_live']>=0 else '#ff4b4b'}'>({d['d_live']:+.2f}%)</span></div>", unsafe_allow_html=True)
        
        # BOLD UI
        st.markdown(f"""
        <div style='font-size:14px;line-height:1.6;'>
            <b>TREND:</b> <span style='color:{'#00C805' if d['tr']=='BULL' else '#FF4B4B'}'><b>{d['tr']}</b></span><br>
            <b>ANALYST RATING:</b> <span style='color:{d['r_col']}'><b>{d['rating']}</b></span><br>
            <b>EARNINGS:</b> 📅 <b>{d['earn']}</b>
        </div>
        """, unsafe_allow_html=True)
        
        c_df = pd.DataFrame({'T': d['chart'].index, 'V': ((d['chart']['Close']-d['p_anchor'])/d['p_anchor'])*100})
        ch = alt.Chart(c_df).mark_line(color="#4caf50" if d['d_live']>=0 else "#ff4b4b").encode(x=alt.X('T', axis=None), y=alt.Y('V', axis=None)).properties(height=60)
        st.altair_chart(ch, use_container_width=True)
        st.markdown(d['bars'], unsafe_allow_html=True)
        st.divider()
    else: st.warning(f"No Data: {t}")

with t1:
    cols = st.columns(3)
    W = [x.strip().upper() for x in st.session_state.w_input.split(",") if x.strip()]
    for i, t in enumerate(W):
        with cols[i%3]: draw_card(t)

# News Logic
with t3:
    if st.button("Deep Scan (AI)"):
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
    
    for n in st.session_state['news_results']:
        st.markdown(f"**{n.get('ticker','')} {n.get('signal','')}** | {n.get('time','')} | [{n.get('title','')}]({n.get('link','')})")
        st.caption(n.get('reason',''))
        st.divider()

# Heartbeat
time.sleep(2)
st.rerun()
