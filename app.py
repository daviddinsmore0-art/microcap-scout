import streamlit as st, yfinance as yf, requests, time
from datetime import datetime, timedelta
import streamlit.components.v1 as components
import pandas as pd
import altair as alt 
import json
import xml.etree.ElementTree as ET
import email.utils 
import os 
import urllib.parse
import base64

# --- 1. SETUP ---
try: st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="wide")
except: pass 

# ==========================================
# 🎛️ CONTROL TOWER
# ==========================================
DEFAULT_WATCHLIST = "TD.TO, CCO.TO, IVN.TO, BN.TO, HIVE, SPY"
DEFAULT_PORTFOLIO = {'HIVE': {'e': 3.19, 'q': 50, 'd': 'Dec 01'}, 'BAER': {'e': 1.86, 'q': 100, 'd': 'Jan 10'}, 'TX': {'e': 38.1, 'q': 40, 'd': 'Nov 05'}, 'IMNN': {'e': 3.22, 'q': 100, 'd': 'Aug 20'}, 'RERE': {'e': 5.31, 'q': 100, 'd': 'Oct 12'}}
ADMIN_PASSWORD = "admin123" 
WEBHOOK_URL = "" 
LOGO_PATH = "logo.png" 
# ==========================================

# --- INITIALIZE STATE ---
if 'initialized' not in st.session_state:
    st.session_state['initialized'] = True
    if 'portfolio' not in st.session_state: st.session_state['portfolio'] = DEFAULT_PORTFOLIO.copy()
    defaults = {'w_key': DEFAULT_WATCHLIST, 'at_key': "TD.TO", 'ap_key': 0.0, 'ao_key': False, 'fo_key': False, 'ko_key': False, 'no_key': False}
    for k, v in defaults.items():
        if k not in st.session_state: st.session_state[k] = v
    if 'w' in st.query_params: st.session_state['w_key'] = st.query_params['w']
    st.session_state.update({'alert_log': [], 'storm_cooldown': {}, 'banner_msg': None, 'meta_cache': {}})

# --- FUNCTIONS ---
def get_base64_image(image_path):
    if os.path.exists(image_path):
        with open(image_path, "rb") as img_file: return base64.b64encode(img_file.read()).decode()
    return None

def inject_wake_lock(enable):
    if enable: components.html("""<script>navigator.wakeLock.request('screen').catch(console.log);</script>""", height=0)

# --- DATA ENGINE (OPTIMIZED BATCH) ---
@st.cache_data(ttl=60)
def fetch_batch_data(tickers):
    if not tickers: return None
    try: return yf.download(tickers, period="1mo", interval="15m", group_by='ticker', progress=False, threads=True)
    except: return None

def get_meta(ticker):
    # Cache metadata for 1 hour to prevent 1ST crashes
    now = time.time()
    if ticker in st.session_state['meta_cache']:
        data, ts = st.session_state['meta_cache'][ticker]
        if now - ts < 3600: return data
    
    try:
        tk = yf.Ticker(ticker)
        inf = tk.info
        rat = inf.get('recommendationKey', 'BUY').upper().replace('_',' ')
        earn = "N/A"
        cal = tk.calendar
        if isinstance(cal, dict) and 'Earnings Date' in cal:
            earn = f"Next: {cal['Earnings Date'][0].strftime('%b %d')}"
        elif hasattr(cal, 'iloc') and not cal.empty:
            earn = f"Next: {cal.iloc[0, 0].strftime('%b %d')}"
        
        res = {"rat": rat, "earn": earn}
        st.session_state['meta_cache'][ticker] = (res, now)
        return res
    except:
        return {"rat": "BUY", "earn": "N/A"}

def get_pro_data(ticker, batch_data):
    try:
        if isinstance(batch_data.columns, pd.MultiIndex):
            if ticker not in batch_data.columns.levels[0]: return None
            df = batch_data[ticker].dropna()
        else: df = batch_data.dropna()
        if df.empty: return None

        p_live = df['Close'].iloc[-1]
        prev_close = df['Close'].iloc[-2]
        day_h, day_l = df['High'].tail(26).max(), df['Low'].tail(26).min()

        now_et = datetime.utcnow() - timedelta(hours=5) 
        is_market = (now_et.weekday() < 5) and (9 <= now_et.hour < 16) and not (now_et.hour==9 and now_et.minute<30)
        is_tsx = any(x in ticker for x in ['.TO', '.V', '.CN'])

        disp_p, disp_pct = p_live, ((p_live - prev_close)/prev_close)*100
        ext_str = ""
        # Fix: TSX no extended hours
        if not is_tsx and not is_market and abs(p_live - prev_close) > 0.01:
            state = "PRE" if now_et.hour < 9 else "POST"
            col = "#4caf50" if disp_pct >= 0 else "#ff4b4b"
            ext_str = f"<div style='text-align:right; font-weight:bold; color:{col}; font-size:14px;'>{state}: ${p_live:,.2f} ({disp_pct:+.2f}%)</div>"

        rsi, trend, vol = 50, "NEUTRAL", 1.0
        if len(df) > 14:
            d = df['Close'].diff(); u, dd = d.clip(lower=0), -1*d.clip(upper=0)
            rsi = 100 - (100/(1 + (u.rolling(14).mean()/dd.rolling(14).mean()).iloc[-1]))
            trend = "BULL" if (df['Close'].ewm(span=12).mean() - df['Close'].ewm(span=26).mean()).iloc[-1] > 0 else "BEAR"
            vol = df['Volume'].iloc[-1] / df['Volume'].mean() if df['Volume'].mean() > 0 else 1.0

        chart = df['Close'].tail(50).reset_index()
        chart.columns = ['T', 'Stock']; chart['Idx'] = range(len(chart))
        chart['Stock'] = ((chart['Stock'] - chart['Stock'].iloc[0])/chart['Stock'].iloc[0])*100
        
        # SPY comparison logic
        if "SPY" in batch_data.columns.levels[0] if isinstance(batch_data.columns, pd.MultiIndex) else "SPY" in batch_data.columns:
            spy_df = batch_data["SPY"].dropna().tail(len(chart))
            chart['SPY'] = ((spy_df['Close'] - spy_df['Close'].iloc[0])/spy_df['Close'].iloc[0]*100).values

        meta = get_meta(ticker)

        return {"p": disp_p, "d": disp_pct, "h": day_h, "l": day_l, "rsi": rsi, "tr": trend, "vol": vol, "chart": chart, "ext_str": ext_str, "rat": meta['rat'], "earn": meta['earn']}
    except: return None

# --- UI LOGIC ---
st.sidebar.header("⚡ Penny Pulse")
st.sidebar.text_input("Tickers", key="w_key")
if st.sidebar.text_input("Admin Key", type="password", key="admin_key") == ADMIN_PASSWORD:
    with st.sidebar.expander("Admin Panel", expanded=True):
        c1, c2, c3 = st.columns([2,2,2])
        new_t, new_p, new_q = c1.text_input("Ticker").upper(), c2.number_input("Price", 0.0), c3.number_input("Qty", 0)
        if st.button("➕ Add"):
            if new_t and new_q > 0: st.session_state['portfolio'][new_t] = {"e": new_p, "q": new_q}; st.rerun()
        st.code(f"DEFAULT_PORTFOLIO = {json.dumps(st.session_state['portfolio'])}", language="python")

# --- FETCH ---
all_t = list(set([x.strip().upper() for x in st.session_state['w_key'].split(",") if x.strip()] + list(st.session_state['portfolio'].keys()) + ["SPY"]))
BATCH_DATA = fetch_batch_data(" ".join(all_t))

# --- SCROLLER ---
scroller_items = []
if BATCH_DATA is not None:
    for t in ["SPY", "^IXIC", "BTC-USD"]:
        try:
            tk = t if t != "^IXIC" else "Nasdaq"
            px = BATCH_DATA[t]['Close'].iloc[-1]
            pct = ((px - BATCH_DATA[t]['Open'].iloc[-1])/BATCH_DATA[t]['Open'].iloc[-1])*100
            col = "#4caf50" if pct >= 0 else "#ff4b4b"
            scroller_items.append(f"{tk}: <span style='color:{col}'>${px:,.2f} ({pct:+.2f}%)</span>")
        except: pass
marquee_text = " &nbsp;&nbsp;|&nbsp;&nbsp; ".join(scroller_items) if scroller_items else "Penny Pulse Market Tracker Active"
st.markdown(f"""<div style="background:#0E1117;padding:5px;border-bottom:1px solid #333;margin-bottom:15px;"><marquee style="color:#EEE;font-size:18px;">{marquee_text}</marquee></div>""", unsafe_allow_html=True)

# --- HEADER ---
img_html = f'<img src="data:image/png;base64,{get_base64_image(LOGO_PATH)}" style="max-height:100px; display:block; margin:0 auto;">' if get_base64_image(LOGO_PATH) else "<h1 style='text-align:center;'>⚡ Penny Pulse</h1>"
next_up = (datetime.utcnow() - timedelta(hours=5) + timedelta(minutes=1)).strftime('%H:%M:%S')
st.markdown(f"""<div style="background:black;border:1px solid #333;border-radius:10px;padding:20px;text-align:center;margin-bottom:20px;">{img_html}<div style="color:#888;font-size:12px;margin-top:10px;">NEXT UPDATE: <span style="color:#4CAF50;">{next_up} ET</span></div></div>""", unsafe_allow_html=True)

t1, t2, t3 = st.tabs(["🏠 Dashboard", "🚀 My Picks", "📰 Market News"])

def draw_card(t, port=None):
    d = get_pro_data(t, BATCH_DATA)
    if not d: return
    col_hex = "#4caf50" if d['d']>=0 else "#ff4b4b"
    st.markdown(f"""<div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:2px;"><div style="font-size:24px; font-weight:900;">{get_name(t)}</div><div style="text-align:right;"><div style="font-size:22px; font-weight:bold;">${d['p']:,.2f}</div><div style="font-size:14px; font-weight:bold; color:{col_hex};">{d['d']:+.2f}%</div>{d['ext_str']}</div></div>""", unsafe_allow_html=True)
    
    # INFO BLOCK (DNA RESTORED)
    ai_col = "🟢" if d['tr'] == 'BULL' else "🔴"
    st.markdown(f"**☻ AI:** {ai_col} {'BULLISH' if d['tr']=='BULL' else 'BEARISH'} BIAS<br>**TREND:** <span style='color:{col_hex};font-weight:bold;'>{d['tr']}</span><br>**ANALYST RATING:** <span style='color:#4caf50;font-weight:bold;'>{d['rat']}</span><br>**EARNINGS:** <b>{d['earn']}</b>", unsafe_allow_html=True)
    
    # CHART
    base = alt.Chart(d['chart']).encode(x=alt.X('Idx', axis=None))
    l1 = base.mark_line(color=col_hex).encode(y=alt.Y('Stock', axis=None))
    charts = l1
    if 'SPY' in d['chart']:
        l2 = base.mark_line(color='orange', strokeDash=[2,2]).encode(y=alt.Y('SPY', axis=None))
        charts = l1 + l2
    st.altair_chart(charts.properties(height=60), use_container_width=True)
    st.caption("INTRADAY vs SPY (Orange/Dotted)")

    # BARS
    pct = max(0, min(100, ((d['p'] - d['l']) / (d['h'] - d['l']) * 100 if d['h'] > d['l'] else 50)))
    st.markdown(f"""<div style="font-size:10px;color:#888;">Day Range</div><div style="width:100%;height:8px;background:linear-gradient(90deg, #ff4b4b, #ffff00, #4caf50);border-radius:4px;position:relative;margin-bottom:10px;"><div style="position:absolute;left:{pct}%;top:-2px;width:3px;height:12px;background:white;border:1px solid #333;"></div></div>""", unsafe_allow_html=True)
    st.markdown(f"""<div style="font-size:10px;color:#888;">Volume ({d['vol']:.1f}x)</div><div style="width:100%;height:6px;background:#333;border-radius:3px;margin-bottom:8px;"><div style="width:{min(100, d['vol']*50)}%;height:100%;background:#2196F3;"></div></div><div style="font-size:10px;color:#888;">RSI ({d['rsi']:.0f})</div><div style="width:100%;height:6px;background:#333;border-radius:3px;margin-bottom:15px;"><div style="width:{d['rsi']}%;height:100%;background:{'#ff4b4b' if d['rsi']>70 else '#4caf50'};"></div></div>""", unsafe_allow_html=True)
    st.divider()

with t1:
    cols = st.columns(3)
    w_list = [x.strip().upper() for x in st.session_state['w_key'].split(",") if x.strip()]
    for i, t in enumerate(w_list):
        with cols[i%3]: draw_card(t)

with t2:
    # SLEEK DASHBOARD RESTORED
    data_list = [get_pro_data(t, BATCH_DATA) for t in st.session_state['portfolio'].keys()]
    tv = sum(d['p']*st.session_state['portfolio'][t]['q'] for d, t in zip(data_list, st.session_state['portfolio'].keys()) if d)
    tc = sum(inf['e']*inf['q'] for inf in st.session_state['portfolio'].values())
    tpl = tv - tc; troi = (tpl/tc*100) if tc>0 else 0
    cc = "#4caf50" if tpl>=0 else "#ff4b4b"
    
    st.markdown(f"""
    <div style="background:#1E1E1E;border:1px solid #333;border-radius:10px;padding:20px;text-align:center;margin-bottom:20px;">
        <div style="color:#888;font-size:12px;font-weight:bold;">NET LIQUIDITY</div>
        <div style="font-size:32px;font-weight:bold;color:white;margin-bottom:5px;">${tv:,.2f}</div>
        <div style="color:{cc};font-size:18px;font-weight:bold;">${tpl:,.2f} ({troi:+.1f}%)</div>
    </div>
    """, unsafe_allow_html=True)
    
    cols = st.columns(3)
    for i, (t, inf) in enumerate(st.session_state['portfolio'].items()):
        with cols[i%3]: draw_card(t, inf)

time.sleep(65); st.rerun()
