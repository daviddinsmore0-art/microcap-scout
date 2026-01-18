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
    p, pv, f = 0.0, 0.0, False
    tk = yf.Ticker(s)
    is_crypto = s.endswith("-USD")
    if is_crypto:
        try:
            h = tk.history(period="1d", interval="1m")
            if not h.empty: p, pv, f = h['Close'].iloc[-1], h['Open'].iloc[0], True
        except: pass
    if not f:
        try: p, pv, f = tk.fast_info['last_price'], tk.fast_info['previous_close'], True
        except:
            try:
                h = tk.history(period="5d")
                if not h.empty: p, pv, f = h['Close'].iloc[-1], h['Close'].iloc[-2], True
            except: pass
    if not f: return None
    
    dp = ((p-pv)/pv)*100 if pv>0 else 0.0
    c = "green" if dp>=0 else "red"
    x_str = f"**Live: ${p:,.2f} (:{c}[{dp:+.2f}%])**" if is_crypto else f"**🌙 Ext: ${p:,.2f} (:{c}[{dp:+.2f}%])**"
    
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
    return {"p":p, "d":dp, "x":x_str, "v":v_str, "vt":vol_tag, "rsi":rsi, "rl":rl, "tr":tr, "raw_trend":raw_trend}

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
        c, a = ("#4caf50","▲") if d['d']>=0 else ("#f44336","▼")
        name = NAMES.get(t, t)
        ti.append(f"<span style='margin-right:30px;font-weight:900;font-size:22px;color:white;'>{name}: <span style='color:{c};'>${d['p']:,.2f} {a} {d['d']:.2f}%</span></span>")
h = "".join(ti)

st.markdown(f"""
<div style="background-color: #0E1117; padding: 10px 0; border-top: 2px solid #333; border-bottom: 2px solid #333;">
    <marquee scrollamount="6" style="width: 100%;">
        {h * 15}
    </marquee>
</div>
""", unsafe_allow_html=True)

# --- FLIP CHECK ---
def check_flip(ticker, current_trend):
    if not flip_on: return
    if ticker in st.session_state['last_trends']:
        prev = st.session_state['last_trends'][ticker]
        if prev != "NEUTRAL" and current_trend != "NEUTRAL" and prev != current_trend:
            st.toast(f"🔀 TREND FLIP: {ticker} switched to {current_trend}!", icon="⚠️")
    st.session_state['last_trends'][ticker] = current_trend

# --- DASHBOARD ---
t1, t2, t3 = st.tabs(["🏠 Dashboard", "🚀 My Picks", "📰 Market News"])
with t1:
    cols = st.columns(3)
    for i, t in enumerate(WATCH):
        with cols[i%3]:
            d = get_data_cached(t)
            if d:
                check_flip(t, d['raw_trend'])
                st.metric(NAMES.get(t, t), f"${d['p']:,.2f}", f"{d['d']:.2f}%")
                st.markdown(f"<div style='font-size:16px; margin-bottom:5px;'><b>Momentum:</b> {d['tr']}</div>", unsafe_allow_html=True)
                st.markdown(f"<div style='font-weight:bold; font-size:16px; margin-bottom:5px;'>Vol: {d['v']} ({d['vt']})</div>", unsafe_allow_html=True)
                st.markdown(f"<div style='font-weight:bold; font-size:16px; margin-bottom:5px;'>RSI: {d['rsi']:.0f} ({d['rl']})</div>", unsafe_allow_html=True)
                st.markdown(d['x'])
            else: st.metric(t, "---", "0.0%")
            st.divider()
with t2:
    cols = st.columns(3)
    for i, (t, inf) in enumerate(PORT.items()):
        with cols[i%3]:
            d = get_data_cached(t)
            if d:
                check_flip(t, d['raw_trend'])
                st.metric(NAMES.get(t, t), f"${d['p']:,.2f}", f"{((d['p']-inf['e'])/inf['e'])*100:.2f}% (Total)")
                st.markdown(f"<div style='font-size:16px; margin-bottom:5px;'><b>Momentum:</b> {d['tr']}</div>", unsafe_allow_html=True)
                date_str = inf.get("d", "N/A")
                st.markdown(f"<div style='font-weight:bold; font-size:16px; margin-bottom:5px;'>Entry: ${inf['e']} ({date_str})</div>", unsafe_allow_html=True)
                st.markdown(f"<div style='font-weight:bold; font-size:16px; margin-bottom:5px;'>Vol: {d['v']} ({d['vt']})</div>", unsafe_allow_html=True)
                st.markdown(d['x'])
            st.divider()

if a_on:
    d = get_data_cached(a_tick)
    if d and d['p'] >= a_price and not st.session_state['alert_triggered']:
        st.toast(f"🚨 ALERT: {a_tick} HIT ${d['p']:,.2f}!", icon="🔥")
        st.session_state['alert_triggered'] = True

# --- NEWS (ROBUST + BACKUP) ---
@st.cache_data(ttl=300, show_spinner=False)
def get_news_cached():
    head = {'User-Agent': 'Mozilla/5.0'}
    # Added Investing.com as a backup source
    urls = [
        "https://finance.yahoo.com/news/rssindex", 
        "https://www.cnbc.com/id/100003114/device/rss/rss.html",
        "https://www.investing.com/rss/news.rss"
    ]
    it, seen = [], set()
    for u in urls:
        try:
            # Increased timeout to 5 seconds to prevent empty lists
            r = requests.get(u, headers=head, timeout=5)
            root = ET.fromstring(r.content)
            for i in root.findall('.//item')[:5]:
                t, l = i.find('title').text, i.find('link').text
                if t and t not in seen:
                    seen.add(t); it.append({"title":t,"link":l})
        except: continue
    return it

with t3:
    st.subheader("🚨 Global Wire")
    if st.button("Generate Report", type="primary", key="news_btn"):
        with st.spinner("Scanning..."):
            raw = get_news_cached()
            if not raw:
                st.error("⚠️ No news sources responded. Please try again.")
            elif not KEY:
                st.warning("⚠️ No OpenAI Key. Showing Headlines.")
                st.session_state['news_results'] = [{"ticker":"NEWS","signal":"⚪","reason":"Free Mode","title":x['title'],"link":x['link']} for x in raw]
            else:
                try:
                    from openai import OpenAI
                    p_list = "\n".join([f"{i+1}. {x['title']}" for i,x in enumerate(raw)])
                    system_instr = "Analyze these headlines. If a headline compares two stocks (e.g. 'Better than NVDA'), ignore the benchmark ticker. Only tag the main subject. If unsure, use 'MARKET'."
                    res = OpenAI(api_key=KEY).chat.completions.create(model="gpt-4o-mini", messages=[
                        {"role":"system", "content": system_instr},
                        {"role":"user","content":f"Format: Ticker | Signal (🟢/🔴/⚪) | Reason. Headlines:\n{p_list}"}
                    ], max_tokens=400)
                    enrich = []
                    lines = res.choices[0].message.content.strip().split("\n")
                    idx = 0
                    for l in lines:
                        parts = l.split("|")
                        if len(parts)>=3 and idx<len(raw):
                            enrich.append({"ticker":parts[0].strip(),"signal":parts[1].strip(),"reason":parts[2].strip(),"title":raw[idx]['title'],"link":raw[idx]['link']})
                            idx+=1
                    st.session_state['news_results'] = enrich
                except:
                    st.warning("⚠️ AI Limit Reached. Showing Free Headlines.")
                    # Fallback to free headlines if AI fails
                    st.session_state['news_results'] = [{"ticker":"NEWS","signal":"⚪","reason":"AI Unavailable","title":x['title'],"link":x['link']} for x in raw]

    if st.session_state.get('news_results'):
        for r in st.session_state['news_results']:
            st.markdown(f"**{r['ticker']} {r['signal']}** - [{r['title']}]({r['link']})")
            st.caption(r['reason'])
            st.divider()

# --- RECONNECT LOGIC ---
now = datetime.now()
wait = 60 - now.second
time.sleep(wait + 1)
st.rerun()
