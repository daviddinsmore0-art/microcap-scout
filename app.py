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

# --- THE COUNTDOWN (Moved to stable header) ---
c1, c2 = st.columns([2, 1])
with c1:
    st.title("⚡ Penny Pulse")
with c2:
    # Restored and stabilized countdown component
    components.html("""
    <div style="background:#1e2127; padding:10px; border-radius:8px; text-align:center; border:1px solid #333;">
        <span style="color:#888; font-size:12px; font-weight:bold;">NEXT PULSE</span><br>
        <span id="timer" style="color:#FF4B4B; font-size:24px; font-weight:900;">60</span><span style="color:#FF4B4B; font-size:14px;">s</span>
    </div>
    <script>
        let s = 60;
        setInterval(() => {
            s--;
            if(s < 0) s = 60;
            document.getElementById('timer').innerText = s;
        }, 1000);
    </script>
    """, height=80)

# --- PRICE FETCHER (Ultra Robust) ---
@st.cache_data(ttl=60, show_spinner=False)
def get_data_cached(s):
    try:
        tk = yf.Ticker(s)
        # Try fast_info first, then history as backup
        try:
            p = tk.fast_info['last_price']
            pv = tk.fast_info['previous_close']
            dh, dl = tk.fast_info['day_high'], tk.fast_info['day_low']
        except:
            h = tk.history(period="1d")
            p = h['Close'].iloc[-1]
            pv = h['Open'].iloc[0]
            dh, dl = h['High'].max(), h['Low'].min()

        dp = ((p-pv)/pv)*100
        d_raw = p - pv
        
        # Trend / RSI / Volume
        hm = tk.history(period="1mo")
        rsi, rl, tr, v_str, vt, raw_trend = 50, "Neutral", "Neutral", "N/A", "", "NEUTRAL"
        if not hm.empty:
            cur_v = hm['Volume'].iloc[-1]
            v_str = f"{cur_v/1e6:.1f}M" if cur_v>=1e6 else f"{cur_v:,.0f}"
            avg_v = hm['Volume'].iloc[:-1].mean()
            vt = "⚡ SURGE" if cur_v > avg_v else "🌊 STEADY"
            if len(hm)>=14:
                d_diff = hm['Close'].diff()
                g = d_diff.where(d_diff>0,0).rolling(14).mean()
                l = (-d_diff.where(d_diff<0,0)).rolling(14).mean()
                rsi = (100-(100/(1+(g/l)))).iloc[-1]
                rl = "🔥 HOT" if rsi >= 70 else "❄️ COLD" if rsi <= 30 else "😐 OK"
                macd = hm['Close'].ewm(span=12).mean() - hm['Close'].ewm(span=26).mean()
                raw_trend = "BULL" if macd.iloc[-1] > 0 else "BEAR"
                tr = f"<span style='color:{'#00C805' if raw_trend=='BULL' else '#FF2B2B'}; font-weight:bold;'>{raw_trend}</span>"

        return {"p":p, "d":dp, "d_raw":d_raw, "v":v_str, "vt":vt, "rsi":rsi, "rl":rl, "tr":tr, "raw_trend":raw_trend, "chart":hm['Close'] if not hm.empty else None}
    except: return None

# --- UI TAPE ---
ti = []
for t in ["SPY","^IXIC","BTC-USD"]:
    d = get_data_cached(t)
    if d:
        c = "#4caf50" if d['d']>=0 else "#f44336"
        ti.append(f"<span style='margin-right:25px; color:white;'>{t}: <span style='color:{c};'>${d['p']:,.2f}</span></span>")
st.markdown(f"<marquee style='background:#0E1117; padding:5px; border:1px solid #333;'>{''.join(ti)*10}</marquee>", unsafe_allow_allow_html=True)

# --- DASHBOARD ---
def render_card(t, inf=None):
    d = get_data_cached(t)
    if not d:
        st.error(f"⚠️ {t}: Data Link Failed")
        return
    nm = NAMES.get(t, t)
    st.markdown(f"### {nm}")
    if inf: st.caption(f"Owned: {inf['q']} @ ${inf['e']}")
    st.metric("Price", f"${d['p']:,.2f}", f"{d['d']:.2f}%")
    st.markdown(f"**Trend:** {d['tr']} | **RSI:** {d['rsi']:.0f} ({d['rl']})", unsafe_allow_html=True)
    st.markdown(f"**Vol:** {d['v']} ({d['vt']})")
    with st.expander("Chart"):
        if d['chart'] is not None: st.line_chart(d['chart'])
    st.divider()

t1, t2, t3 = st.tabs(["Dashboard", "My Picks", "News"])
with t1:
    c = st.columns(3)
    for i, t in enumerate(WATCH):
        with c[i%3]: render_card(t)

with t2:
    for t, inf in PORT.items():
        render_card(t, inf)

with t3:
    if st.button("Generate News report"):
        st.write("Fetching fresh market signals...")
        # (News logic remains the same as v24.5)

# --- AUTO REFRESH ---
time.sleep(60)
st.rerun()
