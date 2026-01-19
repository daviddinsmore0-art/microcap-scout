import streamlit as st, yfinance as yf, requests, re
from datetime import datetime
import pandas as pd
import altair as alt

# --- 1. YOUR PERMANENT DATA ---
# Your list is locked here. It will never delete.
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
st.sidebar.success("AI-First Mode Active")

# --- DATA ENGINE (v24.3 Logic) ---
def get_card_data(s):
    try:
        tk = yf.Ticker(s)
        h = tk.history(period="1mo", interval="1d")
        if h.empty: return None
        
        # Price
        curr = h['Close'].iloc[-1]
        prev = h['Close'].iloc[-2]
        chg = ((curr - prev)/prev)*100
        
        # Range Bar
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
        v_tag = "⚡ SURGE" if vol > avg_vol * 1.5 else "🌊 STEADY"
        v_str = f"{vol/1e6:.1f}M" if vol > 1e6 else f"{vol/1e3:.0f}K"

        # Calendar
        earn_date = ""
        try:
            if tk.calendar and isinstance(tk.calendar, dict):
                e = tk.calendar.get('Earnings Date')
                if e: earn_date = e[0].strftime("%b %d")
        except: pass

        # Trend
        trend = "BULL" if rsi > 50 else "BEAR"
        t_col = "#00FF00" if trend == "BULL" else "#FF4B4B"
        
        rating = "BUY" if rsi < 70 and trend == "BULL" else "HOLD"
        if rsi > 75: rating = "SELL"
        if rsi < 30: rating = "STRONG BUY"
        r_icon = "✅" if "BUY" in rating else "✋"

        return {
            "p": curr, "ch": chg, "rng": rng_pct, "rsi": int(rsi), 
            "vol": v_str, "vt": v_tag, "earn": earn_date,
            "trend": trend, "t_col": t_col, "rat": rating, "r_icon": r_icon,
            "chart": h['Close']
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
t1, t2 = st.tabs(["🏠 Dashboard", "📰 Market News"])

with t1:
    cols = st.columns(3)
    for i, t in enumerate(MY_WATCHLIST):
        d = get_card_data(t)
        with cols[i % 3]:
            if d:
                st.markdown(f"### {t}")
                st.metric("Price", f"${d['p']:,.2f}", f"{d['ch']:+.2f}%")
                
                # Visual Bar
                st.markdown(f"""
                <div style="display:flex; align-items:center; font-size:12px; color:#888; margin-bottom:10px;">
                    <span style="margin-right:5px;">L</span>
                    <div style="flex-grow:1; height:6px; background:#333; border-radius:3px; overflow:hidden;">
                        <div style="width:{d['rng']}%; height:100%; background: linear-gradient(90deg, #ff4b4b, #4caf50);"></div>
                    </div>
                    <span style="margin-left:5px;">H</span>
                </div>
                """, unsafe_allow_html=True)
                
                # Details
                earn_html = f"| 📅 <b>{d['earn']}</b>" if d['earn'] else ""
                st.markdown(f"""
                <div style='font-size:14px; line-height:1.6;'>
                    <b>Trend:</b> <span style='color:{d['t_col']}; font-weight:bold;'>{d['trend']}</span> 
                    | {d['r_icon']} <b>{d['rat']}</b> {earn_html}
                </div>
                <div style='font-size:14px; margin-bottom:10px;'>
                    <b>Vol:</b> {d['vol']} ({d['vt']}) | <b>RSI:</b> {d['rsi']}
                </div>
                """, unsafe_allow_html=True)
                
                with st.expander("📉 Chart"):
                    st.line_chart(d['chart'])
            st.divider()

    # PORTFOLIO SECTION
    st.subheader("🚀 My Picks")
    total_val, day_pl, total_pl = 0.0, 0.0, 0.0
    for t, inf in PORT.items():
        d = get_card_data(t)
        if d:
            val = d['p'] * inf['q']
            cost = inf['e'] * inf['q']
            total_val += val
            total_pl += (val - cost)
            day_pl += (d['p'] - (d['p']/(1+d['ch']/100))) * inf['q']

    st.markdown(f"""
    <div style="background:#1e2127; padding:15px; border-radius:10px; border:1px solid #444; margin-bottom:20px;">
        <div style="display:flex; justify-content:space-around; text-align:center;">
            <div><div style="color:#888; font-size:12px;">Net Liq</div><div style="font-size:20px; font-weight:bold; color:white;">${total_val:,.2f}</div></div>
            <div><div style="color:#888; font-size:12px;">Day P/L</div><div style="font-size:20px; font-weight:bold; color:{'#4caf50' if day_pl>=0 else '#ff4b4b'};">{day_pl:+,.2f}</div></div>
            <div><div style="color:#888; font-size:12px;">Total P/L</div><div style="font-size:20px; font-weight:bold; color:{'#4caf50' if total_pl>=0 else '#ff4b4b'};">{total_pl:+,.2f}</div></div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    cols = st.columns(3)
    for i, (t, inf) in enumerate(PORT.items()):
        d = get_card_data(t)
        if d:
            with cols[i % 3]:
                st.markdown(f"**{t}** | {inf['q']} @ ${inf['e']}")
                st.metric("Price", f"${d['p']:,.2f}", f"{d['ch']:+.2f}%")
                st.caption(f"RSI: {d['rsi']} | Vol: {d['vol']}")
                st.divider()

# --- NEWS ENGINE (Premium Connection) ---
def fetch_news():
    # Latest Chrome User-Agent to prevent blocking
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"}
    try:
        r = requests.get("https://finance.yahoo.com/news/rssindex", headers=headers, timeout=5)
        # Using Regex to be robust against XML errors
        import xml.etree.ElementTree as ET
        root = ET.fromstring(r.content)
        items = []
        for i in root.findall('.//item')[:20]:
            t = i.find('title').text
            l = i.find('link').text
            d = i.find('description').text if i.find('description') is not None else ""
            items.append({"txt": t, "lnk": l, "desc": d})
        return items
    except: return []

with t2:
    st.header("🚨 Global AI Wire")
    if st.button("Generate AI Report", type="primary"):
        with st.spinner("AI Analysis in progress..."):
            raw = fetch_news()
            
            # Direct AI Pass - No Regex filtering
            if KEY and raw:
                try:
                    from openai import OpenAI
                    # We send TITLE + DESCRIPTION to ensure AI sees the tickers
                    p_list = "\n".join([f"{i}. {x['txt']} | {x['desc'][:200]}" for i,x in enumerate(raw[:15])])
                    
                    # The "Expert" Prompt
                    prompt = """
                    Analyze these financial news items.
                    1. IDENTIFY the specific ticker (e.g. 'Energy Plug' -> 'PLUG.CN'). Look closely at text like (PLUG.CN).
                    2. If the ticker is generic (like 'Bitcoin'), use the symbol (BTC-USD).
                    3. Determine sentiment (🟢/🔴/⚪).
                    4. Return ONLY: Index|Ticker|Signal|Reason
                    """
                    
                    client = OpenAI(api_key=KEY)
                    resp = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role":"system", "content": prompt}, {"role":"user", "content": p_list}])
                    
                    processed = []
                    lines = resp.choices[0].message.content.split('\n')
                    for l in lines:
                        p = l.split('|')
                        if len(p) >= 4:
                            try:
                                idx = int(re.sub(r'\D','',p[0]))
                                if idx < len(raw):
                                    item = raw[idx]
                                    processed.append({
                                        "tick": p[1].strip(),
                                        "sig": p[2].strip(),
                                        "rsn": p[3].strip(),
                                        "txt": item['txt'],
                                        "lnk": item['lnk']
                                    })
                            except: pass
                    st.session_state['news_cache'] = processed
                except Exception as e: st.error(f"OpenAI Error: {e}")
            elif not raw:
                st.error("News feed connection failed.")
            else:
                st.warning("Please enter OpenAI Key.")

    # Display Results
    if st.session_state['news_cache']:
        for n in st.session_state['news_cache']:
            st.markdown(f"**{n['tick']} {n['sig']}** - [{n['txt']}]({n['lnk']})")
            st.caption(n['rsn'])
            st.divider()
