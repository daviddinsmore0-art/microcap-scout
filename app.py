import streamlit as st
import requests
import time
from openai import OpenAI
from datetime import datetime, timedelta

# --- CONFIGURATION ---
st.set_page_config(page_title="PennyPulse Pro", page_icon="📡", layout="wide")

# --- 1. INTELLIGENT KEY LOADER ---
# Checks if keys are in Secrets; if not, asks in Sidebar.
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
st.caption("Live AI Analysis")

# --- FUNCTIONS ---
def get_ai_analysis(headline, asset, client):
    try:
        # Strict instruction for AI to be concise
        prompt = f"""
        Headline: "{headline}"
        Asset: {asset}
        Task:
        1. Classify: 🟢 (Positive), 🔴 (Negative), or ⚪ (Neutral).
        2. Explain why in 10 words.
        Format: [Emoji] | [Reason]
        """
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=40
        )
        return response.choices[0].message.content.strip()
    except:
        return "⚪ | AI connecting..."

def fetch_stock_news(symbol, api_key):
    start = (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d')
    today = datetime.now().strftime('%Y-%m-%d')
    url = f"https://finnhub.io/api/v1/company-news?symbol={symbol}&from={start}&to={today}&token={api_key}"
    return requests.get(url).json()

def fetch_forex_news(api_key):
    # Get general forex news
    url = f"https://finnhub.io/api/v1/news?category=forex&token={api_key}"
    return requests.get(url).json()

# --- MAIN APP LOOP ---
if st.button("🚀 Run Full Scan"):
    if not FINNHUB_KEY or not OPENAI_KEY:
        st.error("⚠️ Please enter API Keys to start!")
    else:
        client = OpenAI(api_key=OPENAI_KEY)
        
        # 1. STOCK SCANNER
        st.subheader("📉 Stocks")
        for symbol in stock_list:
            data = fetch_stock_news(symbol, FINNHUB_KEY)
            if len(data) > 0:
                top_story = data[0]
                result = get_ai_analysis(top_story['headline'], symbol, client)
                
                # Clean up the AI text
                if "|" in result:
                    emoji, reason = result.split("|", 1)
                else:
                    emoji, reason = "⚪", result
                
                st.markdown(f"**{emoji} {symbol}**")
                st.info(f"{reason}")
                st.caption(f"Source: {top_story['headline']}")
                st.divider()
            else:
                st.write(f"{symbol}: No news in last 3 days.")
        
        # 2. FOREX SCANNER (Unfiltered)
        st.subheader("💱 Global Forex Wire")
        forex_data = fetch_forex_news(FINNHUB_KEY)
        
        if len(forex_data) > 0:
            # Just show the top 3 stories regardless of currency
            for item in forex_data[:3]:
                headline = item['headline']
                # Ask AI to identify the currency for us
                result = get_ai_analysis(headline, "Forex", client)
                
                if "|" in result:
                    emoji, reason = result.split("|", 1)
                else:
                    emoji, reason = "⚪", result
                    
                st.markdown(f"**{emoji} Market Update**")
                st.write(f"_{headline}_")
                st.caption(f"AI Insight: {reason}")
                st.divider()
        else:
            st.write("No Forex news found right now.")
