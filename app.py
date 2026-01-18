import streamlit as st, yfinance as yf, requests, time, xml.etree.ElementTree as ET
from datetime import datetime
import streamlit.components.v1 as components

try: st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="wide")
except: pass

# --- SESSION STATE INITIALIZATION ---
if 'news_results' not in st.session_state: st.session_state['news_results'] = []
if 'alert_triggered' not in st.session_state: st.session_state['alert_triggered'] = False
if 'last_trends' not in st.session_state: st.session_state['last_trends'] = {}

# Initialize Alert Persistence
if 'saved_a_tick' not in st.session_state: st.session_state['saved_a_tick'] = "SPY"
if 'saved_a_price' not in st.session_state: st.session_state['saved_a_price'] = 0.0
if 'saved_a_on' not in st.session_state: st.session_state['saved_a_on'] = False
if 'saved_flip_on' not in st.session_state: st.session_state['saved_flip_on'] = False

# --- PORTFOLIO ---
PORT = {
    "HIVE": {"e": 3.19, "d": "Dec. 01, 2024"},
    "BAER": {"e": 1.86, "d": "Jan. 10, 2025"},
    "TX":   {"e": 38.10, "d": "Nov. 05, 2023"},
    "IMNN": {"e": 3.22, "d": "Aug. 20, 2024"},
    "RERE": {"e": 5.31, "d": "Oct. 12, 2024"}
}

NAMES = {"TSLA":"Tesla","NVDA":"Nvidia","BTC-USD":"Bitcoin","AMD":"AMD","PLTR":"Palantir","AAPL":"Apple","SPY":"S&P 500","^IXIC":"Nasdaq","^DJI":"Dow Jones","GC=F":"Gold","TD.TO":"TD Bank","IVN.TO":"Ivanhoe","BN.TO":"Brookfield","JNJ":"J&J"}

# --- SIDEBAR ---
st.sidebar.header("⚡ Pulse")
if "OPENAI_KEY" in st.secrets: KEY = st.secrets["OPENAI_KEY"]
else: KEY = st.sidebar.text_input("OpenAI Key (Optional)", type="password")

qp = st.query_params
w_str = qp.get("watchlist", "SPY, AAPL, NVDA, TSLA, AMD, PLTR, BTC-USD, JNJ")
u_in = st.sidebar.text_input("Add Tickers", value=w_str)
if u_in != w_str: st.query_params["watchlist"] = u_in
WATCH = [x.strip().upper() for x in u_in.split(",")]
ALL = list(set(WATCH + list(PORT.keys())))
st.sidebar.divider()
st.sidebar.subheader("🔔 Smart Alerts")

# --- PERSISTENT WIDGETS ---
a_tick = st.sidebar.selectbox("Price Target Asset", sorted(ALL), key="saved_a_tick")
a_price = st.sidebar.number_input("Target ($)", step=0.5, key="saved_a_price")
a_on = st.sidebar.toggle("Active Price Alert", key="saved_a_on")
flip_on = st.sidebar.toggle("Alert on Trend Flip", key="saved_flip_on")

# --- CACHED DATA ENGINE ---
@st.cache_data(ttl=60, show_spinner=False)
def get_data_cached(s):
    s = s.strip().upper()
    p, pv, dh, dl, f = 0.0, 0.0, 0.0, 0.0, False
    tk = yf.Ticker(s)
    is_crypto = s.endswith("-USD")
    
    # 1. Try Fast Info (Stocks)
    if not is_crypto:
        try:
            p = tk.fast_info['last_price']
            pv = tk.fast_info['previous_close']
            dh = tk.fast_info['day_high']
            dl = tk.fast_info['day_low']
            f = True
        except: pass

    # 2. Try History (Crypto or Fallback)
    if not f or is_crypto:
        try:
            h = tk.history(period="1d", interval="1m") # 1m data for crypto precision
            if h.empty: h = tk.history(period="5d") # Fallback
            
            if not h.empty:
                p = h['Close'].iloc[-1]
                pv = h['Open'].iloc[0] if is_crypto else h['Close'].iloc[-2]
                dh = h['High'].max()
                dl = h['Low'].min()
                f = True
        except: pass
        
    if not f: return None
    
    # Calc Metrics
    dp = ((p-pv)/pv)*100 if pv>0 else 0.0
    c = "green" if dp>=0 else "red"
    x_str = f"**Live: ${p:,.2f} (:{c}[{dp:+.2f}%])**" if is_crypto else f"**🌙 Ext: ${p:,.2f} (:{c}[{dp:+.2f}%])**"
    
    # Calc Range Bar (0% to 100%)
    if dh > dl:
        rng_pct = max(0, min(1, (p - dl) / (dh - dl))) * 100
    else:
        rng_pct = 50 # Default middle if no range
    
    # Create HTML Range Bar
    # Gradient from Red (Low) to Green (High)
    rng_html = f"""
    <div style="display:flex; align-items:center; font-size:12px; color:#888; margin-top:5px; margin-bottom:2px;">
        <span style="margin-right:5px;">L</span>
        <div style="flex-grow:1; height:6px; background:#333; border-radius:3px; overflow:hidden;">
            <div style="width:{rng_pct}%; height:100%; background: linear-gradient(90deg, #ff4b4b, #4caf50);"></div>
        </div>
        <span style="margin-left:5px;">H</span>
    </div>
    """

    rsi, rl, tr, v_str, vol_tag, raw_trend = 50, "Neutral", "Neutral", "N/A", "", "NEUTRAL"
    try:
        hm = tk.history(period="1mo")
        if not hm.empty:
            cur_v = hm['Volume'].iloc[-1]
            avg_v = hm['Volume'].iloc[:-1].mean() if len(hm) > 1 else cur_v
            v_str = f"{cur_v/1e6:.1f}M" if cur_v>=1e6 else f"{cur_v:,.0f}"
            if avg_v > 0:
                ratio = cur_v / avg_v
                if ratio >= 1.0: vol_tag = "⚡ SURGE"
                elif ratio >= 0.5: vol_tag = "🌊 STEADY"
                else: vol_tag = "💤 QUIET"
            if len(hm)>=14:
                d = hm['Close'].diff()
                g, l = d.where(d>0,0).rolling(14).mean(), (-d.where(d<0,0)).rolling(14).mean()
                rsi = (100-(100/(1+(g/l)))).iloc[-1]
                if rsi >= 70: rl = "🔥 HOT"
                elif rsi <= 30: rl = "❄️ COLD"
                else: rl = "😐 OK"
                macd = hm['Close'].ewm(span=12).mean() - hm['Close'].ewm(span=26).mean()
                if macd.iloc[-1] > 0:
                    raw_trend = "BULL"
                    tr = "<span style='color:#00C805; font-weight:bold;'>BULL</span>"
                else:
                    raw_trend = "BEAR"
                    tr = "<span style='color:#FF2B2B; font-weight:bold;'>BEAR</span>"
    except: pass
    return {"p":p, "d":dp, "x":x_str, "v":v_str, "vt":vol_tag, "rsi":rsi, "rl":rl, "tr":tr, "raw_trend":raw_trend, "rng_html":rng_html}

# --- HEADER & COUNTDOWN (CENTERED) ---
c1, c2 = st.columns([1, 1])
with c1:
    st.title("⚡ Penny Pulse")
    st.caption(f"Last Updated: {datetime.now().strftime('%H:%M:%S')}")

with c2:
    components.html("""
    <div style="font-family: 'Helvetica', sans-serif; background-color: #0E1117; padding: 5px; border-radius: 5px; text-align:center; display:flex; justify-content:center; align-items:center; height:100%;">
        <span style="color: #BBBBBB; font-weight: bold; font-size: 14px; margin-right:5px;">Next Update: </span>
        <span id="countdown" style="color: #FF4B4B; font-weight: 900; font-size: 18px;">--</span>
        <span style="color: #BBBBBB; font-size: 14px; margin-left:2px;"> s</span>
    </div>
    <script>
    function startTimer() {
        var timer = setInterval(function() {
            var now = new Date();
            var seconds = 60 - now.getSeconds();
            var el = document.getElementById("countdown");
            if(el) { el.innerHTML = seconds; }
        }, 1000);
    }
    startTimer();
    </script>
    """, height=60)

# --- TICKER (SEAMLESS LOOP) ---
ti = []
for t in ["SPY","^IXIC","^DJI","BTC-USD"]:
    d = get_data_cached(t)
    if d:
        c, a = ("#4caf50","▲") if d['d']>=0 else ("#f443
