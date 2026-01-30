import streamlit as st
import pandas as pd
import altair as alt
import time
import json
import mysql.connector
import requests
import yfinance as yf
from datetime import datetime, timedelta, timezone
import streamlit.components.v1 as components
import os
import uuid
import re

# --- IMPORTS FOR NEWS & AI ---
try:
    import feedparser
    import openai
    NEWS_LIB_READY = True
except ImportError:
    NEWS_LIB_READY = False

# --- CONFIG ---
try:
    st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="wide")
except:
    pass

ADMIN_PASSWORD = st.secrets.get("ADMIN_PASSWORD", "")
LOGO_PATH = "logo.png"

# *** DATABASE CONFIG ***
DB_CONFIG = {
    "host": "atlanticcanadaschoice.com",
    "user": "atlantic",                 
    "password": "1q2w3e4R!!",   
    "database": "atlantic_pennypulse",    
    "connect_timeout": 30,
}

# --- DATABASE ENGINE ---
def get_connection():
    return mysql.connector.connect(**DB_CONFIG)

def init_db():
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS user_profiles (username VARCHAR(255) PRIMARY KEY, user_data TEXT, pin VARCHAR(50))")
        cursor.execute("CREATE TABLE IF NOT EXISTS user_sessions (token VARCHAR(255) PRIMARY KEY, username VARCHAR(255), created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stock_cache (
                ticker VARCHAR(20) PRIMARY KEY,
                current_price DECIMAL(20, 4),
                day_change DECIMAL(10, 2),
                rsi DECIMAL(10, 2),
                volume_status VARCHAR(20),
                trend_status VARCHAR(20),
                rating VARCHAR(50),
                next_earnings VARCHAR(20),
                pre_post_price DECIMAL(20, 4),
                pre_post_pct DECIMAL(10, 2),
                price_history JSON,
                company_name VARCHAR(255),
                day_high DECIMAL(20, 4),
                day_low DECIMAL(20, 4),
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("CREATE TABLE IF NOT EXISTS daily_briefing (date DATE PRIMARY KEY, picks JSON, sent TINYINT DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        try: cursor.execute("ALTER TABLE daily_briefing ADD COLUMN sent TINYINT DEFAULT 0")
        except: pass
        for col in ['day_high', 'day_low', 'company_name', 'pre_post_price', 'rating', 'next_earnings']:
            try:
                dtype = "DECIMAL(20,4)" if "day" in col or "price" in col else "VARCHAR(255)"
                cursor.execute(f"ALTER TABLE stock_cache ADD COLUMN {col} {dtype}")
            except: pass
        conn.close()
        return True
    except Exception:
        return False

# --- BACKEND UPDATE ENGINE ---
def run_backend_update():
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True, buffered=True)
        cursor.execute("SELECT user_data FROM user_profiles")
        users = cursor.fetchall()
        
        def clean_list(raw_str):
            if not raw_str: return []
            return [t.split(":")[0].strip().upper() for t in raw_str.split(",") if t.strip()]

        all_tickers = set(["^DJI", "^IXIC", "^GSPTSE", "GC=F"]) 
        for r in users:
            try:
                data = json.loads(r['user_data'])
                if 'w_input' in data: all_tickers.update(clean_list(data['w_input']))
                if 'portfolio' in data: all_tickers.update(data['portfolio'].keys())
                if 'tape_input' in data: all_tickers.update(clean_list(data['tape_input']))
            except: pass

        if not all_tickers: conn.close(); return
        format_strings = ','.join(['%s'] * len(all_tickers))
        cursor.execute(f"SELECT ticker, last_updated, rating, next_earnings FROM stock_cache WHERE ticker IN ({format_strings})", tuple(all_tickers))
        existing_rows = {row['ticker']: row for row in cursor.fetchall()}
        
        to_fetch_price = []
        now = datetime.now()
        for t in all_tickers:
            row = existing_rows.get(t)
            if not row or not row['last_updated'] or (now - row['last_updated']).total_seconds() > 120:
                to_fetch_price.append(t)
        
        if to_fetch_price:
            batch_size = 15
            for i in range(0, len(to_fetch_price), batch_size):
                batch = list(to_fetch_price)[i:i + batch_size]
                tickers_str = " ".join(batch)
                try:
                    live_data = yf.download(tickers_str, period="5d", interval="1m", prepost=False, group_by='ticker', threads=True, progress=False)
                    post_data = yf.download(tickers_str, period="5d", interval="1m", prepost=True, group_by='ticker', threads=True, progress=False)
                    hist_data = yf.download(tickers_str, period="1mo", interval="1d", group_by='ticker', threads=True, progress=False)

                    for t in batch:
                        try:
                            df_live = live_data[t] if len(batch) > 1 else live_data
                            df_live = df_live.dropna(subset=['Close'])
                            if df_live.empty: continue
                            live_price = float(df_live['Close'].iloc[-1])

                            df_hist = hist_data[t] if len(batch) > 1 else hist_data
                            df_hist = df_hist.dropna(subset=['Close'])
                            
                            day_change, trend = 0.0, "NEUTRAL"
                            if not df_hist.empty:
                                prev_c = float(df_hist['Close'].iloc[-2]) if len(df_hist) > 1 else live_price
                                day_change = ((live_price - prev_c) / prev_c) * 100
                                trend = "UPTREND" if live_price > df_hist['Close'].tail(20).mean() else "DOWNTREND"
                            
                            sql = """INSERT INTO stock_cache (ticker, current_price, day_change, trend_status, last_updated) 
                                     VALUES (%s, %s, %s, %s, NOW()) ON DUPLICATE KEY UPDATE current_price=%s, day_change=%s, trend_status=%s, last_updated=NOW()"""
                            cursor.execute(sql, (t, live_price, day_change, trend, live_price, day_change, trend))
                            conn.commit()
                        except: continue
                except: pass
        conn.close()
    except Exception: pass

# --- SCANNER ENGINE (TITANIUM AI: NEWS CONTEXT AWARE) ---
@st.cache_data(ttl=900)
def run_gap_scanner(api_key):
    ticker_news_map = {} 
    try:
        feeds = ["https://finance.yahoo.com/rss/most-active", "https://finance.yahoo.com/news/rssindex"]
        for url in feeds:
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                f = feedparser.parse(resp.content)
                for entry in f.entries[:30]: 
                    match = re.search(r'\b[A-Z]{2,5}\b', entry.title)
                    if match: 
                        t = match.group(0)
                        if t not in ["ETF", "THE", "FOR", "AND", "NEW", "CEO", "DOW", "S&P"]: 
                            if t not in ticker_news_map: ticker_news_map[t] = entry.title
    except: pass
    
    scan_list = list(ticker_news_map.keys())
    if not scan_list or not api_key: return []
    
    candidates = []
    try:
        data = yf.download(" ".join(scan_list), period="5d", interval="1d", prepost=True, group_by='ticker', progress=False)
        for t in scan_list:
            df = data[t] if len(scan_list) > 1 else data
            if df.empty or len(df) < 2: continue
            gap = ((df['Close'].iloc[-1] - df['Close'].iloc[-2]) / df['Close'].iloc[-2]) * 100
            if abs(gap) > 1.5:
                candidates.append({"ticker": t, "gap": f"{gap:.1f}%", "headline": ticker_news_map[t]})
    except: pass

    if candidates:
        client = openai.OpenAI(api_key=api_key)
        prompt = f"Pick top 3 stocks with best news. Return JSON: {{'picks': ['TICKER', 'TICKER', 'TICKER']}}. Candidates: {str(candidates[:10])}"
        resp = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"})
        return json.loads(resp.choices[0].message.content).get("picks", [])
    return []

# --- AUTH & HELPERS ---
def check_user_exists(username):
    try:
        conn = get_connection(); cursor = conn.cursor()
        cursor.execute("SELECT pin FROM user_profiles WHERE username = %s", (username,))
        res = cursor.fetchone(); conn.close()
        return (True, res[0]) if res else (False, None)
    except: return False, None

def create_session(username):
    token = str(uuid.uuid4())
    try:
        conn = get_connection(); cursor = conn.cursor()
        cursor.execute("INSERT INTO user_sessions (token, username) VALUES (%s, %s)", (token, username))
        conn.commit(); conn.close(); return token
    except: return None

def validate_session(token):
    try:
        conn = get_connection(); cursor = conn.cursor()
        cursor.execute("SELECT username FROM user_sessions WHERE token = %s", (token,))
        res = cursor.fetchone(); conn.close(); return res[0] if res else None
    except: return None

def load_user_profile(username):
    try:
        conn = get_connection(); cursor = conn.cursor()
        cursor.execute("SELECT user_data FROM user_profiles WHERE username = %s", (username,))
        res = cursor.fetchone(); conn.close()
        return json.loads(res[0]) if res else {"w_input": "TD.TO, SPY"}
    except: return {"w_input": "TD.TO, SPY"}

def save_user_profile(username, data, pin=None):
    try:
        conn = get_connection(); cursor = conn.cursor()
        j_str = json.dumps(data)
        if pin: cursor.execute("INSERT INTO user_profiles (username, user_data, pin) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE user_data = %s, pin = %s", (username, j_str, pin, j_str, pin))
        else: cursor.execute("UPDATE user_profiles SET user_data = %s WHERE username = %s", (j_str, username))
        conn.commit(); conn.close()
    except: pass

def load_global_config():
    try:
        conn = get_connection(); cursor = conn.cursor()
        cursor.execute("SELECT user_data FROM user_profiles WHERE username = 'GLOBAL_CONFIG'")
        res = cursor.fetchone(); conn.close()
        return json.loads(res[0]) if res else {"portfolio": {}, "openai_key": "", "tape_input": "^DJI, ^IXIC, ^GSPTSE, GC=F"}
    except: return {}

def save_global_config(data):
    try:
        conn = get_connection(); cursor = conn.cursor()
        j_str = json.dumps(data)
        sql = "INSERT INTO user_profiles (username, user_data) VALUES ('GLOBAL_CONFIG', %s) ON DUPLICATE KEY UPDATE user_data = %s"
        cursor.execute(sql, (j_str, j_str))
        conn.commit(); conn.close()
    except: pass

def get_global_config_data():
    api_key = st.secrets.get("OPENAI_KEY") or st.secrets.get("OPENAI_API_KEY")
    g = load_global_config()
    if not api_key: api_key = g.get("openai_key")
    return api_key, g.get("rss_feeds", ["https://finance.yahoo.com/news/rssindex"]), g

# --- NEWS ENGINE (WITH 1-10 SCORING) ---
def relative_time(date_str):
    try:
        dt = datetime.strptime(date_str, "%a, %d %b %Y %H:%M:%S %z")
        diff = datetime.now(timezone.utc) - dt
        s = diff.total_seconds()
        if s < 3600: return f"{int(s // 60)}m ago"
        if s < 86400: return f"{int(s // 3600)}h ago"
        return f"{int(s // 86400)}d ago"
    except: return "Recent"

@st.cache_data(ttl=600)
def fetch_news(feeds, tickers, api_key):
    if not NEWS_LIB_READY: return []
    all_feeds = feeds.copy()
    for t in tickers: all_feeds.append(f"https://finance.yahoo.com/rss/headline?s={t}")
    articles, seen = [], set()
    for url in all_feeds:
        try:
            f = feedparser.parse(url)
            for entry in f.entries[:10]:
                if entry.link not in seen:
                    seen.add(entry.link)
                    found_t, sentiment, score = "", "NEUTRAL", 5
                    if api_key:
                        try:
                            client = openai.OpenAI(api_key=api_key)
                            prompt = f"Analyze: '{entry.title}'. Return: TICKER|SENTIMENT|SCORE(1-10)."
                            res = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}], max_tokens=25)
                            parts = res.choices[0].message.content.strip().upper().split("|")
                            found_t = parts[0].strip()
                            sentiment = "BULLISH" if "BULL" in parts[1] else "BEARISH" if "BEAR" in parts[1] else "NEUTRAL"
                            try: score = int(re.search(r'\d+', parts[2]).group())
                            except: score = 5
                        except: pass
                    articles.append({"title": entry.title, "link": entry.link, "published": relative_time(entry.get("published", "")), "ticker": found_t, "sentiment": sentiment, "score": score})
        except: pass
    return articles

# --- DATA ENGINE ---
def get_batch_data(tickers_list):
    results = {}
    try:
        conn = get_connection(); cursor = conn.cursor(dictionary=True)
        cursor.execute(f"SELECT * FROM stock_cache WHERE ticker IN ({','.join(['%s']*len(tickers_list))})", tuple(tickers_list))
        for row in cursor.fetchall():
            s, p, c = row['ticker'], float(row['current_price']), float(row['day_change'])
            results[s] = {"p": p, "d": c, "name": row.get('company_name') or s, "rsi": float(row['rsi'] or 50), "trend": row['trend_status'], "pp": ""}
        conn.close()
    except: pass
    return results

def get_tape_data(symbol_string, nickname_string=""):
    items, symbols = [], [x.split(":")[0].strip().upper() for x in symbol_string.split(",") if x.strip()]
    nick_map = {k.strip().upper(): v.strip().upper() for p in nickname_string.split(",") if ":" in p for k,v in [p.split(":")]}
    final_map = {"^DJI": "DOW", "^IXIC": "NASDAQ", "^GSPTSE": "TSX", "GC=F": "GOLD", "BTC-USD": "BTC"}.copy()
    final_map.update(nick_map)
    try:
        conn = get_connection(); cursor = conn.cursor(dictionary=True)
        cursor.execute(f"SELECT ticker, current_price, day_change FROM stock_cache WHERE ticker IN ({','.join(['%s']*len(symbols))})", tuple(symbols))
        data_map = {row['ticker']: row for row in cursor.fetchall()}; conn.close()
        for s in symbols:
            disp = final_map.get(s, s)
            if s in data_map:
                row = data_map[s]; col, arrow = ("#4caf50", "▲") if float(row['day_change']) >= 0 else ("#ff4b4b", "▼")
                items.append(f"<span style='color:#ccc; margin-left:20px;'>{disp}</span> <span style='color:{col}'>{arrow} {float(row['current_price']):,.2f} ({float(row['day_change']):+.2f}%)</span>")
    except: pass
    return "    ".join(items)

# --- UI LOGIC ---
init_db()
run_backend_update()
ACTIVE_KEY, SHARED_FEEDS, _ = get_global_config_data()

st.markdown("""<style>
.block-container { padding-top: 4.5rem !important; }
div[data-testid="stVerticalBlock"] > div[style*="flex-direction: column;"] > div[data-testid="stVerticalBlock"] { background-color: #ffffff; border-radius: 12px; padding: 15px; box-shadow: 0 4px 10px rgba(0,0,0,0.05); border: 1px solid #f0f0f0; }
.news-card { padding: 10px; margin-bottom: 15px; border-left: 6px solid #ccc; background: #fff; }
.news-title { font-size: 16px; font-weight: 700; color: #333; text-decoration: none; display: block; margin-bottom: 4px; }
.hot-badge { background: linear-gradient(90deg, #ff4b4b, #ff9100); color: white; padding: 2px 8px; border-radius: 10px; font-weight: bold; font-size: 10px; animation: pulse 2s infinite; }
@keyframes pulse { 0%{opacity:0.8} 50%{opacity:1} 100%{opacity:0.8} }
</style>""", unsafe_allow_html=True)

if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
    token = st.query_params.get("token")
    if token:
        user = validate_session(token)
        if user:
            st.session_state.update({"username": user, "user_data": load_user_profile(user), "global_data": load_global_config(), "logged_in": True})

if not st.session_state["logged_in"]:
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        if os.path.exists(LOGO_PATH): st.image(LOGO_PATH, width=150)
        with st.form("login"):
            u = st.text_input("Username"); p = st.text_input("PIN", type="password")
            if st.form_submit_button("🚀 Login"):
                exists, stored = check_user_exists(u.strip())
                if (exists and stored == p) or not exists:
                    if not exists: save_user_profile(u.strip(), {"w_input": "TD.TO, SPY"}, p)
                    st.query_params["token"] = create_session(u.strip())
                    st.session_state.update({"username": u.strip(), "user_data": load_user_profile(u.strip()), "global_data": load_global_config(), "logged_in": True})
                    st.rerun()
else:
    def push_user(): save_user_profile(st.session_state["username"], st.session_state["user_data"])
    def push_global(): save_global_config(st.session_state["global_data"])
    GLOBAL, USER = st.session_state["global_data"], st.session_state["user_data"]
    
    tape = get_tape_data(GLOBAL.get("tape_input", "^DJI,^IXIC"), GLOBAL.get("tape_nicknames", ""))
    components.html(f"<div style='background:#111; height:45px; display:flex; align-items:center; color:white; overflow:hidden; border-radius:0 0 15px 15px;'><marquee scrollamount='5' style='font-weight:900;'>{tape}</marquee></div>", height=50)

    with st.sidebar:
        st.markdown(f"👤 **{st.session_state['username']}**")
        new_w = st.text_area("Watchlist", USER.get("w_input", ""), height=100)
        if new_w != USER.get("w_input"): USER["w_input"] = new_w; push_user(); st.rerun()
        
        with st.expander("🔔 Alert Settings"):
            curr_tg = USER.get("tg_id", "")
            new_tg = st.text_input("Telegram ID", value=curr_tg)
            if new_tg != curr_tg: USER["tg_id"] = new_tg; push_user(); st.success("Saved!")
            st.checkbox("AI Daily Picks", value=USER.get("alert_ai", True))
        
        with st.expander("🔐 Admin"):
            if st.button("🔎 Scan Market"):
                picks = run_gap_scanner(ACTIVE_KEY)
                if picks:
                    conn = get_connection(); cursor = conn.cursor()
                    cursor.execute("DELETE FROM daily_briefing WHERE date = %s", (datetime.now().strftime('%Y-%m-%d'),))
                    cursor.execute("INSERT INTO daily_briefing (date, picks) VALUES (%s, %s)", (datetime.now().strftime('%Y-%m-%d'), json.dumps(picks)))
                    conn.commit(); conn.close(); st.success("Picks Saved!")

        if st.button("Logout"): st.session_state["logged_in"] = False; st.rerun()

    @st.fragment(run_every=60)
    def render_dashboard():
        t1, t2, t3, t4 = st.tabs(["📊 Live Market", "🚀 My Picks", "📰 My News", "🌎 Discovery"])
        w_tickers = [x.strip().upper() for x in USER.get("w_input", "").split(",") if x.strip()]
        port = GLOBAL.get("portfolio", {})
        all_view = list(set(w_tickers + list(port.keys())))
        batch = get_batch_data(all_view)
        news = fetch_news(SHARED_FEEDS, all_view, ACTIVE_KEY)

        def draw_card(t, port_item=None):
            d = batch.get(t)
            if not d: return
            b_col = "#4caf50" if d["d"] >= 0 else "#ff4b4b"
            high_impact = [n for n in news if n['ticker'] == t and n['score'] >= 8]
            hot = "<span class='hot-badge'>🔥 HOT</span>" if len(high_impact) >= 2 else ""
            with st.container():
                st.markdown(f"<div style='height:4px; background:{b_col}; border-radius:4px 4px 0 0;'></div><div style='display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:15px;'><div><div style='font-size:22px; font-weight:bold;'>{t} {hot}</div><div style='font-size:12px; color:#888;'>{d['name'][:25]}...</div></div><div style='text-align:right;'><div style='font-size:22px; font-weight:bold;'>${d['p']:,.2f}</div><div style='font-size:13px; font-weight:bold; color:{b_col};'>{d['d']:+.2f}%</div></div></div>", unsafe_allow_html=True)
                st.divider()

        with t1:
            cols = st.columns(3)
            for i, t in enumerate(w_tickers):
                with cols[i % 3]: draw_card(t)

        with t3:
            for n in news:
                col = "#4caf50" if n['score'] >= 8 else "#f1c40f" if n['score'] >= 5 else "#ff4b4b"
                st.markdown(f"<div class='news-card' style='border-left-color:{col};'><div style='display:flex; justify-content:space-between;'><a href='{n['link']}' target='_blank' class='news-title'>{n['title']}</a><span style='background:{col}; color:white; padding:2px 8px; border-radius:12px; font-size:10px; font-weight:bold;'>{n['score']}/10</span></div><small>{n['ticker']} | {n['sentiment']}</small></div>", unsafe_allow_html=True)

    render_dashboard()
