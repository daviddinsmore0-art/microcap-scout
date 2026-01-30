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
        conn = get_connection(); cursor = conn.cursor()
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
        conn.close()
        return True
    except: return False

# --- BACKEND UPDATE ENGINE ---
def run_backend_update():
    try:
        conn = get_connection(); cursor = conn.cursor(dictionary=True, buffered=True)
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
        cursor.execute(f"SELECT ticker, last_updated FROM stock_cache WHERE ticker IN ({format_strings})", tuple(all_tickers))
        existing_rows = {row['ticker']: row for row in cursor.fetchall()}
        
        to_fetch = [t for t in all_tickers if t not in existing_rows or (datetime.now() - existing_rows[t]['last_updated']).total_seconds() > 120]
        
        if to_fetch:
            batch_size = 15
            for i in range(0, len(to_fetch), batch_size):
                batch = to_fetch[i:i + batch_size]
                tickers_str = " ".join(batch)
                try:
                    live_data = yf.download(tickers_str, period="5d", interval="1m", prepost=True, group_by='ticker', threads=True, progress=False)
                    for t in batch:
                        df = live_data[t] if len(batch) > 1 else live_data
                        df = df.dropna(subset=['Close'])
                        if df.empty: continue
                        curr_p = float(df['Close'].iloc[-1])
                        prev_c = float(df['Close'].iloc[-2]) if len(df) > 1 else curr_p
                        day_change = ((curr_p - prev_c) / prev_c) * 100
                        
                        sql = "INSERT INTO stock_cache (ticker, current_price, day_change, last_updated) VALUES (%s, %s, %s, NOW()) ON DUPLICATE KEY UPDATE current_price=%s, day_change=%s, last_updated=NOW()"
                        cursor.execute(sql, (t, curr_p, day_change, curr_p, day_change))
                        conn.commit()
                except: pass
        conn.close()
    except: pass

# --- SCANNER ENGINE ---
@st.cache_data(ttl=900)
def run_gap_scanner(api_key):
    return ["AAPL", "TSLA", "NVDA"]

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
        if pin: cursor.execute("INSERT INTO user_profiles (username, user_data, pin) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE user_data=%s, pin=%s", (username, j_str, pin, j_str, pin))
        else: cursor.execute("UPDATE user_profiles SET user_data=%s WHERE username=%s", (j_str, username))
        conn.commit(); conn.close()
    except: pass

def load_global_config():
    try:
        conn = get_connection(); cursor = conn.cursor()
        cursor.execute("SELECT user_data FROM user_profiles WHERE username = 'GLOBAL_CONFIG'")
        res = cursor.fetchone(); conn.close()
        return json.loads(res[0]) if res else {"tape_input": "^DJI,^IXIC"}
    except: return {}

# --- NEWS ENGINE (WITH SCORE) ---
@st.cache_data(ttl=600)
def fetch_news(feeds, tickers, api_key):
    if not NEWS_LIB_READY: return []
    all_feeds = feeds + [f"https://finance.yahoo.com/rss/headline?s={t}" for t in tickers]
    articles, seen = [], set()
    for url in all_feeds:
        try:
            f = feedparser.parse(url)
            for entry in f.entries[:5]:
                if entry.link not in seen:
                    seen.add(entry.link)
                    score = 5
                    if api_key:
                        try:
                            client = openai.OpenAI(api_key=api_key)
                            prompt = f"Impact of: '{entry.title}'. Return Impact (1-10)."
                            res = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role":"user","content":prompt}], max_tokens=10)
                            score = int(re.search(r'\d+', res.choices[0].message.content).group())
                        except: pass
                    articles.append({"title": entry.title, "link": entry.link, "score": score, "ticker": "MARKET"})
        except: pass
    return articles

# --- DASHBOARD UI ---
def render_dashboard():
    USER = st.session_state["user_data"]
    GLOBAL = st.session_state["global_data"]
    api_key = st.secrets.get("OPENAI_KEY")
    
    t1, t2, t3, t4 = st.tabs(["📊 Live", "🚀 Picks", "📰 News", "🌎 Discovery"])
    w_list = [x.strip().upper() for x in USER.get("w_input", "").split(",") if x.strip()]
    
    # Load batch data for UI
    batch_results = {}
    try:
        conn = get_connection(); cursor = conn.cursor(dictionary=True)
        cursor.execute(f"SELECT * FROM stock_cache WHERE ticker IN ({','.join(['%s']*len(w_list))})", tuple(w_list))
        batch_results = {row['ticker']: row for row in cursor.fetchall()}
        conn.close()
    except: pass

    with t1:
        cols = st.columns(3)
        for i, t in enumerate(w_list):
            row = batch_results.get(t)
            if row:
                with cols[i % 3]:
                    st.metric(t, f"${float(row['current_price']):,.2f}", f"{float(row['day_change']):+.2f}%")

    with t3:
        news = fetch_news([], w_list, api_key)
        for n in news:
            st.markdown(f"**({n['score']}/10)** [{n['title']}]({n['link']})")

# --- APP BOOTSTRAP ---
if "logged_in" not in st.session_state: st.session_state["logged_in"] = False

if not st.session_state["logged_in"]:
    st.title("⚡ Penny Pulse")
    u = st.text_input("Username")
    p = st.text_input("PIN", type="password")
    if st.button("Login"):
        exists, stored = check_user_exists(u)
        if exists and stored == p:
            st.session_state.update({"logged_in": True, "username": u, "user_data": load_user_profile(u), "global_data": load_global_config()})
            st.rerun()
else:
    init_db(); run_backend_update(); render_dashboard()
