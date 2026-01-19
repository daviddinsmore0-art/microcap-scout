import streamlit as st, yfinance as yf, requests, time, xml.etree.ElementTree as ET
from datetime import datetime
import streamlit.components.v1 as components
import pandas as pd
import altair as alt

try: st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="wide")
except: pass

# --- SESSION STATE ---
if 'news_results' not in st.session_state: st.session_state['news_results'] = []
if 'alert_triggered' not in st.session_state: st.session_state['alert_triggered'] = False
if 'price_mem' not in st.session_state: st.session_state['price_mem'] = {}
if 'saved_a_tick' not in st.session_state: st.session_state['saved_a_tick'] = "SPY"
if 'saved_a_price' not in st.session_state: st.session_state['saved_a_price'] = 0.0
if 'saved_a_on' not in st.session_state: st.session_state['saved_a_on'] = False

# --- YOUR PORTFOLIO ---
PORT = {
    "HIVE": {"e": 3.19, "d": "Dec. 01, 2024", "q": 50},
    "BAER": {"e": 1.86, "d": "Jan. 10, 2025", "q": 120},
    "TX":   {"e": 38.10, "d": "Nov. 05, 2023", "q": 40},
    "IMNN": {"e": 3.22, "d": "Aug. 20, 2024", "q": 100},
    "RERE": {"e": 5.31, "d": "Oct. 12, 2024", "q": 100}
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

# --- ALERTS ---
st.sidebar.subheader("🔔 Smart Alerts")
a_tick = st.sidebar.selectbox("Price Target Asset", sorted(ALL), key="saved_a_tick")
a_price = st.sidebar.number_input("Target ($)", step=0.5, key="saved_a_price")
a_on = st.sidebar.toggle("Active Price Alert", key="saved_a_on")

# --- SAFE DATA ENGINE (The Core Fix) ---
def get_safe_data(s):
    try:
        tk = yf.Ticker(s)
        # We fetch 1 month of history to calculate RSI and Trends manually
        # This replaces 5 different API calls with just 1, preventing blocks.
        h = tk.history(period="1mo", interval="1d")
        
        if not h.empty:
            # 1. Price Data
            p = h['Close'].iloc[-1]
            
            # SPY Glitch Fix
            if s == "SPY" and p > 650:
                h_daily = tk.history(period="1d")
                p = h_daily['Close'].iloc[-1]

            prev = h['Close'].iloc[-2]
            dp = ((p - prev)/prev)*100
            d_raw = p - prev
            
            # 2. Volume Logic (Calculated Manually)
            vol = h['Volume'].iloc[-1]
            avg_vol = h['Volume'].mean()
            vol_str = f"{vol/1e6:.1f}M" if vol > 1e6 else f"{vol/1e3:.0f}K"
            ratio = vol / avg_vol if avg_vol > 0 else 1.0
            
            if ratio >= 1.5: vol_tag = "⚡ SURGE"
            elif ratio >= 0.8: vol_tag = "🌊 STEADY"
            else: vol_tag = "💤 QUIET"
            
            # 3. RSI Logic (Calculated Manually)
            delta = h['Close'].diff()
            up = delta.clip(lower=0)
            down = -1 * delta.clip(upper=0)
            ema_up = up.ewm(com=13, adjust=False).mean()
            ema_down = down.ewm(com=13, adjust=False).mean()
            rs = ema_up / ema_down
            rsi = 100 - (100 / (1 + rs)).iloc[-1]
            
            rsi_tag = "🔥 HOT" if rsi > 70 else "❄️ COLD" if rsi < 30 else "😐 OK"
            
            # 4. AI Signal (Reconstructed from Manual Data)
            ai_score = 0
            if rsi >= 70: ai_score -= 2
            elif rsi <= 30: ai_score += 2
            if ratio > 1.2: ai_score += 1 if dp > 0 else -1
            
            if ai_score >= 2: ai_txt, ai_col = "🟢 BULLISH BIAS", "#4caf50"
            elif ai_score <= -2: ai_txt, ai_col = "🔴 BEARISH BIAS", "#ff4b4b"
            else: ai_txt, ai_col = "⚪ NEUTRAL", "#888"

            # 5. Trend
            macd = h['Close'].ewm(span=12).mean() - h['Close'].ewm(span=26).mean()
            raw_trend = "BULL" if macd.iloc[-1] > 0 else "BEAR"
            tr_html = f"<span style='color:{'#00C805' if raw_trend=='BULL' else '#FF2B2B'}; font-weight:bold;'>{raw_trend}</span>"

            # 6. Chart Data
            chart_data = h['Close']

            data = {
                "p": p, "d": dp, "d_raw": d_raw, 
                "vol": vol_str, "vt": vol_tag, 
                "rsi": rsi, "rl": rsi_tag, 
                "ai_txt": ai_txt, "ai_col": ai_col,
                "tr": tr_html, "chart": chart_data
            }
            # Save to memory bank
            st.session_state['price_mem'][s] = data
            return data
    except: pass
    # Fallback to memory if fetch fails
    return st.session_state['price_mem'].get(s)

# --- HEADER & COUNTDOWN ---
c1, c2 = st.columns([1, 1])
with c1:
    st.title("⚡ Penny Pulse")
    st.caption(f"Last Updated: {datetime.now().strftime('%H:%M:%S')}")
with c2:
    components.html("""<div style="font-family: 'Helvetica', sans-serif; background-color: #0E1117; padding: 5px; border-radius: 5px; text-align:center; display:flex; justify-content:center; align-items:center; height:100%;"><span style="color: #BBBBBB; font-weight: bold; font-size: 14px; margin-right:5px;">Next Update: </span><span id="countdown" style="color: #FF4B4B; font-weight: 900; font-size: 18px;">--</span><span style="color: #BBBBBB; font-size: 14px; margin-left:2px;"> s</span></div><script>function startTimer(){var timer=setInterval(function(){var now=new Date();var seconds=60-now.getSeconds();var el=document.getElementById("countdown");if(el){el.innerHTML=seconds;}},1000);}startTimer();</script>""", height=60)

# --- TICKER TAPE ---
ti = []
for t in ["SPY","^IXIC","^DJI","BTC-USD"]:
    d = get_safe_data(t)
    if d:
        c, a = ("#4caf50","▲") if d['d']>=0 else ("#f44336","▼")
        ti.append(f"<span style='margin-right:30px;font-weight:900;font-size:22px;color:white;'>{NAMES.get(t,t)}: <span style='color:{c};'>${d['p']:,.2f} {a} {d['d']:.2f}%</span></span>")
h = "".join(ti)
if h: st.markdown(f"""<div style="background-color: #0E1117; padding: 10px 0; border-top: 2px solid #333; border-bottom: 2px solid #333;"><marquee scrollamount="6" style="width: 100%;">{h * 15}</marquee></div>""", unsafe_allow_html=True)

# --- RENDER CARD FUNCTION ---
def render_card(t, inf=None):
    d = get_safe_data(t)
    if d:
        nm = NAMES.get(t, t)
        url = f"https://finance.yahoo.com/quote/{t}"
        st.markdown(f"<h3 style='margin:0; padding:0;'><a href='{url}' target='_blank' style='text-decoration:none; color:inherit;'>{nm}</a></h3>", unsafe_allow_html=True)
        
        if inf:
            q = inf.get("q", 100)
            st.caption(f"{q} Shares @ ${inf['e']}")
            st.metric("Price", f"${d['p']:,.2f}", f"{((d['p']-inf['e'])/inf['e'])*100:.2f}% (Total)")
        else:
            st.metric("Price", f"${d['p']:,.2f}", f"{d['d']:.2f}%")
        
        st.markdown(f"<div style='margin-bottom:10px; font-weight:bold; font-size:14px;'>🤖 AI: <span style='color:{d['ai_col']};'>{d['ai_txt']}</span></div>", unsafe_allow_html=True)
        st.markdown(f"<div style='font-size:16px; margin-bottom:5px;'><b>Trend:</b> {d['tr']}</div>", unsafe_allow_html=True)
        st.markdown(f"<div style='font-weight:bold; font-size:16px; margin-bottom:5px;'>Vol: {d['vol']} ({d['vt']})</div>", unsafe_allow_html=True)
        st.markdown(f"<div style='font-weight:bold; font-size:16px; margin-bottom:5px;'>RSI: {d['rsi']:.0f} ({d['rl']})</div>", unsafe_allow_html=True)
        
        with st.expander("📉 Chart"):
            if d['chart'] is not None:
                cdf = d['chart'].reset_index()
                cdf.columns = ['Time', 'Price']
                c = alt.Chart(cdf).mark_line().encode(x=alt.X('Time', axis=alt.Axis(format='%d', title='')), y=alt.Y('Price', scale=alt.Scale(zero=False), title='')).properties(height=200)
                st.altair_chart(c, use_container_width=True)
    else: st.metric(t, "---", "0.0%")
    st.divider()

# --- TABS ---
t1, t2, t3 = st.tabs(["🏠 Dashboard", "🚀 My Picks", "📰 Market News"])
with t1:
    cols = st.columns(3)
    for i, t in enumerate(WATCH):
        with cols[i%3]: render_card(t)

with t2:
    # Portfolio Summary Calculation
    tot_val, day_pl, tot_pl = 0.0, 0.0, 0.0
    for t, inf in PORT.items():
        d = get_safe_data(t)
        if d:
            q = inf.get("q", 100)
            curr = d['p'] * q
            tot_val += curr
            tot_pl += (curr - (inf['e'] * q))
            day_pl += (d['d_raw'] * q)
            
    st.markdown(f"""<div style="background-color:#1e2127; padding:15px; border-radius:10px; margin-bottom:20px; border:1px solid #444;"><div style="display:flex; justify-content:space-around; text-align:center;"><div><div style="color:#aaa; font-size:12px;">Net Liq</div><div style="font-size:18px; font-weight:bold; color:white;">${tot_val:,.2f}</div></div><div><div style="color:#aaa; font-size:12px;">Day P/L</div><div style="font-size:18px; font-weight:bold; color:{'green' if day_pl>=0 else 'red'};">${day_pl:+,.2f}</div></div><div><div style="color:#aaa; font-size:12px;">Total P/L</div><div style="font-size:18px; font-weight:bold; color:{'green' if tot_pl>=0 else 'red'};">${tot_pl:+,.2f}</div></div></div></div>""", unsafe_allow_html=True)
    cols = st.columns(3)
    for i, (t, inf) in enumerate(PORT.items()):
        with cols[i%3]: render_card(t, inf)

# --- ALERT CHECK ---
if a_on:
    d = get_safe_data(a_tick)
    if d and d['p'] >= a_price and not st.session_state['alert_triggered']:
        st.toast(f"🚨 ALERT: {a_tick} HIT ${d['p']:,.2f}!", icon="🔥")
        st.session_state['alert_triggered'] = True

# --- NEWS ENGINE (Cached) ---
@st.cache_data(ttl=300, show_spinner=False)
def get_news_cached():
    head = {'User-Agent': 'Mozilla/5.0'}
    urls = ["https://rss.app/feeds/K6MyOnsQgG4k4MrG.xml","https://rss.app/feeds/Iz44ECtFw3ipVPNF.xml","https://finance.yahoo.com/news/rssindex", "https://www.cnbc.com/id/10000664/device/rss/rss.html"]
    it, seen = [], set()
    blacklist = ["kill", "dead", "troop", "war", "sport", "football", "murder", "crash", "police", "arrest", "shoot", "bomb"]
    for u in urls:
        try:
            r = requests.get(u, headers=head, timeout=5)
            root = ET.fromstring(r.content)
            for i in root.findall('.//item')[:20]:
                t, l = i.find('title').text, i.find('link').text
                if t and t not in seen:
                    t_lower = t.lower()
                    if not any(b in t_lower for b in blacklist):
                        seen.add(t); it.append({"title":t,"link":l})
        except: continue
    return it

with t3:
    st.subheader("🚨 Global AI Wire")
    if st.button("Generate AI Report", type="primary", key="news_btn"):
        with st.spinner("AI Scanning Market News..."):
            raw = get_news_cached()
            if not raw: st.error("⚠️ No news sources responded.")
            elif not KEY:
                st.warning("⚠️ No OpenAI Key. Showing Headlines.")
                st.session_state['news_results'] = [{"ticker":"NEWS","signal":"⚪","reason":"Free Mode","title":x['title'],"link":x['link']} for x in raw]
            else:
                try:
                    from openai import OpenAI
                    p_list = "\n".join([f"{i+1}. {x['title']}" for i,x in enumerate(raw[:20])]) # Limit to 20 to save tokens
                    system_instr = "Filter: stocks/finance only. Format: Ticker | Signal (🟢/🔴/⚪) | Reason."
                    res = OpenAI(api_key=KEY).chat.completions.create(model="gpt-4o-mini", messages=[{"role":"system", "content": system_instr}, {"role":"user","content":f"Headlines:\n{p_list}"}], max_tokens=400)
                    enrich = []
                    lines = res.choices[0].message.content.strip().split("\n")
                    for l in lines:
                        parts = l.split("|")
                        if len(parts)>=3: enrich.append({"ticker":parts[0].strip(),"signal":parts[1].strip(),"reason":parts[2].strip(),"title":parts[0],"link":"#"})
                    if not enrich: st.session_state['news_results'] = [{"ticker":"NEWS","signal":"⚪","reason":"AI Filtered","title":x['title'],"link":x['link']} for x in raw]
                    else: st.session_state['news_results'] = enrich
                except:
                    st.warning("⚠️ AI Limit Reached or Key Invalid. Showing Headlines.")
                    st.session_state['news_results'] = [{"ticker":"NEWS","signal":"⚪","reason":"AI Unavailable","title":x['title'],"link":x['link']} for x in raw]
    
    if st.session_state.get('news_results'):
        for r in st.session_state['news_results']:
            st.markdown(f"**{r['ticker']} {r['signal']}** - [{r['title']}]({r['link']})")
            st.caption(r['reason'])
            st.divider()

now = datetime.now()
wait = 60 - now.second
time.sleep(wait + 1)
st.rerun()
