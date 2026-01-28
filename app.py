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
        cursor.execute(f"SELECT ticker, last_updated FROM stock_cache WHERE ticker IN ({format_strings})", tuple(all_tickers))
        existing_rows = {row['ticker']: row for row in cursor.fetchall()}
        
        to_fetch_price = []
        now = datetime.now()
        for t in all_tickers:
            row = existing_rows.get(t)
            if not row or not row['last_updated'] or (now - row['last_updated']).total_seconds() > 120:
                to_fetch_price.append(t)
        
        if to_fetch_price:
            tickers_str = " ".join(to_fetch_price)
            live_data = yf.download(tickers_str, period="5d", interval="1m", prepost=True, group_by='ticker', threads=True, progress=False)
            hist_data = yf.download(tickers_str, period="1mo", interval="1d", group_by='ticker', threads=True, progress=False)

            for t in to_fetch_price:
                try:
                    df_live = live_data[t] if len(to_fetch_price) > 1 else live_data
                    df_live = df_live.dropna(subset=['Close'])
                    if df_live.empty: continue
                    live_price = float(df_live['Close'].iloc[-1])

                    df_hist = hist_data[t] if len(to_fetch_price) > 1 else hist_data
                    day_change = 0.0; rsi = 50.0; vol_stat = "NORMAL"; trend = "NEUTRAL"
                    chart_json = "[]"; day_h = live_price; day_l = live_price

                    if not df_hist.empty:
                        df_hist = df_hist.dropna(subset=['Close'])
                        close_price = float(df_hist['Close'].iloc[-1]) 
                        day_h = max(float(df_hist['High'].iloc[-1]), live_price)
                        day_l = min(float(df_hist['Low'].iloc[-1]), live_price)

                        if len(df_hist) > 1:
                            prev_close = float(df_hist['Close'].iloc[-2])
                            day_change = ((live_price - prev_close) / prev_close) * 100
                        
                        trend = "UPTREND" if live_price > df_hist['Close'].tail(20).mean() else "DOWNTREND"
                        v_avg = df_hist['Volume'].tail(20).mean()
                        v_curr = df_hist['Volume'].iloc[-1]
                        if v_curr > v_avg * 1.5: vol_stat = "HEAVY"
                        elif v_curr < v_avg * 0.5: vol_stat = "LIGHT"
                        chart_json = json.dumps(df_hist['Close'].tail(20).tolist())

                    sql = """INSERT INTO stock_cache (ticker, current_price, day_change, rsi, volume_status, trend_status, price_history, day_high, day_low, last_updated) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()) ON DUPLICATE KEY UPDATE current_price=VALUES(current_price), day_change=VALUES(day_change), volume_status=VALUES(volume_status), trend_status=VALUES(trend_status), last_updated=NOW()"""
                    cursor.execute(sql, (t, live_price, day_change, rsi, vol_stat, trend, chart_json, day_h, day_l))
                    conn.commit()
                except: pass
        conn.close()
    except: pass

# --- SCANNER ENGINE ---
@st.cache_data(ttl=900)
def run_gap_scanner(api_key):
    candidates = []
    discovery_tickers = set()
    try:
        feeds = ["https://finance.yahoo.com/rss/most-active", "https://finance.yahoo.com/news/rssindex"]
        for url in feeds:
            f = feedparser.parse(requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5).content)
            for entry in f.entries[:25]:
                match = re.search(r'\b[A-Z]{2,5}\b', entry.title)
                if match: discovery_tickers.add(match.group(0))
    except: pass
    
    scan_list = list(discovery_tickers)
    if not scan_list: return []
    
    try:
        data = yf.download(" ".join(scan_list), period="30d", interval="1d", group_by='ticker', threads=True, progress=False)
        for t in scan_list:
            try:
                df = data[t] if len(scan_list) > 1 else data
                if df.empty or len(df) < 10: continue
                avg_vol = df['Volume'].tail(20).mean()
                curr_vol = df['Volume'].iloc[-1]
                rvol = round(curr_vol / avg_vol, 2) if avg_vol > 0 else 1.0
                gap = ((df['Close'].iloc[-1] - df['Close'].iloc[-2]) / df['Close'].iloc[-2]) * 100
                if abs(gap) >= 0.5 and curr_vol > 50000:
                    sector = yf.Ticker(t).info.get('sector', 'Unknown')
                    candidates.append({"ticker": t, "gap": gap, "rvol": rvol, "sector": sector})
            except: continue
    except: return []

    if api_key and candidates:
        candidates.sort(key=lambda x: abs(x['gap']), reverse=True)
        top_10 = candidates[:10]
        client = openai.OpenAI(api_key=api_key)
        prompt = f"Pick Top 3 day trade setups (prioritize RVOL and Sector diversity): {str(top_10)}"
        resp = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"})
        return json.loads(resp.choices[0].message.content).get("picks", [])
    return [c['ticker'] for c in sorted(candidates, key=lambda x: abs(x['gap']), reverse=True)[:3]]

# --- AUTH HELPERS ---
def check_user_exists(username):
    conn = get_connection(); cursor = conn.cursor()
    cursor.execute("SELECT pin FROM user_profiles WHERE username = %s", (username,))
    res = cursor.fetchone(); conn.close()
    return (True, res[0]) if res else (False, None)

def create_session(username):
    token = str(uuid.uuid4())
    conn = get_connection(); cursor = conn.cursor()
    cursor.execute("INSERT INTO user_sessions (token, username) VALUES (%s, %s)", (token, username))
    conn.commit(); conn.close()
    return token

def validate_session(token):
    conn = get_connection(); cursor = conn.cursor()
    cursor.execute("SELECT username FROM user_sessions WHERE token = %s", (token,))
    res = cursor.fetchone(); conn.close()
    return res[0] if res else None

def load_user_profile(username):
    conn = get_connection(); cursor = conn.cursor()
    cursor.execute("SELECT user_data FROM user_profiles WHERE username = %s", (username,))
    res = cursor.fetchone(); conn.close()
    return json.loads(res[0]) if res else {"w_input": "TD.TO, SPY"}

def save_user_profile(username, data, pin=None):
    conn = get_connection(); cursor = conn.cursor()
    j_str = json.dumps(data)
    if pin: cursor.execute("INSERT INTO user_profiles (username, user_data, pin) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE user_data=%s, pin=%s", (username, j_str, pin, j_str, pin))
    else: cursor.execute("UPDATE user_profiles SET user_data=%s WHERE username=%s", (j_str, username))
    conn.commit(); conn.close()

# --- UI START ---
init_db()
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
    token = st.query_params.get("token")
    if token:
        u = validate_session(token)
        if u: 
            st.session_state["username"] = u
            st.session_state["logged_in"] = True

# --- LOGIN VIEW ---
if not st.session_state["logged_in"]:
    st.title("⚡ Penny Pulse Login")
    with st.form("login"):
        u = st.text_input("Username")
        p = st.text_input("PIN", type="password")
        if st.form_submit_button("Login"):
            exists, stored_pin = check_user_exists(u)
            if exists and stored_pin == p:
                st.session_state["logged_in"] = True
                st.session_state["username"] = u
                st.query_params["token"] = create_session(u)
                st.rerun()
            elif not exists:
                save_user_profile(u, {"w_input": "TD.TO, SPY"}, p)
                st.session_state["logged_in"] = True
                st.session_state["username"] = u
                st.query_params["token"] = create_session(u)
                st.rerun()

# --- MAIN APP VIEW ---
else:
    USER = load_user_profile(st.session_state["username"])
    
    with st.sidebar:
        st.header(f"👤 {st.session_state['username']}")
        if st.button("🔎 Scan Market"):
            with st.spinner("Analyzing..."):
                picks = run_gap_scanner(st.secrets.get("OPENAI_KEY"))
                conn = get_connection(); cursor = conn.cursor()
                today = datetime.now().strftime('%Y-%m-%d')
                cursor.execute("DELETE FROM daily_briefing WHERE date = %s", (today,))
                cursor.execute("INSERT INTO daily_briefing (date, picks, sent) VALUES (%s, %s, 0)", (today, json.dumps(picks)))
                conn.commit(); conn.close()
                st.success("Status reset to 0. Ready for dispatch.")

        if st.button("🚀 Dispatch Telegram"):
            requests.get("https://atlanticcanadaschoice.com/pennypulse/up.php")
            st.success("Signal Sent.")

    # --- DASHBOARD TABS ---
    t1, t2 = st.tabs(["📊 Market", "💼 Portfolio"])
    
    with t1:
        try:
            conn = get_connection(); cursor = conn.cursor(dictionary=True)
            today = datetime.now().strftime('%Y-%m-%d')
            cursor.execute("SELECT picks, created_at FROM daily_briefing WHERE date = %s", (today,))
            row = cursor.fetchone(); conn.close()
            if row:
                picks = json.loads(row['picks'])
                ts = row['created_at']
                total_min = (ts.hour * 60) + ts.minute
                label = "PRE-MARKET PICKS" if total_min < 600 else "DAILY PICKS" if total_min < 960 else "POST-MARKET PICKS"
                st.success(f"📌 **{label}:** {', '.join(picks)} | _Updated: {ts.strftime('%I:%M %p')}_")
        except: pass

        # Simple Ticker View
        tickers = [x.strip() for x in USER['w_input'].split(",")]
        cols = st.columns(3)
        for i, t in enumerate(tickers):
            with cols[i % 3]: st.write(f"**{t}** Live Data Placeholder")

    if st.button("Logout"):
        st.session_state["logged_in"] = False
        st.query_params.clear()
        st.rerun()
