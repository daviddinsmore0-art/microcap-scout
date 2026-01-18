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

# --- INITIALIZE SESSION STATE ---
if 'market_data' not in st.session_state: st.session_state['market_data'] = {}
if 'last_update' not in st.session_state: st.session_state['last_update'] = "Not started"
if 'live_mode' not in st.session_state: st.session_state['live_mode'] = False
if 'news_results' not in st.session_state: st.session_state['news_results'] = []

# --- CONFIGURATION & LISTS ---
if "OPENAI_KEY" in st.secrets:
    OPENAI_KEY = st.secrets["OPENAI_KEY"]
else:
    st.sidebar.header("🔑 Login")
    OPENAI_KEY = st.sidebar.text_input("OpenAI Key", type="password")

st.sidebar.header("⚡ Penny Pulse")

# Watchlist Management
query_params = st.query_params
if "watchlist" in query_params:
    saved_watchlist = query_params["watchlist"]
else:
    saved_watchlist = "SPY, AAPL, NVDA, TSLA, AMD, PLTR, BTC-USD, JNJ"

user_input = st.sidebar.text_input("Add Tickers", value=saved_watchlist)
if user_input != saved_watchlist:
    st.query_params["watchlist"] = user_input

watchlist_list = [x.strip().upper() for x in user_input.split(",")]

# Portfolio
MY_PORTFOLIO = {
    "HIVE": {"entry": 3.19, "date": "Jan 7"},
    "BAER": {"entry": 1.86, "date": "Dec 31"},
    "TX":   {"entry": 38.10, "date": "Dec 29"},
    "IMNN": {"entry": 3.22, "date": "Dec 29"}, 
    "RERE": {"entry": 5.31, "date": "Dec 29"}
}

ALL_ASSETS = list(set(watchlist_list + list(MY_PORTFOLIO.keys())))
MACRO_TICKERS = ["SPY", "^IXIC", "^DJI", "BTC-USD"]

# Symbol Mapping
SYMBOL_NAMES = {
    "TSLA": "Tesla", "NVDA": "Nvidia", "BTC-USD": "Bitcoin", "AMD": "AMD",
    "PLTR": "Palantir", "AAPL": "Apple", "MSFT": "Microsoft", "GOOGL": "Google",
    "AMZN": "Amazon", "META": "Meta", "NFLX": "Netflix", "SPY": "S&P 500",
    "QQQ": "Nasdaq", "IWM": "Russell 2k", "DIA": "Dow Jones", "^DJI": "Dow Jones",
    "^IXIC": "Nasdaq", "^GSPTSE": "TSX Composite", "GC=F": "Gold", "SI=F": "Silver",
    "CL=F": "Crude Oil", "HIVE": "HIVE Digital", "RERE": "ATRenew", "TX": "Ternium",
    "UAL": "United Airlines", "PG": "Procter & Gamble", "TMQ": "Trilogy Metals",
    "VCIG": "VCI Global", "TD.TO": "TD Bank", "CCO.TO": "Cameco", "IVN.TO": "Ivanhoe Mines",
    "BN.TO": "Brookfield", "NKE": "Nike", "JNJ": "Johnson & Johnson"
}

# --- ⚡ CORE DATA ENGINE (RUNS FIRST) ---
def update_market_data():
    """Fetches data for ALL assets and updates Session State before UI renders."""
    temp_data = {}
    targets = list(set(ALL_ASSETS + MACRO_TICKERS))
    
    for symbol in targets:
        clean_symbol = symbol.strip().upper()
        try:
            ticker = yf.Ticker(clean_symbol)
            price = 0.0
            prev_close = 0.0
            found = False
            
            # 1. CRYPTO FAST PATH
            if clean_symbol.endswith("-USD"):
                try:
                    hist = ticker.history(period="1d", interval="1m")
                    if not hist.empty:
                        price = hist['Close'].iloc[-1]
                        prev_close = hist['Open'].iloc[0]
                        found = True
                except: pass
            
            # 2. STOCK FAST PATH
            if not found:
                try:
                    price = ticker.fast_info['last_price']
                    prev_close = ticker.fast_info['previous_close']
                    found = True
                except:
                    # 3. STOCK SLOW PATH (Fallback)
                    try:
                        hist = ticker.history(period="5d")
                        if not hist.empty:
                            price = hist['Close'].iloc[-1]
                            prev_close = hist['Close'].iloc[-2]
                            found = True
                    except: pass
            
            if found:
                # Basic Math
                delta = ((price - prev_close) / prev_close) * 100 if prev_close > 0 else 0.0
                
                # Extended Info (RSI/Vol) - Optional, doesn't break loop if fails
                vol_str = "N/A"
                rsi_val = 50
                trend = "WAIT"
                
                try:
                    hist_mo = ticker.history(period="1mo")
                    if not hist_mo.empty:
                        v_raw = hist_mo['Volume'].iloc[-1]
                        if v_raw >= 1_000_000: vol_str = f"{v_raw/1_000_000:.1f}M"
                        elif v_raw >= 1_000: vol_str = f"{v_raw/1_000:.1f}K"
                        else: vol_str = str(v_raw)
                        
                        if len(hist_mo) >= 14:
                            d = hist_mo['Close'].diff()
                            g, l = d.where(d>0,0).rolling(14).mean(), -d.where(d<0,0).rolling(14).mean()
                            rsi_val = 100 - (100/(1 + (g/l))).iloc[-1]
                            
                            e12 = hist_mo['Close'].ewm(span=12).mean()
                            e26 = hist_mo['Close'].ewm(span=26).mean()
                            trend = ":green[BULL]" if (e12 - e26).iloc[-1] > 0 else ":red[BEAR]"
                except: pass

                # Formatting
                is_crypto = clean_symbol.endswith("-USD")
                if is_crypto:
                    c = "green" if delta >= 0 else "red"
                    ext = f"**⚡ Live: ${price:,.2f} (:{c}[{delta:+.2f}%])**"
                else:
                    ext = f"**🌙 Ext: ${price:,.2f} (:gray[Market Closed])**"

                temp_data[clean_symbol] = {
                    "price": price, "delta": delta, "vol": vol_str,
                    "rsi": rsi_val, "trend": trend, "ext": ext, "valid": True
                }
            else:
                # Zombie Data
                temp_data[clean_symbol] = {"valid": False}
                
        except:
            temp_data[clean_symbol] = {"valid": False}
    
    st.session_state['market_data'] = temp_data
    st.session_state['last_update'] = datetime.now().strftime("%H:%M:%S")

# --- CONTROL LOGIC ---
# If Live Mode is ON, we update data BEFORE drawing anything
if st.session_state['live_mode']:
    with st.spinner("Refreshing Market Data..."):
        update_market_data()

# --- UI DRAWING ---
c1, c2 = st.columns([3, 1])
with c1:
    st.markdown(f"## ⚡ Penny Pulse :red[● LIVE] <span style='font-size:14px; color:gray'>Updated: {st.session_state['last_update']}</span>", unsafe_allow_html=True)
with c2:
    if st.toggle("🔴 LIVE DATA", key="live_toggle", value=st.session_state['live_mode']):
        st.session_state['live_mode'] = True
    else:
        st.session_state['live_mode'] = False

# Ticker Tape (Reads from Session State)
tape_html = []
for t in MACRO_TICKERS:
    d = st.session_state['market_data'].get(t, {})
    if d.get("valid"):
        c = "#4caf50" if d['delta'] >= 0 else "#f44336"
        a = "▲" if d['delta'] >= 0 else "▼"
        n = SYMBOL_NAMES.get(t, t)
        tape_html.append(f"<span style='margin-right:40px; font-weight:900; color:white;'>{n}: <span style='color:{c};'>${d['price']:,.2f} {a} {d['delta']:.2f}%</span></span>")
    else:
        tape_html.append(f"<span style='margin-right:40px; color:gray;'>{t}: ...</span>")

st.markdown(f"""
<div style='background:#0e1117; padding:12px; border-bottom:2px solid #444; overflow:hidden; white-space:nowrap;'>
    {''.join(tape_html)}
</div>""", unsafe_allow_html=True)

# Tabs
tab1, tab2, tab3 = st.tabs(["🏠 Dashboard", "🚀 Portfolio", "📰 News"])

with tab1:
    st.subheader("My Watchlist")
    cols = st.columns(3)
    for i, t in enumerate(watchlist_list):
        with cols[i % 3]:
            d = st.session_state['market_data'].get(t, {})
            if d.get("valid"):
                st.metric(t, f"${d['price']:,.2f}", f"{d['delta']:.2f}%")
                st.markdown(f"**Vol: {d['vol']} | RSI: {d['rsi']:.0f} | {d['trend']}**")
                st.markdown(d['ext'])
                st.divider()
            else:
                st.warning(f"{t} Loading/Offline...")

with tab2:
    st.subheader("My Picks")
    cols = st.columns(3)
    for i, (t, info) in enumerate(MY_PORTFOLIO.items()):
        with cols[i % 3]:
            d = st.session_state['market_data'].get(t, {})
            if d.get("valid"):
                ret = ((d['price'] - info['entry']) / info['entry']) * 100
                st.metric(f"{t}", f"${d['price']:,.2f}", f"{ret:.2f}% (Total)")
                st.markdown(f"**Entry: ${info['entry']} | {d['trend']}**")
                st.markdown(d['ext'])
                st.divider()

# --- REFRESH TIMER ---
if st.session_state['live_mode']:
    time.sleep(15)
    st.rerun()

st.success("✅ System Ready (v6.1 - Sync-Wait)")
