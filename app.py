import streamlit as st, yfinance as yf, requests, time, xml.etree.ElementTree as ET
from datetime import datetime
import streamlit.components.v1 as components
import pandas as pd
import altair as alt

# --- APP CONFIG ---
try: st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="wide")
except: pass

# --- SESSION STATE (The Memory) ---
# This ensures your watchlist stays put when you refresh
if 'user_watchlist' not in st.session_state: 
    st.session_state['user_watchlist'] = "SPY, BTC-USD, TD.TO"
if 'news_data' not in st.session_state: st.session_state['news_data'] = []

# --- PORTFOLIO (Your Specific Data) ---
PORT = {
    "HIVE": {"e": 3.19, "q": 50},
    "BAER": {"e": 1.86, "q": 120},
    "TX":   {"e": 38.10, "q": 40},
    "IMNN": {"e": 3.22, "q": 100},
    "RERE": {"e": 5.31, "q": 100}
}

# --- SIDEBAR (Restored Control) ---
st.sidebar.header("⚡ Penny Pulse")
if "OPENAI_KEY" in st.secrets: KEY = st.secrets["OPENAI_KEY"]
else: KEY = st.sidebar.text_input("OpenAI Key", type="password")

# This binds the input box to the session state so it remembers your list
def update_list():
    st.session_state['user_watchlist'] = st.session_state.widget_input

u_in = st.sidebar.text_input("Add Tickers (Comma Separated)", 
                             value=st.session_state['user_watchlist'], 
                             key="widget_input", 
                             on_change=update_list)

# Combine Watchlist + Portfolio
WATCH = [x.strip().upper() for x in st.session_state['user_watchlist'].split(",") if x.strip()]
ALL_TICKERS = list(set(WATCH + list(PORT.keys())))

# --- DATA ENGINE (Reliable Version) ---
def get_data(s):
    try:
        tk = yf.Ticker(s)
        # 1. Price History (Safe)
        h = tk.history(period="1mo", interval="1d")
        if h.empty: return None
        
        p = h['Close'].iloc[-1]
        prev = h['Close'].iloc[-2]
        change = ((p - prev)/prev)*100
        
        # 2. RSI (Manual Math = No API Blocks)
        delta = h['Close'].diff()
        up, down = delta.clip(lower=0), -1*delta.clip(upper=0)
        rs = up.ewm(com=13, adjust=False).mean() / down.ewm(com=13, adjust=False).mean()
        rsi = 100 - (100/(1+rs)).iloc[-1]
        
        # 3. Calendar (The "Yesterday" Logic)
        # We try to grab the date. If Yahoo blocks it, we show nothing (no crash).
        earn = ""
        try:
            cal = tk.calendar
            if isinstance(cal, dict) and 'Earnings Date' in cal:
                dte = cal['Earnings Date'][0]
                earn = dte.strftime("%b %d")
        except: pass

        return {"p": p, "ch": change, "rsi": int(rsi), "e": earn, "h": h['Close']}
    except: return None

# --- NEWS ENGINE (Robust) ---
def fetch_news():
    try:
        # Using a reliable RSS feed
        url = "https://finance.yahoo.com/news/rssindex"
        r = requests.get(url, timeout=5)
        root = ET.fromstring(r.content)
        items = []
        for i in root.findall('.//item')[:20]:
            title = i.find('title').text
            link = i.find('link').text
            items.append({"title": title, "link": link})
        return items
    except: return []

# --- DASHBOARD UI ---
st.title("⚡ Penny Pulse")
t1, t2, t3 = st.tabs(["📊 Watchlist", "🚀 Portfolio", "📰 News"])

with t1:
    cols = st.columns(3)
    for i, t in enumerate(WATCH):
        d = get_data(t)
        with cols[i % 3]:
            if d:
                st.metric(t, f"${d['p']:,.2f}", f"{d['ch']:+.2f}%")
                st.caption(f"RSI: {d['rsi']} | Earn: {d['e'] if d['e'] else '---'}")
                st.line_chart(d['h'], height=100)
            st.divider()

with t2:
    total_val = 0.0
    for t, inf in PORT.items():
        d = get_data(t)
        if d:
            val = d['p'] * inf['q']
            cost = inf['e'] * inf['q']
            gain = val - cost
            total_val += val
            
            c1, c2 = st.columns([2, 1])
            with c1:
                st.subheader(f"{t} ({inf['q']} @ ${inf['e']})")
                st.metric("Value", f"${val:,.2f}", f"{gain:+.2f}")
                if d['e']: st.caption(f"📅 Earnings: {d['e']}")
            with c2:
                st.line_chart(d['h'], height=80)
            st.divider()

with t3:
    if st.button("Refresh News", type="primary"):
        with st.spinner("Fetching..."):
            raw = fetch_news()
            if KEY and raw:
                try:
                    from openai import OpenAI
                    client = OpenAI(api_key=KEY)
                    # Simple, unbreakable prompt
                    prompt = "Identify the ticker for each headline. If none, skip. Format: TICKER - HEADLINE. \n" + "\n".join([x['title'] for x in raw[:15]])
                    resp = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role":"user", "content": prompt}])
                    st.session_state['news_data'] = resp.choices[0].message.content
                except: st.error("AI Error - Check Key")
            elif raw:
                st.session_state['news_data'] = "\n".join([f"- {x['title']}" for x in raw])
            else:
                st.error("News feed blocked.")
                
    if st.session_state['news_data']:
        st.markdown(st.session_state['news_data'])
