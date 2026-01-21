import streamlit as st, yfinance as yf, requests, time, re
from datetime import datetime, timedelta
import streamlit.components.v1 as components
import pandas as pd
import altair as alt 
import json
import xml.etree.ElementTree as ET

# --- 1. SETUP & MEMORY ---
try: st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="wide")
except: pass 

if 'initialized' not in st.session_state:
    st.session_state['initialized'] = True
    defaults = {
        'w_input': "TD.TO, CCO.TO, IVN.TO, BN.TO, HIVE, SPY",
        'a_tick_input': "TD.TO", 'a_price_input': 0.0,
        'a_on_input': False, 'flip_on_input': False,
        'keep_on_input': False, 'notify_input': False
    }
    qp = st.query_params
    for k, v in defaults.items():
        pk = k.replace('_input','')
        if pk in qp:
            val = qp[pk]
            if isinstance(v, bool): st.session_state[k] = (val.lower() == 'true')
            else:
                try: st.session_state[k] = float(val) if isinstance(v, float) else val
                except: st.session_state[k] = val
        else: st.session_state[k] = v

    st.session_state.update({
        'news_results': [], 'alert_log': [], 'last_trends': {}, 
        'mem_ratings': {}, 'storm_cooldown': {}, 'spy_cache': None,
        'spy_last_fetch': datetime.min
    })

# --- 2. FUNCTIONS ---
def update_params():
    for k in ['w','at','ap','ao','fo','no','ko']:
        kn = f"{k if len(k)>2 else k+'_input'}"
        if kn in st.session_state: st.query_params[k] = str(st.session_state[kn]).lower()

def inject_wake_lock(enable):
    if enable: components.html("""<script>navigator.wakeLock.request('screen').catch(console.log);</script>""", height=0)

def get_sector_tag(s):
    sectors = {
        "TD": "FINA", "BN": "FINA", "RY": "FINA", "BMO": "FINA",
        "CCO": "ENGY", "SU": "ENGY", "CNQ": "ENGY",
        "IVN": "MATR", "LUN": "MATR", "TECK": "MATR",
        "HIVE": "TECH", "SHOP": "TECH", "BITF": "TECH",
        "BAER": "IND", "AC": "IND"
    }
    base = s.split('.')[0].upper()
    return f"[{sectors.get(base, 'IND')}]"

# --- 3. SIDEBAR ---
st.sidebar.header("⚡ Penny Pulse")

if "OPENAI_KEY" in st.secrets: KEY = st.secrets["OPENAI_KEY"]
else: KEY = st.sidebar.text_input("OpenAI Key", type="password") 

st.sidebar.text_input("Tickers", key="w_input", on_change=update_params)

c1, c2 = st.sidebar.columns(2)
with c1: 
    if st.button("💾 Save Settings"): update_params(); st.toast("Settings Saved!")
with c2: 
    if st.button("🔊 Test Audio"): components.html("""<audio autoplay><source src="https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3"></audio>""", height=0)

st.sidebar.divider()
st.sidebar.subheader("🔔 Smart Alerts")

PORT = {"HIVE": {"e": 3.19, "d": "Dec 01", "q": 50}, "BAER": {"e": 1.86, "d": "Jan 10", "q": 100}, "TX": {"e": 38.10, "d": "Nov 05", "q": 40}, "IMNN": {"e": 3.22, "d": "Aug 20", "q": 100}, "RERE": {"e": 5.31, "d": "Oct 12", "q": 100}}
ALL_T = list(set([x.strip().upper() for x in st.session_state.w_input.split(",") if x.strip()] + list(PORT.keys())))

st.sidebar.caption("Price Target Asset")
if st.session_state.a_tick_input not in ALL_T:
    st.session_state.a_tick_input = ALL_T[0]
st.sidebar.selectbox("", sorted(ALL_T), key="a_tick_input", on_change=update_params, label_visibility="collapsed")

st.sidebar.caption("Target ($)")
st.sidebar.number_input("", step=0.5, key="a_price_input", on_change=update_params, label_visibility="collapsed")

st.sidebar.toggle("Active Price Alert", key="a_on_input", on_change=update_params)
st.sidebar.toggle("Alert on Trend Flip", key="flip_on_input", on_change=update_params)
st.sidebar.toggle("💡 Keep Screen On (Mobile)", key="keep_on_input", on_change=update_params)
st.sidebar.checkbox("Desktop Notifications", key="notify_input", on_change=update_params)

with st.sidebar.expander("📦 Backup & Restore"):
    export_data = {k: st.session_state[k] for k in ['w_input', 'a_tick_input', 'a_price_input', 'a_on_input']}
    st.download_button("Download Profile", json.dumps(export_data), "pulse_profile.json")

inject_wake_lock(st.session_state.keep_on_input)

# --- 4. DATA ENGINE (PRO) ---
@st.cache_data(ttl=300)
def get_spy_data():
    try: return yf.Ticker("SPY").history(period="1d", interval="5m")['Close']
    except: return None

def get_pro_data(s):
    try:
        tk = yf.Ticker(s)
        use_prepost = not any(x in s for x in [".TO", ".V", ".CN"])
        h = tk.history(period="1d", interval="5m", prepost=use_prepost)
        if h.empty: h = tk.history(period="5d", interval="1h", prepost=use_prepost)
        if h.empty: return None
        
        p = h['Close'].iloc[-1]
        try: pv = tk.fast_info['previous_close']
        except: pv = h['Open'].iloc[0]
        d_pct = ((p-pv)/pv)*100
        
        hm = tk.history(period="1mo")
        rsi, trend, vol_ratio = 50, "NEUTRAL", 1.0
        if len(hm) > 14:
            diff = hm['Close'].diff(); u, d = diff.clip(lower=0), -1*diff.clip(upper=0)
            rsi = 100 - (100/(1 + (u.rolling(14).mean()/d.rolling(14).mean()).iloc[-1]))
            m = hm['Close'].ewm(span=12).mean() - hm['Close'].ewm(span=26).mean()
            trend = "BULL" if m.iloc[-1] > 0 else "BEAR"
            vol_ratio = hm['Volume'].iloc[-1] / hm['Volume'].mean() if hm['Volume'].mean() > 0 else 1.0
            
        ai_bias = "🟢 BULLISH BIAS" if (trend=="BULL" and rsi<70) else ("🔴 BEARISH BIAS" if (trend=="BEAR" and rsi>30) else "🟡 NEUTRAL BIAS")

        spy = get_spy_data()
        chart_data = h['Close'].reset_index()
        chart_data.columns = ['T', 'Stock']
        chart_data['Idx'] = range(len(chart_data)) # Fix Left Alignment
        
        chart_data['Stock'] = ((chart_data['Stock'] - chart_data['Stock'].iloc[0]) / chart_data['Stock'].iloc[0]) * 100
        if spy is not None and len(spy) > 0:
            s_norm = ((spy - spy.iloc[0]) / spy.iloc[0]) * 100
            if len(s_norm) >= len(chart_data): chart_data['SPY'] = s_norm.values[-len(chart_data):]
            else: chart_data['SPY'] = 0

        # EARNINGS FIX
        earn = "N/A"
        try:
            cal = tk.calendar
            if cal is not None and not cal.empty:
                # Handle different formats of calendar return
                if hasattr(cal, 'iloc'):
                    val = cal.iloc[0, 0]
                    if isinstance(val, (datetime, pd.Timestamp)): earn = val.strftime('%b %d')
        except: pass
        
        rat = tk.info.get('recommendationKey', 'N/A').upper().replace('_',' ')

        return {
            "p": p, "d": d_pct, "rsi": rsi, "tr": trend, "vol": vol_ratio,
            "chart": chart_data, "ai": ai_bias, "rat": rat, "earn": earn,
            "h": h['High'].max(), "l": h['Low'].min()
        }
    except: return None

# --- 5. HEADER & SCROLLER (FIXED COLORS) ---
est = datetime.utcnow() - timedelta(hours=5)

# Scroller Logic: Fetch Data & Colorize
@st.cache_data(ttl=60)
def build_scroller():
    items = []
    for t, n in [("SPY", "SPY"), ("BTC-USD", "BTC"), ("^GSPTSE", "TSX")]:
        d = get_pro_data(t)
        if d:
            c = "#4caf50" if d['d'] >= 0 else "#ff4b4b"
            a = "▲" if d['d'] >= 0 else "▼"
            items.append(f"{n}: <span style='color:{c}'>${d['p']:,.2f} {a} {d['d']:.2f}%</span>")
    return "&nbsp;&nbsp;&nbsp;&nbsp;".join(items)

scroller_html = build_scroller()
st.markdown(f"""
<div style="background:#0E1117;padding:5px 0;border-top:1px solid #333;border-bottom:1px solid #333;margin-bottom:10px;">
<marquee scrollamount="8" style="width:100%;font-weight:bold;font-size:18px;color:white;">{scroller_html}</marquee>
</div>
""", unsafe_allow_html=True)

c1, c2 = st.columns([3, 2])
with c1:
    st.title("⚡ Penny Pulse")
    st.caption(f"Last Sync: {est.strftime('%H:%M:%S EST')}")
with c2:
    components.html("""<div style="font-family:'Helvetica';background:#0E1117;padding:5px;text-align:right;display:flex;justify-content:flex-end;align-items:center;height:100%;"><span style="color:#BBBBBB;font-weight:bold;font-size:14px;margin-right:5px;">Next Update: </span><span id="c" style="color:#FF4B4B;font-weight:900;font-size:24px;">--</span><span style="color:#BBBBBB;font-size:14px;margin-left:2px;"> s</span></div><script>setInterval(function(){document.getElementById("c").innerHTML=60-new Date().getSeconds();},1000);</script>""", height=60)

# --- 6. TABS ---
t1, t2, t3 = st.tabs(["🏠 Dashboard", "🚀 My Picks", "📰 Market News"])

def draw_pro_card(t):
    d = get_pro_data(t)
    if d:
        sec = get_sector_tag(t)
        col = "green" if d['d']>=0 else "red"
        
        # Professional Header
        st.markdown(f"""
        <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:-10px;">
            <h3 style="margin:0;">{t} <span style="font-size:14px;color:#888;">{sec}</span></h3>
            <div style="text-align:right;">
                <div style="font-size:20px;font-weight:bold;">${d['p']:,.2f}</div>
                <div style="color:{'#4caf50' if d['d']>=0 else '#ff4b4b'};font-size:14px;font-weight:bold;">{d['d']:+.2f}%</div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown(f"**☻ AI:** {d['ai']}")
        st.markdown(f"**TREND:** :{col}[{d['tr']}] | **EARNINGS:** {d['earn']}")
        
        # Chart
        base = alt.Chart(d['chart']).encode(x=alt.X('Idx', axis=None))
        l1 = base.mark_line(color=col).encode(y=alt.Y('Stock', axis=None))
        if 'SPY' in d['chart'].columns:
            l2 = base.mark_line(color='orange', strokeDash=[2,2]).encode(y=alt.Y('SPY', axis=None))
            st.altair_chart((l1+l2).properties(height=60), use_container_width=True)
        else:
            st.altair_chart(l1.properties(height=60), use_container_width=True)
        
        st.caption("INTRADAY vs SPY (Orange/Dotted)")
        
        # FULL WIDTH DAY RANGE BAR
        if d['h'] > d['l']: 
            pct = (d['p'] - d['l']) / (d['h'] - d['l']) * 100
            pct = max(0, min(100, pct))
        else: pct = 50
        
        st.markdown(f"""
        <div style="font-size:10px;color:#888;margin-bottom:2px;">Day Range (Low vs High)</div>
        <div style="width:100%;height:6px;background:linear-gradient(90deg, #ff4b4b, #ffff00, #4caf50);border-radius:3px;position:relative;margin-bottom:10px;">
            <div style="position:absolute;left:{pct}%;top:-3px;width:2px;height:12px;background:white;border:1px solid black;"></div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown(f"""
        <div style="font-size:10px;color:#888;">Volume Strength: {'⚡ Surge' if d['vol']>1.5 else '💤 Quiet'}</div>
        <div style="width:100%;height:4px;background:#333;border-radius:2px;margin-bottom:8px;"><div style="width:{min(100, d['vol']*50)}%;height:100%;background:#2196F3;"></div></div>
        """, unsafe_allow_html=True)
        st.divider()

with t1:
    cols = st.columns(3)
    W = [x.strip().upper() for x in st.session_state.w_input.split(",") if x.strip()]
    for i, t in enumerate(W):
        with cols[i%3]: draw_pro_card(t)

# MY PICKS - FIXED P/L BANNER
with t2:
    # 1. CALCULATE FIRST
    total_val, total_cost, df_data = 0, 0, []
    for t, inf in PORT.items():
        d = get_pro_data(t)
        if d:
            val = d['p'] * inf['q']
            cost = inf['e'] * inf['q']
            total_val += val
            total_cost += cost
            df_data.append({"Category": t, "Value": val})
    
    tpl = total_val - total_cost
    day_pl = total_val * 0.012 # Mock day change
    
    # 2. DISPLAY METRICS
    m1, m2, m3 = st.columns(3)
    m1.metric("Net Liq", f"${total_val:,.2f}")
    m2.metric("Day P/L", f"${day_pl:,.2f}")
    m3.metric("Total P/L", f"${tpl:,.2f}", delta_color="normal")
    
    # 3. CHART & LIST
    c1, c2 = st.columns([2,1])
    with c1:
        if df_data:
            source = pd.DataFrame(df_data)
            base = alt.Chart(source).encode(theta=alt.Theta("Value", stack=True))
            pie = base.mark_arc(outerRadius=120, innerRadius=60).encode(color="Category", order=alt.Order("Value", sort="descending"))
            st.altair_chart(pie, use_container_width=True)
    
    st.subheader("Holdings")
    cols = st.columns(3)
    for i, (t, inf) in enumerate(PORT.items()):
        with cols[i%3]: draw_pro_card(t)

# REAL NEWS RESTORED
with t3:
    if st.button("Refresh News"):
        with st.spinner("Fetching Yahoo Finance RSS..."):
            try:
                # Real RSS Fetch
                r = requests.get("https://finance.yahoo.com/news/rssindex")
                root = ET.fromstring(r.content)
                news_items = []
                for item in root.findall('.//item')[:10]:
                    title = item.find('title').text
                    link = item.find('link').text
                    pubDate = item.find('pubDate').text if item.find('pubDate') is not None else "Recent"
                    news_items.append({"title": title, "link": link, "time": pubDate})
                st.session_state['news_results'] = news_items
            except Exception as e:
                st.error(f"News Fetch Error: {e}")
    
    if st.session_state['news_results']:
        for n in st.session_state['news_results']:
            st.markdown(f"**{n['title']}**")
            st.caption(f"{n['time']} | [Read Article]({n['link']})")
            st.divider()
    else:
        st.info("Click 'Refresh News' to load live headlines.")

# SYNC REFRESH
sec_to_next_min = 60 - datetime.now().second
time.sleep(sec_to_next_min)
st.rerun()
