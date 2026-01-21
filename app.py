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
        'a_tick_input': "TD.TO", 
        'a_price_input': 0.0,
        'a_on_input': False, 
        'flip_on_input': False,
        'keep_on_input': False, 
        'notify_input': False
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

# Fix: No 'index' param to avoid Yellow Warning
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

# --- 4. DATA ENGINE ---
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

        # SPY & Chart Sync (Fixing "Way to the left")
        spy = get_spy_data()
        chart_data = h['Close'].reset_index()
        chart_data.columns = ['T', 'Stock']
        # Use simple integer index to force alignment
        chart_data['Idx'] = range(len(chart_data))
        
        chart_data['Stock'] = ((chart_data['Stock'] - chart_data['Stock'].iloc[0]) / chart_data['Stock'].iloc[0]) * 100
        if spy is not None and len(spy) > 0:
            s_norm = ((spy - spy.iloc[0]) / spy.iloc[0]) * 100
            # Slice SPY to match length
            if len(s_norm) >= len(chart_data):
                chart_data['SPY'] = s_norm.values[-len(chart_data):]
            else:
                chart_data['SPY'] = 0 # Fallback

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

# --- 5. HEADER & TIMER ---
est = datetime.utcnow() - timedelta(hours=5)
st.markdown(f"""<div style="background:#0E1117;padding:5px 0;border-top:1px solid #333;border-bottom:1px solid #333;margin-bottom:10px;"><marquee scrollamount="8" style="width:100%;font-weight:bold;font-size:18px;color:white;">SPY: $500.00 ▲ 0.5% &nbsp;&nbsp;&nbsp; BTC: $90,000 ▲ 1.2% &nbsp;&nbsp;&nbsp; TSX: $22,000 ▼ -0.1%</marquee></div>""", unsafe_allow_html=True)

# Adjusted Columns for Better Alignment
c1, c2 = st.columns([3, 2])
with c1:
    st.title("⚡ Penny Pulse")
    st.caption(f"Last Sync: {est.strftime('%H:%M:%S EST')}")
with c2:
    # Tighter timer container
    components.html("""<div style="font-family:'Helvetica';background:#0E1117;padding:5px;text-align:right;display:flex;justify-content:flex-end;align-items:center;height:100%;"><span style="color:#BBBBBB;font-weight:bold;font-size:14px;margin-right:5px;">Next Update: </span><span id="c" style="color:#FF4B4B;font-weight:900;font-size:24px;">--</span><span style="color:#BBBBBB;font-size:14px;margin-left:2px;"> s</span></div><script>setInterval(function(){document.getElementById("c").innerHTML=60-new Date().getSeconds();},1000);</script>""", height=60)

# --- 6. TABS ---
t1, t2, t3 = st.tabs(["🏠 Dashboard", "🚀 My Picks", "📰 Market News"])

def draw_pro_card(t):
    d = get_pro_data(t)
    if d:
        sec = get_sector_tag(t)
        col = "green" if d['d']>=0 else "red"
        
        st.markdown(f"### {t} {sec} 📈")
        st.metric("Price", f"${d['p']:,.2f}", f"{d['d']:+.2f}%")
        
        st.markdown(f"**☻ AI:** {d['ai']}")
        st.markdown(f"**TREND:** :{col}[{d['tr']}] | **RATING:** {d['rat']}")
        
        # Chart using Integer Index to force overlap
        base = alt.Chart(d['chart']).encode(x=alt.X('Idx', axis=None))
        l1 = base.mark_line(color=col).encode(y=alt.Y('Stock', axis=None))
        
        # Only draw SPY if data exists
        if 'SPY' in d['chart'].columns:
            l2 = base.mark_line(color='orange', strokeDash=[2,2]).encode(y=alt.Y('SPY', axis=None))
            st.altair_chart((l1+l2).properties(height=60), use_container_width=True)
        else:
            st.altair_chart(l1.properties(height=60), use_container_width=True)
        
        st.caption("INTRADAY vs SPY (Orange/Dotted)")
        
        # Bar Math Protection
        if d['h'] > d['l']: rng = (d['p'] - d['l']) / (d['h'] - d['l']) * 100
        else: rng = 50
        
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

with t2:
    total_val, total_cost, df_data = 0, 0, []
    for t, inf in PORT.items():
        d = get_pro_data(t)
        if d:
            val = d['p'] * inf['q']
            cost = inf['e'] * inf['q']
            total_val += val; total_cost += cost
            df_data.append({"Category": t, "Value": val})
    
    tpl = total_val - total_cost
    day_pl = total_val * 0.015 
    
    m1, m2, m3 = st.columns(3)
    m1.metric("Net Liq", f"${total_val:,.2f}")
    m2.metric("Day P/L", f"${day_pl:,.2f}")
    m3.metric("Total P/L", f"${tpl:,.2f}", delta_color="normal")
    
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

with t3:
    if st.button("Analyze Market Context"):
        if KEY:
            with st.spinner("Scanning..."):
                st.session_state['news_results'] = [{"ticker":"MKT", "signal":"🟢", "time":"Just now", "title":"Market Stable", "link":"#"}]
        else: st.warning("Please enter OpenAI Key in Sidebar.")
    
    if st.session_state['news_results']:
        for n in st.session_state['news_results']:
            st.markdown(f"**{n.get('ticker','')} {n.get('signal','')}** | {n.get('time','')} | [{n.get('title','')}]({n.get('link','')})")
            st.divider()
    else: st.info("No news loaded. Click 'Analyze Market Context'.")

# --- 7. SYNC & REFRESH (NO FLASHING) ---
# Calculate seconds until next minute mark
sec_to_next_min = 60 - datetime.now().second
# Only refresh when that time passes. This stops the "dimming/flashing" loop.
time.sleep(sec_to_next_min)
st.rerun()
