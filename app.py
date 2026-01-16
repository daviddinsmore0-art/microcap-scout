import streamlit as st
import requests
import yfinance as yf
import xml.etree.ElementTree as ET
import time
import pandas as pd
import altair as alt  # <--- Added for Smart Charts
from openai import OpenAI

# --- CONFIGURATION ---
st.set_page_config(page_title="PennyPulse Pro", page_icon="⚡", layout="wide")

if 'live_mode' not in st.session_state: st.session_state['live_mode'] = False
if 'news_results' not in st.session_state: st.session_state['news_results'] = []
if 'news_error' not in st.session_state: st.session_state['news_error'] = None

if "OPENAI_KEY" in st.secrets:
    OPENAI_KEY = st.secrets["OPENAI_KEY"]
else:
    st.sidebar.header("🔑 Login")
    OPENAI_KEY = st.sidebar.text_input("OpenAI Key", type="password")

# --- SETTINGS ---
st.sidebar.divider()
st.sidebar.header("🚀 My Picks")
user_input = st.sidebar.text_input("Edit Tickers", value="TSLA, NVDA, GME, BTC-USD")
my_picks_list = [x.strip().upper() for x in user_input.split(",")]

st.sidebar.divider()
st.sidebar.header("📈 Chart Room")
chart_ticker = st.sidebar.selectbox("Select Asset", my_picks_list + ["SPY", "BTC-USD"])

MARKET_TICKERS = ["SPY", "QQQ", "IWM", "BTC-USD", "ETH-USD", "GC=F", "CL=F"]

st.title("⚡ PennyPulse Pro")

# --- INSTANT TICKER MAP ---
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
    "JPMORGAN": "JPM", "GOLDMAN": "GS", "BOEING": "BA"
}

# --- FUNCTIONS ---
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

        try:
            live_price = ticker.fast_info['last_price']
            prev_close = ticker.fast_info['previous_close']
            delta_pct = ((live_price - prev_close) / prev_close) * 100
        except:
            live_price = history['Close'].iloc[-1]
            prev_close = history['Close'].iloc[-2]
            delta_pct = ((live_price - prev_close) / prev_close) * 100

        delta = history['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        history['RSI'] = 100 - (100 / (1 + rs))

        ema12 = history['Close'].ewm(span=12, adjust=False).mean()
        ema26 = history['Close'].ewm(span=26, adjust=False).mean()
        history['MACD'] = ema12 - ema26
        history['Signal'] = history['MACD'].ewm(span=9, adjust=False).mean()

        return {
            "price": live_price,
            "delta": delta_pct,
            "rsi": history['RSI'].iloc[-1],
            "macd": history['MACD'].iloc[-1],
            "macd_sig": history['Signal'].iloc[-1]
        }
    except: return None

def display_ticker_grid(ticker_list, live_mode=False):
    if live_mode:
        st.info("🔴 Live Streaming Active. Uncheck to stop.")
        price_containers = {}
        cols = st.columns(4)
        for i, tick in enumerate(ticker_list):
            with cols[i % 4]:
                price_containers[tick] = st.empty()
        
        while True:
            for tick, container in price_containers.items():
                price, delta = get_live_price(tick)
                with container:
                    st.metric(label=tick, value=f"${price:,.2f}", delta=f"{delta:.2f}%")
            time.sleep(2)
    else:
        cols = st.columns(3)
        for i, tick in enumerate(ticker_list):
            with cols[i % 3]:
                data = fetch_quant_data(tick)
                if data:
                    rsi_sig = "🔴 Over" if data['rsi'] > 70 else ("🟢 Under" if data['rsi'] < 30 else "⚪ Neut")
                    macd_
