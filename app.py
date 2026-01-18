import streamlit as st
import yfinance as yf
import pandas as pd
import time
from datetime import datetime

# --- CONFIGURATION ---
st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="wide")

# --- SESSION STATE SETUP ---
if 'live_mode' not in st.session_state: st.session_state['live_mode'] = False

# --- 🗓️ MANUAL EARNINGS LIST ---
# Kept clean and simple. No logic, just data.
MANUAL_EARNINGS = {
    "TMQ": "2026-02-13",
    "NFLX": "2026-01-20",
    "PG": "2026-01-22",
    "UAL": "2026-01-21",
    "JNJ": "2026-01-21"
}

# --- 💼 SHARED PORTFOLIO ---
MY_PORTFOLIO = {
    "HIVE": {"entry": 3.19, "date": "Jan 7"},
    "BAER": {"entry": 1.86, "date": "Dec 31"},
    "TX":   {"entry": 38.10, "date": "Dec 29"},
    "IMNN": {"entry": 3.22, "date": "Dec 29"}, 
    "RERE": {"entry": 5.31, "date": "Dec 29"}
}

# --- SIDEBAR ---
st.sidebar.header("⚡ Penny Pulse")

# --- 🧠 MEMORY SYSTEM ---
query_params = st.query_params
if "watchlist" in query_params:
    saved_watchlist = query_params["watchlist"]
else:
    saved_watchlist = "SPY, AAPL, NVDA, TSLA, AMD, PLTR, BTC-USD"

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

# --- ⚡ BATCH LOADER (CACHE LOGIC) ---
# Normal Mode: Cache for 60s to save data.
@st.cache_data(ttl=60)
def load_market_data_cached(tickers):
    if not tickers: return None
    try:
        return yf.download(tickers, period="1mo", group_by='ticker', progress=False, threads=True)
    except: return None

# Live Mode: NO CACHE. Grabs fresh data instantly.
def load_market_data_live(tickers):
    if not tickers: return None
    try:
        return yf.download(tickers, period="1mo", group_by='ticker', progress=False, threads=True)
    except: return None

# --- DECISION ENGINE ---
# This is the fix. If Live Mode is ON, we bypass the cache and trigger a loop.
if st.session_state['live_mode']:
    BATCH_DATA = load_market_data_live(ALL_ASSETS)
    # The heartbeat: Wait 3 seconds, then force reload
    time.sleep(3) 
    st.rerun()
else:
    BATCH_DATA = load_market_data_cached(ALL_ASSETS)

# --- FUNCTIONS ---
def get_live_price_macro(symbol):
    # Specialized fetch for the top ticker tape (lighter weight)
    try:
        ticker = yf.Ticker(symbol)
        price = ticker.fast_info['last_price']
        prev = ticker.fast_info['previous_close']
        delta = ((price - prev) / prev) * 100
        return price, delta
    except: return 0.0, 0.0

def fetch_from_batch(symbol):
    try:
        clean_symbol = symbol.strip().upper()
        
        # 1. EXTRACT DATAFRAME
        df = None
        if BATCH_DATA is not None:
            if isinstance(BATCH_DATA.columns, pd.MultiIndex):
                if clean_symbol in BATCH_DATA.columns.levels[0]:
                    df = BATCH_DATA[clean_symbol].copy()
            elif clean_symbol == ALL_ASSETS[0]: 
                df = BATCH_DATA.copy()

        if df is None or df.empty: return None
        df = df.dropna(subset=['Close'])
        if df.empty: return None

        # 2. PRICE MATH
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
        
        # 3. RSI INDICATOR
        rsi_val = 50
        trend_str = ":gray[**WAIT**]"
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
                if macd.iloc[-1] > 0: trend_str = ":green[**BULL**]" 
                else: trend_str = ":red[**BEAR**]"
        except: pass

        # 4. EARNINGS (MANUAL ONLY)
        earnings_msg = ""
        next_date = None
        if clean_symbol in MANUAL_EARNINGS:
            try:
                next_date = datetime.strptime(MANUAL_EARNINGS[clean_symbol], "%Y-%m-%d")
            except: pass

        if next_date:
            if hasattr(next_date, "replace"): next_date = next_date.replace(tzinfo=None)
            now = datetime.now().replace(tzinfo=None)
            days_diff = (next_date - now).days
            
            if -1 <= days_diff <= 8:
                earnings_msg = f":rotating_light: **Earnings: {days_diff} Days!**"
            elif 8 < days_diff <= 90:
                fmt_date = next_date.strftime("%b %d")
                earnings_msg = f":calendar: **Earn: {fmt_date}**"

        return {
            "reg_price": reg_price, "day_delta": day_pct, "ext_str": ext_str,
            "volume": volume, "rsi": rsi_val, "trend": trend_str, "earn_str": earnings_msg
        }
    except: return None

def format_volume(num):
    if num >= 1_000_000: return f"{num/1_000_000:.1f}M"
    if num >= 1_000: return f"{num/1_000:.1f}K"
    return str(num)

# --- UI LAYOUT ---
st.title("⚡ Penny Pulse")

MACRO_TICKERS = ["SPY", "^IXIC", "^DJI", "BTC-USD"]
ticker_items = []
for tick in MACRO_TICKERS:
    p, d = get_live_price_macro(tick)
    c = "#4caf50" if d >= 0 else "#f44336"
    a = "▲" if d >= 0 else "▼"
    ticker_items.append(f"<span style='margin-right:20px; font-size:18px;'>{tick}: <span style='color:{c};'>${p:,.2f} {a} {d:.2f}%</span></span>")
st.markdown(f"<div style='background:#0e1117; padding:10px; border-bottom:1px solid #333;'>{' '.join(ticker_items)}</div>", unsafe_allow_html=True)

tab1, tab2 = st.tabs(["🏠 Dashboard", "🚀 My Portfolio"])

with tab1:
    c1, c2 = st.columns([3, 1])
    with c1:
        st.subheader("My Watchlist")
        st.caption(f"Tracking: {', '.join(watchlist_list)}")
    with c2:
        # LIVE SWITCH
        live_on = st.toggle("🔴 LIVE DATA", key="live_mode_toggle")
        if live_on: st.session_state['live_mode'] = True
        else: st.session_state['live_mode'] = False

    # ALERT CHECK
    if alert_active and BATCH_DATA is not None:
        try:
            if isinstance(BATCH_DATA.columns, pd.MultiIndex):
                if alert_ticker in BATCH_DATA.columns.levels[0]:
                    curr = BATCH_DATA[alert_ticker]['Close'].iloc[-1]
            elif alert_ticker == ALL_ASSETS[0]: curr = BATCH_DATA['Close'].iloc[-1]
            
            if 'curr' in locals() and curr >= alert_price:
                st.toast(f"🚨 ALERT: {alert_ticker} HIT ${curr:,.2f}!", icon="🔥")
        except: pass

    cols = st.columns(3)
    for i, tick in enumerate(watchlist_list):
        with cols[i % 3]:
            data = fetch_from_batch(tick)
            if data:
                vol = format_volume(data['volume'])
                rsi = data['rsi']
                if rsi > 70: rsi_s = f"{rsi:.0f} (🔥)"
                elif rsi < 30: rsi_s = f"{rsi:.0f} (🧊)"
                else: rsi_s = f"{rsi:.0f}"
                
                st.metric(label=f"{tick}", value=f"${data['reg_price']:,.2f}", delta=f"{data['day_delta']:.2f}%")
                st.caption(f"Vol: {vol} | RSI: {rsi_s} | {data['trend']}")
                if data['earn_str']: st.markdown(data['earn_str'])
                st.divider()
            else: st.warning(f"{tick} Loading...")

with tab2:
    st.subheader("My Picks")
    cols = st.columns(3)
    for i, (tick, info) in enumerate(MY_PORTFOLIO.items()):
        with cols[i % 3]:
            data = fetch_from_batch(tick)
            if data:
                curr = data['reg_price']
                ret = ((curr - info['entry']) / info['entry']) * 100
                st.metric(label=f"{tick}", value=f"${curr:,.2f}", delta=f"{ret:.2f}% (Total)")
                st.caption(f"Entry: ${info['entry']} | {data['trend']}")
                if data['earn_str']: st.markdown(data['earn_str'])
                st.divider()

if st.session_state['live_mode']:
    st.toast("⚡ Live Updating (3s)...")

st.success("✅ System Ready (v4.8 - Heartbeat Active)")
