import streamlit as st
import requests
import yfinance as yf
import pandas as pd
from openai import OpenAI
from datetime import datetime, timedelta

# --- CONFIGURATION ---
st.set_page_config(page_title="PennyPulse Pro", page_icon="⚡", layout="wide")

# --- 1. KEY LOADER ---
if "FINNHUB_KEY" in st.secrets:
    FINNHUB_KEY = st.secrets["FINNHUB_KEY"]
    OPENAI_KEY = st.secrets["OPENAI_KEY"]
else:
    st.sidebar.header("🔑 Login")
    FINNHUB_KEY = st.sidebar.text_input("Finnhub Key", type="password")
    OPENAI_KEY = st.sidebar.text_input("OpenAI Key", type="password")

# --- 2. SETTINGS ---
st.sidebar.divider()
st.sidebar.header("⚡ Watchlist")
user_input = st.sidebar.text_input("My Portfolio", value="TSLA, NVDA, GME, BTC-USD")
stock_list = [x.strip().upper() for x in user_input.split(",")]

# DEBUG TOGGLE
show_raw = st.sidebar.checkbox("Show Raw Feed (Debug Mode)", value=False)

st.title("⚡ PennyPulse Pro")
st.caption("Quant Data + Fail-Safe News Wire")

# --- FUNCTIONS ---
def get_ai_analysis(headline, client):
    try:
        # Simplified Prompt
        prompt = f"""
        Headline: "{headline}"
        Task: Extract Ticker (e.g. AAPL) and Sentiment (Bullish/Bearish).
        If no specific ticker, use "MARKET".
        Format: Ticker | Signal | Reason
        """
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=50
        )
        return response.choices[0].message.content.strip()
    except:
        return "MARKET | ⚪ | AI Busy"

def fetch_quant_data(symbol):
    try:
        ticker = yf.Ticker(symbol)
        history = ticker.history(period="3mo", interval="1d", prepost=True)
        if history.empty: return None

        # Indicators
        delta = history['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        history['RSI'] = 100 - (100 / (1 + rs))

        ema12 = history['Close'].ewm(span=12, adjust=False).mean()
        ema26 = history['Close'].ewm(span=26, adjust=False).mean()
        history['MACD'] = ema12 - ema26
        history['Signal'] = history['MACD'].ewm(span=9, adjust=False).mean()

        latest = history.iloc[-1]
        prev = history.iloc[-2]
        delta_pct = ((latest['Close'] - prev['Close']) / prev['Close']) * 100
        
        return {
            "price": latest['Close'],
            "delta": delta_pct,
            "rsi": latest['RSI'],
            "macd": latest['MACD'],
            "macd_sig": latest['Signal']
        }
    except:
        return None

def fetch_general_news(api_key):
    all_news = []
    # Fetch General + Crypto
    for cat in ["general", "crypto"]:
        try:
            url = f"https://finnhub.io/api/v1/news?category={cat}&token={api_key}"
            data = requests.get(url).json()
            if isinstance(data, list):
                all_news.extend(data)
        except: pass
    
    all_news.sort(key=lambda x: x.get('datetime', 0), reverse=True)
    return all_news[:25] # Limit to 25 to be safe

# --- MAIN APP ---
if st.button("🚀 Run Analysis"):
    if not FINNHUB_KEY or not OPENAI_KEY:
        st.error("⚠️ Enter API Keys in Sidebar!")
    else:
        client = OpenAI(api_key=OPENAI_KEY)
        tab1, tab2 = st.tabs(["📊 My Portfolio", "🌎 News Wire"])

        # --- TAB 1: QUANT DASHBOARD ---
        with tab1:
            st.subheader("Your Watchlist")
            for symbol in stock_list:
                data = fetch_quant_data(symbol)
                if data:
                    rsi_sig = "🔴 Overbought" if data['rsi'] > 70 else ("🟢 Oversold" if data['rsi'] < 30 else "⚪ Neutral")
                    macd_sig = "🟢 Bullish" if data['macd'] > data['macd_sig'] else "🔴 Bearish"
                    color = "green" if data['delta'] > 0 else "red"
                    
                    c1, c2, c3 = st.columns([1.5, 1, 1])
                    with c1:
                        st.markdown(f"### {symbol}")
                        st.markdown(f"<span style='color:{color}; font-size: 24px; font-weight:bold'>${data['price']:,.2f}</span> ({data['delta']:.2f}%)", unsafe_allow_html=True)
                    with c2:
                        st.caption("RSI")
                        st.write(f"**{data['rsi']:.0f}** {rsi_sig}")
                    with c3:
                        st.caption("MACD")
                        st.write(f"{macd_sig}")
                    st.divider()

        # --- TAB 2: NEWS WIRE ---
        with tab2:
            st.subheader("🚨 Global Wire")
            
            # 1. Fetch
            raw_news = fetch_general_news(FINNHUB_KEY)
            
            # DEBUG MESSAGE (So you know it worked)
            if len(raw_news) == 0:
                st.error("⚠️ Finnhub API returned 0 stories. Check API limits.")
            else:
                st.caption(f"⚡ Fetched {len(raw_news)} raw stories from the wire.")

            # 2. Process
            # If "Debug Mode" is ON, we show everything without AI (Fastest)
            if show_raw:
                for item in raw_news:
                    st.markdown(f"**{item['headline']}**")
                    st.caption(f"Source: {item['source']}")
                    st.divider()
            
            # Normal Mode: AI Analysis
            else:
                count = 0
                for item in raw_news:
                    headline = item['headline']
                    
                    # Direct AI Check (No Python Filter)
                    ai_result = get_ai_analysis(headline, client)
                    
                    parts = ai_result.split("|")
                    if len(parts) == 3:
                        ticker, signal, reason = parts[0].strip(), parts[1].strip(), parts[2].strip()
                        
                        with st.container():
                            c1, c2 = st.columns([1, 4])
                            with c1:
                                st.markdown(f"## {ticker}")
                                st.caption(f"{signal}")
                            with c2:
                                st.markdown(f"**{headline}**")
                                st.info(f"{reason}")
                            st.divider()
                        count += 1
                        
                    # Stop after 10 stories to keep it fast
                    if count >= 10: break
                
                if count == 0 and len(raw_news) > 0:
                    st.warning("AI filtered out all stories (or API returned generic news). Try checking 'Show Raw Feed' in the sidebar.")
