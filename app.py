import streamlit as st, yfinance as yf, requests, time
from datetime import datetime, timedelta
import streamlit.components.v1 as components
import pandas as pd
import altair as alt 
import xml.etree.ElementTree as ET
import os
import base64

# --- 1. SETUP ---
try: st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="wide")
except: pass 

# *** CONFIG ***
ADMIN_PASSWORD = "admin123"
LOGO_PATH = "logo.png"

# --- 2. SESSION STATE (RAM ONLY - NO FILE SAVING) ---
if 'initialized' not in st.session_state:
    st.session_state['initialized'] = True
    # YOUR DEFAULT LIST (Hardcoded since we aren't saving)
    st.session_state['w_input'] = "TD.TO, CCO.TO, IVN.TO, BN.TO, HIVE, SPY, NKE, VCIG, AIRE, IMNN, BAER, RERE"
    
    # YOUR DEFAULT PORTFOLIO (Hardcoded)
    st.session_state['portfolio'] = {
        "HIVE": {"e": 3.19, "q": 50}, 
        "BAER": {"e": 1.86, "q": 100}, 
        "TX": {"e": 38.10, "q": 40}, 
        "IMNN": {"e": 3.22, "q": 100}, 
        "RERE": {"e": 5.31, "q": 100}
    }
    
    st.session_state['alerts'] = {"tick": "TD.TO", "price": 0.0, "active": False, "flip": False}
    st.session_state['meta_cache'] = {} # RAM Cache only
    st.session_state['keep_on_input'] = False
    st.session_state['a_tick_input'] = "TD.TO"
    st.session_state['a_price_input'] = 0.0
    st.session_state['a_on_input'] = False
    st.session_state['flip_on_input'] = False

# --- HELPERS ---
def get_base64_image(image_path):
    if os.path.exists(image_path):
        with open(image_path, "rb") as img_file: return base64.b64encode(img_file.read()).decode()
    return None

def inject_wake_lock(enable):
    if enable: components.html("""<script>navigator.wakeLock.request('screen').catch(console.log);</script>""", height=0) 

# --- DATA ENGINE (DIRECT & DECOUPLED) ---
@st.cache_data(ttl=300)
def get_spy_data():
    try: return yf.Ticker("SPY").history(period="1d", interval="5m")['Close']
    except: return None 

def get_pro_data(s):
    try:
        tk = yf.Ticker(s)
        
        # 1. PRICE (Daily - Guaranteed)
        daily = tk.history(period="1d")
        if daily.empty: return None 
        
        p_live = daily['Close'].iloc[-1]
        p_open = daily['Open'].iloc[-1]
        
        # 2. CHART (Intraday - Best Effort)
        try:
            intraday = tk.history(period="1d", interval="5m", prepost=False)
        except: intraday = pd.DataFrame()
            
        if not intraday.empty:
            chart_source = intraday
            p_live = intraday['Close'].iloc[-1]
            prev_close = intraday['Close'].iloc[0] 
        else:
            chart_source = daily
            prev_close = p_open

        # Math
        d_val = p_live - prev_close
        d_pct = (d_val / prev_close) * 100 if prev_close != 0 else 0
        
        # 3. METADATA (RAM Cache Only)
        if s in st.session_state['meta_cache']:
            meta = st.session_state['meta_cache'][s]
        else:
            info = tk.info or {}
            try: cal = tk.calendar
            except: cal = {}
            earn = "N/A"
            if isinstance(cal, dict) and 'Earnings Date' in cal:
                dates = cal['Earnings Date']
                future = [d for d in dates if d.date() >= datetime.now().date()]
                if future: earn = f"Next: {future[0].strftime('%b %d')}"
                elif dates: earn = f"Last: {dates[0].strftime('%b %d')}"
            rat = info.get('recommendationKey', 'N/A').upper().replace('_',' ')
            meta = {"rat": rat, "earn": earn, "name": info.get('longName', s)}
            st.session_state['meta_cache'][s] = meta

        # Chart
        chart = chart_source['Close'].reset_index()
        chart.columns = ['T', 'Stock']
        chart['Idx'] = range(len(chart))
        chart['Stock'] = ((chart['Stock'] - chart['Stock'].iloc[0])/chart['Stock'].iloc[0])*100

        spy = get_spy_data()
        if spy is not None and len(spy) > 0 and len(chart) > 1 and not intraday.empty:
             spy_slice = spy.tail(len(chart))
             if len(spy_slice) == len(chart):
                 chart['SPY'] = ((spy_slice.values - spy_slice.values[0])/spy_slice.values[0])*100

        trend = "BULL" if d_pct >= 0 else "BEAR"
        
        return {
            "p": p_live, "d": d_pct, "tr": trend,
            "chart": chart, "rat": meta['rat'], "earn": meta['earn'], "name": meta.get('name', s),
            "h": daily['High'].max(), "l": daily['Low'].min(), 
            "ai": f"{'🟢' if trend=='BULL' else '🔴'} {trend} BIAS"
        }
    except: return None

# --- 3. SIDEBAR ---
with st.sidebar:
    st.header("⚡ Penny Pulse")
    
    # Simple Text Input (RAM Only)
    new_w = st.text_input("Tickers", value=st.session_state.w_input)
    if new_w != st.session_state.w_input:
        st.session_state.w_input = new_w
        st.rerun()
    
    if st.text_input("Admin Key", type="password") == ADMIN_PASSWORD:
        with st.expander("💼 Portfolio Admin", expanded=True):
            st.info("🔓 Access Granted (RAM Only)")
            c1, c2, c3 = st.columns([2,2,2])
            new_t = c1.text_input("Sym").upper(); new_p = c2.number_input("Px", 0.0); new_q = c3.number_input("Qty", 0)
            if st.button("➕ Add") and new_t: 
                st.session_state['portfolio'][new_t] = {"e": new_p, "q": int(new_q)}
                st.rerun()
            rem_t = st.selectbox("Remove", [""] + list(st.session_state['portfolio'].keys()))
            if st.button("🗑️ Del") and rem_t: 
                del st.session_state['portfolio'][rem_t]
                st.rerun()

    st.divider()
    st.subheader("🔔 Smart Alerts")
    ALL_T = list(set([x.strip().upper() for x in st.session_state.w_input.split(",") if x.strip()] + list(st.session_state['portfolio'].keys())))
    if st.session_state.a_tick_input not in ALL_T and ALL_T: st.session_state.a_tick_input = ALL_T[0]
    
    st.selectbox("Asset", sorted(ALL_T), key="a_tick_input")
    st.number_input("Target ($)", key="a_price_input")
    st.toggle("Price Alert", key="a_on_input")
    st.toggle("Trend Alert", key="flip_on_input")
    st.toggle("Keep Screen On", key="keep_on_input")

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
st.markdown(f"""<div style="background:black;border:1px solid #333;border-radius:10px;padding:20px;text-align:center;margin-bottom:20px;">{img_html}<div style="color:#888;font-size:12px;margin-top:10px;">NEXT PULSE: <span style="color:#4caf50; font-weight:bold;">{(datetime.utcnow()-timedelta(hours=5)+timedelta(minutes=1)).strftime('%H:%M:%S')} ET</span></div></div>""", unsafe_allow_html=True)

# --- 6. TABS ---
t1, t2, t3 = st.tabs(["🏠 Dashboard", "🚀 My Picks", "📰 Market News"])

def draw_card(t, port=None):
    d = get_pro_data(t)
    if not d:
        st.warning(f"⚠️ {t}: Data N/A (Retrying...)")
        return

    col_str = "green" if d['d']>=0 else "red"
    col_hex = "#4caf50" if d['d']>=0 else "#ff4b4b"
    
    c_head, c_price = st.columns([2, 1])
    with c_head:
        st.markdown(f"### {d['name']}")
        st.caption(f"{t}")
    with c_price:
        st.metric(label="", value=f"${d['p']:,.2f}", delta=f"{d['d']:.2f}%")

    if port:
        gain = (d['p'] - port['e']) * port['q']
        st.info(f"Qty: {port['q']} | Avg: ${port['e']} | Gain: ${gain:,.2f}")

    st.markdown(f"**☻ AI:** {d['ai']}<br>**TREND:** :{col_str}[**{d['tr']}**]<br>**RATING:** {d['rat']}<br>**EARNINGS:** {d['earn']}", unsafe_allow_html=True)
    
    chart = alt.Chart(d['chart']).mark_line(color=col_hex).encode(x=alt.X('Idx', axis=None), y=alt.Y('Stock', axis=None)).properties(height=70)
    if 'SPY' in d['chart'].columns: chart += alt.Chart(d['chart']).mark_line(color='orange', strokeDash=[2,2]).encode(x='Idx', y='SPY')
    st.altair_chart(chart, use_container_width=True)
    st.caption("INTRADAY vs SPY (Orange/Dotted)")

    pct = max(0, min(100, ((d['p']-d['l'])/(d['h']-d['l'])*100 if d['h']>d['l'] else 50)))
    st.markdown(f"""<div style="font-size:10px;color:#888;">Day Range</div><div style="width:100%;height:8px;background:linear-gradient(90deg, #ff4b4b, #ffff00, #4caf50);border-radius:4px;position:relative;margin-bottom:10px;"><div style="position:absolute;left:{pct}%;top:-2px;width:3px;height:12px;background:white;border:1px solid #333;"></div></div>""", unsafe_allow_html=True)
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
        raw = []
        for f in ["https://finance.yahoo.com/news/rssindex", "http://feeds.marketwatch.com/marketwatch/topstories"]:
            try: 
                r = requests.get(f, timeout=3); root = ET.fromstring(r.content)
                for i in root.findall('.//item')[:5]: raw.append({"title": i.find('title').text, "link": i.find('link').text, "time": "Recent"})
            except: continue
        for n in raw: st.markdown(f"<div style='border-left:4px solid #4caf50; padding-left:10px; margin-bottom:10px;'>{n.get('title')} <a href='{n.get('link')}'>Read</a></div>", unsafe_allow_html=True)

time.sleep(60); st.rerun()
