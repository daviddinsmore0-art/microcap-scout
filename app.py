import streamlit as st, yfinance as yf, requests, time
from datetime import datetime, timedelta
import streamlit.components.v1 as components
import pandas as pd
import altair as alt 
import json
import xml.etree.ElementTree as ET
import email.utils 
import os
import base64
import concurrent.futures

# --- 1. SETUP ---
try: st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="wide")
except: pass 

# *** PASTE YOUR DISCORD WEBHOOK URL HERE ***
WEBHOOK_URL = "" 
LOGO_PATH = "logo.png"
# ******************************************* if 'initialized' not in st.session_state:
    st.session_state['initialized'] = True
    # FIXED: Initialize session state keys BEFORE widgets to stop the Yellow Error Box
    if 'w_input' not in st.session_state: st.session_state['w_input'] = "TD.TO, BN.TO, IVN.TO, CCO.TO, NKE, BTC-USD"
    if 'a_tick_input' not in st.session_state: st.session_state['a_tick_input'] = "TD.TO"
    if 'a_price_input' not in st.session_state: st.session_state['a_price_input'] = 0.0
    if 'a_on_input' not in st.session_state: st.session_state['a_on_input'] = False
    if 'flip_on_input' not in st.session_state: st.session_state['flip_on_input'] = False
    if 'keep_on_input' not in st.session_state: st.session_state['keep_on_input'] = False
    if 'notify_input' not in st.session_state: st.session_state['notify_input'] = False
    
    st.session_state.update({
        'news_results': [], 'raw_news_cache': [], 'news_offset': 0,
        'alert_log': [], 'storm_cooldown': {}, 'spy_cache': None, 
        'spy_last_fetch': datetime.min, 'banner_msg': None, 'meta_cache': {}
    })

# --- STABILITY ARMOR: PREVENT "1ST" CRASH ---
def safe_fetch_data(ticker_obj, method_name, timeout=0.8):
    """Executes a yfinance call with a hard timeout to prevent server kill."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        if method_name == "history":
            future = executor.submit(ticker_obj.history, period="1mo", interval="15m")
        elif method_name == "info":
            future = executor.submit(lambda: ticker_obj.info)
        elif method_name == "calendar":
            future = executor.submit(lambda: ticker_obj.calendar)
        
        try: return future.result(timeout=timeout)
        except: return None

# --- 2. FUNCTIONS ---
def update_params():
    for k in ['w','at','ap','ao','fo','no','ko']:
        kn = f"{k if len(k)>2 else k+'_input'}"
        if kn in st.session_state: st.query_params[k] = str(st.session_state[kn]).lower() 

def inject_wake_lock(enable):
    if enable: components.html("""<script>navigator.wakeLock.request('screen').catch(console.log);</script>""", height=0) 

def log_alert(msg, sound=True):
    if msg not in st.session_state.alert_log:
        st.session_state.alert_log.insert(0, f"{datetime.now().strftime('%H:%M')} - {msg}")
        if sound: components.html("""<audio autoplay><source src="https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3"></audio>""", height=0)
        st.session_state['banner_msg'] = msg

def get_pro_data(s):
    try:
        tk = yf.Ticker(s)
        h = safe_fetch_data(tk, "history")
        if h is None or h.empty: return None
        
        p_live = h['Close'].iloc[-1]
        prev_close = h['Close'].iloc[-2] if len(h) > 1 else p_live
        
        # Meta Data (Info/Calendar) with Shield
        now = time.time()
        if s not in st.session_state['meta_cache'] or (now - st.session_state['meta_cache'][s][1] > 3600):
            info = safe_fetch_data(tk, "info") or {}
            cal = safe_fetch_data(tk, "calendar")
            earn = "N/A"
            if isinstance(cal, dict) and 'Earnings Date' in cal:
                earn = f"Next: {cal['Earnings Date'][0].strftime('%b %d')}"
            res = {"rat": (info.get('recommendationKey', 'N/A')).upper(), "earn": earn, "name": info.get('longName', s)}
            st.session_state['meta_cache'][s] = (res, now)
        
        meta = st.session_state['meta_cache'][s][0]
        
        # Indicators
        diff = h['Close'].diff(); u, d = diff.clip(lower=0), -1*diff.clip(upper=0)
        rsi = 100 - (100/(1 + (u.rolling(14).mean()/d.rolling(14).mean()).iloc[-1]))
        trend = "BULL" if (h['Close'].ewm(span=12).mean() - h['Close'].ewm(span=26).mean()).iloc[-1] > 0 else "BEAR"
        vol_ratio = h['Volume'].iloc[-1] / h['Volume'].mean() if h['Volume'].mean() > 0 else 1.0

        chart_data = h['Close'].tail(50).reset_index()
        chart_data.columns = ['T', 'Stock']; chart_data['Idx'] = range(len(chart_data))
        chart_data['Stock'] = ((chart_data['Stock'] - chart_data['Stock'].iloc[0]) / chart_data['Stock'].iloc[0]) * 100

        return {
            "p": p_live, "d": ((p_live - prev_close)/prev_close)*100, "rsi": rsi, "tr": trend, 
            "vol": vol_ratio, "chart": chart_data, "rat": meta['rat'], "earn": meta['earn'],
            "h": h['High'].tail(26).max(), "l": h['Low'].tail(26).min(), "name": meta['name']
        }
    except: return None

# --- 3. SIDEBAR ---
with st.sidebar:
    st.header("⚡ Penny Pulse")
    st.text_input("Tickers", key="w_input", on_change=update_params)
    c1, c2 = st.columns(2)
    with c1: 
        if st.button("💾 Save"): update_params(); st.toast("Saved!")
    with c2: 
        if st.button("🔊 Test"): log_alert("Test Signal Active", sound=True)

    st.divider()
    st.subheader("🔔 Smart Alerts")
    PORT = {"HIVE": {"e": 3.19, "q": 50}, "BAER": {"e": 1.86, "q": 100}, "TX": {"e": 38.10, "q": 40}, "IMNN": {"e": 3.22, "q": 100}, "RERE": {"e": 5.31, "q": 100}}
    ALL_T = list(set([x.strip().upper() for x in st.session_state.w_input.split(",") if x.strip()] + list(PORT.keys())))
    st.selectbox("Price Target Asset", sorted(ALL_T), key="a_tick_input", on_change=update_params)
    st.number_input("Target ($)", key="a_price_input", on_change=update_params)
    st.toggle("Active Price Alert", key="a_on_input", on_change=update_params)
    st.toggle("Alert on Trend Flip", key="flip_on_input", on_change=update_params)

# --- 4. SCROLLER (FIXED NaN) ---
indices = [("^GSPC", "S&P 500"), ("^IXIC", "Nasdaq"), ("BTC-USD", "Bitcoin")]
idx_items = []
for sym, name in indices:
    d = get_pro_data(sym)
    if d and not pd.isna(d['p']):
        col = "#4caf50" if d['d']>=0 else "#ff4b4b"
        idx_items.append(f"{name}: <span style='color:{col}'>${d['p']:,.2f} ({d['d']:+.2f}%)</span>")
scroller_html = " &nbsp;&nbsp;|&nbsp;&nbsp; ".join(idx_items) if idx_items else "Market Tracker Active"
st.markdown(f"""<div style="background:#0E1117;padding:10px 0;border-bottom:1px solid #333;margin-bottom:15px;"><marquee style="font-weight:bold;font-size:18px;color:#EEE;">{scroller_html}</marquee></div>""", unsafe_allow_html=True)

# --- 5. HEADER ---
def get_b64(path):
    if os.path.exists(path):
        with open(path, "rb") as f: return base64.b64encode(f.read()).decode()
    return None
img_b64 = get_b64(LOGO_PATH)
img_html = f'<img src="data:image/png;base64,{img_b64}" style="max-height:100px; display:block; margin:0 auto;">' if img_b64 else "<h1 style='text-align:center;'>⚡ Penny Pulse</h1>"
st.markdown(f"""<div style="background:black;border:1px solid #333;border-radius:10px;padding:20px;text-align:center;margin-bottom:20px;">{img_html}<div style="color:#888;font-size:12px;margin-top:10px;">REFRESHING IN: <span id='count'>60</span>s</div></div><script>var c=60;setInterval(function(){{c--;if(c<0)c=60;document.getElementById('count').innerHTML=c;}},1000);</script>""", unsafe_allow_html=True)

t1, t2, t3 = st.tabs(["🏠 Dashboard", "🚀 My Picks", "📰 Market News"])

def draw_card(t, p_data=None):
    d = get_pro_data(t)
    if not d: return
    col = "#4caf50" if d['d']>=0 else "#ff4b4b"
    st.markdown(f"""<div style="display:flex; justify-content:space-between;"><div><div style="font-size:24px; font-weight:900;">{d['name']}</div><div style="font-size:12px; color:#888;">{t}</div></div><div style="text-align:right;"><div style="font-size:22px; font-weight:bold;">${d['p']:,.2f}</div><div style="color:{col}; font-weight:bold;">{d['d']:+.2f}%</div></div></div>""", unsafe_allow_html=True)
    
    if p_data:
        gain = (d['p'] - p_data['e']) * p_data['q']
        st.markdown(f"<div style='background:black; padding:5px; border-left:4px solid {col}; margin:5px 0;'>Qty: {p_data['q']} | Avg: ${p_data['e']} | Gain: <span style='color:{col}'>${gain:,.2f}</span></div>", unsafe_allow_html=True)

    st.markdown(f"**☻ AI:** {'🟢 BULLISH' if d['tr']=='BULL' else '🔴 BEARISH'} BIAS<br>**TREND:** <span style='color:{col};font-weight:bold;'>{d['tr']}</span><br>**RATING:** <span style='color:#4caf50;'>{d['rat']}</span><br>**EARNINGS:** <b>{d['earn']}</b>", unsafe_allow_html=True)
    
    chart = alt.Chart(d['chart']).mark_line(color=col).encode(x=alt.X('Idx', axis=None), y=alt.Y('Stock', axis=None)).properties(height=70)
    st.altair_chart(chart, use_container_width=True)
    
    pct = max(0, min(100, ((d['p']-d['l'])/(d['h']-d['l'])*100 if d['h']>d['l'] else 50)))
    st.markdown(f"""<div style="font-size:10px;color:#888;">Day Range</div><div style="width:100%;height:8px;background:linear-gradient(90deg, #ff4b4b, #ffff00, #4caf50);border-radius:4px;position:relative;margin-bottom:10px;"><div style="position:absolute;left:{pct}%;top:-2px;width:3px;height:12px;background:white;border:1px solid #333;"></div></div>""", unsafe_allow_html=True)
    st.markdown(f"""<div style="font-size:10px;color:#888;">Volume ({d['vol']:.1f}x)</div><div style="width:100%;height:6px;background:#333;border-radius:3px;margin-bottom:8px;"><div style="width:{min(100, d['vol']*50)}%;height:100%;background:#2196F3;"></div></div><div style="font-size:10px;color:#888;">RSI ({d['rsi']:.0f})</div><div style="width:100%;height:6px;background:#333;border-radius:3px;margin-bottom:15px;"><div style="width:{d['rsi']}%;height:100%;background:{'#ff4b4b' if d['rsi']>70 else '#4caf50'};"></div></div>""", unsafe_allow_html=True)
    st.divider()

with t1:
    cols = st.columns(3)
    W = [x.strip().upper() for x in st.session_state.w_input.split(",") if x.strip()]
    for i, t in enumerate(W):
        with cols[i%3]: draw_card(t)

with t2:
    total_val = sum(get_pro_data(tk)['p']*inf['q'] for tk, inf in PORT.items() if get_pro_data(tk))
    total_cost = sum(inf['e']*inf['q'] for inf in PORT.values())
    profit = total_val - total_cost
    st.markdown(f"""<div style="background:#1E1E1E; border-radius:10px; padding:20px; text-align:center; border:1px solid #333;"><div style="color:#888; font-size:12px;">NET LIQUIDITY</div><div style="font-size:32px; font-weight:bold; color:white;">${total_val:,.2f}</div><div style="color:#4caf50; font-size:20px;">${profit:+,.2f} ({(profit/total_cost*100):+.1f}%)</div></div>""", unsafe_allow_html=True)
    cols = st.columns(3)
    for i, (t, inf) in enumerate(PORT.items()):
        with cols[i%3]: draw_card(t, inf)

with t3:
    if st.button("Analyze News Feed"):
        st.info("Market Context Engine Initializing...")

time.sleep(60); st.rerun()
