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
        try: cursor.execute("ALTER TABLE daily_briefing ADD COLUMN sent TINYINT DEFAULT 0"); 
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
            cleaned = []
            for t in raw_str.split(","):
                symbol = t.split(":")[0].strip().upper()
                if symbol: cleaned.append(symbol)
            return cleaned

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
        to_fetch_meta = []
        now = datetime.now()
        
        for t in all_tickers:
            row = existing_rows.get(t)
            if not row or not row['last_updated'] or (now - row['last_updated']).total_seconds() > 120:
                to_fetch_price.append(t)
            if not row or row.get('rating') == 'N/A' or row.get('next_earnings') == 'N/A':
                to_fetch_meta.append(t)
        
        if to_fetch_price:
            batch_size = 15
            ticker_list = list(to_fetch_price)
            for i in range(0, len(ticker_list), batch_size):
                batch = ticker_list[i:i + batch_size]
                tickers_str = " ".join(batch)
                try:
                    live_data = yf.download(tickers_str, period="5d", interval="1m", prepost=False, group_by='ticker', threads=True, progress=False)
                    post_data = yf.download(tickers_str, period="5d", interval="1m", prepost=True, group_by='ticker', threads=True, progress=False)
                    hist_data = yf.download(tickers_str, period="1mo", interval="1d", group_by='ticker', threads=True, progress=False)

                    for t in batch:
                        try:
                            if len(batch) == 1: df_live = live_data
                            else: 
                                if t not in live_data.columns.levels[0]: continue
                                df_live = live_data[t]
                            
                            df_live = df_live.dropna(subset=['Close'])
                            if df_live.empty: continue
                            
                            live_price = float(df_live['Close'].iloc[-1])
                            last_time = df_live.index[-1]

                            ext_price = live_price 
                            if len(batch) == 1: df_post = post_data
                            else:
                                if t in post_data.columns.levels[0]: df_post = post_data[t]
                                else: df_post = pd.DataFrame()
                            
                            if not df_post.empty:
                                df_post = df_post.dropna(subset=['Close'])
                                if not df_post.empty:
                                    ext_price = float(df_post['Close'].iloc[-1])

                            if len(batch) == 1: df_hist = hist_data
                            else:
                                if t in hist_data.columns.levels[0]: df_hist = hist_data[t]
                                else: df_hist = pd.DataFrame()
                            
                            day_change, rsi, vol_stat, trend, chart_json = 0.0, 50.0, "NORMAL", "NEUTRAL", "[]"
                            final_price, day_h, day_l = live_price, live_price, live_price

                            if not df_hist.empty:
                                df_hist = df_hist.dropna(subset=['Close'])
                                daily_price = float(df_hist['Close'].iloc[-1]) 
                                if last_time.hour >= 15 and last_time.minute >= 59:
                                    if df_hist.index[-1].date() == last_time.date():
                                        final_price = daily_price
                                
                                ext_pct = 0.0
                                if final_price > 0:
                                    ext_pct = ((ext_price - final_price) / final_price) * 100

                                if len(df_hist) > 0:
                                    day_h = max(float(df_hist['High'].iloc[-1]), live_price)
                                    day_l = min(float(df_hist['Low'].iloc[-1]), live_price)

                                if len(df_hist) > 1:
                                    prev_close = float(df_hist['Close'].iloc[-2])
                                    if last_time.date() > df_hist.index[-1].date():
                                        prev_close = float(df_hist['Close'].iloc[-1])
                                    if prev_close > 0:
                                        day_change = ((final_price - prev_close) / prev_close) * 100
                                
                                trend = "UPTREND" if daily_price > df_hist['Close'].tail(20).mean() else "DOWNTREND"
                                try:
                                    delta = df_hist['Close'].diff()
                                    g = delta.where(delta > 0, 0).rolling(14).mean()
                                    l = (-delta.where(delta < 0, 0)).rolling(14).mean()
                                    if not l.empty and l.iloc[-1] != 0: rsi = 100 - (100 / (1 + (g.iloc[-1]/l.iloc[-1])))
                                except: pass

                                if not df_hist['Volume'].empty:
                                    v_avg = df_hist['Volume'].mean()
                                    if v_avg > 0:
                                        v_curr = df_hist['Volume'].iloc[-1]
                                        if v_curr > v_avg * 1.5: vol_stat = "HEAVY"
                                        elif v_curr < v_avg * 0.5: vol_stat = "LIGHT"
                                
                                chart_json = json.dumps(df_hist['Close'].tail(20).tolist())

                            sql = """INSERT INTO stock_cache 
                                     (ticker, current_price, day_change, rsi, volume_status, trend_status, price_history, day_high, day_low, pre_post_price, pre_post_pct, last_updated) 
                                     VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()) 
                                     ON DUPLICATE KEY UPDATE 
                                     current_price=%s, day_change=%s, rsi=%s, volume_status=%s, trend_status=%s, price_history=%s, day_high=%s, day_low=%s, pre_post_price=%s, pre_post_pct=%s, last_updated=NOW()"""
                            
                            v = (t, final_price, day_change, rsi, vol_stat, trend, chart_json, day_h, day_l, ext_price, ext_pct, 
                                 final_price, day_change, rsi, vol_stat, trend, chart_json, day_h, day_l, ext_price, ext_pct)
                            
                            cursor.execute(sql, v)
                            conn.commit()
                        except: pass
                except: pass

        if to_fetch_meta:
            for t in to_fetch_meta[:3]: 
                try:
                    time.sleep(0.5) 
                    tk = yf.Ticker(t)
                    info = tk.info
                    r_val = info.get('recommendationKey', 'N/A').replace('_', ' ').upper()
                    n_val = info.get('shortName') or info.get('longName') or t
                    e_val = "N/A"
                    try:
                        cal = tk.calendar
                        dates = []
                        if isinstance(cal, dict) and 'Earnings Date' in cal: dates = cal['Earnings Date']
                        elif hasattr(cal, 'iloc'): dates = [v for v in cal.values.flatten() if isinstance(v, (datetime, pd.Timestamp))]
                        future_dates = [d for d in dates if pd.to_datetime(d).date() >= datetime.now().date()]
                        if future_dates: e_val = min(future_dates).strftime('%b %d')
                    except: pass
                    sql = "UPDATE stock_cache SET rating=%s, next_earnings=%s, company_name=%s WHERE ticker=%s"
                    cursor.execute(sql, (r_val, e_val, n_val, t))
                    conn.commit()
                except: pass
        conn.close()
    except Exception: pass

# --- SCANNER ENGINE ---
@st.cache_data(ttl=900)
def run_gap_scanner(api_key):
    fh_key = st.secrets.get("FINNHUB_API_KEY")
    candidates = []
    ticker_news_map = {} 
    now_est = datetime.now(timezone.utc) - timedelta(hours=5)
    current_hour = now_est.hour
    is_pre_market = current_hour < 9 or (current_hour == 9 and now_est.minute < 30)
    is_post_market = current_hour >= 16
    
    min_gap = 4.0 if (is_pre_market or is_post_market) else 1.0
    max_price = 50 if (is_pre_market or is_post_market) else 5000 

    try:
        feeds = ["https://finance.yahoo.com/rss/most-active", "https://finance.yahoo.com/news/rssindex"]
        headers = {'User-Agent': 'Mozilla/5.0'}
        for url in feeds:
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                f = feedparser.parse(resp.content)
                for entry in f.entries[:30]: 
                    match = re.search(r'\b[A-Z]{2,5}\b', entry.title)
                    if match: 
                        t = match.group(0)
                        if t not in ["ETF", "THE", "FOR", "AND", "NEW", "CEO", "Dow", "S&P"]: 
                            if t not in ticker_news_map: ticker_news_map[t] = entry.title
    except: pass
    
    scan_list = list(ticker_news_map.keys())
    try:
        if scan_list:
            data = yf.download(" ".join(scan_list), period="5d", interval="1d", prepost=True, group_by='ticker', threads=True, progress=False)
            for t in scan_list:
                df = data[t] if len(scan_list) > 1 else data
                if df.empty or len(df) < 2: continue
                prev_c = float(df['Close'].iloc[-2])
                curr_p = float(df['Close'].iloc[-1]) 
                gap_pct = ((curr_p - prev_c) / prev_c) * 100
                if abs(gap_pct) >= min_gap and curr_p <= max_price:
                    candidates.append({"ticker": t, "gap": f"{gap_pct:.1f}%", "headline": ticker_news_map.get(t, "No Headline")})
    except: pass

    if api_key and candidates:
        try:
            candidates.sort(key=lambda x: float(x['gap'].strip('%')), reverse=True)
            client = openai.OpenAI(api_key=api_key)
            prompt = f"Analyze these stocks. Pick top 3 with best news. Return JSON: {{'picks': ['TICKER', 'TICKER', 'TICKER']}}. Candidates: {str(candidates[:10])}"
            resp = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"})
            return json.loads(resp.choices[0].message.content).get("picks", [])
        except: return [c['ticker'] for c in candidates[:3]]
    return [c['ticker'] for c in candidates[:3]] if candidates else []

# --- AUTH & HELPERS ---
def check_user_exists(username):
    try:
        conn = get_connection(); cursor = conn.cursor()
        cursor.execute("SELECT pin FROM user_profiles WHERE username = %s", (username,))
        res = cursor.fetchone(); conn.close(); return (True, res[0]) if res else (False, None)
    except: return False, None

def create_session(username):
    token = str(uuid.uuid4())
    try:
        conn = get_connection(); cursor = conn.cursor()
        cursor.execute("DELETE FROM user_sessions WHERE username = %s", (username,))
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
        return json.loads(res[0]) if res else {"tape_input": "^DJI, ^IXIC, ^GSPTSE, GC=F"}
    except: return {}

def save_global_config(data):
    try:
        conn = get_connection(); cursor = conn.cursor()
        j_str = json.dumps(data)
        cursor.execute("INSERT INTO user_profiles (username, user_data) VALUES ('GLOBAL_CONFIG', %s) ON DUPLICATE KEY UPDATE user_data = %s", (j_str, j_str))
        conn.commit(); conn.close()
    except: pass

def get_global_config_data():
    api_key = st.secrets.get("OPENAI_KEY") or st.secrets.get("OPENAI_API_KEY")
    g = load_global_config()
    if not api_key: api_key = g.get("openai_key")
    return api_key, g.get("rss_feeds", ["https://finance.yahoo.com/news/rssindex"]), g

# --- NEWS ENGINE ---
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
                            res = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}], max_tokens=20)
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
def get_fundamentals(s):
    try:
        conn = get_connection(); cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT rating, next_earnings FROM stock_cache WHERE ticker = %s", (s,))
        row = cursor.fetchone(); conn.close()
        return {"rating": row['rating'] or "N/A", "earn": row['next_earnings'] or "N/A"} if row else {"rating": "N/A", "earn": "N/A"}
    except: return {"rating": "N/A", "earn": "N/A"}

def get_batch_data(tickers_list):
    results = {}
    try:
        conn = get_connection(); cursor = conn.cursor(dictionary=True)
        cursor.execute(f"SELECT * FROM stock_cache WHERE ticker IN ({','.join(['%s']*len(tickers_list))})", tuple(tickers_list))
        for row in cursor.fetchall():
            s, p, c = row['ticker'], float(row['current_price']), float(row['day_change'])
            pp_html = ""
            if row.get('pre_post_price') and float(row['pre_post_price']) > 0:
                pp_p = float(row['pre_post_price'])
                pp_c = ((pp_p - p) / p * 100) if p > 0 else 0
                now = datetime.now(timezone.utc) - timedelta(hours=5)
                lbl = "POST" if (now.weekday() > 4 or now.hour >= 16) else "PRE" if (now.hour < 9 or (now.hour==9 and now.minute<30)) else ""
                if lbl: pp_html = f"<div style='font-size:11px; color:#888;'>{lbl}: <span style='color:{'#4caf50' if pp_c>=0 else '#ff4b4b'}; font-weight:bold;'>${pp_p:,.2f} ({pp_c:+.2f}%)</span></div>"
            
            raw_hist = row.get('price_history')
            points = json.loads(raw_hist) if raw_hist else [p]*20
            chart = pd.DataFrame({'Idx': range(len(points)), 'Stock': points})
            base = chart['Stock'].iloc[0] or 1
            chart['Stock'] = ((chart['Stock'] - base) / base) * 100
            
            results[s] = {"p": p, "d": c, "name": row.get('company_name') or s, "rsi": float(row['rsi']), "vol_pct": 150 if row['volume_status']=="HEAVY" else 50 if row['volume_status']=="LIGHT" else 100, "vol_label": row['volume_status'], "range_pos": 50, "h": float(row.get('day_high', p)), "l": float(row.get('day_low', p)), "ai": "BULLISH" if row['trend_status'] == "UPTREND" else "BEARISH", "trend": row['trend_status'], "pp": pp_html, "chart": chart}
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
        cursor.execute(f"SELECT ticker, current_price, day_change, company_name FROM stock_cache WHERE ticker IN ({','.join(['%s']*len(symbols))})", tuple(symbols))
        data_map = {row['ticker']: row for row in cursor.fetchall()}; conn.close()
        for s in symbols:
            disp = final_map.get(s, data_map[s]['company_name'].split(",")[0][:15] if (s in data_map and data_map[s]['company_name']) else s)
            if s in data_map:
                row = data_map[s]; col, arrow = ("#4caf50", "▲") if float(row['day_change']) >= 0 else ("#ff4b4b", "▼")
                items.append(f"<span style='color:#ccc; margin-left:20px;'>{disp}</span> <span style='color:{col}'>{arrow} {float(row['current_price']):,.2f} ({float(row['day_change']):+.2f}%)</span>")
    except: pass
    return "    ".join(items)

# --- UI LOGIC ---
init_db()
run_backend_update()
ACTIVE_KEY, SHARED_FEEDS, _ = get_global_config_data()

if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
    token = st.query_params.get("token")
    if token:
        user = validate_session(token)
        if user:
            st.session_state.update({"username": user, "user_data": load_user_profile(user), "global_data": load_global_config(), "logged_in": True})

st.markdown("""<style>
#MainMenu {visibility: visible;} footer {visibility: hidden;}
.block-container { padding-top: 4.5rem !important; }
div[data-testid="stVerticalBlock"] > div[style*="flex-direction: column;"] > div[data-testid="stVerticalBlock"] { background-color: #ffffff; border-radius: 12px; padding: 15px; box-shadow: 0 4px 10px rgba(0,0,0,0.05); border: 1px solid #f0f0f0; }
.metric-label { font-size: 10px; color: #888; text-transform: uppercase; display: flex; justify-content: space-between; margin-top: 8px; }
.bar-bg { background: #eee; height: 5px; border-radius: 3px; overflow: hidden; margin-top: 3px; }
.bar-fill { height: 100%; border-radius: 3px; }
.tag { font-size: 9px; padding: 1px 5px; border-radius: 3px; color: white; font-weight: bold; }
.info-pill { font-size: 10px; color: #333; background: #f8f9fa; padding: 3px 8px; border-radius: 4px; margin-right: 6px; border: 1px solid #eee; }
.news-card { padding: 8px 0 8px 15px; margin-bottom: 15px; border-left: 6px solid #ccc; background: #fff; }
.news-title { font-size: 16px; font-weight: 700; color: #333; text-decoration: none; display: block; margin-bottom: 4px; }
.news-meta { font-size: 11px; color: #888; }
.hot-badge { background: linear-gradient(90deg, #ff4b4b, #ff9100); color: white; padding: 2px 8px; border-radius: 10px; font-weight: bold; font-size: 10px; animation: pulse 2s infinite; }
@keyframes pulse { 0% { opacity: 0.8; } 50% { opacity: 1; } 100% { opacity: 0.8; } }
</style>""", unsafe_allow_html=True)

if not st.session_state["logged_in"]:
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        if os.path.exists(LOGO_PATH): st.image(LOGO_PATH, width=150)
        with st.form("login"):
            u = st.text_input("Username")
            p = st.text_input("PIN", type="password")
            if st.form_submit_button("🚀 Login"):
                exists, stored = check_user_exists(u.strip())
                if exists and stored == p:
                    st.query_params["token"] = create_session(u.strip())
                    st.session_state.update({"username": u.strip(), "user_data": load_user_profile(u.strip()), "global_data": load_global_config(), "logged_in": True})
                    st.rerun()
                elif not exists:
                    save_user_profile(u.strip(), {"w_input": "TD.TO, SPY"}, p)
                    st.query_params["token"] = create_session(u.strip())
                    st.session_state.update({"username": u.strip(), "user_data": load_user_profile(u.strip()), "global_data": load_global_config(), "logged_in": True})
                    st.rerun()
else:
    def push_user(): save_user_profile(st.session_state["username"], st.session_state["user_data"])
    def push_global(): save_global_config(st.session_state["global_data"])
    GLOBAL, USER = st.session_state["global_data"], st.session_state["user_data"]
    
    tape = get_tape_data(GLOBAL.get("tape_input", "^DJI,^IXIC"), GLOBAL.get("tape_nicknames", ""))
    components.html(f"<div style='background:#111; height:45px; display:flex; align-items:center; color:white; overflow:hidden; white-space:nowrap; border-radius:0 0 15px 15px;'><marquee scrollamount='5' style='font-weight:900; font-size:16px;'>{tape}</marquee></div>", height=50)

    with st.sidebar:
        st.markdown(f"👤 **{st.session_state['username']}**")
        new_w = st.text_area("Watchlist", USER.get("w_input", ""), height=100)
        if new_w != USER.get("w_input"): USER["w_input"] = new_w; push_user(); st.rerun()
        
        with st.expander("🔐 Admin"):
            if st.text_input("Pass", type="password") == ADMIN_PASSWORD:
                if st.button("🔎 Scan Market"):
                    picks = run_gap_scanner(ACTIVE_KEY)
                    if picks:
                        conn = get_connection(); cursor = conn.cursor()
                        cursor.execute("DELETE FROM daily_briefing WHERE date = %s", (datetime.now().strftime('%Y-%m-%d'),))
                        cursor.execute("INSERT INTO daily_briefing (date, picks) VALUES (%s, %s)", (datetime.now().strftime('%Y-%m-%d'), json.dumps(picks)))
                        conn.commit(); conn.close(); st.success("Saved!")
                if st.button("🚀 Dispatch Alerts"):
                    r = requests.get("https://atlanticcanadaschoice.com/pennypulse/up.php")
                    st.info(r.text)
        if st.button("Logout"): logout_session(st.query_params.get("token")); st.query_params.clear(); st.session_state["logged_in"] = False; st.rerun()

    @st.fragment(run_every=60)
    def render_dashboard():
        t1, t2, t3, t4 = st.tabs(["📊 Live", "🚀 Picks", "📰 News", "🌎 Discovery"])
        w_tickers = [x.strip().upper() for x in USER.get("w_input", "").split(",") if x.strip()]
        port = GLOBAL.get("portfolio", {}); p_tickers = list(port.keys())
        batch = get_batch_data(list(set(w_tickers + p_tickers)))
        news = fetch_news(SHARED_FEEDS, list(set(w_tickers + p_tickers)), ACTIVE_KEY)

        def draw_card(t, port_item=None):
            d = batch.get(t)
            if not d: return
            f = get_fundamentals(t)
            b_col = "#4caf50" if d["d"] >= 0 else "#ff4b4b"
            high_impact = [n for n in news if n['ticker'] == t and n['score'] >= 8]
            hot = "<span class='hot-badge'>🔥 HOT</span>" if len(high_impact) >= 2 else ""
            
            with st.container():
                st.markdown(f"<div style='height:4px; background:{b_col}; border-radius:4px 4px 0 0;'></div><div style='display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:15px;'><div><div style='font-size:22px; font-weight:bold;'>{t} {hot}</div><div style='font-size:12px; color:#888;'>{d['name'][:25]}...</div></div><div style='text-align:right;'><div style='font-size:22px; font-weight:bold;'>${d['p']:,.2f}</div><div style='font-size:13px; font-weight:bold; color:{b_col};'>{d['d']:+.2f}%</div>{d['pp']}</div></div><div style='margin-bottom:10px;'><span class='info-pill' style='border-left: 3px solid {b_col}'>AI: {d['ai']}</span><span class='info-pill' style='border-left: 3px solid {b_col}'>{d['trend']}</span></div>", unsafe_allow_html=True)
                st.altair_chart(alt.Chart(d["chart"]).mark_area(line={"color": b_col}, color=alt.Gradient(gradient="linear", stops=[alt.GradientStop(color=b_col, offset=0), alt.GradientStop(color="white", offset=1)], x1=1, x2=1, y1=1, y2=0)).encode(x=alt.X("Idx", axis=None), y=alt.Y("Stock", axis=None)).properties(height=40), use_container_width=True)
                rsi_bg = "#ff4b4b" if d["rsi"] > 70 else "#4caf50" if d["rsi"] < 30 else "#999"
                st.markdown(f"<div class='metric-label'>RSI ({int(d['rsi'])})</div><div class='bar-bg'><div class='bar-fill' style='width:{d['rsi']}%; background:{rsi_bg};'></div></div>", unsafe_allow_html=True)
                if port_item:
                    gain = (d["p"] - port_item["e"]) * port_item["q"]
                    st.markdown(f"<div style='background:#f9f9f9; padding:5px; margin-top:10px; border-radius:5px; display:flex; justify-content:space-between; font-size:12px;'><span>Qty: <b>{port_item['q']}</b></span><span style='color:{'#4caf50' if gain>=0 else '#ff4b4b'}; font-weight:bold;'>${gain:+,.0f}</span></div>", unsafe_allow_html=True)
                st.divider()

        with t1:
            try:
                conn = get_connection(); cursor = conn.cursor(dictionary=True)
                cursor.execute("SELECT picks, created_at FROM daily_briefing ORDER BY date DESC LIMIT 1")
                row = cursor.fetchone(); conn.close()
                if row:
                    picks_list = json.loads(row['picks'])
                    st.success(f"📌 **DAILY PICKS:** {', '.join([p.get('ticker', p) if isinstance(p, dict) else p for p in picks_list])}")
            except: pass
            cols = st.columns(3)
            for i, t in enumerate(w_tickers):
                with cols[i % 3]: draw_card(t)

        def render_news_item(n):
            score = n.get("score", 5)
            col = "#4caf50" if score >= 8 else "#ff4b4b" if score <= 3 else "#f1c40f"
            st.markdown(f"<div class='news-card' style='border-left-color:{col};'><div style='display:flex; justify-content:space-between;'><a href='{n['link']}' target='_blank' class='news-title'>{n['title']}</a><span style='background:{col}; color:white; padding:2px 8px; border-radius:12px; font-size:10px; font-weight:bold;'>{score}/10</span></div><small>{n['published']} | Ticker: <b>{n['ticker']}</b></small></div>", unsafe_allow_html=True)

        with t3:
            for n in news: render_news_item(n)
        
        with t4:
            disc_news = fetch_news(GLOBAL.get("rss_feeds", []), [], ACTIVE_KEY)
            for n in disc_news: render_news_item(n)

    render_dashboard()
