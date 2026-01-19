import streamlit as st, yfinance as yf, requests, re, time
from datetime import datetime
import streamlit.components.v1 as components
import pandas as pd

# --- 1. PERMANENT WATCHLIST ---
# Your list is locked here.
MY_WATCHLIST = ["SPY", "BTC-USD", "TD.TO", "PLUG.CN", "VTX.V", "IVN.TO", "HIVE", "BAER", "TX", "IMNN", "RERE"]

# --- APP CONFIG ---
try: st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="wide")
except: pass

if 'news_cache' not in st.session_state: st.session_state['news_cache'] = []

# --- SIDEBAR ---
st.sidebar.header("⚡ Penny Pulse")
if "OPENAI_KEY" in st.secrets: KEY = st.secrets["OPENAI_KEY"]
else: KEY = st.sidebar.text_input("OpenAI Key", type="password")

# --- DATA ENGINE ---
def get_card_data(s):
    try:
        tk = yf.Ticker(s)
        # 1. Price History
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

        # Calendar (Robust Method)
        earn_date = ""
        try:
            # Try the basic calendar first
            if tk.calendar and isinstance(tk.calendar, dict):
                e = tk.calendar.get('Earnings Date')
                if e: earn_date = e[0].strftime("%b %d")
            
            # If empty, try the dataframe method (often works for TSX stocks)
            if not earn_date:
                edt = tk.get_earnings_dates(limit=1)
                if edt is not None and not edt.empty:
                    earn_date = edt.index[0].strftime("%b %d")
        except: pass

        # Trend & Rating
        trend = "BULL" if rsi > 50 else "BEAR"
        t_col = "#00C805" if trend == "BULL" else "#FF4B4B"
        
        rating = "BUY" if rsi < 70 and trend == "BULL" else "HOLD"
        if rsi > 75: rating = "SELL"
        if rsi < 30: rating = "STRONG BUY"
        r_icon = "✅" if "BUY" in rating else "✋"

        return {
            "p": curr, "ch": chg, "dh": day_h, "dl": day_l, "rng": rng_pct,
            "rsi": int(rsi), "vol": v_str, "vt": v_tag, "earn": earn_date,
            "trend": trend, "t_col": t_col, "rat": rating, "r_icon": r_icon,
            "chart": h['Close']
        }
    except: return None

# --- HEADER & COUNTDOWN ---
c1, c2 = st.columns([3, 1])
with c1: st.title("⚡ Penny Pulse")
with c2:
    # JavaScript Countdown Timer
    components.html("""
        <div style="font-family: sans-serif; text-align: center; color: #888; background-color: #1e2127; padding: 5px; border-radius: 5px; border: 1px solid #333;">
            <div style="font-size: 12px; font-weight: bold;">NEXT PULSE</div>
            <div style="font-size: 20px; font-weight: 900; color: #FF4B4B;">
                <span id="timer">60</span>s
            </div>
        </div>
        <script>
            let left = 60;
            setInterval(function() {
                left--;
                if (left < 0) left = 60;
                document.getElementById('timer').innerText = left;
            }, 1000);
        </script>
    """, height=65)

# Ticker Tape (Marquee)
tape = []
for t in ["SPY", "BTC-USD", "^IXIC"]:
    d = get_card_data(t)
    if d:
        c = "#4caf50" if d['ch']>=0 else "#ff4b4b"
        tape.append(f"<span style='font-weight:bold; margin-right: 15px;'>{t}: <span style='color:{c}'>${d['p']:,.2f}</span></span>")
st.markdown(f"<div style='background:#1e2127; padding:8px; border-radius:5px; border:1px solid #333; margin-bottom:15px; white-space: nowrap; overflow: hidden;'>{' | '.join(tape)}</div>", unsafe_allow_html=True)

# --- TABS ---
t1, t2 = st.tabs(["🏠 Dashboard", "📰 Global AI Wire"])

with t1:
    cols = st.columns(3)
    for i, t in enumerate(MY_WATCHLIST):
        d = get_card_data(t)
        with cols[i % 3]:
            if d:
                # HEADER
                st.markdown(f"### {t}")
                st.metric("Price", f"${d['p']:,.2f}", f"{d['ch']:+.2f}%")
                
                # RANGE BAR (Restored)
                st.markdown(f"""
                <div style="display:flex; align-items:center; font-size:12px; color:#888; margin-bottom:8px;">
                    <span style="margin-right:5px;">L</span>
                    <div style="flex-grow:1; height:4px; background:#333; border-radius:2px; overflow:hidden;">
                        <div style="width:{d['rng']}%; height:100%; background: linear-gradient(90deg, #ff4b4b, #4caf50);"></div>
                    </div>
                    <span style="margin-left:5px;">H</span>
                </div>
                """, unsafe_allow_html=True)
                
                # DETAILS (Clean Layout)
                earn_html = f"| 📅 <b>{d['earn']}</b>" if d['earn'] else ""
                st.markdown(f"""
                <div style='font-size:14px; margin-bottom:4px;'>
                    <b>Trend:</b> <span style='color:{d['t_col']}; font-weight:bold;'>{d['trend']}</span> 
                    | {d['r_icon']} <b>{d['rat']}</b> {earn_html}
                </div>
                <div style='font-size:13px; color:#ccc;'>
                    Vol: {d['vol']} ({d['vt']}) | RSI: {d['rsi']}
                </div>
                """, unsafe_allow_html=True)
                
                st.line_chart(d['chart'], height=100)
            st.divider()

# --- NEWS ENGINE ---
def fetch_news():
    # Chrome Headers to stop blocking
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    try:
        r = requests.get("https://finance.yahoo.com/news/rssindex", headers=headers, timeout=5)
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
    if st.button("Generate AI Report", type="primary"):
        with st.spinner("AI Analysis Running..."):
            raw = fetch_news()
            if not raw: 
                st.error("News feed blocked. Try again in 30s.")
            else:
                if KEY:
                    try:
                        from openai import OpenAI
                        # STRICT PROMPT: Only Index, Ticker, Emoji, Reason
                        p_list = "\n".join([f"{i}. {x['txt']} | {x['desc'][:150]}" for i,x in enumerate(raw[:20])])
                        prompt = """
                        Analyze these financial headlines.
                        1. IDENTIFY the ticker (e.g. (PLUG.CN) -> PLUG.CN, Bitcoin -> BTC). If none, use NEWS.
                        2. DECIDE sentiment: 🟢 (Bullish) or 🔴 (Bearish) or ⚪ (Neutral).
                        3. EXTRACT a 5-word reason.
                        Format strictly: Index|Ticker|Emoji|Reason
                        Example: 0|NVDA|🟢|AI demand surges
                        """
                        
                        client = OpenAI(api_key=KEY)
                        resp = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role":"system", "content": prompt}, {"role":"user", "content": p_list}])
                        
                        processed = []
                        for l in resp.choices[0].message.content.split('\n'):
                            p = l.split('|')
                            if len(p) >= 4:
                                idx = int(re.sub(r'\D','',p[0]))
                                if idx < len(raw):
                                    processed.append({
                                        "tick": p[1].strip(),
                                        "emo": p[2].strip(),
                                        "rsn": p[3].strip(),
                                        "txt": raw[idx]['txt'],
                                        "lnk": raw[idx]['lnk']
                                    })
                        st.session_state['news_cache'] = processed
                    except Exception as e: st.error(f"AI Error: {e}")
                else:
                    st.warning("Enter OpenAI Key for Analysis")

    # Display (Clean Format like 1000013217.jpg)
    if st.session_state['news_cache']:
        for n in st.session_state['news_cache']:
            st.markdown(f"**{n['tick']} {n['emo']}** - [{n['txt']}]({n['lnk']})")
            st.caption(n['rsn'])
            st.divider()
