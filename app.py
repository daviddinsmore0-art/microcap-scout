import streamlit as st, yfinance as yf, requests, time, xml.etree.ElementTree as ET
from datetime import datetime, timedelta
import email.utils
import streamlit.components.v1 as components

# --- APP SETUP ---
try: st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="wide")
except: pass

# Permanent Memory for the session
if 'price_cache' not in st.session_state: st.session_state['price_cache'] = {}
if 'news_data' not in st.session_state: st.session_state['news_data'] = []

# --- PORTFOLIO ---
PORT = {"HIVE": {"e": 3.19, "q": 1000}, "BAER": {"e": 1.86, "q": 500}, "TX": {"e": 38.10, "q": 100}, "IMNN": {"e": 3.22, "q": 200}, "RERE": {"e": 5.31, "q": 300}}
NAMES = {"TSLA":"Tesla","NVDA":"Nvidia","BTC-USD":"Bitcoin","AMD":"AMD","PLTR":"Palantir","AAPL":"Apple","SPY":"S&P 500","^IXIC":"Nasdaq","^DJI":"Dow Jones","GC=F":"Gold","TD.TO":"TD Bank","IVN.TO":"Ivanhoe","BN.TO":"Brookfield"}

# --- SIDEBAR ---
st.sidebar.header("⚡ Pulse Settings")
if "OPENAI_KEY" in st.secrets: KEY = st.secrets["OPENAI_KEY"]
else: KEY = st.sidebar.text_input("OpenAI Key", type="password")

qp = st.query_params
w_str = qp.get("watchlist", "TD.TO, IVN.TO, BTC-USD, HIVE, BAER, TX, IMNN, RERE")
u_in = st.sidebar.text_input("Watchlist", value=w_str)
WATCH = [x.strip().upper() for x in u_in.split(",")]

# --- HEADER ---
c1, c2 = st.columns([3, 1])
with c1: st.title("⚡ Penny Pulse")
with c2:
    components.html("""<div style="background:#1e2127; padding:8px; border-radius:8px; text-align:center; border:1px solid #444; font-family:sans-serif;"><span style="color:#888; font-size:11px; font-weight:bold;">NEXT REFRESH</span><br><span id="timer" style="color:#FF4B4B; font-size:22px; font-weight:900;">60</span><span style="color:#FF4B4B; font-size:12px;">s</span></div><script>let s=60; setInterval(()=>{s--; if(s<0)s=60; document.getElementById('timer').innerText=s;},1000);</script>""", height=75)

# --- THE "FAIL-SAFE" ENGINE ---
def get_safe_data(s):
    try:
        # Try fresh pull (using history only to avoid ValueError)
        tk = yf.Ticker(s)
        h = tk.history(period="2d", interval="1h")
        if not h.empty and len(h) >= 2:
            p = h['Close'].iloc[-1]
            pv = h['Close'].iloc[-2]
            dp = ((p-pv)/pv)*100
            # Update Memory Bank
            st.session_state['price_cache'][s] = {"p": p, "d": dp, "chart": h['Close']}
            return st.session_state['price_cache'][s]
    except: pass
    
    # Return last good data if Yahoo is blocking us
    return st.session_state['price_cache'].get(s, None)

# --- MARKET BAR ---
tape = []
for t in ["SPY", "^IXIC", "BTC-USD"]:
    d = get_safe_data(t)
    if d:
        c = "#00ff00" if d['d'] >= 0 else "#ff4b4b"
        tape.append(f"{t}: <span style='color:{c}; font-weight:bold;'>${d['p']:,.2f}</span>")
if tape:
    st.markdown(f"<div style='background:#1e2127; padding:12px; border:1px solid #333; text-align:center; border-radius:5px;'>{' | '.join(tape)}</div>", unsafe_allow_html=True)

# --- CARDS ---
def render_card(t, inf=None):
    d = get_safe_data(t)
    if not d:
        st.info(f"⏳ {t}: Waiting for Yahoo signal...")
        return
    with st.container():
        st.subheader(NAMES.get(t, t))
        if inf: st.caption(f"Owned: {inf['q']} Shares @ ${inf['e']}")
        st.metric("Price", f"${d['p']:,.2f}", f"{d['d']:.2f}%")
        with st.expander("📉 Quick Chart"):
            st.line_chart(d['chart'])
    st.divider()

# --- TABS ---
t1, t2, t3 = st.tabs(["🏠 Dashboard", "🚀 My Picks", "📰 Market News"])
with t1:
    cols = st.columns(3)
    for i, t in enumerate(WATCH):
        with cols[i%3]: render_card(t)
with t2:
    for t, inf in PORT.items(): render_card(t, inf)
with t3:
    if st.button("Generate Fresh Report"):
        st.info("AI scanning headlines...")

# --- AUTO-REFRESH ---
time.sleep(60)
st.rerun()
