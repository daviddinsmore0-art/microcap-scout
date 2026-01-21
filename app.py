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
        'keep_on_input': False, 'notify_input': False, 'base_url_input': ""
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
    st.session_state.update({'news_results': [], 'alert_log': [], 'last_trends': {}, 'mem_ratings': {}, 'mem_meta': {}, 'banner_msg': None, 'storm_cooldown': {}, 'spy_cache': None, 'spy_last_fetch': datetime.min})

# --- 3. FUNCTIONS ---
def update_params():
    for k in ['w','at','ap','ao','fo','no','ko']:
        key_name = f"{k if len(k)>2 else k+'_input'}"
        if key_name in st.session_state:
            st.query_params[k] = str(st.session_state[key_name]).lower()

def load_profile_callback():
    up = st.session_state.get('uploader_key')
    if up:
        try:
            d = json.load(up)
            m = {'w':'w_input', 'at':'a_tick_input', 'ap':'a_price_input', 'ao':'a_on_input', 'fo':'flip_on_input'}
            for j,s in m.items(): 
                if j in d: st.session_state[s] = d[j]
            st.toast("Restored!", icon="✅")
        except: st.error("File Error")

# Friendly Names Mapping
NAMES = {
    "TD.TO": "TD Bank", "TD": "TD Bank",
    "IVN.TO": "Ivanhoe", "IVN": "Ivanhoe",
    "BN.TO": "Brookfield", "BN": "Brookfield",
    "BTC-USD": "Bitcoin", "^GSPTSE": "TSX Composite",
    "SPY": "S&P 500", "^IXIC": "Nasdaq", "^DJI": "Dow Jones"
}

def get_display_name(ticker):
    if ticker in NAMES: return NAMES[ticker]
    # Strip Canadian suffixes for display
    clean = ticker.replace(".TO", "").replace(".V", "").replace(".CN", "")
    return clean

# --- 4. SIDEBAR ---
st.sidebar.header("⚡ Pulse")
KEY = st.secrets["OPENAI_KEY"] if "OPENAI_KEY" in st.secrets else st.sidebar.text_input("OpenAI Key", type="password") 
st.sidebar.text_input("Tickers", key="w_input", on_change=update_params)

st.sidebar.divider()
st.sidebar.subheader("🔔 Alerts")
ALL_T = list(set([x.strip().upper() for x in st.session_state.w_input.split(",") if x.strip()] + ["HIVE","BAER","TX","IMNN","RERE"]))
st.sidebar.selectbox("Asset", sorted(ALL_T), key="a_tick_input")
st.sidebar.number_input("Target ($)", step=0.5, key="a_price_input")
st.sidebar.toggle("Price Alert", key="a_on_input")
st.sidebar.toggle("Flip Alert", key="flip_on_input")
st.sidebar.toggle("Keep Screen On", key="keep_on_input")
st.sidebar.checkbox("Desktop Notify", key="notify_input")

# --- 5. DATA LOGIC ---
def get_data_accurate(s):
    if not s: return None
    try:
        tk = yf.Ticker(s)
        hd = tk.history(period="5d", interval="1d")
        if len(hd) < 2: return None
        
        is_today = hd.index[-1].date() == datetime.now().date()
        p_anchor = hd['Close'].iloc[-2] if is_today else hd['Close'].iloc[-1]
        p_prev = hd['Close'].iloc[-3] if is_today else hd['Close'].iloc[-2]
        d_static = ((p_anchor - p_prev) / p_prev) * 100
        
        h = tk.history(period="1d", interval="5m", prepost=True)
        if h.empty: h = tk.history(period="5d", interval="1h", prepost=True)
        p_live = h['Close'].iloc[-1]
        d_live = ((p_live - p_anchor) / p_anchor) * 100
        
        hm = tk.history(period="1mo")
        rsi = 50; trend = "NEUTRAL"; ai_bias = "NEUTRAL"; ai_col = "#888"
        if len(hm) > 14:
            diff = hm['Close'].diff(); u, d = diff.clip(lower=0), -1*diff.clip(upper=0)
            rsi = 100 - (100/(1 + (u.rolling(14).mean()/d.rolling(14).mean()).iloc[-1]))
            m = hm['Close'].ewm(span=12).mean() - hm['Close'].ewm(span=26).mean()
            trend = "BULL" if m.iloc[-1] > 0 else "BEAR"
            ai_bias = f"{trend}ISH BIAS"; ai_col = "#00C805" if trend == "BULL" else "#FF4B4B"

        dh, dl = h['High'].max(), h['Low'].min()
        rng_p = max(0, min(1, (p_live - dl) / (dh - dl))) * 100 if dh > dl else 50
        
        bars = f"""
        <div style="font-size:11px;color:#666;margin-top:10px;">Day Range</div>
        <div style="display:flex;align-items:center;font-size:10px;color:#888;"><span style="margin-right:4px;">L</span><div style="flex-grow:1;height:4px;background:#333;border-radius:2px;"><div style="width:{rng_p}%;height:100%;background:linear-gradient(90deg,#ff4b4b,#4caf50);"></div></div><span style="margin-left:4px;">H</span></div>
        <div style="font-size:11px;color:#666;margin-top:8px;">RSI: <b>{rsi:.0f}</b></div>
        <div style="width:100%;height:6px;background:#333;border-radius:3px;"><div style="width:{rsi}%;height:100%;background:{'#ff4b4b' if rsi>70 or rsi<30 else '#4caf50'};border-radius:3px;"></div></div>
        """
        return {"p_anchor":p_anchor, "d_static":d_static, "p_live":p_live, "d_live":d_live, "rsi":rsi, "tr":trend, "chart":h, "ai":ai_bias, "ai_c":ai_col, "bars":bars}
    except: return None

# --- 6. UI HEADER ---
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
    st.caption(f"{status} | {est.strftime('%H:%M EST')}")
with c2:
    components.html(f"""<div style="font-family:sans-serif;background:#0E1117;padding:10px;text-align:center;border-radius:5px;border:1px solid #333;color:#FF4B4B;font-weight:bold;font-size:20px;">Next Update: <span id="c">--</span>s</div><script>setInterval(()=>{{document.getElementById("c").innerHTML=60-new Date().getSeconds()}},1000);</script>""", height=70)

# --- 7. DASHBOARD ---
t1, t2, t3 = st.tabs(["🏠 Dashboard", "🚀 My Picks", "📰 News"])

def draw_card(t):
    d = get_data_accurate(t)
    if d:
        display_name = get_display_name(t)
        st.markdown(f"### {display_name}")
        st.caption("Prev Close")
        st.metric("", f"${d['p_anchor']:,.2f}", f"{d['d_static']:+.2f}%")
        st.markdown(f"<div style='margin-top:-15px;margin-bottom:10px;font-weight:bold;'>⚡ LIVE: ${d['p_live']:,.2f} <span style='color:{'#4caf50' if d['d_live']>=0 else '#ff4b4b'}'>({d['d_live']:+.2f}%)</span></div>", unsafe_allow_html=True)
        st.markdown(f"**⚙️ AI:** <span style='color:{d['ai_c']}'>{d['ai']}</span>", unsafe_allow_html=True)
        
        c_df = pd.DataFrame({'Time': d['chart'].index, 'Val': ((d['chart']['Close']-d['p_anchor'])/d['p_anchor'])*100})
        ch = alt.Chart(c_df).mark_line(color="#4caf50" if d['d_live']>=0 else "#ff4b4b").encode(x=alt.X('Time', axis=None), y=alt.Y('Val', axis=None)).properties(height=60)
        st.altair_chart(ch, use_container_width=True)
        st.markdown(d['bars'], unsafe_allow_html=True)
        st.divider()
    else: st.warning(f"No Data: {t}")

with t1:
    cols = st.columns(3)
    WATCH_LIST = [x.strip().upper() for x in st.session_state.w_input.split(",") if x.strip()]
    for i, t in enumerate(WATCH_LIST):
        with cols[i%3]: draw_card(t)

time.sleep(1)
st.rerun()
