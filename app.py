import streamlit as st
import yfinance as yf
import requests
import xml.etree.ElementTree as ET
import time
import pandas as pd
import altair as alt
from openai import OpenAI
from PIL import Image

# --- CONFIGURATION ---
try:
    icon_img = Image.open("logo.png")
    st.set_page_config(page_title="PennyPulse Pro", page_icon=icon_img, layout="wide")
except:
    st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="wide")

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
    "BAER":    {"entry": 1.8697, "date": "Dec 31"},
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

# 1. Read from URL (or default)
query_params = st.query_params
if "watchlist" in query_params:
    saved_watchlist = query_params["watchlist"]
else:
    saved_watchlist = ""

# 2. Input Box
user_input = st.sidebar.text_input("Add Tickers", value=saved_watchlist)

# 3. Update URL if changed
if user_input != saved_watchlist:
    st.query_params["watchlist"] = user_input
    # No rerun needed, Streamlit handles the URL update dynamically

watchlist_list = [x.strip().upper() for x in user_input.split(",")]

st.sidebar.divider()
st.sidebar.header("🔔 Price Alert")
all_assets = sorted(list(set(list(MY_PORTFOLIO.keys()) + watchlist_list)))
alert_ticker = st.sidebar.selectbox("Alert Asset", all_assets)
alert_price = st.sidebar.number_input("Target Price ($)", min_value=0.0, value=0.0, step=0.5)
alert_active = st.sidebar.toggle("Activate Alert")

if not alert_active:
    st.session_state['alert_triggered'] = False 

st.sidebar.divider()
st.sidebar.header("📈 Chart Room")
MARKET_TICKERS = ["SPY", "QQQ", "SI=F", "BTC-USD", "ETH-USD", "GC=F", "CL=F"]
chart_ticker = st.sidebar.selectbox("Select Asset", sorted(list(set(MARKET_TICKERS + all_assets))))

st.title("⚡ Penny Pulse Pro")

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
        
        volume = history['Volume'].iloc[-1]
        if volume == 0 and len(history) > 1: volume = history['Volume'].iloc[-2]

        delta = history['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        history['RSI'] = 100 - (100 / (1 + rs))
        return {
            "price": live_price, "delta": delta_pct, "volume": volume,
            "rsi": history['RSI'].iloc[-1]
        }
    except: return None

def format_volume(num):
    if num >= 1_000_000: return f"{num/1_000_000:.1f}M"
    if num >= 1_000: return f"{num/1_000:.1f}K"
    return str(num)

def display_ticker_grid(ticker_list, live_mode=False):
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
                    rsi_sig = "🔴 Over" if data['rsi'] > 70 else ("🟢 Under" if data['rsi'] < 30 else "⚪ Neut")
                    vol_str = format_volume(data['volume'])
                    st.metric(label=f"{tick} (Vol: {vol_str})", value=f"${data['price']:,.2f}", delta=f"{data['delta']:.2f}%")
                    st.caption(f"RSI: {data['rsi']:.0f} | {rsi_sig}")
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

# --- TABS LAYOUT ---
tab1, tab2, tab3, tab4 = st.tabs(["🏠 Dashboard", "🚀 My Portfolio", "📰 News", "📈 Chart Room"])

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

with tab4:
    st.subheader(f"📈 Chart: {chart_ticker}")
    live_chart = st.toggle("🔴 Enable Live Chart (5s Refresh)", key="live_chart")
    
    price_container = st.empty()
    st.markdown("### Volume Profile")
    volume_container = st.empty()
    
    def render_chart():
        try:
            # 1. ALERT CHECK
            if alert_active and not st.session_state['alert_triggered']:
                check_tick = yf.Ticker(alert_ticker)
                curr_price = check_tick.fast_info['last_price']
                if curr_price >= alert_price:
                    st.toast(f"🚨 ALERT: {alert_ticker} HIT ${curr_price:,.2f}!", icon="🔥")
                    st.session_state['alert_triggered'] = True
            
            # 2. RENDER CHART
            tick_obj = yf.Ticker(chart_ticker)
            chart_data = tick_obj.history(period="1d", interval="5m")
            if chart_data.empty: chart_data = tick_obj.history(period="5d", interval="5m")

            if not chart_data.empty:
                chart_data = chart_data.dropna().reset_index()
                chart_data.columns = ['Datetime'] + list(chart_data.columns[1:])
                chart_data['SMA 20'] = chart_data['Close'].rolling(window=20).mean()

                with price_container:
                    curr = chart_data['Close'].iloc[-1]
                    diff = curr - chart_data['Close'].iloc[0]
                    st.metric("Current Price", f"${curr:,.2f}", f"{diff:,.2f}")
                    
                    base = alt.Chart(chart_data).encode(x='Datetime:T')
                    price_line = base.mark_line().encode(
                        y=alt.Y('Close', scale=alt.Scale(zero=False), title='Price'),
                        tooltip=['Datetime:T', 'Close']
                    )
                    sma_line = base.mark_line(color='orange', opacity=0.8).encode(y='SMA 20')
                    st.altair_chart((price_line + sma_line).interactive(), use_container_width=True)

                base = alt.Chart(chart_data).encode(x='Datetime:T')
                vol_bar = base.mark_bar().encode(
                    y=alt.Y('Volume', title='Vol'),
                    color=alt.condition("datum.Open < datum.Close", alt.value("green"), alt.value("red"))
                ).properties(height=150)
                
                with volume_container:
                    st.altair_chart(vol_bar, use_container_width=True)
            else:
                with price_container: st.warning("Waiting for Market Data...")
        except Exception as e:
            with price_container: st.error(f"Sync Issue: {e}")

    render_chart()
    if live_chart:
        while True:
            time.sleep(5)
            render_chart()

st.success("✅ System Ready (Stable URL Edition)")
