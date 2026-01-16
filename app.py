import streamlit as st
import requests
import time
import yfinance as yf
from openai import OpenAI
from datetime import datetime, timedelta

# --- CONFIGURATION ---
st.set_page_config(page_title="PennyPulse Terminal", page_icon="📡", layout="wide")

# --- 1. KEY LOADER ---
if "FINNHUB_KEY" in st.secrets:
    FINNHUB_KEY = st.secrets["FINNHUB_KEY"]
    OPENAI_KEY = st.secrets["OPENAI_KEY"]
else:
    st.sidebar.header("🔑 Login")
    FINNHUB_KEY = st.sidebar.text_input("Finnhub Key", type="password")
    OPENAI_KEY = st.sidebar.text_input("OpenAI Key", type="password")

# --- 2. SEARCH BAR ---
st.sidebar.divider()
st.sidebar.header("🔎 Asset Scanner")
user_input = st.sidebar.text_input("Symbols", value="BTC-USD, ETH-USD, GOLD, NEM")
stock_list = [x.strip().upper() for x in user_input.split(",")]

st.title("📡 PennyPulse Terminal")
st.caption("Live AI Analysis: Stocks, Crypto & Commodities")

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
        """
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=50
        )
        return response.choices[0].message.content.strip()
    except:
        return "⚪ | Wait | AI Connecting..."

def fetch_specific_news(symbol, api_key):
    # Works best for COMPANIES (Apple, Tesla, Barrick Gold)
    start = (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d')
    today = datetime.now().strftime('%Y-%m-%d')
    url = f"https://finnhub.io/api/v1/company-news?symbol={symbol}&from={start}&to={today}&token={api_key}"
    return requests.get(url).json()

def fetch_market_news(api_key):
    # ROBUST UPDATE: Combine General + Forex + Crypto so it's never empty
    all_news = []
    categories = ["general", "forex", "stocks", "crypto"]
    
    for cat in categories:
        try:
            url = f"https://finnhub.io/api/v1/news?category={cat}&token={api_key}"
            data = requests.get(url).json()
            if isinstance(data, list):
                all_news.extend(data)
        except:
            pass
            
    # Sort combined list by time (newest first) and take top 10
    # 'datetime' field is a unix timestamp
    all_news.sort(key=lambda x: x.get('datetime', 0), reverse=True)
    return all_news[:10]

# --- MAIN APP ---
if st.button("🚀 Run Scan"):
    if not FINNHUB_KEY or not OPENAI_KEY:
        st.error("⚠️ Enter API Keys in Sidebar!")
    else:
        client = OpenAI(api_key=OPENAI_KEY)
        
        # TAB 1: ASSET SCANNER
        tab1, tab2 = st.tabs(["🔎 Specific Assets", "🌎 Global Market Wire"])
        
        with tab1:
            for symbol in stock_list:
                # 1. Chart Data (Yahoo)
                try:
                    stock_data = yf.Ticker(symbol)
                    history = stock_data.history(period="1mo")
                except:
                    history = None
                
                # 2. News (Finnhub)
                news = fetch_specific_news(symbol, FINNHUB_KEY)
                
                col1, col2 = st.columns([2, 1])
                
                # LEFT: Chart
                with col1:
                    if history is not None and not history.empty:
                        curr = history['Close'].iloc[-1]
                        if len(history) > 1:
                            prev = history['Close'].iloc[-2]
                            delta = round(((curr - prev) / prev) * 100, 2)
                        else:
                            delta = 0
                        st.metric(f"{symbol} Price", f"${curr:,.2f}", f"{delta}%")
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
                            sig, trade, reason = parts[0], parts[1], parts[2]
                        else:
                            sig, trade, reason = "⚪", "Wait", ai_result

                        st.markdown(f"**{sig} {trade}**")
                        st.info(f"{reason}")
                        st.caption(f"📰 {top_story['headline']}")
                    else:
                        st.write("No company-specific news.")
                        st.caption("Check 'Global Market Wire' tab for macro news.")
                st.divider()

        # TAB 2: THE "OMNI" FEED
        with tab2:
            st.subheader("📰 Global Headlines (Gold, Crypto, Forex)")
            # Uses the new Robust Fetcher
            market_data = fetch_market_news(FINNHUB_KEY)
            
            if len(market_data) > 0:
                for item in market_data[:5]: # Top 5 Stories from the combined list
                    headline = item['headline']
                    category = item.get('category', 'Market')
                    # Ask AI to analyze
                    ai_result = get_ai_analysis(headline, "Global Market", client)
                    
                    st.markdown(f"**{ai_result}**")
                    st.write(f"_{headline}_")
                    st.caption(f"Tag: {category.upper()}")
                    st.divider()
            else:
                st.error("No news found. Check API Key or try again later.")
