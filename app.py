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

# --- SETUP ---
try:
    st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="wide")
except:
    pass

ADMIN_PASSWORD = st.secrets.get("ADMIN_PASSWORD", "")
DB_CONFIG = {
    "host": st.secrets["DB_HOST"],
    "user": st.secrets["DB_USER"],
    "password": st.secrets["DB_PASS"],
    "database": st.secrets["DB_NAME"],
    "connect_timeout": 30,
}

# --- DATABASE ---
def get_connection():
    return mysql.connector.connect(**DB_CONFIG)

def init_db():
    try:
        conn = get_connection(); cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS user_profiles (username VARCHAR(255) PRIMARY KEY, user_data TEXT, pin VARCHAR(50))")
        cursor.execute("CREATE TABLE IF NOT EXISTS user_sessions (token VARCHAR(255) PRIMARY KEY, username VARCHAR(255), created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
        # Ensure stock_cache exists
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
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
        """)
        conn.close()
    except Exception as e:
        st.error(f"DB Init Error: {e}")

# --- THE UPDATE ENGINE (WITH DEBUGGING) ---
def run_backend_update(force=False):
    """
    Updates stock data.
    If 'force=True', it ignores the timer and updates EVERYTHING.
    """
    status_container = st.empty() # Placeholder for status messages
    
    try:
        conn = get_connection(); cursor = conn.cursor(dictionary=True)
        
        # 1. Get List of Tickers
        cursor.execute("SELECT user_data FROM user_profiles")
        users = cursor.fetchall()
        needed = set(["^DJI", "^IXIC", "^GSPTSE", "GC=F"]) 
        for r in users:
            try:
                data = json.loads(r['user_data'])
                if 'w_input' in data: needed.update([t.strip().upper() for t in data['w_input'].split(",") if t.strip()])
                if 'portfolio' in data: needed.update(data['portfolio'].keys())
            except: pass
        
        # 2. Check which ones are old
        to_fetch = []
        if force:
            to_fetch = list(needed)
            status_container.info(f"⚡ FORCE UPDATE: Refreshing {len(to_fetch)} tickers...")
        else:
            format_strings = ','.join(['%s'] * len(needed))
            cursor.execute(f"SELECT ticker, last_updated FROM stock_cache WHERE ticker IN ({format_strings})", tuple(needed))
            existing = {row['ticker']: row['last_updated'] for row in cursor.fetchall()}
            now = datetime.now()
            for t in needed:
                last = existing.get(t)
                # Update if missing OR older than 5 mins
                if not last or (now - last).total_seconds() > 300:
                    to_fetch.append(t)
        
        if not to_fetch:
            conn.close()
            return # Nothing to do

        # 3. Fetch Data (Visible Progress)
        progress_bar = status_container.progress(0)
        total = len(to_fetch)
        
        for i, t in enumerate(to_fetch):
            try:
                # Yahoo Call
                tk = yf.Ticker(t)
                hist = tk.history(period="1mo", interval="1d", timeout=10)
                
                if hist.empty:
                    print(f"Skipping {t}: No data found")
                    continue

                curr = float(hist['Close'].iloc[-1])
                prev = float(hist['Close'].iloc[-2]) if len(hist) > 1 else curr
                change = ((curr - prev) / prev) * 100
                
                # Indicators
                trend = "UPTREND" if curr > hist['Close'].tail(20).mean() else "DOWNTREND"
                info = tk.info
                name = info.get('shortName') or info.get('longName') or t
                rating = info.get('recommendationKey', 'N/A').upper().replace('_', ' ')
                
                # RSI
                delta = hist['Close'].diff()
                g = delta.where(delta > 0, 0).rolling(14).mean()
                l = (-delta.where(delta < 0, 0)).rolling(14).mean()
                if not l.empty and not pd.isna(l.iloc[-1]):
                     rsi_val = 100 - (100 / (1 + (g / l).iloc[-1]))
                else:
                     rsi_val = 50.0

                # Pre-Market
                pp_p, pp_c = 0.0, 0.0
                try:
                    live = tk.history(period="1d", interval="1m", prepost=True)
                    if not live.empty:
                        lp = live['Close'].iloc[-1]
                        if abs(lp - curr) > 0.01: 
                            pp_p, pp_c = float(lp), float(((lp - curr)/curr)*100)
                except: pass

                # SQL Save
                sql = """
                INSERT INTO stock_cache 
                (ticker, current_price, day_change, rsi, trend_status, rating, price_history, company_name, pre_post_price, pre_post_pct, last_updated)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON DUPLICATE KEY UPDATE
                current_price=%s, day_change=%s, rsi=%s, trend_status=%s, rating=%s, price_history=%s, company_name=%s, pre_post_price=%s, pre_post_pct=%s, last_updated=NOW()
                """
                j_p = json.dumps(hist['Close'].tail(20).tolist())
                vals = (t, curr, change, rsi_val, trend, rating, j_p, name, pp_p, pp_c,
                        curr, change, rsi_val, trend, rating, j_p, name, pp_p, pp_c)
                cursor.execute(sql, vals)
                conn.commit()
                
            except Exception as e:
                # SHOW ERROR ON SCREEN
                st.toast(f"❌ Error on {t}: {str(e)}")
            
            # Update Progress
            progress_bar.progress((i + 1) / total)
            
        status_container.success("✅ Update Complete!")
        time.sleep(1)
        status_container.empty()
        conn.close()
        
    except Exception as e:
        st.error(f"Backend Error: {e}")

# --- AUTH HELPERS ---
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
init_db()

# --- LOGIN ---
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
                # Simplified check for demo
                save_user_profile(user, {"w_input": "TD.TO, SPY"}, pin) 
                st.session_state["username"] = user; st.session_state["logged_in"] = True; st.rerun()
else:
    USER_NAME = st.session_state["username"]
    USER_DATA = load_user_profile(USER_NAME)
    GLOBAL = load_global_config()

    # --- SIDEBAR ---
    with st.sidebar:
        st.title(f"Hi, {USER_NAME}!")
        
        # *** THE MAGIC FIX BUTTON ***
        if st.button("⚡ Force Update Data", type="primary"):
            run_backend_update(force=True)
            st.rerun()
            
        new_w = st.text_area("Watchlist", value=USER_DATA.get("w_input", ""))
        if new_w != USER_DATA.get("w_input"): USER_DATA["w_input"] = new_w; save_user_profile(USER_NAME, USER_DATA); st.rerun()
        if st.button("Logout"): st.query_params.clear(); st.session_state["logged_in"] = False; st.rerun()

    # --- TICKER TAPE ---
    try:
        conn = get_connection(); cursor = conn.cursor(dictionary=True)
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
            conn = get_connection(); cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM stock_cache WHERE ticker = %s", (t,))
            d = cursor.fetchone(); conn.close()
            
            if not d: 
                st.warning(f"⚠️ {t}: No data yet. Click 'Force Update' in sidebar.")
                return

            p, chg = float(d['current_price']), float(d['day_change'])
            b_col = "#4caf50" if chg >= 0 else "#ff4b4b"
            
            # --- CARD HEADER ---
            st.markdown(f"""<div style='display:flex; justify-content:space-between; align-items:flex-start;'>
                <div><div style='font-size:22px; font-weight:bold;'>{t}</div><div style='font-size:12px; color:#888;'>{d['company_name'][:25]}</div></div>
                <div style='text-align:right;'><div style='font-size:22px; font-weight:bold;'>${p:,.2f}</div><div style='color:{b_col}; font-weight:bold;'>{chg:+.2f}%</div></div>
            </div>""", unsafe_allow_html=True)
            
            # --- POST MARKET ---
            if d['pre_post_price'] and float(d['pre_post_price']) > 0:
                pp_p = float(d['pre_post_price'])
                pp_c = float(d['pre_post_pct'])
                if abs(pp_p - p) > 0.01:
                    st.markdown(f"<div style='text-align:right; font-size:11px; color:#888;'>POST: <span style='color:{'#4caf50' if pp_c>=0 else '#ff4b4b'}'>${pp_p:,.2f} ({pp_c:+.2f}%)</span></div>", unsafe_allow_html=True)

            # --- CHART ---
            hist = json.loads(d['price_history'])
            c_df = pd.DataFrame({'x': range(len(hist)), 'y': hist})
            chart = alt.Chart(c_df).mark_area(line={'color': b_col}, color=alt.Gradient(gradient='linear', stops=[alt.GradientStop(color=b_col, offset=0), alt.GradientStop(color='white', offset=1)], x1=1, x2=1, y1=1, y2=0)).encode(x=alt.X('x', axis=None), y=alt.Y('y', axis=None, scale=alt.Scale(zero=False))).properties(height=50)
            st.altair_chart(chart, use_container_width=True)
            
            # --- GAUGES ---
            rsi = float(d['rsi'])
            st.markdown(f"<div class='info-pill'>AI: {d['trend_status']}</div><div class='info-pill'>RSI: {int(rsi)}</div><div class='info-pill'>Rating: {d['rating']}</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='metric-label'><span>RSI Strength</span></div><div class='bar-bg'><div class='bar-fill' style='width:{rsi}%; background:{b_col};'></div></div>", unsafe_allow_html=True)
            
            if port:
                gain = (p - port['e']) * port['q']
                st.markdown(f"<div style='font-size:12px; margin-top:10px; background:#f9f9f9; padding:5px; border-radius:5px;'>Qty: {port['q']} | Avg: ${port['e']} | <span style='color:{'#4caf50' if gain>=0 else '#ff4b4b'}'>${gain:+,.2f}</span></div>", unsafe_allow_html=True)
            
            # Timestamp (So you know it's fresh)
            if d['last_updated']:
                diff = datetime.now() - d['last_updated']
                mins = int(diff.total_seconds() / 60)
                st.caption(f"Updated: {mins} mins ago")
                
        except Exception as e:
            st.error(f"Draw Error {t}: {e}")

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
                conn = get_connection(); cursor = conn.cursor(dictionary=True)
                cursor.execute("SELECT current_price FROM stock_cache WHERE ticker=%s", (k,))
                row = cursor.fetchone(); conn.close()
                if row: total_val += float(row['current_price']) * v['q']; total_cost += v['e'] * v['q']
            st.metric("Total Value", f"${total_val:,.2f}", f"{(total_val-total_cost):+,.2f}")
            cols = st.columns(3)
            for i, (k, v) in enumerate(port.items()):
                with cols[i % 3]: draw_card(k, port=v)

    # --- AUTO LOOP ---
    # Attempt auto-update if not forced
    run_backend_update(force=False)
    time.sleep(60)
    st.rerun()
