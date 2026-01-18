import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime
from PIL import Image

# --- CONFIGURATION ---
try:
    icon_img = Image.open("logo.png")
    st.set_page_config(page_title="Penny Pulse", page_icon=icon_img, layout="wide")
except:
    st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="wide")

if 'live_mode' not in st.session_state: st.session_state['live_mode'] = False

# --- 🗓️ MANUAL EARNINGS LIST (The "Back to Basics" Fix) ---
# Edit this list directly to fix dates. It overrides everything else.
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
    # YOUR FULL LIST
    saved_watchlist = "TD.TO, CCO.TO, IVN.TO, BN.TO, VCIG, TMQ, NKE, NFLX, UAL, PG"

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

# --- MACRO TAPE LIST ---
MACRO_TICKERS = [
    "SPY", "^IXIC", "^DJI", "^GSPTSE", "IWM", 
    "GC=F", "SI=F", "CL=F", "DX-Y.NYB", "^VIX", "BTC-USD"
]

# --- FUNCTIONS ---
def get_live_price(symbol):
    try:
        ticker = yf.Ticker(symbol)
        # Use history for macro too (Safer)
        hist = ticker.history(period="2d")
        if not hist.empty:
            price = hist['Close'].iloc[-1]
            prev = hist['Close'].iloc[-2] if len(hist) > 1 else price
            delta = ((price - prev) / prev) * 100
            return price, delta
        return 0.0, 0.0
    except: return 0.0, 0.0

def fetch_quant_data_tank(symbol):
    try:
        ticker = yf.Ticker(symbol)
        clean_symbol = symbol.strip().upper()
        
        # --- TANK MODE: HISTORY ONLY ---
        # We request 5 days to ensure we get data even over weekends/holidays
        try:
            hist = ticker.history(period="5d")
            if hist.empty:
                return None
            
            reg_price = hist['Close'].iloc[-1]
            # Use open or previous close
            if len(hist) > 1:
                prev_close = hist['Close'].iloc[-2]
            else:
                prev_close = hist['Open'].iloc[-1]
                
        except:
            return None

        # 2. IS THIS CRYPTO?
        is_crypto = symbol.endswith("-USD") or "BTC" in symbol or "ETH" in symbol

        # 3. CALCULATE GAINS
        if prev_close and prev_close > 0:
            day_pct = ((reg_price - prev_close) / prev_close) * 100
        else:
            day_pct = 0.0
            
        # 4. FORMAT SECOND LINE
        if is_crypto:
            color = "green" if day_pct >= 0 else "red"
            ext_str = f"**⚡ Live: ${reg_price:,.2f} (:{color}[{day_pct:+.2f}%])**"
        else:
            ext_str = f"**🌙 Ext: ${reg_price:,.2f} (:gray[Market Closed])**"

        # 5. INDICATORS (RSI / Trend)
        volume = 0
        rsi_val = 50
        trend_str = ":gray[**WAIT**]"
        
        try:
            # We already have history, let's use it if it's long enough, else fetch more
            if len(hist) < 20:
                hist = ticker.history(period="1mo", interval="1d")
            
            if not hist.empty:
                volume = hist['Volume'].iloc[-1]
                
                # RSI Calc
                delta = hist['Close'].diff()
                gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                rs = gain / loss
                hist['RSI'] = 100 - (100 / (1 + rs))
                rsi_val = hist['RSI'].iloc[-1]
                
                # MACD Trend
                ema12 = hist['Close'].ewm(span=12, adjust=False).mean()
                ema26 = hist['Close'].ewm(span=26, adjust=False).mean()
                macd = ema12 - ema26
                if macd.iloc[-1] > 0: trend_str = ":green[**BULL**]" 
                else: trend_str = ":red[**BEAR**]"
        except: pass

        # 6. EARNINGS RADAR (MANUAL OVERRIDE FIRST)
        earnings_msg = ""
        next_date = None
        source_label = ""
        
        # PRIORITY 1: Check Manual List (Line 30)
        if clean_symbol in MANUAL_EARNINGS:
            try:
                next_date = datetime.strptime(MANUAL_EARNINGS[clean_symbol], "%Y-%m-%d")
            except: pass
            
        # PRIORITY 2: Yahoo Calendar (Auto)
        if next_date is None:
            try:
                cal = ticker.calendar
                if cal is not None:
                    if isinstance(cal, dict):
                        if 'Earnings Date' in cal:
                            val = cal['Earnings Date']
                            if isinstance(val, list): next_date = val[0]
                            else: next_date = val
                        elif 0 in cal:
                            val = cal[0]
                            if isinstance(val, list): next_date = val[0]
                            else: next_date = val
                    elif not cal.empty:
                        if 'Earnings Date' in cal: next_date = cal['Earnings Date'].iloc[0]
                        elif 0 in cal: next_date = cal[0].iloc[0]
            except: pass

        # --- CALCULATE BADGE ---
        if next_date:
            if hasattr(next_date, "replace"):
                next_date = next_date.replace(tzinfo=None)
            
            now = datetime.now().replace(tzinfo=None)
            days_diff = (next_date - now).days
            
            # EXTENDED TO 90 DAYS
            if -1 <= days_diff <= 8:
                earnings_msg = f":rotating_light: **Earnings: {days_diff} Days!**"
            elif 8 < days_diff <= 90:
                fmt_date = next_date.strftime("%b %d")
                earnings_msg = f":calendar: **Earn: {fmt_date}**"

        return {
            "reg_price": reg_price,
            "day_delta": day_pct,
            "ext_str": ext_str,
            "volume": volume,
            "rsi": rsi_val,
            "trend": trend_str,
            "earn_str": earnings_msg
        }
    except: return None

def format_volume(num):
    if num >= 1_000_000: return f"{num/1_000_000:.1f}M"
    if num >= 1_000: return f"{num/1_000:.1f}K"
    return str(num)

# --- MACRO TAPE ---
def render_ticker_tape(tickers):
    ticker_items = []
    for tick in tickers:
        p, d = get_live_price(tick)
        color = "#4caf50" if d >= 0 else "#f44336"
        arrow = "▲" if d >= 0 else "▼"
        display_name = SYMBOL_NAMES.get(tick, tick) 
        
        ticker_items.append(f"<span style='margin-right: 40px; font-weight: 900; font-size: 20px; color: white;'>{display_name}: <span style='color: {color};'>${p:,.2f} {arrow} {d:.2f}%</span></span>")
    
    content_str = ' '.join(ticker_items)
    
    ticker_html = f"""
    <style>
    .ticker-wrap {{
        width: 100%;
        overflow: hidden;
        background-color: #0e1117;
        border-bottom: 2px solid #444; 
        white-space: nowrap;
        box-sizing: border-box;
        height: 50px; 
        display: flex;
        align-items: center;
    }}
    .ticker {{
        display: inline-block;
        white-space: nowrap;
        animation: ticker 100s linear infinite; 
    }}
    @keyframes ticker {{
        0% {{ transform: translateX(0); }}
        100% {{ transform: translateX(-100%); }}
    }}
    </style>
    <div class="ticker-wrap">
        <div class="ticker">
            {content_str} {content_str} {content_str} {content_str}
        </div>
    </div>
    """
    st.markdown(ticker_html, unsafe_allow_html=True)

def display_ticker_grid(ticker_list, live_mode=False):
    if alert_active:
        try:
            check_tick = yf.Ticker(alert_ticker)
            curr_price = check_tick.fast_info['last_price']
            if curr_price >= alert_price and not st.session_state.get('alert_triggered', False):
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
                # USING TANK MODE ENGINE
                data = fetch_quant_data_tank(tick)
                if data:
                    rsi_val = data['rsi']
                    if pd.isna(rsi_val): 
                        rsi_disp = "N/A"
                    else:
                        if rsi_val > 70:   rsi_sig = "🔥 Over"
                        elif rsi_val < 30: rsi_sig = "🧊 Under"
                        else:              rsi_sig = "⚪ Neut"
                        rsi_disp = f"{rsi_val:.0f} ({rsi_sig})"
                    
                    vol_str = format_volume(data['volume'])

                    st.metric(
                        label=f"{tick} (Vol: {vol_str})", 
                        value=f"${data['reg_price']:,.2f}", 
                        delta=f"{data['day_delta']:.2f}% (Close)"
                    )
                    st.markdown(data['ext_str'])
                    
                    if data.get('earn_str'):
                        st.markdown(data['earn_str'])
                    
                    st.caption(f"{data['trend']} | RSI: {rsi_disp}")
                    st.divider()
                else:
                    # If Tank Mode fails, show a clean error so we know WHICH one failed
                    st.error(f"⚠️ {tick} Unreachable")

# --- MAIN APP UI ---
st.title("⚡ Penny Pulse")

render_ticker_tape(MACRO_TICKERS)

# --- TABS LAYOUT ---
tab1, tab2 = st.tabs(["🏠 Dashboard", "🚀 My Portfolio"])

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
            data = fetch_quant_data_tank(ticker)
            if data:
                current = data['reg_price'] 
                entry = info['entry']
                total_return = ((current - entry) / entry) * 100
                st.metric(
                    label=f"{ticker} (Since {info['date']})",
                    value=f"${current:,.2f}",
                    delta=f"{total_return:.2f}% (Total)"
                )
                if data['ext_str']: st.markdown(data['ext_str'])
                
                if data.get('earn_str'):
                    st.markdown(data['earn_str'])
                    
                st.caption(f"Entry: ${entry:,.2f}")
                st.divider()
            else:
                st.warning(f"Loading {ticker}...")

st.success("✅ System Ready (v4.0 - Tank Edition)")
