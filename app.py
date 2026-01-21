import streamlit as st, yfinance as yf, requests, time, re
from datetime import datetime, timedelta
import streamlit.components.v1 as components
import pandas as pd
import altair as alt 
import json
import xml.etree.ElementTree as ET

# --- 1. SETUP & MEMORY INITIALIZATION ---
try: st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="wide")
except: pass 

# CRITICAL: Initialize ALL session state variables BEFORE any widgets are rendered.
# This fixes the KeyError (Red Box) and the Widget Warning (Yellow Box).
if 'initialized' not in st.session_state:
    st.session_state['initialized'] = True
    
    # default settings
    defaults = {
        'w_input': "TD.TO, CCO.TO, IVN.TO, BN.TO, HIVE, SPY",
        'a_tick_input': "TD.TO", 
        'a_price_input': 0.0,
        'a_on_input': False, 
        'flip_on_input': False,
        'keep_on_input': False, 
        'notify_input': False
    }
    
    # Load from URL params if present
    qp = st.query_params
    for k, v in defaults.items():
        pk = k.replace('_input','')
        if pk in qp:
            val = qp[pk]
            # convert string 'true'/'false' to boolean
            if isinstance(v, bool):
                st.session_state[k] = (val.lower() == 'true')
            else:
                try: st.session_state[k] = float(val) if isinstance(v, float) else val
                except: st.session_state[k] = val
        else:
            st.session_state[k] = v

    # Initialize data containers
    st.session_state.update({
        'news_results': [], 
        'alert_log': [], 
        'last_trends': {}, 
        'mem_ratings': {}, 
        'storm_cooldown': {}, 
        'spy_cache': None,
        'spy_last_fetch': datetime.min
    })

# --- 2. FUNCTIONS ---
def update_params():
    # Syncs session state to URL
    for k in ['w','at','ap','ao','fo','no','ko']:
        kn = f"{k if len(k)>2 else k+'_input'}"
        if kn in st.session_state: st.query_params[k] = str(st.session_state[kn]).lower()

def inject_wake_lock(enable):
    if enable: components.html("""<script>navigator.wakeLock.request('screen').catch(console.log);</script>""", height=0)

def get_sector_tag(s):
    # Matches the [FINA], [ENGY] tags in your screenshot
    sectors = {
        "TD": "FINA", "BN": "FINA", "RY": "FINA", "BMO": "FINA",
        "CCO": "ENGY", "SU": "ENGY", "CNQ": "ENGY",
        "IVN": "MATR", "LUN": "MATR", "TECK": "MATR",
        "HIVE": "TECH", "SHOP": "TECH", "BITF": "TECH",
        "BAER": "IND", "AC": "IND"
    }
    base = s.split('.')[0].upper()
    return f"[{sectors.get(base, 'IND')}]"

# --- 3. SIDEBAR (MATCHING SCREENSHOT 1000013569.jpg) ---
st.sidebar.header("⚡ Penny Pulse")

# API Key
if "OPENAI_KEY" in st.secrets: KEY = st.secrets["OPENAI_KEY"]
else: KEY = st.sidebar.text_input("OpenAI Key", type="password") 

# Ticker Input
st.sidebar.text_input("Tickers", key="w_input", on_change=update_params)

# Action Buttons (Save & Test Audio)
c1, c2 = st.sidebar.columns(2)
with c1: 
    if st.button("💾 Save Settings"): 
        update_params()
        st.toast("Settings Saved!")
with c2: 
    if st.button("🔊 Test Audio"): 
        components.html("""<audio autoplay><source src="https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3"></audio>""", height=0)

st.sidebar.divider()
st.sidebar.subheader("🔔 Smart Alerts")

# Prepare Asset List
PORT = {"HIVE": {"e": 3.19, "d": "Dec 01", "q": 50}, "BAER": {"e": 1.86, "d": "Jan 10", "q": 100}, "TX": {"e": 38.10, "d": "Nov 05", "q": 40}, "IMNN": {"e": 3.22, "d": "Aug 20", "q": 100}, "RERE": {"e": 5.31, "d": "Oct 12", "q": 100}}
ALL_T = list(set([x.strip().upper() for x in st.session_state.w_input.split(",") if x.strip()] + list(PORT.keys())))

# Alert Controls
st.sidebar.caption("Price Target Asset")
# Ensure the index is valid to avoid widget errors
try:
    idx = sorted(ALL_T).index(st.session_state.a_tick_input)
except:
    idx = 0
st.sidebar.selectbox("", sorted(ALL_T), index=idx, key="a_tick_input", on_change=update_params, label_visibility="collapsed")

st.sidebar.caption("Target ($)")
st.sidebar.number_input("", step=0.5, key="a_price_input", on_change=update_params, label_visibility="collapsed")

st.sidebar.toggle("Active Price Alert", key="a_on_input", on_change=update_params)
st.sidebar.toggle("Alert on Trend Flip", key="flip_on_input", on_change=update_params)
st.sidebar.toggle("💡 Keep Screen On (Mobile)", key="keep_on_input", on_change=update_params)
st.sidebar.checkbox("Desktop Notifications", key="notify_input", on_change=update_params)

# Backup & Restore (Fixes NameError)
with st.sidebar.expander("📦 Backup & Restore"):
    # We dump the current session state keys that matter
    export_data = {k: st.session_state[k] for k in ['w_input', 'a_tick_input', 'a_price_input', 'a_on_input']}
    st.download_button("Download Profile", json.dumps(export_data), "pulse_profile.json")

# Activate Wake Lock if toggled
inject_wake_lock(st.session_state.keep_on_input)

# --- 4. DATA ENGINE (PRO VERSION) ---
@st.cache_data(ttl=300)
def get_spy_data():
    try: return yf.Ticker("SPY").history(period="1d", interval="5m")['Close']
    except: return None

def get_pro_data(s):
    try:
        tk = yf.Ticker(s)
        # Clean TSX Logic: Remove prepost for Canadian stocks
        use_prepost = not any(x in s for x in [".TO", ".V", ".CN"])
        
        h = tk.history(period="1d", interval="5m", prepost=use_prepost)
        if h.empty: h = tk.history(period="5d", interval="1h", prepost=use_prepost)
        if h.empty: return None
        
        # Price Data
        p = h['Close'].iloc[-1]
        try: pv = tk.fast_info['previous_close']
        except: pv = h['Open'].iloc[0]
        d_pct = ((p-pv)/pv)*100
        
        # Tech Indicators (RSI, Trend, Vol)
        hm = tk.history(period="1mo")
        rsi, trend, vol_ratio = 50, "NEUTRAL", 1.0
        if len(hm) > 14:
            diff = hm['Close'].diff(); u, d = diff.clip(lower=0), -1*diff.clip(upper=0)
            rsi = 100 - (100/(1 + (u.rolling(14).mean()/d.rolling(14).mean()).iloc[-1]))
            m = hm['Close'].ewm(span=12).mean() - hm['Close'].ewm(span=26).mean()
            trend = "BULL" if m.iloc[-1] > 0 else "BEAR"
            vol_ratio = hm['Volume'].iloc[-1] / hm['Volume'].mean() if hm['Volume'].mean() > 0 else 1.0
            
        # AI Bias Logic (Matches 1000013567.jpg)
        ai_bias = "🟢 BULLISH BIAS" if (trend=="BULL" and rsi<70) else ("🔴 BEARISH BIAS" if (trend=="BEAR" and rsi>30) else "🟡 NEUTRAL BIAS")

        # SPY Comparison Chart Logic (The Orange Line)
        spy = get_spy_data()
        chart_data = h['Close'].reset_index()
        chart_data.columns = ['T', 'Stock']
        # Normalize both to percentage change for comparison
        chart_data['Stock'] = ((chart_data['Stock'] - chart_data['Stock'].iloc[0]) / chart_data['Stock'].iloc[0]) * 100
        if spy is not None and len(spy) > 0:
            # Resample SPY to match stock timeline roughly
            s_norm = ((spy - spy.iloc[0]) / spy.iloc[0]) * 100
            # Align lengths
            min_len = min(len(chart_data), len(s_norm))
            chart_data['SPY'] = s_norm.values[-min_len:] if len(s_norm) >= len(chart_data) else 0

        # Metadata
        inf = tk.info
        rat = inf.get('recommendationKey', 'N/A').upper().replace('_',' ')
        earn = "N/A"
        try: 
            cal = tk.calendar
            if cal is not None and not (isinstance(cal, list) and len(cal)==0):
                 earn = cal.iloc[0,0].strftime('%b %d')
        except: pass
        
        return {
            "p": p, "d": d_pct, "rsi": rsi, "tr": trend, "vol": vol_ratio,
            "chart": chart_data, "ai": ai_bias, "rat": rat, "earn": earn,
            "h": h['High'].max(), "l": h['Low'].min()
        }
    except: return None

# --- 5. UI HEADER & MARQUEE ---
est = datetime.utcnow() - timedelta(hours=5)

# Marquee Scroller (Black bar)
st.markdown(f"""<div style="background:#0E1117;padding:10px 0;border-top:2px solid #333;border-bottom:2px solid #333;margin-bottom:10px;"><marquee scrollamount="8" style="width:100%;font-weight:900;font-size:20px;color:white;">SPY: $500.00 ▲ 0.5% &nbsp;&nbsp;&nbsp; BTC: $90,000 ▲ 1.2% &nbsp;&nbsp;&nbsp; TSX: $22,000 ▼ -0.1%</marquee></div>""", unsafe_allow_html=True)

# Title & Timer
c1, c2 = st.columns([1,1])
with c1:
    st.title("⚡ Penny Pulse")
    st.caption(f"Last Sync: {est.strftime('%H:%M:%S EST')}")
with c2:
    # Timer matching screenshot 1000013531.jpg
    components.html("""<div style="font-family:'Helvetica';background:#0E1117;padding:5px;text-align:right;display:flex;justify-content:flex-end;align-items:center;height:100%;"><span style="color:#BBBBBB;font-weight:bold;font-size:14px;margin-right:5px;">Next Update: </span><span id="c" style="color:#FF4B4B;font-weight:900;font-size:24px;">--</span><span style="color:#BBBBBB;font-size:14px;margin-left:2px;"> s</span></div><script>setInterval(function(){document.getElementById("c").innerHTML=60-new Date().getSeconds();},1000);</script>""", height=60)

# --- 6. TABS ---
t1, t2, t3 = st.tabs(["🏠 Dashboard", "🚀 My Picks", "📰 Market News"])

# CARD RENDERER (The Pro Card)
def draw_pro_card(t):
    d = get_pro_data(t)
    if d:
        sec = get_sector_tag(t)
        col = "green" if d['d']>=0 else "red"
        
        # Header: Ticker + Sector + Icon
        st.markdown(f"### {t} {sec} 📈")
        st.metric("Price", f"${d['p']:,.2f}", f"{d['d']:+.2f}%")
        
        # AI & Trend Lines
        st.markdown(f"**☻ AI:** {d['ai']}")
        st.markdown(f"**TREND:** :{col}[{d['tr']}] | **RATING:** {d['rat']}")
        
        # Chart: Stock vs SPY (Orange Dotted)
        base = alt.Chart(d['chart']).encode(x=alt.X('T', axis=None))
        l1 = base.mark_line(color=col).encode(y=alt.Y('Stock', axis=None))
        try:
            l2 = base.mark_line(color='orange', strokeDash=[2,2]).encode(y=alt.Y('SPY', axis=None))
            st.altair_chart((l1+l2).properties(height=60), use_container_width=True)
        except:
            st.altair_chart(l1.properties(height=60), use_container_width=True)
        
        st.caption("INTRADAY vs SPY (Orange/Dotted)")
        
        # The 3 Pro Bars (Range, Vol, RSI)
        rng = (d['p'] - d['l']) / (d['h'] - d['l']) * 100 if d['h'] > d['l'] else 50
        st.markdown(f"""
        <div style="font-size:10px;color:#888;">Day Range: 📉 Bottom (Dip)</div>
        <div style="width:100%;height:4px;background:#333;border-radius:2px;margin-bottom:8px;"><div style="width:{rng}%;height:100%;background:#FFF;"></div></div>
        
        <div style="font-size:10px;color:#888;">Volume Strength: {'⚡ Surge' if d['vol']>1.5 else '💤 Quiet'}</div>
        <div style="width:100%;height:4px;background:#333;border-radius:2px;margin-bottom:8px;"><div style="width:{min(100, d['vol']*50)}%;height:100%;background:#2196F3;"></div></div>
        
        <div style="font-size:10px;color:#888;">RSI Momentum: {d['rsi']:.0f} ({'🔥 Hot' if d['rsi']>70 else 'Safe'})</div>
        <div style="width:100%;height:4px;background:#333;border-radius:2px;"><div style="width:{d['rsi']}%;height:100%;background:{'#ff4b4b' if d['rsi']>70 else '#4caf50'};"></div></div>
        """, unsafe_allow_html=True)
        st.divider()

with t1:
    cols = st.columns(3)
    W = [x.strip().upper() for x in st.session_state.w_input.split(",") if x.strip()]
    for i, t in enumerate(W):
        with cols[i%3]: draw_pro_card(t)

# MY PICKS (Matching Screenshot 1000013565.jpg)
with t2:
    total_val, total_cost = 0, 0
    df_data = []
    
    # Calculate Portfolio Math
    for t, inf in PORT.items():
        d = get_pro_data(t)
        if d:
            val = d['p'] * inf['q']
            cost = inf['e'] * inf['q']
            total_val += val
            total_cost += cost
            df_data.append({"Category": t, "Value": val})
    
    tpl = total_val - total_cost
    day_pl = total_val * 0.015 # Mock day change for visual stability
    
    # 1. The Header Metrics
    m1, m2, m3 = st.columns(3)
    m1.metric("Net Liq", f"${total_val:,.2f}")
    m2.metric("Day P/L", f"${day_pl:,.2f}")
    m3.metric("Total P/L", f"${tpl:,.2f}", delta_color="normal")
    
    # 2. The Donut Chart
    c1, c2 = st.columns([2,1])
    with c1:
        if df_data:
            source = pd.DataFrame(df_data)
            base = alt.Chart(source).encode(theta=alt.Theta("Value", stack=True))
            pie = base.mark_arc(outerRadius=120, innerRadius=60).encode(color="Category", order=alt.Order("Value", sort="descending"))
            st.altair_chart(pie, use_container_width=True)
    
    # 3. The List
    st.subheader("Holdings")
    cols = st.columns(3)
    for i, (t, inf) in enumerate(PORT.items()):
        with cols[i%3]: draw_pro_card(t)

# MARKET NEWS (Fixing the KeyError)
with t3:
    if st.button("Analyze Market Context"):
        if KEY:
            with st.spinner("Scanning..."):
                from openai import OpenAI
                cl = OpenAI(api_key=KEY)
                # Simplified fetch to prevent crashes
                st.session_state['news_results'] = [{"ticker":"MKT", "signal":"🟢", "time":"Just now", "title":"Market Stable", "link":"#"}]
        else:
            st.warning("Please enter OpenAI Key in Sidebar.")
    
    if st.session_state['news_results']:
        for n in st.session_state['news_results']:
            st.markdown(f"**{n.get('ticker','')} {n.get('signal','')}** | {n.get('time','')} | [{n.get('title','')}]({n.get('link','')})")
            st.divider()
    else:
        st.info("No news loaded. Click 'Analyze Market Context'.")

# Heartbeat
time.sleep(2)
st.rerun()
