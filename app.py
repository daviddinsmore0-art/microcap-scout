import streamlit as st, yfinance as yf, pandas as pd, altair as alt, time
from datetime import datetime, timedelta
import streamlit.components.v1 as components
import os
import base64

# --- 1. SETUP ---
try: st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="wide")
except: pass 

# *** CONFIG ***
ADMIN_PASSWORD = "admin123"
LOGO_PATH = "logo.png"

# --- 2. HELPERS (Defined First to Prevent Crash) ---
def get_base64_image(image_path):
    if os.path.exists(image_path):
        with open(image_path, "rb") as img_file: return base64.b64encode(img_file.read()).decode()
    return None

def inject_wake_lock(enable):
    if enable: components.html("""<script>navigator.wakeLock.request('screen').catch(console.log);</script>""", height=0) 

# --- 3. SESSION STATE (RAM ONLY) ---
if 'init' not in st.session_state:
    st.session_state['init'] = True
    # Default List (Hardcoded because no persistence)
    st.session_state['w_input'] = "TD.TO, CCO.TO, IVN.TO, BN.TO, HIVE, SPY, NKE"
    
    # Default Portfolio (Hardcoded)
    st.session_state['portfolio'] = {
        "HIVE": {"e": 3.19, "q": 50}, 
        "BAER": {"e": 1.86, "q": 100}, 
        "TX": {"e": 38.10, "q": 40}, 
        "IMNN": {"e": 3.22, "q": 100}, 
        "RERE": {"e": 5.31, "q": 100}
    }
    st.session_state['keep_on'] = False

# --- 4. DATA ENGINE (Direct + Heavy Lifter) ---
def get_pro_data(s):
    try:
        tk = yf.Ticker(s)
        
        # 1. PRICE (Daily - Guaranteed Success)
        # This is the "Heavy Lifter" fix. We get the daily price first so the card is never empty.
        daily = tk.history(period="1d")
        if daily.empty: return None 
        
        p_live = daily['Close'].iloc[-1]
        p_open = daily['Open'].iloc[-1]
        
        # 2. CHART (Intraday - Best Effort)
        # We try to get the 5m chart. If it fails (timeout), we just skip the chart but keep the price.
        try:
            intraday = tk.history(period="1d", interval="5m", prepost=False)
        except: intraday = pd.DataFrame()
            
        if not intraday.empty:
            chart_source = intraday
            p_live = intraday['Close'].iloc[-1] # More accurate live price
            prev_close = intraday['Close'].iloc[0] 
        else:
            chart_source = daily # Fallback to flat line
            prev_close = p_open

        # Math
        d_val = p_live - prev_close
        d_pct = (d_val / prev_close) * 100 if prev_close != 0 else 0
        
        # Simple Metadata (No Caching to avoid I/O lock)
        try: name = tk.info.get('longName', s)
        except: name = s
        
        # Chart Builder
        chart = chart_source['Close'].reset_index()
        chart.columns = ['T', 'Stock']
        chart['Idx'] = range(len(chart))
        chart['Stock'] = ((chart['Stock'] - chart['Stock'].iloc[0])/chart['Stock'].iloc[0])*100
        
        trend = "BULL" if d_pct >= 0 else "BEAR"
        
        return {
            "p": p_live, "d": d_pct, "tr": trend,
            "chart": chart, "name": name,
            "ai": f"{'🟢' if trend=='BULL' else '🔴'} {trend} BIAS"
        }
    except: return None

# --- 5. SIDEBAR ---
with st.sidebar:
    st.header("⚡ Penny Pulse")
    
    # Simple Input (Resets on reload)
    new_w = st.text_input("Tickers", value=st.session_state.w_input)
    if new_w != st.session_state.w_input:
        st.session_state.w_input = new_w
        st.rerun()
    
    if st.text_input("Admin Key", type="password") == ADMIN_PASSWORD:
        with st.expander("💼 Portfolio Admin", expanded=True):
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
    st.checkbox("Keep Screen On", key="keep_on")

inject_wake_lock(st.session_state['keep_on'])

# --- 6. MAIN UI ---
# Header (With Logo Logic)
img_code = get_base64_image(LOGO_PATH)
if img_code:
    img_html = f'<img src="data:image/png;base64,{img_code}" style="max-height:100px; display:block; margin:0 auto;">'
else:
    img_html = "<h1 style='text-align:center;'>⚡ Penny Pulse</h1>"

t_str = (datetime.utcnow()-timedelta(hours=5)+timedelta(minutes=1)).strftime('%H:%M:%S')
st.markdown(f"""<div style="background:black;border:1px solid #333;border-radius:10px;padding:20px;text-align:center;margin-bottom:20px;">{img_html}<div style="color:#888;font-size:12px;margin-top:10px;">NEXT PULSE: <span style="color:#4caf50; font-weight:bold;">{t_str} ET</span></div></div>""", unsafe_allow_html=True)

# Tabs
t1, t2 = st.tabs(["🏠 Dashboard", "🚀 My Picks"])

def draw_card(t, port=None):
    d = get_pro_data(t)
    if not d:
        st.warning(f"⚠️ {t}: Data N/A")
        return

    col_hex = "#4caf50" if d['d']>=0 else "#ff4b4b"
    col_str = "green" if d['d']>=0 else "red"
    
    c_head, c_price = st.columns([2, 1])
    with c_head:
        st.markdown(f"### {d['name']}")
        st.caption(f"{t}")
    with c_price:
        st.metric(label="", value=f"${d['p']:,.2f}", delta=f"{d['d']:.2f}%")

    if port:
        gain = (d['p'] - port['e']) * port['q']
        st.info(f"Qty: {port['q']} | Avg: ${port['e']} | Gain: ${gain:,.2f}")

    st.markdown(f"**TREND:** :{col_str}[**{d['tr']}**]", unsafe_allow_html=True)
    
    chart = alt.Chart(d['chart']).mark_line(color=col_hex).encode(x=alt.X('Idx', axis=None), y=alt.Y('Stock', axis=None)).properties(height=70)
    st.altair_chart(chart, use_container_width=True)
    st.divider()

# Dashboard Tab
with t1:
    cols = st.columns(3)
    W = [x.strip().upper() for x in st.session_state.w_input.split(",") if x.strip()]
    for i, t in enumerate(W):
        with cols[i%3]: draw_card(t)

# Portfolio Tab
with t2:
    PORT = st.session_state['portfolio']
    tv = sum(get_pro_data(tk)['p']*inf['q'] for tk, inf in PORT.items() if get_pro_data(tk))
    tc = sum(inf['e']*inf['q'] for inf in PORT.values())
    profit = tv - tc
    st.markdown(f"""<h2 style='text-align:center; color:{'#4caf50' if profit>=0 else '#ff4b4b'}'>TOTAL RETURN: ${profit:+,.2f}</h2>""", unsafe_allow_html=True)
    
    cols = st.columns(3)
    for i, (t, inf) in enumerate(PORT.items()):
        with cols[i%3]: draw_card(t, inf)

time.sleep(60)
st.rerun()
