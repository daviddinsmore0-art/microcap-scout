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

st.title("⚡ PennyPulse Pro")
st.caption("Quant Data + Ticker-Only News Feed")

# --- FUNCTIONS ---
def get_ai_analysis(headline, context, client):
    try:
        # STRICT PROMPT: The "Doorman" Logic
        prompt = f"""
        Act as a Financial Analyst.
        Headline: "{headline}"
        
        Strict Filter Task:
        1. Does this headline mention a specific publicly traded company or asset?
           - If NO (e.g. celebrity gossip, sports, generic housing news), output ONLY: "SKIP"
           - If YES, proceed to step 2.
           
        2. Extract the Ticker Symbol (e.g. "AAPL", "BTC", "TSLA").
        3. Signal: 🟢 (Bullish), 🔴 (Bearish), or ⚪ (Neutral).
        4. Reason: 5 words max.
        
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
        return "SKIP"

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
    # We grab MORE news (50 items) because we expect to delete many of them
    all_news = []
    for cat in ["general", "forex", "crypto"]:
        try:
            url = f"https://finnhub.io/api/v1/news?category={cat}&token={api_key}"
            data = requests.get(url).json()
            if isinstance(data, list):
                all_news.extend(data)
        except: pass
    
    # Sort Newest First
    all_news.sort(key=lambda x: x.get('datetime', 0), reverse=True)
    return all_news[:50] 

# --- MAIN APP ---
if st.button("🚀 Run Analysis"):
    if not FINNHUB_KEY or not OPENAI_KEY:
        st.error("⚠️ Enter API Keys in Sidebar!")
    else:
        client = OpenAI(api_key=OPENAI_KEY)
        tab1, tab2 = st.tabs(["📊 My Portfolio", "🌎 Ticker Wire"])

        # --- TAB 1: PORTFOLIO ---
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

        # --- TAB 2: TICKER WIRE ---
        with tab2:
            st.subheader("🚨 Verified Asset News")
            st.caption("Filtering for valid tickers only...")
            
            news_data = fetch_general_news(FINNHUB_KEY)
            valid_count = 0
            
            # Progress Bar (Optional UI Polish)
            progress_text = st.empty()
            
            if len(news_data) > 0:
                for i, item in enumerate(news_data):
                    headline = item['headline']
                    
                    # AI "Doorman" Check
                    ai_result = get_ai_analysis(headline, "Market", client)
                    
                    # If AI returns "SKIP", we don't even show it
                    if "SKIP" in ai_result:
                        continue
                        
                    # Valid News Found!
                    parts = ai_result.split("|")
                    if len(parts) == 3:
                        ticker, signal, reason = parts[0].strip(), parts[1].strip(), parts[2].strip()
                        
                        # Display Card
                        with st.container():
                            c1, c2 = st.columns([1, 4])
                            with c1:
                                st.markdown(f"## {ticker}")
                                st.caption(f"{signal}")
                            with c2:
                                st.markdown(f"**{headline}**")
                                st.info(f"{reason}")
                            st.divider()
                        
                        valid_count += 1
                        if valid_count >= 10: # Stop after 10 valid stories
                            break
            
            if valid_count == 0:
                st.write("No company-specific news found in the last 50 headlines.")
