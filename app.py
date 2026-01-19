import streamlit as st, yfinance as yf, requests, time, xml.etree.ElementTree as ET
from datetime import datetime, timedelta
import email.utils
import streamlit.components.v1 as components
import pandas as pd
import altair as alt

try: st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="wide")
except: pass

# --- SESSION STATE ---
if 'news_results' not in st.session_state: st.session_state['news_results'] = []
if 'alert_triggered' not in st.session_state: st.session_state['alert_triggered'] = False

# --- PORTFOLIO ---
PORT = {
    "HIVE": {"e": 3.19, "d": "Dec. 01, 2024", "q": 1000},
    "BAER": {"e": 1.86, "d": "Jan. 10, 2025", "q": 500},
    "TX":   {"e": 38.10, "d": "Nov. 05, 2023", "q": 100},
    "IMNN": {"e": 3.22, "d": "Aug. 20, 2024", "q": 200},
    "RERE": {"e": 5.31, "d": "Oct. 12, 2024", "q": 300}
}

NAMES = {"TSLA":"Tesla","NVDA":"Nvidia","BTC-USD":"Bitcoin","AMD":"AMD","PLTR":"Palantir","AAPL":"Apple","SPY":"S&P 500","^IXIC":"Nasdaq","^DJI":"Dow Jones","GC=F":"Gold","TD.TO":"TD Bank","IVN.TO":"Ivanhoe","BN.TO":"Brookfield","JNJ":"J&J"}

# --- SIDEBAR ---
st.sidebar.header("⚡ Pulse")
if "OPENAI_KEY" in st.secrets: KEY = st.secrets["OPENAI_KEY"]
else: KEY = st.sidebar.text_input("OpenAI Key", type="password")

qp = st.query_params
w_str = qp.get("watchlist", "TD.TO, IVN.TO, BTC-USD, HIVE, BAER, TX, IMNN, RERE")
u_in = st.sidebar.text_input("Add Tickers", value=w_str)
if u_in != w_str: st.query_params["watchlist"] = u_in
WATCH = [x.strip().upper() for x in u_in.split(",")]

# --- HEADER & TIMER ---
c1, c2 = st.columns([2, 1])
with c1: st.title("⚡ Penny Pulse")
with c2:
    components.html("""
    <div style="background:#1e2127; padding:10px; border-radius:8px; text-align:center; border:1px solid #333; font-family:sans-serif;">
        <span style="color:#888; font-size:12px; font-weight:bold;">NEXT PULSE</span><br>
        <span id="timer" style="color:#FF4B4B; font-size:24px; font-weight:900;">60</span><span style="color:#FF4B4B; font-size:14px;">s</span>
    </div>
    <script>
        let s = 60;
        setInterval(() => {
            s--; if(s < 0) s = 60;
            document.getElementById('timer').innerText = s;
        }, 1000);
    </script>
    """, height=85)

# --- ROBUST DATA FETCH ---
@st.cache_data(ttl=60, show_spinner=False)
def get_data_cached(s):
    try:
        tk = yf.Ticker(s)
        h = tk.history(period="5d", interval="1h")
        if h.empty: return None
        
        p = h['Close'].iloc[-1]
        pv = h['Close'].iloc[-2]
        dp = ((p-pv)/pv)*100
        
        # Simple Technicals
        rsi, raw_trend = 50, "NEUTRAL"
        if len(h) >= 14:
            diff = h['Close'].diff()
            g = diff.where(diff > 0, 0).rolling(14).mean()
            l = (-diff.where(diff < 0, 0)).rolling(14).mean()
            rsi = (100 - (100 / (1 + (g / l)))).iloc[-1]
            macd = h['Close'].ewm(span(12)).mean() - h['Close'].ewm(span(26)).mean()
            raw_trend = "BULL" if macd.iloc[-1] > 0 else "BEAR"
        
        return {"p":p, "d":dp, "rsi":rsi, "trend":raw_trend, "chart":h['Close']}
    except: return None

# --- FIXED TICKER TAPE ---
ti = []
for t in ["SPY", "^IXIC", "BTC-USD"]:
    d = get_data_cached(t)
    if d:
        color = "green" if d['d'] >= 0 else "red"
        ti.append(f"{t}: ${d['p']:,.2f} ({d['d']:.2f}%)")
tape_text = "  |  ".join(ti)
st.info(f"📊 Market: {tape_text}") # Using standard component to avoid TypeError

# --- CARDS ---
def render_card(t, inf=None):
    d = get_data_cached(t)
    if not d:
        st.warning(f"⚠️ {t}: Syncing...")
        return
    st.subheader(NAMES.get(t, t))
    if inf: st.caption(f"{inf['q']} Shares @ ${inf['e']}")
    st.metric("Price", f"${d['p']:,.2f}", f"{d['d']:.2f}%")
    st.write(f"Trend: **{d['trend']}** | RSI: **{d['rsi']:.0f}**")
    with st.expander("Chart"): st.line_chart(d['chart'])
    st.divider()

t1, t2, t3 = st.tabs(["Dashboard", "My Picks", "News"])
with t1:
    cols = st.columns(3)
    for i, t in enumerate(WATCH):
        with cols[i%3]: render_card(t)
with t2:
    for t, inf in PORT.items(): render_card(t, inf)
with t3:
    if st.button("Generate Report"): st.write("Scanning fresh news...")

time.sleep(60)
st.rerun()
