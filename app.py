import streamlit as st
import requests
import yfinance as yf
import pandas as pd
import xml.etree.ElementTree as ET
from openai import OpenAI

# --- CONFIGURATION ---
st.set_page_config(page_title="PennyPulse Pro", page_icon="⚡", layout="wide")

if "OPENAI_KEY" in st.secrets:
    OPENAI_KEY = st.secrets["OPENAI_KEY"]
else:
    st.sidebar.header("🔑 Login")
    OPENAI_KEY = st.sidebar.text_input("OpenAI Key", type="password")

# --- SETTINGS ---
st.sidebar.divider()
st.sidebar.header("⚡ Watchlist")
user_input = st.sidebar.text_input("Portfolio", value="TSLA, NVDA, GME, BTC-USD")
stock_list = [x.strip().upper() for x in user_input.split(",")]

st.title("⚡ PennyPulse Pro")
st.caption("Quant Data + Batch-Processed News")

# --- INSTANT TICKER MAP (The Cheat Sheet) ---
TICKER_MAP = {
    "TESLA": "TSLA", "MUSK": "TSLA", "CYBERTRUCK": "TSLA",
    "NVIDIA": "NVDA", "JENSEN": "NVDA", "AI CHIP": "NVDA",
    "APPLE": "AAPL", "IPHONE": "AAPL", "MAC": "AAPL",
    "MICROSOFT": "MSFT", "WINDOWS": "MSFT", "OPENAI": "MSFT",
    "GOOGLE": "GOOGL", "GEMINI": "GOOGL", "YOUTUBE": "GOOGL",
    "AMAZON": "AMZN", "AWS": "AMZN", "PRIME": "AMZN",
    "META": "META", "FACEBOOK": "META", "INSTAGRAM": "META",
    "NETFLIX": "NFLX", "DISNEY": "DIS",
    "BITCOIN": "BTC-USD", "CRYPTO": "BTC-USD", "COINBASE": "COIN",
    "GOLD": "GC=F", "OIL": "CL=F", "FED": "USD", "POWELL": "USD"
}

# --- FUNCTIONS ---
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

def fetch_rss_headlines():
    # Grabs top headlines from CNBC & MarketWatch
    urls = [
        "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=15839069",
        "https://feeds.content.dowjones.io/public/rss/mw_topstories"
    ]
    all_news = []
    for url in urls:
        try:
            response = requests.get(url, timeout=2)
            root = ET.fromstring(response.content)
            for item in root.findall('.//item'):
                title = item.find('title').text
                if title and len(title) > 10:
                    all_news.append(title)
        except: continue
    return all_news[:6] # Top 6 for Batch Speed

def analyze_batch(headlines, client):
    """
    Sends ALL headlines in ONE request. 10x Faster.
    """
    # 1. Pre-process with Cheat Sheet
    numbered_list = ""
    for i, hl in enumerate(headlines):
        # Check map
        hint = ""
        upper_hl = hl.upper()
        for key, val in TICKER_MAP.items():
            if key in upper_hl:
                hint = f"(Hint: {val})"
                break
        numbered_list += f"{i+1}. {hl} {hint}\n"

    # 2. The Batch Prompt
    prompt = f"""
    Analyze these {len(headlines)} headlines.
    For each, identify the Ticker (or use "MACRO"), the Sentiment (🟢/🔴/⚪), and a 3-word reason.
    
    Headlines:
    {numbered_list}
    
    Output Format (one per line):
    Ticker | Signal | Reason
    """
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200
        )
        return response.choices[0].message.content.strip().split("\n")
    except:
        return []

# --- MAIN APP ---
if st.button("🚀 Run Analysis"):
    if not OPENAI_KEY:
        st.error("⚠️ Enter OpenAI Key!")
    else:
        client = OpenAI(api_key=OPENAI_KEY)
        tab1, tab2 = st.tabs(["📊 Portfolio", "🌎 Turbo Wire"])

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

        # --- TAB 2: BATCH WIRE ---
        with tab2:
            st.subheader("🚨 Global Wire (Batch Mode)")
            
            # 1. Fetch
            headlines = fetch_rss_headlines()
            
            if not headlines:
                st.error("⚠️ News Offline.")
            else:
                # 2. Analyze (ONE SPINNER FOR EVERYTHING)
                with st.spinner(f"Analyzing {len(headlines)} headlines at once..."):
                    results = analyze_batch(headlines, client)
                
                # 3. Display
                for i, line in enumerate(results):
                    if "|" in line:
                        parts = line.split("|")
                        if len(parts) >= 3:
                            ticker = parts[0].strip()
                            signal = parts[1].strip()
                            reason = parts[2].strip()
                            
                            # Clean Display
                            headline_text = headlines[i] if i < len(headlines) else "Headline Error"
                            
                            # Badges
                            if ticker in ["MACRO", "SECTOR"]:
                                badge = "🌎 MACRO"
                                b_color = "gray"
                            else:
                                badge = ticker
                                b_color = "blue"

                            with st.container():
                                c1, c2 = st.columns([1, 4])
                                with c1:
                                    st.markdown(f"### :{b_color}[{badge}]")
                                    st.caption(f"{signal}")
                                with c2:
                                    st.markdown(f"**{headline_text}**")
                                    st.info(f"{reason}")
                                st.divider()
