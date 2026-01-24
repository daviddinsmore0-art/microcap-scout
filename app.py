import streamlit as st
import yfinance as yf
import pandas as pd
import altair as alt
import time
import json
import mysql.connector
from mysql.connector import Error
from datetime import datetime, timedelta, timezone
import streamlit.components.v1 as components
import os
import base64
import uuid

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
    "host": st.secrets["DB_HOST"],
    "user": st.secrets["DB_USER"],
    "password": st.secrets["DB_PASS"],
    "database": st.secrets["DB_NAME"],
    "connect_timeout": 30
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
            "CREATE TABLE IF NOT EXISTS user_sessions (token VARCHAR(255) PRIMARY KEY, username VARCHAR(255))"
        )
        conn.close()
        return True
    except Error:
        return False

# --- AUTHENTICATION (ORIGINAL SIMPLE VERSION) ---
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
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT username FROM user_sessions WHERE token = %s", (token,)
        )
        res = cursor.fetchone()
        conn.close()
        if res:
            return res[0]
    except:
        pass
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
        cursor.execute(
            "SELECT user_data FROM user_profiles WHERE username = %s", (username,)
        )
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

# --- INIT ---
init_db()

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    url_token = st.query_params.get("token")
    if url_token:
        user = validate_session(url_token)
        if user:
            st.session_state.logged_in = True
            st.session_state.username = user
            st.session_state.user_data = load_user_profile(user)

# --- LOGIN SCREEN ---
if not st.session_state.logged_in:
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        if os.path.exists(LOGO_PATH):
            st.image(LOGO_PATH, width=160)
        else:
            st.markdown("<h1>⚡ Penny Pulse</h1>", unsafe_allow_html=True)

        st.text_input("Username", key="login_user")

        if st.button("Login"):
            u = st.session_state.login_user.strip()
            if u:
                token = create_session(u)
                st.query_params["token"] = token
                st.session_state.logged_in = True
                st.session_state.username = u
                st.session_state.user_data = load_user_profile(u)
                st.rerun()

# --- MAIN APP ---
else:
    USER = st.session_state.user_data

    with st.sidebar:
        st.markdown(f"👤 **{st.session_state.username}**")

        new_w = st.text_area(
            "Your Watchlist (comma separated)",
            USER.get("w_input", ""),
        )
        if new_w != USER.get("w_input"):
            USER["w_input"] = new_w
            save_user_profile(st.session_state.username, USER)

        if st.button("Logout"):
            logout_session(st.query_params.get("token"))
            st.query_params.clear()
            st.session_state.clear()
            st.rerun()

    st.markdown("## 📊 Live Watchlist")

    tickers = [
        x.strip().upper()
        for x in USER.get("w_input", "").split(",")
        if x.strip()
    ]

    if not tickers:
        st.info("Add tickers to your watchlist.")
    else:
        cols = st.columns(3)
        for i, t in enumerate(tickers):
            with cols[i % 3]:
                try:
                    tk = yf.Ticker(t)
                    p = tk.history(period="2d")
                    if not p.empty:
                        last = p["Close"].iloc[-1]
                        prev = p["Close"].iloc[-2]
                        pct = ((last - prev) / prev) * 100
                        st.metric(t, f"${last:.2f}", f"{pct:+.2f}%")
                except:
                    st.warning(t)

    st.caption("Restored original Penny Pulse UI ✔")
