import streamlit as st
import requests
import yfinance as yf
import pandas as pd
import xml.etree.ElementTree as ET
from openai import OpenAI

# --- CONFIGURATION ---
st.set_page_config(page_title="PennyPulse Pro", page_icon="⚡", layout="wide")

# --- 1. KEY LOADER ---
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
st.caption("Quant Data + Stable News Wire")

# --- CHEAT SHEET (Instant Tickers) ---
TICKER_MAP = {
    "TESLA": "TSLA", "MUSK": "TSLA",
    "NVIDIA": "NVDA", "AI": "NVDA",
    "APPLE": "AAPL", "IPHONE": "AAPL",
    "MICROSOFT": "MSFT", "WINDOWS": "MSFT",
    "GOOGLE": "GOOGL", "ALPHABET": "GOOGL",
    "AMAZON": "AMZN", "AWS": "AMZN",
    "META": "META", "FACEBOOK": "META",
    "NETFLIX": "NFLX",
    "BITCOIN": "BTC-USD", "CRYPTO": "BTC-USD",
    "GOLD": "GC=F",
    "OIL": "CL=F", "CRUDE": "CL=F",
    "FED": "USD", "POWELL": "USD", "RATES": "USD"
}

# --- FUNCTIONS ---
def get_ai_analysis(headline, client):
    try:
        # 1. Check Cheat Sheet first (Instant)
        upper_hl = headline.upper()
        pre_ticker = "MARKET"
        for keyword, symbol in TICKER_MAP.items():
            if keyword in upper_hl:
                pre_ticker = symbol
                break

        # 2. Ask AI
        prompt = f"""
        Headline: "{headline}"
        Context: Ticker might be {pre_ticker}.
        Task: 
        1. Confirm Ticker (e.g. 'Boeing' -> 'BA'). If generic, use "MARKET".
        2. Signal: 🟢, 🔴, or ⚪.
        3. Reason: 5 words max.
        
        Format: Ticker | Signal | Reason
        """
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=50
        )
        return response.choices[0].message.content.strip()
    except:
        return f"MARKET | ⚪ | AI Busy"

def fetch_quant_data(symbol):
    try:
        ticker = yf.Ticker(symbol)
        history = ticker.history(period="3mo", interval="1d", prepost=True)
        if history.empty: return None

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

def fetch_rss_feed():
    urls = [
        "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=15839069",
        "https://feeds.content.dowjones.io/public/rss/mw_topstories"
    ]
    all_news = []
    for url in urls:
        try:
            response = requests.get(url, timeout=3)
            root = ET.fromstring(response.content)
            for item in root.findall('.//item'):
                title = item.find('title').text
                if title and len(title) > 10:
                    all_news.append(title)
        except: continue
    return all_news[:10] # Grab top 10

# --- MAIN APP ---
if st.button("🚀 Run Analysis"):
    if not OPENAI_KEY:
        st.error("⚠️ Enter OpenAI Key!")
    else:
        client = OpenAI(api_key=OPENAI_KEY)
        tab1, tab2 = st.tabs(["📊 My Portfolio", "🌎 Stable Wire"])

        # --- TAB 1: QUANT ---
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

        # --- TAB 2: STABLE RSS ---
        with tab2:
            st.subheader("🚨 Global Wire (Top 5 Stories)")
            
            # 1. Fetch Headlines
            headlines = fetch_rss_feed()
            
            if not headlines:
                st.error("⚠️ RSS Feed Connection Failed.")
            else:
                # 2. Limit to Top 5 for Speed
                headlines = headlines[:5]
                
                # 3. Progress Bar
                progress_bar = st.progress(0)
                
                for i, headline in enumerate(headlines):
                    # Analysis
                    ai_result = get_ai_analysis(headline, client)
                    
                    # Update Bar
                    progress_bar.progress((i + 1) / len(headlines))
                    
                    # Display Result
                    parts = ai_result.split("|")
                    if len(parts) == 3:
                        ticker, signal, reason = parts[0].strip(), parts[1].strip(), parts[2].strip()
                        if ticker == "MARKET": ticker = "🌎 MKT"

                        with st.container():
                            c1, c2 = st.columns([1, 4])
                            with c1:
                                st.markdown(f"## {ticker}")
                                st.caption(f"{signal}")
                            with c2:
                                st.markdown(f"**{headline}**")
                                st.info(f"{reason}")
                            st.divider()
                
                # Hide Bar when done
                progress_bar.empty()
