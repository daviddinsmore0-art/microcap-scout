import streamlit as st
import yfinance as yf
import pandas as pd
import altair as alt
import time
import json
import mysql.connector
from mysql.connector import Error
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import streamlit.components.v1 as components
import os
import uuid
from contextlib import contextmanager

# =========================
# PAGE CONFIG
# =========================
st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="wide")

# =========================
# SECRETS / CONFIG
# =========================
ADMIN_PASSWORD = st.secrets["ADMIN_PASSWORD"]

DB_CONFIG = {
    "host": st.secrets["DB_HOST"],
    "user": st.secrets["DB_USER"],
    "password": st.secrets["DB_PASS"],
    "database": st.secrets["DB_NAME"],
    "connect_timeout": 30
}

OPENAI_KEY = st.secrets.get("OPENAI_API_KEY")

# =========================
# DATABASE HELPERS
# =========================
@contextmanager
def db():
    conn = mysql.connector.connect(**DB_CONFIG)
    cur = conn.cursor()
    try:
        yield conn, cur
    finally:
        cur.close()
        conn.close()

def init_db():
    with db() as (conn, cur):
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_profiles (
                username VARCHAR(255) PRIMARY KEY,
                user_data JSON
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_sessions (
                token VARCHAR(255) PRIMARY KEY,
                username VARCHAR(255),
                expires_at DATETIME
            )
        """)
        conn.commit()

# =========================
# AUTH
# =========================
def create_session(username):
    token = str(uuid.uuid4())
    expires = datetime.utcnow() + timedelta(days=30)
    with db() as (conn, cur):
        cur.execute("DELETE FROM user_sessions WHERE username=%s", (username,))
        cur.execute(
            "INSERT INTO user_sessions VALUES (%s,%s,%s)",
            (token, username, expires)
        )
        conn.commit()
    return token

def validate_session(token):
    with db() as (conn, cur):
        cur.execute(
            "SELECT username, expires_at FROM user_sessions WHERE token=%s",
            (token,)
        )
        row = cur.fetchone()
        if not row:
            return None
        if row[1] < datetime.utcnow():
            return None
        return row[0]

def logout_session(token):
    with db() as (conn, cur):
        cur.execute("DELETE FROM user_sessions WHERE token=%s", (token,))
        conn.commit()

# =========================
# USER DATA
# =========================
def load_user(username):
    with db() as (_, cur):
        cur.execute("SELECT user_data FROM user_profiles WHERE username=%s", (username,))
        row = cur.fetchone()
        return json.loads(row[0]) if row else {"w_input": "TD.TO, NKE, SPY"}

def save_user(username, data):
    with db() as (conn, cur):
        cur.execute("""
            INSERT INTO user_profiles VALUES (%s,%s)
            ON DUPLICATE KEY UPDATE user_data=%s
        """, (username, json.dumps(data), json.dumps(data)))
        conn.commit()

# =========================
# PRICE ENGINE
# =========================
@st.cache_data(ttl=60)
def get_price(symbol):
    tk = yf.Ticker(symbol)
    hist = tk.history(period="2d")
    if hist.empty:
        return None
    last = hist.iloc[-1]
    prev = hist.iloc[-2]
    pct = ((last.Close - prev.Close) / prev.Close) * 100
    return {
        "price": last.Close,
        "pct": pct,
        "name": tk.info.get("longName", symbol)
    }

# =========================
# SESSION INIT
# =========================
init_db()

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    token = st.query_params.get("token")
    if token:
        user = validate_session(token)
        if user:
            st.session_state.username = user
            st.session_state.user = load_user(user)
            st.session_state.logged_in = True

# =========================
# LOGIN
# =========================
if not st.session_state.logged_in:
    st.title("⚡ Penny Pulse")
    username = st.text_input("Username")
    if st.button("Login") and username:
        token = create_session(username.strip())
        st.query_params["token"] = token
        st.session_state.username = username.strip()
        st.session_state.user = load_user(username.strip())
        st.session_state.logged_in = True
        st.rerun()

# =========================
# MAIN APP
# =========================
else:
    USER = st.session_state.user

    with st.sidebar:
        st.markdown(f"👤 **{st.session_state.username}**")
        watch = st.text_area("Watchlist", USER.get("w_input", ""))
        if watch != USER.get("w_input"):
            USER["w_input"] = watch
            save_user(st.session_state.username, USER)
            st.rerun()

        if st.button("Logout"):
            logout_session(st.query_params.get("token"))
            st.query_params.clear()
            st.session_state.logged_in = False
            st.rerun()

    t1, t2 = st.tabs(["📊 Live Market", "📰 News"])

    # ---------- LIVE MARKET ----------
    with t1:
        tickers = [x.strip().upper() for x in USER["w_input"].split(",") if x.strip()]
        cols = st.columns(3)
        for i, t in enumerate(tickers):
            with cols[i % 3]:
                d = get_price(t)
                if not d:
                    st.warning(f"{t} unavailable")
                    continue
                col = "green" if d["pct"] >= 0 else "red"
                st.metric(t, f"${d['price']:.2f}", f"{d['pct']:+.2f}%")

    # ---------- NEWS ----------
    with t2:
        st.info("News engine unchanged — safe to reattach your existing fetch_news()")
