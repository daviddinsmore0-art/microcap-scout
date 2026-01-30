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
                batch = to_fetch[i:i + batch_size]; tickers_str = " ".join(batch)
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

# --- AUTH LOGIC ---
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
        return json.loads(res[0]) if res else {"w_input": "Td.to, bn.to, ivn.to"}
    except: return {"w_input": "Td.to, bn.to, ivn.to"}

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
        return json.loads(res[0]) if res else {"tape_input": "^DJI,^IXIC,GC=F"}
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
                    score, sentiment, found_t = 5, "NEUTRAL", ""
                    if api_key:
                        try:
                            client = openai.OpenAI(api_key=api_key)
                            prompt = f"Impact of: '{entry.title}'. Return TICKER|SENTIMENT|SCORE(1-10)."
                            res = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role":"user","content":prompt}], max_tokens=25)
                            parts = res.choices[0].message.content.split("|")
                            found_t, sentiment = parts[0].strip().upper(), parts[1].strip().upper()
                            score = int(re.search(r'\d+', parts[2]).group())
                        except: pass
                    articles.append({"title": entry.title, "link": entry.link, "score": score, "ticker": found_t, "sentiment": sentiment})
        except: pass
    return articles

# --- SCROLLER DATA ENGINE ---
def get_tape_data(symbol_string):
    items, symbols = [], [x.split(":")[0].strip().upper() for x in symbol_string.split(",") if x.strip()]
    try:
        conn = get_connection(); cursor = conn.cursor(dictionary=True)
        cursor.execute(f"SELECT ticker, current_price, day_change FROM stock_cache WHERE ticker IN ({','.join(['%s']*len(symbols))})", tuple(symbols))
        data_map = {row['ticker']: row for row in cursor.fetchall()}; conn.close()
        for s in symbols:
            if s in data_map:
                row = data_map[s]; col = "#4caf50" if float(row['day_change']) >= 0 else "#ff4b4b"
                arrow = "▲" if float(row['day_change']) >= 0 else "▼"
                items.append(f"<span style='color:#ccc; margin-left:20px;'>{s}</span> <span style='color:{col}'>{arrow} {float(row['current_price']):,.2f} ({float(row['day_change']):+.2f}%)</span>")
    except: pass
    return "    ".join(items)

# --- DASHBOARD UI ---
def render_dashboard():
    st.markdown("<style>.news-card { padding: 10px; margin-bottom: 10px; border-radius: 8px; background: white; box-shadow: 0 2px 5px rgba(0,0,0,0.05); } .hot-badge { background: linear-gradient(90deg, #ff4b4b, #ff9100); color: white; padding: 2px 8px; border-radius: 10px; font-weight: bold; font-size: 10px; animation: pulse 2s infinite; } @keyframes pulse { 0%{opacity:0.8} 50%{opacity:1} 100%{opacity:0.8} }</style>", unsafe_allow_html=True)
    USER, GLOBAL = st.session_state["user_data"], st.session_state["global_data"]
    api_key = GLOBAL.get("openai_key") or st.secrets.get("OPENAI_KEY")
    
    t1, t2, t3, t4 = st.tabs(["📊 Live Market", "🚀 My Picks", "📰 My News", "🌎 Discovery"])
    w_list = [x.strip().upper() for x in USER.get("w_input", "").split(",") if x.strip()]
    
    # Batch data fetch
    batch_results = {}
    if w_list:
        try:
            conn = get_connection(); cursor = conn.cursor(dictionary=True)
            cursor.execute(f"SELECT * FROM stock_cache WHERE ticker IN ({','.join(['%s']*len(w_list))})", tuple(w_list))
            batch_results = {row['ticker']: row for row in cursor.fetchall()}; conn.close()
        except: pass

    news_data = fetch_news([], w_list, api_key)

    with t1:
        cols = st.columns(3)
        for i, t in enumerate(w_list):
            row = batch_results.get(t)
            if row:
                high_sent = [n for n in news_data if n['ticker'] == t and n['score'] >= 8]
                hot = "<span class='hot-badge'>🔥 HOT</span>" if len(high_sent) >= 2 else ""
                with cols[i % 3]:
                    with st.container(border=True):
                        st.markdown(f"#### {t} {hot}", unsafe_allow_html=True)
                        st.markdown(f"## ${float(row['current_price']):,.2f}")
                        col = "green" if float(row['day_change']) >= 0 else "red"
                        st.markdown(f"<span style='color:{col}'>{float(row['day_change']):+.2f}%</span>", unsafe_allow_html=True)

    with t3:
        for n in news_data:
            c = "#4caf50" if n['score'] >= 8 else "#f1c40f" if n['score'] >= 5 else "#ff4b4b"
            st.markdown(f"<div class='news-card' style='border-left:5px solid {c};'><div style='display:flex; justify-content:space-between;'><a href='{n['link']}' target='_blank' style='font-weight:bold; color:#333; text-decoration:none;'>{n['title']}</a><span style='background:{c}; color:white; padding:2px 8px; border-radius:12px; font-size:12px;'>{n['score']}/10</span></div><small>{n['ticker']} | {n['sentiment']}</small></div>", unsafe_allow_html=True)

# --- LOGIN & SIDEBAR ---
if "logged_in" not in st.session_state: st.session_state["logged_in"] = False

if not st.session_state["logged_in"]:
    st.title("⚡ Penny Pulse")
    with st.form("login"):
        u, p = st.text_input("Username"), st.text_input("PIN", type="password")
        if st.form_submit_button("Login"):
            exists, stored = check_user_exists(u.strip())
            if exists and stored == p:
                st.session_state.update({"logged_in": True, "username": u.strip(), "user_data": load_user_profile(u.strip()), "global_data": load_global_config()})
                st.rerun()
            elif not exists:
                save_user_profile(u.strip(), {"w_input": "Td.to, SPY"}, p)
                st.session_state.update({"logged_in": True, "username": u.strip(), "user_data": load_user_profile(u.strip()), "global_data": load_global_config()})
                st.rerun()
else:
    def push_user(): save_user_profile(st.session_state["username"], st.session_state["user_data"])
    tape = get_tape_data(st.session_state["global_data"].get("tape_input", "^DJI,^IXIC,GC=F"))
    components.html(f"<div style='background:#111; height:45px; display:flex; align-items:center; color:white; overflow:hidden; border-radius:0 0 15px 15px;'><marquee scrollamount='5' style='font-weight:900;'>{tape}</marquee></div>", height=50)
    
    with st.sidebar:
        st.markdown(f"👤 **{st.session_state['username']}**")
        new_w = st.text_area("Watchlist", st.session_state["user_data"].get("w_input", ""), height=100)
        if new_w != st.session_state["user_data"].get("w_input"): 
            st.session_state["user_data"]["w_input"] = new_w; push_user(); st.rerun()
        
        with st.expander("🔔 Alert Settings"):
            curr_id = st.session_state["user_data"].get("tg_id", "")
            new_id = st.text_input("Telegram ID", value=curr_id)
            if new_id != curr_id: st.session_state["user_data"]["tg_id"] = new_id; push_user(); st.rerun()
            st.checkbox("AI Daily Picks", value=st.session_state["user_data"].get("alert_ai", True))
        
        if st.button("Logout"): st.session_state["logged_in"] = False; st.rerun()
            
    init_db(); run_backend_update(); render_dashboard()
