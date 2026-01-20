import streamlit as st, yfinance as yf, requests, time, re
from datetime import datetime, timedelta
import streamlit.components.v1 as components
import pandas as pd
import altair as alt 
import json
import xml.etree.ElementTree as ET

# --- 1. CONFIG & SETUP ---
try: st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="wide")
except: pass 

# --- 2. SESSION STATE INITIALIZATION ---
if 'initialized' not in st.session_state:
    st.session_state['initialized'] = False
    st.session_state['news_results'] = []
    st.session_state['scanned_count'] = 0
    st.session_state['market_mood'] = None 
    st.session_state['alert_triggered'] = False
    st.session_state['alert_log'] = [] 
    st.session_state['last_trends'] = {}
    st.session_state['mem_ratings'] = {}
    st.session_state['mem_meta'] = {}
    st.session_state['spy_cache'] = None
    st.session_state['spy_last_fetch'] = datetime.min
    st.session_state['banner_msg'] = None
    st.session_state['storm_cooldown'] = {}

# --- 3. JAVASCRIPT BRIDGES ---
def sync_js(config_json):
    js = f"""
    <script>
        const KEY = "penny_pulse_v59_data";
        const fromPython = {config_json};
        const saved = localStorage.getItem(KEY);
        const urlParams = new URLSearchParams(window.location.search);
        
        if (!urlParams.has("w") && saved) {{
            try {{
                const c = JSON.parse(saved);
                if (c.w && c.w !== "SPY") {{
                    const newUrl = new URL(window.location);
                    newUrl.searchParams.set("w", c.w);
                    newUrl.searchParams.set("at", c.at);
                    newUrl.searchParams.set("ap", c.ap);
                    newUrl.searchParams.set("ao", c.ao);
                    newUrl.searchParams.set("fo", c.fo);
                    newUrl.searchParams.set("no", c.no);
                    window.location.href = newUrl.toString();
                }}
            }} catch(e) {{}}
        }}
        
        if (fromPython.w) {{
            localStorage.setItem(KEY, JSON.stringify(fromPython));
        }}
    </script>
    """
    components.html(js, height=0, width=0)

def inject_wake_lock(enable):
    if enable:
        js = """
        <script>
        let wakeLock = null;
        async function requestWakeLock() {
            try {
                wakeLock = await navigator.wakeLock.request('screen');
                console.log('Wake Lock active!');
                wakeLock.addEventListener('release', () => { console.log('Wake Lock released!'); });
            } catch (err) { console.log(`${err.name}, ${err.message}`); }
        }
        requestWakeLock();
        document.addEventListener('visibilitychange', async () => {
            if (wakeLock !== null && document.visibilityState === 'visible') { requestWakeLock(); }
        });
        </script>
        """
        components.html(js, height=0, width=0)

# --- 4. CORE LOGIC FUNCTIONS ---
def update_params():
    st.query_params["w"] = st.session_state.w_input
    st.query_params["at"] = st.session_state.a_tick_input
    st.query_params["ap"] = str(st.session_state.a_price_input)
    st.query_params["ao"] = str(st.session_state.a_on_input).lower()
    st.query_params["fo"] = str(st.session_state.flip_on_input).lower()
    st.query_params["no"] = str(st.session_state.notify_input).lower()
    st.query_params["ko"] = str(st.session_state.keep_on_input).lower()
    if 'base_url_input' in st.session_state:
        st.query_params["bu"] = st.session_state.base_url_input

def restore_from_file(uploaded_file):
    if uploaded_file is not None:
        try:
            data = json.load(uploaded_file)
            st.session_state.w_input = data.get("w", "SPY")
            st.session_state.a_tick_input = data.get("at", "SPY")
            st.session_state.a_price_input = float(data.get("ap", 0.0))
            st.session_state.a_on_input = data.get("ao", False)
            st.session_state.flip_on_input = data.get("fo", False)
            st.session_state.notify_input = data.get("no", False)
            update_params()
            st.toast("Profile Restored!", icon="✅")
            time.sleep(1)
            st.rerun()
        except: st.error("Invalid Config File")

def play_alert_sound():
    sound_html = """
    <audio autoplay>
    <source src="https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3" type="audio/mpeg">
    </audio>
    """
    components.html(sound_html, height=0, width=0)

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

def log_alert(msg, title="Penny Pulse Alert", is_crash=False):
    t_stamp = (datetime.utcnow() - timedelta(hours=5)).strftime('%H:%M')
    st.session_state['alert_log'].insert(0, f"[{t_stamp}] {msg}")
    play_alert_sound()
    color = "#ff0000" if is_crash else "#ff4b4b"
    st.session_state['banner_msg'] = f"<span style='color:{color};'>🚨 {msg.upper()} 🚨</span>"
    if st.session_state.get("notify_input", False):
        send_notification(title, msg)

def calculate_storm_score(ticker, rsi, vol_ratio, trend, price_change):
    score = 0
    reasons = []
    mode = "NEUTRAL"
    if vol_ratio >= 2.0: score += 30; reasons.append("Volume Surge (2x)")
    elif vol_ratio >= 1.5: score += 15; reasons.append("High Volume")
    if trend == "BULL" and price_change > 0:
        if rsi <= 35: score += 25; reasons.append("Oversold (Bounce)")
        if price_change > 2.0: score += 20; reasons.append("Strong Momentum")
        mode = "BULL"
    elif trend == "BEAR" and price_change < 0:
        if rsi >= 65: score += 25; reasons.append("Overbought (Dump)")
        if price_change < -2.0: score += 25; reasons.append("Panic Selling")
        mode = "BEAR"
    if score >= 70:
        last_time = st.session_state['storm_cooldown'].get(ticker, datetime.min)
        if (datetime.now() - last_time).seconds > 300:
            if mode == "BULL":
                msg = f"🚀 PERFECT STORM: {ticker} (Score: {score}) - Buying Opportunity!"
                log_alert(msg, title="Bull Storm")
            elif mode == "BEAR":
                msg = f"⚠️ CRASH WARNING: {ticker} (Score: {score}) - Selling Pressure!"
                log_alert(msg, title="Crash Alert", is_crash=True)
            st.session_state['storm_cooldown'][ticker] = datetime.now()
    return score, mode, reasons

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
            chart_data = h 
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
    storm_html = ""
    
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
                
                s_score, s_mode, s_reasons = calculate_storm_score(s, rsi, ratio, raw_trend, d_reg_pct)
                if s_score >= 50:
                    storm_color = "#4caf50" if s_mode == "BULL" else "#ff4b4b"
                    icon = "🚀" if s_mode == "BULL" else "⚠️"
                    storm_html = f"<div style='margin-top:10px; padding:5px; border:1px solid {storm_color}; border-radius:5px; font-size:12px; color:{storm_color}; text-align:center;'><b>{icon} {s_mode} STORM: {s_score}/100</b><br><span style='font-size:10px; color:#aaa;'>{', '.join(s_reasons)}</span></div>"

    except: pass
    return {"p":p_reg, "d":d_reg_pct, "d_raw": (p_reg - pv), "x":x_str, "v":v_str, "vt":vol_tag, "rsi":rsi, "rl":rl, "tr":tr, "raw_trend":raw_trend, "rng_html":rng_html, "vol_html":vol_html, "rsi_html":rsi_html, "chart":chart_data, "ai_txt":ai_txt, "ai_col":ai_col, "gc":golden_cross_html, "storm_html":storm_html} 

# --- 5. INITIAL CONFIG & SIDEBAR ---
# Load URL State
qp = st.query_params
current_config = {
    "w": qp.get("w", "SPY, BTC-USD, TD.TO, PLUG.CN, VTX.V"),
    "at": qp.get("at", "SPY"),
    "ap": float(qp.get("ap", 0.0)),
    "ao": qp.get("ao", "false") == "true",
    "fo": qp.get("fo", "false") == "true",
    "no": qp.get("no", "false") == "true",
    "ko": qp.get("ko", "false") == "true",
    "bu": qp.get("bu", "")
}
config_json = json.dumps(current_config)
sync_js(config_json)
inject_wake_lock(current_config["ko"])

PORT = {
    "HIVE": {"e": 3.19, "d": "Dec. 01, 2024", "q": 50},
    "BAER": {"e": 1.86, "d": "Jan. 10, 2025", "q": 100},
    "TX":   {"e": 38.10, "d": "Nov. 05, 2023", "q": 40},
    "IMNN": {"e": 3.22, "d": "Aug. 20, 2024", "q": 100},
    "RERE": {"e": 5.31, "d": "Oct. 12, 2024", "q": 100}
} 

NAMES = {
    "TSLA":"Tesla", "NVDA":"Nvidia", "BTC-USD":"Bitcoin", "AMD":"AMD", 
    "PLTR":"Palantir", "AAPL":"Apple", "SPY":"S&P 500", "^IXIC":"Nasdaq", 
    "^DJI":"Dow Jones", "GC=F":"Gold", "TD.TO":"TD Bank", "IVN.TO":"Ivanhoe", 
    "BN.TO":"Brookfield", "JNJ":"J&J", "^GSPTSE": "TSX"
} 

# --- SIDEBAR WIDGETS ---
st.sidebar.header("⚡ Pulse")
if "OPENAI_KEY" in st.secrets: KEY = st.secrets["OPENAI_KEY"]
else: KEY = st.sidebar.text_input("OpenAI Key (Optional)", type="password") 

st.sidebar.text_input("Add Tickers (Comma Sep)", value=current_config['w'], key="w_input", on_change=update_params)
WATCH = [x.strip().upper() for x in st.session_state.w_input.split(",") if x.strip()]
ALL = list(set(WATCH + list(PORT.keys())))

c1, c2 = st.sidebar.columns(2)
with c1:
    if st.button("💾 Save Settings"):
        update_params()
        st.toast("Settings Saved!", icon="💾")
with c2:
    if st.button("🔊 Test Audio"):
        play_alert_sound()
        st.toast("Audio Armed!", icon="🔊")

st.sidebar.divider()
st.sidebar.subheader("🔔 Smart Alerts") 

curr_tick = current_config['at']
if curr_tick not in ALL and ALL: curr_tick = sorted(ALL)[0]
idx = 0
if curr_tick in sorted(ALL): idx = sorted(ALL).index(curr_tick)

st.sidebar.selectbox("Price Target Asset", sorted(ALL), index=idx, key="a_tick_input", on_change=update_params)
st.sidebar.number_input("Target ($)", value=current_config['ap'], step=0.5, key="a_price_input", on_change=update_params)
st.sidebar.toggle("Active Price Alert", value=current_config['ao'], key="a_on_input", on_change=update_params)
st.sidebar.toggle("Alert on Trend Flip", value=current_config['fo'], key="flip_on_input", on_change=update_params) 
st.sidebar.toggle("💡 Keep Screen On", value=current_config['ko'], key="keep_on_input", on_change=update_params, help="Prevents phone from sleeping.")
st.sidebar.checkbox("Desktop Notifications", value=current_config['no'], key="notify_input", on_change=update_params, help="Works on Desktop/HTTPS only.")

# --- HELPERS USING SESSION STATE DIRECTLY (CRASH FIX) ---
def check_flip(ticker, current_trend):
    # Fix: Use session state directly to avoid NameError if var is not in scope
    if not st.session_state.get('flip_on_input', False): return
    if ticker in st.session_state['last_trends']:
        prev = st.session_state['last_trends'][ticker]
        if prev != "NEUTRAL" and current_trend != "NEUTRAL" and prev != current_trend:
            msg = f"{ticker} flipped to {current_trend}"
            st.toast(msg, icon="⚠️")
            log_alert(msg, title="Trend Flip Alert")
    st.session_state['last_trends'][ticker] = current_trend 

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
        
        spy_data = get_spy_benchmark()
        if d['chart'] is not None and not d['chart'].empty:
            stock_series = d['chart']['Close'].tail(30)
            if len(stock_series) > 1:
                start_p = stock_series.iloc[0]
                stock_norm = ((stock_series - start_p) / start_p) * 100
                plot_df = pd.DataFrame({'Stock': stock_norm})
                plot_df = plot_df.reset_index().rename(columns={plot_df.index.name: 'Time'})
                has_spy = False
                if spy_data is not None and not spy_data.empty:
                    try:
                        spy_aligned = spy_data.reindex(stock_series.index, method='nearest', tolerance=timedelta(minutes=10))
                        if not spy_aligned['Close'].isnull().all():
                            spy_vals = spy_aligned['Close']
                            valid_spy = spy_vals.dropna()
                            if not valid_spy.empty:
                                spy_start = valid_spy.iloc[0]
                                plot_df['SPY'] = ((spy_vals.values - spy_start) / spy_start) * 100
                                has_spy = True
                    except: pass
                line_color = "#4caf50" if d['d'] >= 0 else "#ff4b4b"
                base = alt.Chart(plot_df).encode(x=alt.X('Time', axis=None))
                l_stock = base.mark_line(color=line_color, strokeWidth=2).encode(y=alt.Y('Stock', scale=alt.Scale(zero=False), axis=None))
                final_chart = l_stock
                if has_spy:
                    l_spy = base.mark_line(color='orange', strokeDash=[2,2], opacity=0.8).encode(y='SPY')
                    final_chart = l_stock + l_spy
                st.altair_chart(final_chart.properties(height=40, width='container').configure_view(strokeWidth=0), use_container_width=True)
            else: st.caption("Not enough intraday data.")
        else: st.caption("Chart data unavailable.")
        
        st.markdown(d['rng_html'], unsafe_allow_html=True)
        st.markdown(d['vol_html'], unsafe_allow_html=True)
        st.markdown(d['rsi_html'], unsafe_allow_html=True)
        st.markdown(d['storm_html'], unsafe_allow_html=True)
    else: st.metric(t, "---", "0.0%")
    st.divider() 

# --- RESTORED BACKUP MENU (ABOVE SHARE) ---
st.sidebar.divider()
with st.sidebar.expander("📦 Backup & Restore"):
    st.caption("Download your profile to save it.")
    export_data = json.dumps(current_config, indent=2)
    st.download_button(label="📥 Download Profile", data=export_data, file_name="my_pulse_config.json", mime="application/json")
    uploaded = st.file_uploader("📤 Restore Profile", type=["json"])
    if uploaded: restore_from_file(uploaded)

with st.sidebar.expander("🔗 Share & Invite"):
    base_url = st.text_input("App Web Address (Paste Once)", value=current_config['bu'], placeholder="e.g. https://my-app.streamlit.app", key="base_url_input", on_change=update_params)
    if base_url:
        clean_base = base_url.split("?")[0].strip("/")
        params = f"?w={st.session_state.w_input}&at={a_tick}&ap={a_price}&ao={str(a_on).lower()}&fo={str(flip_on).lower()}"
        full_link = f"{clean_base}/{params}"
        st.code(full_link, language="text")

if st.session_state['alert_log']:
    st.sidebar.divider()
    st.sidebar.markdown("**📜 Recent Alerts**")
    for msg in st.session_state['alert_log'][:5]: st.sidebar.caption(msg)
    if st.sidebar.button("Clear Log"):
        st.session_state['alert_log'] = []
        st.rerun()

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
            # --- TOKEN SAVER: REDUCED TO 300 CHARS ---
            batch_content += f"\n\nARTICLE {idx+1}:\nTitle: {item['title']}\nLink: {item['link']}\nContent: {content[:300]}\nDate: {item['date_str']}"
            progress_bar.progress(min((idx + 1) / total_items, 1.0))
        
        system_instr = "You are a financial analyst. Analyze these articles. Return a JSON object with a key 'articles' which is a list of objects. Each object must have: 'ticker', 'signal' (🟢, 🔴, or ⚪), 'reason', 'title', 'link', 'date_display'. 'date_display' should be the relative time (e.g. '2h ago') derived from the article date. The link must be the original URL. IMPORTANT: Ignore articles that are about general crime, police arrests, sports, gossip, or non-financial news. Only return financial, market, or company news. **KEEP REASONS EXTREMELY CONCISE (UNDER 10 WORDS).**"
        
        res = client.chat.completions.create(
            model="gpt-4o-mini", 
            messages=[
                {"role":"system", "content": system_instr}, 
                {"role":"user", "content": batch_content}
            ], 
            response_format={"type": "json_object"},
            max_tokens=3000  
        )
        
        try:
            data = json.loads(res.choices[0].message.content)
            new_results = data.get("articles", [])
        except json.JSONDecodeError:
            st.warning("⚠️ AI Analysis incomplete (Limit Reached). Showing partial results.")
            return []
        
        valid_results = []
        for r in new_results:
            if r['link'].startswith("http"):
                valid_results.append(r)
        
        if valid_results:
            bull_cnt = sum(1 for r in valid_results if "🟢" in r['signal'])
            tot = len(valid_results)
            if tot > 0:
                bull_pct = int((bull_cnt / tot) * 100)
                if bull_pct >= 60: mood = f"🐂 {bull_pct}% BULLISH"
                elif bull_pct <= 40: mood = f"🐻 {100-bull_pct}% BEARISH"
                else: mood = f"⚖️ {bull_pct}% NEUTRAL"
                st.session_state['market_mood'] = mood
        
        progress_bar.empty()
        return valid_results
    except Exception as e:
        print(f"AI Error: {e}") 
        st.caption("⚠️ News Analysis unavailable at this moment.")
        return []

@st.cache_data(ttl=300, show_spinner=False)
def get_news_cached():
    head = {'User-Agent': 'Mozilla/5.0'}
    urls = ["https://www.prnewswire.com/rss/news-releases-list.rss","https://finance.yahoo.com/news/rssindex", "https://www.cnbc.com/id/10000664/device/rss/rss.html"]
    it, seen = [], set()
    blacklist = ["kill", "dead", "troop", "war", "sport", "football", "murder", "crash", "police", "arrest", "shoot", "bomb", "jail", "prison", "sentence", "suspect", "court", "francais", "la", "le", "et", "pour"]
    for u in urls:
        try:
            r = requests.get(u, headers=head, timeout=5)
            if r.status_code != 200: continue
            
            root = ET.fromstring(r.content)
            items = root.findall('.//item')
            if not items: items = root.findall('.//{http://www.w3.org/2005/Atom}entry')
            
            for i in items[:50]:
                t = i.find('title')
                if t is None: t = i.find('{http://www.w3.org/2005/Atom}title')
                
                l = i.find('link')
                if l is None: l = i.find('{http://www.w3.org/2005/Atom}link')
                
                url = None
                if l is not None:
                    if l.text and l.text.strip(): url = l.text.strip()
                    elif 'href' in l.attrib: url = l.attrib['href']
                
                d = i.find('pubDate')
                if d is None: d = i.find('{http://www.w3.org/2005/Atom}published')
                date_str = d.text if d is not None else ""
                
                if url:
                    title_text = t.text if t is not None else "No Title"
                    desc = i.find('description')
                    if desc is None: desc = i.find('{http://www.w3.org/2005/Atom}summary')
                    desc_text = desc.text if desc is not None else ""

                    t_lower = title_text.lower()
                    if not any(b in t_lower for b in blacklist) and title_text not in seen:
                        seen.add(title_text)
                        it.append({"title":title_text,"link":url, "desc": desc_text, "date_str": date_str})
        except: continue
    return it 

t1, t2, t3 = st.tabs(["🏠 Dashboard", "🚀 My Picks", "📰 Market News"])
with t1:
    cols = st.columns(3)
    for i, t in enumerate(WATCH):
        with cols[i%3]: render_card(t) 

with t2:
    tot_val, day_pl, tot_pl = 0.0, 0.0, 0.0
    pie_data = []
    
    for t, inf in PORT.items():
        d = get_data_cached(t)
        if d:
            q = inf.get("q", 100)
            curr = d['p'] * q
            tot_val += curr
            tot_pl += (curr - (inf['e'] * q))
            day_pl += (d['d_raw'] * q)
            pie_data.append({"Ticker": t, "Value": curr})
            
    st.markdown(f"""<div style="background-color:#1e2127; padding:15px; border-radius:10px; margin-bottom:20px; border:1px solid #444;"><div style="display:flex; justify-content:space-around; text-align:center;"><div><div style="color:#aaa; font-size:12px;">Net Liq</div><div style="font-size:18px; font-weight:bold; color:white;">${tot_val:,.2f}</div></div><div><div style="color:#aaa; font-size:12px;">Day P/L</div><div style="font-size:18px; font-weight:bold; color:{'green' if day_pl>=0 else 'red'};">${day_pl:+,.2f}</div></div><div><div style="color:#aaa; font-size:12px;">Total P/L</div><div style="font-size:18px; font-weight:bold; color:{'green' if tot_pl>=0 else 'red'};">${tot_pl:+,.2f}</div></div></div></div>""", unsafe_allow_html=True)
    
    c_pie1, c_pie2 = st.columns([1, 2])
    with c_pie1:
        if pie_data:
            df_pie = pd.DataFrame(pie_data)
            pie_chart = alt.Chart(df_pie).mark_arc(innerRadius=50).encode(
                theta=alt.Theta(field="Value", type="quantitative"),
                color=alt.Color(field="Ticker", type="nominal"),
                tooltip=["Ticker", "Value"]
            )
            st.altair_chart(pie_chart, use_container_width=True)
    
    cols = st.columns(3)
    for i, (t, inf) in enumerate(PORT.items()):
        with cols[i%3]: render_card(t, inf) 

with t3:
    c_n1, c_n2 = st.columns([3, 1])
    with c_n1: st.subheader("🚨 Global Wire (Deep AI Scan)")
    with c_n2: 
        if st.session_state['market_mood']:
            st.markdown(f"<div style='background:#333; color:white; padding:5px; border-radius:5px; text-align:center; font-weight:bold;'>Mood: {st.session_state['market_mood']}</div>", unsafe_allow_html=True)
    if st.button("Deep AI Scan Reports (Top 10)", type="primary", key="deep_scan_btn"):
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
            time_tag = f"🕒 {r.get('date_display', 'Recent')}"
            st.markdown(f"**{r['ticker']} {r['signal']}** | {time_tag} | [{r['title']}]({r['link']})")
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
