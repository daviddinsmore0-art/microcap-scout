import streamlit as st
import yfinance as yf
import pandas as pd
from openai import OpenAI
from datetime import datetime

# --- CONFIGURATION ---
st.set_page_config(page_title="PennyPulse Pro", page_icon="⚡", layout="wide")

# --- 1. KEY LOADER ---
# Note: We only need OpenAI Key now. Finnhub is only for backup if you wanted it.
if "OPENAI_KEY" in st.secrets:
    OPENAI_KEY = st.secrets["OPENAI_KEY"]
else:
    st.sidebar.header("🔑 Login")
    OPENAI_KEY = st.sidebar.text_input("OpenAI Key", type="password")

# --- 2. SETTINGS ---
st.sidebar.divider()
st.sidebar.header("⚡ Watchlist")
user_input = st.sidebar.text_input("My Portfolio", value="TSLA, NVDA, GME, BTC-USD")
stock_list = [x.strip().upper() for x in user_input.split(",")]

st.title("⚡ PennyPulse Pro")
st.caption("Quant Data + Yahoo Finance News Feed")

# --- FUNCTIONS ---
def get_ai_analysis(headline, client):
    try:
        # AI Task: Extract Ticker & Sentiment
        prompt = f"""
        Act as a Trader.
        Headline: "{headline}"
        
        Task:
        1. Extract the Ticker (e.g. AAPL, BTC, GOLD). If none, use "MARKET".
        2. Determine Signal: 🟢 (Bullish), 🔴 (Bearish), or ⚪ (Neutral).
        3. Write a 5-word Reason.
        
        Format: Ticker | Signal | Reason
        Example: TSLA | 🔴 | Recalls affecting production.
        """
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=60
        )
        return response.choices[0].message.content.strip()
    except:
        return "MARKET | ⚪ | AI Busy"

def fetch_quant_data(symbol):
    try:
        ticker = yf.Ticker(symbol)
        history = ticker.history(period="3mo", interval="1d", prepost=True)
        if history.empty: return None

        # Indicators
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

def fetch_yahoo_news():
    """
    Fetches news from 5 major "Market Movers" to create a global feed.
    """
    # These proxies cover the whole market
    proxies = ["SPY", "QQQ", "BTC-USD", "GC=F", "CL=F"] 
    all_news = []
    seen_titles = set()

    for symbol in proxies:
        try:
            ticker = yf.Ticker(symbol)
            news = ticker.news
            for item in news:
                title = item['title']
                # Deduplicate (SPY and QQQ often share stories)
                if title not in seen_titles:
                    seen_titles.add(title)
                    all_news.append({
                        "headline": title,
                        "time": item['providerPublishTime']
                    })
        except:
            pass
    
    # Sort by time (Newest First)
    all_news.sort(key=lambda x: x['time'], reverse=True)
    return all_news[:20] # Return Top 20

# --- MAIN APP ---
if st.button("🚀 Run Analysis"):
    if not OPENAI_KEY:
        st.error("⚠️ Enter OpenAI Key in Sidebar!")
    else:
        client = OpenAI(api_key=OPENAI_KEY)
        tab1, tab2 = st.tabs(["📊 My Portfolio", "🌎 Yahoo Market Wire"])

        # --- TAB 1: QUANT DASHBOARD ---
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

        # --- TAB 2: YAHOO WIRE ---
        with tab2:
            st.subheader("🚨 Global Wire (Source: Yahoo Finance)")
            
            # 1. Fetch from Yahoo
            raw_news = fetch_yahoo_news()
            
            if len(raw_news) == 0:
                st.error("⚠️ Connection Error. Yahoo returned 0 stories.")
            else:
                st.caption(f"⚡ Analyzed {len(raw_news)} breaking stories.")
                
                count = 0
                for item in raw_news:
                    headline = item['headline']
                    
                    # AI Analysis
                    ai_result = get_ai_analysis(headline, client)
                    
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
                        count += 1
                        
                    if count >= 15: break
