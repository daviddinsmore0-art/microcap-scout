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

# --- 2. SCANNER INPUT ---
st.sidebar.divider()
st.sidebar.header("⚡ Watchlist Scanner")
user_input = st.sidebar.text_input("My Portfolio", value="TSLA, NVDA, GME, BTC-USD")
stock_list = [x.strip().upper() for x in user_input.split(",")]

st.title("⚡ PennyPulse Pro")
st.caption("Quant Data + Global News Dragnet")

# --- FUNCTIONS ---
def get_ai_analysis(headline, context, client):
    try:
        # We ask AI to FIND the ticker in the generic news
        prompt = f"""
        Act as a Trader.
        Headline: "{headline}"
        Context: {context}
        
        Task:
        1. Identify Ticker: If a company is mentioned, give the symbol (e.g. "AAPL"). If none, write "MARKET".
        2. Signal: 🟢 (Bullish), 🔴 (Bearish), or ⚪ (Neutral).
        3. Reason: 5 words max.
        
        Format: [Ticker] | [Signal] | [Reason]
        Example: TSLA | 🔴 Bearish | Recalls affecting output.
        """
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=60
        )
        return response.choices[0].message.content.strip()
    except:
        return "MARKET | ⚪ | AI Connecting..."

def fetch_quant_data(symbol):
    try:
        ticker = yf.Ticker(symbol)
        history = ticker.history(period="3mo", interval="1d", prepost=True)
        if history.empty: return None

        # RSI & MACD Calc
        delta = history['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        history['RSI'] = 100 - (100 / (1 + rs))

        ema12 = history['Close'].ewm(span=12, adjust=False).mean()
        ema26 = history['Close'].ewm(span=26, adjust=False).mean()
        history['MACD'] = ema12 - ema26
        history['Signal'] = history['MACD'].ewm(span=9, adjust=False).mean()
        history['Momentum'] = history['Close'].pct_change(periods=10) * 100

        latest = history.iloc[-1]
        prev = history.iloc[-2]
        delta_pct = ((latest['Close'] - prev['Close']) / prev['Close']) * 100
        
        return {
            "price": latest['Close'],
            "delta": delta_pct,
            "rsi": latest['RSI'],
            "macd": latest['MACD'],
            "macd_sig": latest['Signal'],
            "mom": latest['Momentum']
        }
    except:
        return None

def fetch_general_news(api_key):
    # Grabs "General" (Stocks/Econ) and "Crypto"
    all_news = []
    for cat in ["general", "crypto"]:
        try:
            url = f"https://finnhub.io/api/v1/news?category={cat}&token={api_key}"
            data = requests.get(url).json()
            if isinstance(data, list):
                all_news.extend(data)
        except: pass
    
    # Sort and Cut off at 25
    all_news.sort(key=lambda x: x.get('datetime', 0), reverse=True)
    return all_news[:25]

# --- MAIN APP ---
if st.button("🚀 Run Analysis"):
    if not FINNHUB_KEY or not OPENAI_KEY:
        st.error("⚠️ Enter API Keys in Sidebar!")
    else:
        client = OpenAI(api_key=OPENAI_KEY)
        tab1, tab2 = st.tabs(["📊 My Portfolio", "🌎 Global Wire (Last 25)"])

        # --- TAB 1: PORTFOLIO QUANT ---
        with tab1:
            st.subheader("Your Watchlist")
            for symbol in stock_list:
                data = fetch_quant_data(symbol)
                if data:
                    # Signals
                    rsi_sig = "🔴 Overbought" if data['rsi'] > 70 else ("🟢 Oversold" if data['rsi'] < 30 else "⚪ Neutral")
                    macd_sig = "🟢 Bullish" if data['macd'] > data['macd_sig'] else "🔴 Bearish"
                    
                    # Color Price
                    color = "green" if data['delta'] > 0 else "red"
                    price_html = f"<span style='color:{color}; font-size: 24px; font-weight:bold'>${data['price']:,.2f}</span>"
                    
                    c1, c2, c3 = st.columns([1.5, 1, 1])
                    with c1:
                        st.markdown(f"### {symbol}")
                        st.markdown(f"{price_html} ({data['delta']:.2f}%)", unsafe_allow_html=True)
                    with c2:
                        st.caption("RSI")
                        st.write(f"**{data['rsi']:.0f}** {rsi_sig}")
                    with c3:
                        st.caption("MACD")
                        st.write(f"{macd_sig}")
                    st.divider()
                else:
                    st.warning(f"No data for {symbol}")

        # --- TAB 2: GLOBAL WIRE (ANY TICKER) ---
        with tab2:
            st.subheader("🚨 Market Dragnet")
            news_data = fetch_general_news(FINNHUB_KEY)
            
            if len(news_data) > 0:
                for item in news_data:
                    headline = item['headline']
                    
                    # 1. Ask AI to find the Ticker & Sentiment
                    ai_result = get_ai_analysis(headline, "General Market News", client)
                    
                    # 2. Parse the AI's 3-part response
                    parts = ai_result.split("|")
                    if len(parts) == 3:
                        extracted_ticker = parts[0].strip()
                        signal = parts[1].strip()
                        reason = parts[2].strip()
                    else:
                        extracted_ticker = "MARKET"
                        signal = "⚪"
                        reason = ai_result

                    # 3. Display
                    with st.container():
                        c1, c2 = st.columns([1, 4])
                        with c1:
                            # Show the Ticker the AI found (e.g. "AAPL" or "GOLD")
                            st.markdown(f"## {extracted_ticker}")
                            st.caption(f"{signal}")
                        with c2:
                            st.markdown(f"**{headline}**")
                            st.info(f"AI Insight: {reason}")
                        st.divider()
            else:
                st.write("No wire news found. (Check API quota)")
