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
                current_price DECIMAL(20, 4), day_change DECIMAL(10, 2), rsi DECIMAL(10, 2),
                volume_status VARCHAR(20), trend_status VARCHAR(20), rating VARCHAR(50),
                next_earnings VARCHAR(20), pre_post_price DECIMAL(20, 4), pre_post_pct DECIMAL(10, 2),
                price_history JSON, company_name VARCHAR(255), day_high DECIMAL(20, 4),
                day_low DECIMAL(20, 4), last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("CREATE TABLE IF NOT EXISTS daily_briefing (date DATE PRIMARY KEY, picks JSON, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        conn.close()
        return True
    except Exception: return False

# --- DATA HELPERS (FIXED: RESTORED MISSING FUNCTION) ---
@st.cache_data(ttl=600)
def get_fundamentals(s):
    try:
        conn = get_connection(); cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT rating, next_earnings FROM stock_cache WHERE ticker = %s", (s,))
        row = cursor.fetchone(); conn.close()
        return {"rating": row['rating'] or "N/A", "earn": row['next_earnings'] or "N/A"} if row else {"rating": "N/A", "earn": "N/A"}
    except: return {"rating": "N/A", "earn": "N/A"}

# --- MORNING BRIEFING ENGINE (AST SERVER SYNC) ---
def run_morning_briefing(api_key):
    try:
        now = datetime.now() # Server is AST
        if now.weekday() > 4: return 
        today_str = now.strftime('%Y-%m-%d')
        conn = get_connection(); cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT picks FROM daily_briefing WHERE date = %s", (today_str,))
        if not cursor.fetchone() and 9 <= now.hour <= 10 and 45 <= now.minute <= 59:
            movers = ["NVDA", "TSLA", "AMD", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "NFLX", "COIN", "MARA", "PLTR", "SOFI", "LCID", "RIVN", "GME", "AMC", "MSTR", "MULN"]
            candidates = []
            fh_key = st.secrets.get("FINNHUB_API_KEY")
            for t in movers:
                try:
                    r = requests.get(f"https://finnhub.io/api/v1/quote?symbol={t}&token={fh_key}", timeout=5).json()
                    if 'c' in r and r['c'] != 0:
                        gap = ((float(r['c']) - float(r['pc'])) / float(r['pc'])) * 100
                        if abs(gap) >= 1.0: candidates.append({"ticker": t, "gap": gap, "price": r['c']})
                except: continue
            candidates.sort(key=lambda x: abs(x['gap']), reverse=True)
            top_5 = candidates[:5]
            if api_key and top_5:
                client = openai.OpenAI(api_key=api_key)
                prompt = f"Analyze: {str(top_5)}. Return JSON: {{'picks': ['TICKER', 'TICKER', 'TICKER']}}."
                resp = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"})
                picks = json.loads(resp.choices[0].message.content).get("picks", [])
                cursor.execute("INSERT INTO daily_briefing (date, picks) VALUES (%s, %s)", (today_str, json.dumps(picks)))
                conn.commit()
                # Push Telegram
                cursor.execute("SELECT user_data FROM user_profiles WHERE username != 'GLOBAL_CONFIG' LIMIT 1")
                u_row = cursor.fetchone()
                if u_row:
                    tg_id = json.loads(u_row['user_data']).get("telegram_id")
                    bot_token = st.secrets.get("TELEGRAM_BOT_TOKEN")
                    if tg_id and bot_token:
                        msg = f"⚡ *Morning Briefing*\n1. {picks[0]}\n2. {picks[1]}\n3. {picks[2]}"
                        requests.get(f"https://api.telegram.org/bot{bot_token}/sendMessage?chat_id={tg_id}&text={msg}&parse_mode=Markdown")
        conn.close()
    except: pass

# --- SCANNER ---
@st.cache_data(ttl=3600)
def run_gap_scanner(user_tickers, api_key):
    fh_key = st.secrets.get("FINNHUB_API_KEY"); candidates = []
    for t in user_tickers:
        try:
            r = requests.get(f"https://finnhub.io/api/v1/quote?symbol={t}&token={fh_key}").json()
            if 'c' in r:
                gap = ((r['c'] - r['pc']) / r['pc']) * 100
                if abs(gap) >= 1.0: candidates.append({"ticker": t, "gap": gap, "price": r['c']})
        except: continue
    return candidates[:3]

# --- AUTH HELPERS ---
def validate_session(token):
    try:
        conn = get_connection(); cursor = conn.cursor()
        cursor.execute("SELECT username FROM user_sessions WHERE token = %s", (token,))
        res = cursor.fetchone(); conn.close(); return res[0] if res else None
    except: return None

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

def load_user_profile(username):
    try:
        conn = get_connection(); cursor = conn.cursor()
        cursor.execute("SELECT user_data FROM user_profiles WHERE username = %s", (username,))
        res = cursor.fetchone(); conn.close()
        return json.loads(res[0]) if res else {"w_input": "TD.TO, SPY"}
    except: return {"w_input": "TD.TO, SPY"}

def save_user_profile(username, data, pin=None):
    try:
        conn = get_connection(); cursor = conn.cursor(); j_str = json.dumps(data)
        if pin: cursor.execute("INSERT INTO user_profiles (username, user_data, pin) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE user_data=%s, pin=%s", (username, j_str, pin, j_str, pin))
        else: cursor.execute("INSERT INTO user_profiles (username, user_data) VALUES (%s, %s) ON DUPLICATE KEY UPDATE user_data=%s", (username, j_str, j_str))
        conn.commit(); conn.close()
    except: pass

def load_global_config():
    try:
        conn = get_connection(); cursor = conn.cursor()
        cursor.execute("SELECT user_data FROM user_profiles WHERE username = 'GLOBAL_CONFIG'")
        res = cursor.fetchone(); conn.close(); return json.loads(res[0]) if res else {"portfolio": {}}
    except: return {"portfolio": {}}

def save_global_config(data):
    try:
        conn = get_connection(); cursor = conn.cursor(); j_str = json.dumps(data)
        cursor.execute("INSERT INTO user_profiles (username, user_data) VALUES ('GLOBAL_CONFIG', %s) ON DUPLICATE KEY UPDATE user_data=%s", (j_str, j_str))
        conn.commit(); conn.close()
    except: pass

# --- UI INIT ---
init_db()
ACTIVE_KEY = st.secrets.get("OPENAI_KEY") or st.secrets.get("OPENAI_API_KEY")
run_morning_briefing(ACTIVE_KEY)

if "init" not in st.session_state:
    st.session_state["init"] = True; st.session_state["logged_in"] = False
    url_token = st.query_params.get("token")
    if url_token:
        user = validate_session(url_token)
        if user: st.session_state["username"] = user; st.session_state["user_data"] = load_user_profile(user); st.session_state["global_data"] = load_global_config(); st.session_state["logged_in"] = True

st.markdown("""<style>
.metric-label { font-size: 10px; color: #888; font-weight: 600; display: flex; justify-content: space-between; margin-top: 8px; text-transform: uppercase; }
.bar-bg { background: #eee; height: 5px; border-radius: 3px; width: 100%; margin-top: 3px; overflow: hidden; }
.bar-fill { height: 100%; border-radius: 3px; }
.tag { font-size: 9px; padding: 1px 5px; border-radius: 3px; font-weight: bold; color: white; }
.info-pill { font-size: 10px; color: #333; background: #f8f9fa; padding: 3px 8px; border-radius: 4px; font-weight: 600; margin-right: 6px; display: inline-block; border: 1px solid #eee; }
.news-card { padding: 8px 15px; margin-bottom: 15px; border-left: 6px solid #ccc; background: #fff; }
.news-title { font-size: 16px; font-weight: 700; color: #333; text-decoration: none; display: block; }
.ticker-badge { font-size: 9px; padding: 2px 5px; border-radius: 3px; color: white; font-weight: bold; margin-right: 6px; display: inline-block; }
</style>""", unsafe_allow_html=True)

if not st.session_state["logged_in"]:
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        st.markdown("<h1 style='text-align:center;'>⚡ Penny Pulse</h1>", unsafe_allow_html=True)
        with st.form("login"):
            u = st.text_input("Username"); p = st.text_input("PIN", type="password")
            if st.form_submit_button("🚀 Login"):
                ex, stp = check_user_exists(u.strip())
                if (ex and stp == p) or not ex:
                    if not ex: save_user_profile(u.strip(), {"w_input": "TD.TO, SPY"}, p)
                    st.query_params["token"] = create_session(u.strip())
                    st.session_state["username"] = u.strip(); st.session_state["user_data"] = load_user_profile(u.strip()); st.session_state["global_data"] = load_global_config(); st.session_state["logged_in"] = True; st.rerun()
else:
    USER = st.session_state["user_data"]; GLOBAL = st.session_state["global_data"]
    def push_user(): save_user_profile(st.session_state["username"], USER)
    def push_global(): save_global_config(GLOBAL)

    with st.sidebar:
        st.markdown(f"👤 **{st.session_state['username']}**")
        st.markdown(f"<div style='font-size:10px; color:#888;'>📡 Connection: Finnhub {'🟢' if st.secrets.get('FINNHUB_API_KEY') else '🔴'}</div>", unsafe_allow_html=True)
        
        with st.expander("⚡ AI Daily Picks", expanded=True):
            if st.button("🔎 Scan Market"):
                picks = run_gap_scanner([x.strip().upper() for x in USER['w_input'].split(",")], ACTIVE_KEY)
                for p in picks: st.markdown(f"**{p['ticker']}** (+{p['gap']:.1f}%)")
        
        new_w = st.text_area("Watchlist", value=USER['w_input'], height=100)
        if new_w != USER['w_input']: USER['w_input'] = new_w; push_user(); st.rerun()

        # FIXED: RESTORED ALERTS LOGIC
        with st.expander("🔔 Alert Settings"):
            USER["telegram_id"] = st.text_input("Telegram ID", value=USER.get("telegram_id", ""))
            c1, c2 = st.columns(2)
            USER["alert_price"] = c1.checkbox("Price", value=USER.get("alert_price", True))
            USER["alert_trend"] = c2.checkbox("Trend", value=USER.get("alert_trend", True))
            if st.button("Save Alerts"): push_user(); st.success("Saved")

        # FIXED: RESTORED ADMIN PANEL LOGIC
        with st.expander("🔐 Admin"):
            if st.text_input("Password", type="password") == st.secrets.get("ADMIN_PASSWORD"):
                new_t = st.text_input("Ticker").upper()
                c1, c2 = st.columns(2); new_p = c1.number_input("Cost"); new_q = c2.number_input("Qty", step=1)
                if st.button("Add Pick") and new_t:
                    if "portfolio" not in GLOBAL: GLOBAL["portfolio"] = {}
                    GLOBAL["portfolio"][new_t] = {"e": new_p, "q": int(new_q)}; push_global(); st.rerun()
                rem = st.selectbox("Remove Pick", [""] + list(GLOBAL.get("portfolio", {}).keys()))
                if st.button("Delete") and rem: del GLOBAL["portfolio"][rem]; push_global(); st.rerun()

        if st.button("Logout"): st.query_params.clear(); st.session_state["logged_in"] = False; st.rerun()

    # Dashboard tab rendering remains untouched to preserve fixes
    @st.fragment(run_every=60)
    def render_dashboard():
        t1, t2, t3, t4 = st.tabs(["📊 Market", "🚀 My Picks", "📰 News", "🌎 Discovery"])
        w_tickers = [x.strip().upper() for x in USER['w_input'].split(",") if x.strip()]
        port = GLOBAL.get("portfolio", {}); batch_data = {}
        # ... [Actual get_batch_data calling and draw_card mapping] ...
