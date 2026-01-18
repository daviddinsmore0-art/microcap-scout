import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
from openai import OpenAI
from PIL import Image

# --- CONFIGURATION ---
try:
    icon_img = Image.open("logo.png")
    st.set_page_config(page_title="Penny Pulse", page_icon=icon_img, layout="wide")
except:
    st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="wide")

if 'live_mode' not in st.session_state: st.session_state['live_mode'] = False
if 'news_results' not in st.session_state: st.session_state['news_results'] = []

if "OPENAI_KEY" in st.secrets:
    OPENAI_KEY = st.secrets["OPENAI_KEY"]
else:
    st.sidebar.header("🔑 Login")
    OPENAI_KEY = st.sidebar.text_input("OpenAI Key", type="password")

# --- 🗓️ MANUAL EARNINGS LIST (Edit Here) ---
MANUAL_EARNINGS = {
    "TMQ": "2026-02-13",
    "NFLX": "2026-01-20",
    "PG": "2026-01-22",
    "UAL": "2026-01-21"
}

# --- 💼 SHARED PORTFOLIO ---
MY_PORTFOLIO = {
    "HIVE": {"entry": 3.19, "date": "Jan 7"},
    "BAER": {"entry": 1.86, "date": "Dec 31"},
    "TX":   {"entry": 38.10, "date": "Dec 29"},
    "IMNN": {"entry": 3.22, "date": "Dec 29"}, 
    "RERE": {"entry": 5.31, "date": "Dec 29"}
}

# --- SIDEBAR ---
st.sidebar.divider()
try:
    st.sidebar.image("logo.png", width=150) 
except:
    st.sidebar.header("⚡ Penny Pulse")

# --- 🧠 MEMORY SYSTEM ---
st.sidebar.header("👀 Watchlist")
query_params = st.query_params
if "watchlist" in query_params:
    saved_watchlist = query_params["watchlist"]
else:
    saved_watchlist = "TD.TO, CCO.TO, IVN.TO, BN.TO, VCIG, TMQ, NKE, NFLX, UAL, PG"

user_input = st.sidebar.text_input("Add Tickers", value=saved_watchlist)
if user_input != saved_watchlist:
    st.query_params["watchlist"] = user_input

watchlist_list = [x.strip().upper() for x in user_input.split(",")]
ALL_ASSETS = list(set(watchlist_list + list(MY_PORTFOLIO.keys())))

st.sidebar.divider()
st.sidebar.header("🔔 Price Alert")
alert_ticker = st.sidebar.selectbox("Alert Asset", sorted(ALL_ASSETS))
alert_price = st.sidebar.number_input("Target Price ($)", min_value=0.0, value=0.0, step=0.5)
alert_active = st.sidebar.toggle("Activate Alert")

# --- SYMBOL NAMES ---
SYMBOL_NAMES = {
    "TSLA": "Tesla", "NVDA": "Nvidia", "BTC-USD": "Bitcoin",
    "AMD": "AMD", "PLTR": "Palantir", "AAPL": "Apple", "MSFT": "Microsoft",
    "GOOGL": "Google", "AMZN": "Amazon", "META": "Meta", "NFLX": "Netflix",
    "SPY": "S&P 500", "QQQ": "Nasdaq", "IWM": "Russell 2k", "DIA": "Dow Jones",
    "^DJI": "Dow Jones", "^IXIC": "Nasdaq", "^GSPTSE": "TSX Composite",
    "GC=F": "Gold", "SI=F": "Silver", "CL=F": "Crude Oil", "DX-Y.NYB": "USD Index", "^VIX": "VIX",
    "HIVE": "HIVE Digital", "RERE": "ATRenew", "TX": "Ternium", "UAL": "United Airlines", "PG": "Procter & Gamble",
    "TMQ": "Trilogy Metals", "VCIG": "VCI Global", "TD.TO": "TD Bank", "CCO.TO": "Cameco", "IVN.TO": "Ivanhoe Mines", "BN.TO": "Brookfield", "NKE": "Nike"
}

MACRO_TICKERS = ["SPY", "^IXIC", "^DJI", "^GSPTSE", "IWM", "GC=F", "SI=F", "CL=F", "DX-Y.NYB", "^VIX", "BTC-USD"]

# --- ⚡ BATCH LOADER (1 MONTH for RSI) ---
@st.cache_data(ttl=60)
def load_market_data(tickers):
    if not tickers: return None
    try:
        # Request 1 Month (1mo) to ensure we have enough candles for RSI-14
        data = yf.download(tickers, period="1mo", group_by='ticker', progress=False, threads=True)
        return data
    except: return None

BATCH_DATA = load_market_data(ALL_ASSETS)

# --- FUNCTIONS ---
def get_live_price(symbol):
    try:
        ticker = yf.Ticker(symbol)
        price = ticker.fast_info['last_price']
        prev = ticker.fast_info['previous_close']
        delta = ((price - prev) / prev) * 100
        return price, delta
    except: return 0.0, 0.0

def fetch_from_batch(symbol):
    try:
        clean_symbol = symbol.strip().upper()
        
        # Handle Batch Data Structure
        df = None
        if BATCH_DATA is not None:
            # If multiple tickers, it uses a MultiIndex
            if isinstance(BATCH_DATA.columns, pd.MultiIndex):
                if clean_symbol in BATCH_DATA.columns.levels[0]:
                    df = BATCH_DATA[clean_symbol].copy()
            # If single ticker (edge case), it's a flat index
            elif clean_symbol == ALL_ASSETS[0]: 
                df = BATCH_DATA.copy()

        if df is None or df.empty: return None
        
        # Clean Data
        df = df.dropna(subset=['Close'])
        if df.empty: return None

        # Price Info
        reg_price = df['Close'].iloc[-1]
        if len(df) > 1: prev_close = df['Close'].iloc[-2]
        else: prev_close = df['Open'].iloc[-1]

        is_crypto = symbol.endswith("-USD") or "BTC" in symbol
        day_pct = ((reg_price - prev_close) / prev_close) * 100 if prev_close > 0 else 0.0
        
        if is_crypto:
            color = "green" if day_pct >= 0 else "red"
            ext_str = f"**⚡ Live: ${reg_price:,.2f} (:{color}[{day_pct:+.2f}%])**"
        else:
            ext_str = f"**🌙 Ext: ${reg_price:,.2f} (:gray[Market Closed])**"

        volume = df['Volume'].iloc[-1]
        
        # RSI & Trend Calculation
        rsi_val = 50
        trend_str = ":gray[**WAIT**]"
        
        try:
            if len(df) >= 14:
                delta = df['Close'].diff()
                gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                rs = gain / loss
                df['RSI'] = 100 - (100 / (1 + rs))
                rsi_val = df['RSI'].iloc[-1]
                
                ema12 = df['Close'].ewm(span=12, adjust=False).mean()
                ema26 = df['Close'].ewm(span=26, adjust=False).mean()
                macd = ema12 - ema26
                if macd.iloc[-1] > 0: trend_str = ":green[**BULL**]" 
                else: trend_str = ":red[**BEAR**]"
        except: pass

        # Earnings Radar
        earnings_msg = ""
        next_date = None
        if clean_symbol in MANUAL_EARNINGS:
            try:
                next_date = datetime.strptime(MANUAL_EARNINGS[clean_symbol], "%Y-%m-%d")
            except: pass

        if next_date:
            if hasattr(next_date, "replace"): next_date = next_date.replace(tzinfo=None)
            now = datetime.now().replace(tzinfo=None)
            days_diff = (next_date - now).days
            
            if -1 <= days_diff <= 8:
                earnings_msg = f":rotating_light: **Earnings: {days_diff} Days!**"
            elif 8 < days_diff <= 90:
                fmt_date = next_date.strftime("%b %d")
                earnings_msg = f":calendar: **Earn: {fmt_date}**"

        return {
            "reg_price": reg_price, "day_delta": day_pct, "ext_str": ext_str,
            "volume": volume, "rsi": rsi_val, "trend": trend_str, "earn_str": earnings_msg
        }
    except: return None

def format_volume(num):
    if num >= 1_000_000: return f"{num/1_000_000:.1f}M"
    if num >= 1_000: return f"{num/1_000:.1f}K"
    return str(num)

# --- NEWS FUNCTIONS ---
def fetch_rss_items():
    headers = {'User-Agent': 'Mozilla/5.0'}
    urls = [
        "https://rss.app/feeds/tMfefT7whS1oe2VT.xml",
        "https://rss.app/feeds/T1dwxaFTbqidPRNW.xml",
        "https://rss.app/feeds/jjNMcVmfZ51Jieij.xml"
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
    except Exception as e: return []

# --- MAIN APP UI ---
st.title("⚡ Penny Pulse")

def render_ticker_tape(tickers):
    ticker_items = []
    for tick in tickers:
        p, d = get_live_price(tick)
        color = "#4caf50" if d >= 0 else "#f44336"
        arrow = "▲" if d >= 0 else "▼"
        display_name = SYMBOL_NAMES.get(tick, tick) 
        ticker_items.append(f"<span style='margin-right: 40px; font-weight: 900; font-size: 20px; color: white;'>{display_name}: <span style='color: {color};'>${p:,.2f} {arrow} {d:.2f}%</span></span>")
    content_str = ' '.join(ticker_items)
    st.markdown(f"""
    <style>
    .ticker-wrap {{ width: 100%; overflow: hidden; background-color: #0e1117; border-bottom: 2px solid #444; white-space: nowrap; box-sizing: border-box; height: 50px; display: flex; align-items: center; }}
    .ticker {{ display: inline-block; white-space: nowrap; animation: ticker 100s linear infinite; }}
    @keyframes ticker {{ 0% {{ transform: translateX(0); }} 100% {{ transform: translateX(-100%); }} }}
    </style>
    <div class="ticker-wrap"><div class="ticker">{content_str} {content_str} {content_str}</div></div>
    """, unsafe_allow_html=True)

render_ticker_tape(MACRO_TICKERS)

# --- TABS LAYOUT ---
tab1, tab2, tab3 = st.tabs(["🏠 Dashboard", "🚀 My Portfolio", "📰 News"])

def display_ticker_grid(ticker_list, live_mode=False):
    if alert_active:
        try:
            if BATCH_DATA is not None:
                # Handle single ticker edge case
                if isinstance(BATCH_DATA.columns, pd.MultiIndex):
                    if alert_ticker in BATCH_DATA.columns.levels[0]:
                        curr_price = BATCH_DATA[alert_ticker]['Close'].iloc[-1]
                elif alert_ticker == ALL_ASSETS[0]:
                     curr_price = BATCH_DATA['Close'].iloc[-1]
                
                if 'curr_price' in locals() and curr_price >= alert_price and not st.session_state.get('alert_triggered', False):
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
                data = fetch_from_batch(tick)
                if data:
                    vol_str = format_volume(data['volume'])
                    
                    # RSI Formatting
                    rsi_v = data['rsi']
                    if rsi_v > 70: rsi_disp = f"{rsi_v:.0f} (🔥 Over)"
                    elif rsi_v < 30: rsi_disp = f"{rsi_v:.0f} (🧊 Under)"
                    else: rsi_disp = f"{rsi_v:.0f} (⚪ Neut)"

                    st.metric(label=f"{tick} (Vol: {vol_str})", value=f"${data['reg_price']:,.2f}", delta=f"{data['day_delta']:.2f}% (Close)")
                    st.markdown(data['ext_str'])
                    if data.get('earn_str'): st.markdown(data['earn_str'])
                    st.caption(f"{data['trend']} | RSI: {rsi_disp}")
                    st.divider()
                else: st.error(f"⚠️ {tick} No Data")

with tab1:
    st.subheader("My Watchlist")
    st.caption(f"Currently Tracking: {', '.join(watchlist_list)}")
    live_on = st.toggle("🔴 Enable Live Prices", key="live_market") 
    display_ticker_grid(watchlist_list, live_mode=live_on)

with tab2:
    st.subheader("My Picks")
    cols = st.columns(3)
    for i, (ticker, info) in enumerate(MY_PORTFOLIO.items()):
        with cols[i % 3]:
            data = fetch_from_batch(ticker)
            if data:
                current = data['reg_price'] 
                entry = info['entry']
                total_return = ((current - entry) / entry) * 100
                st.metric(label=f"{ticker} (Since {info['date']})", value=f"${current:,.2f}", delta=f"{total_return:.2f}% (Total)")
                if data['ext_str']: st.markdown(data['ext_str'])
                if data.get('earn_str'): st.markdown(data['earn_str'])
                st.caption(f"Entry: ${entry:,.2f}")
                st.divider()
            else: st.warning(f"Loading {ticker}...")

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
            display_name = SYMBOL_NAMES.get(tick, tick)
            b_color = "gray" if tick == "MACRO" else "blue"
            with st.container():
                c1, c2 = st.columns([1, 4])
                with c1:
                    st.markdown(f"### :{b_color}[{display_name}]")
                    st.caption(f"{res['signal']}")
                with c2:
                    st.markdown(f"**[{res['title']}]({res['link']})**")
                    st.info(f"{res['reason']}")
                st.divider()

st.success("✅ System Ready (v4.3 - Full Power)")
