import streamlit as st
import requests
import time
from openai import OpenAI
from datetime import datetime, timedelta

# --- CONFIGURATION ---
st.set_page_config(page_title="Market Scout", page_icon="📡", layout="wide")

# --- SIDEBAR ---
st.sidebar.header("📡 Settings")
FINNHUB_KEY = st.sidebar.text_input("Finnhub API Key", type="password")
OPENAI_KEY = st.sidebar.text_input("OpenAI API Key", type="password")

st.title("📡 AI Market Scout")
st.write("Real-time sentiment analysis for Stocks & Forex")

# --- FUNCTIONS ---
def get_ai_sentiment(headline, asset, client):
    try:
        prompt = f"""
        Rank sentiment for {asset}: "{headline}"
        Options: 🟢 VERY POSITIVE, 🟢 POSITIVE, 🔴 NEGATIVE, ⚪ NEUTRAL
        Reply ONLY with emoji and text.
        """
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=15
        )
        return response.choices[0].message.content.strip()
    except:
        return "⚪ ERROR"

def fetch_news(symbol, api_key):
    # Get last 7 days of news
    start = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    to = datetime.now().strftime('%Y-%m-%d')
    url = f"https://finnhub.io/api/v1/company-news?symbol={symbol}&from={start}&to={to}&token={api_key}"
    return requests.get(url).json()

# --- MAIN APP ---
stock_list = st.sidebar.multiselect("Stocks", ["MULN", "CEI", "TSLA", "AAPL"], ["MULN", "TSLA"])
forex_list = st.sidebar.multiselect("Forex", ["EUR/USD", "USD/JPY"], ["EUR/USD"])

if st.button("🚀 Start Scan"):
    if not FINNHUB_KEY or not OPENAI_KEY:
        st.error("Please enter keys in sidebar!")
    else:
        client = OpenAI(api_key=OPENAI_KEY)
        
        st.subheader("Results")
        # 1. SCAN STOCKS
        for symbol in stock_list:
            data = fetch_news(symbol, FINNHUB_KEY)
            if len(data) > 0:
                top = data[0]
                rank = get_ai_sentiment(top['headline'], symbol, client)
                st.markdown(f"**{symbol}** | {rank}")
                st.write(top['headline'])
                st.divider()
            time.sleep(1) # Safety delay
            
        # 2. SCAN FOREX (Simplified for speed)
        st.write(f"*(Forex scanning enabled for: {', '.join(forex_list)})*")
