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

# --- IMPORTS FOR NEWS ---
try:
    import feedparser
    NEWS_LIB_READY = True
except ImportError:
    NEWS_LIB_READY = False

# --- CONFIG ---
try:
    st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="wide")
except: pass

ADMIN_PASSWORD = st.secrets.get("ADMIN_PASSWORD", "")
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

def check_and_fix_schema():
    """Auto-heals the database schema if columns are missing."""
    try:
        conn = get_connection(); cursor = conn.cursor(buffered=True)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stock_cache (
                ticker VARCHAR(20) PRIMARY KEY,
                current_price DECIMAL(20, 4),
                day_change DECIMAL(10, 2),
                rsi DECIMAL(10, 2),
                volume_status VARCHAR(20),
                trend_status VARCHAR(20),
                rating VARCHAR(50),
                price_history JSON,
                company_name VARCHAR(255),
                pre_post_price DECIMAL(20, 4),
                pre_post_pct DECIMAL(10, 2),
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        for col, dtype in [('company_name', 'VARCHAR(255)'), ('pre_post_price', 'DECIMAL(20, 4)'), ('pre_post_pct', 'DECIMAL(10, 2)')]:
            cursor.execute(f"SHOW COLUMNS FROM stock_cache LIKE '{col}'")
            if not cursor.fetchone():
                cursor.execute(f"ALTER TABLE stock_cache ADD COLUMN {col} {dtype}")
                conn.commit()
        conn.close()
    except: pass

# --- THE BULK DOWNLOAD ENGINE (BATCH MODE) ---
def run_backend_update(force=False):
    """Downloads ALL stocks in ONE single request to prevent bans."""
    status = st.empty()
    try:
        conn = get_connection(); cursor = conn.cursor(dictionary=True, buffered=True)
        
        # 1. Gather all unique tickers
        cursor.execute("SELECT user_data FROM user_profiles")
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
        
        # 2. Filter stale tickers
        to_fetch = []
        if force:
            to_fetch = list(needed)
        else:
            format_strings = ','.join(['%s'] * len(needed))
            cursor.execute(f"SELECT ticker, last_updated FROM stock_cache WHERE ticker IN ({format_strings})", tuple(needed))
            existing = {row['ticker']: row['last_updated'] for row in cursor.fetchall()}
            now = datetime.now()
            for t in needed:
                last = existing.get(t)
                if not last or (now - last).total_seconds() > 300: # 5 min cache
                    to_fetch.append(t)
        
        if not to_fetch: conn.close(); return

        # 3. BATCH DOWNLOAD
        if force: status.info(f"⚡ Batching {len(to_fetch)} tickers from Yahoo...")
        
        tickers_str = " ".join(to_fetch)
        # Use yfinance bulk download
        data = yf.download(tickers_str, period="1mo", group_by='ticker', threads=True, progress=False)
        
        # 4. Process Batch Data
        for t in to_fetch:
            try:
                if len(to_fetch) == 1: df = data
                else: 
                    # Handle missing data in batch
                    if t not in data.columns.levels[0]: continue 
                    df = data[t]
                
                df = df.dropna(subset=['Close'])
                if df.empty: continue

                curr = float(df['Close'].iloc[-1])
                prev = float(df['Close'].iloc[-2]) if len(df) > 1 else curr
                change = ((curr - prev) / prev) * 100
                trend = "UPTREND" if curr > df['Close'].tail(20).mean() else "DOWNTREND"
                
                delta = df['Close'].diff()
                g = delta.where(delta > 0, 0).rolling(14).mean()
                l = (-delta.where(delta < 0, 0)).rolling(14).mean()
                rsi_val = 100 - (100 / (1 + (g / l).iloc[-1])) if (not l.empty and l.iloc[-1] != 0) else 50.0
                
                vol_mean = df['Volume'].mean()
                vol_pct = (df['Volume'].iloc[-1] / vol_mean * 100) if vol_mean > 0 else 100
                
                # Note: 'info' is not available in bulk, so we default name to ticker
                # This is the trade-off for 100x speed.
                
                j_p = json.dumps(df['Close'].tail(20).tolist())
                
                sql = """
                INSERT INTO stock_cache 
                (ticker, current_price, day_change, rsi, volume_status, trend_status, price_history, company_name, last_updated)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON DUPLICATE KEY UPDATE
                current_price=%s, day_change=%s, rsi=%s, volume_status=%s, trend_status=%s, price_history=%s, last_updated=NOW()
                """
                v = (t, curr, change, rsi_val, vol_pct, trend, j_p, t, 
                     curr, change, rsi_val, vol_pct, trend, j_p)
                cursor.execute(sql, v)
                
            except Exception as e: pass
        
        conn.commit(); conn.close()
        status.empty()
    except: pass

# --- AUTH HELPERS ---
def check_user_exists(username):
    try:
        conn = get_connection(); cursor = conn.cursor(buffered=True)
        cursor.execute("SELECT pin FROM user_profiles WHERE username = %s", (username,))
        res = cursor.fetchone(); conn.close()
        return (True, res[0]) if res else (False, None)
    except: return False, None

def create_session(username):
    token = str(uuid.uuid4())
    try:
        conn = get_connection(); cursor = conn.cursor(buffered=True)
        cursor.execute("DELETE FROM user_sessions WHERE username = %s", (username,))
        cursor.execute("INSERT INTO user_sessions (token, username) VALUES (%s, %s)", (token, username))
        conn.commit(); conn.close(); return token
    except: return None

def validate_session(token):
    try:
        conn = get_connection(); cursor = conn.cursor(buffered=True)
        cursor.execute("SELECT username FROM user_sessions WHERE token = %s", (token,))
        res = cursor.fetchone(); conn.close()
        return res[0] if res else None
    except: return None

def load_user_profile(username):
    try:
        conn = get_connection(); cursor = conn.cursor(buffered=True)
        cursor.execute("SELECT user_data FROM user_profiles WHERE username = %s", (username,))
        res = cursor.fetchone(); conn.close()
        return json.loads(res[0]) if res else {"w_input": "TD.TO, SPY"}
    except: return {"w_input": "TD.TO, SPY"}

def save_user_profile(username, data, pin=None):
    try:
        conn = get_connection(); cursor = conn.cursor(buffered=True); j_str = json.dumps(data)
        if pin: cursor.execute("INSERT INTO user_profiles (username, user_data, pin) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE user_data = %s, pin = %s", (username, j_str, pin, j_str, pin))
        else: cursor.execute("INSERT INTO user_profiles (username, user_data) VALUES (%s, %s) ON DUPLICATE KEY UPDATE user_data = %s", (username, j_str, j_str))
        conn.commit(); conn.close()
    except: pass

def load_global_config():
    try:
        conn = get_connection(); cursor = conn.cursor(buffered=True)
        cursor.execute("SELECT user_data FROM user_profiles WHERE username = 'GLOBAL_CONFIG'")
        res = cursor.fetchone(); conn.close()
        return json.loads(res[0]) if res else {"portfolio": {}, "tape_input": "^DJI, ^IXIC, ^GSPTSE, GC=F"}
    except: return {}

# --- UI STYLING ---
st.markdown("""<style>
.block-container { padding-top: 0rem !important; }
div[data-testid="stVerticalBlock"] { background-color: #ffffff; border-radius: 12px; padding: 15px; box-shadow: 0 4px 10px rgba(0,0,0,0.05); border: 1px solid #f0f0f0; margin-bottom: 10px; }
.metric-label { font-size: 10px; color: #888; font-weight: 600; display: flex; justify-content: space-between; margin-top: 8px; text-transform: uppercase; }
.bar-bg { background: #eee; height: 5px; border-radius: 3px; width: 100%; margin-top: 3px; overflow: hidden; }
.bar-fill { height: 100%; border-radius: 3px; }
.info-pill { font-size: 10px; color: #333; background: #f8f9fa; padding: 3px 8px; border-radius: 4px; font-weight: 600; margin-right: 6px; display: inline-block; border: 1px solid #eee; }
</style>""", unsafe_allow_html=True)

# --- STARTUP ---
check_and_fix_schema()
run_backend_update(force=False) # Auto-batch update

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
                if exists and str(stored_pin) == str(pin):
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
        if st.button("⚡ Force Batch Update", type="primary"):
            run_backend_update(force=True)
            st.rerun()
            
        new_w = st.text_area("Watchlist", value=USER_DATA.get("w_input", ""))
        if new_w != USER_DATA.get("w_input"): USER_DATA["w_input"] = new_w; save_user_profile(USER_NAME, USER_DATA); st.rerun()
        if st.button("Logout"): st.query_params.clear(); st.session_state["logged_in"] = False; st.rerun()

    # --- TICKER TAPE ---
    try:
        conn = get_connection(); cursor = conn.cursor(dictionary=True, buffered=True)
        t_symbols = [x.strip().upper() for x in GLOBAL.get("tape_input", "^DJI,^IXIC,^GSPTSE,GC=F").split(",")]
        format_strings = ','.join(['%s'] * len(t_symbols))
        cursor.execute(f"SELECT ticker, current_price, day_change FROM stock_cache WHERE ticker IN ({format_strings})", tuple(t_symbols))
        tape_rows = cursor.fetchall(); conn.close()
        tape_str = "  |  ".join([f"{r['ticker']} ${float(r['current_price']):,.2f} ({float(r['day_change']):+.2f}%)" for r in tape_rows])
        components.html(f'<marquee style="background:#111; color:white; padding:10px; font-weight:bold;">{tape_str}</marquee>', height=45)
    except: pass

    # --- MAIN CONTENT ---
    tabs = st.tabs(["📊 Market", "🚀 Portfolio", "📰 News"])

    def draw_card(t, port=None):
        try:
            conn = get_connection(); cursor = conn.cursor(dictionary=True, buffered=True)
            cursor.execute("SELECT * FROM stock_cache WHERE ticker = %s", (t,))
            d = cursor.fetchone(); conn.close()
            if not d: return # Silent fail for clean UI

            p, chg = float(d['current_price']), float(d['day_change'])
            b_col = "#4caf50" if chg >= 0 else "#ff4b4b"
            display_name = d.get('company_name') or t
            
            st.markdown(f"""<div style='display:flex; justify-content:space-between; align-items:flex-start;'>
                <div><div style='font-size:22px; font-weight:bold;'>{t}</div><div style='font-size:12px; color:#888;'>{display_name[:25]}</div></div>
                <div style='text-align:right;'><div style='font-size:22px; font-weight:bold;'>${p:,.2f}</div><div style='color:{b_col}; font-weight:bold;'>{chg:+.2f}%</div></div>
            </div>""", unsafe_allow_html=True)
            
            # Post Market
            if d.get('pre_post_price') and float(d['pre_post_price']) > 0:
                 pp = float(d['pre_post_price']); ppc = float(d['pre_post_pct'])
                 if abs(pp - p) > 0.01:
                     st.markdown(f"<div style='text-align:right; font-size:11px; color:#888;'>EXT: <span style='color:{'#4caf50' if ppc>=0 else '#ff4b4b'}'>${pp:,.2f}</span></div>", unsafe_allow_html=True)

            hist = json.loads(d['price_history'])
            c_df = pd.DataFrame({'x': range(len(hist)), 'y': hist})
            spark = alt.Chart(c_df).mark_area(line={'color': b_col}, color=alt.Gradient(gradient='linear', stops=[alt.GradientStop(color=b_col, offset=0), alt.GradientStop(color='white', offset=1)], x1=1, x2=1, y1=1, y2=0)).encode(x=alt.X('x', axis=None), y=alt.Y('y', axis=None, scale=alt.Scale(zero=False))).properties(height=50)
            st.altair_chart(spark, use_container_width=True)
            
            rsi = float(d['rsi']); vol = float(d['volume_status'])
            st.markdown(f"<div class='info-pill'>AI: {d['trend_status']}</div><div class='info-pill'>RSI: {int(rsi)}</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='metric-label'><span>RSI Strength</span></div><div class='bar-bg'><div class='bar-fill' style='width:{rsi}%; background:{b_col};'></div></div>", unsafe_allow_html=True)
            st.markdown(f"<div class='metric-label'><span>Volume</span></div><div class='bar-bg'><div class='bar-fill' style='width:{min(vol, 100)}%; background:#3498db;'></div></div>", unsafe_allow_html=True)
            
            if port:
                gain = (p - port['e']) * port['q']
                st.markdown(f"<div style='font-size:12px; margin-top:10px; background:#f9f9f9; padding:5px; border-radius:5px;'>Qty: {port['q']} | Avg: ${port['e']} | <span style='color:{'#4caf50' if gain>=0 else '#ff4b4b'}'>${gain:+,.2f}</span></div>", unsafe_allow_html=True)
        except: pass

    with tabs[0]:
        tickers = [x.strip().upper() for x in USER_DATA.get("w_input", "").split(",") if x.strip()]
        cols = st.columns(3)
        for i, t in enumerate(tickers):
            with cols[i % 3]: draw_card(t)

    with tabs[1]:
        port = GLOBAL.get("portfolio", {})
        if not port: st.info("No picks published.")
        else:
            total_val, total_cost = 0.0, 0.0
            for k, v in port.items():
                conn = get_connection(); cursor = conn.cursor(dictionary=True, buffered=True)
                cursor.execute("SELECT current_price FROM stock_cache WHERE ticker=%s", (k,))
                row = cursor.fetchone(); conn.close()
                if row: total_val += float(row['current_price']) * v['q']; total_cost += v['e'] * v['q']
            st.metric("Total Value", f"${total_val:,.2f}", f"{(total_val-total_cost):+,.2f}")
            cols = st.columns(3)
            for i, (k, v) in enumerate(port.items()):
                with cols[i % 3]: draw_card(k, port=v)

    with tabs[2]:
        if NEWS_LIB_READY:
            rss = GLOBAL.get("rss_feeds", ["https://finance.yahoo.com/news/rssindex"])
            try:
                for url in rss:
                    f = feedparser.parse(url)
                    for e in f.entries[:5]:
                        st.markdown(f"**[{e.title}]({e.link})**")
            except: st.info("News Unavailable")

    time.sleep(60)
    st.rerun()
