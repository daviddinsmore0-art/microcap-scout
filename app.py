import streamlit as st, yfinance as yf, requests, time, xml.etree.ElementTree as ET
from datetime import datetime
import streamlit.components.v1 as components

try: st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="wide")
except: pass

if 'news_results' not in st.session_state: st.session_state['news_results'] = []
if 'alert_triggered' not in st.session_state: st.session_state['alert_triggered'] = False

# --- DATA ---
PORT = {"HIVE":{"e":3.19},"BAER":{"e":1.86},"TX":{"e":38.10},"IMNN":{"e":3.22},"RERE":{"e":5.31}}
NAMES = {"TSLA":"Tesla", "NVDA":"Nvidia", "BTC-USD":"Bitcoin", "AMD":"AMD", "PLTR":"Palantir", "AAPL":"Apple", "SPY":"S&P 500", "^IXIC":"Nasdaq", "^DJI":"Dow Jones", "GC=F":"Gold", "TD.TO":"TD Bank", "IVN.TO":"Ivanhoe", "BN.TO":"Brookfield", "JNJ":"J&J"}

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
a_tick = st.sidebar.selectbox("Alert Asset", sorted(ALL))
a_price = st.sidebar.number_input("Target ($)", value=0.0, step=0.5)
a_on = st.sidebar.toggle("Activate Alert")

# --- ENGINE ---
def get_data(s):
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
        
    rsi, rsi_label, tr, v_str = 50, "Neutral", "Neutral", "N/A"
    try:
        hm = tk.history(period="1mo")
        if not hm.empty:
            v = hm['Volume'].iloc[-1]
            v_str = f"{v/1e6:.1f}M" if v>=1e6 else f"{v:,.0f}"
            if len(hm)>=14:
                d = hm['Close'].diff()
                g, l = d.where(d>0,0).rolling(14).mean(), (-d.where(d<0,0)).rolling(14).mean()
                rsi = (100-(100/(1+(g/l)))).iloc[-1]
                # RSI Logic (Hot/Cold)
                if rsi >= 70: rsi_label = "🔥 HOT"
                elif rsi <= 30: rsi_label = "❄️ COLD"
                else: rsi_label = "😐 OK"
                # MACD Logic (Momentum)
                macd = hm['Close'].ewm(span=12).mean() - hm['Close'].ewm(span=26).mean()
                tr = ":green[BULL]" if macd.iloc[-1]>0 else ":red[BEAR]"
    except: pass
    return {"p":p, "d":dp, "x":x_str, "v":v_str, "rsi":rsi, "rl":rsi_label, "tr":tr}

# --- HEADER & FIXED TIMER ---
c1, c2 = st.columns([3,1])
with c1: st.title("⚡ Penny Pulse")
with c2: 
    # Self-correcting Javascript Timer
    components.html("""
    <div style="font-family:sans-serif; color:#888; font-size:14px; text-align:right; padding-top:20px;">
    Next Update: <span id="timer" style="color:white; font-weight:bold; font-size:16px;">--</span>s
    </div>
    <script>
    function updateTimer() {
        var now = new Date();
        var seconds = now.getSeconds();
        var left = 60 - seconds;
        document.getElementById("timer").innerText = left;
    }
    setInterval(updateTimer, 1000);
    updateTimer();
    </script>
    """, height=50)

# --- TAPE ---
ti = []
for t in ["SPY","^IXIC","^DJI","BTC-USD"]:
    d = get_data(t)
    if d:
        c, a = ("#4caf50","▲") if d['d']>=0 else ("#f44336","▼")
        name = NAMES.get(t, t)
        ti.append(f"<span style='margin-right:40px;font-weight:bold;font-size:18px;color:white;'>{name}: <span style='color:{c};'>${d['p']:,.2f} {a} {d['d']:.2f}%</span></span>")
h = "".join(ti)
st.markdown(f"""<style>.tc{{width:100%;overflow:hidden;background:#0e1117;border-bottom:2px solid #444;height:50px;display:flex;align-items:center;}}.tx{{display:flex;white-space:nowrap;animation:ts 150s linear infinite;}}@keyframes ts{{0%{{transform:translateX(0);}}100%{{transform:translateX(-100%);}}}}</style><div class="tc"><div class="tx">{h*30}</div></div>""", unsafe_allow_html=True)

# --- TABS ---
t1, t2, t3 = st.tabs(["🏠 Dashboard", "🚀 My Picks", "📰 Market News"])
with t1:
    cols = st.columns(3)
    for i, t in enumerate(WATCH):
        with cols[i%3]:
            d = get_data(t)
            if d:
                st.metric(NAMES.get(t, t), f"${d['p']:,.2f}", f"{d['d']:.2f}%")
                # CLEANER LAYOUT
                st.markdown(f"**Momentum: {d['tr']}**")
                st.caption(f"Vol: {d['v']} | RSI: {d['rsi']:.0f} ({d['rl']})")
                st.markdown(d['x'])
            else: st.metric(t, "---", "0.0%")
            st.divider()
with t2:
    cols = st.columns(3)
    for i, (t, inf) in enumerate(PORT.items()):
        with cols[i%3]:
            d = get_data(t)
            if d:
                st.metric(NAMES.get(t, t), f"${d['p']:,.2f}", f"{((d['p']-inf['e'])/inf['e'])*100:.2f}% (Total)")
                st.markdown(f"**Momentum: {d['tr']}**")
                st.caption(f"Entry: ${inf['e']} | RSI: {d['rsi']:.0f}")
                st.markdown(d['x'])
            st.divider()

if a_on:
    d = get_data(a_tick)
    if d and d['p'] >= a_price and not st.session_state['alert_triggered']:
        st.toast(f"🚨 ALERT: {a_tick} HIT ${d['p']:,.2f}!", icon="🔥")
        st.session_state['alert_triggered'] = True

# --- NEWS ---
def get_news():
    head = {'User-Agent': 'Mozilla/5.0'}
    urls = ["https://finance.yahoo.com/news/rssindex", "https://www.cnbc.com/id/100003114/device/rss/rss.html"]
    it, seen = [], set()
    for u in urls:
        try:
            r = requests.get(u, headers=head, timeout=2)
            root = ET.fromstring(r.content)
            for i in root.findall('.//item')[:5]:
                t, l = i.find('title').text, i.find('link').text
                if t and t not in seen:
                    seen.add(t); it.append({"title":t,"link":l})
        except: continue
    return it

with t3:
    st.subheader("🚨 Global Wire")
    if st.button("Generate Report (Auto-Detect)", type="primary"):
        with st.spinner("Scanning..."):
            raw = get_news()
            if not KEY:
                st.warning("⚠️ No OpenAI Key found. Showing headlines.")
                st.session_state['news_results'] = [{"ticker":"NEWS","signal":"⚪","reason":"Free Mode","title":x['title'],"link":x['link']} for x in raw]
            else:
                try:
                    from openai import OpenAI
                    p_list = "\n".join([f"{i+1}. {x['title']}" for i,x in enumerate(raw)])
                    res = OpenAI(api_key=KEY).chat.completions.create(model="gpt-4o-mini", messages=[{"role":"user","content":f"Analyze {len(raw)} headlines. Format: Ticker | Signal (🟢/🔴/⚪) | Reason. Headlines:\n{p_list}"}], max_tokens=400)
                    enrich = []
                    lines = res.choices[0].message.content.strip().split("\n")
                    idx = 0
                    for l in lines:
                        parts = l.split("|")
                        if len(parts)>=3 and idx<len(raw):
                            enrich.append({"ticker":parts[0].strip(),"signal":parts[1].strip(),"reason":parts[2].strip(),"title":raw[idx]['title'],"link":raw[idx]['link']})
                            idx+=1
                    st.session_state['news_results'] = enrich
                except Exception as e: 
                    st.warning(f"⚠️ AI Busy/Limit Reached. Switched to Free Mode.")
                    st.session_state['news_results'] = [{"ticker":"NEWS","signal":"⚪","reason":"AI Unavailable","title":x['title'],"link":x['link']} for x in raw]

    if st.session_state.get('news_results'):
        for r in st.session_state['news_results']:
            st.markdown(f"**{r['ticker']} {r['signal']}** - [{r['title']}]({r['link']})")
            st.caption(r['reason'])
            st.divider()

# Sync to Minute
now = datetime.now()
wait = 60 - now.second
time.sleep(wait + 1)
st.rerun()
