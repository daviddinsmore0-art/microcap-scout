import streamlit as st, yfinance as yf, requests, time, xml.etree.ElementTree as ET
from datetime import datetime
import streamlit.components.v1 as components
import pandas as pd
import altair as alt 

try: st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="wide")
except: pass 

# --- SESSION STATE ---
if 'news_results' not in st.session_state: st.session_state['news_results'] = []
if 'alert_triggered' not in st.session_state: st.session_state['alert_triggered'] = False
if 'last_trends' not in st.session_state: st.session_state['last_trends'] = {}
if 'mem_ratings' not in st.session_state: st.session_state['mem_ratings'] = {}
if 'mem_meta' not in st.session_state: st.session_state['mem_meta'] = {}

if 'saved_a_tick' not in st.session_state: st.session_state['saved_a_tick'] = "SPY"
if 'saved_a_price' not in st.session_state: st.session_state['saved_a_price'] = 0.0
if 'saved_a_on' not in st.session_state: st.session_state['saved_a_on'] = False
if 'saved_flip_on' not in st.session_state: st.session_state['saved_flip_on'] = False 

# --- PORTFOLIO ---
PORT = {
    "HIVE": {"e": 3.19, "d": "Dec. 01, 2024", "q": 1000},
    "BAER": {"e": 1.86, "d": "Jan. 10, 2025", "q": 500},
    "TX":   {"e": 38.10, "d": "Nov. 05, 2023", "q": 100},
    "IMNN": {"e": 3.22, "d": "Aug. 20, 2024", "q": 200},
    "RERE": {"e": 5.31, "d": "Oct. 12, 2024", "q": 300}
} 

NAMES = {
    "TSLA":"Tesla", "NVDA":"Nvidia", "BTC-USD":"Bitcoin", "AMD":"AMD", 
    "PLTR":"Palantir", "AAPL":"Apple", "SPY":"S&P 500", "^IXIC":"Nasdaq", 
    "^DJI":"Dow Jones", "GC=F":"Gold", "TD.TO":"TD Bank", "IVN.TO":"Ivanhoe", 
    "BN.TO":"Brookfield", "JNJ":"J&J", "^GSPTSE": "TSX"
} 

# --- SIDEBAR ---
st.sidebar.header("⚡ Pulse")
if "OPENAI_KEY" in st.secrets: KEY = st.secrets["OPENAI_KEY"]
else: KEY = st.sidebar.text_input("OpenAI Key (Optional)", type="password") 

# --- PERMANENT WATCHLIST ---
default_list = "SPY, BTC-USD, TD.TO, PLUG.CN, VTX.V, IVN.TO, CCO.TO, BN.TO"

qp = st.query_params
w_str = qp.get("watchlist", default_list)
u_in = st.sidebar.text_input("Add Tickers", value=w_str)
if u_in != w_str: st.query_params["watchlist"] = u_in

WATCH = [x.strip().upper() for x in u_in.split(",") if x.strip()]
ALL = list(set(WATCH + list(PORT.keys())))
st.sidebar.divider()
st.sidebar.subheader("🔔 Smart Alerts") 

# --- PERSISTENT WIDGETS ---
a_tick = st.sidebar.selectbox("Price Target Asset", sorted(ALL), key="saved_a_tick")
a_price = st.sidebar.number_input("Target ($)", step=0.5, key="saved_a_price")
a_on = st.sidebar.toggle("Active Price Alert", key="saved_a_on")
flip_on = st.sidebar.toggle("Alert on Trend Flip", key="saved_flip_on") 

# --- SECTOR & EARNINGS ---
def get_meta_data(s):
    try:
        tk = yf.Ticker(s)
        sec_raw = tk.info.get('sector', 'N/A')
        sec_map = {"Technology":"TECH", "Financial Services":"FIN", "Healthcare":"HLTH", "Consumer Cyclical":"CYCL", "Communication Services":"COMM", "Industrials":"IND", "Energy":"NRGY", "Basic Materials":"MAT", "Real Estate":"RE", "Utilities":"UTIL"}
        sector_code = sec_map.get(sec_raw, sec_raw[:4].upper()) if sec_raw != 'N/A' else ""
        earn_html = ""
        
        cal = tk.calendar
        dates = []
        if isinstance(cal, dict) and 'Earnings Date' in cal: dates = cal['Earnings Date']
        elif hasattr(cal, 'iloc') and not cal.empty: dates = [cal.iloc[0,0]]
        
        if len(dates) > 0:
            nxt = dates[0]
            if hasattr(nxt, "date"): nxt = nxt.date()
            days = (nxt - datetime.now().date()).days
            
            if 0 <= days <= 7: 
                earn_html = f"<span style='background:#550000; color:#ff4b4b; padding:1px 4px; border-radius:4px; font-size:11px; margin-left:5px;'>⚠️ {days}d</span>"
            elif 8 <= days <= 30: 
                earn_html = f"<span style='background:#333; color:#ccc; padding:1px 4px; border-radius:4px; font-size:11px; margin-left:5px;'>📅 {days}d</span>"
            elif days > 30:
                d_str = nxt.strftime("%b %d")
                earn_html = f"<span style='background:#222; color:#888; padding:1px 4px; border-radius:4px; font-size:11px; margin-left:5px;'>📅 {d_str}</span>"
        
        if sector_code or earn_html:
            st.session_state['mem_meta'][s] = (sector_code, earn_html)
        return sector_code, earn_html
        
    except:
        if s in st.session_state['mem_meta']: return st.session_state['mem_meta'][s]
        return "", "" 

# --- ANALYST RATINGS ---
def get_rating_cached(s):
    try:
        info = yf.Ticker(s).info
        rec = info.get('recommendationKey', 'none').replace('_', ' ').upper()
        res = ("N/A", "#888")
        if "STRONG BUY" in rec: res = ("🌟 STRONG BUY", "#00C805")
        elif "BUY" in rec: res = ("✅ BUY", "#4caf50")
        elif "HOLD" in rec: res = ("✋ HOLD", "#FFC107")
        elif "SELL" in rec: res = ("🔻 SELL", "#FF4B4B")
        elif "STRONG SELL" in rec: res = ("🆘 STRONG SELL", "#FF0000")
        if res[0] != "N/A": st.session_state['mem_ratings'][s] = res
        return res
    except:
        if s in st.session_state['mem_ratings']: return st.session_state['mem_ratings'][s]
        return "N/A", "#888"

# --- AI SIGNAL LOGIC ---
def get_ai_signal(rsi, vol_ratio, trend, price_change):
    score = 0
    if rsi >= 80: score -= 3
    elif rsi >= 70: score -= 2
    elif rsi <= 20: score += 3
    elif rsi <= 30: score += 2
    if vol_ratio > 2.0: score += 2 if price_change > 0 else -2
    elif vol_ratio > 1.2: score += 1 if price_change > 0 else -1
    if trend == "BULL": score += 1
    elif trend == "BEAR": score -= 1
    
    if score >= 3: return "🚀 RALLY LIKELY", "#00ff00"
    elif score >= 1: return "🟢 BULLISH BIAS", "#4caf50"
    elif score <= -3: return "⚠️ PULLBACK RISK", "#ff0000"
    elif score <= -1: return "🔴 BEARISH BIAS", "#ff4b4b"
    return "💤 CONSOLIDATION", "#888" 

# --- LIVE PRICE & CHART (DECOUPLED LOGIC) ---
@st.cache_data(ttl=60, show_spinner=False)
def get_data_cached(s):
    if not s or s == "": return None
    s = s.strip().upper()
    
    # 1. Variables for "Official" (Main Metric) Data
    p_reg, pv, dh, dl = 0.0, 0.0, 0.0, 0.0
    
    # 2. Variables for "Extended/Live" (Ext Line) Data
    p_ext = 0.0
    
    tk = yf.Ticker(s)
    is_crypto = s.endswith("-USD")
    valid_data = False
    
    # A. FETCH REGULAR DATA (For Main Metric)
    if not is_crypto:
        try:
            # fast_info usually holds the Regular Market Close during Pre/Post market
            p_reg = tk.fast_info['last_price']
            pv = tk.fast_info['previous_close']
            dh = tk.fast_info['day_high']
            dl = tk.fast_info['day_low']
            if p_reg is not None and pv is not None: 
                valid_data = True
        except: pass
    
    # B. FETCH HISTORY (For Chart + Fallback)
    chart_data = None
    try:
        # We request prepost=True to ensure we catch the LATEST trade for the Ext line
        h = tk.history(period="1d", interval="5m", prepost=True)
        if h.empty: h = tk.history(period="5d", interval="1h", prepost=True)
        
        if not h.empty:
            chart_data = h['Close']
            
            # If fast_info failed (or it's crypto), use history for everything
            if not valid_data or is_crypto:
                p_reg = h['Close'].iloc[-1]
                if is_crypto: pv = h['Open'].iloc[0] 
                else: pv = tk.fast_info['previous_close'] # Try to keep Anchor valid
                
                # Fallback Anchor if fast_info completely dead
                if pd.isna(pv) or pv == 0: pv = h['Close'].iloc[0]
                
                dh = h['High'].max()
                dl = h['Low'].min()
                valid_data = True
            
            # C. CAPTURE EXTENDED PRICE
            # The last bar of 'prepost' history is the true live price
            p_ext = h['Close'].iloc[-1]
    except: pass
    
    if not valid_data or pv == 0: return None
    
    # --- CALCULATIONS ---
    
    # 1. Official Change (Main Metric)
    # Uses p_reg (Official Close) vs pv (Prev Close)
    try:
        d_reg_pct = ((p_reg - pv) / pv) * 100
    except: d_reg_pct = 0.0

    # 2. Extended/Live Change (Ext Line)
    # Uses p_ext (Live/Pre-market) vs pv (Prev Close)
    # If p_ext wasn't found (no history), default to p_reg
    if p_ext == 0: p_ext = p_reg
    
    try:
        d_ext_pct = ((p_ext - pv) / pv) * 100
    except: d_ext_pct = 0.0

    # --- FORMATTING ---
    
    # X_STR uses the EXTENDED data (p_ext, d_ext_pct)
    c_ext = "green" if d_ext_pct >= 0 else "red"
    x_str = f"**Live: ${p_ext:,.2f} (:{c_ext}[{d_ext_pct:+.2f}%])**" if is_crypto else f"**🌙 Ext: ${p_ext:,.2f} (:{c_ext}[{d_ext_pct:+.2f}%])**"
    
    # RANGE BAR
    try:
        rng_pct = max(0, min(1, (p_reg - dl) / (dh - dl))) * 100 if (dh > dl) else 50
    except: rng_pct = 50
    rng_html = f"""<div style="display:flex; align-items:center; font-size:12px; color:#888;
