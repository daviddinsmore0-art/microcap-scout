import streamlit as st, yfinance as yf, requests, time, re
from datetime import datetime
import streamlit.components.v1 as components
import pandas as pd
import altair as alt

try: st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="wide")
except: pass

# --- SESSION STATE (Memory) ---
if 'user_watchlist' not in st.session_state: 
    st.session_state['user_watchlist'] = "SPY, BTC-USD, TD.TO"
if 'news_cache' not in st.session_state: st.session_state['news_cache'] = []

# --- YOUR PORTFOLIO (Hardcoded for Safety) ---
PORT = {
    "HIVE": {"e": 3.19, "q": 50},
    "BAER": {"e": 1.86, "q": 120},
    "TX":   {"e": 38.10, "q": 40},
    "IMNN": {"e": 3.22, "q": 100},
    "RERE": {"e": 5.31, "q": 100}
}

# --- SIDEBAR ---
st.sidebar.header("⚡ Pulse")
if "OPENAI_KEY" in st.secrets: KEY = st.secrets["OPENAI_KEY"]
else: KEY = st.sidebar.text_input("OpenAI Key", type="password")

# Watchlist Input (Locked to Session State)
def update_list():
    st.session_state['user_watchlist'] = st.session_state.widget_input

u_in = st.sidebar.text_input("Add Tickers", 
                             value=st.session_state['user_watchlist'], 
                             key="widget_input", 
                             on_change=update_list)

WATCH = [x.strip().upper() for x in st.session_state['user_watchlist'].split(",") if x.strip()]

# --- DATA ENGINE (The "Pro" Logic) ---
def get_pro_data(s):
    try:
        tk = yf.Ticker(s)
        # 1. Price History (1 Month for RSI/Trend)
        h = tk.history(period="1mo", interval="1d")
        if h.empty: return None
        
        # Price Math
        p = h['Close'].iloc[-1]
        prev = h['Close'].iloc[-2]
        change = ((p - prev)/prev)*100
        
        # 2. RSI & Volume (Manual Math = Safe)
        delta = h['Close'].diff()
        up, down = delta.clip(lower=0), -1*delta.clip(upper=0)
        rs = up.ewm(com=13, adjust=False).mean() / down.ewm(com=13, adjust=False).mean()
        rsi = 100 - (100/(1+rs)).iloc[-1]
        
        vol = h['Volume'].iloc[-1]
        avg_vol = h['Volume'].mean()
        v_tag = "⚡ SURGE" if vol > avg_vol * 1.5 else "🌊 STEADY"
        v_str = f"{vol/1e6:.1f}M" if vol > 1e6 else f"{vol/1e3:.0f}K"

        # 3. Calendar (The logic that works)
        earn = "N/A"
        try:
            if tk.calendar and isinstance(tk.calendar, dict):
                dates = tk.calendar.get('Earnings Date')
                if dates: earn = dates[0].strftime("%b %d")
        except: pass

        return {
            "p": p, "ch": change, "rsi": int(rsi), "e": earn, 
            "v": v_str, "vt": v_tag, "h": h['Close']
        }
    except: return None

# --- HEADER & MARQUEE ---
c1, c2 = st.columns([3, 1])
with c1: st.title("⚡ Penny Pulse")
with c2: st.caption(f"Live: {datetime.now().strftime('%H:%M:%S')}")

# Ticker Tape
tape_html = ""
for t in ["SPY", "BTC-USD", "^IXIC"]:
    d = get_pro_data(t)
    if d:
        c = "#4caf50" if d['ch'] >= 0 else "#ff4b4b"
        tape_html += f"<span style='margin-right:20px; font-weight:bold;'>{t}: <span style='color:{c}'>${d['p']:,.2f}</span></span>"
st.markdown(f"<div style='background:#1e2127; padding:10px; border-radius:5px; border:1px solid #333; margin-bottom:20px;'>{tape_html}</div>", unsafe_allow_html=True)

# --- TABS ---
t1, t2, t3 = st.tabs(["🏠 Dashboard", "🚀 My Picks", "📰 Smart News"])

# 1. DASHBOARD (Watchlist)
with t1:
    cols = st.columns(3)
    for i, t in enumerate(WATCH):
        d = get_pro_data(t)
        with cols[i % 3]:
            if d:
                st.subheader(t)
                st.metric("Price", f"${d['p']:,.2f}", f"{d['ch']:+.2f}%")
                # The "Nice" Details
                st.caption(f"RSI: **{d['rsi']}** | Vol: **{d['v']}**")
                st.caption(f"📅 Earnings: **{d['e']}**")
                st.line_chart(d['h'], height=100)
            st.divider()

# 2. PORTFOLIO (The "Black Box" Header)
with t2:
    total_val, day_pl, total_pl = 0.0, 0.0, 0.0
    
    # Calculate Totals
    port_data = {} # Cache data to avoid double-fetching
    for t, inf in PORT.items():
        d = get_pro_data(t)
        if d:
            val = d['p'] * inf['q']
            cost = inf['e'] * inf['q']
            total_val += val
            total_pl += (val - cost)
            day_pl += (d['p'] - (d['p']/(1+d['ch']/100))) * inf['q']
            port_data[t] = d

    # Render "The Black Box"
    st.markdown(f"""
    <div style="background:#1e2127; padding:15px; border-radius:10px; border:1px solid #444; margin-bottom:20px;">
        <div style="display:flex; justify-content:space-around; text-align:center;">
            <div><div style="color:#888; font-size:12px;">Net Liq</div><div style="font-size:20px; font-weight:bold; color:white;">${total_val:,.2f}</div></div>
            <div><div style="color:#888; font-size:12px;">Day P/L</div><div style="font-size:20px; font-weight:bold; color:{'#4caf50' if day_pl>=0 else '#ff4b4b'};">{day_pl:+,.2f}</div></div>
            <div><div style="color:#888; font-size:12px;">Total P/L</div><div style="font-size:20px; font-weight:bold; color:{'#4caf50' if total_pl>=0 else '#ff4b4b'};">{total_pl:+,.2f}</div></div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Render Cards
    cols = st.columns(3)
    for i, (t, inf) in enumerate(PORT.items()):
        d = port_data.get(t)
        with cols[i % 3]:
            if d:
                st.markdown(f"### {t}")
                st.caption(f"{inf['q']} shares @ ${inf['e']}")
                st.metric("Price", f"${d['p']:,.2f}", f"{d['ch']:+.2f}%")
                st.markdown(f"**RSI:** {d['rsi']} | **Vol:** {d['v']}")
                st.markdown(f"📅 **{d['e']}**")
                st.line_chart(d['h'], height=80)
            st.divider()

# 3. NEWS ENGINE (With Browser Headers)
def fetch_news():
    # Mimic a real browser to stop "News Blocked"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/91.0.4472.124 Safari/537.36"}
    try:
        r = requests.get("https://finance.yahoo.com/news/rssindex", headers=headers, timeout=5)
        root = ET.fromstring(r.content)
        items = []
        for i in root.findall('.//item')[:20]:
            items.append({"title": i.find('title').text, "link": i.find('link').text})
        return items
    except: return []

# Regex Hunter
def hunt_ticker(txt):
    m = re.search(r'\(([A-Z]{2,5}(?:\.[A-Z]+)?)\)', txt)
    return m.group(1) if m else None

with t3:
    if st.button("Generate AI Report", type="primary"):
        with st.spinner("Scanning Wires..."):
            raw = fetch_news()
            if not raw: st.error("Feed Blocked - Try again in 30s")
            
            # 1. Regex Pass
            processed = []
            for r in raw:
                tick = hunt_ticker(r['title'])
                processed.append({"t": tick if tick else "NEWS", "txt": r['title'], "l": r['link']})
            
            # 2. AI Pass (Only if Key exists)
            if KEY:
                try:
                    from openai import OpenAI
                    prompt = "Analyze headlines. Return: Index|Signal(🟢/🔴/⚪)|Reason\n" + "\n".join([f"{i}. {x['txt']}" for i,x in enumerate(processed[:20])])
                    client = OpenAI(api_key=KEY)
                    resp = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role":"user", "content": prompt}])
                    lines = resp.choices[0].message.content.split('\n')
                    for l in lines:
                        p = l.split('|')
                        if len(p)>=3:
                            idx = int(re.sub(r'\D','',p[0]))
                            if idx < len(processed):
                                processed[idx]['sig'] = p[1]
                                processed[idx]['rsn'] = p[2]
                except: pass
            
            st.session_state['news_cache'] = processed

    # Display (Clean, No Dimming)
    if st.session_state['news_cache']:
        for n in st.session_state['news_cache']:
            sig = n.get('sig', '⚪')
            rsn = n.get('rsn', '')
            st.markdown(f"**{n['t']} {sig}** - [{n['txt']}]({n['l']})")
            if rsn: st.caption(rsn)
            st.divider()
