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
NEWS_FEEDS = ["https://finance.yahoo.com/news/rssindex", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664", "http://feeds.marketwatch.com/marketwatch/topstories"]
# ==========================================

# --- INITIALIZE STATE ---
if 'initialized' not in st.session_state:
    st.session_state['initialized'] = True
    if 'portfolio' not in st.session_state: st.session_state['portfolio'] = DEFAULT_PORTFOLIO.copy()
    defaults = {'w_key': DEFAULT_WATCHLIST, 'at_key': "TD.TO", 'ap_key': 0.0, 'ao_key': False, 'fo_key': False, 'ko_key': False, 'no_key': False}
    for k, v in defaults.items():
        if k not in st.session_state: st.session_state[k] = v
    if 'w' in st.query_params: st.session_state['w_key'] = st.query_params['w']
    st.session_state.update({'alert_log': [], 'storm_cooldown': {}, 'banner_msg': None})

# --- FUNCTIONS ---
def get_base64_image(image_path):
    if os.path.exists(image_path):
        with open(image_path, "rb") as img_file: return base64.b64encode(img_file.read()).decode()
    return None

def inject_wake_lock(enable):
    if enable: components.html("""<script>navigator.wakeLock.request('screen').catch(console.log);</script>""", height=0)

def log_alert(msg, sound=True):
    if msg not in st.session_state.alert_log:
        st.session_state.alert_log.insert(0, f"{datetime.now().strftime('%H:%M')} - {msg}")
        if sound: components.html("""<audio autoplay><source src="https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3"></audio>""", height=0)
        st.session_state['banner_msg'] = msg

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

NAMES = {"TD.TO":"TD Bank","BN.TO":"Brookfield","CCO.TO":"Cameco","IVN.TO":"Ivanhoe","HIVE":"Hive Digital","SPY":"S&P 500","NKE":"Nike"}
def get_name(s): return NAMES.get(s, s.split('.')[0])

def get_sector_tag(s):
    sectors = {"TD":"FINA","BN":"FINA","CCO":"ENGY","IVN":"MATR","HIVE":"TECH"}
    return f"[{sectors.get(s.split('.')[0].upper(), 'IND')}]"

# --- 4. HIGH-SPEED BATCH DATA ENGINE ---
@st.cache_data(ttl=60)
def fetch_batch_data(tickers):
    if not tickers: return None
    try:
        # Fetching enough data to calculate RSI and Day Ranges
        data = yf.download(tickers, period="1mo", interval="15m", group_by='ticker', progress=False, threads=True)
        return data
    except: return None

def get_pro_data(ticker, batch_data):
    try:
        if isinstance(batch_data.columns, pd.MultiIndex):
            if ticker not in batch_data.columns.levels[0]: return None
            df = batch_data[ticker].dropna()
        else:
            df = batch_data.dropna()
            
        if df.empty: return None

        # Prices
        p_live = df['Close'].iloc[-1]
        prev_close = df['Close'].iloc[-2]
        
        # Day Range (Using last 1 day of 15m intervals approx 26 bars)
        # We will approximate Day High/Low from the last 24h of data
        last_day = df.tail(26)
        day_h = last_day['High'].max()
        day_l = last_day['Low'].min()

        # Timezone Logic
        now_et = datetime.utcnow() - timedelta(hours=5) 
        is_market = (now_et.weekday() < 5) and (9 <= now_et.hour < 16) and not (now_et.hour==9 and now_et.minute<30)
        is_tsx = any(x in ticker for x in ['.TO', '.V', '.CN'])

        disp_p = p_live
        disp_pct = ((p_live - prev_close)/prev_close)*100
        
        state, ext_p, ext_pct = "REG", None, 0.0
        if not is_tsx and not is_market and abs(p_live - prev_close) > 0.01:
            state = "PRE-MKT" if now_et.hour < 9 else ("POST-MKT" if now_et.hour >= 16 else "EXT")
            ext_p, ext_pct = p_live, disp_pct

        # Indicators
        rsi, trend, vol = 50, "NEUTRAL", 1.0
        if len(df) > 14:
            d = df['Close'].diff(); u, dd = d.clip(lower=0), -1*d.clip(upper=0)
            rsi = 100 - (100/(1 + (u.rolling(14).mean()/dd.rolling(14).mean()).iloc[-1]))
            trend = "BULL" if (df['Close'].ewm(span=12).mean() - df['Close'].ewm(span=26).mean()).iloc[-1] > 0 else "BEAR"
            vol = df['Volume'].iloc[-1] / df['Volume'].mean() if df['Volume'].mean() > 0 else 1.0

        # Chart
        chart = df['Close'].tail(50).reset_index()
        chart.columns = ['T', 'Stock']; chart['Idx'] = range(len(chart))
        chart['Stock'] = ((chart['Stock'] - chart['Stock'].iloc[0])/chart['Stock'].iloc[0])*100

        # Check alerts
        last_alert = st.session_state['storm_cooldown'].get(ticker, datetime.min)
        if (datetime.now()-last_alert).seconds > 300:
            if trend=="BULL" and rsi<35 and vol>1.2: log_alert(f"⚡ PERFECT STORM: {ticker}"); st.session_state['storm_cooldown'][ticker]=datetime.now()
            elif trend=="BEAR" and rsi>65 and vol>1.2: log_alert(f"🐻 DEATH BEAR: {ticker}"); st.session_state['storm_cooldown'][ticker]=datetime.now()

        return {"p": disp_p, "d": disp_pct, "h": day_h, "l": day_l, "rsi": rsi, "tr": trend, "vol": vol, 
                "chart": chart, "ai": "🟢 BULLISH" if trend=="BULL" else "🔴 BEARISH", "rat": "BUY", 
                "state": state, "ext_p": ext_p, "ext_d": ext_pct}
    except: return None

# --- SIDEBAR ---
st.sidebar.header("⚡ Penny Pulse")
if "OPENAI_KEY" in st.secrets: KEY = st.secrets["OPENAI_KEY"]
else: KEY = st.sidebar.text_input("OpenAI Key", type="password") 

# ADMIN
st.sidebar.markdown("---")
if st.sidebar.text_input("Admin Key", type="password", key="admin_key") == ADMIN_PASSWORD:
    st.sidebar.success("👑 Admin Mode")
    with st.sidebar.expander("Panel", expanded=True):
        c1, c2, c3 = st.columns([2,2,2])
        new_t = c1.text_input("Ticker").upper()
        new_p = c2.number_input("Price", 0.0)
        new_q = c3.number_input("Qty", 0)
        if st.button("➕ Add"):
            if new_t and new_q > 0: st.session_state['portfolio'][new_t] = {"e": new_p, "q": new_q}; st.rerun()
        if st.button("🗑️ Clear"): st.session_state['portfolio'] = {}; st.rerun()
        st.code(f"DEFAULT_PORTFOLIO = {json.dumps(st.session_state['portfolio'])}", language="python")

# BACKUP
with st.sidebar.expander("📤 Backup", expanded=False):
    if st.session_state.get('w_key'): st.query_params['w'] = st.session_state['w_key']
    current_w = st.session_state.get('w_key', "")
    if current_w: st.code(f"/?w={urllib.parse.quote(current_w)}", language="text")
    export = {'w_key': st.session_state.get('w_key'), 'portfolio': st.session_state.get('portfolio'), 'at_key': st.session_state.get('at_key'), 'ap_key': st.session_state.get('ap_key'), 'ao_key': st.session_state.get('ao_key')}
    st.download_button("Download", json.dumps(export), "pulse_profile.json")
    up = st.file_uploader("Restore", type="json")
    if up:
        try:
            d = json.loads(up.getvalue().decode("utf-8"))
            km = {'w_input': 'w_key', 'w_data': 'w_key', 'a_tick_input': 'at_key', 'a_price_input': 'ap_key'}
            for k, v in d.items(): st.session_state[km.get(k, k)] = v
            st.toast("Restored!"); time.sleep(0.5); st.rerun()
        except: st.error("Error")

# WIDGETS
st.sidebar.text_input("Tickers", key="w_key")
c1, c2 = st.sidebar.columns(2)
with c1: 
    if st.button("💾 Save"): st.toast("Saved!")
with c2: 
    if st.button("🔊 Test"): log_alert("Test!", sound=True)
st.sidebar.divider()
PORT = st.session_state.get('portfolio', {})
w_str = st.session_state.get('w_key', "")
ALL_T = list(set([x.strip().upper() for x in w_str.split(",") if x.strip()] + list(PORT.keys())))
st.sidebar.caption("Price Target Asset")
if st.session_state.get('at_key') not in ALL_T and ALL_T: st.session_state['at_key'] = ALL_T[0]
try: idx = sorted(ALL_T).index(st.session_state.get('at_key'))
except: idx = 0
st.sidebar.selectbox("", sorted(ALL_T), index=idx, key="at_key", label_visibility="collapsed")
st.sidebar.caption("Target ($)"); st.sidebar.number_input("", step=0.5, key="ap_key", label_visibility="collapsed")
st.sidebar.toggle("Active Price Alert", key="ao_key")
st.sidebar.toggle("Alert on Trend Flip", key="fo_key")
st.sidebar.toggle("💡 Keep Screen On", key="ko_key")
st.sidebar.checkbox("Desktop Notifications", key="no_key")
inject_wake_lock(st.session_state.get('ko_key', False))

# --- BATCH PRE-FETCH ---
all_tickers = list(set([x.strip().upper() for x in w_str.split(",") if x.strip()] + list(PORT.keys()) + ["SPY"]))
BATCH_DATA = fetch_batch_data(" ".join(all_tickers))

# --- SCROLLER ---
scroller_text = "Penny Pulse Market Tracker"
if BATCH_DATA is not None:
    scroller_text = "Penny Pulse Market Tracker • Market Data Active"
st.markdown(f"""<div style="background:#0E1117;padding:5px;border-bottom:1px solid #333;margin-bottom:15px;"><marquee style="color:#EEE;font-size:18px;">{scroller_text}</marquee></div>""", unsafe_allow_html=True)

# HEADER
img_html = f'<img src="data:image/png;base64,{get_base64_image(LOGO_PATH)}" style="max-height:120px; display:block; margin:0 auto;">' if get_base64_image(LOGO_PATH) else "<h1 style='text-align:center;'>⚡ Penny Pulse</h1>"
next_up = (datetime.utcnow() - timedelta(hours=5) + timedelta(minutes=1)).strftime('%H:%M:%S')
st.markdown(f"""<div style="background:black;border:1px solid #333;border-radius:10px;padding:20px;text-align:center;margin-bottom:20px;">{img_html}<div style="color:#888;font-size:12px;margin-top:10px;">NEXT UPDATE: <span style="color:#4CAF50;">{next_up} ET</span></div></div>""", unsafe_allow_html=True)

# UI TABS
t1, t2, t3 = st.tabs(["🏠 Dashboard", "🚀 My Picks", "📰 Market News"])

def draw_card(t, port=None):
    d = get_pro_data(t, BATCH_DATA)
    if not d: st.markdown(f"<div style='border:1px solid #333;padding:10px;border-radius:5px;'>Loading {t}...</div>", unsafe_allow_html=True); return
    
    col = "green" if d['d']>=0 else "red"
    col_hex = "#4caf50" if d['d']>=0 else "#ff4b4b"
    
    # CARD HEADER
    st.markdown(f"""
    <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:5px; padding-bottom:5px; border-bottom:1px solid #333;">
        <div style="flex:1;">
            <div style="font-size:24px; font-weight:900;">{get_name(t)}</div>
            <div style="font-size:14px; color:#BBB; font-weight:bold;">{t} <span style="color:#666; font-weight:normal;">{get_sector_tag(t)}</span></div>
        </div>
        <div style="text-align:right;">
            <div style="font-size:22px; font-weight:bold;">${d['p']:,.2f}</div>
            <div style="font-size:14px; font-weight:bold; color:{col_hex};">{d['d']:+.2f}%</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    if d['ext_p']: st.markdown(f"<div style='text-align:right;color:{'#4caf50' if d['ext_d']>=0 else '#ff4b4b'}'>{d['state']}: ${d['ext_p']:.2f} ({d['ext_d']:+.2f}%)</div>", unsafe_allow_html=True)
    
    if port:
        val = d['p']*port['q']; gain = val - (port['e']*port['q'])
        st.markdown(f"""<div style="background:#111;padding:8px;border-left:3px solid {col_hex};margin-bottom:10px;">Qty: {port['q']} | Avg: ${port['e']} | Gain: <span style="color:{col_hex}">${gain:,.2f}</span></div>""", unsafe_allow_html=True)

    # CHART
    base = alt.Chart(d['chart']).encode(x=alt.X('Idx', axis=None))
    l1 = base.mark_line(color=col_hex).encode(y=alt.Y('Stock', axis=None))
    l2 = base.mark_line(color='orange', strokeDash=[2,2]).encode(y=alt.Y('SPY', axis=None)) if 'SPY' in d['chart'] else l1
    st.altair_chart((l1+l2).properties(height=60), use_container_width=True)

    # DAY RANGE GRADIENT
    if d['h'] > d['l']: pct = (d['p'] - d['l']) / (d['h'] - d['l']) * 100
    else: pct = 50
    pct = max(0, min(100, pct))
    st.markdown(f"""<div style="font-size:10px;color:#888;margin-bottom:2px;">Day Range</div><div style="width:100%;height:8px;background:linear-gradient(90deg, #ff4b4b, #ffff00, #4caf50);border-radius:4px;position:relative;margin-bottom:10px;"><div style="position:absolute;left:{pct}%;top:-2px;width:3px;height:12px;background:white;border:1px solid #333;"></div></div>""", unsafe_allow_html=True)

    # VOL & RSI BARS
    vol_c = "#2196F3"; rsi_c = "#ff4b4b" if d['rsi']>70 else ("#4caf50" if d['rsi']>30 else "#2196F3")
    st.markdown(f"""
    <div style="font-size:10px;color:#888;">Volume ({d['vol']:.1f}x)</div>
    <div style="width:100%;height:6px;background:#333;border-radius:3px;margin-bottom:8px;"><div style="width:{min(100, d['vol']*50)}%;height:100%;background:{vol_c};"></div></div>
    <div style="font-size:10px;color:#888;">RSI ({d['rsi']:.0f})</div>
    <div style="width:100%;height:6px;background:#333;border-radius:3px;margin-bottom:15px;"><div style="width:{d['rsi']}%;height:100%;background:{rsi_c};"></div></div>
    """, unsafe_allow_html=True)
    st.divider()

with t1:
    cols = st.columns(3)
    try: w_list = [x.strip().upper() for x in st.session_state['w_key'].split(",") if x.strip()]
    except: w_list = []
    for i, t in enumerate(w_list):
        with cols[i%3]: draw_card(t)

with t2:
    if not st.session_state['portfolio']: st.info("Portfolio empty.")
    else:
        tv = 0; tc = 0
        if BATCH_DATA is not None:
            for t, inf in st.session_state['portfolio'].items():
                d = get_pro_data(t, BATCH_DATA)
                if d: tv += d['p']*inf['q']; tc += inf['e']*inf['q']
        
        tpl = tv - tc; troi = (tpl/tc)*100 if tc>0 else 0
        cc = "#4caf50" if tpl>=0 else "#ff4b4b"
        
        # RESTORED 3-COLUMN LAYOUT
        c1, c2, c3 = st.columns(3)
        with c1: st.markdown(f"""<div style="background:#1E1E1E;border:1px solid #333;border-radius:8px;padding:15px;text-align:center;"><div style="color:#888;font-size:12px;font-weight:bold;">NET LIQUIDITY</div><div style="font-size:24px;font-weight:900;color:white;">${tv:,.2f}</div></div>""", unsafe_allow_html=True)
        with c2: st.markdown(f"""<div style="background:#1E1E1E;border:1px solid #333;border-radius:8px;padding:15px;text-align:center;"><div style="color:#888;font-size:12px;font-weight:bold;">DAY PROFIT</div><div style="font-size:24px;font-weight:900;color:{cc};">${tv*0.01:,.2f}</div></div>""", unsafe_allow_html=True) # Placeholder calc for Day P/L
        with c3: st.markdown(f"""<div style="background:#1E1E1E;border:1px solid #333;border-radius:8px;padding:15px;text-align:center;"><div style="color:#888;font-size:12px;font-weight:bold;">TOTAL RETURN</div><div style="font-size:24px;font-weight:900;color:{cc};">${tpl:,.2f}<br><span style="font-size:16px;">({troi:+.1f}%)</span></div></div>""", unsafe_allow_html=True)
        
        st.markdown("<br>", unsafe_allow_html=True)
        cols = st.columns(3)
        for i, (t, inf) in enumerate(st.session_state['portfolio'].items()):
            with cols[i%3]: 
                draw_card(t, inf)
                if st.session_state.get('admin_key') == ADMIN_PASSWORD and st.button(f"🗑️ Remove {t}", key=f"del_{t}"):
                    del st.session_state['portfolio'][t]; st.rerun()

with t3:
    if st.button("Analyze News"):
        try:
            raw = []
            for f in NEWS_FEEDS:
                try: 
                    r = requests.get(f, timeout=3); root = ET.fromstring(r.content)
                    for i in root.findall('.//item')[:5]: raw.append({"title": i.find('title').text, "link": i.find('link').text, "time": "Recent"})
                except: continue
            if KEY:
                res = process_ai_batch(raw[:15], KEY)
                for n in res:
                    sc = "#4caf50" if n.get('sentiment')=="BULL" else "#ff4b4b"
                    st.markdown(f"<div style='border-left:4px solid {sc};padding-left:10px;margin-bottom:10px;'><b>{n.get('ticker','MKT')}</b>: {n.get('summary')} <a href='{n.get('link')}'>Read</a></div>", unsafe_allow_html=True)
            else: st.error("No API Key")
        except: st.error("News Error")

time.sleep(60)
st.rerun()
