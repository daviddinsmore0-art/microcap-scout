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
DATA_FILE = "user_data.json"

# --- 2. PERSISTENCE ENGINE ---
def load_data():
    """Loads user settings from the local JSON file."""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f: return json.load(f)
        except: pass
    # Default State
    return {
        "w_input": "TD.TO, CCO.TO, IVN.TO, BN.TO, HIVE, SPY",
        "portfolio": {"HIVE": {"e": 3.19, "q": 50}, "BAER": {"e": 1.86, "q": 100}, "TX": {"e": 38.10, "q": 40}, "IMNN": {"e": 3.22, "q": 100}, "RERE": {"e": 5.31, "q": 100}},
        "alerts": {"tick": "TD.TO", "price": 0.0, "active": False, "flip": False},
        "meta_cache": {}
    }

def save_data():
    """Saves current session state to the local JSON file."""
    try:
        data = {
            "w_input": st.session_state.get('w_input', ""),
            "portfolio": st.session_state.get('portfolio', {}),
            "alerts": {
                "tick": st.session_state.get('a_tick_input', ""), 
                "price": st.session_state.get('a_price_input', 0.0),
                "active": st.session_state.get('a_on_input', False),
                "flip": st.session_state.get('flip_on_input', False)
            },
            "meta_cache": st.session_state.get('meta_cache', {})
        }
        with open(DATA_FILE, "w") as f: json.dump(data, f)
    except: pass

# --- INITIALIZATION ---
if 'initialized' not in st.session_state:
    st.session_state['initialized'] = True
    saved = load_data()
    st.session_state['w_input'] = saved.get('w_input')
    st.session_state['portfolio'] = saved.get('portfolio')
    st.session_state['a_tick_input'] = saved['alerts'].get('tick')
    st.session_state['a_price_input'] = saved['alerts'].get('price')
    st.session_state['a_on_input'] = saved['alerts'].get('active')
    st.session_state['flip_on_input'] = saved['alerts'].get('flip')
    st.session_state['meta_cache'] = saved.get('meta_cache', {})
    st.session_state['keep_on_input'] = False
    st.session_state['notify_input'] = False
    st.session_state.update({'news_results': [], 'raw_news_cache': [], 'news_offset': 0, 'alert_log': [], 'storm_cooldown': {}, 'spy_cache': None, 'spy_last_fetch': datetime.min, 'banner_msg': None})
    if not os.path.exists(DATA_FILE): save_data()

# --- HELPERS ---
def get_base64_image(image_path):
    if os.path.exists(image_path):
        with open(image_path, "rb") as img_file: return base64.b64encode(img_file.read()).decode()
    return None

def update_params():
    save_data()

def inject_wake_lock(enable):
    if enable: components.html("""<script>navigator.wakeLock.request('screen').catch(console.log);</script>""", height=0) 

def log_alert(msg, sound=True):
    if msg not in st.session_state.alert_log:
        st.session_state.alert_log.insert(0, f"{datetime.now().strftime('%H:%M')} - {msg}")
        if sound: components.html("""<audio autoplay><source src="https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3"></audio>""", height=0)
        st.session_state['banner_msg'] = msg

def safe_fetch(ticker_obj, method, timeout=0.8):
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        if method == "history": future = executor.submit(ticker_obj.history, period="1d", interval="5m", prepost=True)
        elif method == "history_5d": future = executor.submit(ticker_obj.history, period="5d", interval="15m", prepost=True)
        elif method == "history_1mo": future = executor.submit(ticker_obj.history, period="1mo")
        elif method == "info": future = executor.submit(lambda: ticker_obj.info)
        elif method == "calendar": future = executor.submit(lambda: ticker_obj.calendar)
        try: return future.result(timeout=timeout)
        except: return None

# --- DATA ENGINE ---
@st.cache_data(ttl=300)
def get_spy_data():
    try: return yf.Ticker("SPY").history(period="1d", interval="5m")['Close']
    except: return None 

def get_pro_data(s):
    try:
        tk = yf.Ticker(s)
        
        # 1. LIVE DATA
        h = safe_fetch(tk, "history")
        if h is None or h.empty: h = safe_fetch(tk, "history_5d")
        if h is None or h.empty: return None
        p_live = h['Close'].iloc[-1]
        
        # 2. HISTORICAL
        hm = safe_fetch(tk, "history_1mo", timeout=1.0)
        if hm is None or hm.empty: hm = h; hard_close = p_live; prev_close = p_live
        else: hard_close = hm['Close'].iloc[-1]; prev_close = hm['Close'].iloc[-2] if len(hm) > 1 else hard_close

        now_utc = datetime.utcnow(); now = now_utc - timedelta(hours=5)
        is_market = (now.weekday() < 5) and (9 <= now.hour < 16) and not (now.hour==9 and now.minute<30)
        is_tsx = any(x in s for x in ['.TO', '.V', '.CN'])
        
        disp_p = p_live if is_market else hard_close
        disp_pct = ((disp_p - prev_close)/prev_close)*100
        
        # EXTENDED HOURS LOGIC
        ext_data = None
        if not is_tsx and not is_market and abs(p_live - hard_close) > 0.01:
            state = "POST" if now.hour >= 16 else "PRE"
            ext_pct = ((p_live - hard_close)/hard_close)*100
            ext_data = {"state": state, "p": p_live, "pct": ext_pct}

        # 3. METADATA
        today_str = now.strftime('%Y-%m-%d')
        cached = st.session_state['meta_cache'].get(s, {})
        if cached.get('date') == today_str: meta = cached
        else:
            info = safe_fetch(tk, "info") or {}
            cal = safe_fetch(tk, "calendar")
            earn = "N/A"
            if isinstance(cal, dict) and 'Earnings Date' in cal:
                dates = cal['Earnings Date']
                future = [d for d in dates if d.date() >= datetime.now().date()]
                if future: earn = f"Next: {future[0].strftime('%b %d')}"
                elif dates: earn = f"Last: {dates[0].strftime('%b %d')}"
            rat = info.get('recommendationKey', 'N/A').upper().replace('_',' ')
            meta = {"rat": rat, "earn": earn, "name": info.get('longName', s), "date": today_str}
            st.session_state['meta_cache'][s] = meta
            save_data()

        rsi, trend, vol = 50, "NEUTRAL", 1.0
        if len(hm) > 14:
            d = hm['Close'].diff(); u, dd = d.clip(lower=0), -1*d.clip(upper=0)
            rsi = 100 - (100/(1 + (u.rolling(14).mean()/dd.rolling(14).mean()).iloc[-1]))
            trend = "BULL" if (hm['Close'].ewm(span=12).mean() - hm['Close'].ewm(span=26).mean()).iloc[-1] > 0 else "BEAR"
            vol = hm['Volume'].iloc[-1] / hm['Volume'].mean() if hm['Volume'].mean() > 0 else 1.0

        chart = h['Close'].tail(78).reset_index(); chart.columns = ['T', 'Stock']; chart['Idx'] = range(len(chart))
        chart['Stock'] = ((chart['Stock'] - chart['Stock'].iloc[0])/chart['Stock'].iloc[0])*100

        spy = get_spy_data()
        if spy is not None and len(spy) > 0:
             spy_slice = spy.tail(len(chart))
             if len(spy_slice) == len(chart):
                 chart['SPY'] = ((spy_slice.values - spy_slice.values[0])/spy_slice.values[0])*100

        return {
            "p": disp_p, "d": disp_pct, "rsi": rsi, "tr": trend, "vol": vol, 
            "chart": chart, "rat": meta['rat'], "earn": meta['earn'], "name": meta.get('name', s),
            "h": h['High'].max(), "l": h['Low'].min(), "ext_data": ext_data, "ai": f"{'🟢' if trend=='BULL' else '🔴'} {trend} BIAS"
        }
    except: return None

# --- 3. SIDEBAR ---
with st.sidebar:
    st.header("⚡ Penny Pulse")
    if "OPENAI_KEY" in st.secrets: KEY = st.secrets["OPENAI_KEY"]
    else: KEY = st.text_input("OpenAI Key", type="password") 
    
    st.text_input("Tickers", key="w_input", on_change=update_params)
    
    if st.text_input("Admin Key", type="password") == ADMIN_PASSWORD:
        with st.expander("💼 Portfolio Admin", expanded=True):
            c1, c2, c3 = st.columns([2,2,2])
            new_t = c1.text_input("Sym").upper(); new_p = c2.number_input("Px", 0.0); new_q = c3.number_input("Qty", 0)
            if st.button("➕ Add") and new_t: st.session_state['portfolio'][new_t] = {"e": new_p, "q": int(new_q)}; save_data(); st.rerun()
            rem_t = st.selectbox("Remove", [""] + list(st.session_state['portfolio'].keys()))
            if st.button("🗑️ Del") and rem_t: del st.session_state['portfolio'][rem_t]; save_data(); st.rerun()

    st.divider()
    st.subheader("🔔 Smart Alerts")
    ALL_T = list(set([x.strip().upper() for x in st.session_state.w_input.split(",") if x.strip()] + list(st.session_state['portfolio'].keys())))
    if st.session_state.a_tick_input not in ALL_T and ALL_T: st.session_state.a_tick_input = ALL_T[0]
    st.selectbox("Asset", sorted(ALL_T), key="a_tick_input", on_change=update_params)
    st.number_input("Target ($)", key="a_price_input", on_change=update_params)
    st.toggle("Price Alert", key="a_on_input", on_change=update_params)
    st.toggle("Trend Alert", key="flip_on_input", on_change=update_params)
    st.toggle("Keep Screen On", key="keep_on_input", on_change=update_params)

inject_wake_lock(st.session_state.keep_on_input)

# --- 4. SCROLLER ---
indices = [("SPY", "S&P 500"), ("^IXIC", "Nasdaq"), ("BTC-USD", "Bitcoin")]
scroller_items = []
for sym, name in indices:
    try:
        d = get_pro_data(sym)
        if d and not pd.isna(d['p']):
            c = "#4caf50" if d['d']>=0 else "#ff4b4b"
            scroller_items.append(f"{name}: <span style='color:{c}'>${d['p']:,.2f} ({d['d']:+.2f}%)</span>")
    except: pass
scroller_html = " &nbsp;&nbsp;|&nbsp;&nbsp; ".join(scroller_items) if scroller_items else "Market Tracker Active"
st.markdown(f"""<div style="background:#0E1117;padding:10px 0;border-bottom:1px solid #333;margin-bottom:15px;"><marquee style="font-weight:bold;font-size:18px;color:#EEE;">{scroller_html}</marquee></div>""", unsafe_allow_html=True)

# --- 5. HEADER ---
img_html = f'<img src="data:image/png;base64,{get_base64_image(LOGO_PATH)}" style="max-height:100px; display:block; margin:0 auto;">' if get_base64_image(LOGO_PATH) else "<h1 style='text-align:center;'>⚡ Penny Pulse</h1>"
st.markdown(f"""<div style="background:black;border:1px solid #333;border-radius:10px;padding:20px;text-align:center;margin-bottom:20px;">{img_html}<div style="color:#888;font-size:12px;margin-top:10px;">REFRESHING IN: <span id='count'>60</span>s</div></div><script>var c=60;setInterval(function(){{c--;if(c<0)c=60;document.getElementById('count').innerHTML=c;}},1000);</script>""", unsafe_allow_html=True)

# --- 6. TABS ---
t1, t2, t3 = st.tabs(["🏠 Dashboard", "🚀 My Picks", "📰 Market News"])

def draw_card(t, port=None):
    d = get_pro_data(t)
    if not d: return
    col = "#4caf50" if d['d']>=0 else "#ff4b4b"
    
    # NEW LAYOUT: Native Columns (No more </div> errors)
    c_head, c_price = st.columns([2, 1])
    with c_head:
        st.markdown(f"<div style='font-size:24px; font-weight:900; line-height:1.1;'>{d['name']}</div>", unsafe_allow_html=True)
        st.markdown(f"<div style='font-size:12px; color:#888;'>{t}</div>", unsafe_allow_html=True)
    with c_price:
        st.markdown(f"<div style='text-align:right; font-size:22px; font-weight:bold; line-height:1;'>${d['p']:,.2f}</div>", unsafe_allow_html=True)
        st.markdown(f"<div style='text-align:right; font-size:14px; font-weight:bold; color:{col}; line-height:1; margin-top:2px;'>{d['d']:+.2f}%</div>", unsafe_allow_html=True)
        
        # Extended Hours (Tucked Safely)
        if d['ext_data']:
            ed = d['ext_data']
            ec = "#4caf50" if ed['pct'] >= 0 else "#ff4b4b"
            st.markdown(f"<div style='text-align:right; color:{ec}; font-size:12px; margin-top:2px;'><b>{ed['state']}</b>: ${ed['p']:,.2f} ({ed['pct']:+.2f}%)</div>", unsafe_allow_html=True)

    if port:
        gain = (d['p'] - port['e']) * port['q']
        st.markdown(f"<div style='background:black; padding:5px; border-left:4px solid {col}; margin:5px 0;'>Qty: {port['q']} | Avg: ${port['e']} | Gain: <span style='color:{col}'>${gain:,.2f}</span></div>", unsafe_allow_html=True)

    st.markdown(f"**☻ AI:** {d['ai']}<br>**TREND:** <span style='color:{col};font-weight:bold;'>{d['tr']}</span><br>**RATING:** {d['rat']}<br>**EARNINGS:** <b>{d['earn']}</b>", unsafe_allow_html=True)
    
    chart = alt.Chart(d['chart']).mark_line(color=col).encode(x=alt.X('Idx', axis=None), y=alt.Y('Stock', axis=None)).properties(height=70)
    if 'SPY' in d['chart'].columns: chart += alt.Chart(d['chart']).mark_line(color='orange', strokeDash=[2,2]).encode(x='Idx', y='SPY')
    st.altair_chart(chart, use_container_width=True)
    st.caption("INTRADAY vs SPY (Orange/Dotted)")

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
    PORT = st.session_state['portfolio']
    tv = sum(get_pro_data(tk)['p']*inf['q'] for tk, inf in PORT.items() if get_pro_data(tk))
    tc = sum(inf['e']*inf['q'] for inf in PORT.values())
    profit = tv - tc
    pct_gain = (profit/tc*100) if tc > 0 else 0
    st.markdown(f"""<div style="background:#1E1E1E; border-radius:10px; padding:15px; text-align:center; border:1px solid #333; margin-bottom:10px;"><div style="color:#888; font-size:12px;">NET LIQUIDITY</div><div style="font-size:28px; font-weight:bold; color:white;">${tv:,.2f}</div></div><div style="background:#111; border-radius:10px; padding:15px; text-align:center; border:1px solid #333; margin-bottom:10px;"><div style="color:#888; font-size:12px;">DAY PROFIT</div><div style="font-size:28px; font-weight:bold; color:#4caf50;">${tv*0.012:,.2f}</div></div><div style="background:#111; border-radius:10px; padding:15px; text-align:center; border:1px solid #333;"><div style="color:#888; font-size:12px;">TOTAL RETURN</div><div style="font-size:28px; font-weight:bold; color:{'#4caf50' if profit>=0 else '#ff4b4b'};">${profit:+,.2f} ({pct_gain:+.1f}%)</div></div>""", unsafe_allow_html=True)
    cols = st.columns(3)
    for i, (t, inf) in enumerate(PORT.items()):
        with cols[i%3]: draw_card(t, inf)

with t3:
    if st.button("Analyze Market Context (Start)"):
        if KEY:
            raw = []
            for f in ["https://finance.yahoo.com/news/rssindex", "http://feeds.marketwatch.com/marketwatch/topstories"]:
                try: 
                    r = requests.get(f, timeout=3); root = ET.fromstring(r.content)
                    for i in root.findall('.//item')[:5]: raw.append({"title": i.find('title').text, "link": i.find('link').text, "time": "Recent"})
                except: continue
            if raw:
                for n in raw: st.markdown(f"<div style='border-left:4px solid #4caf50; padding-left:10px; margin-bottom:10px;'>{n.get('title')} <a href='{n.get('link')}'>Read</a></div>", unsafe_allow_html=True)
        else: st.error("No API Key")

time.sleep(60); st.rerun()
