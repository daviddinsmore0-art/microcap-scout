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
    "password": "1q2w3e4R!!",   # <--- PASTE PASSWORD HERE
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
        # Auto-patch missing columns
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

# --- SCANNER ENGINE (THE CYBORG) ---
@st.cache_data(ttl=3600)
def run_gap_scanner(user_tickers, api_key):
    high_vol_tickers = ['NVDA', 'GOOGL', 'AAPL', 'MSFT', 'AMZN', 'META', 'AVGO', 'TSLA', 'JPM', 'V', 'JNJ', 'ORCL', 'MU', 'COST', 'HD', 'BAC', 'NFLX', 'PG', 'CVX', 'UNH', 'KO', 'GE', 'CSCO', 'CAT', 'GS', 'TM', 'HSBC', 'AZN', 'MS', 'NVS', 'NVO', 'LRCX', 'IBM', 'SAP', 'PM', 'WFC', 'MRK', 'RTX', 'AMAT', 'AXP', 'RY', 'TMO', 'INTC', 'MCD', 'CRM', 'LIN', 'TMUS', 'SHEL', 'PEP', 'KLAC', 'C', 'DIS', 'BA', 'ABT', 'ISRG', 'AMGN', 'SCHW', 'SYK', 'TXN', 'BLK', 'CRDO', 'BE', 'IONQ', 'KTOS', 'HL', 'CDE', 'FN', 'NXT', 'AVAV', 'BBIO', 'GH', 'SMCI', 'APG', 'CRUS', 'ONC', 'WTS', 'AEIS', 'AXSM', 'PGEN', 'BMY', 'SNDX', 'RDW', 'LAC', 'WOLF', 'AXTI', 'BW', 'MGNI', 'AMPL', 'CWCO', 'SG', 'SHAK', 'SQSP', 'PRCH', 'IRTC', 'UPWK', 'SKYW', 'RIVN', 'GOSS', 'ADTX', 'MULN']
    scan_list = list(set(high_vol_tickers + user_tickers))
    candidates = []
    try:
        data = yf.download(" ".join(scan_list), period="1mo", interval="1d", group_by='ticker', threads=True, progress=False)
        for t in scan_list:
            try:
                if t in data.columns.levels[0]: df = data[t]
                else: continue
                if len(df) < 14: continue 
                curr_close = float(df['Close'].iloc[-1])
                prev_close = float(df['Close'].iloc[-2])
                open_price = float(df['Open'].iloc[-1])
                gap_pct = ((open_price - prev_close) / prev_close) * 100
                if df['Volume'].mean() < 500000: continue
                high_low = df['High'] - df['Low']
                high_close = (df['High'] - df['Close'].shift()).abs()
                low_close = (df['Low'] - df['Close'].shift()).abs()
                ranges = pd.concat([high_low, high_close, low_close], axis=1)
                true_range = ranges.max(axis=1)
                atr = true_range.rolling(14).mean().iloc[-1]
                if atr < 0.50: continue
                if abs(gap_pct) >= 1.0:
                    candidates.append({"ticker": t, "gap": gap_pct, "atr": atr, "price": curr_close})
            except: pass
    except: return []

    candidates.sort(key=lambda x: abs(x['gap']), reverse=True)
    top_5 = candidates[:5]
    if api_key and NEWS_LIB_READY and top_5:
        try:
            client = openai.OpenAI(api_key=api_key)
            prompt = f"Analyze these stocks for a day trade. Pick the Top 3 based on momentum catalysts. Ignore buyout rumors. Return JSON: {{'picks': ['TICKER', 'TICKER']}}.\nData: {str(top_5)}"
            response = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"})
            picks_json = json.loads(response.choices[0].message.content)
            picked_tickers = picks_json.get("picks", [])
            final_picks = [c for c in top_5 if c['ticker'] in picked_tickers]
            if not final_picks: final_picks = top_5[:3]
        except: pass
    return final_picks if 'final_picks' in locals() else top_5[:3]

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
            sql = "INSERT INTO user_profiles (username, user_data) VALUES ('GLOBAL_CONFIG', %s) ON DUPLICATE KEY UPDATE user_data = %s"
            cursor.execute(sql, (j_str, j_str))
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
    articles = []; seen = set()
    for url in all_feeds:
        try:
            f = feedparser.parse(url)
            for entry in f.entries[:5]:
                if entry.link not in seen:
                    seen.add(entry.link)
                    found_ticker, sentiment = "", "NEUTRAL"
                    if api_key:
                        try:
                            client = openai.OpenAI(api_key=api_key)
                            prompt = f"Analyze news: '{entry.title}'. Return: TICKER|SENTIMENT (BULLISH/BEARISH/NEUTRAL)."
                            response = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}], max_tokens=15)
                            ans = response.choices[0].message.content.strip().upper()
                            if "|" in ans:
                                parts = ans.split("|")
                                found_ticker = parts[0].strip()
                                raw_sent = parts[1].strip()
                                # Internal fix for CSS key matching
                                if "BULL" in raw_sent: sentiment = "BULLISH"
                                elif "BEAR" in raw_sent: sentiment = "BEARISH"
                                else: sentiment = "NEUTRAL"
                        except: pass
                    articles.append({"title": entry.title, "link": entry.link, "published": relative_time(entry.get("published", "")), "ticker": found_ticker, "sentiment": sentiment})
        except: pass
    return articles

# --- DATA ENGINE ---
@st.cache_data(ttl=600)
def get_fundamentals(s):
    try:
        conn = get_connection(); cursor = conn.
