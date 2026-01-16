import streamlit as st
import requests
import time
from openai import OpenAI
from datetime import datetime, timedelta

# --- CONFIGURATION ---
st.set_page_config(page_title="PennyPulse", page_icon="📡", layout="wide")

# --- SIDEBAR ---
st.sidebar.header("📡 Settings")
FINNHUB_KEY = st.sidebar.text_input("Finnhub API Key", type="password")
OPENAI_KEY = st.sidebar.text_input("OpenAI API Key", type="password")

st.sidebar.divider()
st.sidebar.subheader("Watchlist")
stock_list = st.sidebar.multiselect("Stocks", ["MULN", "TSLA", "AAPL", "CEI"], ["TSLA", "MULN"])
forex_list = st.sidebar.multiselect("Forex", ["EUR/USD", "USD/JPY", "GBP/USD"], ["EUR/USD"])

st.title("📡 PennyPulse Pro")
st.write("Live AI Analysis & Reasoning")

# --- FUNCTIONS ---
def get_ai_analysis(headline, asset, client):
    try:
        # We ask for TWO things: The Emoji AND a 1-sentence reason
        prompt = f"""
        Analyze this news for {asset}: "{headline}"
        1. Classify sentiment: 🟢 (Positive), 🔴 (Negative), or ⚪ (Neutral).
        2. Write a 10-word reason why.
        
        Format: [Emoji] | [Reason]
        Example: 🔴 | Earnings missed expectations by 20%.
        """
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=50
        )
        return response.choices[0].message.content.strip()
    except:
        return "⚪ | AI Error"

def fetch_news(symbol, api_key):
    start = (datetime.now() - timedelta(days=5)).strftime('%Y-%m-%d')
    today = datetime.now().strftime('%Y-%m-%d')
    url = f"https://finnhub.io/api/v1/company-news?symbol={symbol}&from={start}&to={today}&token={api_key}"
    return requests.get(url).json()

def fetch_forex(api_key):
    url = f"https://finnhub.io/api/v1/news?category=forex&token={api_key}"
    return requests.get(url).json()

# --- MAIN APP ---
if st.button("🚀 Run Full Scan"):
    if not FINNHUB_KEY or not OPENAI_KEY:
        st.error("Please enter keys in sidebar!")
    else:
        client = OpenAI(api_key=OPENAI_KEY)
        
        # 1. STOCKS
        st.subheader("📉 Stock Analysis")
        for symbol in stock_list:
            data = fetch_news(symbol, FINNHUB_KEY)
            if len(data) > 0:
                top_story = data[0]
                result = get_ai_analysis(top_story['headline'], symbol, client)
                
                # Split the emoji from the reason
                parts = result.split("|")
                emoji = parts[0].strip()
                reason = parts[1].strip() if len(parts) > 1 else "No reason given."
                
                st.markdown(f"### {emoji} {symbol}")
                st.info(f"**AI Insight:** {reason}")
                st.caption(f"📰 Source: {top_story['headline']}")
                st.divider()
            else:
                st.write(f"{symbol}: No recent news.")
            time.sleep(0.5)

        # 2. FOREX
        st.subheader("💱 Forex Analysis")
        forex_data = fetch_forex(FINNHUB_KEY)
        
        # Simple filter for our selected pairs
        found_any = False
        for pair in forex_list:
            curr1, curr2 = pair.split("/")
            # Check top 10 stories for matches
            for item in forex_data[:10]:
                if curr1 in item['headline'] or curr2 in item['headline']:
                    found_any = True
                    result = get_ai_analysis(item['headline'], pair, client)
                    
                    st.markdown(f"**{pair}**")
                    st.write(result)
                    st.divider()
                    break # Only show 1 story per pair
        
        if not found_any:
            st.write("No major headlines for selected pairs.")

