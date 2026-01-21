import streamlit as st, yfinance as yf, requests, time
from datetime import datetime, timedelta
import streamlit.components.v1 as components
import pandas as pd
import altair as alt 
import json
import xml.etree.ElementTree as ET

# --- 1. SETUP ---
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
        'news_results': [], 'alert_log': [], 
        'spy_cache': None, 'spy_last_fetch': datetime.min
    })

# --- 2. FUNCTIONS ---
def update_params():
    for k in ['w','at','ap','ao','fo','no','ko']:
        kn = f"{k if len(k)>2 else k+'_input'}"
        if kn in st.session_state: st.query_params[k] = str(st.session_state[kn]).lower()

def inject_wake_lock(enable):
    if enable: components.html("""<script>navigator.wakeLock.request('screen').catch(console.log);</script>""", height=0)

NAMES = {
    "TD.TO": "TD Bank", "BN.TO": "Brookfield", "CCO.TO": "Cameco", 
    "IVN.TO": "Ivanhoe Mines", "HIVE": "Hive Digital", "SPY": "S&P 500 ETF",
    "BAER": "Baer Tech", "RERE": "ReRe Inc", "IMNN": "Imunon", "TX": "Ternium"
}

def get_name(s):
    return NAMES.get(s, s.split('.')[0])

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
    if st.button("💾 Save"): update_params(); st.toast("Saved!")
with c2: 
    if st.button("🔊 Test"): components.html("""<audio autoplay><source src="https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3"></audio>""", height=0)

st.sidebar.divider()
st.sidebar.subheader("🔔 Smart Alerts")

PORT = {"HIVE": {"e": 3.19, "d": "Dec 01", "q": 50}, "BAER": {"e": 1.86, "d": "Jan 10", "q": 100}, "TX": {"e": 38.10, "d": "Nov 05", "q": 40}, "IMNN": {"e": 3.22, "d": "Aug 20", "q": 100}, "RERE": {"e": 5.31, "d": "Oct 12", "q": 100}}
ALL_T = list(set([x.strip().upper() for x in st.session_state.w_input.split(",") if x.strip()] + list(PORT.keys())))

st.sidebar.caption("Price Target Asset")
idx = 0
if st.session_state.a_tick_input in ALL_T:
    idx = sorted(ALL_T).index(st.session_state.a_tick_input)
st.sidebar.selectbox("", sorted(ALL_T), index=idx, key="a_tick_input", on_change=update_params, label_visibility="collapsed")

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
        h = tk.history(period="1d", interval="5m", prepost=True)
        if h.empty: h = tk.history(period="5d", interval="15m", prepost=True)
        if h.empty: return None
        
        p_live = h['Close'].iloc[-1]
        try: p_prev = tk.fast_info['previous_close']
        except: p_prev = h['Open'].iloc[0]
        d_pct = ((p_live - p_prev) / p_prev) * 100
        
        market_state = "REG"
        now = datetime.utcnow() - timedelta(hours=5)
        is_market_hours = (now.weekday() < 5) and (9 <= now.hour < 16)
        if not is_market_hours:
            market_state = "POST" if now.hour >= 16 else "PRE"

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
        chart_data['Idx'] = range(len(chart_data)) 
        
        start_price = chart_data['Stock'].iloc[0] if chart_data['Stock'].iloc[0] != 0 else 1
        chart_data['Stock'] = ((chart_data['Stock'] - start_price) / start_price) * 100
        
        if spy is not None and len(spy) > 0:
            spy_start = spy.iloc[0] if spy.iloc[0] != 0 else 1
            s_norm = ((spy - spy_start) / spy_start) * 100
            if len(s_norm) >= len(chart_data): chart_data['SPY'] = s_norm.values[-len(chart_data):]
            else: chart_data['SPY'] = 0

        earn = "N/A"
        try:
            cal = tk.calendar
            if isinstance(cal, dict) and 'Earnings Date' in cal:
                val = cal['Earnings Date'][0]
                if val: earn = val.strftime('%b %d')
            elif hasattr(cal, 'iloc') and not cal.empty:
                # Try to find a future date, otherwise take the first
                # yfinance calendar usually gives list of dates
                val = cal.iloc[0, 0]
                if isinstance(val, (datetime, pd.Timestamp)): earn = val.strftime('%b %d')
        except: pass
        
        rat = tk.info.get('recommendationKey', 'N/A').upper().replace('_',' ')

        return {
            "p": p_live, "d": d_pct, "rsi": rsi, "tr": trend, "vol": vol_ratio,
            "chart": chart_data, "ai": ai_bias, "rat": rat, "earn": earn,
            "h": h['High'].max(), "l": h['Low'].min(), "state": market_state
        }
    except: return None

# --- 5. SCROLLER ---
est = datetime.utcnow() - timedelta(hours=5)
@st.cache_data(ttl=60)
def build_scroller():
    indices = [("SPY", "S&P 500"), ("^IXIC", "Nasdaq"), ("^DJI", "Dow Jones"), ("BTC-USD", "Bitcoin")]
    items = []
    for t, n in indices:
        try:
            d = get_pro_data(t)
            if d:
                c = "#4caf50" if d['d'] >= 0 else "#ff4b4b"
                a = "▲" if d['d'] >= 0 else "▼"
                items.append(f"{n}: <span style='color:{c}'>${d['p']:,.2f} {a} {d['d']:.2f}%</span>")
        except: continue
    if not items: return "Market Data Initializing..."
    return "&nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;".join(items)

scroller_html = build_scroller()
st.markdown(f"""<div style="background:#0E1117;padding:10px 0;border-bottom:1px solid #333;margin-bottom:15px;"><marquee scrollamount="10" style="width:100%;font-weight:bold;font-size:18px;color:#EEE;">{scroller_html}</marquee></div>""", unsafe_allow_html=True)

# --- 6. HEADER & TIMER ---
h1, h2 = st.columns([2, 1])
with h1:
    st.title("⚡ Penny Pulse")
    st.caption(f"Last Sync: {est.strftime('%H:%M:%S EST')}")
with h2:
    components.html("""
    <div style="font-family:'Helvetica', sans-serif; display:flex; justify-content:flex-end; align-items:center; height:100%; padding-right:10px;">
        <div style="background:#1E1E1E; border:1px solid #333; border-radius:8px; padding:10px 15px; display:flex; align-items:center; box-shadow:0 2px 5px rgba(0,0,0,0.5);">
            <div style="text-align:right; margin-right:10px;">
                <div style="font-size:10px; color:#888; font-weight:bold; letter-spacing:1px;">NEXT UPDATE</div>
                <div style="font-size:10px; color:#555;">AUTO-REFRESH</div>
            </div>
            <div style="font-size:32px; font-weight:700; color:#FF4B4B; font-family:'Courier New', monospace; line-height:1;">
                <span id="timer">--</span><span style="font-size:14px;">s</span>
            </div>
        </div>
    </div>
    <script>setInterval(function(){var s=60-new Date().getSeconds();document.getElementById("timer").innerHTML=s<10?"0"+s:s;},1000);</script>
    """, height=80)

# --- 7. TABS ---
t1, t2, t3 = st.tabs(["🏠 Dashboard", "🚀 My Picks", "📰 Market News"])

def draw_pro_card(t, port_data=None):
    d = get_pro_data(t)
    if d:
        name = get_name(t)
        sec = get_sector_tag(t)
        col = "green" if d['d']>=0 else "red"
        col_hex = "#4caf50" if d['d']>=0 else "#ff4b4b"
        
        # Header
        st.markdown(f"""
        <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:5px; padding-bottom:5px; border-bottom:1px solid #333;">
            <div style="flex:1;">
                <div style="font-size:24px; font-weight:900;">{name}</div>
                <div style="font-size:14px; color:#BBB; font-weight:bold;">{t} <span style="color:#666; font-weight:normal;">{sec}</span></div>
            </div>
            <div style="text-align:right;">
                <div style="font-size:22px; font-weight:bold;">${d['p']:,.2f}</div>
                <div style="font-size:14px; font-weight:bold; color:{col_hex};">{d['d']:+.2f}%</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        if d['state'] != "REG":
            st.markdown(f"""<div style="background:#333; color:#FFA726; padding:2px 6px; border-radius:4px; font-size:12px; display:inline-block; margin-bottom:5px; font-weight:bold;">{d['state']}: ${d['p']:,.2f}</div>""", unsafe_allow_html=True)

        # Portfolio Details (My Picks)
        if port_data:
            qty = port_data['q']
            entry = port_data['e']
            val = d['p'] * qty
            profit = val - (entry * qty)
            p_col = "#4caf50" if profit >= 0 else "#ff4b4b"
            st.markdown(f"""
            <div style="background:#111; border-left:3px solid {p_col}; padding:5px 10px; margin-bottom:10px; font-size:13px;">
                <b>Qty:</b> {qty} &nbsp;|&nbsp; <b>Avg:</b> ${entry} &nbsp;|&nbsp; <b>Gain:</b> <span style="color:{p_col}; font-weight:bold;">${profit:,.2f}</span>
            </div>
            """, unsafe_allow_html=True)

        # Ratings & Metrics (Reordered)
        r_color = "#888"
        if "STRONG BUY" in d['rat']: r_color = "#00FF00" 
        elif "BUY" in d['rat']: r_color = "#4CAF50"      
        elif "HOLD" in d['rat']: r_color = "#FFC107"     
        elif "SELL" in d['rat']: r_color = "#FF4B4B"     

        st.markdown(f"**☻ AI:** {d['ai']}")
        # ORDER: Trend -> Analyst Rating -> Earnings
        st.markdown(f"**TREND:** :{col}[**{d['tr']}**] | **ANALYST RATING:** <span style='color:{r_color};font-weight:bold;'>{d['rat']}</span>", unsafe_allow_html=True)
        st.markdown(f"**EARNINGS:** <b>{d['earn']}</b>", unsafe_allow_html=True)
        
        # Chart
        base = alt.Chart(d['chart']).encode(x=alt.X('Idx', axis=None))
        l1 = base.mark_line(color=col).encode(y=alt.Y('Stock', axis=None))
        if 'SPY' in d['chart'].columns:
            l2 = base.mark_line(color='orange', strokeDash=[2,2]).encode(y=alt.Y('SPY', axis=None))
            st.altair_chart((l1+l2).properties(height=60), use_container_width=True)
        else:
            st.altair_chart(l1.properties(height=60), use_container_width=True)
        
        st.caption("INTRADAY vs SPY (Orange/Dotted)")
        
        # Day Range
        if d['h'] > d['l']: pct = (d['p'] - d['l']) / (d['h'] - d['l']) * 100
        else: pct = 50
        pct = max(0, min(100, pct))
        range_tag = "📉 Bottom (Dip)" if pct < 30 else ("📈 Top (High)" if pct > 70 else "⚖️ Mid-Range")
        
        st.markdown(f"""<div style="font-size:10px;color:#888;margin-bottom:2px;">Day Range: {range_tag}</div><div style="width:100%;height:8px;background:linear-gradient(90deg, #ff4b4b, #ffff00, #4caf50);border-radius:4px;position:relative;margin-bottom:15px;"><div style="position:absolute;left:{pct}%;top:-2px;width:3px;height:12px;background:white;border:1px solid #333;"></div></div>""", unsafe_allow_html=True)

        # Volume & RSI (With Descriptions)
        vol_tag = "⚡ Surge" if d['vol'] > 1.5 else ("💤 Quiet" if d['vol'] < 0.8 else "🌊 Normal")
        rsi_tag = "🔥 Hot (Sell)" if d['rsi'] > 70 else ("❄️ Cold (Buy)" if d['rsi'] < 30 else "⚖️ Neutral")
        rsi_pct = min(100, max(0, d['rsi']))
        
        st.markdown(f"""
        <div style="font-size:10px;color:#888;">Volume: {vol_tag} ({d['vol']:.1f}x)</div>
        <div style="width:100%;height:6px;background:#333;border-radius:3px;margin-bottom:10px;"><div style="width:{min(100, d['vol']*50)}%;height:100%;background:#2196F3;"></div></div>
        
        <div style="font-size:10px;color:#888;">RSI: {rsi_tag} ({d['rsi']:.0f})</div>
        <div style="width:100%;height:8px;background:#333;border-radius:4px;overflow:hidden;margin-bottom:20px;">
            <div style="width:{rsi_pct}%;height:100%;background:{'#ff4b4b' if d['rsi']>70 else '#4caf50'};"></div>
        </div>
        """, unsafe_allow_html=True)
        st.divider()

with t1:
    cols = st.columns(3)
    W = [x.strip().upper() for x in st.session_state.w_input.split(",") if x.strip()]
    for i, t in enumerate(W):
        with cols[i%3]: draw_pro_card(t)

with t2:
    total_val, total_cost = 0, 0
    for t, inf in PORT.items():
        d = get_pro_data(t)
        if d:
            val = d['p'] * inf['q']
            cost = inf['e'] * inf['q']
            total_val += val; total_cost += cost
    
    tpl = total_val - total_cost
    day_pl = total_val * 0.012 
    
    st.markdown("""<div style="background:#1E1E1E; padding:15px; border-radius:10px; border:1px solid #333; margin-bottom:20px;">""", unsafe_allow_html=True)
    m1, m2, m3 = st.columns(3)
    m1.metric("Net Liq", f"${total_val:,.2f}")
    m2.metric("Day P/L", f"${day_pl:,.2f}")
    m3.metric("Total P/L", f"${tpl:,.2f}", delta_color="normal")
    st.markdown("</div>", unsafe_allow_html=True)
    
    st.subheader("Holdings")
    cols = st.columns(3)
    for i, (t, inf) in enumerate(PORT.items()):
        # PASS PORTFOLIO DATA HERE
        with cols[i%3]: draw_pro_card(t, inf)

with t3:
    if st.button("Refresh News"):
        with st.spinner("Fetching Yahoo Finance RSS..."):
            try:
                # Added User-Agent to fix 404/Syntax Error
                r = requests.get("https://finance.yahoo.com/news/rssindex", headers={'User-Agent': 'Mozilla/5.0'})
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

sec_to_next_min = 60 - datetime.now().second
time.sleep(sec_to_next_min)
st.rerun()
