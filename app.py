import streamlit as st
import requests
import time
from openai import OpenAI
from datetime import datetime, timedelta

# --- CONFIGURATION ---
st.set_page_config(page_title="PennyPulse Pro", page_icon="📈", layout="wide")

# --- 1. KEY LOADER ---
if "FINNHUB_KEY" in st.secrets:
    FINNHUB_KEY = st.secrets["FINNHUB_KEY"]
    OPENAI_KEY = st.secrets["OPENAI_KEY"]
else:
    st.sidebar.header("🔑 Login")
    FINNHUB_KEY = st.sidebar.text_input("Finnhub Key", type="password")
    OPENAI_KEY = st.sidebar.text_input("OpenAI Key", type="password")

st.sidebar.divider()
st.sidebar.subheader("Watchlist")
stock_list = st.sidebar.multiselect("Stocks", ["MULN", "TSLA", "AAPL", "CEI", "NVDA"], ["TSLA", "MULN"])

st.title("📈 PennyPulse Terminal")
st.caption("Live AI Signals + Price Action")

# --- FUNCTIONS ---
def get_ai_analysis(headline, asset, client):
    try:
        prompt = f"""
        Act as a Trader.
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

def fetch_data(symbol, api_key):
    # Get News (Last 3 days)
    start = (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d')
    today = datetime.now().strftime('%Y-%m-%d')
    news_url = f"https://finnhub.io/api/v1/company-news?symbol={symbol}&from={start}&to={today}&token={api_key}"
    
    # Get Current Price (Quote)
    quote_url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={api_key}"
    
    # Get Chart Data (Last 30 Days Candles)
    # We use UNIX timestamps for this specific endpoint
    t_now = int(time.time())
    t_start = t_now - (30 * 24 * 60 * 60) # 30 days ago
    chart_url = f"https://finnhub.io/api/v1/stock/candle?symbol={symbol}&resolution=D&from={t_start}&to={t_now}&token={api_key}"
    
    return {
        "news": requests.get(news_url).json(),
        "quote": requests.get(quote_url).json(),
        "chart": requests.get(chart_url).json()
    }

def fetch_forex(api_key):
    url = f"https://finnhub.io/api/v1/news?category=forex&token={api_key}"
    return requests.get(url).json()

# --- MAIN APP ---
if st.button("🚀 Run Terminal Scan"):
    if not FINNHUB_KEY or not OPENAI_KEY:
        st.error("⚠️ Enter API Keys in Sidebar!")
    else:
        client = OpenAI(api_key=OPENAI_KEY)
        
        # 1. STOCK TERMINAL
        st.subheader("📉 Market Action")
        
        for symbol in stock_list:
            # Fetch EVERYTHING in one go
            market_data = fetch_data(symbol, FINNHUB_KEY)
            quote = market_data['quote']
            chart = market_data['chart']
            news = market_data['news']
            
            # Create a 2-Column Layout
            col1, col2 = st.columns([1, 2])
            
            # LEFT COLUMN: Price & Chart
            with col1:
                # Check if we got valid price data
                if quote and 'c' in quote:
                    current_price = quote['c']
                    percent_change = quote['dp']
                    st.metric(label=symbol, value=f"${current_price}", delta=f"{percent_change}%")
                
                # Draw the chart (if data exists)
                if chart and 's' in chart and chart['s'] == 'ok':
                    st.line_chart(chart['c'], height=150) # 'c' is closing prices
                else:
                    st.caption("(Chart unavailable)")

            # RIGHT COLUMN: AI Analysis
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
                    st.write("No major news catalysts.")
            
            st.divider()
            time.sleep(0.5)
