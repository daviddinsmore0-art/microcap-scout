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
st.sidebar.header("⚡ Live Scanner")
user_input = st.sidebar.text_input("Watchlist", value="TSLA, NVDA, GME, BTC-USD, AMD")
stock_list = [x.strip().upper() for x in user_input.split(",")]

st.title("⚡ PennyPulse Pro")
st.caption("Quant Data + Real-Time News Feed")

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
        """
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=50
        )
        return response.choices[0].message.content.strip()
    except:
        return "⚪ | Wait | AI Connecting..."

def fetch_stock_news(symbol, api_key):
    try:
        start = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d')
        today = datetime.now().strftime('%Y-%m-%d')
        url = f"https://finnhub.io/api/v1/company-news?symbol={symbol}&from={start}&to={today}&token={api_key}"
        data = requests.get(url).json()
        # Add symbol to each news item so we know who it belongs to later
        for item in data:
            item['symbol'] = symbol
        return data
    except:
        return []

def get_quant_data(symbol):
    try:
        ticker = yf.Ticker(symbol)
        # Get 3mo history for valid MACD/RSI
        history = ticker.history(period="3mo", interval="1d", prepost=True)
        
        if history.empty: return None

        # 1. RSI
        delta = history['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        history['RSI'] = 100 - (100 / (1 + rs))

        # 2. MACD
        ema12 = history['Close'].ewm(span=12, adjust=False).mean()
        ema26 = history['Close'].ewm(span=26, adjust=False).mean()
        history['MACD'] = ema12 - ema26
        history['Signal'] = history['MACD'].ewm(span=9, adjust=False).mean()

        # 3. Momentum
        history['Momentum'] = history['Close'].pct_change(periods=10) * 100

        # Current Stats
        latest = history.iloc[-1]
        prev = history.iloc[-2]
        curr_price = latest['Close']
        delta_pct = ((curr_price - prev['Close']) / prev['Close']) * 100
        
        return {
            "price": curr_price,
            "delta": delta_pct,
            "rsi": latest['RSI'],
            "macd": latest['MACD'],
            "macd_sig": latest['Signal'],
            "mom": latest['Momentum']
        }
    except:
        return None

# --- MAIN APP ---
if st.button("🚀 Run Analysis"):
    if not FINNHUB_KEY or not OPENAI_KEY:
        st.error("⚠️ Enter API Keys in Sidebar!")
    else:
        client = OpenAI(api_key=OPENAI_KEY)
        
        # CREATE TABS
        tab1, tab2 = st.tabs(["📊 Quant Dashboard", "📰 Live News Wire"])

        # --- PRE-FETCH DATA ---
        # We fetch data once to use in both tabs
        quant_cache = {}
        all_news = []

        with st.spinner("Analyzing Market Data..."):
            for symbol in stock_list:
                # Get Stats
                q_data = get_quant_data(symbol)
                if q_data:
                    quant_cache[symbol] = q_data
                
                # Get News
                s_news = fetch_stock_news(symbol, FINNHUB_KEY)
                if s_news:
                    all_news.extend(s_news)
        
        # Sort news by time (Newest First)
        all_news.sort(key=lambda x: x.get('datetime', 0), reverse=True)

        # --- TAB 1: QUANT DASHBOARD (The Comparison View) ---
        with tab1:
            st.subheader("Market Overview")
            for symbol in stock_list:
                if symbol in quant_cache:
                    data = quant_cache[symbol]
                    
                    # Logic
                    rsi_sig = "🔴 Overbought" if data['rsi'] > 70 else ("🟢 Oversold" if data['rsi'] < 30 else "⚪ Neutral")
                    macd_sig = "🟢 Bullish" if data['macd'] > data['macd_sig'] else "🔴 Bearish"
                    mom_sig = "🟢 Strong" if data['mom'] > 0 else "🔴 Weak"
                    
                    # Color Coded Price String
                    color = "green" if data['delta'] > 0 else "red"
                    price_html = f"<span style='color:{color}; font-size: 24px; font-weight:bold'>${data['price']:,.2f}</span>"
                    delta_html = f"<span style='color:{color}; font-size: 16px'>({data['delta']:.2f}%)</span>"

                    # Layout
                    c1, c2, c3 = st.columns([1.5, 1, 1])
                    with c1:
                        st.markdown(f"### {symbol}")
                        st.markdown(f"{price_html} {delta_html}", unsafe_allow_html=True)
                    with c2:
                        st.caption("RSI (14)")
                        st.write(f"**{data['rsi']:.0f}** {rsi_sig}")
                    with c3:
                        st.caption("MACD")
                        st.write(f"{macd_sig}")
                    st.divider()

        # --- TAB 2: LIVE NEWS WIRE (The "Jump on it" View) ---
        with tab2:
            st.subheader("🚨 Breaking News Feed")
            
            # Limit to top 20 stories to keep it fast
            for story in all_news[:20]:
                symbol = story['symbol']
                headline = story['headline']
                
                # Container for the news item
                with st.container():
                    # 1. Headline
                    st.markdown(f"**{symbol}: {headline}**")
                    
                    # 2. The "Mini Quant Card" (User requested Chart/Stats for news)
                    if symbol in quant_cache:
                        data = quant_cache[symbol]
                        
                        # Simplified Logic for the News Card
                        rsi_val = data['rsi']
                        rsi_color = "🟢" if rsi_val < 30 else ("🔴" if rsi_val > 70 else "⚪")
                        macd_val = "🟢" if data['macd'] > data['macd_sig'] else "🔴"
                        
                        # Price Color
                        p_color = "green" if data['delta'] > 0 else "red"
                        
                        # Display Stats INLINE with the news
                        stats_html = f"""
                        <span style='color:{p_color}; font-weight:bold'>${data['price']:.2f} ({data['delta']:.2f}%)</span> 
                        | RSI: {rsi_color} {rsi_val:.0f} | MACD: {macd_val}
                        """
                        st.markdown(stats_html, unsafe_allow_html=True)
                    
                    # 3. AI Insight
                    ai_result = get_ai_analysis(headline, symbol, client)
                    st.info(f"AI: {ai_result}")
                    
                    st.divider()
