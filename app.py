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

# *** CONFIG ***
WEBHOOK_URL = "" 
LOGO_PATH = "logo.png"
ADMIN_PASSWORD = "admin123"
NEWS_FEEDS = [
    "https://finance.yahoo.com/news/rssindex",
    "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664",
    "http://feeds.marketwatch.com/marketwatch/topstories"
]

# --- 2. STATE INITIALIZATION ---
if 'initialized' not in st.session_state:
    st.session_state['initialized'] = True
    if 'w_input' not in st.session_state: st.session_state['w_input'] = "TD.TO, CCO.TO, IVN.TO, BN.TO, HIVE, SPY"
    if 'a_tick_input' not in st.session_state: st.session_state['a_tick_input'] = "TD.TO"
    if 'a_price_input' not in st.session_state: st.session_state['a_price_input'] = 0.0
    if 'a_on_input' not in st.session_state: st.session_state['a_on_input'] = False
    if 'flip_on_input' not in st.session_state: st.session_state['flip_on_input'] = False
    
    st.session_state.update({
        'news_results': [], 'raw_news_cache': [], 'news_offset': 0,
        'alert_log': [], 'storm_cooldown': {}, 'meta_cache': {}, 'banner_msg': None
    })

# --- AI & NEWS HELPERS ---
def get_relative_time(date_str):
    try:
        dt = email.utils.parsedate_to_datetime(date_str)
        now = datetime.now(dt.tzinfo); diff = now - dt; s = diff.total_seconds()
        if s < 60: return "Just now"
        elif s < 3600: return f"{int(s//60)}m ago"
        elif s < 86400: return f"{int(s//3600)}h ago"
        else: return "Yesterday"
    except: return "Recent"

def process_ai_batch(items_to_process, key):
    try:
        from openai import OpenAI
        cl = OpenAI(api_key=key)
        prompt = "Analyze financial headlines. Return JSON: {'items': [{'ticker': '...', 'sentiment': 'BULL/BEAR/NEUTRAL', 'summary': '...', 'link': '...', 'time': '...'}]}"
        ai_input = "\n".join([f"{x['title']} | {x['time']} | {x['link']}" for x in items_to_process])
        resp = cl.chat.completions.create(model="gpt-4o-mini", messages=[{"role":"system", "content": prompt}, {"role":"user", "content": ai_input}], response_format={"type": "json_object"})
        return json.loads(resp.choices[0].message.content).get('items', [])
    except: return []

# --- STABILITY ARMOR ---
def safe_fetch(ticker_obj, method, timeout=0.8):
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        if method == "history": future = executor.submit(ticker_obj.history, period="1mo", interval="15m")
        elif method == "info": future = executor.submit(lambda: ticker_obj.info)
        elif method == "calendar": future = executor.submit(lambda: ticker_obj.calendar)
        try: return future.result(timeout=timeout)
        except: return None

# --- 3. DATA LOGIC ---
def get_pro_data(s):
    try:
        tk = yf.Ticker(s)
        h = safe_fetch(tk, "history")
        if h is None or h.empty: return None
        p_live, prev_close = h['Close'].iloc[-1], h['Close'].iloc[-2]
        
        now = time.time()
        if s not in st.session_state['meta_cache'] or (now - st.session_state['meta_cache'][s][1] > 3600):
            info = safe_fetch(tk, "info") or {}
            cal = safe_fetch(tk, "calendar")
            earn = "N/A"
            if isinstance(cal, dict) and 'Earnings Date' in cal: earn = f"Last: {cal['Earnings Date'][0].strftime('%b %d')}"
            res = {"rat": (info.get('recommendationKey', 'BUY')).upper().replace('_',' '), "earn": earn, "name": info.get('longName', s.split('.')[0])}
            st.session_state['meta_cache'][s] = (res, now)
        
        meta = st.session_state['meta_cache'][s][0]
        diff = h['Close'].diff(); u, d = diff.clip(lower=0), -1*diff.clip(upper=0)
        rsi = 100 - (100/(1 + (u.rolling(14).mean()/d.rolling(14).mean()).iloc[-1]))
        trend = "BULL" if (h['Close'].ewm(span=12).mean() - h['Close'].ewm(span=26).mean()).iloc[-1] > 0 else "BEAR"
        vol = h['Volume'].iloc[-1] / h['Volume'].mean() if h['Volume'].mean() > 0 else 1.0
        chart = h['Close'].tail(50).reset_index(); chart.columns = ['T', 'Stock']; chart['Idx'] = range(len(chart))
        chart['Stock'] = ((chart['Stock'] - chart['Stock'].iloc[0]) / chart['Stock'].iloc[0]) * 100

        return {"p": p_live, "d": ((p_live - prev_close)/prev_close)*100, "rsi": rsi, "tr": trend, "vol": vol, "chart": chart, "rat": meta['rat'], "earn": meta['earn'], "h": h['High'].tail(26).max(), "l": h['Low'].tail(26).min(), "name": meta['name']}
    except: return None

# --- 4. SIDEBAR ---
if "OPENAI_KEY" in st.secrets: KEY = st.secrets["OPENAI_KEY"]
else: KEY = st.sidebar.text_input("OpenAI Key", type="password")

with st.sidebar:
    st.header("⚡ Penny Pulse")
    st.text_input("Tickers", key="w_input")
    st.divider()
    st.subheader("🔔 Smart Alerts")
    PORT = {"HIVE": {"e": 3.19, "q": 50}, "BAER": {"e": 1.86, "q": 100}, "TX": {"e": 38.10, "q": 40}, "IMNN": {"e": 3.22, "q": 100}, "RERE": {"e": 5.31, "q": 100}}
    ALL_T = list(set([x.strip().upper() for x in st.session_state.w_input.split(",") if x.strip()] + list(PORT.keys())))
    st.selectbox("Price Target Asset", sorted(ALL_T), key="a_tick_input")
    st.number_input("Target ($)", key="a_price_input")
    st.toggle("Active Price Alert", key="a_on_input")
    st.toggle("Alert on Trend Flip", key="flip_on_input")

# --- 5. SCROLLER ---
idx_items = []
for sym, name in [("^GSPC", "S&P 500"), ("^IXIC", "Nasdaq"), ("BTC-USD", "Bitcoin")]:
    d = get_pro_data(sym)
    if d and not pd.isna(d['p']):
        col = "#4caf50" if d['d']>=0 else "#ff4b4b"
        idx_items.append(f"{name}: <span style='color:{col}'>${d['p']:,.2f} ({d['d']:+.2f}%)</span>")
st.markdown(f"""<div style="background:#0E1117;padding:10px;border-bottom:1px solid #333;margin-bottom:15px;"><marquee style="font-weight:bold;font-size:18px;color:#EEE;">{" &nbsp;&nbsp;|&nbsp;&nbsp; ".join(idx_items) if idx_items else "Market Data Active"}</marquee></div>""", unsafe_allow_html=True)

# --- 6. TABS ---
t1, t2, t3 = st.tabs(["🏠 Dashboard", "🚀 My Picks", "📰 Market News"])

def draw_card(t, p_data=None):
    d = get_pro_data(t)
    if not d: return
    col = "#4caf50" if d['d']>=0 else "#ff4b4b"
    st.markdown(f"""<div style="display:flex; justify-content:space-between;"><div><div style="font-size:24px; font-weight:900;">{d['name']}</div><div style="font-size:12px; color:#888;">{t}</div></div><div style="text-align:right;"><div style="font-size:22px; font-weight:bold;">${d['p']:,.2f}</div><div style="color:{col}; font-weight:bold;">{d['d']:+.2f}%</div></div></div>""", unsafe_allow_html=True)
    st.markdown(f"**☻ AI:** {'🟢 BULLISH' if d['tr']=='BULL' else '🔴 BEARISH'} BIAS<br>**TREND:** <span style='color:{col};font-weight:bold;'>{d['tr']}</span><br>**ANALYST RATING:** <span style='color:#4caf50;'>{d['rat']}</span><br>**EARNINGS:** <b>{d['earn']}</b>", unsafe_allow_html=True)
    st.altair_chart(alt.Chart(d['chart']).mark_line(color=col).encode(x=alt.X('Idx', axis=None), y=alt.Y('Stock', axis=None)).properties(height=70), use_container_width=True)
    pct = max(0, min(100, ((d['p']-d['l'])/(d['h']-d['l'])*100 if d['h']>d['l'] else 50)))
    st.markdown(f"""<div style="font-size:10px;color:#888;">Day Range</div><div style="width:100%;height:8px;background:linear-gradient(90deg, #ff4b4b, #ffff00, #4caf50);border-radius:4px;position:relative;margin-bottom:10px;"><div style="position:absolute;left:{pct}%;top:-2px;width:3px;height:12px;background:white;border:1px solid #333;"></div></div>""", unsafe_allow_html=True)
    st.markdown(f"""<div style="font-size:10px;color:#888;">Volume ({d['vol']:.1f}x)</div><div style="width:100%;height:6px;background:#333;border-radius:3px;margin-bottom:8px;"><div style="width:{min(100, d['vol']*50)}%;height:100%;background:#2196F3;"></div></div><div style="font-size:10px;color:#888;">RSI ({d['rsi']:.0f})</div><div style="width:100%;height:6px;background:#333;border-radius:3px;margin-bottom:15px;"><div style="width:{d['rsi']}%;height:100%;background:{'#ff4b4b' if d['rsi']>70 else '#4caf50'};"></div></div>""", unsafe_allow_html=True)
    st.divider()

with t1:
    cols = st.columns(3)
    W_list = [x.strip().upper() for x in st.session_state.w_input.split(",") if x.strip()]
    for i, t in enumerate(W_list):
        with cols[i%3]: draw_card(t)

with t2:
    data_list = [get_pro_data(tk) for tk in PORT.keys()]
    tv = sum(d['p']*inf['q'] for d, (tk, inf) in zip(data_list, PORT.items()) if d)
    tc = sum(inf['e']*inf['q'] for inf in PORT.values())
    profit = tv - tc
    st.markdown(f"""<div style="background:#111; border-radius:10px; padding:15px; text-align:center; border:1px solid #333; margin-bottom:10px;"><div style="color:#888; font-size:12px;">NET LIQUIDITY</div><div style="font-size:28px; font-weight:bold; color:white;">${tv:,.2f}</div></div><div style="background:#111; border-radius:10px; padding:15px; text-align:center; border:1px solid #333; margin-bottom:10px;"><div style="color:#888; font-size:12px;">DAY PROFIT</div><div style="font-size:28px; font-weight:bold; color:#4caf50;">${tv*0.012:,.2f}</div></div><div style="background:#111; border-radius:10px; padding:15px; text-align:center; border:1px solid #333;"><div style="color:#888; font-size:12px;">TOTAL RETURN</div><div style="font-size:28px; font-weight:bold; color:#4caf50;">${profit:+,.2f} ({(profit/tc*100):+.1f}%)</div></div>""", unsafe_allow_html=True)
    cols = st.columns(3)
    for i, (t, inf) in enumerate(PORT.items()):
        with cols[i%3]: draw_card(t, inf)

with t3:
    if st.button("Analyze Market Context (Start)"):
        if KEY:
            raw_items = []
            for f in NEWS_FEEDS:
                try:
                    r = requests.get(f, timeout=5); root = ET.fromstring(r.content)
                    for item in root.findall('.//item')[:10]:
                        raw_items.append({"title": item.find('title').text, "link": item.find('link').text, "time": "Recent"})
                except: continue
            if raw_items:
                analyzed = process_ai_batch(raw_items[:15], KEY)
                for n in analyzed:
                    s_color = "#4caf50" if n.get('sentiment')=="BULL" else "#ff4b4b"
                    st.markdown(f"<div style='border-left:4px solid {s_color}; padding-left:10px; margin-bottom:15px;'><b>{n.get('ticker')}</b>: {n.get('summary')} <a href='{n.get('link')}'>Read</a></div>", unsafe_allow_html=True)
        else: st.error("No API Key")

time.sleep(60); st.rerun()
