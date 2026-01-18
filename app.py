import streamlit as st
import yfinance as yf
import requests
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from openai import OpenAI

# --- CONFIG ---
try: st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="wide")
except: pass

# --- STATE ---
if 'live_mode' not in st.session_state: st.session_state['live_mode'] = False
if 'last_update' not in st.session_state: st.session_state['last_update'] = datetime.now().strftime("%H:%M:%S")
if 'news_results' not in st.session_state: st.session_state['news_results'] = []
if 'alert_triggered' not in st.session_state: st.session_state['alert_triggered'] = False

# --- PORTFOLIO & KEYS ---
MY_PORTFOLIO = {
    "HIVE": {"entry": 3.19}, "BAER": {"entry": 1.86}, "TX": {"entry": 38.10},
    "IMNN": {"entry": 3.22}, "RERE": {"entry": 5.31}
}

if "OPENAI_KEY" in st.secrets: OPENAI_KEY = st.secrets["OPENAI_KEY"]
else:
    st.sidebar.header("🔑 Login")
    OPENAI_KEY = st.sidebar.text_input("OpenAI Key", type="password")

# --- SIDEBAR ---
st.sidebar.header("⚡ Pulse")
query_params = st.query_params
saved_watchlist = query_params.get("watchlist", "SPY, AAPL, NVDA, TSLA, AMD, PLTR, BTC-USD, JNJ")
user_input = st.sidebar.text_input("Add Tickers", value=saved_watchlist)
if user_input != saved_watchlist: st.query_params["watchlist"] = user_input

watchlist_list = [x.strip().upper() for x in user_input.split(",")]
ALL_ASSETS = list(set(watchlist_list + list(MY_PORTFOLIO.keys())))

st.sidebar.divider()
alert_ticker = st.sidebar.selectbox("Alert Asset", sorted(ALL_ASSETS))
alert_price = st.sidebar.number_input("Target ($)", value=0.0, step=0.5)
alert_active = st.sidebar.toggle("Activate Alert")

# --- DATA ENGINE ---
def fetch_stock_data(symbol):
    clean = symbol.strip().upper()
    price, prev_close, found = 0.0, 0.0, False
    ticker = yf.Ticker(clean)

    if clean.endswith("-USD"):
        try:
            h = ticker.history(period="1d", interval="1m")
            if not h.empty: price, prev_close, found = h['Close'].iloc[-1], h['Open'].iloc[0], True
        except: pass

    if not found:
        try:
            price, prev_close = ticker.fast_info['last_price'], ticker.fast_info['previous_close']
            found = True
        except:
            try:
                h = ticker.history(period="5d")
                if not h.empty:
                    price, prev_close = h['Close'].iloc[-1], h['Close'].iloc[-2]
                    found = True
            except: pass
            
    if not found: return None

    day_pct = ((price - prev_close) / prev_close) * 100 if prev_close > 0 else 0.0
    color = "green" if day_pct >= 0 else "red"
    ext_str = f"**Live: ${price:,.2f} (:{color}[{day_pct:+.2f}%])**"

    # History (Volume/RSI)
    rsi_val, trend_str, vol_str = 50, "WAIT", "N/A"
    try:
        hm = ticker.history(period="1mo")
        if not hm.empty:
            v = hm['Volume'].iloc[-1]
            vol_str = f"{v/1e6:.1f}M" if v>=1e6 else f"{v:,.0f}"
            if len(hm) >= 14:
                d = hm['Close'].diff()
                g, l = d.where(d>0,0).rolling(14).mean(), (-d.where(d<0,0)).rolling(14).mean()
                rsi_val = (100 - (100 / (1 + (g/l)))).iloc[-1]
                macd = hm['Close'].ewm(span=12).mean() - hm['Close'].ewm(span=26).mean()
                trend_str = ":green[BULL]" if macd.iloc[-1] > 0 else ":red[BEAR]"
    except: pass

    return {"reg_price": price, "day_delta": day_pct, "ext_str": ext_str, "volume": vol_str, "rsi": rsi_val, "trend": trend_str}

# --- UI HEADER ---
c1, c2 = st.columns([3, 1])
with c1:
    if st.session_state['live_mode']: st.markdown(f"## ⚡ Penny Pulse :red[● LIVE] <span style='font-size:14px; color:gray'>{st.session_state['last_update']}</span>", unsafe_allow_html=True)
    else: st.title("⚡ Penny Pulse")
with c2:
    if st.toggle("🔴 LIVE DATA", key="live_mode_toggle"):
        st.session_state['live_mode'] = True
        st.session_state['last_update'] = datetime.now().strftime("%H:%M:%S")
    else: st.session_state['live_mode'] = False

# --- TICKER TAPE ---
t_items = []
for t in ["SPY", "^IXIC", "^DJI", "BTC-USD"]:
    d = fetch_stock_data(t)
    if d:
        c, a = ("#4caf50", "▲") if d['day_delta'] >= 0 else ("#f44336", "▼")
        t_items.append(f"<span style='margin-right:50px;font-weight:900;font-size:18px;color:white;'>{t}: <span style='color:{c};'>${d['reg_price']:,.2f} {a} {d['day_delta']:.2f}%</span></span>")
h = "".join(t_items)
st.markdown(f"""<style>.tc{{width:100%;overflow:hidden;background:#0e1117;border-bottom:2px solid #444;height:50px;display:flex;align-items:center;}}.txt{{display:flex;white-space:nowrap;animation:ts 60s linear infinite;}}@keyframes ts{{0%{{transform:translateX(0);}}100%{{transform:translateX(-100%);}}}}</style><div class="tc"><div class="txt">{h*3}</div></div>""", unsafe_allow_html=True)

# --- DASHBOARD TABS ---
tab1, tab2, tab3 = st.tabs(["🏠 Dashboard", "🚀 My Picks", "📰 AI News"])

with tab1:
    st.subheader("My Watchlist")
    cols = st.columns(3)
    for i, t in enumerate(watchlist_list):
        with cols[i%3]:
            d = fetch_stock_data(t)
            if d:
                st.metric(t, f"${d['reg_price']:,.2f}", f"{d['day_delta']:.2f}%")
                st.markdown(f"**Vol: {d['volume']} | RSI: {d['rsi']:.0f} | {d['trend']}**")
                st.markdown(d['ext_str'])
            else: st.metric(t, "---", "0.0%")
            st.divider()

with tab2:
    st.subheader("My Picks")
    cols = st.columns(3)
    for i, (t, info) in enumerate(MY_PORTFOLIO.items()):
        with cols[i%3]:
            d = fetch_stock_data(t)
            if d:
                st.metric(t, f"${d['reg_price']:,.2f}", f"{((d['reg_price']-info['entry'])/info['entry'])*100:.2f}% (Total)")
                st.markdown(f"**Entry: ${info['entry']} | {d['trend']}**")
                st.markdown(d['ext_str'])
            st.divider()
# --- NEWS ENGINE (Yahoo/CNBC/WSJ) ---
def fetch_rss_items():
    headers = {'User-Agent': 'Mozilla/5.0'}
    urls = [
        "https://finance.yahoo.com/news/rssindex",
        "https://www.cnbc.com/id/100003114/device/rss/rss.html",
        "https://feeds.a.dj.com/rss/RSSMarketsMain.xml"
    ]
    items = []
    seen = set()
    for url in urls:
        try:
            r = requests.get(url, headers=headers, timeout=2)
            root = ET.fromstring(r.content)
            for item in root.findall('.//item')[:5]:
                t = item.find('title').text
                l = item.find('link').text
                if t and t not in seen:
                    seen.add(t)
                    items.append({"title": t, "link": l})
        except: continue
    return items

def analyze_batch(items, client):
    if not items: return []
    p_list = ""
    for i, item in enumerate(items):
        p_list += f"{i+1}. {item['title']}\n"
    prompt = f"Analyze {len(items)} headlines. Format: Ticker | Signal (🟢/🔴/⚪) | Reason. Headlines:\n{p_list}"
    try:
        resp = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role":"user", "content":prompt}], max_tokens=400)
        lines = resp.choices[0].message.content.strip().split("\n")
        enrich = []
        idx = 0
        for l in lines:
            parts = l.split("|")
            if len(parts) >= 3 and idx < len(items):
                enrich.append({"ticker": parts[0].strip(), "signal": parts[1].strip(), "reason": parts[2].strip(), "title": items[idx]['title'], "link": items[idx]['link']})
                idx += 1
        return enrich
    except: return []

with tab3:
    st.subheader("🚨 Global Wire (Yahoo/CNBC/WSJ)")
    if st.button("Generate AI Report", type="primary"):
        if not OPENAI_KEY: st.error("Enter OpenAI Key")
        else:
            with st.spinner("Scanning Markets..."):
                raw = fetch_rss_items()
                res = analyze_batch(raw, OpenAI(api_key=OPENAI_KEY))
                st.session_state['news_results'] = res
    if st.session_state.get('news_results'):
        for r in st.session_state['news_results']:
            st.markdown(f"**{r['ticker']} {r['signal']}** - [{r['title']}]({r['link']})")
            st.caption(r['reason'])
            st.divider()

if st.session_state['live_mode']:
    time.sleep(15)
    st.rerun()
# --- NEWS ENGINE (High Quality Sources) ---
def fetch_rss_items():
    headers = {'User-Agent': 'Mozilla/5.0'}
    urls = [
        "https://finance.yahoo.com/news/rssindex",
        "https://www.cnbc.com/id/100003114/device/rss/rss.html",
        "https://feeds.a.dj.com/rss/RSSMarketsMain.xml"
    ]
    items = []
    seen = set()
    for url in urls:
        try:
            r = requests.get(url, headers=headers, timeout=2)
            root = ET.fromstring(r.content)
            for item in root.findall('.//item')[:5]:
                t = item.find('title').text
                l = item.find('link').text
                if t and t not in seen:
                    seen.add(t)
                    items.append({"title": t, "link": l})
        except: continue
    return items

def analyze_batch(items, client):
    if not items: return []
    p_list = ""
    for i, item in enumerate(items):
        p_list += f"{i+1}. {item['title']}\n"
    prompt = f"Analyze {len(items)} headlines. Format: Ticker | Signal (🟢/🔴/⚪) | Reason. Headlines:\n{p_list}"
    try:
        resp = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role":"user", "content":prompt}], max_tokens=400)
        lines = resp.choices[0].message.content.strip().split("\n")
        enrich = []
        idx = 0
        for l in lines:
            parts = l.split("|")
            if len(parts) >= 3 and idx < len(items):
                enrich.append({"ticker": parts[0].strip(), "signal": parts[1].strip(), "reason": parts[2].strip(), "title": items[idx]['title'], "link": items[idx]['link']})
                idx += 1
        return enrich
    except: return []

with tab3:
    st.subheader("🚨 Global Wire (Yahoo/CNBC/WSJ)")
    if st.button("Generate AI Report", type="primary"):
        if not OPENAI_KEY: st.error("Enter OpenAI Key")
        else:
            with st.spinner("Scanning Markets..."):
                raw = fetch_rss_items()
                res = analyze_batch(raw, OpenAI(api_key=OPENAI_KEY))
                st.session_state['news_results'] = res
    if st.session_state.get('news_results'):
        for r in st.session_state['news_results']:
            st.markdown(f"**{r['ticker']} {r['signal']}** - [{r['title']}]({r['link']})")
            st.caption(r['reason'])
            st.divider()

if st.session_state['live_mode']:
    time.sleep(15)
    st.rerun()

st.success("✅ System Ready (v6.0 - Unified Sync + Pro News)")
