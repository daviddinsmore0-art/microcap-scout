import streamlit as st
import pandas as pd
import altair as alt
import time
import json
import mysql.connector
from mysql.connector import Error
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

# --- SETUP & STYLING ---
try:
    st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="wide")
except:
    pass

# *** CONFIG ***
ADMIN_PASSWORD = st.secrets.get("ADMIN_PASSWORD", "")
LOGO_PATH = "logo.png"

# *** DATABASE CONFIG (SECRETS) ***
DB_CONFIG = {
    "host": st.secrets["DB_HOST"],
    "user": st.secrets["DB_USER"],
    "password": st.secrets["DB_PASS"],
    "database": st.secrets["DB_NAME"],
    "connect_timeout": 30,
}

# --- DATABASE ENGINE ---
def get_connection():
    return mysql.connector.connect(**DB_CONFIG)

def init_db():
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS user_profiles (username VARCHAR(255) PRIMARY KEY, user_data TEXT)"
        )
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS user_sessions (token VARCHAR(255) PRIMARY KEY, username VARCHAR(255), created_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
        )
        conn.close()
        return True
    except Error:
        return False

# --- AUTHENTICATION ---
def create_session(username):
    token = str(uuid.uuid4())
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM user_sessions WHERE username = %s", (username,))
        cursor.execute(
            "INSERT INTO user_sessions (token, username) VALUES (%s, %s)",
            (token, username),
        )
        conn.commit()
        conn.close()
        return token
    except:
        return None

def validate_session(token):
    for _ in range(3):
        try:
            conn = get_connection()
            if not conn.is_connected():
                conn.reconnect(attempts=3, delay=1)
            cursor = conn.cursor()
            cursor.execute("SELECT username FROM user_sessions WHERE token = %s", (token,))
            res = cursor.fetchone()
            conn.close()
            if res:
                return res[0]
        except:
            time.sleep(0.5)
            continue
    return None

def logout_session(token):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM user_sessions WHERE token = %s", (token,))
        conn.commit()
        conn.close()
    except:
        pass

# --- DATA LOADERS ---
def load_user_profile(username):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_data FROM user_profiles WHERE username = %s", (username,))
        res = cursor.fetchone()
        conn.close()
        if res:
            return json.loads(res[0])
        else:
            return {"w_input": "TD.TO, NKE, SPY"}
    except:
        return {"w_input": "TD.TO, NKE, SPY"}

def save_user_profile(username, data):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        j_str = json.dumps(data)
        sql = """
        INSERT INTO user_profiles (username, user_data)
        VALUES (%s, %s)
        ON DUPLICATE KEY UPDATE user_data = %s
        """
        cursor.execute(sql, (username, j_str, j_str))
        conn.commit()
        conn.close()
    except:
        pass

def load_global_config():
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_data FROM user_profiles WHERE username = 'GLOBAL_CONFIG'")
        res = cursor.fetchone()
        conn.close()
        if res:
            return json.loads(res[0])
        else:
            return {
                "portfolio": {},
                "openai_key": "",
                "rss_feeds": ["https://finance.yahoo.com/news/rssindex"],
                "tape_input": "^DJI, ^IXIC, ^GSPTSE, GC=F",
            }
    except:
        return {}

def save_global_config(data):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        j_str = json.dumps(data)
        sql = """
        INSERT INTO user_profiles (username, user_data)
        VALUES ('GLOBAL_CONFIG', %s)
        ON DUPLICATE KEY UPDATE user_data = %s
        """
        cursor.execute(sql, (j_str, j_str))
        conn.commit()
        conn.close()
    except:
        pass

# --- GLOBAL KEY FINDER ---
def get_global_config_data():
    api_key = None
    rss_feeds = ["https://finance.yahoo.com/news/rssindex"]
    try:
        api_key = st.secrets.get("OPENAI_KEY") or st.secrets.get("OPENAI_API_KEY")
    except:
        pass

    g = load_global_config()
    if not api_key:
        api_key = g.get("openai_key")
    if g.get("rss_feeds"):
        rss_feeds = g.get("rss_feeds")

    return api_key, rss_feeds, g

# --- HELPERS ---
def inject_wake_lock(enable):
    if enable:
        components.html(
            """<script>navigator.wakeLock.request('screen').catch(console.log);</script>""",
            height=0,
        )

# --- NEWS & AI ENGINE ---
def relative_time(date_str):
    try:
        dt = datetime.strptime(date_str, "%a, %d %b %Y %H:%M:%S %z")
        diff = datetime.now(timezone.utc) - dt
        seconds = diff.total_seconds()
        if seconds < 3600:
            return f"{int(seconds // 60)}m ago"
        if seconds < 86400:
            return f"{int(seconds // 3600)}h ago"
        return f"{int(seconds // 86400)}d ago"
    except:
        return "Recent"

@st.cache_data(ttl=600)
def fetch_news(feeds, tickers, api_key):
    if not NEWS_LIB_READY:
        return []
    all_feeds = feeds.copy()

    if tickers:
        for t in tickers:
            all_feeds.append(f"https://finance.yahoo.com/rss/headline?s={t}")

    articles = []
    seen = set()
    
    smart_tickers = {}
    if tickers:
        for t in tickers:
            root = t.split('.')[0] 
            smart_tickers[t] = root

    for url in all_feeds:
        try:
            f = feedparser.parse(url)
            limit = 5 if tickers else 10

            for entry in f.entries[:limit]:
                if entry.link not in seen:
                    seen.add(entry.link)
                    found_ticker, sentiment = "", "NEUTRAL"
                    title_upper = entry.title.upper()

                    # 1. AI Analysis
                    if api_key:
                        try:
                            client = openai.OpenAI(api_key=api_key)
                            prompt = (
                                f"Analyze headline: '{entry.title}'. Return exactly: TICKER|SENTIMENT. "
                                f"If a specific company is mentioned, use its ticker. "
                                f"If
