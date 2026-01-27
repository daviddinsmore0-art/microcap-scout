import streamlit as st
import pandas as pd
import altair as alt
import time
import json
import mysql.connector
import requests
import yfinance as yf
# Using generic Exception to strictly prevent NameError/ImportError crashes
from datetime import datetime, timedelta, timezone
import streamlit.components.v1 as components
import os
import uuid
import re
import numpy as np

# --- IMPORTS FOR NEWS & AI ---
try:
    import feedparser
    import openai
    NEWS_LIB_READY = True
except ImportError:
    NEWS_LIB_READY = False

# --- SETUP & STYLING ---
try:
    st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="wide")
except:
    pass

# *** CONFIG ***
ADMIN_PASSWORD = st.secrets.get("ADMIN_PASSWORD", "")
LOGO_PATH = "logo.png"

# *** DATABASE CONFIG (MASTER KEY) ***
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
        # Ensure daily_briefing table exists with 'sent' column
        cursor.execute("CREATE TABLE IF NOT EXISTS daily_briefing (date DATE PRIMARY KEY, picks JSON, sent TINYINT DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        
        # Auto-patch: Add 'sent' column if it's missing
        try:
            cursor.execute("ALTER TABLE daily_briefing ADD COLUMN sent TINYINT DEFAULT 0")
        except: pass

        # Auto-patch missing stock columns
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
        all_tickers = set(["^DJI", "^IXIC", "^GSPTSE", "GC=F"]) 
        for r in users:
            try:
                data = json.loads(r['user_data'])
                if 'w_input' in data: all_tickers.update([t.strip().upper() for t in data['w_input'].split(",") if t.strip()])
                if 'portfolio' in data: all_tickers.update(data['portfolio'].keys())
                if 'tape_input' in data: all_tickers.update([t.strip().upper() for t in data['tape_input'].split(",") if t.strip()])
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
            tickers_str = " ".join(to_fetch_price)
            live_data = yf.download(tickers_str, period="5d", interval="1m", prepost=True, group_by='ticker', threads=True, progress=False)
            hist_data = yf.download(tickers_str, period="1mo", interval="1d", group_by='ticker', threads=True, progress=False)

            for t in to_fetch_price:
                try:
                    # LIVE
                    if len(to_fetch_price) == 1: df_live = live_data
                    else: 
                        if t not in live_data.columns.levels[0]: continue
                        df_live = live_data[t]
                    df_live = df_live.dropna(subset=['Close'])
                    if df_live.empty: continue
                    live_price = float(df_live['Close'].iloc[-1])

                    # HISTORY
                    if len(to_fetch_price) == 1: df_hist = hist_data
                    else:
                        if t in hist_data.columns.levels[0]: df_hist = hist_data[t]
                        else: df_hist = pd.DataFrame()
                    
                    day_change = 0.0; rsi = 50.0; vol_stat = "NORMAL"; trend = "NEUTRAL"
                    chart_json = "[]"
                    close_price = live_price 
                    day_h = live_price; day_l = live_price

                    if not df_hist.empty:
                        df_hist = df_hist.dropna(subset=['Close'])
                        close_price = float(df_hist['Close'].iloc[-1]) 
                        if len(df_hist) > 0:
                            day_h = float(df_hist['High'].iloc[-1])
                            day_l = float(df_hist['Low'].iloc[-1])
                            day_h = max(day_h, live_price)
                            day_l = min(day_l, live_price)

                        if len(df_hist) > 1:
                            prev_close = float(df_hist['Close'].iloc[-2])
                            if df_live.index[-1].date() > df_hist.index[-1].date():
                                prev_close = float(df_hist['Close'].iloc[-1])
                            day_change = ((close_price - prev_close) / prev_close) * 100
                        
                        trend = "UPTREND" if close_price > df_hist['Close'].tail(20).mean() else "DOWNTREND"
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

                    final_price = close_price
                    pp_p = 0.0; pp_pct = 0.0
                    is_crypto = "-" in t or "=F" in t
                    if is_crypto:
                        final_price = live_price
                        if len(df_hist) > 0:
                            day_change = ((live_price - float(df_hist['Close'].iloc[-1])) / float(df_hist['Close'].iloc[-1])) * 100
                    else:
                        if abs(live_price - close_price) > 0.01:
                            pp_p = live_price
                            pp_pct = ((live_price - close_price) / close_price) * 100

                    sql = """INSERT INTO stock_cache (ticker, current_price, day_change, rsi, volume_status, trend_status, price_history, pre_post_price, pre_post_pct, day_high, day_low, last_updated) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()) ON DUPLICATE KEY UPDATE current_price=%s, day_change=%s, rsi=%s, volume_status=%s, trend_status=%s, price_history=%s, pre_post_price=%s, pre_post_pct=%s, day_high=%s, day_low=%s, last_updated=NOW()"""
                    v = (t, final_price, day_change, rsi, vol_stat, trend, chart_json, pp_p, pp_pct, day_h, day_l, final_price, day_change, rsi, vol_stat, trend, chart_json, pp_p, pp_pct, day_h, day_l)
                    cursor.execute(sql, v)
                    conn.commit()
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

# --- SCANNER ENGINE (ROBUST BATCH + 0.5% GAP) ---
@st.cache_data(ttl=900)
def run_gap_scanner(api_key):
    fh_key = st.secrets.get("FINNHUB_API_KEY")
    candidates = []
    discovery_tickers = set()
    
    # 1. DISCOVERY: RSS Feeds (WITH HEADERS)
    try:
        feeds = ["https://finance.yahoo.com/rss/most-active", "https://finance.yahoo.com/news/rssindex"]
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        
        for url in feeds:
            try:
                resp = requests.get(url, headers=headers, timeout=5)
                if resp.status_code == 200:
                    f = feedparser.parse(resp.content)
                    for entry in f.entries[:25]:
                        match = re.search(r'\b[A-Z]{2,5}\b', entry.title)
                        if match: 
                            t = match.group(0)
                            if t not in ["ETF", "THE", "FOR", "AND", "NEW", "CEO"]: 
                                discovery_tickers.add(t)
            except: continue
    except: pass
    
    # 2. FORCE FALLBACK (Ensures scanner never fails)
    staples = ["NVDA", "TSLA", "AMD", "MARA", "COIN", "PLTR", "SOFI", "LCID", "GME", "HOLO", "MSTR", "DJT", "RIVN", "HOOD", "DKNG"]
    discovery_tickers.update(staples)
    
    scan_list = list(discovery_tickers)
    
    # 3. BATCH DOWNLOAD & FILTER
    try:
        data = yf.download(" ".join(scan_list), period="5d", interval="1d", group_by='ticker', threads=True, progress=False)
        
        for t in scan_list:
            try:
                if len(scan_list) > 1:
                    if t not in data.columns.levels[0]: continue
                    df = data[t]
                else: df = data

                if df.empty or len(df) < 2: continue

                prev_close = float(df['Close'].iloc[-2])
                curr_price = float(df['Close'].iloc[-1]) 
                
                # Check Finnhub for real-time price
                try:
                    r = requests.get(f"https://finnhub.io/api/v1/quote?symbol={t}&token={fh_key}", timeout=1).json()
                    if 'c' in r and r['c'] != 0: curr_price = float(r['c'])
                except: pass

                gap_pct = ((curr_price - prev_close) / prev_close) * 100
                avg_vol = df['Volume'].mean()
                atr = (df['High'] - df['Low']).mean()

                # RELAXED CRITERIA: Gap > 0.5% | Vol > 50k
                if abs(gap_pct) >= 0.5 and avg_vol > 50000:
                    candidates.append({
                        "ticker": t,
                        "gap": gap_pct,
                        "atr": atr
                    })
            except: continue
    except: return []

    # 4. AI SELECTION
    if api_key and candidates:
        try:
            candidates.sort(key=lambda x: abs(x['gap']), reverse=True)
            top_10 = candidates[:10]
            
            client = openai.OpenAI(api_key=api_key)
            prompt = f"Pick Top 3 for day trading. Return JSON: {{'picks': ['TICKER', 'TICKER', 'TICKER']}}\nData: {str(top_10)}"
            resp = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"})
            picks = json.loads(resp.choices[0].message.content).get("picks", [])
            return picks if picks else [c['ticker'] for c in top_10[:3]]
        except: 
            return [c['ticker'] for c in candidates[:3]]
            
    # Fallback if no AI
    candidates.sort(key=lambda x: abs(x['gap']), reverse=True)
    return [c['ticker'] for c in candidates[:3]]

# --- MORNING BRIEFING ENGINE ---
def run_morning_briefing(api_key):
    try:
        now = datetime.now()
        if now.weekday() > 4: return 
        today_str = now.strftime('%Y-%m-%d')
        conn = get_connection(); cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT picks FROM daily_briefing WHERE date = %s", (today_str,))
        if not cursor.fetchone() and 9 <= now.hour <= 10 and 45 <= now.minute <= 59:
            final_picks = run_gap_scanner(api_key)
            if final_picks:
                cursor.execute("INSERT INTO daily_briefing (date, picks, sent) VALUES (%s, %s, 0)", (today_str, json.dumps(final_picks)))
                conn.commit()
        conn.close()
    except: pass

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
        cursor.execute("DELETE FROM user_sessions WHERE username = %s", (username,))
        cursor.execute("INSERT INTO user_sessions (token, username) VALUES (%s, %s)", (token, username))
        conn.commit(); conn.close()
        return token
    except: return None

def validate_session(token):
    for _ in range(3):
        try:
            conn = get_connection(); 
            if not conn.is_connected(): conn.reconnect(attempts=3, delay=1)
            cursor = conn.cursor(); cursor.execute("SELECT username FROM user_sessions WHERE token = %s", (token,))
            res = cursor.fetchone(); conn.close()
            if res: return res[0]
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
        res = cursor.fetchone(); conn.close()
        return json.loads(res[0]) if res else {"w_input": "TD.TO, NKE, SPY"}
    except: return {"w_input": "TD.TO, NKE, SPY"}

def save_user_profile(username, data, pin=None):
    try:
        conn = get_connection(); cursor = conn.cursor()
        j_str = json.dumps(data)
        if pin:
            sql = "INSERT INTO user_profiles (username, user_data, pin) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE user_data = %s, pin = %s"
            cursor.execute(sql, (username, j_str, pin, j_str, pin))
        else:
            sql = "INSERT INTO user_profiles (username, user_data) VALUES (%s, %s) ON DUPLICATE KEY UPDATE user_data = %s"
            cursor.execute(sql, (username, j_str, j_str))
        conn.commit(); conn.close()
    except: pass

def load_global_config():
    try:
        conn = get_connection(); cursor = conn.cursor()
        cursor.execute("SELECT user_data FROM user_profiles WHERE username = 'GLOBAL_CONFIG'")
        res = cursor.fetchone(); conn.close()
        return json.loads(res[0]) if res else {"portfolio": {}, "openai_key": "", "rss_feeds": ["https://finance.yahoo.com/news/rssindex"], "tape_input": "^DJI, ^IXIC, ^GSPTSE, GC=F"}
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
    api_key = None; rss_feeds = ["https://finance.yahoo.com/news/rssindex"]
    try: api_key = st.secrets.get("OPENAI_KEY") or st.secrets.get("OPENAI_API_KEY")
    except: pass
    g = load_global_config()
    if not api_key: api_key = g.get("openai_key")
    if g.get("rss_feeds"): rss_feeds = g.get("rss_feeds")
    return api_key, rss_feeds, g

# --- NEWS ENGINE ---
def relative_time(date_str):
    try:
        dt = datetime.strptime(date_str, "%a, %d %b %Y %H:%M:%S %z")
        diff = datetime.now(timezone.utc) - dt
        seconds = diff.total_seconds()
        if seconds < 3600: return f"{int(seconds // 60)}m ago"
        if seconds < 86400: return f"{int(seconds // 3600)}h ago"
        return f"{int(seconds // 86400)}d ago"
    except: return "Recent"

@st.cache_data(ttl=600)
def fetch_news(feeds, tickers, api_key):
    if not NEWS_LIB_READY: return []
    all_feeds = feeds.copy()
    if tickers:
        for t in tickers: all_feeds.append(f"https://finance.yahoo.com/rss/headline?s={t}")
    articles = []; seen = set(); smart_tickers = {}
    if tickers:
        for t in tickers: smart_tickers[t] = t.split('.')[0]
    for url in all_feeds:
        try:
            f = feedparser.parse(url)
            limit = 5 if tickers else 10
            for entry in f.entries[:limit]:
                if entry.link not in seen:
                    seen.add(entry.link)
                    found_ticker, sentiment = "", "NEUTRAL"
                    title_upper = entry.title.upper(); summary_text = entry.get("summary", "")
                    if api_key:
                        try:
                            client = openai.OpenAI(api_key=api_key)
                            prompt = f"Analyze this news: '{entry.title}'. Return: TICKER|SENTIMENT."
                            response = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}], max_tokens=15)
                            ans = response.choices[0].message.content.strip().upper()
                            if "|" in ans: 
                                parts = ans.split("|"); found_ticker = parts[0].strip()
                                raw_sent = parts[1].strip()
                                if "POS" in raw_sent or "BULL" in raw_sent: sentiment = "BULLISH"
                                elif "NEG" in raw_sent or "BEAR" in raw_sent: sentiment = "BEARISH"
                                else: sentiment = "NEUTRAL"
                        except: pass
                    if not found_ticker and tickers:
                        for original_t, root_t in smart_tickers.items():
                            if re.search(r'\b'+re.escape(root_t)+r'\b', title_upper) or original_t in title_upper: found_ticker = original_t; break
                    articles.append({"title": entry.title, "link": entry.link, "published": relative_time(entry.get("published", "")), "ticker": found_ticker, "sentiment": sentiment})
        except: pass
    return articles

# --- DATA ENGINE ---
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
            rsi_val = float(row['rsi']); trend = row['trend_status']
            vol_stat = row['volume_status']; display_name = row.get('company_name') or s
            pp_html = ""
            if row.get('pre_post_price') and float(row['pre_post_price']) > 0:
                pp_p = float(row['pre_post_price']); pp_c = float(row['pre_post_pct'])
                if abs(pp_p - price) > 0.01:
                    now = datetime.now(timezone.utc) - timedelta(hours=5)
                    lbl = "POST" if now.hour >= 16 else "PRE" if now.hour < 9 else "LIVE"
                    if now.weekday() > 4: lbl = "POST" 
                    col = "#4caf50" if pp_c >= 0 else "#ff4b4b"
                    pp_html = f"<div style='font-size:11px; color:#888; margin-top:2px;'>{lbl}: <span style='color:{col}; font-weight:bold;'>${pp_p:,.2f} ({pp_c:+.2f}%)</span></div>"
            vol_pct = 150 if vol_stat == "HEAVY" else (50 if vol_stat == "LIGHT" else 100)
            day_h = float(row.get('day_high') or price); day_l = float(row.get('day_low') or price)
            range_pos = 50
            if day_h > day_l: range_pos = max(0, min(100, ((price - day_l) / (day_h - day_l)) * 100))
            raw_hist = row.get('price_history')
            points = json.loads(raw_hist) if raw_hist else [price] * 20
            chart_data = pd.DataFrame({'Idx': range(len(points)), 'Stock': points})
            base = chart_data['Stock'].iloc[0] if chart_data['Stock'].iloc[0] != 0 else 1
            chart_data['Stock'] = ((chart_data['Stock'] - base) / base) * 100
            results[s] = {"p": price, "d": change, "name": display_name, "rsi": rsi_val, "vol_pct": vol_pct, "vol_label": vol_stat, "range_pos": range_pos, "h": day_h, "l": day_l, "ai": "BULLISH" if trend == "UPTREND" else "BEARISH", "trend": trend, "pp": pp_html, "chart": chart_data}
    except: pass
    return results

@st.cache_data(ttl=60)
def get_tape_data(symbol_string, nickname_string=""):
    items = []; symbols = [x.strip().upper() for x in symbol_string.split(",") if x.strip()]
    nick_map = {}
    if nickname_string:
        try:
            for p in nickname_string.split(","): k, v = p.split(":"); nick_map[k.strip().upper()] = v.strip().upper()
        except: pass
    defaults = {"^DJI": "DOW", "^IXIC": "NASDAQ", "^GSPTSE": "TSX", "GC=F": "GOLD", "BTC-USD": "BTC"}
    final_map = defaults.copy(); final_map.update(nick_map)
    if not symbols: return ""
    try:
        conn = get_connection(); cursor = conn.cursor(dictionary=True)
        cursor.execute(f"SELECT * FROM stock_cache WHERE ticker IN ({','.join(['%s']*len(symbols))})", tuple(symbols))
        rows = cursor.fetchall(); conn.close()
        data_map = {row['ticker']: row for row in rows}
        for s in symbols:
            if s in data_map:
                row = data_map[s]; px = float(row['current_price']); chg = float(row['day_change'])
                disp = final_map.get(s, row.get('company_name', s).split(",")[0][:15])
                col, arrow = ("#4caf50", "▲") if chg >= 0 else ("#ff4b4b", "▼")
                items.append(f"<span style='color:#ccc; margin-left:20px;'>{disp}</span> <span style='color:{col}'>{arrow} {px:,.2f} ({chg:+.2f}%)</span>")
    except: pass
    return "    ".join(items)

# --- UI LOGIC ---
init_db()
run_backend_update()
ACTIVE_KEY, SHARED_FEEDS, _ = get_global_config_data()
run_morning_briefing(ACTIVE_KEY)

if "init" not in st.session_state:
    st.session_state["init"] = True
    st.session_state["logged_in"] = False
    url_token = st.query_params.get("token", None)
    if url_token:
        user = validate_session(url_token)
        if user:
            st.session_state["username"] = user
            st.session_state["user_data"] = load_user_profile(user)
            st.session_state["global_data"] = load_global_config()
            st.session_state["logged_in"] = True
if "fcm_token" in st.query_params: st.query_params.clear()

st.markdown("""<style>
#MainMenu {visibility: visible;} footer {visibility: hidden;}
.block-container { padding-top: 4.5rem !important; padding-bottom: 2rem; }
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
        st.markdown("##### 👋 Welcome")
        with st.form("login_form"):
            user = st.text_input("Username", placeholder="e.g. Dave")
            pin = st.text_input("4-Digit PIN", type="password", max_chars=4, help="Create a PIN if you are new. Enter your PIN if you are returning.")
            if st.form_submit_button("🚀 Login / Start", type="primary"):
                exists, stored_pin = check_user_exists(user.strip())
                if exists and stored_pin == pin:
                    st.success("Welcome back!")
                    st.query_params["token"] = create_session(user.strip())
                    st.session_state["username"] = user.strip()
                    st.session_state["user_data"] = load_user_profile(user.strip())
                    st.session_state["global_data"] = load_global_config()
                    st.session_state["logged_in"] = True
                    st.rerun()
                elif exists: st.error("❌ Incorrect PIN.")
                else:
                    save_user_profile(user.strip(), {"w_input": "TD.TO, SPY"}, pin)
                    st.query_params["token"] = create_session(user.strip())
                    st.session_state["username"] = user.strip()
                    st.session_state["user_data"] = load_user_profile(user.strip())
                    st.session_state["global_data"] = load_global_config()
                    st.session_state["logged_in"] = True
                    st.rerun()
else:
    def push_user(): save_user_profile(st.session_state["username"], st.session_state["user_data"])
    def push_global(): save_global_config(st.session_state["global_data"])
    GLOBAL = st.session_state["global_data"]
    USER = st.session_state["user_data"]
    ACTIVE_KEY, SHARED_FEEDS, _ = get_global_config_data()

    tape_content = get_tape_data(GLOBAL.get("tape_input", "^DJI, ^IXIC, ^GSPTSE, GC=F"), GLOBAL.get("tape_nicknames", ""))
    components.html(f"""<!DOCTYPE html><html><head><style>body{{margin:0;padding:0;background:transparent;overflow:hidden;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}}.ticker-container{{width:100%;height:45px;background:#111;display:flex;align-items:center;border-bottom:1px solid #333;border-radius:0 0 15px 15px;box-shadow:0 4px 10px rgba(0,0,0,0.3)}}.ticker-wrap{{width:100%;overflow:hidden;white-space:nowrap}}.ticker-move{{display:inline-block;animation:ticker 15s linear infinite}}@keyframes ticker{{0%{{transform:translate3d(0,0,0)}}100%{{transform:translate3d(-25%,0,0)}}}}.ticker-item{{display:inline-block;color:white;font-weight:900;font-size:16px;padding:0 20px}}</style></head><body><div class="ticker-container"><div class="ticker-wrap"><div class="ticker-move"><span class="ticker-item">{tape_content}&nbsp;|&nbsp;{tape_content}&nbsp;|&nbsp;{tape_content}&nbsp;|&nbsp;{tape_content}</span></div></div></div></body></html>""", height=50)

    with st.sidebar:
        st.markdown(f"<div style='background:#f0f2f6; padding:10px; border-radius:5px; margin-bottom:10px; text-align:center;'>👤 <b>{st.session_state['username']}</b></div>", unsafe_allow_html=True)
        
        # --- NEW SCANNER ---
        with st.expander("⚡ AI Daily Picks", expanded=True):
            if st.button("🔎 Scan Market"):
                with st.spinner("Hunting for setups..."):
                    picks = run_gap_scanner(ACTIVE_KEY)
                    if not picks: st.warning("No matches today.")
                    else:
                        for p in picks:
                            ticker = p.get('ticker', p) if isinstance(p, dict) else p
                            st.markdown(f"**{ticker}**")
                            st.divider()

        st.subheader("Your Watchlist")
        new_w = st.text_area("Edit Tickers", value=USER.get("w_input", ""), height=100)
        if new_w != USER.get("w_input"):
            USER["w_input"] = new_w; push_user(); st.info("Updated!"); time.sleep(1); st.rerun()

        st.divider()
        with st.expander("🔔 Alert Settings"):
            curr_tg = USER.get("telegram_id", "")
            new_tg = st.text_input("Telegram Chat ID", value=curr_tg)
            if new_tg != curr_tg: USER["telegram_id"] = new_tg.strip(); push_user(); st.success("Saved!"); time.sleep(1); st.rerun()
            st.markdown("[Get my ID](https://t.me/userinfobot)", unsafe_allow_html=True)
            c1, c2 = st.columns(2)
            a_price = c1.checkbox("Price", value=USER.get("alert_price", True))
            a_trend = c2.checkbox("Trend", value=USER.get("alert_trend", True))
            a_pre = st.checkbox("Premarket", value=USER.get("alert_pre", True))
            if (a_price != USER.get("alert_price", True) or a_trend != USER.get("alert_trend", True) or a_pre != USER.get("alert_pre", True)):
                USER["alert_price"] = a_price; USER["alert_trend"] = a_trend; USER["alert_pre"] = a_pre; push_user(); st.rerun()

        with st.expander("🔐 Admin"):
            if st.text_input("Password", type="password") == ADMIN_PASSWORD:
                if "portfolio" in USER and USER["portfolio"] and not GLOBAL.get("portfolio"):
                     if st.button("Import Old Picks"): GLOBAL["portfolio"] = USER["portfolio"]; push_global(); st.rerun()
                new_t = st.text_input("Ticker").upper()
                c1, c2 = st.columns(2); new_p = c1.number_input("Cost"); new_q = c2.number_input("Qty", step=1)
                if st.button("Add Pick") and new_t:
                    if "portfolio" not in GLOBAL: GLOBAL["portfolio"] = {}
                    GLOBAL["portfolio"][new_t] = {"e": new_p, "q": int(new_q)}; push_global(); st.rerun()
                rem = st.selectbox("Remove Pick", [""] + list(GLOBAL.get("portfolio", {}).keys()))
                if st.button("Delete") and rem: del GLOBAL["portfolio"][rem]; push_global(); st.rerun()
                new_key = st.text_input("OpenAI Key", value=GLOBAL.get("openai_key", ""), type="password")
                if new_key != GLOBAL.get("openai_key", ""): GLOBAL["openai_key"] = new_key; push_global(); st.rerun()
                
                # --- NEW FORCE TEST BUTTON ---
                st.divider()
                st.markdown("### 🛠️ Testing")
                if st.button("🔴 Force Morning Briefing (Test)"):
                    with st.spinner("Generating Picks & Resetting DB..."):
                        test_picks = run_gap_scanner(ACTIVE_KEY)
                        try:
                            conn = get_connection(); cursor = conn.cursor()
                            today_str = datetime.now().strftime('%Y-%m-%d')
                            cursor.execute("DELETE FROM daily_briefing WHERE date = %s", (today_str,))
                            cursor.execute("INSERT INTO daily_briefing (date, picks, sent) VALUES (%s, %s, 0)", (today_str, json.dumps(test_picks)))
                            conn.commit(); conn.close()
                            st.success(f"Generated! Picks: {[p.get('ticker', p) if isinstance(p,dict) else p for p in test_picks]}")
                            st.info("👉 Now run your 'up.php' script to send the Telegram.")
                        except Exception as e:
                            st.error(f"Error: {e}")

        if st.button("Logout"): logout_session(st.query_params.get("token")); st.query_params.clear(); st.session_state["logged_in"] = False; st.rerun()
    
    @st.fragment(run_every=60)
    def render_dashboard():
        t1, t2, t3, t4 = st.tabs(["📊 Live Market", "🚀 My Picks", "📰 My News", "🌎 Discovery"])
        w_tickers = [x.strip().upper() for x in USER.get("w_input", "").split(",") if x.strip()]
        port = GLOBAL.get("portfolio", {}); p_tickers = list(port.keys())
        batch_data = get_batch_data(list(set(w_tickers + p_tickers)))

        def draw_card(t, port_item=None):
            d = batch_data.get(t)
            if not d: st.markdown(f"<div style='padding:15px; border:1px dashed #ccc; border-radius:10px; color:#888; font-size:12px;'>⚠️ <b>{t}</b>: Processing...</div>", unsafe_allow_html=True); return
            f = get_fundamentals(t)
            b_col, arrow = ("#4caf50", "▲") if d["d"] >= 0 else ("#ff4b4b", "▼")
            r_up = f["rating"].upper()
            r_col = "#4caf50" if "BUY" in r_up or "OUT" in r_up else "#ff4b4b" if "SELL" in r_up or "UNDER" in r_up else "#f1c40f"
            ai_col = "#4caf50" if d["ai"] == "BULLISH" else "#ff4b4b"; tr_col = "#4caf50" if d["trend"] == "UPTREND" else "#ff4b4b"
            pills = f'<span class="info-pill" style="border-left: 3px solid {ai_col}">AI: {d["ai"]}</span><span class="info-pill" style="border-left: 3px solid {tr_col}">{d["trend"]}</span>'
            if f["rating"] != "N/A": pills += f'<span class="info-pill" style="border-left: 3px solid {r_col}">RATING: {f["rating"]}</span>'
            if f["earn"] != "N/A": pills += f'<span class="info-pill" style="border-left: 3px solid #333">EARN: {f["earn"]}</span>'
            with st.container():
                st.markdown(f"<div style='height:4px; width:100%; background-color:{b_col}; border-radius: 4px 4px 0 0;'></div><div style='display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:5px;'><div><div style='font-size:22px; font-weight:bold; margin-right:8px; color:#2c3e50;'>{t}</div><div style='font-size:12px; color:#888; margin-top:-2px;'>{d['name'][:25]}...</div></div><div style='text-align:right;'><div style='font-size:22px; font-weight:bold; color:#2c3e50;'>${d['p']:,.2f}</div><div style='font-size:13px; font-weight:bold; color:{b_col}; margin-top:-4px;'>{arrow} {d['d']:.2f}%</div>{d['pp']}</div></div><div style='margin-bottom:10px; display:flex; flex-wrap:wrap; gap:4px;'>{pills}</div>", unsafe_allow_html=True)
                st.altair_chart(alt.Chart(d["chart"]).mark_area(line={"color": b_col}, color=alt.Gradient(gradient="linear", stops=[alt.GradientStop(color=b_col, offset=0), alt.GradientStop(color="white", offset=1)], x1=1, x2=1, y1=1, y2=0)).encode(x=alt.X("Idx", axis=None), y=alt.Y("Stock", axis=None), tooltip=[]).configure_view(strokeWidth=0).properties(height=45), use_container_width=True)
                rsi_bg = "#ff4b4b" if d["rsi"] > 70 else "#4caf50" if d["rsi"] < 30 else "#999"
                st.markdown(f"<div class='metric-label'><span>Day Range</span><span style='color:#555'>${d['l']:,.2f} - ${d['h']:,.2f}</span></div><div class='bar-bg'><div class='bar-fill' style='width:{d['range_pos']}%; background: linear-gradient(90deg, #ff4b4b, #f1c40f, #4caf50);'></div></div><div class='metric-label'><span>RSI ({int(d['rsi'])})</span><span class='tag' style='background:{rsi_bg}'>{'HOT' if d['rsi']>70 else 'COLD' if d['rsi']<30 else 'NEUTRAL'}</span></div><div class='bar-bg'><div class='bar-fill' style='width:{d['rsi']}%; background:{rsi_bg};'></div></div>", unsafe_allow_html=True)
                
                # --- SURGICAL ADD: VOLUME BAR VISUAL ---
                st.markdown(f"""
                    <div class='metric-label'><span>Volume Status</span><span class='tag' style='background:#00d4ff'>{d['vol_label']}</span></div>
                    <div class='bar-bg'>
                        <div class='bar-fill' style='width:{d['vol_pct']}%; background:#00d4ff;'></div>
                    </div>
                """, unsafe_allow_html=True)

                if port_item:
                    gain = (d["p"] - port_item["e"]) * port_item["q"]
                    st.markdown(f"<div style='background:#f9f9f9; padding:5px; margin-top:10px; border-radius:5px; display:flex; justify-content:space-between; font-size:12px;'><span>Qty: <b>{port_item['q']}</b></span><span>Avg: <b>${port_item['e']}</b></span><span style='color:{'#4caf50' if gain>=0 else '#ff4b4b'}; font-weight:bold;'>${gain:+,.0f}</span></div>", unsafe_allow_html=True)
                st.divider()

        with t1:
            # MORNING BANNER
            try:
                conn = get_connection(); cursor = conn.cursor(dictionary=True)
                today = datetime.now().strftime('%Y-%m-%d')
                cursor.execute("SELECT picks FROM daily_briefing WHERE date = %s", (today,))
                row = cursor.fetchone(); conn.close()
                if row:
                    picks_list = json.loads(row['picks'])
                    display_tickers = [p.get('ticker', p) if isinstance(p, dict) else p for p in picks_list]
                    st.success(f"📌 **Daily Picks:** {', '.join(display_tickers)}")
            except: pass
            
            cols = st.columns(3)
            for i, t in enumerate(w_tickers):
                with cols[i % 3]: draw_card(t)

        with t2:
            if not port: st.info("No Picks Published.")
            else:
                total_val, total_cost, day_pl_sum = 0.0, 0.0, 0.0
                for k, v in port.items():
                    d = batch_data.get(k)
                    if d:
                        total_val += d["p"] * v["q"]; total_cost += v["e"] * v["q"]
                        if d["d"] != 0: day_pl_sum += (d["p"] - (d["p"] / (1 + (d["d"] / 100)))) * v["q"]
                day_col = "#4caf50" if day_pl_sum >= 0 else "#ff4b4b"
                tot_col = "#4caf50" if (total_val - total_cost) >= 0 else "#ff4b4b"
                day_pct = (day_pl_sum / (total_val - day_pl_sum) * 100) if (total_val - day_pl_sum) > 0 else 0
                tot_pct = ((total_val - total_cost) / total_cost * 100) if total_cost > 0 else 0
                st.markdown(f"<div style='background-color:white; border-radius:12px; padding:15px; box-shadow:0 4px 10px rgba(0,0,0,0.05); border:1px solid #f0f0f0; margin-bottom:20px;'><div style='display:flex; justify-content:space-between; margin-bottom:10px;'><div><div style='font-size:11px; color:#888; font-weight:bold;'>NET ASSETS</div><div style='font-size:24px; font-weight:900; color:#333;'>${total_val:,.2f}</div></div><div style='text-align:right;'><div style='font-size:11px; color:#888; font-weight:bold;'>INVESTED</div><div style='font-size:24px; font-weight:900; color:#555;'>${total_cost:,.2f}</div></div></div><div style='height:1px; background:#eee; margin:10px 0;'></div><div style='display:flex; justify-content:space-between;'><div><div style='font-size:11px; color:#888; font-weight:bold;'>DAY P/L</div><div style='font-size:16px; font-weight:bold; color:{day_col};'>${day_pl_sum:+,.2f} ({day_pct:+.2f}%)</div></div><div style='text-align:right;'><div style='font-size:11px; color:#888; font-weight:bold;'>TOTAL P/L</div><div style='font-size:16px; font-weight:bold; color:{tot_col};'>${total_val - total_cost:+,.2f} ({tot_pct:+.2f}%)</div></div></div></div>", unsafe_allow_html=True)
                cols = st.columns(3)
                for i, (k, v) in enumerate(port.items()):
                    with cols[i % 3]: draw_card(k, v)

        def render_news(n):
            # SURGICAL CSS UPDATE: Fuzzy matching for Green/Red
            s_val = n["sentiment"].upper()
            if "BULL" in s_val or "POS" in s_val: col = "#4caf50"
            elif "BEAR" in s_val or "NEG" in s_val: col = "#ff4b4b"
            else: col = "#333"
            
            disp = n["ticker"] if n["ticker"] else "MARKET"
            st.markdown(f"<div class='news-card' style='border-left-color: {col};'><div style='display:flex; align-items:center;'><span class='ticker-badge' style='background-color:{col}'>{disp}</span><a href='{n['link']}' target='_blank' class='news-title'>{n['title']}</a></div><div class='news-meta'>{n['published']} | Sentiment: <b>{n['sentiment']}</b></div></div>", unsafe_allow_html=True)

        with t3:
            c_head, c_btn = st.columns([4, 1]); c_head.subheader("Portfolio News")
            if c_btn.button("🔄 Refresh", key=f"btn_n1_{int(time.time()/60)}"):
                with st.spinner("Analyzing..."): fetch_news.clear(); fetch_news([], list(set(w_tickers + p_tickers)), ACTIVE_KEY); st.rerun()
            if not NEWS_LIB_READY: st.error("Missing Libraries.")
            else:
                news_items = fetch_news([], list(set(w_tickers + p_tickers)), ACTIVE_KEY)
                if not news_items: st.info("No news.")
                else:
                    for n in news_items: render_news(n)
        
        with t4:
            c_head, c_btn = st.columns([4, 1]); c_head.subheader("Market Discovery")
            if c_btn.button("🔄 Refresh", key=f"btn_n2_{int(time.time()/60)}"):
                with st.spinner("Analyzing..."): fetch_news.clear(); fetch_news(GLOBAL.get("rss_feeds", ["https://finance.yahoo.com/news/rssindex"]), [], ACTIVE_KEY); st.rerun()
            if not NEWS_LIB_READY: st.error("Missing Libraries.")
            else:
                news_items = fetch_news(GLOBAL.get("rss_feeds", ["https://finance.yahoo.com/news/rssindex"]), [], ACTIVE_KEY)
                if not news_items: st.info("No news.")
                else:
                    for n in news_items: render_news(n)

    render_dashboard()
