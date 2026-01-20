import streamlit as st, yfinance as yf, requests, re, time
from datetime import datetime
import streamlit.components.v1 as components
import pandas as pd
import altair as alt

# --- 1. CONFIG & DATA LOCK ---
try: st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="wide")
except: pass

# Hardcoded Data to prevent "Portfolio Gone"
MY_WATCHLIST = ["SPY", "BTC-USD", "TD.TO", "PLUG.CN", "VTX.V", "IVN.TO", "CCO.TO", "BN.TO", "INTC"]
PORT = {
    "HIVE": {"e": 3.19, "q": 50},
    "BAER": {"e": 1.86, "q": 120},
    "TX":   {"e": 38.10, "q": 40},
    "IMNN": {"e": 3.22, "q": 100},
    "RERE": {"e": 5.31, "q": 100}
}

if 'news_cache' not in st.session_state: st.session_state['news_cache'] = []

# --- SIDEBAR ---
st.sidebar.header("⚡ Penny Pulse")
if "OPENAI_KEY" in st.secrets: KEY = st.secrets["OPENAI_KEY"]
else: KEY = st.sidebar.text_input("OpenAI Key", type="password")

# --- DATA ENGINE ---
def get_card_data(s):
    try:
        tk = yf.Ticker(s)
        h = tk.history(period="1mo", interval="1d")
        if h.empty: return None
        
        # Price Data
        curr = h['Close'].iloc[-1]
        prev = h['Close'].iloc[-2]
        chg = ((curr - prev)/prev)*100
        
        # Range Bar Data
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
        v_str = f"{vol/1e6:.1f}M" if vol > 1e6 else f"{vol/1e3:.0f}K"
        v_tag = "⚡ SURGE" if vol > avg_vol * 1.5 else "🌊 STEADY"

        # Calendar Logic (The working one)
        earn_date = "N/A"
        try:
            edt = tk.get_earnings_dates(limit=1)
            if edt is not None and not edt.empty:
                earn_date = edt.index[0].strftime("%b %d")
            elif tk.calendar and isinstance(tk.calendar, dict):
                 e = tk.calendar.get('Earnings Date')
                 if e: earn_date = e[0].strftime("%b %d")
        except: pass

        # Indicators
        trend = "BULL" if rsi > 50 else "BEAR"
        t_col = "#00C805" if trend == "BULL" else "#FF4B4B"
        
        rating = "BUY" if rsi < 70 and trend == "BULL" else "HOLD"
        if rsi > 75: rating = "SELL"
        if rsi < 30: rating = "STRONG BUY"
        r_icon = "✅" if "BUY" in rating else "✋"
        
        ai_txt = "BULLISH BIAS" if trend == "BULL" else "BEARISH BIAS"
        ai_dot = "🟢" if trend == "BULL" else "🔴"

        return {
            "p": curr, "ch": chg, "rng": rng_pct, "rsi": int(rsi), "vol": v_str, "vt": v_tag, "earn": earn_date,
            "trend": trend, "t_col": t_col, "rat": rating, "r_icon": r_icon, "ai_txt": ai_txt, "ai_dot": ai_dot, "chart": h['Close']
        }
    except: return None

# --- HEADER & COUNTDOWN ---
c1, c2 = st.columns([3, 1])
with c1: st.title("⚡ Penny Pulse")
with c2: 
    st.caption(f"Last Update: {datetime.now().strftime('%H:%M:%S')}")
    # THE LIVE COUNTDOWN FIX
    components.html("""
        <div style="background-color:#1e2127; padding:5px; border-radius:5px; text-align:center; border:1px solid #333; color:#ccc; font-family:sans-serif;">
            <div style="font-size:12px; font-weight:bold;">NEXT UPDATE</div>
            <div style="color:#FF4B4B; font-weight:900; font-size:18px;"><span id="timer">60</span>s</div>
        </div>
        <script>
            let t=60; setInterval(()=>{ t--; if(t<0)t=60; document.getElementById('timer').innerText=t; }, 1000);
        </script>
    """, height=60)

# --- THE SCROLLER FIX (Marquee) ---
tape_html = []
for t in ["SPY", "BTC-USD", "^IXIC"]:
    d = get_card_data(t)
    if d:
        c = "#4caf50" if d['ch']>=0 else "#ff4b4b"
        tape_html.append(f"<span style='font-weight:bold; margin-right:30px; font-size:18px;'>{t}: <span style='color:{c}'>${d['p']:,.2f}</span></span>")

st.markdown(f"""
    <div style="background:#1e2127; padding:10px; border-radius:5px; border:1px solid #333; margin-bottom:20px;">
        <marquee scrollamount="8" style="color:white; width:100%;">
            {''.join(tape_html)}
        </marquee>
    </div>
""", unsafe_allow_html=True)

# --- TABS ---
t1, t2, t3 = st.tabs(["🏠 Dashboard", "🚀 My Picks", "📰 Market News"])

# --- DASHBOARD ---
with t1:
    cols = st.columns(3)
    for i, t in enumerate(MY_WATCHLIST):
        d = get_card_data(t)
        with cols[i % 3]:
            if d:
                st.markdown(f"### {t}")
                st.metric("Price", f"${d['p']:,.2f}", f"{d['ch']:+.2f}%")
                
                # AI Bias Line
                st.markdown(f"<div style='font-size:12px; margin-bottom:5px;'>⚙️ AI: {d['ai_dot']} <span style='font-weight:bold; color:{'#ff4b4b' if 'BEAR' in d['ai_txt'] else '#4caf50'}'>{d['ai_txt']}</span></div>", unsafe_allow_html=True)

                # Range Bar
                st.markdown(f"""
                <div style="display:flex; align-items:center; font-size:12px; color:#888; margin-bottom:8px;">
                    <span style="margin-right:5px;">L</span>
                    <div style="flex-grow:1; height:6px; background:#333; border-radius:3px; overflow:hidden;">
                        <div style="width:{d['rng']}%; height:100%; background: linear-gradient(90deg, #ff4b4b, #4caf50);"></div>
                    </div>
                    <span style="margin-left:5px;">H</span>
                </div>
                """, unsafe_allow_html=True)
                
                # --- YOUR TWEAKS HERE ---
                # 1. Analyst Rating on new line
                # 2. Earnings text added
                # 3. Bold Black styling
                st.markdown(f"""
                <div style='font-size:14px; margin-bottom:4px; line-height:1.6;'>
                    <b>Trend:</b> <span style='color:{d['t_col']}; font-weight:bold;'>{d['trend']}</span>
                    <br>
                    <span style='font-weight:900; color:black;'>ANALYST RATING:</span> {d['r_icon']} <span style='color:{d['t_col']}; font-weight:bold;'>{d['rat']}</span>
                    <br>
                    <span style='font-weight:900; color:black;'>EARNINGS:</span> 📅 <span style='color:#555; font-weight:bold;'>{d['earn']}</span>
                </div>
                <div style='font-size:13px; color:#ccc; margin-top:5px;'>
                    <b>Vol:</b> {d['vol']} ({d['vt']}) | <b>RSI:</b> {d['rsi']}
                </div>
                """, unsafe_allow_html=True)
                
                with st.expander("📉 Chart"):
                    st.line_chart(d['chart'])
            st.divider()

# --- PORTFOLIO ---
with t2:
    total_val, day_pl = 0.0, 0.0
    for t, inf in PORT.items():
        d = get_card_data(t)
        if d:
            val = d['p'] * inf['q']
            day_pl += (d['p'] - (d['p']/(1+d['ch']/100))) * inf['q']
            total_val += val
    
    st.markdown(f"""<div style="background:#1e2127; padding:15px; border-radius:10px; border:1px solid #444; margin-bottom:20px; text-align:center;"><div style="color:#888; font-size:12px;">Net Liq</div><div style="font-size:24px; font-weight:bold; color:white;">${total_val:,.2f}</div><div style="color:{'#4caf50' if day_pl>=0 else '#ff4b4b'}; font-weight:bold;">{day_pl:+,.2f} Today</div></div>""", unsafe_allow_html=True)

    cols = st.columns(3)
    for i, (t, inf) in enumerate(PORT.items()):
        d = get_card_data(t)
        if d:
            with cols[i % 3]:
                st.markdown(f"### {t}")
                st.caption(f"{inf['q']} shares")
                st.metric("Price", f"${d['p']:,.2f}", f"{d['ch']:+.2f}%")
                st.markdown(f"<b>Trend:</b> <span style='color:{d['t_col']}'>{d['trend']}</span>", unsafe_allow_html=True)
                st.divider()

# --- NEWS (Fixed Ticker Extraction) ---
def fetch_news():
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get("https://finance.yahoo.com/news/rssindex", headers=headers, timeout=5)
        import xml.etree.ElementTree as ET
        root = ET.fromstring(r.content)
        items = []
        for i in root.findall('.//item')[:20]:
            items.append({"txt": i.find('title').text, "lnk": i.find('link').text, "desc": i.find('description').text or ""})
        return items
    except: return []

def hunt_ticker(txt):
    m = re.search(r'\(([A-Z]{2,5}(?:\.[A-Z]+)?)\)', txt)
    if m: return m.group(1)
    if "BITCOIN" in txt.upper(): return "BTC-USD"
    if "NVIDIA" in txt.upper(): return "NVDA"
    return "NEWS"

with t3:
    if st.button("Generate AI Report", type="primary"):
        with st.spinner("Scanning..."):
            raw = fetch_news()
            if not raw: st.error("News blocked.")
            else:
                final = []
                for r in raw:
                    tick = hunt_ticker(r['txt'] + " " + r['desc'])
                    final.append({"tick": tick, "txt": r['txt'], "lnk": r['lnk'], "desc": r['desc'], "emo": "⚪", "rsn": "Scanning..."})
                
                if KEY:
                    try:
                        from openai import OpenAI
                        p_list = "\n".join([f"{i}. {x['txt']}" for i,x in enumerate(final[:15])])
                        prompt = "Analyze. Format: Index|Emoji|Reason"
                        client = OpenAI(api_key=KEY)
                        resp = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role":"system", "content": prompt}, {"role":"user", "content": p_list}])
                        for l in resp.choices[0].message.content.split('\n'):
                            p = l.split('|')
                            if len(p)>=3:
                                idx=int(re.sub(r'\D','',p[0]))
                                if idx<len(final):
                                    final[idx]['emo']=p[1].strip()
                                    final[idx]['rsn']=p[2].strip()
                    except: pass
                st.session_state['news_cache'] = final

    if st.session_state['news_cache']:
        for n in st.session_state['news_cache']:
            st.markdown(f"**{n['tick']} {n['emo']}** - [{n['txt']}]({n['lnk']})")
            st.caption(n['rsn'])
            st.divider()
