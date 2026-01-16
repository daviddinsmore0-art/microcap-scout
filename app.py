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
st.caption("Quant Data + Hybrid News Filter")

# --- 3. THE PYTHON GATEKEEPER ---
# We filter these LOCALLY first. If a headline misses these, AI never sees it.
FINANCIAL_KEYWORDS = [
    "stock", "share", "market", "trade", "invest", "profit", "loss",
    "surge", "crash", "plunge", "soar", "rally", "drop", "high", "low",
    "fed", "rate", "bank", "inflation", "yield", "crypto", "bitcoin",
    "gold", "oil", "futures", "etf", "dividend", "earnings", "revenue",
    "sec", "ipo", "merger", "acquisition", "deal", "sp500", "dow", "nasdaq"
]

# --- FUNCTIONS ---
def get_ai_analysis(headline, client):
    try:
        # AI Task: Extract Ticker & Sentiment
        prompt = f"""
        Act as a Trader.
        Headline: "{headline}"
        
        Task:
        1. Does this mention a specific ticker/asset?
           - If NO, output: "SKIP"
           - If YES, output: [Ticker] | [Signal] | [Reason]
           
        Format: Ticker | Signal (🟢/🔴/⚪) | Reason (5 words)
        Example: TSLA | 🔴 | Recalls affecting production.
        """
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=60
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
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
    all_news = []
    # Only fetch GENERAL and CRYPTO to save bandwidth
    for cat in ["general", "crypto"]:
        try:
            url = f"https://finnhub.io/api/v1/news?category={cat}&token={api_key}"
            data = requests.get(url).json()
            if isinstance(data, list):
                all_news.extend(data)
        except: pass
    
    all_news.sort(key=lambda x: x.get('datetime', 0), reverse=True)
    return all_news[:60] # Fetch 60, but Python will filter most

# --- MAIN APP ---
if st.button("🚀 Run Analysis"):
    if not FINNHUB_KEY or not OPENAI_KEY:
        st.error("⚠️ Enter API Keys in Sidebar!")
    else:
        client = OpenAI(api_key=OPENAI_KEY)
        tab1, tab2 = st.tabs(["📊 My Portfolio", "🌎 Smart Wire"])

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

        # --- TAB 2: SMART WIRE ---
        with tab2:
            st.subheader("🚨 Verified Financial News")
            st.caption("Filtering noise locally...")
            
            raw_news = fetch_general_news(FINNHUB_KEY)
            valid_count = 0
            
            if len(raw_news) > 0:
                for item in raw_news:
                    headline = item['headline']
                    
                    # LAYER 1: PYTHON CHECK (Instant)
                    # Does it contain a financial keyword?
                    is_financial = any(word in headline.lower() for word in FINANCIAL_KEYWORDS)
                    
                    # Also check if it contains a known big ticker (optional safety net)
                    has_ticker = any(t in headline for t in ["TSLA", "AAPL", "BTC", "ETH", "GOLD", "USD"])
                    
                    if not (is_financial or has_ticker):
                        continue # Silent Delete
                        
                    # LAYER 2: AI CHECK (Only for survivors)
                    ai_result = get_ai_analysis(headline, client)
                    
                    if "SKIP" in ai_result:
                        continue
                        
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
                        
                        valid_count += 1
                        if valid_count >= 10: break
            
            if valid_count == 0:
                st.write("No major financial news in the last batch.")
