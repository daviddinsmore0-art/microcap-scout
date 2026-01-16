import streamlit as st
import requests
import yfinance as yf
import pandas as pd
from openai import OpenAI
from datetime import datetime, timedelta

# --- CONFIGURATION ---
st.set_page_config(page_title="PennyPulse Quant", page_icon="📊", layout="wide")

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
st.sidebar.header("🔎 Quant Scanner")
user_input = st.sidebar.text_input("Symbols", value="BTC, ETH, SOL, GC=F, SI=F")
stock_list = [x.strip().upper() for x in user_input.split(",")]

st.title("📊 PennyPulse Quant")
st.caption("Live AI Analysis + Technical Indicators")

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

def fetch_news(symbol, api_key):
    # Fetch news from Finnhub
    try:
        start = (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d')
        today = datetime.now().strftime('%Y-%m-%d')
        url = f"https://finnhub.io/api/v1/company-news?symbol={symbol}&from={start}&to={today}&token={api_key}"
        return requests.get(url).json()
    except:
        return []

def calculate_indicators(df):
    # 1. RSI (Relative Strength Index)
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))

    # 2. MACD (Moving Average Convergence Divergence)
    # EMA 12 (Fast) and EMA 26 (Slow)
    ema12 = df['Close'].ewm(span=12, adjust=False).mean()
    ema26 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = ema12 - ema26
    df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()

    # 3. MOMENTUM (10-day Rate of Change)
    # (Price - Price_10_days_ago) / Price_10_days_ago
    df['Momentum'] = df['Close'].pct_change(periods=10) * 100

    return df

# --- MAIN APP ---
if st.button("🚀 Run Quant Scan"):
    if not FINNHUB_KEY or not OPENAI_KEY:
        st.error("⚠️ Enter API Keys in Sidebar!")
    else:
        client = OpenAI(api_key=OPENAI_KEY)
        
        st.subheader("📉 Technical & Fundamental Analysis")
        
        for symbol in stock_list:
            # 1. FETCH DATA (3 Months for valid MACD)
            try:
                ticker = yf.Ticker(symbol)
                # 'prepost=True' gets us the hidden pre-market trades
                history = ticker.history(period="3mo", interval="1d", prepost=True)
                
                # Get the absolute latest price (even pre-market)
                try:
                    # Try to get live fast_info, fallback to last history close
                    curr_price = ticker.fast_info['last_price']
                except:
                    curr_price = history['Close'].iloc[-1]
            except:
                st.error(f"Could not load data for {symbol}")
                continue
            
            # 2. CALCULATE INDICATORS
            if not history.empty:
                df = calculate_indicators(history)
                latest = df.iloc[-1]
                
                # --- LOGIC FOR GREEN/RED SIGNALS ---
                
                # RSI Logic (Standard: >70 Sell, <30 Buy)
                rsi_val = latest['RSI']
                if rsi_val > 70: rsi_signal = "🔴 Overbought"
                elif rsi_val < 30: rsi_signal = "🟢 Oversold"
                else: rsi_signal = "⚪ Neutral"
                
                # MACD Logic (Bullish if MACD Line > Signal Line)
                macd_val = latest['MACD']
                sig_val = latest['Signal']
                if macd_val > sig_val: macd_signal = "🟢 Bullish"
                else: macd_signal = "🔴 Bearish"
                
                # Momentum Logic (Positive/Negative)
                mom_val = latest['Momentum']
                if mom_val > 0: mom_signal = "🟢 Strong"
                else: mom_signal = "🔴 Weak"

                # 3. DISPLAY ROW
                col1, col2, col3, col4 = st.columns([1.5, 1, 1, 2])
                
                with col1:
                    # Big Price Metric
                    prev_close = history['Close'].iloc[-2]
                    delta_pct = ((curr_price - prev_close) / prev_close) * 100
                    st.metric(label=symbol, value=f"${curr_price:,.2f}", delta=f"{delta_pct:.2f}%")
                
                with col2:
                    st.caption("RSI (14)")
                    st.write(f"**{rsi_val:.0f}** {rsi_signal}")
                    st.caption("MACD")
                    st.write(f"{macd_signal}")

                with col3:
                    st.caption("Momentum (10d)")
                    st.write(f"**{mom_val:.1f}%** {mom_signal}")
                    
                with col4:
                    # AI News Analysis
                    news = fetch_news(symbol, FINNHUB_KEY)
                    if len(news) > 0:
                        ai_res = get_ai_analysis(news[0]['headline'], symbol, client)
                        st.info(f"AI: {ai_res}")
                    else:
                        st.caption("No recent news headlines.")
                
                st.divider()
            else:
                st.write(f"{symbol}: No Data Available.")
