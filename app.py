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

# --- BACKEND UPDATE ENGINE (RESTORED METADATA LOOP) ---
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
                            # 1. Regular Data
                            if len(batch) == 1: df_live = live_data
                            else: 
                                if t not in live_data.columns.levels[0]: continue
                                df_live = live_data[t]
                            
                            df_live = df_live.dropna(subset=['Close'])
                            if df_live.empty: continue
                            live_price = float(df_live['Close'].iloc[-1])
                            last_time = df_live.index[-1]

                            # 2. Extended Data (TSX FIX)
                            ext_price = live_price 
                            is_tsx = t.endswith(".TO") or t.endswith(".V")

                            if not is_tsx:
                                if len(batch) == 1: df_post = post_data
                                else:
                                    if t in post_data.columns.levels[0]: df_post = post_data[t]
                                    else: df_post = pd.DataFrame()
                                if not df_post.empty:
                                    df_post = df_post.dropna(subset=['Close'])
                                    if not df_post.empty: ext_price = float(df_post['Close'].iloc[-1])

                            # 3. History
                            if len(batch) == 1: df_hist = hist_data
                            else:
                                if t in hist_data.columns.levels[0]: df_hist = hist_data[t]
                                else: df_hist = pd.DataFrame()
                            
                            day_change = 0.0; rsi = 50.0; vol_stat = "NORMAL"; trend = "NEUTRAL"
                            chart_json = "[]"; final_price = live_price 
                            day_h = live_price; day_l = live_price

                            if not df_hist.empty:
                                df_hist = df_hist.dropna(subset=['Close'])
                                daily_price = float(df_hist['Close'].iloc[-1]) 
                                if last_time.hour >= 15 and last_time.minute >= 59:
                                    if df_hist.index[-1].date() == last_time.date(): final_price = daily_price
                                
                                ext_pct = 0.0
                                if not is_tsx and final_price > 0:
                                    ext_pct = ((ext_price - final_price) / final_price) * 100

                                if len(df_hist) > 0:
                                    day_h = float(df_hist['High'].iloc[-1])
                                    day_l = float(df_hist['Low'].iloc[-1])
                                    day_h = max(day_h, live_price)
                                    day_l = min(day_l, live_price)

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

        # --- RESTORED METADATA FETCH (Ratings/Earnings) ---
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

# --- SCANNER & NEWS ---
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
            try:
                resp = requests.get(url, headers=headers, timeout=5)
                if resp.status_code == 200:
                    f = feedparser.parse(resp.content)
                    for entry in f.entries[:30]: 
                        match = re.search(r'\b[A-Z]{2,5}\b', entry.title)
                        if match: 
                            t = match.group(0)
                            if t not in ["ETF", "THE", "FOR", "AND", "NEW", "CEO", "Dow", "S&P"]: 
                                if t not in ticker_news_map: ticker_news_map[t] = entry.title
            except: continue
    except: pass
    
    scan_list = list(ticker_news_map.keys())
    try:
        if not scan_list: return []
        data = yf.download(" ".join(scan_list), period="5d", interval="1d", prepost=True, group_by='ticker', threads=True, progress=False)
        for t in scan_list:
            try:
                df = data[t] if len(scan_list) > 1 else data
                if df.empty or len(df) < 2: continue
                prev_close = float(df['Close'].iloc[-2])
                curr_price = float(df['Close'].iloc[-1]) 
                gap_pct = ((curr_price - prev_close) / prev_close) * 100
                if curr_price > max_price: continue
                if abs(gap_pct) >= min_gap:
                    candidates.append({"ticker": t, "gap": f"{gap_pct:.1f}%", "headline": ticker_news_map.get(t, "No Headline")})
            except: continue
    except: return []

    if api_key and candidates:
        try:
            candidates.sort(key=lambda x: float(x['gap'].strip('%')), reverse=True)
            top_10 = candidates[:10]
            client = openai.OpenAI(api_key=api_key)
            prompt = (f"Analyze these stocks. Pick top 3 with best CATALYST (News). Return JSON: {{'picks': ['TICKER', 'TICKER', 'TICKER']}}. Candidates: {str(top_10)}")
            resp = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"})
            picks = json.loads(resp.choices[0].message.content).get("picks", [])
            return picks if picks else [c['ticker'] for c in top_10[:3]]
        except: return [c['ticker'] for c in candidates[:3]]
    candidates.sort(key=lambda x: float(x['gap'].strip('%')), reverse=True)
    return [c['ticker'] for c in candidates[:3]]

def relative_time(date_str):
    try:
        dt = datetime.strptime(date_str, "%a, %d %b %Y %H:%M:%S %z")
        diff = datetime.now(timezone.utc) - dt
        seconds = diff.total_seconds()
        if seconds < 3600: return f"{int(seconds // 60)}m ago"
        if seconds < 86400: return f"{int(seconds // 3600)}h ago"
        return f"{int(seconds // 86400)}d ago"
    except: return "Recent"

@st.cache_data(ttl=300)
def fetch_fast_news(feeds, tickers):
    all_feeds = feeds.copy()
    if tickers:
        for t in tickers: all_feeds.append(f"https://finance.yahoo.com/rss/headline?s={t}")
    articles, seen = [], set()
    for url in all_feeds:
        try:
            f = feedparser.parse(url)
            for entry in f.entries[:5]:
                if entry.link not in seen:
                    seen.add(entry.link)
                    found_t = ""
                    match = re.search(r'symbol=([A-Z\.]+)', entry.link)
                    if match: found_t = match.group(1)
                    if not found_t and tickers:
                        for t in tickers:
                            if t in entry.title.upper(): found_t = t; break
                    articles.append({"title": entry.title, "link": entry.link, "published": relative_time(entry.get("published", "")), "ticker": found_t if found_t else "MARKET"})
        except: pass
    return articles

# --- DATA FORMATTER (RESTORED CHARTS) ---
@st.cache_data(ttl=600)
def get_fundamentals(s):
    try:
        conn = get_connection(); cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT rating, next_earnings FROM stock_cache WHERE ticker = %s", (s,))
        row = cursor.fetchone(); conn.close()
        return {"rating": row['rating'] or "N/A", "earn": row['next_earnings'] or "N/A"} if row else {"rating": "N/A", "earn": "N/A"}
    except: return {"rating": "N/A", "earn": "N/A"}

def get_batch_data(tickers_list):
    if not tickers_list: return {}
    results = {}
    try:
        conn = get_connection(); cursor = conn.cursor(dictionary=True)
        format_strings = ','.join(['%s'] * len(tickers_list))
        cursor.execute(f"SELECT * FROM stock_cache WHERE ticker IN ({format_strings})", tuple(tickers_list))
        rows = cursor.fetchall(); conn.close()
        for row in rows:
            s = row['ticker']
            price = float(row['current_price']); change = float(row['day_change'])
            rsi_val = float(row['rsi'] or 50); trend = row['trend_status']
            vol_stat = row['volume_status']; display_name = row.get('company_name') or s
            pp_html = ""
            
            is_tsx = s.endswith(".TO") or s.endswith(".V")
            if not is_tsx and row.get('pre_post_price') and float(row['pre_post_price']) > 0:
                pp_p = float(row['pre_post_price'])
                pp_c = ((pp_p - price) / price) * 100 if price > 0 else 0
                now = datetime.now(timezone.utc) - timedelta(hours=5)
                lbl = "POST" if (now.hour >= 16 or now.weekday() > 4) else "PRE" if now.hour < 9 else ""
                if lbl:
                    col = "#4caf50" if pp_c >= 0 else "#ff4b4b"
                    pp_html = f"<div style='font-size:11px; color:#888; margin-top:2px;'>{lbl}: <span style='color:{col}; font-weight:bold;'>${pp_p:,.2f} ({pp_c:+.2f}%)</span></div>"

            ai_label = "NEUTRAL"
            if rsi_val >= 70: ai_label = "OVERBOUGHT"
            elif rsi_val <= 30: ai_label = "OVERSOLD"
            elif trend == "UPTREND": ai_label = "RISING"
            elif trend == "DOWNTREND": ai_label = "FALLING"

            day_h = float(row.get('day_high') or price); day_l = float(row.get('day_low') or price)
            range_pos = max(0, min(100, ((price - day_l) / (day_h - day_l)) * 100)) if day_h > day_l else 50
            
            # --- RESTORED CHART DATA ---
            raw_hist = row.get('price_history')
            points = json.loads(raw_hist) if raw_hist else [price] * 20
            chart_data = pd.DataFrame({'Idx': range(len(points)), 'Stock': points})
            base = chart_data['Stock'].iloc[0] if chart_data['Stock'].iloc[0] != 0 else 1
            chart_data['Stock'] = ((chart_data['Stock'] - base) / base) * 100
            
            results[s] = {"p": price, "d": change, "name": display_name, "rsi": rsi_val, "vol_pct": 150 if vol_stat=="HEAVY" else 100, "vol_label": vol_stat, "range_pos": range_pos, "h": day_h, "l": day_l, "ai": ai_label, "trend": trend, "pp": pp_html, "chart": chart_data}
    except: pass
    return results

# --- AUTH & TAPE ---
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
    for _ in range(3):
        try:
            conn = get_connection(); 
            if not conn.is_connected(): conn.reconnect(attempts=3, delay=1)
            cursor = conn.cursor(); cursor.execute("SELECT username FROM user_sessions WHERE token = %s", (token,))
            res = cursor.fetchone(); conn.close(); return res[0] if res else None
        except: time.sleep(0.5); continue
    return None

def logout_session(token):
    try:
        conn = get_connection(); cursor = conn.cursor()
        cursor.execute("DELETE FROM user_sessions WHERE token = %s", (token,))
        conn.commit(); conn.close()
    except: pass

def load_user_profile(username):
    try:
        conn = get_connection(); cursor = conn.cursor()
        cursor.execute("SELECT user_data FROM user_profiles WHERE username = %s", (username,))
        res = cursor.fetchone(); conn.close(); return json.loads(res[0]) if res else {"w_input": "TD.TO, NKE, SPY"}
    except: return {"w_input": "TD.TO, NKE, SPY"}

def save_user_profile(username, data, pin=None):
    try:
        conn = get_connection(); cursor = conn.cursor(); j_str = json.dumps(data)
        if pin: cursor.execute("INSERT INTO user_profiles (username, user_data, pin) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE user_data=%s, pin=%s", (username, j_str, pin, j_str, pin))
        else: cursor.execute("UPDATE user_profiles SET user_data=%s WHERE username=%s", (j_str, username))
        conn.commit(); conn.close()
    except: pass

def load_global_config():
    try:
        conn = get_connection(); cursor = conn.cursor()
        cursor.execute("SELECT user_data FROM user_profiles WHERE username = 'GLOBAL_CONFIG'")
        res = cursor.fetchone(); conn.close(); return json.loads(res[0]) if res else {}
    except: return {}

def save_global_config(data):
    try:
        conn = get_connection(); cursor = conn.cursor(); j_str = json.dumps(data)
        cursor.execute("INSERT INTO user_profiles (username, user_data) VALUES ('GLOBAL_CONFIG', %s) ON DUPLICATE KEY UPDATE user_data=%s", (j_str, j_str))
        conn.commit(); conn.close()
    except: pass

def get_global_config_data():
    api_key = st.secrets.get("OPENAI_KEY"); g = load_global_config()
    if not api_key: api_key = g.get("openai_key")
    return api_key, g.get("rss_feeds", ["https://finance.yahoo.com/news/rssindex"]), g

# --- RESTORED SCROLLER (CSS ANIMATION) ---
@st.cache_data(ttl=60)
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
                row = data_map[s]; col = "#4caf50" if float(row['day_change']) >= 0 else "#ff4b4b"
                items.append(f"<span style='color:#ccc; margin-left:20px;'>{disp}</span> <span style='color:{col}'>▲ {float(row['current_price']):,.2f} ({float(row['day_change']):+.2f}%)</span>")
            else: items.append(f"<span style='color:#ccc; margin-left:20px;'>{disp}</span> <span style='color:#888;'>(...)</span>")
    except: pass
    return "".join(items)

# --- APP START ---
init_db()
run_backend_update()
ACTIVE_KEY, SHARED_FEEDS, _ = get_global_config_data()

if "init" not in st.session_state:
    st.session_state["init"] = True
    st.session_state["logged_in"] = False
    url_token = st.query_params.get("token", None)
    if url_token:
        user = validate_session(url_token)
        if user:
            st.session_state.update({"username": user, "user_data": load_user_profile(user), "global_data": load_global_config(), "logged_in": True})

st.markdown("""<style>
.block-container { padding-top: 4.5rem !important; }
div[data-testid="stVerticalBlock"] > div[style*="flex-direction: column;"] > div[data-testid="stVerticalBlock"] { background-color: #ffffff; border-radius: 12px; padding: 15px; box-shadow: 0 4px 10px rgba(0,0,0,0.05); border: 1px solid #f0f0f0; }
.metric-label { font-size: 10px; color: #888; font-weight: 600; display: flex; justify-content: space-between; margin-top: 8px; text-transform: uppercase; }
.bar-bg { background: #eee; height: 5px; border-radius: 3px; width: 100%; margin-top: 3px; overflow: hidden; }
.bar-fill { height: 100%; border-radius: 3px; }
.tag { font-size: 9px; padding: 1px 5px; border-radius: 3px; font-weight: bold; color: white; }
.info-pill { font-size: 10px; color: #333; background: #f8f9fa; padding: 3px 8px; border-radius: 4px; font-weight: 600; margin-right: 6px; display: inline-block; border: 1px solid #eee; }
.news-card { padding: 8px 0 8px 15px; margin-bottom: 15px; border-left: 6px solid #ccc; background-color: #fff; }
.news-title { font-size: 16px; font-weight: 700; color: #333; text-decoration: none; display: block; margin-bottom: 4px; line-height: 1.3; }
.news-meta { font-size: 11px; color: #888; }
.ticker-badge { font-size: 9px; padding: 2px 5px; border-radius: 3px; color: white; font-weight: bold; margin-right: 6px; display: inline-block; vertical-align: middle; }
</style>""", unsafe_allow_html=True)

if not st.session_state["logged_in"]:
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        if os.path.exists(LOGO_PATH): st.image(LOGO_PATH, width=150)
        else: st.markdown("<h1 style='text-align:center;'>⚡ Penny Pulse</h1>", unsafe_allow_html=True)
        with st.form("login_form"):
            user = st.text_input("Username", placeholder="e.g. Dave")
            pin = st.text_input("4-Digit PIN", type="password", max_chars=4)
            if st.form_submit_button("🚀 Login / Start", type="primary"):
                exists, stored_pin = check_user_exists(user.strip())
                if (exists and stored_pin == pin) or not exists:
                    if not exists: save_user_profile(user.strip(), {"w_input": "TD.TO, SPY"}, pin)
                    st.query_params["token"] = create_session(user.strip())
                    st.session_state.update({"username": user.strip(), "user_data": load_user_profile(user.strip()), "global_data": load_global_config(), "logged_in": True})
                    st.rerun()
else:
    def push_user(): save_user_profile(st.session_state["username"], st.session_state["user_data"])
    def push_global(): save_global_config(st.session_state["global_data"])
    GLOBAL, USER = st.session_state["global_data"], st.session_state["user_data"]
    
    tape = get_tape_data(GLOBAL.get("tape_input", "^DJI, ^IXIC"), GLOBAL.get("tape_nicknames", ""))
    components.html(f"""<!DOCTYPE html><html><head><style>body{{margin:0;padding:0;background:transparent;overflow:hidden;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}}.ticker-container{{width:100%;height:45px;background:#111;display:flex;align-items:center;border-bottom:1px solid #333;border-radius:0 0 15px 15px;box-shadow:0 4px 10px rgba(0,0,0,0.3)}}.ticker-wrap{{width:100%;overflow:hidden;white-space:nowrap}}.ticker-move{{display:inline-block;animation:ticker 15s linear infinite}}@keyframes ticker{{0%{{transform:translate3d(0,0,0)}}100%{{transform:translate3d(-25%,0,0)}}}}.ticker-item{{display:inline-block;color:white;font-weight:900;font-size:16px;padding:0 20px}}</style></head><body><div class="ticker-container"><div class="ticker-wrap"><div class="ticker-move"><span class="ticker-item">{tape}</span></div></div></div></body></html>""", height=50)

    with st.sidebar:
        st.markdown(f"<div style='background:#f0f2f6; padding:10px; border-radius:5px; margin-bottom:10px; text-align:center;'>👤 <b>{st.session_state['username']}</b></div>", unsafe_allow_html=True)
        new_w = st.text_area("Edit Tickers", value=USER.get("w_input", ""), height=100)
        if new_w != USER.get("w_input"): USER["w_input"] = new_w; push_user(); st.rerun()
        
        with st.expander("🔔 Alert Settings"):
            curr_tg = USER.get("telegram_id", "")
            new_tg = st.text_input("Telegram Chat ID", value=curr_tg)
            if new_tg != curr_tg: USER["telegram_id"] = new_tg.strip(); push_user(); st.success("Saved!"); time.sleep(1); st.rerun()
            st.checkbox("AI Daily Picks", value=USER.get("alert_pre", True))
        
        with st.expander("🔐 Admin"):
            if st.text_input("Password", type="password") == ADMIN_PASSWORD:
                if st.button("🔎 Scan Market"):
                    picks = run_gap_scanner(ACTIVE_KEY)
                    if picks:
                        conn = get_connection(); cursor = conn.cursor()
                        today_str = datetime.now().strftime('%Y-%m-%d')
                        cursor.execute("DELETE FROM daily_briefing WHERE date = %s", (today_str,))
                        cursor.execute("INSERT INTO daily_briefing (date, picks, sent) VALUES (%s, %s, 0)", (today_str, json.dumps(picks)))
                        conn.commit(); conn.close(); st.success("Picks Saved!")
                if st.button("💾 Save Global Settings"):
                    push_global(); st.success("Saved!")

        if st.button("Logout"): logout_session(st.query_params.get("token")); st.query_params.clear(); st.session_state["logged_in"] = False; st.rerun()

    @st.fragment(run_every=60)
    def render_dashboard():
        t1, t2, t3, t4 = st.tabs(["📊 Live Market", "🚀 My Picks", "📰 News Wire", "🏆 Top Movers"])
        w_tickers = [x.strip().upper() for x in USER.get("w_input", "").split(",") if x.strip()]
        port = GLOBAL.get("portfolio", {}); p_tickers = list(port.keys())
        all_view = list(set(w_tickers + p_tickers))
        batch = get_batch_data(all_view)

        def draw_card(t, port_item=None):
            d = batch.get(t)
            if not d: return
            f = get_fundamentals(t)
            b_col = "#4caf50" if d["d"] >= 0 else "#ff4b4b"
            ai_bg = "#ff9100" if d["ai"] == "OVERBOUGHT" else "#4caf50" if d["ai"] == "RISING" or d["ai"] == "OVERSOLD" else "#ff4b4b"
            pills = f'<span class="info-pill" style="border-left: 3px solid {ai_bg}">AI: {d["ai"]}</span><span class="info-pill" style="border-left: 3px solid {b_col}">TREND: {d["trend"]}</span>'
            if f["rating"] != "N/A": pills += f'<span class="info-pill" style="border-left: 3px solid #333">RATING: {f["rating"]}</span>'
            if f["earn"] != "N/A": pills += f'<span class="info-pill" style="border-left: 3px solid #333">EARN: {f["earn"]}</span>'
            
            with st.container():
                st.markdown(f"<div style='height:4px; width:100%; background-color:{b_col}; border-radius: 4px 4px 0 0;'></div><div style='display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:15px;'><div><div style='font-size:22px; font-weight:bold; margin-right:8px; color:#2c3e50;'>{t}</div><div style='font-size:12px; color:#888; margin-top:-2px;'>{d['name'][:25]}...</div></div><div style='text-align:right;'><div style='font-size:22px; font-weight:bold; color:#2c3e50;'>${d['p']:,.2f}</div><div style='font-size:13px; font-weight:bold; color:{b_col}; margin-top:-4px;'>{d['d']:.2f}%</div>{d['pp']}</div></div><div style='margin-bottom:10px; display:flex; flex-wrap:wrap; gap:4px;'>{pills}</div>", unsafe_allow_html=True)
                st.altair_chart(alt.Chart(d["chart"]).mark_area(line={"color": b_col}, color=alt.Gradient(gradient="linear", stops=[alt.GradientStop(color=b_col, offset=0), alt.GradientStop(color="white", offset=1)], x1=1, x2=1, y1=1, y2=0)).encode(x=alt.X("Idx", axis=None), y=alt.Y("Stock", axis=None), tooltip=[]).configure_view(strokeWidth=0).properties(height=45), use_container_width=True)
                st.markdown(f"<div class='metric-label'><span>Day Range</span><span style='color:#555'>${d['l']:,.2f} - ${d['h']:,.2f}</span></div><div class='bar-bg'><div class='bar-fill' style='width:{d['range_pos']}%; background: linear-gradient(90deg, #ff4b4b, #f1c40f, #4caf50);'></div></div><div class='metric-label'><span>RSI ({int(d['rsi'])})</span><span class='tag' style='background:#999'>NEUTRAL</span></div><div class='bar-bg'><div class='bar-fill' style='width:{d['rsi']}%; background:#999;'></div></div>", unsafe_allow_html=True)
                st.divider()

        with t1:
            try:
                conn = get_connection(); cursor = conn.cursor(dictionary=True)
                cursor.execute("SELECT picks FROM daily_briefing ORDER BY date DESC LIMIT 1")
                row = cursor.fetchone(); conn.close()
                if row: st.success(f"📌 **DAILY PICKS:** {', '.join([p.get('ticker', p) if isinstance(p, dict) else p for p in json.loads(row['picks'])])}")
            except: pass
            cols = st.columns(3)
            for i, t in enumerate(w_tickers):
                with cols[i % 3]: draw_card(t)

        with t2:
            if not port: st.info("No Picks.")
            else:
                cols = st.columns(3)
                for i, (k, v) in enumerate(port.items()):
                    with cols[i % 3]: draw_card(k, v)

        with t3:
            st.markdown("### 📰 Market Wire")
            mode = st.radio("Source", ["👀 My Watchlist", "🌎 General Market"], horizontal=True)
            if "news_limit" not in st.session_state: st.session_state["news_limit"] = 5
            target_tickers = all_view if mode == "👀 My Watchlist" else []
            feeds = [] if mode == "👀 My Watchlist" else GLOBAL.get("rss_feeds", ["https://finance.yahoo.com/news/rssindex"])
            all_news = fetch_fast_news(feeds, target_tickers)
            visible_news = all_news[:st.session_state["news_limit"]]
            if not visible_news: st.info("No news.")
            else:
                for n in visible_news:
                    col = "#4caf50"
                    st.markdown(f"<div class='news-card'><div style='display:flex; align-items:center;'><span class='ticker-badge' style='background-color:{col}'>{n['ticker']}</span><a href='{n['link']}' target='_blank' class='news-title'>{n['title']}</a></div><div class='news-meta'>{n['published']}</div></div>", unsafe_allow_html=True)
                if len(all_news) > st.session_state["news_limit"]:
                    if st.button("Load More", use_container_width=True):
                        st.session_state["news_limit"] += 5
                        st.rerun()

        with t4:
            st.subheader("🏆 Market Movers")
            try:
                movers = pd.DataFrame(yf.download("^IXIC ^DJI ^GSPTSE", period="1d")['Close'].iloc[-1]).reset_index()
                movers.columns = ['Ticker', 'Price']
                st.dataframe(movers, use_container_width=True, hide_index=True)
            except: st.warning("Data unavailable.")

    render_dashboard()
