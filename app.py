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

# --- 2. SETTINGS ---
st.sidebar.divider()
st.sidebar.header("⚡ Watchlist")
user_input = st.sidebar.text_input("My Portfolio", value="TSLA, NVDA, GME, BTC-USD")
stock_list = [x.strip().upper() for x in user_input.split(",")]

st.title("⚡ PennyPulse Pro")
st.caption("Quant Data + Instant-Tag News")

# --- 3. THE "INSTANT-TAG" DICTIONARY ---
# Python matches these keywords to tickers INSTANTLY (0ms latency).
TICKER_MAP = {
    # TECH
    "TESLA": "TSLA", "MUSK": "TSLA", "CYBERTRUCK": "TSLA",
    "NVIDIA": "NVDA", "JENSEN": "NVDA", "GPU": "NVDA", "AI CHIP": "NVDA",
    "APPLE": "AAPL", "IPHONE": "AAPL", "MAC": "AAPL", "TIM COOK": "AAPL",
    "MICROSOFT": "MSFT", "WINDOWS": "MSFT", "AZURE": "MSFT", "OPENAI": "MSFT",
    "GOOGLE": "GOOGL", "ALPHABET": "GOOGL", "SEARCH": "GOOGL", "YOUTUBE": "GOOGL",
    "AMAZON": "AMZN", "AWS": "AMZN", "BEZOS": "AMZN", "PRIME": "AMZN",
    "META": "META", "FACEBOOK": "META", "ZUCKERBERG": "META", "INSTAGRAM": "META",
    "NETFLIX": "NFLX", "STREAMING": "NFLX",
    "AMD": "AMD", "INTEL": "INTC", "TSMC": "TSM",
    
    # MEME / RETAIL
    "GAMESTOP": "GME", "COHEN": "GME",
    "AMC": "AMC", "MOVIES": "AMC",
    "HOOD": "HOOD", "ROBINHOOD": "HOOD",
    "REDDIT": "RDDT",
    
    # CRYPTO
    "BITCOIN": "BTC-USD", "BTC": "BTC-USD", "CRYPTO": "BTC-USD",
    "ETHEREUM": "ETH-USD", "ETHER": "ETH-USD",
    "COINBASE": "COIN", "BINANCE": "BNB-USD",
    
    # COMMODITIES
    "GOLD": "GC=F", "SILVER": "SI=F",
    "OIL": "CL=F", "CRUDE": "CL=F", "ENERGY": "XLE",
    
    # MACRO / BANKS
    "FED": "USD", "POWELL": "USD", "RATES": "USD", "INFLATION": "USD",
    "JPMORGAN": "JPM", "DIMON": "JPM",
    "GOLDMAN": "GS", "BANK OF AMERICA": "BAC",
    "BOEING": "BA", "AIRBUS": "EADSY",
    "DISNEY": "DIS", "WALMART": "WMT", "COSTCO": "COST"
}

# --- FUNCTIONS ---
def analyze_headline(headline, client):
    # 1. INSTANT PYTHON TAGGING
    # Check if we can find the ticker without asking AI
    upper_hl = headline.upper()
    found_ticker = None
    
    for keyword, symbol in TICKER_MAP.items():
        if keyword in upper_hl:
            found_ticker = symbol
            break
            
    # If Python found it, we tell the AI: "Focus on THIS stock."
    context = f"Ticker is {found_ticker}" if found_ticker else "Find the ticker."
    
    try:
        # 2. FAST AI ANALYSIS
        # We ask for a very short response to speed up generation
        prompt = f"""
        Headline: "{headline}"
        Context: {context}
        
        Task:
        1. Identify Ticker (Use context if available). If Macro news, use "MACRO".
        2. Signal: 🟢, 🔴, or ⚪.
        3. Reason: Max 3 words.
        
        Format: Ticker | Signal | Reason
        """
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=30 # Keep tokens low = FASTER
        )
        return response.choices[0].message.content.strip()
    except:
        return f"{found_ticker if found_ticker else 'MACRO'} | ⚪ | AI Busy"

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
    # CNBC and MarketWatch
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
    return all_news[:10]

# --- MAIN APP ---
if st.button("🚀 Run Analysis"):
    if not OPENAI_KEY:
        st.error("⚠️ Enter OpenAI Key!")
    else:
        client = OpenAI(api_key=OPENAI_KEY)
        tab1, tab2 = st.tabs(["📊 My Portfolio", "🌎 Instant Wire"])

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

        # --- TAB 2: INSTANT WIRE ---
        with tab2:
            st.subheader("🚨 Global Wire")
            
            headlines = fetch_rss_feed()
            headlines = headlines[:6] # Top 6 stories for MAX speed
            
            if not headlines:
                st.error("⚠️ News Feed Offline.")
            else:
                progress_bar = st.progress(0)
                
                for i, headline in enumerate(headlines):
                    # FAST ANALYSIS
                    ai_result = analyze_headline(headline, client)
                    
                    progress_bar.progress((i + 1) / len(headlines))
                    
                    parts = ai_result.split("|")
                    if len(parts) == 3:
                        ticker, signal, reason = parts[0].strip(), parts[1].strip(), parts[2].strip()
                        
                        # --- UI UPGRADE: BIG TICKER BADGE ---
                        if ticker == "MACRO": 
                            badge_color = "gray"
                            ticker_display = "🌎 MACRO"
                        else: 
                            badge_color = "blue"
                            ticker_display = ticker

                        with st.container():
                            c1, c2 = st.columns([1, 4])
                            with c1:
                                # BIG BOLD TICKER
                                st.markdown(f"### :{badge_color}[{ticker_display}]")
                                st.caption(f"{signal} Sentiment")
                            with c2:
                                st.markdown(f"**{headline}**")
                                st.info(f"{reason}")
                            st.divider()
                
                progress_bar.empty()
