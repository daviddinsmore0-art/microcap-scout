import streamlit as st, yfinance as yf, requests, time, re, xml.etree.ElementTree as ET
from datetime import datetime
import streamlit.components.v1 as components
import pandas as pd
import altair as alt 

try: st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="wide")
except: pass 

# --- SESSION STATE ---
if 'news_results' not in st.session_state: st.session_state['news_results'] = []
if 'scanned_count' not in st.session_state: st.session_state['scanned_count'] = 0
if 'alert_triggered' not in st.session_state: st.session_state['alert_triggered'] = False
if 'last_trends' not in st.session_state: st.session_state['last_trends'] = {}
if 'mem_ratings' not in st.session_state: st.session_state['mem_ratings'] = {}
if 'mem_meta' not in st.session_state: st.session_state['mem_meta'] = {}

if 'saved_a_tick' not in st.session_state: st.session_state['saved_a_tick'] = "SPY"
if 'saved_a_price' not in st.session_state: st.session_state['saved_a_price'] = 0.0
if 'saved_a_on' not in st.session_state: st.session_state['saved_a_on'] = False
if 'saved_flip_on' not in st.session_state: st.session_state['saved_flip_on'] = False 

# --- PORTFOLIO ---
PORT = {
    "HIVE": {"e": 3.19, "d": "Dec. 01, 2024", "q": 1000},
    "BAER": {"e": 1.86, "d": "Jan. 10, 2025", "q": 500},
    "TX":   {"e": 38.10, "d": "Nov. 05, 2023", "q": 100},
    "IMNN": {"e": 3.22, "d": "Aug. 20, 2024", "q": 200},
    "RERE": {"e": 5.31, "d": "Oct. 12, 2024", "q": 300}
} 

NAMES = {
    "TSLA":"Tesla", "NVDA":"Nvidia", "BTC-USD":"Bitcoin", "AMD":"AMD", 
    "PLTR":"Palantir", "AAPL":"Apple", "SPY":"S&P 500", "^IXIC":"Nasdaq", 
    "^DJI":"Dow Jones", "GC=F":"Gold", "TD.TO":"TD Bank", "IVN.TO":"Ivanhoe", 
    "BN.TO":"Brookfield", "JNJ":"J&J", "^GSPTSE": "TSX"
} 

# --- SIDEBAR ---
st.sidebar.header("⚡ Pulse")
if "OPENAI_KEY" in st.secrets: KEY = st.secrets["OPENAI_KEY"]
else: KEY = st.sidebar.text_input("OpenAI Key (Optional)", type="password") 

# --- PERMANENT WATCHLIST ---
default_list = "SPY, BTC-USD, TD.TO, PLUG.CN, VTX.V, IVN.TO, CCO.TO, BN.TO"

qp = st.query_params
w_str = qp.get("watchlist", default_list)
u_in = st.sidebar.text_input("Add Tickers", value=w_str)
if u_in != w_str: st.query_params["watchlist"] = u_in

WATCH = [x.strip().upper() for x in u_in.split(",") if x.strip()]
ALL = list(set(WATCH + list(PORT.keys())))
st.sidebar.divider()
st.sidebar.subheader("🔔 Smart Alerts") 

# --- PERSISTENT WIDGETS ---
a_tick = st.sidebar.selectbox("Price Target Asset", sorted(ALL), key="saved_a_tick")
a_price = st.sidebar.number_input("Target ($)", step=0.5, key="saved_a_price")
a_on = st.sidebar.toggle("Active Price Alert", key="saved_a_on")
flip_on = st.sidebar.toggle("Alert on Trend Flip", key="saved_flip_on") 

# --- SECTOR & EARNINGS ---
def get_meta_data(s):
    try:
        tk = yf.Ticker(s)
        sec_raw = tk.info.get('sector', 'N/A')
        sec_map = {"Technology":"TECH", "Financial Services":"FIN", "Healthcare":"HLTH", "Consumer Cyclical":"CYCL", "Communication Services":"COMM", "Industrials":"IND", "Energy":"NRGY", "Basic Materials":"MAT", "Real Estate":"RE", "Utilities":"UTIL"}
        sector_code = sec_map.get(sec_raw, sec_raw[:4].upper()) if sec_raw != 'N/A' else ""
        earn_html = ""
        
        cal = tk.calendar
        dates = []
        if isinstance(cal, dict) and 'Earnings Date' in cal: dates = cal['Earnings Date']
        elif hasattr(cal, 'iloc') and not cal.empty: dates = [cal.iloc[0,0]]
        
        if len(dates) > 0:
            nxt = dates[0]
            if hasattr(nxt, "date"): nxt = nxt.date()
            days = (nxt - datetime.now().date()).days
            
            if 0 <= days <= 7: 
                earn_html = f"<span style='background:#550000; color:#ff4b4b; padding:1px 4px; border-radius:4px; font-size:11px; margin-left:5px;'>⚠️ {days}d</span>"
            elif 8 <= days <= 30: 
                earn_html = f"<span style='background:#333; color:#ccc; padding:1px 4px; border-radius:4px; font-size:11px; margin-left:5px;'>📅 {days}d</span>"
            elif days > 30:
                d_str = nxt.strftime("%b %d")
                earn_html = f"<span style='background:#222; color:#888; padding:1px 4px; border-radius:4px; font-size:11px; margin-left:5px;'>📅 {d_str}</span>"
        
        if sector_code or earn_html:
            st.session_state['mem_meta'][s] = (sector_code, earn_html)
        return sector_code, earn_html
        
    except:
        if s in st.session_state['mem_meta']: return st.session_state['mem_meta'][s]
        return "", "" 

# --- ANALYST RATINGS ---
def get_rating_cached(s):
    try:
        info = yf.Ticker(s).info
        rec = info.get('recommendationKey', 'none').replace('_', ' ').upper()
        res = ("N/A", "#888")
        if "STRONG BUY" in rec: res = ("🌟 STRONG BUY", "#00C805")
        elif "BUY" in rec: res = ("✅ BUY", "#4caf50")
        elif "HOLD" in rec: res = ("✋ HOLD", "#FFC107")
        elif "SELL" in rec: res = ("🔻 SELL", "#FF4B4B")
        elif "STRONG SELL" in rec: res = ("🆘 STRONG SELL", "#FF0000")
        if res[0] != "N/A": st.session_state['mem_ratings'][s] = res
        return res
    except:
        if s in st.session_state['mem_ratings']: return st.session_state['mem_ratings'][s]
        return "N/A", "#888"

# --- AI SIGNAL LOGIC ---
def get_ai_signal(rsi, vol_ratio, trend, price_change):
    score = 0
    if rsi >= 80: score -= 3
    elif rsi >= 70: score -= 2
    elif rsi <= 20: score += 3
    elif rsi <= 30: score += 2
    if vol_ratio > 2.0: score += 2 if price_change > 0 else -2
    elif vol_ratio > 1.2: score += 1 if price_change > 0 else -1
    if trend == "BULL": score += 1
    elif trend == "BEAR": score -= 1
    
    if score >= 3: return "🚀 RALLY LIKELY", "#00ff00"
    elif score >= 1: return "🟢 BULLISH BIAS", "#4caf50"
    elif score <= -3: return "⚠️ PULLBACK RISK", "#ff0000"
    elif score <= -1: return "🔴 BEARISH BIAS", "#ff4b4b"
    return "💤 CONSOLIDATION", "#888" 

# --- LIVE PRICE & CHART ---
@st.cache_data(ttl=60, show_spinner=False)
def get_data_cached(s):
    if not s or s == "": return None
    s = s.strip().upper()
    
    p_reg, pv, dh, dl = 0.0, 0.0, 0.0, 0.0
    p_ext = 0.0
    
    tk = yf.Ticker(s)
    is_crypto = s.endswith("-USD")
    valid_data = False
    
    if not is_crypto:
        try:
            p_reg = tk.fast_info['last_price']
            pv = tk.fast_info['previous_close']
            dh = tk.fast_info['day_high']
            dl = tk.fast_info['day_low']
            if p_reg is not None and pv is not None: 
                valid_data = True
        except: pass
    
    chart_data = None
    try:
        h = tk.history(period="1d", interval="5m", prepost=True)
        if h.empty: h = tk.history(period="5d", interval="1h", prepost=True)
        if not h.empty:
            chart_data = h['Close']
            if not valid_data or is_crypto:
                p_reg = h['Close'].iloc[-1]
                if is_crypto: pv = h['Open'].iloc[0] 
                else: pv = tk.fast_info['previous_close']
                if pd.isna(pv) or pv == 0: pv = h['Close'].iloc[0]
                dh = h['High'].max()
                dl = h['Low'].min()
                valid_data = True
            p_ext = h['Close'].iloc[-1]
    except: pass
    
    if not valid_data or pv == 0: return None
    
    try: d_reg_pct = ((p_reg - pv) / pv) * 100
    except: d_reg_pct = 0.0

    if p_ext == 0: p_ext = p_reg
    try: d_ext_pct = ((p_ext - pv) / pv) * 100
    except: d_ext_pct = 0.0

    c_ext = "green" if d_ext_pct >= 0 else "red"
    x_str = f"**Live: ${p_ext:,.2f} (:{c_ext}[{d_ext_pct:+.2f}%])**" if is_crypto else f"**🌙 Ext: ${p_ext:,.2f} (:{c_ext}[{d_ext_pct:+.2f}%])**"
    
    try: rng_pct = max(0, min(1, (p_reg - dl) / (dh - dl))) * 100 if (dh > dl) else 50
    except: rng_pct = 50
    rng_html = f"""<div style="display:flex; align-items:center; font-size:12px; color:#888; margin-top:5px; margin-bottom:2px;"><span style="margin-right:5px;">L</span><div style="flex-grow:1; height:6px; background:#333; border-radius:3px; overflow:hidden;"><div style="width:{rng_pct}%; height:100%; background: linear-gradient(90deg, #ff4b4b, #4caf50);"></div></div><span style="margin-left:5px;">H</span></div>""" 

    rsi, rl, tr, v_str, vol_tag, raw_trend, ai_txt, ai_col = 50, "Neutral", "Neutral", "N/A", "", "NEUTRAL", "N/A", "#888"
    try:
        hm = tk.history(period="1mo")
        if not hm.empty:
            cur_v = hm['Volume'].iloc[-1]
            avg_v = hm['Volume'].iloc[:-1].mean() if len(hm) > 1 else cur_v
            v_str = f"{cur_v/1e6:.1f}M" if cur_v>=1e6 else f"{cur_v:,.0f}"
            ratio = cur_v / avg_v if avg_v > 0 else 1.0
            if ratio >= 1.0: vol_tag = "⚡ SURGE"
            elif ratio >= 0.5: vol_tag = "🌊 STEADY"
            else: vol_tag = "💤 QUIET"
            
            if len(hm)>=14:
                d_diff = hm['Close'].diff()
                g, l = d_diff.where(d_diff>0,0).rolling(14).mean(), (-d_diff.where(d_diff<0,0)).rolling(14).mean()
                rsi = (100-(100/(1+(g/l)))).iloc[-1]
                rl = "🔥 HOT" if rsi >= 70 else "❄️ COLD" if rsi <= 30 else "😐 OK"
                macd = hm['Close'].ewm(span=12).mean() - hm['Close'].ewm(span=26).mean()
                if macd.iloc[-1] > 0: raw_trend = "BULL"; tr = "<span style='color:#00C805; font-weight:bold;'>BULL</span>"
                else: raw_trend = "BEAR"; tr = "<span style='color:#FF2B2B; font-weight:bold;'>BEAR</span>"
                ai_txt, ai_col = get_ai_signal(rsi, ratio, raw_trend, d_reg_pct)
    except: pass
    
    return {"p":p_reg, "d":d_reg_pct, "d_raw": (p_reg - pv), "x":x_str, "v":v_str, "vt":vol_tag, "rsi":rsi, "rl":rl, "tr":tr, "raw_trend":raw_trend, "rng_html":rng_html, "chart":chart_data, "ai_txt":ai_txt, "ai_col":ai_col} 

# --- HEADER & COUNTDOWN ---
c1, c2 = st.columns([1, 1])
with c1:
    st.title("⚡ Penny Pulse")
    st.caption(f"Last Updated: {datetime.now().strftime('%H:%M:%S')}")
with c2:
    components.html("""<div style="font-family: 'Helvetica', sans-serif; background-color: #0E1117; padding: 5px; border-radius: 5px; text-align:center; display:flex; justify-content:center; align-items:center; height:100%;"><span style="color: #BBBBBB; font-weight: bold; font-size: 14px; margin-right:5px;">Next Update: </span><span id="countdown" style="color: #FF4B4B; font-weight: 900; font-size: 18px;">--</span><span style="color: #BBBBBB; font-size: 14px; margin-left:2px;"> s</span></div><script>function startTimer(){var timer=setInterval(function(){var now=new Date();var seconds=60-now.getSeconds();var el=document.getElementById("countdown");if(el){el.innerHTML=seconds;}},1000);}startTimer();</script>""", height=60) 

# --- TICKER ---
ti = []
for t in ["SPY","^IXIC","^DJI","BTC-USD", "^GSPTSE"]:
    d = get_data_cached(t)
    if d:
        c, a = ("#4caf50","▲") if d['d']>=0 else ("#f44336","▼")
        nm = NAMES.get(t, t)
        if t.endswith(".TO"): nm += " (TSX)"
        elif t.endswith(".V"): nm += " (TSXV)"
        elif t.endswith(".CN"): nm += " (CSE)"
        ti.append(f"<span style='margin-right:30px;font-weight:900;font-size:22px;color:white;'>{nm}: <span style='color:{c};'>${d['p']:,.2f} {a} {d['d']:.2f}%</span></span>")
h = "".join(ti)
st.markdown(f"""<div style="background-color: #0E1117; padding: 10px 0; border-top: 2px solid #333; border-bottom: 2px solid #333;"><marquee scrollamount="6" style="width: 100%;">{h * 15}</marquee></div>""", unsafe_allow_html=True) 

# --- FLIP CHECK ---
def check_flip(ticker, current_trend):
    if not flip_on: return
    if ticker in st.session_state['last_trends']:
        prev = st.session_state['last_trends'][ticker]
        if prev != "NEUTRAL" and current_trend != "NEUTRAL" and prev != current_trend:
            st.toast(f"🔀 TREND FLIP: {ticker} switched to {current_trend}!", icon="⚠️")
    st.session_state['last_trends'][ticker] = current_trend 

# --- DASHBOARD LOGIC ---
def render_card(t, inf=None):
    d = get_data_cached(t)
    if d:
        check_flip(t, d['raw_trend'])
        rat_txt, rat_col = get_rating_cached(t)
        sec, earn = get_meta_data(t)
        nm = NAMES.get(t, t)
        
        if t.endswith(".TO"): nm += " (TSX)"
        elif t.endswith(".V"): nm += " (TSXV)"
        elif t.endswith(".CN"): nm += " (CSE)"
        
        sec_tag = f" <span style='color:#777; font-size:14px;'>[{sec}]</span>" if sec else ""
        url = f"https://finance.yahoo.com/quote/{t}"
        st.markdown(f"<h3 style='margin:0; padding:0;'><a href='{url}' target='_blank' style='text-decoration:none; color:inherit;'>{nm}</a>{sec_tag} <a href='{url}' target='_blank' style='text-decoration:none;'>📈</a></h3>", unsafe_allow_html=True)
        
        if inf:
            q = inf.get("q", 100)
            st.caption(f"{q} Shares @ ${inf['e']}")
            st.metric("Price", f"${d['p']:,.2f}", f"{((d['p']-inf['e'])/inf['e'])*100:.2f}% (Total)")
        else:
            st.metric("Price", f"${d['p']:,.2f}", f"{d['d']:.2f}%")
        
        st.markdown(f"<div style='margin-bottom:10px; font-weight:bold; font-size:14px;'>🤖 AI: <span style='color:{d['ai_col']};'>{d['ai_txt']}</span></div>", unsafe_allow_html=True) 
        st.markdown(d['rng_html'], unsafe_allow_html=True)
        
        rating_html = f"<br><span style='font-weight:900; color:black;'>ANALYST RATING:</span> <span style='color:{rat_col}; font-weight:bold;'>{rat_txt}</span>" if rat_txt != "N/A" else ""
        earn_display = f"<br><span style='font-weight:900; color:black;'>EARNINGS:</span> {earn}" if earn else ""
        
        meta_html = f"<div style='font-size:16px; margin-bottom:5px; line-height:1.6;'><b>Trend:</b> {d['tr']}{rating_html}{earn_display}</div>"
        st.markdown(meta_html, unsafe_allow_html=True)
        st.markdown(f"<div style='font-weight:bold; font-size:16px; margin-bottom:5px;'>Vol: {d['v']} ({d['vt']})</div>", unsafe_allow_html=True)
        st.markdown(f"<div style='font-weight:bold; font-size:16px; margin-bottom:5px;'>RSI: {d['rsi']:.0f} ({d['rl']})</div>", unsafe_allow_html=True)
        st.markdown(d['x'])
        
        with st.expander("📉 Chart"):
            if d['chart'] is not None:
                cdf = d['chart'].reset_index()
                cdf.columns = ['Time', 'Price']
                c = alt.Chart(cdf).mark_line().encode(x=alt.X('Time', axis=alt.Axis(format='%H:%M', title='')), y=alt.Y('Price', scale=alt.Scale(zero=False), title='')).properties(height=200)
                st.altair_chart(c, use_container_width=True)
            else: st.caption("Chart data unavailable")
    else: st.metric(t, "---", "0.0%")
    st.divider() 

t1, t2, t3 = st.tabs(["🏠 Dashboard", "🚀 My Picks", "📰 Market News"])
with t1:
    cols = st.columns(3)
    for i, t in enumerate(WATCH):
        with cols[i%3]: render_card(t) 

with t2:
    tot_val, day_pl, tot_pl = 0.0, 0.0, 0.0
    for t, inf in PORT.items():
        d = get_data_cached(t)
        if d:
            q = inf.get("q", 100)
            curr = d['p'] * q
            tot_val += curr
            tot_pl += (curr - (inf['e'] * q))
            day_pl += (d['d_raw'] * q)
            
    st.markdown(f"""<div style="background-color:#1e2127; padding:15px; border-radius:10px; margin-bottom:20px; border:
