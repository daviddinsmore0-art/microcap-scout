import streamlit as st
import requests
import yfinance as yf
import xml.etree.Tree as ET
import time
import pandas as pd
from openai import OpenAI

# --- CONFIGURATION ---
st.set_page_config(page_title="PennyPulse Pro", page_icon="⚡", layout="wide")

if 'news_results' not in st.session_state: st.session_state['news_results'] = []
if 'news_error' not in st.session_state: st.session_state['news_error'] = None

if "OPENAI_KEY" in st.secrets:
    OPENAI_KEY = st.secrets["OPENAI_KEY"]
else:
    st.sidebar.header("🔑 Login")
    OPENAI_KEY = st.sidebar.text_input("OpenAI Key", type="password")

# --- GLOBAL SETTINGS ---
MARKET_TICKERS = ["SPY", "QQQ", "IWM", "BTC-USD", "ETH-USD", "GC=F", "CL=F"]

st.sidebar.divider()
st.sidebar.header("🚀 My Picks")
user_input = st.sidebar.text_input("Edit Tickers", value="TSLA, NVDA, GME, BTC-USD")
my_picks_list = [x.strip().upper() for x in user_input.split(",")]

st.sidebar.divider()
st.sidebar.header("📈 Chart Room")
all_tickers = sorted(list(set(MARKET_TICKERS + my_picks_list)))
chart_ticker = st.sidebar.selectbox("Select Asset to Chart", all_tickers)

st.title("⚡ PennyPulse Pro")

TICKER_MAP = {
    "TESLA": "TSLA", "NVIDIA": "NVDA", "APPLE": "AAPL", "MICROSOFT": "MSFT", 
    "GOOGLE": "GOOGL", "AMAZON": "AMZN", "META": "META", "BITCOIN": "BTC-USD", 
    "GOLD": "GC=F", "OIL": "CL=F", "JPMORGAN": "JPM", "BOEING": "BA"
}

# --- CORE FUNCTIONS ---
def get_live_price(symbol):
    try:
        ticker = yf.Ticker(symbol)
        price = ticker.fast_info['last_price']
        prev = ticker.fast_info['previous_close']
        delta = ((price - prev) / prev) * 100
        return price, delta
    except: return 0.0, 0.0

def fetch_quant_data(symbol):
    try:
        ticker = yf.Ticker(symbol)
        history = ticker.history(period="3mo", interval="1d", prepost=True)
        if history.empty: return None
        live_price = history['Close'].iloc[-1]
        prev_close = history['Close'].iloc[-2]
        delta_pct = ((live_price - prev_close) / prev_close) * 100
        volume = history['Volume'].iloc[-1]
        
        delta = history['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return {"price": live_price, "delta": delta_pct, "volume": volume, "rsi": rsi.iloc[-1]}
    except: return None

# --- TABS ---
tab1, tab2, tab3, tab4 = st.tabs(["🏠 Dashboard", "🚀 My Picks", "📰 News", "📈 Chart Room"])

with tab1:
    st.subheader("Major Indices")
    live_on = st.toggle("🔴 Enable Live Prices", key="live_market")
    cols = st.columns(3)
    for i, tick in enumerate(MARKET_TICKERS):
        with cols[i % 3]:
            data = fetch_quant_data(tick)
            if data: st.metric(label=tick, value=f"${data['price']:,.2f}", delta=f"{data['delta']:.2f}%")

with tab2:
    st.subheader("My Portfolio")
    cols = st.columns(3)
    for i, tick in enumerate(my_picks_list):
        with cols[i % 3]:
            data = fetch_quant_data(tick)
            if data: st.metric(label=tick, value=f"${data['price']:,.2f}", delta=f"{data['delta']:.2f}%")

with tab4:
    st.subheader(f"📈 Chart: {chart_ticker}")
    live_chart = st.toggle("🔴 Enable Live Chart (Refresh every 5s)", key="live_chart")
    chart_container = st.empty()
    
    def draw_chart():
        try:
            tick_obj = yf.Ticker(chart_ticker)
            # Fetch intraday data
            chart_data = tick_obj.history(period="1d", interval="5m")
            if chart_data.empty: chart_data = tick_obj.history(period="5d", interval="15m")

            if not chart_data.empty:
                # SCRUBBER: Drop any corrupted data points at market open
                chart_data = chart_data.dropna().reset_index()
                chart_data.columns = ['Time'] + list(chart_data.columns[1:])
                
                with chart_container:
                    # NATIVE CHART: More robust than Altair for live updates
                    st.line_chart(chart_data.set_index('Time')['Close'])
                    
                    curr = chart_data['Close'].iloc[-1]
                    diff = curr - chart_data['Close'].iloc[0]
                    col = "green" if diff >= 0 else "red"
                    st.markdown(f"### Current: ${curr:,.2f} | Move: :{col}[${diff:,.2f}]")
            else:
                with chart_container: st.warning("Syncing Market Data...")
        except Exception as e:
            with chart_container: st.error(f"Sync Issue: {e}")

    draw_chart()
    if live_chart:
        while True:
            time.sleep(5)
            draw_chart()

st.success("✅ System Ready (Optimized Layout)")
