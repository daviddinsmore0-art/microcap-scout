import streamlit as st, yfinance as yf, requests, time, re, xml.etree.ElementTree as ET
from datetime import datetime, timedelta
import streamlit.components.v1 as components
import pandas as pd
import altair as alt 
import json
import os

try: st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="wide")
except: pass 

# --- CONFIGURATION & PERSISTENCE ---
CONFIG_FILE = "penny_pulse_data.json"

def load_config():
    """Load settings from JSON."""
    default = {
        "w_input": "SPY, BTC-USD, TD.TO, PLUG.CN, VTX.V",
        "a_tick_input": "SPY",
        "a_price_input": 0.0,
        "a_on_input": False,
        "flip_on_input": False,
        "notify_input": False
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                saved = json.load(f)
                default.update(saved)
        except Exception as e:
            st.error(f"Error loading config: {e}")
    return default

def save_config():
    """Dump current Session State to JSON with Error Reporting."""
    config = {
        "w_input": st.session_state.get("w_input"),
        "a_tick_input": st.session_state.get("a_tick_input"),
        "a_price_input": st.session_state.get("a_price_input"),
        "a_on_input": st.session_state.get("a_on_input"),
        "flip_on_input": st.session_state.get("flip_on_input"),
        "notify_input": st.session_state.get("notify_input")
    }
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f)
    except Exception as e:
        st.sidebar.error(f"❌ SAVE FAILED: {e}")

# --- INITIALIZATION (STRICT LOAD) ---
if 'initialized' not in st.session_state:
    user_conf = load_config()
    # Force load into session state
    for key, val in user_conf.items():
        st.session_state[key] = val
    st.session_state['initialized'] = True

# --- SESSION STATE SETUP ---
if 'news_results' not in st.session_state: st.session_state['news_results'] = []
if 'scanned_count' not in st.session_state: st.session_state['scanned_count'] = 0
if 'market_mood' not in st.session_state: st.session_state['market_mood'] = None 
if 'alert_triggered' not in st.session_state: st.session_state['alert_triggered'] = False
if 'alert_log' not in st.session_state: st.session_state['alert_log'] = [] 
if 'last_trends' not in st.session_state: st.session_state['last_trends'] = {}
if 'mem_ratings' not in st.session_state: st.session_state['mem_ratings'] = {}
if 'mem_meta' not in st.session_state: st.session_state['mem_meta'] = {}
if 'spy_cache' not in st.session_state: st.session_state['spy_cache'] = None
if 'spy_last_fetch' not in st.session_state: st.session_state['spy_last_fetch'] = datetime.min
if 'banner_msg' not in st.session_state: st.session_state['banner_msg'] = None

PORT = {
    "HIVE": {"e": 3.19, "d": "Dec. 01, 2024", "q": 100},
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

# --- AUDIO SYSTEM ---
def play_alert_sound():
    sound_html = """
    <audio autoplay>
    <source src="https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3" type="audio/mpeg">
    </audio>
    """
    components.html(sound_html, height=0, width=0)

# --- SIDEBAR ---
st.sidebar.header("⚡ Pulse")
if "OPENAI_KEY" in st.secrets: KEY = st.secrets["OPENAI_KEY"]
else: KEY = st.sidebar.text_input("OpenAI Key (Optional)", type="password") 

# --- WATCHLIST INPUT (PERSISTENT) ---
# Check if key exists, if not initialize it (double safety)
if 'w_input' not in st.session_state: st.session_state['w_input'] = "SPY"

# The Widget
st.sidebar.text_input("Add Tickers", key="w_input", on_change=save_config)

# Processing
raw_w = st.session_state.get('w_input', "")
WATCH = [x.strip().upper() for x in raw_w.split(",") if x.strip()]
ALL = list(set(WATCH + list(PORT.keys())))

# --- SIDEBAR BUTTONS ---
c1, c2 = st.sidebar.columns(2)
with c1:
    if st.button("💾 Save"):
        save_config()
        st.toast("Saved!", icon="💾")
with c2:
    if st.button("🔊 Test"):
        play_alert_sound()
        st.toast("Audio Armed!", icon="🔊")

st.sidebar.divider()
st.sidebar.subheader("🔔 Smart Alerts") 

# --- RESET BUTTON (THE NUCLEAR FIX) ---
if st.sidebar.button("⚠ Factory Reset"):
    if os.path.exists(CONFIG_FILE):
        os.remove(CONFIG_FILE)
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()

def send_notification(title, body):
    js_code = f"""
    <script>
    function notify() {{
        if (!("Notification" in window)) {{ console.log("No support"); }} 
        else if (Notification.permission === "granted") {{ new Notification("{title}", {{ body: "{body}" }}); }} 
        else if (Notification.permission !== "denied") {{
            Notification.requestPermission().then(function (permission) {{
                if (permission === "granted") {{ new Notification("{title}", {{ body: "{body}" }}); }}
            }});
        }}
    }}
    notify();
    </script>
    """
    components.html(js_code, height=0, width=0)

def log_alert(msg, title="Penny Pulse Alert"):
    t_stamp = (datetime.utcnow() - timedelta(hours=5)).strftime('%H:%M')
    st.session_state['alert_log'].insert(0, f"[{t_stamp}] {msg}")
    play_alert_sound()
    st.session_state['banner_msg'] = f"🚨 {msg.upper()} 🚨"
    if st.session_state.get("notify_input", False):
        send_notification(title, msg)

# --- ALERT WIDGETS ---
# Validation
current_choice = st.session_state.get('a_tick_input')
if current_choice not in ALL:
    if ALL: st.session_state['a_tick_input'] = sorted(ALL)[0]

st.sidebar.selectbox("Price Target Asset", sorted(ALL), key="a_tick_input", on_change=save_config)
st.sidebar.number_input("Target ($)", step=0.5, key="a_price_input", on_change=save_config)
st.sidebar.toggle("Active Price Alert", key="a_on_input", on_change=save_config)
st.sidebar.toggle("Alert on Trend Flip", key="flip_on_input", on_change=save_config) 
st.sidebar.checkbox("Desktop Notifications", key="notify_input", on_change=save_config, help="Works on Desktop/HTTPS only.")

a_tick = st.session_state['a_tick_input']
a_price = st.session_state['a_price_input']
a_on = st.session_state['a_on_input']
flip_on = st.session_state['flip_on_input']

if st.session_state['alert_log']:
    st.sidebar.divider()
    st.sidebar.markdown("**📜 Recent Alerts**")
    for msg in st.session_state['alert_log'][:5]: 
        st.sidebar.caption(msg)
    if st.sidebar.button("Clear Log"):
        st.session_state['alert_log'] = []
        st.rerun()

# --- SPY BENCHMARK FETCH (RAW) ---
def get_spy_benchmark():
    now = datetime.now()
    if st.session_state['spy_cache'] is not None:
        if (now - st.session_state['spy_last_fetch']).seconds < 60:
            return st.session_state['spy_cache']
    try:
        spy = yf.Ticker("SPY")
        h = spy.history(period="1d", interval="5m", prepost=True)
        if not h.empty:
            data = h[['Close']]
            st.session_state['spy_cache'] = data
            st.session_state['spy_last_fetch'] = now
            return data
    except: pass
    return None

# --- METADATA ---
def get_meta_data(s):
    if s in st.session_state['mem_meta']: return st.session_state['mem_meta'][s]
    try:
        tk = yf.Ticker(s)
        sec_raw = tk.info.get('sector', 'N/A')
        sec_map = {"Technology":"TECH", "Financial Services":"FIN", "Healthcare":"HLTH", "Consumer Cyclical":"CYCL", "Communication Services":"COMM", "Industrials":"IND", "Energy":"NRGY", "Basic Materials":"MAT", "Real Estate":"RE", "Utilities":"UTIL"}
        sector_code = sec_map.get(sec_raw, sec_raw[:4].upper()) if sec_raw != 'N/A' else ""
        earn_html = "N/A"
        cal = tk.calendar
        dates = []
        if isinstance(cal, dict) and 'Earnings Date' in cal: dates = cal['Earnings Date']
        elif hasattr(cal, 'iloc') and not cal.empty: dates = [cal.iloc[0,0]]
        if len(dates) > 0:
            nxt = dates[0]
            if hasattr(nxt, "date"): nxt = nxt.date()
            days = (nxt - datetime.now().date()).days
            if 0 <= days <= 7: earn_html = f"<span style='background:#550000; color:#ff4b4b; padding:1px 4px; border-radius:4px; font-size:11px;'>⚠️ {days}d</span>"
            elif 8 <= days <= 30: earn_html = f"<span style='background:#333; color:#ccc; padding:1px 4px; border-radius:4px; font-size:11px;'>📅 {days}d</span>"
            elif days > 30: earn_html = f"<span style='background:#222; color:#888; padding:1px 4px; border-radius:4px; font-size:11px;'>📅 {nxt.strftime('%b %d')}</span>"
        res = (sector_code, earn_html)
        st.session_state['mem_meta'][s] = res
        return res
    except: return "", "N/A" 

def get_rating_cached(s):
    if s in st.session_state['mem_ratings']: return st.session_state['mem_ratings'][s]
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
    except: return "N/A", "#888"

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
            if p_reg is not None and pv is not None: valid_data = True
        except: pass
    
    chart_data = None
    golden_cross_html = ""
    try:
        h = tk.history(period="1d", interval="5m", prepost=True)
        if h.empty: h = tk.history(period="5d", interval="1h", prepost=True)
        if not h.empty:
            chart_data = h # Keep raw data frame with Index
            if not valid_data or is_crypto:
                p_reg = h['Close'].iloc[-1]
                if is_crypto: pv = h['Open'].iloc[0] 
                else: pv = tk.fast_info['previous_close']
                if pd.isna(pv) or pv == 0: pv = h['Close'].iloc[0]
                dh = h['High'].max()
                dl = h['Low'].min()
                valid_data = True
            p_ext = h['Close'].iloc[-1]
            try:
                hist_long = tk.history(period="1y", interval="1d")
                if len(hist_long) > 200:
                    ma50 = hist_long['Close'].rolling(window=50).mean().iloc[-1]
                    ma200 = hist_long['Close'].rolling(window=200).mean().iloc[-1]
                    if ma50 > ma200: golden_cross_html = " <span style='background:#FFD700; color:black; padding:1px 4px; border-radius:4px; font-size:11px; margin-left:5px; font-weight:bold;'>🌟 GOLDEN CROSS</span>"
            except: pass
    except: pass
    
    if not valid_data or pv == 0: return None
    try: d_reg_pct = ((p_reg - pv) / pv) * 100
    except: d_reg_pct = 0.0
    if p_ext == 0: p_ext = p_reg
    try: d_ext_pct = ((p_ext - pv) / pv) * 100
    except: d_ext_pct = 0.0

    c_hex = "#4caf50" if d_ext_pct >= 0 else "#ff4b4b"
    lbl = "⚡ LIVE"
    x_str = f"<b>{lbl}: ${p_ext:,.2f} <span style='color:{c_hex};'>({d_ext_pct:+.2f}%)</span></b>"
    
    rng_pct = 50; rng_rate = "⚖️ Average"
    if dh > dl:
        raw_pct = (p_reg - dl) / (dh - dl); rng_pct = max(0, min(1, raw_pct)) * 100
        if raw_pct >= 0.9: rng_rate = "🚀 Top (Peak)"
        elif raw_pct >= 0.7: rng_rate = "📈 Near Highs"
        elif raw_pct <= 0.1: rng_rate = "📉 Bottom (Dip)"
        elif raw_pct <= 0.3: rng_rate = "📉 Near Lows"
        else: rng_rate = "⚖️ Mid-Range"
    rng_html = f"""<div style="font-size:11px; color:#666; margin-top:5px;">Day Range: <b>{rng_rate}</b></div><div style="display:flex; align-items:center; font-size:10px; color:#888; margin-top:2px;"><span style="margin-right:4px;">L</span><div style="flex-grow:1; height:4px; background:#333; border-radius:2px; overflow:hidden;"><div style="width:{rng_pct}%; height:100%; background: linear-gradient(90deg, #ff4b4b, #4caf50);"></div></div><span style="margin-left:4px;">H</span></div>""" 

    rsi, rl, tr, v_str, vol_tag, raw_trend, ai_txt, ai_col = 50, "Neutral", "Neutral", "N/A", "", "NEUTRAL", "N/A", "#888"
    rsi_html, vol_html = "", ""
    try:
        hm = tk.history(period="1mo")
        if not hm.empty:
            cur_v = hm['Volume'].iloc[-1]; avg_v = hm['Volume'].iloc[:-1].mean() if len(hm) > 1 else cur_v
            v_str = f"{cur_v/1e6:.1f}M" if cur_v>=1e6 else f"{cur_v:,.0f}"
            ratio = cur_v / avg_v if avg_v > 0 else 1.0
            if ratio >= 1.0: vol_tag = "⚡ Surge"
            elif ratio >= 0.5: vol_tag = "🌊 Steady"
            else: vol_tag = "💤 Quiet"
            vol_pct = min(100, (ratio / 2.0) * 100)
            vol_color = "#2196F3" if ratio > 1.0 else "#555"
            vol_html = f"""<div style="font-size:11px; color:#666; margin-top:8px;">Volume Strength: <b>{vol_tag}</b></div><div style="width:100%; height:6px; background:#333; border-radius:3px; margin-top:2px;"><div style="width:{vol_pct}%; height:100%; background:{vol_color}; border-radius:3px;"></div></div>"""
            if len(hm)>=14:
                d_diff = hm['Close'].diff()
                g, l = d_diff.where(d_diff>0,0).rolling(14).mean(), (-d_diff.where(d_diff<0,0)).rolling(14).mean()
                rsi = (100-(100/(1+(g/l)))).iloc[-1]
                rsi_color = "#4caf50" 
                if rsi >= 70: rsi_color = "#ff4b4b"; rl = "Hot (Overbought)"
                elif rsi <= 30: rsi_color = "#ff4b4b"; rl = "Cold (Oversold)"
                else: rl = "Neutral (Safe)"
                rsi_html = f"""<div style="font-size:11px; color:#666; margin-top:8px;">RSI Momentum: <b>{rl}</b></div><div style="width:100%; height:6px; background:#333; border-radius:3px; margin-top:2px;"><div style="width:{rsi}%; height:100%; background:{rsi_color}; border-radius:3px;"></div></div>"""
                macd = hm['Close'].ewm(span=12).mean() - hm['Close'].ewm(span=26).mean()
                if macd.iloc[-1] > 0: raw_trend = "BULL"; tr = "<span style='color:#00C805; font-weight:bold;'>BULL</span>"
                else: raw_trend = "BEAR"; tr = "<span style='color:#FF2B2B; font-weight:bold;'>BEAR</span>"
                ai_txt, ai_col = get_ai_signal(rsi, ratio, raw_trend, d_reg_pct)
    except: pass
    return {"p":p_reg, "d":d_reg_pct, "d_raw": (p_reg - pv), "x":x_str, "v":v_str, "vt":vol_tag, "rsi":rsi, "rl":rl, "tr":tr, "raw_trend":raw_trend, "rng_html":rng_html, "vol_html":vol_html, "rsi_html":rsi_html, "chart":chart_data, "ai_txt":ai_txt, "ai_col":ai_col, "gc":golden_cross_html} 

# --- VISUAL ALARM BANNER ---
if st.session_state['banner_msg']:
    st.markdown(f"""
    <div style="
        background-color: #ff4b4b; 
        color: white; 
        padding: 15px; 
        text-align: center; 
        font-size: 20px; 
        font-weight: bold; 
        position: fixed; 
        top: 50px; 
        left: 0; 
        width: 100%; 
        z-index: 9999;
        box-shadow: 0px 4px 6px rgba(0,0,0,0.3);
        animation: pulse 1.5s infinite;
    ">
    {st.session_state['banner_msg']}
    </div>
    <style>
    @keyframes pulse {{
        0% {{ opacity: 1; }}
        50% {{ opacity: 0.7; }}
        100% {{ opacity: 1; }}
    }}
    </style>
    """, unsafe_allow_html=True)
    if st.button("❌ Dismiss Alarm"):
        st.session_state['banner_msg'] = None
        st.rerun()

# --- HEADER ---
est_now = datetime.utcnow() - timedelta(hours=5)
c1, c2 = st.columns([1, 1])
with c1:
    st.title("⚡ Penny Pulse")
    st.caption(f"Last Updated: {est_now.strftime('%H:%M:%S EST')}")
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

# --- FLIP CHECK & NOTIFICATION TRIGGER ---
def check_flip(ticker, current_trend):
    if not flip_on: return
    if ticker in st.session_state['last_trends']:
        prev = st.session_state['last_trends'][ticker]
        if prev != "NEUTRAL" and current_trend != "NEUTRAL" and prev != current_trend:
            msg = f"{ticker} flipped to {current_trend}"
            st.toast(msg, icon="⚠️")
            log_alert(msg, title="Trend Flip Alert")
    st.session_state['last_trends'][ticker] = current_trend 

# --- DASHBOARD LOGIC (SMART CHART MERGE) ---
def render_card(t, inf=None):
    d = get_data_cached(t)
    spy_data = get_spy_benchmark()
    
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
        
        st.markdown(f"<div style='margin-top:-10px; margin-bottom:10px;'>{d['x']}</div>", unsafe_allow_html=True) 
        st.markdown(f"<div style='margin-bottom:10px; font-weight:bold; font-size:14px;'>🤖 AI: <span style='color:{d['ai_col']};'>{d['ai_txt']}</span></div>", unsafe_allow_html=True) 
        
        meta_html = f"""
        <div style='font-size:14px; line-height:1.8; margin-bottom:10px; color:#444;'>
            <div><b style='color:black; margin-right:8px;'>TREND:</b> {d['tr']}{d['gc']}</div>
            <div><b style='color:black; margin-right:8px;'>ANALYST RATING:</b> <span style='color:{rat_col}; font-weight:bold;'>{rat_txt}</span></div>
            <div><b style='color:black; margin-right:8px;'>EARNINGS:</b> {earn}</div>
        </div>
        """
        st.markdown(meta_html, unsafe_allow_html=True)

        st.markdown("<div style='font-size:11px; font-weight:bold; color:#555; margin-bottom:2px;'>INTRADAY vs SPY (Orange/Dotted)</div>", unsafe_allow_html=True)
        
        # --- SMART CHART MERGING LOGIC ---
        if d['chart'] is not None and not d['chart'].empty:
            # 1. Get Stock Data
            stock_series = d['chart']['Close'].tail(30)
            
            if len(stock_series) > 1:
                # Normalize Stock to start at 0
                start_p = stock_series.iloc[0]
                stock_norm = ((stock_series - start_p) / start_p) * 100
                
                # Create DataFrame with 'Time' from Index
                plot_df = pd.DataFrame({'Stock': stock_norm})
                plot_df = plot_df.reset_index().rename(columns={plot_df.index.name: 'Time'})
                
                # 2. Try to Align SPY
                has_spy = False
                if spy_data is not None and not spy_data.empty:
                    try:
                        # Reindex SPY to match Stock timestamps exactly (nearest match within 10 min)
                        spy_aligned = spy_data.reindex(stock_series.index, method='nearest', tolerance=timedelta(minutes=10))
                        
                        if not spy_aligned['Close'].isnull().all():
                            spy_vals = spy_aligned['Close']
                            # We must re-normalize SPY to start at 0 RELATIVE TO THIS WINDOW
                            valid_spy = spy_vals.dropna()
                            if not valid_spy.empty:
                                spy_start = valid_spy.iloc[0]
                                plot_df['SPY'] = ((spy_vals.values - spy_start) / spy_start) * 100
                                has_spy = True
                    except: pass

                # 3. Plotting
                line_color = "#4caf50" if d['d'] >= 0 else "#ff4b4b"
                base = alt.Chart(plot_df).encode(x=alt.X('Time', axis=None))
                
                l_stock = base.mark_line(color=line_color, strokeWidth=2).encode(y=alt.Y('Stock', scale=alt.Scale(zero=False), axis=None))
                final_chart = l_stock
                
                if has_spy:
                    l_spy = base.mark_line(color='orange', strokeDash=[2,2], opacity=0.8).encode(y='SPY')
                    final_chart = l_stock + l_spy
                    
                st.altair_chart(final_chart.properties(height=40, width='container').configure_view(strokeWidth=0), use_container_width=True)
            else:
                st.caption("Not enough intraday data.")
        else:
            st.caption("Chart data unavailable.")
        
        st.markdown(d['rng_html'], unsafe_allow_html=True)
        st.markdown(d['vol_html'], unsafe_allow_html=True)
        st.markdown(d['rsi_html'], unsafe_allow_html=True)
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
    st.markdown(f"""<div style="background-color:#1e2127; padding:15px; border-radius:10px; margin-bottom:20px; border:1px solid #444;"><div style="display:flex; justify-content:space-around; text-align:center;"><div><div style="color:#aaa; font-size:12px;">Net Liq</div><div style="font-size:18px; font-weight:bold; color:white;">${tot_val:,.2f}</div></div><div><div style="color:#aaa; font-size:12px;">Day P/L</div><div style="font-size:18px; font-weight:bold; color:{'green' if day_pl>=0 else 'red'};">${day_pl:+,.2f}</div></div><div><div style="color:#aaa; font-size:12px;">Total P/L</div><div style="font-size:18px; font-weight:bold; color:{'green' if tot_pl>=0 else 'red'};">${tot_pl:+,.2f}</div></div></div></div>""", unsafe_allow_html=True)
    cols = st.columns(3)
    for i, (t, inf) in enumerate(PORT.items()):
        with cols[i%3]: render_card(t, inf) 

if a_on:
    d = get_data_cached(a_tick)
    if d and d['p'] >= a_price:
        if not st.session_state['alert_triggered']:
            msg = f"🚨 {a_tick} hit ${a_price:,.2f}!"
            log_alert(msg, title="Price Target Hit")
            st.session_state['alert_triggered'] = True
    else:
        st.session_state['alert_triggered'] = False 

def fetch_article_text(url):
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, headers=headers, timeout=3)
        if r.status_code == 200:
            clean_text = re.sub(r'<[^>]+>', '', r.text)
            return clean_text[:3000]
    except: pass
    return ""

def process_news_batch(raw_batch):
    try:
        from openai import OpenAI
        client = OpenAI(api_key=KEY)
        progress_bar = st.progress(0)
        batch_content = ""
        total_items = len(raw_batch)
        for idx, item in enumerate(raw_batch):
            full_text = fetch_article_text(item['link'])
            content = full_text if len(full_text) > 200 else item['desc']
            batch_content += f"\n\nARTICLE {idx+1}:\nTitle: {item['title']}\nLink: {item['link']}\nContent: {content[:1000]}"
            progress_bar.progress(min((idx + 1) / total_items, 1.0))
        system_instr = "You are a financial analyst. Read these articles. Identify specific stock tickers. Rank by sentiment. Format: TICKER | SENTIMENT (🟢/🔴/⚪) | REASON | ORIGINAL_TITLE | ORIGINAL_LINK"
        res = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role":"system", "content": system_instr}, {"role":"user", "content": batch_content}], max_tokens=700)
        new_results = []
        lines = res.choices[0].message.content.strip().split("\n")
        green_count = 0
        total_signals = 0
        for l in lines:
            parts = l.split("|")
            if len(parts) >= 5: 
                sig = parts[1].strip()
                if "🟢" in sig: green_count += 1
                if "🟢" in sig or "🔴" in sig: total_signals += 1
                new_results.append({"ticker": parts[0].strip(), "signal": sig, "reason": parts[2].strip(), "title": parts[3].strip(), "link": parts[4].strip()})
        if total_signals > 0:
            bull_pct = int((green_count / total_signals) * 100)
            if bull_pct >= 60: mood = f"🐂 {bull_pct}% BULLISH"
            elif bull_pct <= 40: mood = f"🐻 {100-bull_pct}% BEARISH"
            else: mood = f"⚖️ {bull_pct}% NEUTRAL"
            st.session_state['market_mood'] = mood
        progress_bar.empty()
        return new_results
    except Exception as e:
        st.warning(f"⚠️ AI Error: {e}")
        return []

@st.cache_data(ttl=300, show_spinner=False)
def get_news_cached():
    head = {'User-Agent': 'Mozilla/5.0'}
    urls = ["https://finance.yahoo.com/news/rssindex", "https://www.cnbc.com/id/10000664/device/rss/rss.html"]
    it, seen = [], set()
    blacklist = ["kill", "dead", "troop", "war", "sport", "football", "murder", "crash", "police", "arrest", "shoot", "bomb"]
    for u in urls:
        try:
            r = requests.get(u, headers=head, timeout=5)
            root = ET.fromstring(r.content)
            for i in root.findall('.//item')[:50]:
                t, l = i.find('title').text, i.find('link').text
                desc = i.find('description').text if i.find('description') is not None else ""
                if t and t not in seen:
                    t_lower = t.lower()
                    if not any(b in t_lower for b in blacklist):
                        seen.add(t)
                        it.append({"title":t,"link":l, "desc": desc})
        except: continue
    return it 

with t3:
    c_n1, c_n2 = st.columns([3, 1])
    with c_n1: st.subheader("🚨 Global Wire (Deep Scan)")
    with c_n2: 
        if st.session_state['market_mood']:
            st.markdown(f"<div style='background:#333; color:white; padding:5px; border-radius:5px; text-align:center; font-weight:bold;'>Mood: {st.session_state['market_mood']}</div>", unsafe_allow_html=True)
    if st.button("Deep Scan Reports (Top 10)", type="primary", key="deep_scan_btn"):
        st.session_state['news_results'] = [] 
        st.session_state['scanned_count'] = 0
        st.session_state['market_mood'] = None
        with st.spinner("Analyzing Top 10 Articles..."):
            raw_news = get_news_cached()
            if not raw_news: st.error("⚠️ No news sources found.")
            elif not KEY: st.warning("⚠️ No OpenAI Key.")
            else:
                batch = raw_news[:10]
                results = process_news_batch(batch)
                if results:
                    st.session_state['news_results'] = results
                    st.session_state['scanned_count'] = 10
                    st.rerun()
                else:
                    st.info("No relevant tickers found in this batch.")
    if st.session_state.get('news_results'):
        for i, r in enumerate(st.session_state['news_results']):
            st.markdown(f"**{r['ticker']} {r['signal']}** - [{r['title']}]({r['link']})")
            st.caption(r['reason'])
            st.divider() 
        if st.button("⬇️ Load More News (Next 10)", key="load_more_btn"):
            with st.spinner("Analyzing Next 10 Articles..."):
                raw_news = get_news_cached()
                start = st.session_state['scanned_count']
                end = start + 10 
                if start < len(raw_news):
                    batch = raw_news[start:end]
                    if batch:
                        new_results = process_news_batch(batch)
                        if new_results:
                            st.session_state['news_results'].extend(new_results)
                            st.session_state['scanned_count'] += 10
                            st.rerun() 
                        else:
                            st.warning("No relevant tickers found in this batch. Try again.")
                            st.session_state['scanned_count'] += 10 
                    else:
                        st.info("You have reached the end of the news feed.")
                else:
                    st.info("No more news available right now.")

now = datetime.now()
wait = 60 - now.second
time.sleep(wait + 1)
st.rerun()
