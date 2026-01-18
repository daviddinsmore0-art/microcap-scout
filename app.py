import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from openai import OpenAI

# --- CONFIGURATION ---
try:
    st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="wide")
except: pass

# --- SESSION STATE ---
if 'live_mode' not in st.session_state: st.session_state['live_mode'] = False
if 'last_update' not in st.session_state: st.session_state['last_update'] = datetime.now().strftime("%H:%M:%S")
if 'news_results' not in st.session_state: st.session_state['news_results'] = []

# --- 💼 SHARED PORTFOLIO ---
MY_PORTFOLIO = {
    "HIVE": {"entry": 3.19, "date": "Jan 7"},
    "BAER": {"entry": 1.86, "date": "Dec 31"},
    "TX":   {"entry": 38.10, "date": "Dec 29"},
    "IMNN": {"entry": 3.22, "date": "Dec 29"}, 
    "RERE": {"entry": 5.31, "date": "Dec 29"}
}

if "OPENAI_KEY" in st.secrets:
    OPENAI_KEY = st.secrets["OPENAI_KEY"]
else:
    st.sidebar.header("🔑 Login")
    OPENAI_KEY = st.sidebar.text_input("OpenAI Key", type="password")

# --- SIDEBAR ---
st.sidebar.header("⚡ Penny Pulse")

# --- 🧠 MEMORY SYSTEM ---
query_params = st.query_params
if "watchlist" in query_params:
    saved_watchlist = query_params["watchlist"]
else:
    saved_watchlist = "SPY, AAPL, NVDA, TSLA, AMD, PLTR, BTC-USD, JNJ"

user_input = st.sidebar.text_input("Add Tickers", value=saved_watchlist)
if user_input != saved_watchlist:
    st.query_params["watchlist"] = user_input

watchlist_list = [x.strip().upper() for x in user_input.split(",")]
ALL_ASSETS = list(set(watchlist_list + list(MY_PORTFOLIO.keys())))

st.sidebar.divider()
st.sidebar.header("🔔 Price Alert")
alert_ticker = st.sidebar.selectbox("Alert Asset", sorted(ALL_ASSETS))
alert_price = st.sidebar.number_input("Target Price ($)", min_value=0.0, value=0.0, step=0.5)
alert_active = st.sidebar.toggle("Activate Alert")

# --- SYMBOL NAMES ---
SYMBOL_NAMES = {
    "TSLA": "Tesla", "NVDA": "Nvidia", "BTC-USD": "Bitcoin",
    "AMD": "AMD", "PLTR": "Palantir", "AAPL": "Apple", "MSFT": "Microsoft",
    "GOOGL": "Google", "AMZN": "Amazon", "META": "Meta", "NFLX": "Netflix",
    "SPY": "S&P 500", "QQQ": "Nasdaq", "IWM": "Russell 2k", "DIA": "Dow Jones",
    "^DJI": "Dow Jones", "^IXIC": "Nasdaq", "^GSPTSE": "TSX Composite",
    "GC=F": "Gold", "SI=F": "Silver", "CL=F": "Crude Oil", "DX-Y.NYB": "USD Index", "^VIX": "VIX",
    "HIVE": "HIVE Digital", "RERE": "ATRenew", "TX": "Ternium", "UAL": "United Airlines", "PG": "Procter & Gamble",
    "TMQ": "Trilogy Metals", "VCIG": "VCI Global", "TD.TO": "TD Bank", "CCO.TO": "Cameco", "IVN.TO": "Ivanhoe Mines", "BN.TO": "Brookfield", "NKE": "Nike",
    "JNJ": "Johnson & Johnson"
}

# --- TICKER MAP (Restored) ---
TICKER_MAP = {
    "TESLA": "TSLA", "MUSK": "TSLA", "CYBERTRUCK": "TSLA",
    "NVIDIA": "NVDA", "JENSEN": "NVDA", "AI CHIP": "NVDA",
    "APPLE": "AAPL", "IPHONE": "AAPL", "MAC": "AAPL",
    "MICROSOFT": "MSFT", "WINDOWS": "MSFT", "OPENAI": "MSFT",
    "GOOGLE": "GOOGL", "GEMINI": "GOOGL", "YOUTUBE": "GOOGL",
    "AMAZON": "AMZN", "AWS": "AMZN", "PRIME": "AMZN",
    "META": "META", "FACEBOOK": "META", "INSTAGRAM": "META",
    "NETFLIX": "NFLX", "DISNEY": "DIS",
    "BITCOIN": "BTC-USD", "CRYPTO": "BTC-USD", "COINBASE": "COIN",
    "GOLD": "GC=F", "OIL": "CL=F", "FED": "USD", "POWELL": "USD",
    "JPMORGAN": "JPM", "GOLDMAN": "GS", "BOEING": "BA",
    "JOHNSON": "JNJ", "J&J": "JNJ"
}

MACRO_TICKERS = ["SPY", "^IXIC", "^DJI", "BTC-USD"]

# --- ⚡ THE ENGINE (Safety Net Edition) ---

@st.cache_data(ttl=60)
def load_data_static(tickers):
    try:
        return yf.download(tickers, period="1mo", group_by='ticker', progress=False, threads=True)
    except: return None

def load_data_live(tickers):
    st.cache_data.clear() 
    try:
        return yf.download(tickers, period="1mo", group_by='ticker', progress=False, threads=True)
    except: return None

if st.session_state['live_mode']:
    BATCH_DATA = load_data_live(ALL_ASSETS)
    st.session_state['last_update'] = datetime.now().strftime("%H:%M:%S")
else:
    BATCH_DATA = load_data_static(ALL_ASSETS)

# --- FUNCTIONS ---
def get_live_price_macro(symbol):
    try:
        ticker = yf.Ticker(symbol)
        price = ticker.fast_info['last_price']
        prev = ticker.fast_info['previous_close']
        delta = ((price - prev) / prev) * 100
        return price, delta
    except: return 0.0, 0.0

def fetch_data_safe(symbol):
    # 1. TRY BATCH FIRST
    clean_symbol = symbol.strip().upper()
    df = None
    
    try:
        if BATCH_DATA is not None:
            if isinstance(BATCH_DATA.columns, pd.MultiIndex):
                if clean_symbol in BATCH_DATA.columns.levels[0]:
                    df = BATCH_DATA[clean_symbol].copy()
            elif clean_symbol == ALL_ASSETS[0]: 
                df = BATCH_DATA.copy()
    except: pass

    # 2. SAFETY NET: If Batch failed, fetch individually
    if df is None or df.empty:
        try:
            df = yf.Ticker(symbol).history(period="1mo")
        except: return None

    # 3. If still empty, give up
    if df is None or df.empty: return None
    
    # 4. Clean & Process
    df = df.dropna(subset=['Close'])
    if df.empty: return None

    reg_price = df['Close'].iloc[-1]
    if len(df) > 1: prev_close = df['Close'].iloc[-2]
    else: prev_close = df['Open'].iloc[-1]

    is_crypto = symbol.endswith("-USD") or "BTC" in symbol
    day_pct = ((reg_price - prev_close) / prev_close) * 100 if prev_close > 0 else 0.0
    
    if is_crypto:
        color = "green" if day_pct >= 0 else "red"
        ext_str = f"**⚡ Live: ${reg_price:,.2f} (:{color}[{day_pct:+.2f}%])**"
    else:
        ext_str = f"**🌙 Ext: ${reg_price:,.2f} (:gray[Market Closed])**"

    volume = df['Volume'].iloc[-1]
    
    # RSI & Trend
    rsi_val = 50
    trend_str = "WAIT"
    try:
        if len(df) >= 14:
            delta = df['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            df['RSI'] = 100 - (100 / (1 + rs))
            rsi_val = df['RSI'].iloc[-1]
            
            ema12 = df['Close'].ewm(span=12, adjust=False).mean()
            ema26 = df['Close'].ewm(span=26, adjust=False).mean()
            macd = ema12 - ema26
            if macd.iloc[-1] > 0: trend_str = ":green[BULL]" 
            else: trend_str = ":red[BEAR]"
    except: pass

    return {
        "reg_price": reg_price, "day_delta": day_pct, "ext_str": ext_str,
        "volume": volume, "rsi": rsi_val, "trend": trend_str
    }

def format_volume(num):
    if num >= 1_000_000: return f"{num/1_000_000:.1f}M"
    if num >= 1_000: return f"{num/1_000:.1f}K"
    return str(num)

# --- UI LAYOUT ---
c_head_1, c_head_2 = st.columns([3, 1])
with c_head_1:
    if st.session_state['live_mode']:
        st.markdown(f"## ⚡ Penny Pulse :red[● LIVE] <span style='font-size:14px; color:gray'>Last Update: {st.session_state['last_update']}</span>", unsafe_allow_html=True)
    else:
        st.title("⚡ Penny Pulse")

with c_head_2:
    live_on = st.toggle("🔴 LIVE DATA", key="live_mode_toggle")
    if live_on: st.session_state['live_mode'] = True
    else: st.session_state['live_mode'] = False

# --- TICKER TAPE ---
def render_ticker_tape(tickers):
    ticker_items = []
    for tick in tickers:
        p, d = get_live_price_macro(tick)
        c = "#4caf50" if d >= 0 else "#f44336"
        a = "▲" if d >= 0 else "▼"
        display_name = SYMBOL_NAMES.get(tick, tick) 
        ticker_items.append(f"<span style='display:inline-block; margin-right:50px; font-weight:900; font-size:18px; color:white;'>{display_name}: <span style='color:{c};'>${p:,.2f} {a} {d:.2f}%</span></span>")
    content_str = "".join(ticker_items)
    st.markdown(f"""
    <style>
    .ticker-container {{ width: 100%; overflow: hidden; background-color: #0e1117; border-bottom: 2px solid #444; height: 50px; display: flex; align-items: center; }}
    .ticker-text {{ display: flex; white-space: nowrap; animation: ticker-slide 60s linear infinite; }}
    @keyframes ticker-slide {{ 0% {{ transform: translateX(0); }} 100% {{ transform: translateX(-100%); }} }}
    </style>
    <div class="ticker-container"><div class="ticker-text">{content_str} &nbsp;&nbsp;&nbsp; {content_str} &nbsp;&nbsp;&nbsp; {content_str}</div></div>
    """, unsafe_allow_html=True)

render_ticker_tape(MACRO_TICKERS)

# --- TABS ---
tab1, tab2, tab3 = st.tabs(["🏠 Dashboard", "🚀 My Portfolio", "📰 News"])

if alert_active:
    try:
        res = fetch_data_safe(alert_ticker)
        if res and res['reg_price'] >= alert_price and not st.session_state.get('alert_triggered', False):
            st.toast(f"🚨 ALERT: {alert_ticker} HIT ${res['reg_price']:,.2f}!", icon="🔥")
            st.session_state['alert_triggered'] = True
    except: pass

with tab1:
    st.subheader("My Watchlist")
    st.caption(f"Tracking: {', '.join(watchlist_list)}")
    cols = st.columns(3)
    for i, tick in enumerate(watchlist_list):
        with cols[i % 3]:
            data = fetch_data_safe(tick)
            if data:
                vol = format_volume(data['volume'])
                # BOLDED STATS LINE
                st.metric(label=f"{tick}", value=f"${data['reg_price']:,.2f}", delta=f"{data['day_delta']:.2f}%")
                st.markdown(f"**Vol: {vol} | RSI: {data['rsi']:.0f} | {data['trend']}**")
                st.markdown(data['ext_str'])
                st.divider()
            else: st.warning(f"{tick} Loading...")

with tab2:
    st.subheader("My Picks")
    cols = st.columns(3)
    for i, (ticker, info) in enumerate(MY_PORTFOLIO.items()):
        with cols[i % 3]:
            data = fetch_data_safe(ticker)
            if data:
                curr = data['reg_price']
                ret = ((curr - info['entry']) / info['entry']) * 100
                st.metric(label=f"{ticker}", value=f"${curr:,.2f}", delta=f"{ret:.2f}% (Total)")
                # BOLDED STATS LINE
                st.markdown(f"**Entry: ${info['entry']} | {data['trend']}**")
                st.markdown(data['ext_str'])
                st.divider()

# --- NEWS TAB ---
def fetch_rss_items():
    headers = {'User-Agent': 'Mozilla/5.0'}
    urls = ["https://rss.app/feeds/tMfefT7whS1oe2VT.xml", "https://rss.app/feeds/T1dwxaFTbqidPRNW.xml", "https://rss.app/feeds/jjNMcVmfZ51Jieij.xml"]
    items = []
    seen = set()
    for url in urls:
        try:
            r = requests.get(url, headers=headers, timeout=2)
            root = ET.fromstring(r.content)
            for item in root.findall('.//item'):
                t = item.find('title').text
                l = item.find('link').text
                if t and t not in seen:
                    seen.add(t)
                    items.append({"title": t, "link": l})
        except: continue
    return items[:15]

def analyze_batch(items, client):
    if not items: return []
    p_list = ""
    for i, item in enumerate(items):
        hint = ""
        for k,v in TICKER_MAP.items():
            if k in item['title'].upper():
                hint = f"({v})"
                break
        p_list += f"{i+1}. {item['title']} {hint}\n"
    
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
    st.subheader("🚨 Global Wire")
    if st.button("Generate AI Report", type="primary"):
        if not OPENAI_KEY: st.error("Enter OpenAI Key")
        else:
            with st.spinner("Scanning..."):
                raw = fetch_rss_items()
                res = analyze_batch(raw, OpenAI(api_key=OPENAI_KEY))
                st.session_state['news_results'] = res
    
    if st.session_state.get('news_results'):
        for r in st.session_state['news_results']:
            st.markdown(f"**{r['ticker']} {r['signal']}** - [{r['title']}]({r['link']})")
            st.caption(r['reason'])
            st.divider()

if st.session_state['live_mode']:
    time.sleep(3)
    st.rerun()

st.success("✅ System Ready (v5.4 - Safety Net & Bold)")
