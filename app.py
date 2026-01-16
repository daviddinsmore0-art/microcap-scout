import streamlit as st
import requests
import time
import yfinance as yf
from openai import OpenAI
from datetime import datetime, timedelta

# --- CONFIGURATION ---
st.set_page_config(page_title="PennyPulse Terminal", page_icon="🔎", layout="wide")

# --- 1. KEY LOADER ---
if "FINNHUB_KEY" in st.secrets:
    FINNHUB_KEY = st.secrets["FINNHUB_KEY"]
    OPENAI_KEY = st.secrets["OPENAI_KEY"]
else:
    st.sidebar.header("🔑 Login")
    FINNHUB_KEY = st.sidebar.text_input("Finnhub Key", type="password")
    OPENAI_KEY = st.sidebar.text_input("OpenAI Key", type="password")

# --- 2. UNIVERSAL SEARCH BAR ---
st.sidebar.divider()
st.sidebar.header("🔎 Scanner")
user_input = st.sidebar.text_input("Enter Symbols (comma separated)", value="TSLA, MULN, BTC-USD")
stock_list = [x.strip().upper() for x in user_input.split(",")]

st.title("🔎 PennyPulse Search")
st.caption("Live AI Analysis for ANY Asset")

# --- FUNCTIONS ---
def get_ai_analysis(headline, asset, client):
    try:
        prompt = f"""
        Act as a Wall St Trader.
        Headline: "{headline}"
        Asset: {asset}
        
        Task:
        1. Signal: 🟢 (Bullish), 🔴 (Bearish), or ⚪ (Neutral).
        2. Trade: "Long", "Short", or "Wait".
        3. Reason: 5 words max.
        
        Format: [Signal] | [Trade] | [Reason]
        Example: 🔴 Bearish | Short | Production delays confirmed.
        """
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=50
        )
        return response.choices[0].message.content.strip()
    except:
        return "⚪ | Wait | AI Connecting..."

def fetch_news(symbol, api_key):
    # Get News (Last 3 days)
    start = (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d')
    today = datetime.now().strftime('%Y-%m-%d')
    url = f"https://finnhub.io/api/v1/company-news?symbol={symbol}&from={start}&to={today}&token={api_key}"
    return requests.get(url).json()

def fetch_forex_news(api_key):
    url = f"https://finnhub.io/api/v1/news?category=forex&token={api_key}"
    return requests.get(url).json()

# --- MAIN APP ---
if st.button("🚀 Run Search"):
    if not FINNHUB_KEY or not OPENAI_KEY:
        st.error("⚠️ Enter API Keys in Sidebar!")
    else:
        client = OpenAI(api_key=OPENAI_KEY)
        
        # 1. DYNAMIC STOCK TERMINAL
        st.subheader("📉 Asset Analysis")
        
        for symbol in stock_list:
            # 1. Get Chart Data
            try:
                stock_data = yf.Ticker(symbol)
                history = stock_data.history(period="1mo")
            except:
                history = None
            
            # 2. Get News
            news = fetch_news(symbol, FINNHUB_KEY)
            
            # Layout
            col1, col2 = st.columns([2, 1])
            
            # LEFT: Chart
            with col1:
                if history is not None and not history.empty:
                    current_price = history['Close'].iloc[-1]
                    if len(history) > 1:
                        prev_price = history['Close'].iloc[-2]
                        delta = round(((current_price - prev_price) / prev_price) * 100, 2)
                    else:
                        delta = 0
                    
                    st.metric(label=symbol, value=f"${current_price:,.2f}", delta=f"{delta}%")
                    st.line_chart(history['Close'], height=200)
                else:
                    st.warning(f"Chart unavailable for {symbol}")

            # RIGHT: AI Analysis
            with col2:
                if len(news) > 0:
                    top_story = news[0]
                    ai_result = get_ai_analysis(top_story['headline'], symbol, client)
                    
                    parts = ai_result.split("|")
                    if len(parts) == 3:
                        signal, trade, reason = parts[0], parts[1], parts[2]
                    else:
                        signal, trade, reason = "⚪", "Wait", ai_result

                    st.markdown(f"**AI Signal:** {signal} {trade}")
                    st.info(f"{reason}")
                    st.caption(f"📰 {top_story['headline']}")
                else:
                    st.write("No recent news.")
            
            st.divider()
            time.sleep(0.5)

        # 2. GLOBAL FEED
        st.subheader("💱 Global Headlines")
        forex_data = fetch_forex_news(FINNHUB_KEY)
        if len(forex_data) > 0:
            for item in forex_data[:3]:
                headline = item['headline']
                ai_result = get_ai_analysis(headline, "Forex", client)
                st.write(f"**{ai_result}**") 
                st.caption(f"_{headline}_")
                st.divider()
