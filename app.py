import streamlit as st
import requests
import yfinance as yf
import xml.etree.ElementTree as ET
import time
from openai import OpenAI

# --- CONFIGURATION ---
st.set_page_config(page_title="PennyPulse Pro", page_icon="⚡", layout="wide")

# Initialize Session State
if 'live_mode' not in st.session_state: st.session_state['live_mode'] = False
if 'news_results' not in st.session_state: st.session_state['news_results'] = []
if 'news_error' not in st.session_state: st.session_state['news_error'] = None

if "OPENAI_KEY" in st.secrets:
    OPENAI_KEY = st.secrets["OPENAI_KEY"]
else:
    st.sidebar.header("🔑 Login")
    OPENAI_KEY = st.sidebar.text_input("OpenAI Key", type="password")

# --- SETTINGS ---
st.sidebar.divider()
st.sidebar.header("🚀 My Picks")
user_input = st.sidebar.text_input("Edit Tickers", value="TSLA, NVDA, GME, BTC-USD")
my_picks_list = [x.strip().upper() for x in user_input.split(",")]

MARKET_TICKERS = ["SPY", "QQQ", "IWM", "BTC-USD", "ETH-USD", "GC=F", "CL=F"]

st.title("⚡ PennyPulse Pro")

# --- INSTANT TICKER MAP (Reformatted for Safety) ---
TICKER_MAP = {
    "TESLA": "TSLA",
    "MUSK": "TSLA",
    "CYBERTRUCK": "TSLA",
    "NVIDIA": "NVDA",
    "JENSEN": "NVDA",
    "AI CHIP": "NVDA",
    "APPLE": "AAPL",
    "IPHONE": "AAPL",
    "MAC": "AAPL",
    "MICROSOFT": "MSFT",
    "WINDOWS": "MSFT",
    "OPENAI": "MSFT",
    "GOOGLE": "GOOGL",
    "GEMINI": "GOOGL",
    "YOUTUBE": "GOOGL",
    "AMAZON": "AMZN",
    "AWS": "AMZN",
    "PRIME": "AMZN",
    "META": "META",
    "FACEBOOK": "META",
    "INSTAGRAM": "META",
    "NETFLIX": "NFLX",
    "DISNEY": "DIS",
    "BITCOIN": "BTC-USD",
    "CRYPTO": "BTC-USD",
    "COINBASE": "COIN",
    "GOLD": "GC=F",
    "OIL": "CL=F",
    "FED": "USD",
    "POWELL": "USD",
    "JPMORGAN": "JPM",
    "GOLDMAN": "GS",
    "BOEING": "BA"
}

# --- FUNCTIONS ---
def get_live_price(symbol):
    try:
        ticker = yf.Ticker(symbol)
        price = ticker.fast_info['last_price']
        prev = ticker.fast_info['previous_close']
        delta = ((price - prev) / prev) * 100
        return price, delta
    except: return 0.0, 0.0

def fetch_quant_data(symbol):
    try:
        ticker = yf.Ticker(symbol)
        history = ticker.history(period="3mo", interval="1d", prepost=True)
        if history.empty: return None

        try:
            live_price = ticker.fast_info['last_price']
            prev_close = ticker.fast_info['previous_close']
            delta_pct = ((live_price - prev_close) / prev_close) * 100
        except:
            live_price = history['Close'].iloc[-1]
            prev_close = history['Close'].iloc[-2]
            delta_pct = ((live_price - prev_close) / prev_close) * 100

        delta = history['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        history['RSI'] = 100 - (100 / (1 + rs))

        ema12 = history['Close'].ewm(span=12, adjust=False).mean()
        ema26 = history['Close'].ewm(span=26, adjust=False).mean()
        history['MACD'] = ema12 - ema26
        history['Signal'] = history['MACD'].ewm(span=9, adjust=False).mean()

        return {
            "price": live_price,
            "delta": delta_pct,
            "rsi": history['RSI'].iloc[-1],
            "macd": history['MACD'].iloc[-1],
            "macd_sig": history['Signal'].iloc[-1]
        }
    except: return None

def display_ticker_grid(ticker_list, live_mode=False):
    if live_mode:
        st.info("🔴 Live Streaming Active. Uncheck to stop.")
        price_containers = {}
        cols = st.columns(4)
        for i, tick in enumerate(ticker_list):
            with cols[i % 4]:
                price_containers[tick] = st.empty()
        
        while True:
            for tick, container in price_containers.items():
                price, delta = get_live_price(tick)
                with container:
                    st.metric(label=tick, value=f"${price:,.2f}", delta=f"{delta:.2f}%")
            time.sleep(2)
    else:
        cols = st.columns(3)
        for i, tick in enumerate(ticker_list):
            with cols[i % 3]:
                data = fetch_quant_data(tick)
                if data:
                    rsi_sig = "🔴 Over" if data['rsi'] > 70 else ("🟢 Under" if data['rsi'] < 30 else "⚪ Neut")
                    macd_sig = "🟢 Bull" if data['macd'] > data['macd_sig'] else "🔴 Bear"
                    st.markdown(f"**{tick}**")
                    st.metric(label="Price", value=f"${data['price']:,.2f}", delta=f"{data['delta']:.2f}%")
                    c1, c2 = st.columns(2)
                    c1.caption(f"RSI: {data['rsi']:.0f} ({rsi_sig})")
                    c2.caption(f"MACD: {macd_sig}")
                    st.divider()

def fetch_rss_items():
    headers = {'User-Agent': 'Mozilla/5.0'}
    urls = [
        "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=15839069",
        "https://feeds.content.dowjones.io/public/rss/mw_topstories"
    ]
    items = []
    seen_titles = set()
    for url in urls:
        try:
            response = requests.get(url, headers=headers, timeout=3)
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
    if not items: return []
    
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
    STRICT FORMAT: Ticker | Signal | Reason
    Headlines:
    {prompt_list}
    """
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400
        )
        lines = response.choices[0].message.content.strip().split("\n")
        enriched_results = []
        item_index = 0
        
        for line in lines:
            clean_line = line.replace("```", "").replace("plaintext", "").strip()
            
            # Remove leading numbers (e.g., "25. ")
            if len(clean_line) > 0 and clean_line[0].isdigit():
                parts = clean_line.split(".", 1)
                if len(parts) > 1:
                    clean_line = parts[1].strip()
            
            if not clean_line: continue
            
            if item_index >= len(items): break

            parts = clean_line.split("|")
            if len(parts) >= 3:
                ticker = parts[0].strip()
                
                # Sector Filter
                sectors = ["Real estate", "Retail", "Chemical", "Earnings", "Tax", "Energy", "Airlines", "Semiconductor", "Munis"]
                if any(x in ticker for x in sectors): ticker = "MACRO"
                if len(ticker) > 6 and ticker != "BTC-USD": ticker = "MACRO"
                
                try:
                    enriched_results.append({
                        "ticker": ticker,
                        "signal": parts[1].strip(),
                        "reason": parts[2].strip(),
                        "title": items[item_index]['title'],
                        "link": items[item_index]['link']
                    })
                    item_index += 1
                except IndexError:
                    break
        return enriched_results
    except Exception as e:
        st.session_state['news_error'] = str(e)
        return []

# --- MAIN LAYOUT ---
tab1, tab2, tab3 = st.tabs(["🏠 Market Dashboard", "🚀 My Picks", "📰 News Wire"])

with tab1:
    st.subheader("Major Indices & Commodities")
    live_on = st.toggle("🔴 Enable Live Prices", key="live_market")
    display_ticker_grid(MARKET_TICKERS, live_mode=live_on)

with tab2:
    st.subheader("My Portfolio")
    live_on_picks = st.toggle("🔴 Enable Live Prices", key="live_picks")
    display_ticker_grid(my_picks_list, live_mode=live_on_picks)

with tab3:
    st.subheader("🚨 Global Wire")
    
    # Action Button
    if st.button("Generate AI Report", type="primary"):
        if not OPENAI_KEY:
            st.error("⚠️ Enter OpenAI Key!")
        else:
            client = OpenAI(api_key=OPENAI_KEY)
            with st.spinner("Scanning Global Markets..."):
                raw_items = fetch_rss_items()
                st.session_state['news_error'] = None 
                
                if raw_items:
                    results = analyze_batch(raw_items, client)
                    st.session_state['news_results'] = results
                else:
                    st.session_state['news_error'] = "Could not reach news feeds (Connection blocked)."
                    st.session_state['news_results'] = []

    # Display Logic
    if st.session_state['news_error']:
        st.error(f"⚠️ Error: {st.session_state['news_error']}")
        
    results = st.session_state['news_results']
    
    if results:
        ticker_counts = {}
        for res in results:
            tick = res['ticker']
            if tick not in ticker_counts: ticker_counts[tick] = 0
            if ticker_counts[tick] >= 5: continue 
            ticker_counts[tick] += 1
            
            b_color = "gray" if tick == "MACRO" else "blue"
            with st.container():
                c1, c2 = st.columns([1, 4])
                with c1:
                    st.markdown(f"### :{b_color}[{tick}]")
                    st.caption(f"{res['signal']}")
                with c2:
                    st.markdown(f"**[{res['title']}]({res['link']})**")
                    st.info(f"{res['reason']}")
                st.divider()
    elif not st.session_state['news_error'] and not results:
        st.info("Click 'Generate AI Report' to start scanning.")
