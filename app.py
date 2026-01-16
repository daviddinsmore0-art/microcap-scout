import streamlit as st
import requests
import time
from openai import OpenAI
from datetime import datetime, timedelta

# --- CONFIGURATION ---
st.set_page_config(page_title="PennyPulse Pro", page_icon="📡", layout="wide")

# --- 1. INTELLIGENT KEY LOADER ---
if "FINNHUB_KEY" in st.secrets:
    FINNHUB_KEY = st.secrets["FINNHUB_KEY"]
    OPENAI_KEY = st.secrets["OPENAI_KEY"]
else:
    st.sidebar.header("🔑 Login")
    FINNHUB_KEY = st.sidebar.text_input("Finnhub Key", type="password")
    OPENAI_KEY = st.sidebar.text_input("OpenAI Key", type="password")

st.sidebar.divider()
st.sidebar.subheader("Watchlist")
stock_list = st.sidebar.multiselect("Stocks", ["MULN", "TSLA", "AAPL", "CEI"], ["TSLA", "MULN"])

st.title("📡 PennyPulse Pro")
st.caption("Live AI Trading Signals")

# --- FUNCTIONS ---
def get_ai_analysis(headline, asset, client):
    try:
        # THE NEW "TRADER" PROMPT
        prompt = f"""
        Act as a Forex & Stock Analyst.
        Headline: "{headline}"
        Context: Checking {asset}.
        
        Task:
        1. Sentiment: 🟢 (Positive), 🔴 (Negative), or ⚪ (Neutral).
        2. Signal: Identify the specific move (e.g., "Bullish USD", "Bearish TSLA", "Risk-Off").
        3. Reason: Explain why in 10 words.
        
        Strict Output Format: [Emoji] | [Signal] | [Reason]
        Example: 🔴 | Bullish USD | War fears drive safe-haven demand.
        """
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=60
        )
        return response.choices[0].message.content.strip()
    except:
        return "⚪ | Analyzing... | Connection error"

def fetch_stock_news(symbol, api_key):
    start = (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d')
    today = datetime.now().strftime('%Y-%m-%d')
    url = f"https://finnhub.io/api/v1/company-news?symbol={symbol}&from={start}&to={today}&token={api_key}"
    return requests.get(url).json()

def fetch_forex_news(api_key):
    url = f"https://finnhub.io/api/v1/news?category=forex&token={api_key}"
    return requests.get(url).json()

# --- MAIN APP ---
if st.button("🚀 Run Signal Scan"):
    if not FINNHUB_KEY or not OPENAI_KEY:
        st.error("⚠️ Please enter API Keys to start!")
    else:
        client = OpenAI(api_key=OPENAI_KEY)
        
        # 1. STOCK SIGNALS
        st.subheader("📉 Stock Signals")
        for symbol in stock_list:
            data = fetch_stock_news(symbol, FINNHUB_KEY)
            if len(data) > 0:
                top_story = data[0]
                result = get_ai_analysis(top_story['headline'], symbol, client)
                
                # Parse the 3-part response
                parts = result.split("|")
                if len(parts) == 3:
                    emoji = parts[0].strip()
                    signal = parts[1].strip()
                    reason = parts[2].strip()
                else:
                    emoji, signal, reason = "⚪", "Neutral", result
                
                st.markdown(f"### {emoji} {signal}")
                st.info(f"{reason}")
                st.caption(f"Source: {top_story['headline']}")
                st.divider()
            else:
                st.write(f"{symbol}: Quiet.")
        
        # 2. FOREX SIGNALS
        st.subheader("💱 Forex Signals")
        forex_data = fetch_forex_news(FINNHUB_KEY)
        
        if len(forex_data) > 0:
            for item in forex_data[:3]: # Analyze top 3 global stories
                headline = item['headline']
                # We ask AI to identify the currency from the headline
                result = get_ai_analysis(headline, "Global Forex", client)
                
                parts = result.split("|")
                if len(parts) == 3:
                    emoji = parts[0].strip()
                    signal = parts[1].strip()
                    reason = parts[2].strip()
                else:
                    emoji, signal, reason = "⚪", "Neutral", result
                    
                st.markdown(f"**{emoji} {signal}**")
                st.write(f"_{headline}_")
                st.caption(f"Reason: {reason}")
                st.divider()
        else:
            st.write("No Forex news found.")
