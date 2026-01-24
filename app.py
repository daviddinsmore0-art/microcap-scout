import streamlit as st
import mysql.connector
import json
import uuid
import time

# =========================
# PAGE CONFIG
# =========================
st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="wide")

# =========================
# DATABASE CONFIG (SECRETS)
# =========================
DB_CONFIG = {
    "host": st.secrets["DB_HOST"],
    "user": st.secrets["DB_USER"],
    "password": st.secrets["DB_PASS"],
    "database": st.secrets["DB_NAME"],
    "connect_timeout": 10
}

# =========================
# DB HELPERS
# =========================
def get_connection():
    return mysql.connector.connect(**DB_CONFIG)

def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_profiles (
            username VARCHAR(255) PRIMARY KEY,
            user_data TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_sessions (
            token VARCHAR(255) PRIMARY KEY,
            username VARCHAR(255)
        )
    """)

    conn.commit()
    conn.close()

# =========================
# AUTH
# =========================
def create_session(username):
    token = str(uuid.uuid4())
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("DELETE FROM user_sessions WHERE username=%s", (username,))
    cur.execute(
        "INSERT INTO user_sessions (token, username) VALUES (%s, %s)",
        (token, username)
    )

    conn.commit()
    conn.close()
    return token

def validate_session(token):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT username FROM user_sessions WHERE token=%s",
        (token,)
    )
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None

def logout_session(token):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM user_sessions WHERE token=%s", (token,))
    conn.commit()
    conn.close()

# =========================
# USER DATA
# =========================
def load_user(username):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT user_data FROM user_profiles WHERE username=%s",
        (username,)
    )
    row = cur.fetchone()
    conn.close()

    if row:
        return json.loads(row[0])
    return {"watchlist": "AAPL, MSFT, TSLA"}

def save_user(username, data):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO user_profiles (username, user_data)
        VALUES (%s, %s)
        ON DUPLICATE KEY UPDATE user_data=%s
    """, (username, json.dumps(data), json.dumps(data)))
    conn.commit()
    conn.close()

# =========================
# INIT
# =========================
init_db()

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

token = st.query_params.get("token")
if token and not st.session_state.logged_in:
    user = validate_session(token)
    if user:
        st.session_state.logged_in = True
        st.session_state.username = user
        st.session_state.user_data = load_user(user)

# =========================
# LOGIN SCREEN
# =========================
if not st.session_state.logged_in:
    st.title("⚡ Penny Pulse")

    username = st.text_input("Username")
    if st.button("Login") and username:
        token = create_session(username.strip())
        st.query_params["token"] = token
        st.session_state.logged_in = True
        st.session_state.username = username.strip()
        st.session_state.user_data = load_user(username.strip())
        st.rerun()

# =========================
# MAIN APP
# =========================
else:
    USER = st.session_state.user_data

    with st.sidebar:
        st.markdown(f"👤 **{st.session_state.username}**")

        wl = st.text_area(
            "Your Watchlist (comma separated)",
            USER.get("watchlist", "")
        )

        if wl != USER.get("watchlist"):
            USER["watchlist"] = wl
            save_user(st.session_state.username, USER)

        if st.button("Logout"):
            logout_session(st.query_params.get("token"))
            st.query_params.clear()
            st.session_state.clear()
            st.rerun()

    st.subheader("📊 Live Watchlist")

    tickers = [x.strip().upper() for x in USER.get("watchlist", "").split(",") if x.strip()]

    if not tickers:
        st.info("Add tickers to your watchlist.")
    else:
        for t in tickers:
            st.markdown(f"- **{t}**")

    st.caption("Stable baseline version ✔")
