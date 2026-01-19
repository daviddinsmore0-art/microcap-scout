import streamlit as st, yfinance as yf, requests, re
from datetime import datetime
import pandas as pd
import altair as alt

# --- 1. YOUR PERMANENT DATA ---
# Your specific watchlist and portfolio, hardcoded so they NEVER delete.
MY_WATCHLIST = ["SPY", "BTC-USD", "TD.TO", "PLUG.CN", "VTX.V", "IVN.TO", "CCO.TO", "BN.TO"]

PORT = {
    "HIVE": {"e": 3.19, "q": 50},
    "BAER": {"e": 1.86, "q": 120},
    "TX":   {"e": 38.10, "q": 40},
    "IMNN": {"e": 3.22, "q": 100},
    "RERE": {"e": 5.31, "q": 100}
}

# --- APP SETUP ---
try: st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="wide")
except: pass

if 'news_cache' not in st.session_state: st.session_state['news_cache'] = []

# --- SIDEBAR ---
st.sidebar.header("⚡ Penny Pulse")
if "OPENAI_KEY" in st.secrets: KEY = st.secrets["OPENAI_KEY"]
else: KEY = st.sidebar.text_input("OpenAI Key", type="password")
st.sidebar.success("v24.3 UI Restored")

# --- DATA ENGINE (The v24.3 Logic) ---
def get_card_data(s):
    try:
        tk = yf.Ticker(s)
        h = tk.history(period="1mo", interval="1d")
        if h.empty: return None
        
        # Price Data
        curr = h['Close'].iloc[-1]
        prev = h['Close'].iloc[-2]
        chg = ((curr - prev)/prev)*100
        
        # High/Low for Range Bar (The Visual You Liked)
        day_h = h['High'].iloc[-1]
        day_l = h['Low'].iloc[-1]
        rng_pct = 50
        if day_h > day_l:
            rng_pct = max(0, min(100, (curr - day_l) / (day_h - day_l) * 100))
        
        # RSI
        delta = h['Close'].diff()
        up, down = delta.clip(lower=0), -1*delta.clip(upper=0)
        rs = up.ewm(com=13, adjust=False).mean() / down.ewm(com=13, adjust=False).mean()
        rsi = 100 - (100/(1+rs)).iloc[-1]
        
        # Volume
        vol = h['Volume'].iloc[-1]
        avg_vol = h['Volume'].mean()
        v_tag = "⚡ SURGE" if vol > avg_vol * 1.5 else "🌊 STEADY" if vol > avg_vol * 0.8 else "💤 QUIET"
        v_str = f"{vol/1e6:.1f}M" if vol > 1e6 else f"{vol/1e3:.0f}K"

        # Calendar (The "Kitchen Sink" Strategy)
        earn_date = "N/A"
        try:
            # Method 1: Calendar Dict
            if tk.calendar and isinstance(tk.calendar, dict):
                e = tk.calendar.get('Earnings Date')
                if e: earn_date = e[0].strftime("%b %d")
            
            # Method 2: Fallback
            if earn_date == "N/A":
                edf = tk.get_earnings_dates(limit=1)
                if edf is not None and not edf.empty:
                    earn_date = edf.index[0].strftime("%b %d")
        except: pass

        # Trend & Rating Logic
        trend = "BULL" if rsi > 50 else "BEAR"
        t_col = "#00FF00" if trend == "BULL" else "#FF4B4B"
        
        rating = "BUY" if rsi < 70 and trend == "BULL" else "HOLD"
        if rsi > 75: rating = "SELL"
        if rsi < 30: rating = "STRONG BUY"
        r_icon = "✅" if "BUY" in rating else "✋"

        # AI Bias (Simulated based on technicals)
        ai_bias = "BULLISH BIAS" if trend == "BULL" else "BEARISH BIAS"
        ai_dot = "🟢" if trend == "BULL" else "🔴"

        return {
            "p": curr, "ch": chg, "dh": day_h, "dl": day_l, "rng": rng_pct,
            "rsi": int(rsi), "vol": v_str, "vt": v_tag, "earn": earn_date,
            "trend": trend, "t_col": t_col, "rat": rating, "r_icon": r_icon,
            "ai_bias": ai_bias, "ai_dot": ai_dot, "chart": h['Close']
        }
    except: return None

# --- HEADER ---
c1, c2 = st.columns([3, 1])
with c1: st.title("⚡ Penny Pulse")
with c2: 
    st.caption(f"Last Update: {datetime.now().strftime('%H:%M:%S')}")
    st.markdown("<div style='background:#333; color:white; padding:5px; border-radius:5px; text-align:center;'>Next Update: <span style='color:#FF4B4B; font-weight:bold;'>60s</span></div>", unsafe_allow_html=True)

# Ticker Tape
tape = []
for t in ["SPY", "BTC-USD", "^IXIC"]:
    d = get_card_data(t)
    if d:
        c = "green" if d['ch']>=0 else "red"
        tape.append(f"{t}: :{c}[${d['p']:,.2f}]")
st.markdown(" **|** ".join(tape))
st.divider()

# --- TABS ---
t1, t2, t3 = st.tabs(["🏠 Dashboard", "🚀 My Picks", "📰 Market News"])

# --- DASHBOARD TAB ---
with t1:
    cols = st.columns(3)
    for i, t in enumerate(MY_WATCHLIST):
        d = get_card_data(t)
        with cols[i % 3]:
            if d:
                # 1. HEADER
                st.markdown(f"### {t}")
                st.metric("Price", f"${d['p']:,.2f}", f"{d['ch']:+.2f}%")
                
                # 2. AI BIAS (From v24.3)
                st.markdown(f"<div style='font-size:12px; margin-bottom:5px;'>🤖 AI: {d['ai_dot']} <span style='font-weight:bold; color:{'#ff4b4b' if 'BEAR' in d['ai_bias'] else '#4caf50'}'>{d['ai_bias']}</span></div>", unsafe_allow_html=True)

                # 3. RANGE BAR
                st.markdown(f"""
                <div style="display:flex; align-items:center; font-size:12px; color:#888; margin-bottom:10px;">
                    <span style="margin-right:5px;">L</span>
                    <div style="flex-grow:1; height:6px; background:#333; border-radius:3px; overflow:hidden;">
                        <div style="width:{d['rng']}%; height:100%; background: linear-gradient(90deg, #ff4b4b, #4caf50);"></div>
                    </div>
                    <span style="margin-left:5px;">H</span>
                </div>
                """, unsafe_allow_html=True)
                
                # 4. DETAILS (Trend | Rating | Calendar)
                st.markdown(f"""
                <div style='font-size:14px; line-height:1.6;'>
                    <b>Trend:</b> <span style='color:{d['t_col']}; font-weight:bold;'>{d['trend']}</span> 
                    | {d['r_icon']} <b>{d['rat']}</b> 
                    | 📅 <b>{d['earn']}</b>
                </div>
                <div style='font-size:14px;'>
                    <b>Vol:</b> {d['vol']} ({d['vt']})
                </div>
                <div style='font-size:14px; margin-bottom:10px;'>
                    <b>RSI:</b> {d['rsi']} ({'🔥 HOT' if d['rsi']>70 else '❄️ COLD' if d['rsi']<30 else '😐 OK'})
                </div>
                """, unsafe_allow_html=True)
                
                with st.expander("📉 Chart"):
                    st.line_chart(d['chart'])
            st.divider()

# --- PORTFOLIO TAB ---
with t2:
    total_val, day_pl, total_pl = 0.0, 0.0, 0.0
    port_items = []
    
    # Calculate
    for t, inf in PORT.items():
        d = get_card_data(t)
        if d:
            val = d['p'] * inf['q']
            cost = inf['e'] * inf['q']
            total_val += val
            total_pl += (val - cost)
            day_pl += (d['p'] - (d['p']/(1+d['ch']/100))) * inf['q']
            port_items.append((t, inf, d))

    # The Black Summary Box
    st.markdown(f"""
    <div style="background:#1e2127; padding:15px; border-radius:10px; border:1px solid #444; margin-bottom:20px;">
        <div style="display:flex; justify-content:space-around; text-align:center;">
            <div><div style="color:#888; font-size:12px;">Net Liq</div><div style="font-size:20px; font-weight:bold; color:white;">${total_val:,.2f}</div></div>
            <div><div style="color:#888; font-size:12px;">Day P/L</div><div style="font-size:20px; font-weight:bold; color:{'#4caf50' if day_pl>=0 else '#ff4b4b'};">{day_pl:+,.2f}</div></div>
            <div><div style="color:#888; font-size:12px;">Total P/L</div><div style="font-size:20px; font-weight:bold; color:{'#4caf50' if total_pl>=0 else '#ff4b4b'};">{total_pl:+,.2f}</div></div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Cards
    cols = st.columns(3)
    for i, (t, inf, d) in enumerate(port_items):
        with cols[i % 3]:
            st.markdown(f"### {t}")
            st.caption(f"{inf['q']} shares @ ${inf['e']}")
            st.metric("Price", f"${d['p']:,.2f}", f"{d['ch']:+.2f}%")
            st.markdown(f"""
            <div style='font-size:14px; margin-top:5px;'>
                <b>Trend:</b> <span style='color:{d['t_col']}'>{d['trend']}</span> | 📅 <b>{d['earn']}</b>
            </div>
            """, unsafe_allow_html=True)
            st.line_chart(d['chart'], height=80)
            st.divider()

# --- NEWS ENGINE ---
def fetch_news():
    # Updated User-Agent to stop blocking
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"}
    try:
        r = requests.get("https://finance.yahoo.com/news/rssindex", headers=headers, timeout=5)
        root = ET.fromstring(r.content)
        items = []
        for i in root.findall('.//item')[:20]:
            t = i.find('title').text
            l = i.find('link').text
            d = i.find('description').text if i.find('description') is not None else ""
            items.append({"t": t, "l": l, "d": d})
        return items
    except: return []

# Ticker Hunter (Regex)
def hunt(txt):
    m = re.search(r'\(([A-Z]{2,5}(?:\.[A-Z]+)?)\)', txt)
    if m: return m.group(1)
    if "BITCOIN" in txt.upper(): return "BTC"
    if "NVIDIA" in txt.upper(): return "NVDA"
    return "NEWS"

with t3:
    st.header("🚨 Global AI Wire")
    if st.button("Generate AI Report", type="primary"):
        with st.spinner("Scanning..."):
            raw = fetch_news()
            if not raw: 
                st.error("News feed blocked. Try again in 30s.")
            else:
                results = []
                for r in raw:
                    tick = hunt(r['t'] + " " + r['d'])
                    results.append({"tick": tick, "txt": r['t'], "lnk": r['l'], "sig": "⚪"})
                
                if KEY:
                    try:
                        from openai import OpenAI
                        p_list = "\n".join([f"{i}. {x['txt']}" for i,x in enumerate(results[:15])])
                        prompt = "Analyze. Return: Index|Signal(🟢/🔴/⚪)|Reason. \n" + p_list
                        
                        client = OpenAI(api_key=KEY)
                        resp = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role":"user", "content": prompt}])
                        
                        for l in resp.choices[0].message.content.split('\n'):
                            p = l.split('|')
                            if len(p) >= 3:
                                idx = int(re.sub(r'\D','',p[0]))
                                if idx < len(results):
                                    results[idx]['sig'] = p[1].strip()
                                    results[idx]['rsn'] = p[2].strip()
                    except: pass
                
                st.session_state['news_cache'] = results

    if st.session_state['news_cache']:
        for n in st.session_state['news_cache']:
            st.markdown(f"**{n['tick']} {n['sig']}** - [{n['txt']}]({n['lnk']})")
            if 'rsn' in n: st.caption(n['rsn'])
            st.divider()
