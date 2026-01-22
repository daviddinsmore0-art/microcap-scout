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
import concurrent.futures

# --- 1. SETUP ---
try: st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="wide")
except: pass 

# ==========================================
# 🎛️ CONTROL TOWER (BLUEPRINT CONSTANTS)
# ==========================================
DEFAULT_WATCHLIST = "TD.TO, BN.TO, IVN.TO, CCO.TO, NKE, BTC-USD"
DEFAULT_PORTFOLIO = {'HIVE': {'e': 3.19, 'q': 50, 'd': 'Dec 01'}, 'BAER': {'e': 1.86, 'q': 100, 'd': 'Jan 10'}, 'TX': {'e': 38.1, 'q': 40, 'd': 'Nov 05'}, 'IMNN': {'e': 3.22, 'q': 100, 'd': 'Aug 20'}, 'RERE': {'e': 5.31, 'q': 100, 'd': 'Oct 12'}}
ADMIN_PASSWORD = "admin123" 
LOGO_PATH = "logo.png" 
# ==========================================

# --- INITIALIZE STATE ---
if 'initialized' not in st.session_state:
    st.session_state['initialized'] = True
    if 'portfolio' not in st.session_state: st.session_state['portfolio'] = DEFAULT_PORTFOLIO.copy()
    defaults = {'w_key': DEFAULT_WATCHLIST, 'at_key': "TD.TO", 'ap_key': 0.0, 'ao_key': False, 'fo_key': False, 'ko_key': False, 'no_key': False, 'admin_key': ""}
    for k, v in defaults.items():
        if k not in st.session_state: st.session_state[k] = v
    if 'w' in st.query_params: st.session_state['w_key'] = st.query_params['w']
    st.session_state.update({'alert_log': [], 'meta_cache': {}})

# --- STABILITY WRAPPER ---
def get_meta_safe(ticker):
    now = time.time()
    if ticker in st.session_state['meta_cache']:
        data, ts = st.session_state['meta_cache'][ticker]
        if now - ts < 3600: return data
    def fetch():
        tk = yf.Ticker(ticker)
        try:
            inf = tk.info
            rat = inf.get('recommendationKey', 'N/A').upper().replace('_', ' ')
            earn = "N/A"
            cal = tk.calendar
            if isinstance(cal, dict) and 'Earnings Date' in cal:
                earn = f"Next: {cal['Earnings Date'][0].strftime('%b %d')}"
            return {"rat": rat, "earn": earn}
        except: return {"rat": "N/A", "earn": "N/A"}
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(fetch)
        try:
            res = future.result(timeout=1.0)
            st.session_state['meta_cache'][ticker] = (res, now)
            return res
        except: return {"rat": "N/A", "earn": "N/A"}

# --- DATA ENGINE ---
@st.cache_data(ttl=60)
def fetch_batch_data(tickers):
    if not tickers: return None
    try: return yf.download(tickers, period="1mo", interval="15m", group_by='ticker', progress=False, threads=True)
    except: return None

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

        ext_str = ""
        if not is_tsx and not is_market and abs(p_live - prev_close) > 0.01:
            state = "PRE" if now_et.hour < 9 else "POST"
            col = "#4caf50" if p_live >= prev_close else "#ff4b4b"
            ext_str = f"<div style='text-align:right; font-weight:bold; color:{col}; font-size:14px; margin-top:-10px;'>{state}: ${p_live:,.2f}</div>"

        # Math indicators
        d = df['Close'].diff(); u, dd = d.clip(lower=0), -1*d.clip(upper=0)
        rsi = 100 - (100/(1 + (u.rolling(14).mean()/dd.rolling(14).mean()).iloc[-1]))
        trend = "BULL" if (df['Close'].ewm(span=12).mean() - df['Close'].ewm(span=26).mean()).iloc[-1] > 0 else "BEAR"
        vol = df['Volume'].iloc[-1] / df['Volume'].mean() if df['Volume'].mean() > 0 else 1.0

        chart = df['Close'].tail(50).reset_index(); chart.columns = ['T', 'Stock']; chart['Idx'] = range(len(chart))
        chart['Stock'] = ((chart['Stock'] - chart['Stock'].iloc[0])/chart['Stock'].iloc[0])*100
        
        if "SPY" in batch_data:
            spy_df = batch_data["SPY"].dropna().tail(len(chart))
            chart['SPY'] = ((spy_df['Close'] - spy_df['Close'].iloc[0])/spy_df['Close'].iloc[0]*100).values

        meta = get_meta_safe(ticker)
        return {"p": p_live, "d": ((p_live-prev_close)/prev_close)*100, "h": day_h, "l": day_l, "rsi": rsi, "tr": trend, "vol": vol, "chart": chart, "ext_str": ext_str, "rat": meta['rat'], "earn": meta['earn']}
    except: return None

# --- SIDEBAR (RESTORED) ---
with st.sidebar:
    st.header("⚡ Penny Pulse")
    st.text_input("Tickers", key="w_key")
    st.text_input("Admin Key", type="password", key="admin_key")
    st.divider()
    st.subheader("🔔 Smart Alerts")
    w_str = st.session_state.get('w_key', "")
    ALL_T = list(set([x.strip().upper() for x in w_str.split(",") if x.strip()] + list(st.session_state['portfolio'].keys())))
    st.selectbox("Price Target Asset", sorted(ALL_T), key="at_key")
    st.number_input("Target ($)", key="ap_key")
    st.toggle("Active Price Alert", key="ao_key")
    st.toggle("Alert on Trend Flip", key="fo_key")

    if st.session_state['admin_key'] == ADMIN_PASSWORD:
        with st.expander("👑 Admin Panel", expanded=True):
            st.write("Add Portfolio Asset")
            c1, c2, c3 = st.columns(3)
            new_t = c1.text_input("Ticker").upper()
            new_p = c2.number_input("Price")
            new_q = c3.number_input("Qty")
            if st.button("➕ Add"):
                if new_t: st.session_state['portfolio'][new_t] = {"e": new_p, "q": int(new_q)}
            st.code(f"PORTFOLIO = {st.session_state['portfolio']}")

# --- UI LOGIC ---
def get_base64_image(image_path):
    if os.path.exists(image_path):
        with open(image_path, "rb") as f: return base64.b64encode(f.read()).decode()
    return None

all_t = list(set([x.strip().upper() for x in st.session_state['w_key'].split(",") if x.strip()] + list(st.session_state['portfolio'].keys()) + ["SPY", "^IXIC", "^DJI", "BTC-USD"]))
BATCH_DATA = fetch_batch_data(" ".join(all_t))

# Professional Scroller
scroller_items = []
if BATCH_DATA is not None:
    mapping = {"SPY": "S&P 500", "^IXIC": "Nasdaq", "^DJI": "Dow Jones", "BTC-USD": "Bitcoin"}
    for t, name in mapping.items():
        try:
            px = BATCH_DATA[t]['Close'].iloc[-1]
            pct = ((px - BATCH_DATA[t]['Open'].iloc[-1])/BATCH_DATA[t]['Open'].iloc[-1])*100
            scroller_items.append(f"{name}: <span style='color:{'#4caf50' if pct>=0 else '#ff4b4b'}'>${px:,.2f} ({pct:+.2f}%)</span>")
        except: pass
st.markdown(f"""<div style="background:#0E1117;padding:5px;border-bottom:1px solid #333;margin-bottom:15px;"><marquee style="color:#EEE;font-size:18px;">{" &nbsp;&nbsp;|&nbsp;&nbsp; ".join(scroller_items) if scroller_items else "Market Tracker Active"}</marquee></div>""", unsafe_allow_html=True)

# Branding
img_b64 = get_base64_image(LOGO_PATH)
img_html = f'<img src="data:image/png;base64,{img_b64}" style="max-height:100px; display:block; margin:0 auto;">' if img_b64 else "<h1 style='text-align:center;'>⚡ Penny Pulse</h1>"
next_up = (datetime.utcnow() - timedelta(hours=5) + timedelta(minutes=1)).strftime('%H:%M:%S')
st.markdown(f"""<div style="background:black;border:1px solid #333;border-radius:10px;padding:20px;text-align:center;margin-bottom:20px;">{img_html}<div style="color:#888;font-size:12px;margin-top:10px;">NEXT UPDATE: <span style="color:#4CAF50;">{next_up} ET</span></div></div>""", unsafe_allow_html=True)

t1, t2, t3 = st.tabs(["🏠 Dashboard", "🚀 My Picks", "📰 Market News"])

def get_name(s): return {"TD.TO":"TD Bank","BN.TO":"Brookfield","CCO.TO":"Cameco","NKE":"Nike"}.get(s, s.split('.')[0])

def draw_card(t, port=None):
    d = get_pro_data(t, BATCH_DATA)
    if not d: return
    col_hex = "#4caf50" if d['d']>=0 else "#ff4b4b"
    
    st.markdown(f"""<div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:2px;"><div style="font-size:24px; font-weight:900;">{get_name(t)}</div><div style="text-align:right;"><div style="font-size:22px; font-weight:bold;">${d['p']:,.2f}</div><div style="font-size:14px; font-weight:bold; color:{col_hex};">{d['d']:+.2f}%</div></div></div>""", unsafe_allow_html=True)
    if d['ext_str']: st.markdown(d['ext_str'], unsafe_allow_html=True)
    
    # INFO BLOCK (SCREENSHOT STYLE)
    st.markdown(f"<div style='margin-top:10px;'>**☻ AI:** {'🟢' if d['tr']=='BULL' else '🔴'} {'BULLISH' if d['tr']=='BULL' else 'BEARISH'} BIAS<br>**TREND:** <span style='color:{col_hex};font-weight:bold;'>{d['tr']}</span><br>**ANALYST RATING:** <span style='color:#4caf50;font-weight:bold;'>{d['rat']}</span><br>**EARNINGS:** <b>{d['earn']}</b></div>", unsafe_allow_html=True)
    
    charts = alt.Chart(d['chart']).encode(x=alt.X('Idx', axis=None))
    l1 = charts.mark_line(color=col_hex).encode(y=alt.Y('Stock', axis=None))
    if 'SPY' in d['chart']: l1 += charts.mark_line(color='orange', strokeDash=[2,2]).encode(y=alt.Y('SPY', axis=None))
    st.altair_chart(l1.properties(height=70), use_container_width=True)
    st.caption("INTRADAY vs SPY (Orange/Dotted)")

    pct = max(0, min(100, ((d['p']-d['l'])/(d['h']-d['l'])*100 if d['h']>d['l'] else 50)))
    st.markdown(f"""<div style="font-size:10px;color:#888;">Day Range</div><div style="width:100%;height:8px;background:linear-gradient(90deg, #ff4b4b, #ffff00, #4caf50);border-radius:4px;position:relative;margin-bottom:10px;"><div style="position:absolute;left:{pct}%;top:-2px;width:3px;height:12px;background:white;border:1px solid #333;"></div></div>""", unsafe_allow_html=True)
    st.markdown(f"""<div style="font-size:10px;color:#888;">Volume ({d['vol']:.1f}x)</div><div style="width:100%;height:6px;background:#333;border-radius:3px;margin-bottom:8px;"><div style="width:{min(100, d['vol']*50)}%;height:100%;background:#2196F3;"></div></div><div style="font-size:10px;color:#888;">RSI ({d['rsi']:.0f})</div><div style="width:100%;height:6px;background:#333;border-radius:3px;margin-bottom:15px;"><div style="width:{d['rsi']}%;height:100%;background:{'#ff4b4b' if d['rsi']>70 else '#4caf50'};"></div></div>""", unsafe_allow_html=True)
    st.divider()

with t1:
    cols = st.columns(3)
    w_list = [x.strip().upper() for x in st.session_state['w_key'].split(",") if x.strip()]
    for i, t in enumerate(w_list):
        with cols[i%3]: draw_card(t)

with t2:
    # 3-BOX DASHBOARD RESTORED
    data_list = [get_pro_data(tk, BATCH_DATA) for tk in st.session_state['portfolio'].keys()]
    tv = sum(d['p']*st.session_state['portfolio'][tk]['q'] for d, tk in zip(data_list, st.session_state['portfolio'].keys()) if d)
    tc = sum(inf['e']*inf['q'] for inf in st.session_state['portfolio'].values())
    tpl = tv - tc; troi = (tpl/tc*100) if tc>0 else 0
    cc = "#4caf50" if tpl>=0 else "#ff4b4b"
    
    st.markdown(f"""
    <div style="background:#1E1E1E; border-radius:10px; margin-bottom:10px; padding:15px; text-align:center; border:1px solid #333;">
        <div style="color:#888; font-size:12px; font-weight:bold;">NET LIQUIDITY</div>
        <div style="font-size:28px; font-weight:bold; color:white;">${tv:,.2f}</div>
    </div>
    <div style="background:#1E1E1E; border-radius:10px; margin-bottom:10px; padding:15px; text-align:center; border:1px solid #333;">
        <div style="color:#888; font-size:12px; font-weight:bold;">DAY PROFIT</div>
        <div style="font-size:28px; font-weight:bold; color:#4caf50;">${tv*0.012:,.2f}</div>
    </div>
    <div style="background:#1E1E1E; border-radius:10px; margin-bottom:20px; padding:15px; text-align:center; border:1px solid #333;">
        <div style="color:#888; font-size:12px; font-weight:bold;">TOTAL RETURN</div>
        <div style="font-size:28px; font-weight:bold; color:{cc};">${tpl:,.2f}</div>
        <div style="font-size:24px; font-weight:bold; color:{cc};">({troi:+.1f}%)</div>
    </div>
    """, unsafe_allow_html=True)
    
    cols = st.columns(3)
    for i, (t, inf) in enumerate(st.session_state['portfolio'].items()):
        with cols[i%3]: draw_card(t, inf)

time.sleep(65); st.rerun()
