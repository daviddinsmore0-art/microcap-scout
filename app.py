import streamlit as st, yfinance as yf, requests, re, time
from datetime import datetime
import pandas as pd
import altair as alt

# --- 1. PERMANENT WATCHLIST (EDIT THIS LINE!) ---
# Type your tickers inside the quotes, separated by commas.
# This ensures they NEVER get deleted, even if the internet cuts out.
MY_WATCHLIST = "HIVE, BAER, TX, IMNN, RERE, PLUG.CN, VTX.V, TD.TO"

# --- APP SETUP ---
try: st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="wide")
except: pass

if 'news_results' not in st.session_state: st.session_state['news_results'] = []
if 'news_run' not in st.session_state: st.session_state['news_run'] = False

# --- SIDEBAR ---
st.sidebar.header("⚡ Pulse Settings")
if "OPENAI_KEY" in st.secrets: KEY = st.secrets["OPENAI_KEY"]
else: KEY = st.sidebar.text_input("OpenAI Key", type="password")

# Use the Hardcoded List
WATCH = [x.strip().upper() for x in MY_WATCHLIST.split(",") if x.strip()]
st.sidebar.info(f"Loaded {len(WATCH)} tickers from code.")

# --- DATA ENGINE ---
def get_data(s):
    try:
        tk = yf.Ticker(s)
        h = tk.history(period="1mo", interval="1d")
        if h.empty: return None
        
        # Price
        p = h['Close'].iloc[-1]
        prev = h['Close'].iloc[-2]
        dp = ((p - prev)/prev)*100
        
        # RSI
        delta = h['Close'].diff()
        up, down = delta.clip(lower=0), -1*delta.clip(upper=0)
        rs = up.ewm(com=13, adjust=False).mean() / down.ewm(com=13, adjust=False).mean()
        rsi = 100 - (100/(1+rs)).iloc[-1]
        
        # Vol
        vol = h['Volume'].iloc[-1]
        avg_vol = h['Volume'].mean()
        vol_str = f"{vol/1e6:.1f}M" if vol > 1e6 else f"{vol/1e3:.0f}K"
        v_tag = "⚡ SURGE" if vol > avg_vol * 1.5 else "🌊 STEADY"

        # Calendar (The "Kitchen Sink" Attempt)
        earn_str = ""
        try:
            # Try 1: Calendar Dict
            if tk.calendar and isinstance(tk.calendar, dict):
                dates = tk.calendar.get('Earnings Date')
                if dates: earn_str = dates[0].strftime("%b %d")
            
            # Try 2: Info Timestamp (often not blocked)
            if not earn_str and 'earningsTimestamp' in tk.info:
                ts = tk.info['earningsTimestamp']
                earn_str = datetime.fromtimestamp(ts).strftime("%b %d")
            
            # Try 3: Earnings Dates DataFrame
            if not earn_str:
                e_df = tk.get_earnings_dates(limit=1)
                if e_df is not None and not e_df.empty:
                    earn_str = e_df.index[0].strftime("%b %d")
        except: pass
        
        if not earn_str: earn_str = "N/A"

        return {
            "p": p, "d": dp, "v": vol_str, "vt": v_tag, "rsi": int(rsi), 
            "e": earn_str, "h": h['Close']
        }
    except: return None

# --- HEADER ---
st.title("⚡ Penny Pulse")
st.caption(f"Last Update: {datetime.now().strftime('%H:%M:%S')}")

# --- DASHBOARD ---
t1, t2 = st.tabs(["📊 Dashboard", "📰 Smart News"])

with t1:
    cols = st.columns(3)
    for i, t in enumerate(WATCH):
        d = get_data(t)
        with cols[i % 3]:
            if d:
                st.subheader(t)
                st.metric("Price", f"${d['p']:,.2f}", f"{d['d']:+.2f}%")
                
                # Visual Bar for Calendar/RSI
                c_color = "#00FF00" if "N/A" not in d['e'] else "#555"
                r_color = "red" if d['rsi']>70 else "green" if d['rsi']<30 else "orange"
                
                st.markdown(f"""
                <div style='font-size:14px; margin-bottom:5px;'>
                <b>Vol:</b> {d['v']} ({d['vt']}) <br>
                <b>RSI:</b> <span style='color:{r_color}; font-weight:bold;'>{d['rsi']}</span> <br>
                <b>Earn:</b> <span style='color:{c_color}; font-weight:bold;'>{d['e']}</span>
                </div>
                """, unsafe_allow_html=True)
                
                st.line_chart(d['h'], height=100)
                st.divider()
            else:
                st.error(f"Could not load {t}")

# --- NEWS ENGINE (Browser Mimic) ---
def get_news():
    # Headers that look like a real Chrome browser to avoid blocks
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }
    # Using a reliable aggregator that usually includes full descriptions
    url = "https://finance.yahoo.com/news/rssindex"
    try:
        r = requests.get(url, headers=headers, timeout=10)
        root = ET.fromstring(r.content)
        items = []
        for i in root.findall('.//item')[:20]:
            title = i.find('title').text
            link = i.find('link').text
            desc = i.find('description').text if i.find('description') is not None else ""
            items.append({"title": title, "link": link, "desc": desc})
        return items
    except: return []

# REGEX HUNTER (Looks for (TICKER) patterns)
def hunt(text):
    # Pattern: Uppercase, 2-5 letters, optional .suffix, inside ()
    # e.g., (PLUG), (PLUG.CN), (NVDA)
    m = re.search(r'\(([A-Z]{2,5}(?:\.[A-Z]{1,2})?)\)', text)
    if m: return m.group(1)
    
    # Keyword fallback
    if "BITCOIN" in text.upper(): return "BTC-USD"
    if "GOLD" in text.upper(): return "GC=F"
    return "NEWS"

with t2:
    st.write("Scan the latest wires for actionable signals.")
    
    if st.button("Generate AI Report", type="primary"):
        # No spinner that blocks UI, just a status text
        status = st.empty()
        status.text("Fetching feeds...")
        
        raw = get_news()
        if not raw:
            st.error("Connection blocked. Try again in 60s.")
        else:
            status.text("Analyzing text...")
            results = []
            
            # 1. Regex Pass (Instant)
            for r in raw:
                combo = r['title'] + " " + r['desc']
                found = hunt(combo)
                r['ticker'] = found
                r['signal'] = "⚪"
                results.append(r)
            
            # 2. AI Pass (If Key exists)
            if KEY:
                try:
                    from openai import OpenAI
                    # We format the prompt to be extremely direct
                    prompt = "Analyze these headlines. Return ONLY: Index|Signal(🟢/🔴/⚪)|Reason. \n"
                    for i, r in enumerate(results[:20]):
                        prompt += f"{i}. {r['title']}\n"
                    
                    client = OpenAI(api_key=KEY)
                    resp = client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[{"role":"user", "content": prompt}],
                        max_tokens=500
                    )
                    
                    lines = resp.choices[0].message.content.split('\n')
                    for l in lines:
                        parts = l.split('|')
                        if len(parts) >= 3:
                            try:
                                idx = int(re.sub(r'\D', '', parts[0]))
                                if idx < len(results):
                                    results[idx]['signal'] = parts[1].strip()
                                    results[idx]['reason'] = parts[2].strip()
                            except: pass
                except: pass
            
            st.session_state['news_results'] = results
            st.session_state['news_run'] = True
            status.empty() # Clear status message
            st.rerun()

    # DISPLAY
    if st.session_state['news_run']:
        for n in st.session_state['news_results']:
            # Only show if we found a ticker OR if AI marked it significant
            if n['ticker'] != "NEWS" or n['signal'] != "⚪":
                st.markdown(f"**{n['ticker']} {n['signal']}** [{n['title']}]({n['link']})")
                st.caption(f"{n['reason']}")
                st.divider()
            else:
                # Optional: Show generic news in grey
                st.markdown(f"<span style='color:#777'>{n['title']}</span>", unsafe_allow_html=True)
                st.divider()
