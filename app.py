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
st.caption("Quant Data + Fail-Safe News Feed")

# --- INSTANT TICKER MAP ---
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
    "GOLD": "GC=F", "OIL": "CL=F", "FED": "USD", "POWELL": "USD",
    "JPMORGAN": "JPM", "GOLDMAN": "GS", "BOEING": "BA"
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

def fetch_rss_items():
    urls = [
        "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=15839069",
        "https://feeds.content.dowjones.io/public/rss/mw_topstories"
    ]
    items = []
    seen_titles = set()
    
    for url in urls:
        try:
            response = requests.get(url, timeout=2)
            root = ET.fromstring(response.content)
            for item in root.findall('.//item'):
                title = item.find('title').text
                link = item.find('link').text
                if title and title not in seen_titles:
                    seen_titles.add(title)
                    items.append({"title": title, "link": link})
        except: continue
    
    return items[:25]

def analyze_batch(items, client):
    prompt_list = ""
    for i, item in enumerate(items):
        hl = item['title']
        hint = ""
        upper_hl = hl.upper()
        for key, val in TICKER_MAP.items():
            if key in upper_hl:
                hint = f"(Hint: {val})"
                break
        prompt_list += f"{i+1}. {hl} {hint}\n"

    prompt = f"""
    Analyze these {len(items)} headlines.
    Task: Identify Ticker (or "MACRO"), Signal (🟢/🔴/⚪), and 3-word reason.
    
    Headlines:
    {prompt_list}
    
    Output Format:
    Ticker | Signal | Reason
    """
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=350
        )
        lines = response.choices[0].message.content.strip().split("\n")
        
        enriched_results = []
        for i, line in enumerate(lines):
            if i < len(items):
                parts = line.split("|")
                # RELAXED PARSING: Even if format is weird, try to capture it
                if len(parts) >= 3:
                    ticker = parts[0].strip()
                    if "MACRO" in ticker or "MARKET" in ticker: ticker = "MACRO"
                    enriched_results.append({
                        "ticker": ticker,
                        "signal": parts[1].strip(),
                        "reason": parts[2].strip(),
                        "title": items[i]['title'],
                        "link": items[i]['link']
                    })
        return enriched_results
    except:
        return []

# --- MAIN APP ---
if st.button("🚀 Run Analysis"):
    if not OPENAI_KEY:
        st.error("⚠️ Enter OpenAI Key!")
    else:
        client = OpenAI(api_key=OPENAI_KEY)
        tab1, tab2 = st.tabs(["📊 Portfolio", "🌎 News Wire"])

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

        # --- TAB 2: NEWS ---
        with tab2:
            st.subheader("🚨 Global Wire")
            
            raw_items = fetch_rss_items()
            
            if not raw_items:
                st.error("⚠️ News Offline (Check Internet).")
            else:
                with st.spinner(f"Scanning {len(raw_items)} stories..."):
                    results = analyze_batch(raw_items, client)
                
                # --- DISPLAY LOGIC ---
                ticker_counts = {}
                displayed_count = 0
                
                # 1. Try to display AI-Filtered results
                if results:
                    for res in results:
                        tick = res['ticker']
                        if tick not in ticker_counts: ticker_counts[tick] = 0
                        
                        # RELAXED LIMIT: Allow 5 stories per ticker (prevents empty feed)
                        if ticker_counts[tick] >= 5: continue
                            
                        ticker_counts[tick] += 1
                        displayed_count += 1
                        
                        b_color = "gray" if tick == "MACRO" else "blue"

                        with st.container():
                            c1, c2 = st.columns([1, 4])
                            with c1:
                                st.markdown(f"### :{b_color}[{tick}]")
                                st.caption(f"{res['signal']}")
                            with c2:
                                st.markdown(f"**[{res['title']}]({res['link']})**")
                                st.info(f"{res['reason']}")
                                st.caption(f"[🔗 Read Source]({res['link']})")
                            st.divider()
                
                # 2. SAFETY NET: If AI failed or filtered everything, show RAW feed
                if displayed_count == 0:
                    st.warning("⚠️ AI Filters blocked all stories. Switching to Raw Feed.")
                    for item in raw_items[:10]:
                        with st.container():
                            c1, c2 = st.columns([1, 4])
                            with c1:
                                st.markdown("### :gray[RAW]")
                            with c2:
                                st.markdown(f"**[{item['title']}]({item['link']})**")
                                st.caption(f"[🔗 Read Source]({item['link']})")
                            st.divider()
