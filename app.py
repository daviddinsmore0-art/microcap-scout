import streamlit as st
import pandas as pd
import altair as alt
import time
import json
import mysql.connector
import yfinance as yf
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
        cursor.execute("CREATE TABLE IF NOT EXISTS user_profiles (username VARCHAR(255) PRIMARY KEY, user_data TEXT, pin VARCHAR(50))")
        cursor.execute("CREATE TABLE IF NOT EXISTS user_sessions (token VARCHAR(255) PRIMARY KEY, username VARCHAR(255), created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
        conn.close()
        return True
    except Error: return False

# --- SMART DYNAMIC BACKEND (The Backup Brain) ---
def run_backend_update():
    """Forces the app to update stale data itself if the dedicated server sleeps."""
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT username, user_data FROM user_profiles")
        users = cursor.fetchall()
        needed = set(["^DJI", "^IXIC", "^GSPTSE", "GC=F"]) 
        for r in users:
            try:
                data = json.loads(r['user_data'])
                if 'w_input' in data: needed.update([t.strip().upper() for t in data['w_input'].split(",") if t.strip()])
                if 'portfolio' in data: needed.update(data['portfolio'].keys())
                if r['username'] == 'GLOBAL_CONFIG' and 'tape_input' in data:
                     needed.update([t.strip().upper() for t in data['tape_input'].split(",") if t.strip()])
            except: pass
        if not needed: conn.close(); return
        format_strings = ','.join(['%s'] * len(needed))
        cursor.execute(f"SELECT ticker, last_updated FROM stock_cache WHERE ticker IN ({format_strings})", tuple(needed))
        existing = {row['ticker']: row['last_updated'] for row in cursor.fetchall()}
        to_fetch = []
        now = datetime.now()
        for t in needed:
            last = existing.get(t)
            if not last or (now - last).total_seconds() > 300: to_fetch.append(t)
        if not to_fetch: conn.close(); return
        for t in to_fetch:
            try:
                tk = yf.Ticker(t)
                hist = tk.history(period="1mo", interval="1d", timeout=5)
                if hist.empty: continue
                curr, prev = float(hist['Close'].iloc[-1]), float(hist['Close'].iloc[-2]) if len(hist) > 1 else float(hist['Close'].iloc[-1])
                change = ((curr - prev) / prev) * 100
                rsi = 50.0
                try:
                    delta = hist['Close'].diff(); g = delta.where(delta > 0, 0).rolling(14).mean(); l = (-delta.where(delta < 0, 0)).rolling(14).mean()
                    rsi = 100 - (100 / (1 + (g / l).iloc[-1]))
                except: pass
                trend = "UPTREND" if curr > hist['Close'].tail(20).mean() else "DOWNTREND"
                rating, comp_name = "N/A", t
                try:
                    info = tk.info; rating = info.get('recommendationKey', 'N/A').replace('_', ' ').upper()
                    comp_name = info.get('shortName') or info.get('longName') or t
                except: pass
                earn_str = "N/A"
                try:
                    cal = tk.calendar
                    if isinstance(cal, dict) and 'Earnings Date' in cal:
                        for d in cal['Earnings Date']:
                            if d.date() >= now.date(): earn_str = d.strftime('%b %d'); break
                except: pass
                pp_p, pp_c = 0.0, 0.0
                try:
                    live = tk.history(period="1d", interval="1m", prepost=True)
                    if not live.empty:
                        lp = live['Close'].iloc[-1]
                        if abs(lp - curr) > 0.01: pp_p, pp_c = float(lp), float(((lp - curr)/curr)*100)
                except: pass
                sql = """INSERT INTO stock_cache (ticker, current_price, day_change, rsi, trend_status, rating, next_earnings, pre_post_price, pre_post_pct, price_history, company_name)
                         VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE current_price=%s, day_change=%s, rsi=%s, trend_status=%s, rating=%s, next_earnings=%s,
                         pre_post_price=%s, pre_post_pct=%s, price_history=%s, company_name=%s"""
                j_p = json.dumps(hist['Close'].tail(20).tolist())
                v = (t, curr, change, rsi, trend, rating, earn_str, pp_p, pp_c, j_p, comp_name, curr, change, rsi, trend, rating, earn_str, pp_p, pp_c, j_p, comp_name)
                cursor.execute(sql, v); conn.commit()
            except: pass
        conn.close()
    except: pass

# --- AUTH HELPERS ---
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
        conn.commit(); conn.close(); return token
    except: return None

def validate_session(token):
    try:
        conn = get_connection(); cursor = conn.cursor()
        cursor.execute("SELECT username FROM user_sessions WHERE token = %s", (token,))
        res = cursor.fetchone(); conn.close()
        return res[0] if res else None
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
        if pin: cursor.execute("INSERT INTO user_profiles (username, user_data, pin) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE user_data = %s, pin = %s", (username, j_str, pin, j_str, pin))
        else: cursor.execute("INSERT INTO user_profiles (username, user_data) VALUES (%s, %s) ON DUPLICATE KEY UPDATE user_data = %s", (username, j_str, j_str))
        conn.commit(); conn.close()
    except: pass

def load_global_config():
    try:
        conn = get_connection(); cursor = conn.cursor()
        cursor.execute("SELECT user_data FROM user_profiles WHERE username = 'GLOBAL_CONFIG'")
        res = cursor.fetchone(); conn.close()
        return json.loads(res[0]) if res else {"portfolio": {}, "tape_input": "^DJI, ^IXIC, GC=F"}
    except: return {}

def save_global_config(data):
    try:
        conn = get_connection(); cursor = conn.cursor(); j_str = json.dumps(data)
        cursor.execute("INSERT INTO user_profiles (username, user_data) VALUES ('GLOBAL_CONFIG', %s) ON DUPLICATE KEY UPDATE user_data = %s", (j_str, j_str))
        conn.commit(); conn.close()
    except: pass

# --- UI STYLING ---
st.markdown("""<style>
.block-container { padding-top: 4.5rem !important; }
div[data-testid="stVerticalBlock"] { background-color: #ffffff; border-radius: 12px; padding: 15px; box-shadow: 0 4px 10px rgba(0,0,0,0.05); border: 1px solid #f0f0f0; margin-bottom: 10px; }
.metric-label { font-size: 10px; color: #888; font-weight: 600; display: flex; justify-content: space-between; margin-top: 8px; text-transform: uppercase; }
.bar-bg { background: #eee; height: 5px; border-radius: 3px; width: 100%; margin-top: 3px; overflow: hidden; }
.bar-fill { height: 100%; border-radius: 3px; }
.info-pill { font-size: 10px; color: #333; background: #f8f9fa; padding: 3px 8px; border-radius: 4px; font-weight: 600; margin-right: 6px; display: inline-block; border: 1px solid #eee; }
</style>""", unsafe_allow_html=True)

# --- STARTUP ---
init_db()
run_backend_update() # Forced refresh on start

if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
    token = st.query_params.get("token")
    if token:
        u = validate_session(token)
        if u: st.session_state["username"] = u; st.session_state["logged_in"] = True

if not st.session_state["logged_in"]:
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        st.markdown("<h1 style='text-align:center;'>⚡ Penny Pulse</h1>", unsafe_allow_html=True)
        with st.form("login"):
            user = st.text_input("Username").strip()
            pin = st.text_input("4-Digit PIN", type="password")
            if st.form_submit_button("Login / Sign Up", type="primary"):
                exists, stored_pin = check_user_exists(user)
                if exists and stored_pin == pin:
                    st.session_state["username"] = user; st.session_state["logged_in"] = True
                    st.query_params["token"] = create_session(user); st.rerun()
                elif not exists:
                    save_user_profile(user, {"w_input": "TD.TO, SPY"}, pin)
                    st.session_state["username"] = user; st.session_state["logged_in"] = True
                    st.query_params["token"] = create_session(user); st.rerun()
                else: st.error("Invalid PIN")
else:
    USER_NAME = st.session_state["username"]
    USER_DATA = load_user_profile(USER_NAME)
    GLOBAL = load_global_config()

    # --- SIDEBAR ---
    with st.sidebar:
        st.title(f"Hi, {USER_NAME}!")
        new_w = st.text_area("Your Watchlist", value=USER_DATA.get("w_input", ""))
        if new_w != USER_DATA.get("w_input"): USER_DATA["w_input"] = new_w; save_user_profile(USER_NAME, USER_DATA); st.rerun()
        
        with st.expander("🔔 Alerts"):
            st.text_input("Telegram ID", value=USER_DATA.get("telegram_id", ""), help="Get from @userinfobot")
        
        if st.button("Logout"): st.query_params.clear(); st.session_state["logged_in"] = False; st.rerun()

    # --- MAIN CONTENT ---
    tabs = st.tabs(["📊 Market", "🚀 Portfolio", "📰 News"])

    def draw_card(t, port=None):
        """High-Performance card drawing with SILENT refresh."""
        try:
            conn = get_connection(); cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM stock_cache WHERE ticker = %s", (t,))
            d = cursor.fetchone(); conn.close()
            if not d: st.info(f"Processing {t}..."); return

            p, chg = float(d['current_price']), float(d['day_change'])
            b_col = "#4caf50" if chg >= 0 else "#ff4b4b"
            
            st.markdown(f"""<div style='display:flex; justify-content:space-between;'>
                <div><b>{t}</b><br><small>{d['company_name'][:20]}</small></div>
                <div style='text-align:right;'><b>${p:,.2f}</b><br><span style='color:{b_col}'>{chg:+.2f}%</span></div>
            </div>""", unsafe_allow_html=True)
            
            # Simple Sparkline
            hist = json.loads(d['price_history'])
            c_df = pd.DataFrame({'x': range(len(hist)), 'y': hist})
            spark = alt.Chart(c_df).mark_area(line={'color': b_col}, color=alt.Gradient(gradient='linear', stops=[alt.GradientStop(color=b_col, offset=0), alt.GradientStop(color='white', offset=1)], x1=1, x2=1, y1=1, y2=0)).encode(x=alt.X('x', axis=None), y=alt.Y('y', axis=None, scale=alt.Scale(zero=False))).properties(height=40)
            st.altair_chart(spark, use_container_width=True)
            
            # Indicators
            st.markdown(f"<div class='info-pill'>AI: {d['trend']}</div><div class='info-pill'>RSI: {int(float(d['rsi']))}</div>", unsafe_allow_html=True)
        except: pass

    with tabs[0]:
        tickers = [x.strip().upper() for x in USER_DATA.get("w_input", "").split(",") if x.strip()]
        cols = st.columns(3)
        for i, t in enumerate(tickers):
            with cols[i % 3]: draw_card(t)

    # --- THE ENGINE LOOP ---
    time.sleep(60)
    st.rerun() # Refresh picture every 60s
