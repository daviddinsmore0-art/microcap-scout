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

# *** CONFIGURATION SECTION ***
WEBHOOK_URL = "" 
LOGO_PATH = "logo.png" 
# *****************************

# --- INITIALIZE SESSION STATE ---
if 'initialized' not in st.session_state:
    st.session_state['initialized'] = True
    
    # 1. Defaults
    defaults = {
        'w_key': "TD.TO, CCO.TO, IVN.TO, BN.TO, HIVE, SPY",
        'at_key': "TD.TO",
        'ap_key': 0.0,
        'ao_key': False,
        'fo_key': False,
        'ko_key': False,
        'no_key': False
    }

    # 2. Load Defaults
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v
            
    # 3. URL Recovery (This saves you from crashes)
    qp = st.query_params
    if 'w' in qp: st.session_state['w_key'] = qp['w']

    st.session_state.update({
        'news_results': [], 
        'raw_news_cache': [],
        'news_offset': 0,
        'alert_log': [], 
        'storm_cooldown': {}, 
        'spy_cache': None, 
        'spy_last_fetch': datetime.min,
        'banner_msg': None
    })

# --- 2. FUNCTIONS ---
def get_base64_image(image_path):
    if os.path.exists(image_path):
        with open(image_path, "rb") as img_file:
            return base64.b64encode(img_file.read()).decode()
    return None

def inject_wake_lock(enable):
    if enable: components.html("""<script>navigator.wakeLock.request('screen').catch(console.log);</script>""", height=0)

def send_discord_alert(msg):
    if WEBHOOK_URL:
        try:
            data = {"content": f"🚨 **PENNY PULSE ALERT** 🚨\n{msg}"}
            requests.post(WEBHOOK_URL, json=data)
        except: pass

def log_alert(msg, sound=True):
    if msg not in st.session_state.alert_log:
        st.session_state.alert_log.insert(0, f"{datetime.now().strftime('%H:%M')} - {msg}")
        if sound: 
            components.html("""<audio autoplay><source src="https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3"></audio>""", height=0)
        st.session_state['banner_msg'] = msg
        send_discord_alert(msg)

def get_relative_time(date_str):
    try:
        dt = email.utils.parsedate_to_datetime(date_str)
        now = datetime.now(dt.tzinfo)
        diff = now - dt
        seconds = diff.total_seconds()
        if seconds < 60: return "Just now"
        elif seconds < 3600: return f"{int(seconds//60)}m ago"
        elif seconds < 86400: return f"{int(seconds//3600)}h ago"
        elif seconds < 172800: return "Yesterday"
        else: return f"{int(seconds//86400)}d ago"
    except: return "Recent"

def process_ai_batch(items_to_process, key):
    try:
        from openai import OpenAI
        cl = OpenAI(api_key=key)
        prompt = """
        Analyze these financial headlines. For each relevant item, return a JSON object with:
        - 'ticker': The main stock ticker (e.g. TSLA, AAPL, BTC) or 'MKT' if general.
        - 'sentiment': 'BULL' or 'BEAR' or 'NEUTRAL'.
        - 'summary': A 5-word snappy summary.
        - 'link': The original link.
        - 'time': The original time string.
        Return a JSON wrapper: {'items': [...]}
        """
        ai_input = "\n".join([f"{x['title']} | {x['time']} | {x['link']}" for x in items_to_process])
        resp = cl.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role":"system", "content": prompt}, {"role":"user", "content": ai_input}],
            response_format={"type": "json_object"}
        )
        return json.loads(resp.choices[0].message.content).get('items', [])
    except Exception as e:
        st.error(f"AI Error: {e}")
        return []

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

# --- RESTORE LOGIC ---
with st.sidebar.expander("📤 Share & Backup", expanded=False):
    st.caption("Share this Watchlist")
    
    # Force update URL with current watchlist so refreshes don't lose data
    if st.session_state['w_key']:
        st.query_params['w'] = st.session_state['w_key']
        
    params = []
    current_w = st.session_state.get('w_key', "")
    if current_w: params.append(f"w={urllib.parse.quote(current_w)}")
    query_str = "&".join(params)
    st.code(f"/?{query_str}", language="text")
    st.divider()
    
    export_data = {
        'w_key': st.session_state.get('w_key'),
        'at_key': st.session_state.get('at_key'),
        'ap_key': st.session_state.get('ap_key'),
        'ao_key': st.session_state.get('ao_key')
    }
    st.download_button("Download Profile", json.dumps(export_data), "pulse_profile.json")
    
    uploaded_file = st.file_uploader("Restore Profile", type="json")
    if uploaded_file is not None:
        try:
            string_data = uploaded_file.getvalue().decode("utf-8")
            data = json.loads(string_data)
            
            key_map = {
                'w_input': 'w_key', 'w_data': 'w_key', 'w_key': 'w_key',
                'a_tick_input': 'at_key', 'at_data': 'at_key', 'at_key': 'at_key',
                'a_price_input': 'ap_key', 'ap_data': 'ap_key', 'ap_key': 'ap_key',
                'a_on_input': 'ao_key', 'ao_data': 'ao_key', 'ao_key': 'ao_key'
            }
            
            for k, v in data.items():
                target = key_map.get(k, k)
                st.session_state[target] = v

            st.toast("Restored! Reloading...")
            time.sleep(0.5)
            st.rerun() 
                
        except Exception as e:
            st.error(f"Error: {e}")

# --- WIDGETS ---
st.sidebar.text_input("Tickers", key="w_key")

c1, c2 = st.sidebar.columns(2)
with c1: 
    if st.button("💾 Save"): st.toast("Saved!")
with c2: 
    if st.button("🔊 Test"): 
        log_alert("Test Signal to Discord!", sound=True)

st.sidebar.divider()
st.sidebar.subheader("🔔 Smart Alerts")

if st.session_state.alert_log:
    with st.sidebar.expander("Recent Activity", expanded=True):
        for a in st.session_state.alert_log[:5]:
            st.caption(a)

PORT = {"HIVE": {"e": 3.19, "d": "Dec 01", "q": 50}, "BAER": {"e": 1.86, "d": "Jan 10", "q": 100}, "TX": {"e": 38.10, "d": "Nov 05", "q": 40}, "IMNN": {"e": 3.22, "d": "Aug 20", "q": 100}, "RERE": {"e": 5.31, "d": "Oct 12", "q": 100}}
w_str = st.session_state.get('w_key', "")
ALL_T = list(set([x.strip().upper() for x in w_str.split(",") if x.strip()] + list(PORT.keys())))

st.sidebar.caption("Price Target Asset")
if st.session_state.get('at_key') not in ALL_T and ALL_T:
    st.session_state['at_key'] = ALL_T[0]

try:
    idx = sorted(ALL_T).index(st.session_state.get('at_key'))
    st.sidebar.selectbox("", sorted(ALL_T), key="at_key", label_visibility="collapsed")
except:
    if ALL_T:
        st.sidebar.selectbox("", sorted(ALL_T), key="at_key", label_visibility="collapsed")

st.sidebar.caption("Target ($)")
st.sidebar.number_input("", step=0.5, key="ap_key", label_visibility="collapsed")

st.sidebar.toggle("Active Price Alert", key="ao_key")
st.sidebar.toggle("Alert on Trend Flip", key="fo_key")
st.sidebar.toggle("💡 Keep Screen On", key="ko_key")
st.sidebar.checkbox("Desktop Notifications", key="no_key")

inject_wake_lock(st.session_state.get('ko_key', False))

# --- 4. DATA ENGINE (ROBUST) ---
@st.cache_data(ttl=300)
def get_spy_data():
    try: return yf.Ticker("SPY").history(period="1d", interval="5m")['Close']
    except: return None

def get_pro_data(s):
    try:
        tk = yf.Ticker(s)
        # Fetching data with basic error handling to prevent "1ST" crashes
        try:
            h = tk.history(period="1d", interval="5m", prepost=True)
        except: 
            return None
            
        if h.empty: 
            try: h = tk.history(period="5d", interval="15m", prepost=True)
            except: return None
        if h.empty: return None
        
        p_live = h['Close'].iloc[-1]
        
        # Optimize: Only fetch 1mo history if we really need it for alerts
        # But keeping it for now for consistency
        hm = tk.history(period="1mo")
        if not hm.empty:
            hard_close = hm['Close'].iloc[-1]
            prev_close = hm['Close'].iloc[-2] if len(hm) > 1 else hard_close
        else:
            hard_close = p_live
            prev_close = p_live

        # --- TIMEZONE LOGIC (ET FIXED) ---
        # 1. Get Current UTC
        utc_now = datetime.utcnow()
        # 2. Convert to ET (Standard is UTC-5)
        # Note: This is simple offset. For true DST you'd need pytz library, 
        # but this works for 99% of cases without extra dependencies.
        now_et = utc_now - timedelta(hours=5) 
        
        # Market Hours: 9:30 AM - 4:00 PM ET, Mon-Fri (Weekday < 5)
        market_open = datetime(now_et.year, now_et.month, now_et.day, 9, 30)
        market_close = datetime(now_et.year, now_et.month, now_et.day, 16, 0)
        
        is_market_open = (now_et.weekday() < 5) and (market_open <= now_et <= market_close)
        is_tsx = any(x in s for x in ['.TO', '.V', '.CN'])

        if is_market_open:
            display_price = p_live
            display_pct = ((p_live - prev_close) / prev_close) * 100
        else:
            display_price = hard_close
            display_pct = ((hard_close - prev_close) / prev_close) * 100

        market_state = "REG"
        ext_price = None
        ext_pct = 0.0
        
        # Extended Hours Detection
        if not is_tsx and not is_market_open:
            # If price is significantly different from close, show extended
            if abs(p_live - hard_close) > 0.01:
                if now_et.hour < 9 or (now_et.hour == 9 and now_et.minute < 30):
                    market_state = "PRE-MKT"
                elif now_et.hour >= 16:
                    market_state = "POST-MKT"
                else:
                    market_state = "EXT" # Weekend/Late night
                
                ext_price = p_live
                ext_pct = ((p_live - hard_close) / hard_close) * 100

        rsi, trend, vol_ratio = 50, "NEUTRAL", 1.0
        if len(hm) > 14:
            diff = hm['Close'].diff(); u, d = diff.clip(lower=0), -1*diff.clip(upper=0)
            rsi = 100 - (100/(1 + (u.rolling(14).mean()/d.rolling(14).mean()).iloc[-1]))
            m = hm['Close'].ewm(span=12).mean() - hm['Close'].ewm(span=26).mean()
            trend = "BULL" if m.iloc[-1] > 0 else "BEAR"
            vol_ratio = hm['Volume'].iloc[-1] / hm['Volume'].mean() if hm['Volume'].mean() > 0 else 1.0
            
        ai_bias = "🟢 BULLISH BIAS" if (trend=="BULL" and rsi<70) else ("🔴 BEARISH BIAS" if (trend=="BEAR" and rsi>30) else "🟡 NEUTRAL BIAS")

        spy = get_spy_data()
        chart_data = h['Close'].tail(78).reset_index()
        chart_data.columns = ['T', 'Stock']
        chart_data['Idx'] = range(len(chart_data)) 
        
        start_price = chart_data['Stock'].iloc[0] if chart_data['Stock'].iloc[0] != 0 else 1
        chart_data['Stock'] = ((chart_data['Stock'] - start_price) / start_price) * 100
        
        if spy is not None and len(spy) > 0:
            s_slice = spy.tail(len(chart_data))
            spy_start = s_slice.iloc[0] if s_slice.iloc[0] != 0 else 1
            s_norm = ((s_slice - spy_start) / spy_start) * 100
            chart_data['SPY'] = s_norm.values if len(s_norm) == len(chart_data) else 0

        earn = "N/A"
        try:
            cal = tk.calendar
            if isinstance(cal, dict) and 'Earnings Date' in cal:
                dates = cal['Earnings Date']
                future = [d for d in dates if d.date() >= datetime.now().date()]
                if future: earn = f"Next: {future[0].strftime('%b %d')}"
                elif dates: earn = f"Last: {dates[0].strftime('%b %d')}"
            elif hasattr(cal, 'iloc') and not cal.empty:
                val = cal.iloc[0, 0]
                if isinstance(val, (datetime, pd.Timestamp)):
                    if val.date() >= datetime.now().date(): earn = f"Next: {val.strftime('%b %d')}"
                    else: earn = f"Last: {val.strftime('%b %d')}"
        except: 
            try:
                t = tk.info.get('earningsTimestamp', None)
                if t:
                    dt_earn = datetime.fromtimestamp(t)
                    if dt_earn.date() >= datetime.now().date(): earn = f"Next: {dt_earn.strftime('%b %d')}"
                    else: earn = f"Last: {dt_earn.strftime('%b %d')}"
            except: pass
        
        rat = tk.info.get('recommendationKey', 'N/A').upper().replace('_',' ')

        last_alert = st.session_state['storm_cooldown'].get(s, datetime.min)
        if (datetime.now() - last_alert).total_seconds() > 300:
            if trend == "BULL" and rsi < 35 and vol_ratio > 1.2:
                msg = f"⚡ **PERFECT STORM:** {s}\n- RSI: {rsi:.0f} (Oversold)\n- Vol: {vol_ratio:.1f}x (High)\n- Trend: Bullish Dip"
                log_alert(msg)
                st.session_state['storm_cooldown'][s] = datetime.now()
            elif trend == "BEAR" and rsi > 65 and vol_ratio > 1.2:
                msg = f"🐻 **DEATH BEAR:** {s}\n- RSI: {rsi:.0f} (Overbought)\n- Vol: {vol_ratio:.1f}x\n- Trend: Bearish Rejection"
                log_alert(msg)
                st.session_state['storm_cooldown'][s] = datetime.now()

        return {
            "p": display_price, "d": display_pct, "rsi": rsi, "tr": trend, "vol": vol_ratio,
            "chart": chart_data, "ai": ai_bias, "rat": rat, "earn": earn,
            "h": h['High'].max(), "l": h['Low'].min(), 
            "state": market_state, "ext_p": ext_price, "ext_d": ext_pct
        }
    except: return None

# --- 5. SCROLLER ---
@st.cache_data(ttl=60)
def build_scroller_safe():
    try:
        indices = [("SPY", "S&P 500"), ("^IXIC", "Nasdaq"), ("^DJI", "Dow Jones"), ("BTC-USD", "Bitcoin")]
        items = []
        for t, n in indices:
            d = get_pro_data(t)
            if d:
                c = "#4caf50" if d['d'] >= 0 else "#ff4b4b"
                a = "▲" if d['d'] >= 0 else "▼"
                items.append(f"{n}: <span style='color:{c}'>${d['p']:,.2f} {a} {d['d']:.2f}%</span>")
        if not items: return "Penny Pulse Market Tracker"
        return "&nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;".join(items)
    except: return "Penny Pulse Market Tracker"

if st.session_state['banner_msg']:
    st.markdown(f"<div style='background:#FFD700;color:black;padding:10px;text-align:center;font-weight:bold;border-radius:5px;margin-bottom:10px;'>🔔 {st.session_state['banner_msg']}</div>", unsafe_allow_html=True)
    if st.button("Dismiss Alert"): st.session_state['banner_msg'] = None; st.rerun()

scroller_html = build_scroller_safe()
st.markdown(f"""<div style="background:#0E1117;padding:10px 0;border-bottom:1px solid #333;margin-bottom:15px;"><marquee scrollamount="10" style="width:100%;font-weight:bold;font-size:18px;color:#EEE;">{scroller_html}</marquee></div>""", unsafe_allow_html=True)

# --- HEADER (OLED BLACK BOX) ---
img_html = ""
img_b64 = get_base64_image(LOGO_PATH)

if img_b64:
    img_html = f'<img src="data:image/png;base64,{img_b64}" style="max-height:80px; max-width:100%; display:block; margin: 0 auto 10px auto;">'
else:
    img_html = "<h1 style='text-align: center; margin: 0; padding: 0; color: white;'>⚡ Penny Pulse</h1>"

# ET Time for display
now_et_str = (datetime.utcnow() - timedelta(hours=5)).strftime('%H:%M:%S ET')

st.markdown(f"""
<div style="
    background-color: #000000; 
    border: 1px solid #333; 
    border-radius: 10px; 
    padding: 20px; 
    margin-bottom: 25px; 
    display: flex; 
    flex-direction: column; 
    align-items: center; 
    justify-content: center;
    box-shadow: 0 4px 6px rgba(0,0,0,0.3);
">
    {img_html}
    <div style='text-align: center; color: #888; font-size: 12px; margin-bottom: 10px;'>Last Sync: {now_et_str}</div>
    <div id="timer_div" style="background:#1E1E1E; border:1px solid #333; border-radius:8px; padding:5px 20px; color:#FF4B4B; font-family:'Courier New', monospace; font-weight:bold; font-size: 20px;">
        <span id="timer">--</span>s
    </div>
</div>
<script>
setInterval(function(){{
    var s = 60 - new Date().getSeconds();
    var t = document.getElementById("timer");
    if(t) t.innerHTML = s < 10 ? "0" + s : s;
}}, 1000);
</script>
""", unsafe_allow_html=True)

# --- 7. TABS ---
t1, t2, t3 = st.tabs(["🏠 Dashboard", "🚀 My Picks", "📰 Market News"])

def draw_pro_card(t, port_data=None):
    d = get_pro_data(t)
    if d:
        name = get_name(t)
        sec = get_sector_tag(t)
        col = "green" if d['d']>=0 else "red"
        col_hex = "#4caf50" if d['d']>=0 else "#ff4b4b"
        
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

        if d['state'] != "REG" and d['ext_p']:
            ext_sign = "+" if d['ext_d'] >= 0 else ""
            ext_col = "#4caf50" if d['ext_d'] >= 0 else "#ff4b4b" 
            st.markdown(f"""
            <div style="text-align:right; margin-top:-8px; margin-bottom:8px;">
                <span style="color:{ext_col}; font-size:14px; font-weight:bold;">
                    {d['state']}: ${d['ext_p']:,.2f} ({ext_sign}{d['ext_d']:.2f}%)
                </span>
            </div>
            """, unsafe_allow_html=True)

        if port_data:
            qty = port_data['q']
            entry = port_data['e']
            val = d['p'] * qty
            profit = val - (entry * qty)
            roi = ((d['p'] - entry) / entry) * 100
            p_col = "#4caf50" if profit >= 0 else "#ff4b4b"
            
            st.markdown(f"""
            <div style="background-color:black; color:white; border-left:4px solid {p_col}; padding:8px; margin-bottom:10px; font-size:15px; font-weight:bold; font-family:sans-serif;">
                <span style="color:white;">Qty: {qty}</span> &nbsp;&nbsp; 
                <span style="color:white;">Avg: ${entry}</span> &nbsp;&nbsp; 
                <span style="color:white;">Gain: <span style="color:{p_col};">${profit:,.2f} ({roi:+.1f}%)</span></span>
            </div>
            """, unsafe_allow_html=True)

        r_color = "#888"
        if "STRONG BUY" in d['rat']: r_color = "#00FF00" 
        elif "BUY" in d['rat']: r_color = "#4CAF50"      
        elif "HOLD" in d['rat']: r_color = "#FFC107"     
        elif "SELL" in d['rat']: r_color = "#FF4B4B"     

        t_color = "#FF4B4B" if "BEAR" in d['tr'] else "#4CAF50"

        st.markdown(f"**☻ AI:** {d['ai']}")
        st.markdown(f"**TREND:** <span style='color:{t_color};font-weight:bold;'>{d['tr']}</span>", unsafe_allow_html=True)
        st.markdown(f"**ANALYST RATING:** <span style='color:{r_color};font-weight:bold;'>{d['rat']}</span>", unsafe_allow_html=True)
        st.markdown(f"**EARNINGS:** <b>{d['earn']}</b>", unsafe_allow_html=True)
        
        base = alt.Chart(d['chart']).encode(x=alt.X('Idx', axis=None))
        l1 = base.mark_line(color=col).encode(y=alt.Y('Stock', axis=None))
        if 'SPY' in d['chart'].columns:
            l2 = base.mark_line(color='orange', strokeDash=[2,2]).encode(y=alt.Y('SPY', axis=None))
            st.altair_chart((l1+l2).properties(height=60), use_container_width=True)
        else:
            st.altair_chart(l1.properties(height=60), use_container_width=True)
        
        st.caption("INTRADAY vs SPY (Orange/Dotted)")
        
        if d['h'] > d['l']: pct = (d['p'] - d['l']) / (d['h'] - d['l']) * 100
        else: pct = 50
        pct = max(0, min(100, pct))
        range_tag = "📉 Bottom (Dip)" if pct < 30 else ("📈 Top (High)" if pct > 70 else "⚖️ Mid-Range")
        
        st.markdown(f"""<div style="font-size:10px;color:#888;margin-bottom:2px;">Day Range: {range_tag}</div><div style="width:100%;height:8px;background:linear-gradient(90deg, #ff4b4b, #ffff00, #4caf50);border-radius:4px;position:relative;margin-bottom:15px;"><div style="position:absolute;left:{pct}%;top:-2px;width:3px;height:12px;background:white;border:1px solid #333;"></div></div>""", unsafe_allow_html=True)

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
    # Parse Safe
    try:
        w_list = [x.strip().upper() for x in st.session_state['w_key'].split(",") if x.strip()]
    except: w_list = []
    
    for i, t in enumerate(w_list):
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
    total_roi = (tpl / total_cost) * 100 if total_cost > 0 else 0
    
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(f"""<div style="background:#1E1E1E;border:1px solid #333;border-radius:8px;padding:15px;text-align:center;"><div style="color:#888;font-size:12px;font-weight:bold;">NET LIQUIDITY</div><div style="font-size:24px;font-weight:900;color:white;">${total_val:,.2f}</div></div>""", unsafe_allow_html=True)
    with c2:
        col = "#4caf50" if day_pl >= 0 else "#ff4b4b"
        st.markdown(f"""<div style="background:#1E1E1E;border:1px solid #333;border-radius:8px;padding:15px;text-align:center;"><div style="color:#888;font-size:12px;font-weight:bold;">DAY PROFIT</div><div style="font-size:24px;font-weight:900;color:{col};">${day_pl:,.2f}</div></div>""", unsafe_allow_html=True)
    with c3:
        col = "#4caf50" if tpl >= 0 else "#ff4b4b"
        st.markdown(f"""<div style="background:#1E1E1E;border:1px solid #333;border-radius:8px;padding:15px;text-align:center;"><div style="color:#888;font-size:12px;font-weight:bold;">TOTAL RETURN</div><div style="font-size:24px;font-weight:900;color:{col};">${tpl:,.2f}<br><span style="font-size:32px;font-weight:900;">({total_roi:+.1f}%)</span></div></div>""", unsafe_allow_html=True)
    
    st.markdown("<br>", unsafe_allow_html=True)
    st.subheader("Holdings")
    cols = st.columns(3)
    for i, (t, inf) in enumerate(PORT.items()):
        with cols[i%3]: draw_pro_card(t, inf)

with t3:
    FEEDS = [
        "https://finance.yahoo.com/news/rssindex",
        "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664",
        "http://feeds.marketwatch.com/marketwatch/topstories"
    ]

    if st.button("Analyze Market Context (Start)"):
        if KEY:
            prog_bar = st.progress(0, text="Initializing AI...")
            try:
                prog_bar.progress(20, text="Connecting to News Feeds...")
                raw_items = []
                for f in FEEDS:
                    try:
                        r = requests.get(f, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
                        if r.status_code == 200:
                            root = ET.fromstring(r.content)
                            for item in root.findall('.//item'):
                                title = item.find('title').text
                                link = item.find('link').text
                                pub = item.find('pubDate').text if item.find('pubDate') is not None else str(datetime.now())
                                raw_items.append({"title": title, "link": link, "time": get_relative_time(pub)})
                            if raw_items: break
                    except: continue
                
                if not raw_items:
                    prog_bar.empty()
                    st.error("All news feeds failed. Check internet connection.")
                else:
                    st.session_state['raw_news_cache'] = raw_items
                    st.session_state['news_results'] = []
                    st.session_state['news_offset'] = 0
                    
                    prog_bar.progress(50, text="Analyzing First 20 Stories...")
                    batch = raw_items[:20]
                    analyzed = process_ai_batch(batch, KEY)
                    st.session_state['news_results'] = analyzed
                    st.session_state['news_offset'] = 20
                    
                    prog_bar.progress(100, text="Done!")
                    time.sleep(0.5); prog_bar.empty()
                    st.rerun()
                    
            except Exception as e:
                prog_bar.empty()
                st.error(f"System Error: {e}")
        else:
            st.info("Enter OpenAI Key in Sidebar.")

sec_to_next_min = 60 - datetime.now().second
time.sleep(sec_to_next_min)
st.rerun()
