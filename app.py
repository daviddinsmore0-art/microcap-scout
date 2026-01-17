import streamlit as st
import yfinance as yf
import requests
import xml.etree.ElementTree as ET
import time
import pandas as pd
from openai import OpenAI
from PIL import Image

# --- CONFIGURATION ---
try:
    icon_img = Image.open("logo.png")
    st.set_page_config(page_title="PennyPulse Pro", page_icon=icon_img, layout="wide")
except:
    st.set_page_config(page_title="PennyPulse Pro", page_icon="⚡", layout="wide")

if 'live_mode' not in st.session_state: st.session_state['live_mode'] = False
if 'news_results' not in st.session_state: st.session_state['news_results'] = []
if 'news_error' not in st.session_state: st.session_state['news_error'] = None
if 'alert_triggered' not in st.session_state: st.session_state['alert_triggered'] = False

if "OPENAI_KEY" in st.secrets:
    OPENAI_KEY = st.secrets["OPENAI_KEY"]
else:
    st.sidebar.header("🔑 Login")
    OPENAI_KEY = st.sidebar.text_input("OpenAI Key", type="password")

# --- 💼 SHARED PORTFOLIO ---
MY_PORTFOLIO = {
    "TSLA":    {"entry": 350.00, "date": "Dec 10"},
    "NVDA":    {"entry": 130.50, "date": "Jan 12"},
    "GME":     {"entry": 25.00,  "date": "Jan 14"},
    "BTC-USD": {"entry": 92000.00, "date": "Jan 05"}
}

# --- SIDEBAR ---
st.sidebar.divider()
try:
    st.sidebar.image("logo.png", width=150) 
except:
    st.sidebar.header("⚡ PennyPulse")

# --- 🧠 MEMORY SYSTEM (URL Method) ---
st.sidebar.header("👀 Watchlist")
query_params = st.query_params
if "watchlist" in query_params:
    saved_watchlist = query_params["watchlist"]
else:
    saved_watchlist = "AMD, PLTR"

user_input = st.sidebar.text_input("Add Tickers", value=saved_watchlist)
if user_input != saved_watchlist:
    st.query_params["watchlist"] = user_input

watchlist_list = [x.strip().upper() for x in user_input.split(",")]

st.sidebar.divider()
st.sidebar.header("🔔 Price Alert")
all_assets = sorted(list(set(list(MY_PORTFOLIO.keys()) + watchlist_list)))
alert_ticker = st.sidebar.selectbox("Alert Asset", all_assets)
alert_price = st.sidebar.number_input("Target Price ($)", min_value=0.0, value=0.0, step=0.5)
alert_active = st.sidebar.toggle("Activate Alert")

if not alert_active:
    st.session_state['alert_triggered'] = False 

# --- TICKER MAP ---
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

MARKET_TICKERS = ["SPY", "QQQ", "IWM", "BTC-USD", "ETH-USD", "GC=F", "CL=F"]

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
        # FIXED: Increased period to "1mo" so RSI has enough data (needs 14 days minimum)
        history = ticker.history(period="1mo", interval="1d", prepost=True)
        if history.empty: return None
        
        # --- 1. PRICE LOGIC ---
        # Current Live Price (Post-Market)
        live_price = ticker.fast_info['last_price']
        # Yesterday's Close (For Day Gain)
        prev_close = ticker.fast_info['previous_close']
        
        # Day Gain %
        day_delta_pct = ((live_price - prev_close) / prev_close) * 100
        
        # Extended Hours Check
        # We compare "Live Price" vs "Regular Market Last Close"
        ext_str = ""
        try:
            # Get the last 'Close' from the history table (Usually 4:00 PM price)
            regular_close = history['Close'].iloc[-1]
            
            # Calculate difference between Live (8:00 PM) and Regular (4:00 PM)
            ext_diff = live_price - regular_close
            ext_pct = (ext_diff / regular_close) * 100

            # Only show if there is a real difference (> 0.01%)
            if abs(ext_pct) > 0.01:
                color = "green" if ext_pct > 0 else "red"
                icon = "🌙" # Moon for After Hours
                ext_str = f"**{icon} Ext: :{color}[{ext_pct:+.2f}%]**"
        except:
            pass

        # --- 2. VOLUME ---
        volume = history['Volume'].iloc[-1]
        if volume == 0 and len(history) > 1: volume = history['Volume'].iloc[-2]

        # --- 3. RSI & MACD ---
        delta = history['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        history['RSI'] = 100 - (100 / (1 + rs))
        
        ema12 = history['Close'].ewm(span=12, adjust=False).mean()
        ema26 = history['Close'].ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9, adjust=False).mean()
        
        macd_val = macd.iloc[-1]
        sig_val = signal.iloc[-1]
        
        if macd_val > sig_val: 
            trend_str = ":green[**BULL**]" 
        else: 
            trend_str = ":red[**BEAR**]"

        return {
            "price": live_price, 
            "day_delta": day_delta_pct,
            "ext_str": ext_str,
            "volume": volume,
            "rsi": history['RSI'].iloc[-1],
            "trend": trend_str
        }
    except: return None

def format_volume(num):
    if num >= 1_000_000: return f"{num/1_000_000:.1f}M"
    if num >= 1_000: return f"{num/1_000:.1f}K"
    return str(num)

def display_ticker_grid(ticker_list, live_mode=False):
    if alert_active and not st.session_state['alert_triggered']:
        try:
            check_tick = yf.Ticker(alert_ticker)
            curr_price = check_tick.fast_info['last_price']
            if curr_price >= alert_price:
                st.toast(f"🚨 ALERT: {alert_ticker} HIT ${curr_price:,.2f}!", icon="🔥")
                st.session_state['alert_triggered'] = True
        except: pass

    if live_mode:
        st.info("🔴 Live Streaming Active.")
        cols = st.columns(4)
        for i, tick in enumerate(ticker_list):
            with cols[i % 4]:
                price, delta = get_live_price(tick)
                st.metric(label=tick, value=f"${price:,.2f}", delta=f"{delta:.2f}%")
    else:
        cols = st.columns(3)
        for i, tick in enumerate(ticker_list):
            with cols[i % 3]:
                data = fetch_quant_data(tick)
                if data:
                    # RSI Logic
                    rsi_val = data['rsi']
                    if pd.isna(rsi_val): 
                        rsi_disp = "N/A" # Graceful fail if still loading
                    else:
                        if rsi_val > 70:   rsi_sig = "🔥 Over"
                        elif rsi_val < 30: rsi_sig = "🧊 Under"
                        else:              rsi_sig = "⚪ Neut"
                        rsi_disp = f"{rsi_val:.0f} ({rsi_sig})"
                    
                    vol_str = format_volume(data['volume'])

                    # CARD DISPLAY
                    st.metric(
                        label=f"{tick} (Vol: {vol_str})", 
                        value=f"${data['price']:,.2f}", 
                        delta=f"{data['day_delta']:.2f}% (Day)"
                    )
                    
                    # Row 1: Trend + RSI
                    st.markdown(f"{data['trend']} | RSI: {rsi_disp}")
                    
                    # Row 2: Extended Hours (Only if exists)
                    if data['ext_str']:
                        st.markdown(data['ext_str'])
                    
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
            model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}], max_tokens=400
        )
        lines = response.choices[0].message.content.strip().split("\n")
        enriched_results = []
        item_index = 0
        for line in lines:
            clean_line = line.replace("```", "").replace("plaintext", "").strip()
            if len(clean_line) > 0 and clean_line[0].isdigit():
                parts = clean_line.split(".", 1)
                if len(parts) > 1: clean_line = parts[1].strip()
            if not clean_line: continue
            if item_index >= len(items): break
            parts = clean_line.split("|")
            if len(parts) >= 3:
                ticker = parts[0].strip()
                if len(ticker) > 6 and ticker != "BTC-USD": ticker = "MACRO"
                try:
                    enriched_results.append({
                        "ticker": ticker, "signal": parts[1].strip(), "reason": parts[2].strip(),
                        "title": items[item_index]['title'], "link": items[item_index]['link']
                    })
                    item_index += 1
                except IndexError: break
        return enriched_results
    except Exception as e:
        st.session_state['news_error'] = str(e)
        return []

st.title("⚡ PennyPulse Pro")

# --- TABS LAYOUT ---
tab1, tab2, tab3 = st.tabs(["🏠 Dashboard", "🚀 My Portfolio", "📰 News"])

with tab1:
    st.subheader("Major Indices")
    st.caption(f"Also Watching: {', '.join(watchlist_list)}")
    live_on = st.toggle("🔴 Enable Live Prices", key="live_market")
    display_ticker_grid(MARKET_TICKERS + watchlist_list, live_mode=live_on)

with tab2:
    st.subheader("My Positions")
    cols = st.columns(3)
    for i, (ticker, info) in enumerate(MY_PORTFOLIO.items()):
        with cols[i % 3]:
            data = fetch_quant_data(ticker)
            if data:
                current = data['price']
                entry = info['entry']
                total_return = ((current - entry) / entry) * 100
                st.metric(
                    label=f"{ticker} (Since {info['date']})",
                    value=f"${current:,.2f}",
                    delta=f"{total_return:.2f}% (Total)"
                )
                st.caption(f"Entry: ${entry:,.2f}")
                st.divider()
            else:
                st.warning(f"Loading {ticker}...")

with tab3:
    st.subheader("🚨 Global Wire")
    if st.button("Generate AI Report", type="primary"):
        if not OPENAI_KEY: st.error("⚠️ Enter OpenAI Key!")
        else:
            client = OpenAI(api_key=OPENAI_KEY)
            with st.spinner("Scanning Global Markets..."):
                raw_items = fetch_rss_items()
                if raw_items:
                    results = analyze_batch(raw_items, client)
                    st.session_state['news_results'] = results
                else: st.error("News feed unavailable.")
    
    results = st.session_state['news_results']
    if results:
        for res in results:
            tick = res['ticker']
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

st.success("✅ System Ready (Fixed: RSI & Ext Hours)")
