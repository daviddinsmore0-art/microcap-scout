import streamlit as st, yfinance as yf, requests, time, re, xml.etree.ElementTree as ET
from datetime import datetime, timedelta
import streamlit.components.v1 as components
import pandas as pd
import altair as alt 

try: st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="wide")
except: pass 

# --- SESSION STATE ---
if 'news_results' not in st.session_state: st.session_state['news_results'] = []
if 'scanned_count' not in st.session_state: st.session_state['scanned_count'] = 0
if 'market_mood' not in st.session_state: st.session_state['market_mood'] = None 
if 'alert_triggered' not in st.session_state: st.session_state['alert_triggered'] = False
if 'last_trends' not in st.session_state: st.session_state['last_trends'] = {}
if 'mem_ratings' not in st.session_state: st.session_state['mem_ratings'] = {}
if 'mem_meta' not in st.session_state: st.session_state['mem_meta'] = {}

if 'saved_a_tick' not in st.session_state: st.session_state['saved_a_tick'] = "SPY"
if 'saved_a_price' not in st.session_state: st.session_state['saved_a_price'] = 0.0
if 'saved_a_on' not in st.session_state: st.session_state['saved_a_on'] = False
if 'saved_flip_on' not in st.session_state: st.session_state['saved_flip_on'] = False 

# --- PORTFOLIO ---
PORT = {
    "HIVE": {"e": 3.19, "d": "Dec. 01, 2024", "q": 1000},
    "BAER": {"e": 1.86, "d": "Jan. 10, 2025", "q": 500},
    "TX":   {"e": 38.10, "d": "Nov. 05, 2023", "q": 100},
    "IMNN": {"e": 3.22, "d": "Aug. 20, 2024", "q": 200},
    "RERE": {"e": 5.31, "d": "Oct. 12, 2024", "q": 300}
} 

NAMES = {
    "TSLA":"Tesla", "NVDA":"Nvidia", "BTC-USD":"Bitcoin", "AMD":"AMD", 
    "PLTR":"Palantir", "AAPL":"Apple", "SPY":"S&P 500", "^IXIC":"Nasdaq", 
    "^DJI":"Dow Jones", "GC=F":"Gold", "TD.TO":"TD Bank", "IVN.TO":"Ivanhoe", 
    "BN.TO":"Brookfield", "JNJ":"J&J", "^GSPTSE": "TSX"
} 

# --- SIDEBAR ---
st.sidebar.header("⚡ Pulse")
if "OPENAI_KEY" in st.secrets: KEY = st.secrets["OPENAI_KEY"]
else: KEY = st.sidebar.text_input("OpenAI Key (Optional)", type="password") 

# --- PERMANENT WATCHLIST ---
default_list = "SPY, BTC-USD, TD.TO, PLUG.CN, VTX.V, IVN.TO, CCO.TO, BN.TO"

qp = st.query_params
w_str = qp.get("watchlist", default_list)
u_in = st.sidebar.text_input("Add Tickers", value=w_str)
if u_in != w_str: st.query_params["watchlist"] = u_in

WATCH = [x.strip().upper() for x in u_in.split(",") if x.strip()]
ALL = list(set(WATCH + list(PORT.keys())))
st.sidebar.divider()
st.sidebar.subheader("🔔 Smart Alerts") 

# --- PERSISTENT WIDGETS ---
a_tick = st.sidebar.selectbox("Price Target Asset", sorted(ALL), key="saved_a_tick")
a_price = st.sidebar.number_input("Target ($)", step=0.5, key="saved_a_price")
a_on = st.sidebar.toggle("Active Price Alert", key="saved_a_on")
flip_on = st.sidebar.toggle("Alert on Trend Flip", key="saved_flip_on") 

# --- SECTOR & EARNINGS ---
def get_meta_data(s):
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
            
            if 0 <= days <= 7: 
                earn_html = f"<span style='background:#550000; color:#ff4b4b; padding:1px 4px; border-radius:4px; font-size:11px;'>⚠️ {days}d</span>"
            elif 8 <= days <= 30: 
                earn_html = f"<span style='background:#333; color:#ccc; padding:1px 4px; border-radius:4px; font-size:11px;'>📅 {days}d</span>"
            elif days > 30:
                d_str = nxt.strftime("%b %d")
                earn_html = f"<span style='background:#222; color:#888; padding:1px 4px; border-radius:4px; font-size:11px;'>📅 {d_str}</span>"
        
        if sector_code or earn_html != "N/A":
            st.session_state['mem_meta'][s] = (sector_code, earn_html)
        return sector_code, earn_html
        
    except:
        if s in st.session_state['mem_meta']: return st.session_state['mem_meta'][s]
        return "", "N/A" 

# --- ANALYST RATINGS ---
def get_rating_cached(s):
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
    except:
        if s in st.session_state['mem_ratings']: return st.session_state['mem_ratings'][s]
        return "N/A", "#888"

# --- AI SIGNAL LOGIC ---
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

# --- LIVE PRICE & CHART ---
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
            if p_reg is not None and pv is not None: 
                valid_data = True
        except: pass
    
    chart_data = None
    try:
        h = tk.history(period="1d", interval="5m", prepost=True)
        if h.empty: h = tk.history(period="5d", interval="1h", prepost=True)
        if not h.empty:
            chart_data = h['Close']
            if not valid_data or is_crypto:
                p_reg = h['Close'].iloc[-1]
                if is_crypto: pv = h['Open'].iloc[0] 
                else: pv = tk.fast_info['previous_close']
                if pd.isna(pv) or pv == 0: pv = h['Close'].iloc[0]
                dh = h['High'].max()
                dl = h['Low'].min()
                valid_data = True
            p_ext = h['Close'].iloc[-1]
    except: pass
    
    if not valid_data or pv == 0: return None
    
    try: d_reg_pct = ((p_reg - pv) / pv) * 100
    except: d_reg_pct = 0.0

    if p_ext == 0: p_ext = p_reg
    try: d_ext_pct = ((p_ext - pv) / pv) * 100
    except: d_ext_pct = 0.0

    c_ext = "green" if d_ext_pct >= 0 else "red"
    x_str = f"**Live: ${p_ext:,.2f} (:{c_ext}[{d_ext_pct:+.2f}%])**" if is_crypto else f"**🌙 Ext: ${p_ext:,.2f} (:{c_ext}[{d_ext_pct:+.2f}%])**"
    
    # --- VISUALS ---
    try: rng_pct = max(0, min(1, (p_reg - dl) / (dh - dl))) * 100 if (dh > dl) else 50
    except: rng_pct = 50
    rng_html = f"""<div style="font-size:11px; color:#666; margin-top:5px;">Day Range (Low - High)</div><div style="display:flex; align-items:center; font-size:10px; color:#888; margin-top:2px;"><span style="margin-right:4px;">L</span><div style="flex-grow:1; height:4px; background:#333; border-radius:2px; overflow:hidden;"><div style="width:{rng_pct}%; height:100%; background: linear-gradient(90deg, #ff4b4b, #4caf50);"></div></div><span style="margin-left:4px;">H</span></div>""" 

    rsi, rl, tr, v_str, vol_tag, raw_trend, ai_txt, ai_col = 50, "Neutral", "Neutral", "N/A", "", "NEUTRAL", "N/A", "#888"
    rsi_html, vol_html = "", ""
    
    try:
        hm = tk.history(period="1mo")
        if not hm.empty:
            cur_v = hm['Volume'].iloc[-1]
            avg_v = hm['Volume'].iloc[:-1].mean() if len(hm) > 1 else cur_v
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
    except: pass
    
    return {"p":p_reg, "d":d_reg_pct, "d_raw": (p_reg - pv), "x":x_str, "v":v_str, "vt":vol_tag, "rsi":rsi, "rl":rl, "tr":tr, "raw_trend":raw_trend, "rng_html":rng_html, "vol_html":vol_html, "rsi_html":rsi_html, "chart":chart_data, "ai_txt":ai_txt, "ai_col":ai_col} 

# --- HEADER ---
est_now = datetime.utcnow() - timedelta(hours=5)
c1, c2 = st.columns([1, 1])
with c1:
    st.title("⚡ Penny Pulse")
    st.caption(f"Last Updated: {est_now.strftime('%H:%M:%S EST')}")
with c2:
    components.html("""<div style="font-family: 'Helvetica', sans-serif; background-color: #0E1117; padding: 5px; border-radius: 5px; text-align:center; display:flex; justify-content:center; align-items:center; height:100%;"><span style="color: #BBBBBB; font-weight: bold; font-size: 14px; margin-right:5px;">Next Update: </span><span id="countdown" style="color: #FF4B4B; font-weight: 900; font-size: 18px;">--</span><span style="color: #BBBBBB; font-size: 14px; margin-left:2px;"> s</span></div><script>function startTimer(){var timer=setInterval(function(){var now=new Date();var seconds=60-now.getSeconds();var el=document.getElementById("countdown");if(el){el.innerHTML=seconds;}},1000);}startTimer();</script>""", height=60) 

# --- TICKER ---
ti = []
for t in ["SPY","^IXIC","^DJI","BTC-USD", "^GSPTSE"]:
    d = get_data_cached(t)
    if d:
        c, a = ("#4caf50","▲") if d['d']>=0 else ("#f44336","▼")
        nm = NAMES.get(t, t)
        if t.endswith(".TO"): nm += " (TSX)"
        elif t.endswith(".V"): nm += " (TSXV)"
        elif t.endswith(".CN"): nm += " (CSE)"
        ti.append(f"<span style='margin-right:30px;font-weight:900;font-size:22px;color:white;'>{nm}: <span style='color:{c};'>${d['p']:,.2f} {a} {d['d']:.2f}%</span></span>")
h = "".join(ti)
st.markdown(f"""<div style="background-color: #0E1117; padding: 10px 0; border-top: 2px solid #333; border-bottom: 2px solid #333;"><marquee scrollamount="6" style="width: 100%;">{h * 15}</marquee></div>""", unsafe_allow_html=True) 

# --- FLIP CHECK ---
def check_flip(ticker, current_trend):
    if not flip_on: return
    if ticker in st.session_state['last_trends']:
        prev = st.session_state['last_trends'][ticker]
        if prev != "NEUTRAL" and current_trend != "NEUTRAL" and prev != current_trend:
            st.toast(f"🔀 TREND FLIP: {ticker} switched to {current_trend}!", icon="⚠️")
    st.session_state['last_trends'][ticker] = current_trend 

# --- DASHBOARD LOGIC (RESTRUCTURED) ---
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
        
        # 1. Extended Hours (MOVED UP)
        st.markdown(f"<div style='margin-top:-10px; margin-bottom:10px;'>{d['x']}</div>", unsafe_allow_html=True) 
        
        # 2. AI Signal
        st.markdown(f"<div style='margin-bottom:10px; font-weight:bold; font-size:14px;'>🤖 AI: <span style='color:{d['ai_col']};'>{d['ai_txt']}</span></div>", unsafe_allow_html=True) 
        
        # 3. Key Metadata (SEPARATED LINES & BOLD BLACK CAPS)
        meta_html = f"""
        <div style='font-size:14px; line-height:1.8; margin-bottom:10px; color:#444;'>
            <div style='display:flex; justify-content:space-between;'><span><b style='color:black;'>TREND:</b></span> <span>{d['tr']}</span></div>
            <div style='display:flex; justify-content:space-between;'><span><b style='color:black;'>ANALYST RATING:</b></span> <span style='color:{rat_col}; font-weight:bold;'>{rat_txt}</span></div>
            <div style='display:flex; justify-content:space-between;'><span><b style='color:black;'>EARNINGS:</b></span> <span>{earn}</span></div>
        </div>
        """
        st.markdown(meta_html, unsafe_allow_html=True)

        # 4. Sparkline (LABELED)
        st.markdown("<div style='font-size:11px; font-weight:bold; color:#555; margin-bottom:2px;'>INTRADAY TREND (Last 2 Hours)</div>", unsafe_allow_html=True)
        if d['chart'] is not None:
            spark_data = d['chart'].tail(30).reset_index()
            spark_data.columns = ['Time', 'Price']
            line_color = "#4caf50" if d['d'] >= 0 else "#ff4b4b"
            c = alt.Chart(spark_data).mark_line(color=line_color, strokeWidth=2).encode(x=alt.X('Time', axis=None), y=alt.Y('Price', scale=alt.Scale(zero=False), axis=None)).properties(height=40, width='container').configure_view(strokeWidth=0)
            st.altair_chart(c, use_container_width=True)
        
        # 5. Visual Bars
        st.markdown(d['rng_html'], unsafe_allow_html=True)
        st.markdown(d['vol_html'], unsafe_allow_html=True)
        st.markdown(d['rsi_html'], unsafe_allow_html=True)
        
    else: st.metric(t, "---", "0.0%")
    st.divider() 

t1, t2, t3 = st.tabs(["🏠 Dashboard", "🚀 My Picks", "📰 Market News"])
with t1:
    cols = st.columns(3)
    for i, t in enumerate(WATCH):
        with cols[i%3]: render_card(t) 

with t2:
    tot_val, day_pl, tot_pl = 0.0, 0.0, 0.0
    for t, inf in PORT.items():
        d = get_data_cached(t)
        if d:
            q = inf.get("q", 100)
            curr = d['p'] * q
            tot_val += curr
            tot_pl += (curr - (inf['e'] * q))
            day_pl += (d['d_raw'] * q)
            
    st.markdown(f"""<div style="background-color:#1e2127; padding:15px; border-radius:10px; margin-bottom:20px; border:1px solid #444;"><div style="display:flex; justify-content:space-around; text-align:center;"><div><div style="color:#aaa; font-size:12px;">Net Liq</div><div style="font-size:18px; font-weight:bold; color:white;">${tot_val:,.2f}</div></div><div><div style="color:#aaa; font-size:12px;">Day P/L</div><div style="font-size:18px; font-weight:bold; color:{'green' if day_pl>=0 else 'red'};">${day_pl:+,.2f}</div></div><div><div style="color:#aaa; font-size:12px;">Total P/L</div><div style="font-size:18px; font-weight:bold; color:{'green' if tot_pl>=0 else 'red'};">${tot_pl:+,.2f}</div></div></div></div>""", unsafe_allow_html=True)
    cols = st.columns(3)
    for i, (t, inf) in enumerate(PORT.items()):
        with cols[i%3]: render_card(t, inf) 

if a_on:
    d = get_data_cached(a_tick)
    if d and d['p'] >= a_price and not st.session_state['alert_triggered']:
        st.toast(f"🚨 ALERT: {a_tick} HIT ${d['p']:,.2f}!", icon="🔥")
        st.session_state['alert_triggered'] = True 

# --- DEEP DIVE NEWS AGENT ---
def fetch_article_text(url):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
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
            batch_content += f"\n\nARTICLE {idx+1}:\nTitle: {item['title']}\nLink: {item['link']}\nContent: {content[:1000]}"
            progress_bar.progress(min((idx + 1) / total_items, 1.0))
        
        system_instr = """
        You are a financial analyst. Read these articles.
        Identify specific stock tickers that are the SUBJECT or RECOMMENDATION of the article.
        If no specific ticker is found, use the main sector.
        Rank them by sentiment strength.
        IMPORTANT: For the 'REASON' field, write a specific 5-10 word explanation of WHY (e.g., 'Strong earnings beat expectations' or 'CEO announced new partnership'). DO NOT use the word 'Reason'.
        Format: TICKER | SENTIMENT (🟢/🔴/⚪) | REASON | ORIGINAL_TITLE | ORIGINAL_LINK
        """
        
        res = client.chat.completions.create(
            model="gpt-4o-mini", 
            messages=[{"role":"system", "content": system_instr}, {"role":"user", "content": batch_content}], 
            max_tokens=700
        )
        
        new_results = []
        lines = res.choices[0].message.content.strip().split("\n")
        
        green_count = 0
        total_signals = 0
        
        for l in lines:
            parts = l.split("|")
            if len(parts) >= 5: 
                sig = parts[1].strip()
                if "🟢" in sig: green_count += 1
                if "🟢" in sig or "🔴" in sig: total_signals += 1
                
                reason_text = parts[2].strip()
                if not reason_text or reason_text.upper() == "REASON":
                    reason_text = "Analysis based on article content."
                
                new_results.append({
                    "ticker": parts[0].strip(),
                    "signal": sig,
                    "reason": reason_text,
                    "title": parts[3].strip(),
                    "link": parts[4].strip()
                })
        
        if total_signals > 0:
            bull_pct = int((green_count / total_signals) * 100)
            if bull_pct >= 60: mood = f"🐂 {bull_pct}% BULLISH"
            elif bull_pct <= 40: mood = f"🐻 {100-bull_pct}% BEARISH"
            else: mood = f"⚖️ {bull_pct}% NEUTRAL"
            st.session_state['market_mood'] = mood
        
        progress_bar.empty()
        return new_results
    except Exception as e:
        st.warning(f"⚠️ AI Error: {e}")
        return []

@st.cache_data(ttl=300, show_spinner=False)
def get_news_cached():
    head = {'User-Agent': 'Mozilla/5.0'}
    urls = ["https://finance.yahoo.com/news/rssindex", "https://www.cnbc.com/id/10000664/device/rss/rss.html"]
    it, seen = [], set()
    blacklist = ["kill", "dead", "troop", "war", "sport", "football", "murder", "crash", "police", "arrest", "shoot", "bomb"]
    for u in urls:
        try:
            r = requests.get(u, headers=head, timeout=5)
            root = ET.fromstring(r.content)
            for i in root.findall('.//item')[:50]:
                t, l = i.find('title').text, i.find('link').text
                desc = i.find('description').text if i.find('description') is not None else ""
                if t and t not in seen:
                    t_lower = t.lower()
                    if not any(b in t_lower for b in blacklist):
                        seen.add(t)
                        it.append({"title":t,"link":l, "desc": desc})
        except: continue
    return it 

with t3:
    c_n1, c_n2 = st.columns([3, 1])
    with c_n1: st.subheader("🚨 Global Wire (Deep Scan)")
    with c_n2: 
        if st.session_state['market_mood']:
            st.markdown(f"<div style='background:#333; color:white; padding:5px; border-radius:5px; text-align:center; font-weight:bold;'>Mood: {st.session_state['market_mood']}</div>", unsafe_allow_html=True)
    
    if st.button("Deep Scan Reports (Top 10)", type="primary", key="deep_scan_btn"):
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
            st.markdown(f"**{r['ticker']} {r['signal']}** - [{r['title']}]({r['link']})")
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
