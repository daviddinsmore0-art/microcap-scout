import streamlit as st
import requests
import yfinance as yf
import pandas as pd
import concurrent.futures
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
st.caption("Quant Data + High-Speed News Filter")

# --- FUNCTIONS ---
def analyze_single_headline(item, client):
    """
    This function runs in parallel. 
    It returns None if 'SKIP', or a dict of data if valid.
    """
    headline = item['headline']
    try:
        prompt = f"""
        Act as a Financial Analyst.
        Headline: "{headline}"
        
        Strict Filter Task:
        1. Does this headline mention a specific publicly traded company or asset?
           - If NO (gossip, sports, generic), output ONLY: "SKIP"
           - If YES, proceed.
           
        2. Extract Ticker (e.g. "AAPL").
        3. Signal: 🟢, 🔴, or ⚪.
        4. Reason: 5 words max.
        
        Format: [Ticker] | [Signal] | [Reason]
        """
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=60
        )
        result = response.choices[0].message.content.strip()
        
        if "SKIP" in result:
            return None
            
        parts = result.split("|")
        if len(parts) == 3:
            return {
                "ticker": parts[0].strip(),
                "signal": parts[1].strip(),
                "reason": parts[2].strip(),
                "headline": headline,
                "time": item.get('datetime', 0)
            }
        return None
    except:
        return None

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
    # Fetch 40 items to filter down
    all_news = []
    for cat in ["general", "forex", "crypto"]:
        try:
            url = f"https://finnhub.io/api/v1/news?category={cat}&token={api_key}"
            data = requests.get(url).json()
            if isinstance(data, list):
                all_news.extend(data)
        except: pass
    
    all_news.sort(key=lambda x: x.get('datetime', 0), reverse=True)
    return all_news[:40]

# --- MAIN APP ---
if st.button("🚀 Run Turbo Analysis"):
    if not FINNHUB_KEY or not OPENAI_KEY:
        st.error("⚠️ Enter API Keys in Sidebar!")
    else:
        client = OpenAI(api_key=OPENAI_KEY)
        tab1, tab2 = st.tabs(["📊 My Portfolio", "🌎 Turbo Wire"])

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

        # --- TAB 2: TURBO WIRE ---
        with tab2:
            st.subheader("🚨 Verified Asset News (Parallel Processing)")
            
            # 1. Fetch Raw News
            raw_news = fetch_general_news(FINNHUB_KEY)
            st.caption(f"Scanned {len(raw_news)} headlines. Filtering noise...")
            
            valid_results = []
            
            # 2. THE TURBO ENGINE (Parallel Execution)
            # We spin up 10 workers to hit OpenAI simultaneously
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                # 'future_to_item' maps the task to the data
                futures = [executor.submit(analyze_single_headline, item, client) for item in raw_news]
                
                # As they finish, we collect them
                for future in concurrent.futures.as_completed(futures):
                    result = future.result()
                    if result:
                        valid_results.append(result)
            
            # 3. Sort by Time (Since parallel finishes in random order)
            valid_results.sort(key=lambda x: x['time'], reverse=True)
            
            # 4. Display
            if valid_results:
                for res in valid_results[:15]: # Show top 15 valid
                    with st.container():
                        c1, c2 = st.columns([1, 4])
                        with c1:
                            st.markdown(f"## {res['ticker']}")
                            st.caption(f"{res['signal']}")
                        with c2:
                            st.markdown(f"**{res['headline']}**")
                            st.info(f"{res['reason']}")
                        st.divider()
            else:
                st.warning("No valid tickers found in current batch.")
