import streamlit as st
import pandas as pd
import altair as alt
import time
import json
import mysql.connector
import requests
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
            "CREATE TABLE IF NOT EXISTS user_profiles (username VARCHAR(255) PRIMARY KEY, user_data TEXT, pin VARCHAR(50))"
        )
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS user_sessions (token VARCHAR(255) PRIMARY KEY, username VARCHAR(255), created_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
        )
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
                day_high DECIMAL(20, 4),
                day_low DECIMAL(20, 4),
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
        """)
        # Auto-patch missing columns if they don't exist
        for col in ['day_high', 'day_low', 'company_name', 'pre_post_price']:
            try:
                cursor.execute(f"ALTER TABLE stock_cache ADD COLUMN {col} DECIMAL(20,4)" if 'day' in col or 'price' in col else f"ALTER TABLE stock_cache ADD COLUMN {col} VARCHAR(255)")
            except: pass
            
        conn.close()
        return True
    except Error:
        return False

# --- THE FIX: DUAL-BATCH BACKEND (Live + History) ---
def run_backend_update():
    """
    1. Fetches LIVE 1m data (Price, BTC, Pre-Market).
    2. Fetches HISTORY 1d data (Sparklines, RSI, High/Low).
    """
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True, buffered=True)
        
        # 1. Gather Tickers
        cursor.execute("SELECT user_data FROM user_profiles")
        users = cursor.fetchall()
        all_tickers = set(["^DJI", "^IXIC", "^GSPTSE", "GC=F"]) 
        for r in users:
            try:
                data = json.loads(r['user_data'])
                if 'w_input' in data: all_tickers.update([t.strip().upper() for t in data['w_input'].split(",") if t.strip()])
                if 'portfolio' in data: all_tickers.update(data['portfolio'].keys())
                if 'tape_input' in data: all_tickers.update([t.strip().upper() for t in data['tape_input'].split(",") if t.strip()])
            except: pass

        if not all_tickers: conn.close(); return

        # 2. Check Stale (Update if older than 2 mins)
        format_strings = ','.join(['%s'] * len(all_tickers))
        cursor.execute(f"SELECT ticker, last_updated FROM stock_cache WHERE ticker IN ({format_strings})", tuple(all_tickers))
        existing = {row['ticker']: row['last_updated'] for row in cursor.fetchall()}
        
        to_fetch = []
        now = datetime.now()
        for t in all_tickers:
            last = existing.get(t)
            if not last or (now - last).total_seconds() > 120:
                to_fetch.append(t)
        
        if not to_fetch: conn.close(); return

        tickers_str = " ".join(to_fetch)
        
        # 3. DUAL DOWNLOAD (The Magic Fix)
        # Batch A: LIVE 1m (for BTC & Pre/Post)
        live_data = yf.download(tickers_str, period="5d", interval="1m", prepost=True, group_by='ticker', threads=True, progress=False)
        # Batch B: HISTORY 1d (for Charts & RSI)
        hist_data = yf.download(tickers_str, period="1mo", interval="1d", group_by='ticker', threads=True, progress=False)

        # 4. PROCESS
        for t in to_fetch:
            try:
                # LIVE
                if len(to_fetch) == 1: df_live = live_data
                else: 
                    if t not in live_data.columns.levels[0]: continue
                    df_live = live_data[t]
                
                df_live = df_live.dropna(subset=['Close'])
                if df_live.empty: continue
                curr_price = float(df_live['Close'].iloc[-1])

                # HISTORY
                if len(to_fetch) == 1: df_hist = hist_data
                else:
                    if t in hist_data.columns.levels[0]: df_hist = hist_data[t]
                    else: df_hist = pd.DataFrame()
                
                day_change = 0.0; rsi = 50.0; vol_stat = "NORMAL"; trend = "NEUTRAL"
                day_h = curr_price; day_l = curr_price; chart_json = "[]"

                if not df_hist.empty:
                    df_hist = df_hist.dropna(subset=['Close'])
                    # Day Range
                    if len(df_hist) > 0:
                        day_h = float(df_hist['High'].iloc[-1])
                        day_l = float(df_hist['Low'].iloc[-1])
                        day_h = max(day_h, curr_price)
                        day_l = min(day_l, curr_price)

                    # Change Calc
                    if len(df_hist) > 1:
                        prev_close = float(df_hist['Close'].iloc[-2])
                        if df_live.index[-1].date() > df_hist.index[-1].date():
                            prev_close = float(df_hist['Close'].iloc[-1])
                        day_change = ((curr_price - prev_close) / prev_close) * 100
                    
                    # Trend/RSI/Vol
                    trend = "UPTREND" if curr_price > df_hist['Close'].tail(20).mean() else "DOWNTREND"
                    try:
                        delta = df_hist['Close'].diff()
                        g = delta.where(delta > 0, 0).rolling(14).mean(); l = (-delta.where(delta < 0, 0)).rolling(14).mean()
                        if not l.empty and l.iloc[-1] != 0: rsi = 100 - (100 / (1 + (g.iloc[-1]/l.iloc[-1])))
                    except: pass
                    if not df_hist['Volume'].empty:
                        v_avg = df_hist['Volume'].mean()
                        if v_avg > 0:
                            v_curr = df_hist['Volume'].iloc[-1]
                            if v_curr > v_avg * 1.5: vol_stat = "HEAVY"
                            elif v_curr < v_avg * 0.5: vol_stat = "LIGHT"
                    
                    chart_json = json.dumps(df_hist['Close'].tail(20).tolist())

                # Pre/Post
                pp_p = 0.0; pp_pct = 0.0
                if len(df_live) > 0: pp_p = curr_price; pp_pct = day_change

                # Default Metadata (Lazy)
                rating = "N/A"; earn = "N/A"; comp_name = t

                sql = """
                INSERT INTO stock_cache (ticker, current_price, day_change, rsi, volume_status, trend_status, rating, next_earnings, pre_post_price, pre_post_pct, price_history, company_name, day_high, day_low, last_updated)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON DUPLICATE KEY UPDATE
                current_price=%s, day_change=%s, rsi=%s, volume_status=%s, trend_status=%s, price_history=%s, pre_post_price=%s, pre_post_pct=%s, day_high=%s, day_low=%s, last_updated=NOW()
                """
                v = (t, curr_price, day_change, rsi, vol_stat, trend, rating, earn, pp_p, pp_pct, chart_json, comp_name, day_h, day_l,
                     curr_price, day_change, rsi, vol_stat, trend, chart_json, pp_p, pp_pct, day_h, day_l)
                cursor.execute(sql, v)
                conn.commit()
            except: pass
        conn.close()
    except: pass
# ----------------------------------------------------

# --- AUTHENTICATION ---
def check_user_exists(username):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT pin FROM user_profiles WHERE username = %s", (username,))
        res = cursor.fetchone()
        conn.close()
        if res: return True, res[0]
        return False, None
    except: return False, None

def create_session(username):
    token = str(uuid.uuid4())
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM user_sessions WHERE username = %s", (username,))
        cursor.execute("INSERT INTO user_sessions (token, username) VALUES (%s, %s)", (token, username))
        conn.commit()
        conn.close()
        return token
    except: return None

def validate_session(token):
    for _ in range(3):
        try:
            conn = get_connection()
            if not conn.is_connected(): conn.reconnect(attempts=3, delay=1)
            cursor = conn.cursor()
            cursor.execute("SELECT username FROM user_sessions WHERE token = %s", (token,))
            res = cursor.fetchone()
            conn.close()
            if res: return res[0]
        except:
            time.sleep(0.5); continue
    return None

def logout_session(token):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM user_sessions WHERE token = %s", (token,))
        conn.commit()
        conn.close()
    except: pass

# --- DATA LOADERS ---
def load_user_profile(username):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_data FROM user_profiles WHERE username = %s", (username,))
        res = cursor.fetchone()
        conn.close()
        return json.loads(res[0]) if res else {"w_input": "TD.TO, NKE, SPY"}
    except: return {"w_input": "TD.TO, NKE, SPY"}

def save_user_profile(username, data, pin=None):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        j_str = json.dumps(data)
        if pin:
            sql = "INSERT INTO user_profiles (username, user_data, pin) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE user_data = %s, pin = %s"
            cursor.execute(sql, (username, j_str, pin, j_str, pin))
        else:
            sql = "INSERT INTO user_profiles (username, user_data) VALUES (%s, %s) ON DUPLICATE KEY UPDATE user_data = %s"
            cursor.execute(sql, (username, j_str, j_str))
        conn.commit(); conn.close()
    except: pass

def load_global_config():
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_data FROM user_profiles WHERE username = 'GLOBAL_CONFIG'")
        res = cursor.fetchone()
        conn.close()
        return json.loads(res[0]) if res else {"portfolio": {}, "openai_key": "", "rss_feeds": ["https://finance.yahoo.com/news/rssindex"], "tape_input": "^DJI, ^IXIC, ^GSPTSE, GC=F"}
    except: return {}

def save_global_config(data):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        j_str = json.dumps(data)
        sql = "INSERT INTO user_profiles (username, user_data) VALUES ('GLOBAL_CONFIG', %s) ON DUPLICATE KEY UPDATE user_data = %s"
        cursor.execute(sql, (j_str, j_str))
        conn.commit(); conn.close()
    except: pass

def get_global_config_data():
    api_key = None
    rss_feeds = ["https://finance.yahoo.com/news/rssindex"]
    try: api_key = st.secrets.get("OPENAI_KEY") or st.secrets.get("OPENAI_API_KEY")
    except: pass
    g = load_global_config()
    if not api_key: api_key = g.get("openai_key")
    if g.get("rss_feeds"): rss_feeds = g.get("rss_feeds")
    return api_key, rss_feeds, g

# --- NEWS & AI ENGINE ---
def relative_time(date_str):
    try:
        dt = datetime.strptime(date_str, "%a, %d %b %Y %H:%M:%S %z")
        diff = datetime.now(timezone.utc) - dt
        seconds = diff.total_seconds()
        if seconds < 3600: return f"{int(seconds // 60)}m ago"
        if seconds < 86400: return f"{int(seconds // 3600)}h ago"
        return f"{int(seconds // 86400)}d ago"
    except: return "Recent"

@st.cache_data(ttl=600)
def fetch_news(feeds, tickers, api_key):
    if not NEWS_LIB_READY: return []
    all_feeds = feeds.copy()
    if tickers:
        for t in tickers: all_feeds.append(f"https://finance.yahoo.com/rss/headline?s={t}")

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
                    summary_text = entry.get("summary", "")

                    if api_key:
                        try:
                            client = openai.OpenAI(api_key=api_key)
                            prompt = (
                                f"Analyze this news item:\nHeadline: '{entry.title}'\nSummary: '{summary_text}'\n\n"
                                f"Return exactly: TICKER|SENTIMENT. Use company ticker or MARKET|SENTIMENT."
                            )
                            response = client.chat.completions.create(
                                model="gpt-4o-mini",
                                messages=[{"role": "user", "content": prompt}],
                                max_tokens=15,
                            )
                            ans = response.choices[0].message.content.strip().upper()
                            if "|" in ans:
                                parts = ans.split("|")
                                t_raw = parts[0].strip()
                                if t_raw not in ["NONE", "NULL"]: found_ticker = t_raw
                                sentiment = parts[1].strip()
                        except: pass

                    if not found_ticker and tickers:
                        for original_t, root_t in smart_tickers.items():
                            if re.search(r'\b' + re.escape(root_t) + r'\b', title_upper):
                                found_ticker = original_t; break
                            elif original_t in title_upper:
                                found_ticker = original_t; break
                        if not found_ticker:
                            for original_t, root_t in smart_tickers.items():
                                if re.search(r'\b' + re.escape(root_t) + r'\b', summary_text.upper()):
                                    found_ticker = original_t; break

                    articles.append({
                        "title": entry.title, "link": entry.link,
                        "published": relative_time(entry.get("published", "")),
                        "ticker": found_ticker, "sentiment": sentiment,
                    })
        except: pass
    return articles

# --- DATA ENGINE ---
@st.cache_data(ttl=600)
def get_fundamentals(s):
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT rating, next_earnings FROM stock_cache WHERE ticker = %s", (s,))
        row = cursor.fetchone()
        conn.close()
        return {"rating": row['rating'], "earn": row['next_earnings']} if row else {"rating": "N/A", "earn": "N/A"}
    except: return {"rating": "N/A", "earn": "N/A"}

@st.cache_data(ttl=10)
def get_pro_data(s):
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM stock_cache WHERE ticker = %s", (s,))
        row = cursor.fetchone()
        conn.close()
        if not row: return None

        price = float(row['current_price'])
        change = float(row['day_change'])
        rsi_val = float(row['rsi'])
        trend = row['trend_status']
        vol_stat = row['volume_status']
        display_name = row.get('company_name') or s

        pp_html = ""
        if row.get('pre_post_price') and float(row['pre_post_price']) > 0:
            pp_p = float(row['pre_post_price'])
            pp_c = float(row['pre_post_pct'])
            # Logic: If price in DB (Live) differs from Price in Chart (History)
            if abs(pp_p - price) < 0.01:
                pass # Same
            else:
                now = datetime.now(timezone.utc) - timedelta(hours=5)
                lbl = "POST" if now.hour >= 16 else "PRE" if now.hour < 9 else "LIVE"
                if now.weekday() > 4: lbl = "POST" 
                col = "#4caf50" if pp_c >= 0 else "#ff4b4b"
                pp_html = f"<div style='font-size:11px; color:#888; margin-top:2px;'>{lbl}: <span style='color:{col}; font-weight:bold;'>${pp_p:,.2f} ({pp_c:+.2f}%)</span></div>"

        vol_pct = 150 if vol_stat == "HEAVY" else (50 if vol_stat == "LIGHT" else 100)
        
        # Day Range
        day_h = float(row.get('day_high') or price)
        day_l = float(row.get('day_low') or price)
        range_pos = 50
        if day_h > day_l:
            range_pos = ((price - day_l) / (day_h - day_l)) * 100
            range_pos = max(0, min(100, range_pos))

        raw_hist = row.get('price_history')
        points = json.loads(raw_hist) if raw_hist else [price] * 20
        chart_data = pd.DataFrame({'Idx': range(len(points)), 'Stock': points})
        base = chart_data['Stock'].iloc[0]
        if base == 0: base = 1
        chart_data['Stock'] = ((chart_data['Stock'] - base) / base) * 100

        return {
            "p": price, "d": change, "name": display_name, "rsi": rsi_val, "vol_pct": vol_pct, "range_pos": range_pos, "h": day_h, "l": day_l,
            "ai": "BULLISH" if trend == "UPTREND" else "BEARISH", "trend": trend, "pp": pp_html, "chart": chart_data,
        }
    except: return None

@st.cache_data(ttl=60)
def get_tape_data(symbol_string, nickname_string=""):
    items = []
    symbols = [x.strip().upper() for x in symbol_string.split(",") if x.strip()]
    nick_map = {}
    if nickname_string:
        try:
            pairs = nickname_string.split(",")
            for p in pairs:
                if ":" in p: k, v = p.split(":"); nick_map[k.strip().upper()] = v.strip().upper()
        except: pass

    defaults = {
        "^DJI": "DOW", "^IXIC": "NASDAQ", "^GSPC": "S&P500", 
        "^GSPTSE": "TSX", "GC=F": "GOLD", "SI=F": "SILVER", 
        "BTC-USD": "BTC", "CL=F": "OIL", "EURUSD=X": "USD/EUR"
    }
    final_map = defaults.copy()
    final_map.update(nick_map)

    if not symbols: return ""
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        format_strings = ','.join(['%s'] * len(symbols))
        cursor.execute(f"SELECT * FROM stock_cache WHERE ticker IN ({format_strings})", tuple(symbols))
        rows = cursor.fetchall()
        conn.close()
        data_map = {row['ticker']: row for row in rows}
        for s in symbols:
            if s in data_map:
                row = data_map[s]
                px, chg = float(row['current_price']), float(row['day_change'])
                if s in final_map: disp_name = final_map[s]
                else:
                    raw_name = row.get('company_name') or s
                    disp_name = (raw_name.replace(", Inc.", "").replace(" Inc.", "").replace(" Corporation", "").replace(" Corp.", "").replace(" Limited", "").replace(" Ltd.", "").strip())
                    if len(disp_name) > 15: disp_name = disp_name[:15].strip() + ".."
                color, arrow = ("#4caf50", "▲") if chg >= 0 else ("#ff4b4b", "▼")
                items.append(f"<span style='color:#ccc; margin-left:20px;'>{disp_name}</span> <span style='color:{color}'>{arrow} {px:,.2f} ({chg:+.2f}%)</span>")
    except: pass
    return "   ".join(items)

# --- UI LOGIC ---
init_db()
run_backend_update()

if "init" not in st.session_state:
    st.session_state["init"] = True
    st.session_state["logged_in"] = False
    url_token = st.query_params.get("token", None)
    if url_token:
        user = validate_session(url_token)
        if user:
            st.session_state["username"] = user
            st.session_state["user_data"] = load_user_profile(user)
            st.session_state["global_data"] = load_global_config()
            st.session_state["logged_in"] = True
if "fcm_token" in st.query_params: st.query_params.clear()

st.markdown("""<style>
#MainMenu {visibility: visible;} footer {visibility: hidden;}
.block-container { padding-top: 4.5rem !important; padding-bottom: 2rem; }
div[data-testid="stVerticalBlock"] > div[style*="flex-direction: column;"] > div[data-testid="stVerticalBlock"] { background-color: #ffffff; border-radius: 12px; padding: 15px; box-shadow: 0 4px 10px rgba(0,0,0,0.05); border: 1px solid #f0f0f0; }
.metric-label { font-size: 10px; color: #888; font-weight: 600; display: flex; justify-content: space-between; margin-top: 8px; text-transform: uppercase; }
.bar-bg { background: #eee; height: 5px; border-radius: 3px; width: 100%; margin-top: 3px; overflow: hidden; }
.bar-fill { height: 100%; border-radius: 3px; }
.tag { font-size: 9px; padding: 1px 5px; border-radius: 3px; font-weight: bold; color: white; }
.info-pill { font-size: 10px; color: #333; background: #f8f9fa; padding: 3px 8px; border-radius: 4px; font-weight: 600; margin-right: 6px; display: inline-block; border: 1px solid #eee; }
.news-card { padding: 8px 0 8px 15px; margin-bottom: 15px; border-left: 6px solid #ccc; background-color: #fff; }
.news-title { font-size: 16px; font-weight: 700; color: #333; text-decoration: none; display: block; margin-bottom: 4px; line-height: 1.3; }
.news-meta { font-size: 11px; color: #888; }
.ticker-badge { font-size: 9px; padding: 2px 5px; border-radius: 3px; color: white; font-weight: bold; margin-right: 6px; display: inline-block; vertical-align: middle; }
</style>""", unsafe_allow_html=True)

if not st.session_state["logged_in"]:
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        if os.path.exists(LOGO_PATH): st.image(LOGO_PATH, width=150)
        else: st.markdown("<h1 style='text-align:center;'>⚡ Penny Pulse</h1>", unsafe_allow_html=True)
        st.markdown("##### 👋 Welcome")
        with st.form("login_form"):
            user = st.text_input("Username", placeholder="e.g. Dave")
            pin = st.text_input("4-Digit PIN", type="password", max_chars=4, help="Create a PIN if you are new. Enter your PIN if you are returning.")
            submit = st.form_submit_button("🚀 Login / Start", type="primary")
            if submit and user and pin:
                exists, stored_pin = check_user_exists(user.strip())
                if exists:
                    if stored_pin and stored_pin == pin:
                        st.success("Welcome back!")
                        st.query_params["token"] = create_session(user.strip())
                        st.session_state["username"] = user.strip()
                        st.session_state["user_data"] = load_user_profile(user.strip())
                        st.session_state["global_data"] = load_global_config()
                        st.session_state["logged_in"] = True
                        st.rerun()
                    elif stored_pin and stored_pin != pin: st.error("❌ Incorrect PIN for this user.")
                    else:
                        st.warning("⚠️ Account has no PIN. We will set it now.")
                        save_user_profile(user.strip(), load_user_profile(user.strip()), pin); st.rerun()
                else:
                    st.success("Creating new account...")
                    save_user_profile(user.strip(), {"w_input": "TD.TO, SPY"}, pin)
                    st.query_params["token"] = create_session(user.strip())
                    st.session_state["username"] = user.strip()
                    st.session_state["user_data"] = load_user_profile(user.strip())
                    st.session_state["global_data"] = load_global_config()
                    st.session_state["logged_in"] = True
                    st.rerun()
else:
    def push_user(): save_user_profile(st.session_state["username"], st.session_state["user_data"])
    def push_global(): save_global_config(st.session_state["global_data"])
    GLOBAL = st.session_state["global_data"]
    USER = st.session_state["user_data"]
    ACTIVE_KEY, SHARED_FEEDS, _ = get_global_config_data()

    tape_content = get_tape_data(GLOBAL.get("tape_input", "^DJI, ^IXIC, ^GSPTSE, GC=F"), GLOBAL.get("tape_nicknames", ""))
    header_html = f"""<!DOCTYPE html><html><head><style>
body {{ margin: 0; padding: 0; background: transparent; overflow: hidden; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }}
.ticker-container {{ width: 100%; height: 45px; background: #111; display: flex; align-items: center; border-bottom: 1px solid #333; border-radius: 0 0 15px 15px; box-shadow: 0 4px 10px rgba(0,0,0,0.3); }}
.ticker-wrap {{ width: 100%; overflow: hidden; white-space: nowrap; }}
.ticker-move {{ display: inline-block; animation: ticker 15s linear infinite; }}
@keyframes ticker {{ 0% {{ transform: translate3d(0, 0, 0); }} 100% {{ transform: translate3d(-25%, 0, 0); }} }}
.ticker-item {{ display: inline-block; color: white; font-weight: 900; font-size: 16px; padding: 0 20px; }}
</style></head><body><div class="ticker-container"><div class="ticker-wrap"><div class="ticker-move"><span class="ticker-item">{tape_content} &nbsp;|&nbsp; {tape_content} &nbsp;|&nbsp; {tape_content} &nbsp;|&nbsp; {tape_content}</span></div></div></div></body></html>"""
    components.html(header_html, height=50)

    with st.sidebar:
        st.markdown(f"<div style='background:#f0f2f6; padding:10px; border-radius:5px; margin-bottom:10px; text-align:center;'>👤 <b>{st.session_state['username']}</b></div>", unsafe_allow_html=True)
        st.subheader("Your Watchlist")
        new_w = st.text_area("Edit Tickers", value=USER.get("w_input", ""), height=100)
        if new_w != USER.get("w_input"):
            USER["w_input"] = new_w
            push_user()
            st.info("ℹ️ Watchlist updated. New tickers will load in moments...")
            time.sleep(1)
            st.rerun()

        st.divider()

        with st.expander("🔔 Alert Settings"):
            st.caption("TELEGRAM CONNECTION")
            curr_tg = USER.get("telegram_id", "")
            new_tg = st.text_input(
                "Telegram Chat ID", 
                value=curr_tg, 
                help="1. Download Telegram App.\n2. Search for @userinfobot.\n3. Click Start to get your ID.\n4. Paste it here."
            )
            if new_tg != curr_tg: USER["telegram_id"] = new_tg.strip(); push_user(); st.success("Saved!"); time.sleep(1); st.rerun()
            st.markdown("[Get my ID](https://t.me/userinfobot)", unsafe_allow_html=True)
            st.divider(); st.caption("ALERT PREFERENCES")
            c1, c2 = st.columns(2)
            a_price = c1.checkbox("Price Moves", value=USER.get("alert_price", True))
            a_trend = c2.checkbox("Trend Flips", value=USER.get("alert_trend", True))
            a_rating = c1.checkbox("Analyst Ratings", value=USER.get("alert_rating", True))
            a_pm = c2.checkbox("Post-Market", value=USER.get("alert_pm", True))
            if (a_price != USER.get("alert_price", True) or a_trend != USER.get("alert_trend", True) or a_rating != USER.get("alert_rating", True) or a_pm != USER.get("alert_pm", True)):
                USER["alert_price"] = a_price; USER["alert_trend"] = a_trend; USER["alert_rating"] = a_rating; USER["alert_pm"] = a_pm; push_user(); st.rerun()

        with st.expander("🔐 Admin Controls"):
            if st.text_input("Password", type="password") == ADMIN_PASSWORD:
                st.divider(); st.caption("GLOBAL PORTFOLIO")
                if "portfolio" in USER and USER["portfolio"] and not GLOBAL.get("portfolio"):
                    if st.button("⚠️ IMPORT MY OLD PICKS TO GLOBAL"): GLOBAL["portfolio"] = USER["portfolio"]; push_global(); st.success("Picks Restored!"); time.sleep(1); st.rerun()
                new_t = st.text_input("Ticker").upper()
                c1, c2 = st.columns(2)
                new_p, new_q = c1.number_input("Avg Cost"), c2.number_input("Qty", step=1)
                if st.button("Add Pick") and new_t:
                    if "portfolio" not in GLOBAL: GLOBAL["portfolio"] = {}
                    GLOBAL["portfolio"][new_t] = {"e": new_p, "q": int(new_q)}; push_global(); st.rerun()
                port_keys = list(GLOBAL.get("portfolio", {}).keys())
                rem = st.selectbox("Remove Pick", [""] + port_keys)
                if st.button("Delete") and rem: del GLOBAL["portfolio"][rem]; push_global(); st.rerun()
                st.divider(); st.caption("APP CONFIG (AI & TAPE)")
                new_tape = st.text_input("Ticker Tape Symbols", value=GLOBAL.get("tape_input", ""))
                if new_tape != GLOBAL.get("tape_input", ""): GLOBAL["tape_input"] = new_tape; push_global(); st.rerun()
                def_nicks = "^DJI:DOW, ^IXIC:NASDAQ, ^GSPTSE:TSX, GC=F:GOLD, SI=F:SILVER"
                cur_nicks = GLOBAL.get("tape_nicknames", def_nicks)
                new_nicks = st.text_area("Tape Nicknames (Symbol:Name)", value=cur_nicks, height=70, help="Format: TICKER:NAME, TICKER2:NAME2")
                if new_nicks != cur_nicks: GLOBAL["tape_nicknames"] = new_nicks; push_global(); st.rerun()
                curr_k = GLOBAL.get("openai_key", "")
                new_key = st.text_input("OpenAI Key", value=curr_k, type="password")
                if new_key != curr_k: GLOBAL["openai_key"] = new_key; push_global(); st.rerun()

        with st.expander("📰 News Feed Manager"):
            if st.text_input("Auth", type="password") == ADMIN_PASSWORD:
                st.caption("GLOBAL RSS SOURCES")
                feed_to_add = st.text_input("Add RSS URL")
                if st.button("Save Source") and feed_to_add:
                    if "rss_feeds" not in GLOBAL: GLOBAL["rss_feeds"] = ["https://finance.yahoo.com/news/rssindex"]
                    GLOBAL["rss_feeds"].append(feed_to_add); push_global(); st.rerun()
                current_feeds = GLOBAL.get("rss_feeds", ["https://finance.yahoo.com/news/rssindex"])
                st.write(f"Active Sources: {len(current_feeds)}")
                feed_to_rem = st.selectbox("Remove Source", [""] + current_feeds)
                if st.button("Delete Source") and feed_to_rem: GLOBAL["rss_feeds"].remove(feed_to_rem); push_global(); st.rerun()

        if st.button("Logout"):
            logout_session(st.query_params.get("token"))
            st.query_params.clear(); st.session_state["logged_in"] = False; st.rerun()
    
    t1, t2, t3, t4 = st.tabs(["📊 Live Market", "🚀 My Picks", "📰 My News", "🌎 Discovery"])

    def draw(t, port=None):
        d = get_pro_data(t)
        if not d: 
            st.markdown(f"<div style='padding:15px; border:1px dashed #ccc; border-radius:10px; color:#888; font-size:12px;'>⚠️ <b>{t}</b>: Processing...</div>", unsafe_allow_html=True)
            return

        f = get_fundamentals(t)
        b_col, arrow = ("#4caf50", "▲") if d["d"] >= 0 else ("#ff4b4b", "▼")
        r_up = f["rating"].upper()
        r_col = "#4caf50" if "BUY" in r_up or "OUT" in r_up else "#ff4b4b" if "SELL" in r_up or "UNDER" in r_up else "#f1c40f"
        ai_col = "#4caf50" if d["ai"] == "BULLISH" else "#ff4b4b"
        tr_col = "#4caf50" if d["trend"] == "UPTREND" else "#ff4b4b"
        header_html = f"""<div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:5px;"><div><div style="font-size:22px; font-weight:bold; margin-right:8px; color:#2c3e50;">{t}</div><div style="font-size:12px; color:#888; margin-top:-2px;">{d['name'][:25]}...</div></div><div style="text-align:right;"><div style="font-size:22px; font-weight:bold; color:#2c3e50;">${d['p']:,.2f}</div><div style="font-size:13px; font-weight:bold; color:{b_col}; margin-top:-4px;">{arrow} {d['d']:.2f}%</div>{d['pp']}</div></div>"""
        pills_html = f'<span class="info-pill" style="border-left: 3px solid {ai_col}">AI: {d["ai"]}</span><span class="info-pill" style="border-left: 3px solid {tr_col}">{d["trend"]}</span>'
        if f["rating"] != "N/A": pills_html += f'<span class="info-pill" style="border-left: 3px solid {r_col}">RATING: {f["rating"]}</span>'
        if f["earn"] != "N/A": pills_html += f'<span class="info-pill" style="border-left: 3px solid #333">EARN: {f["earn"]}</span>'
        with st.container():
            st.markdown(f"<div style='height:4px; width:100%; background-color:{b_col}; border-radius: 4px 4px 0 0;'></div>", unsafe_allow_html=True)
            st.markdown(header_html, unsafe_allow_html=True)
            st.markdown(f'<div style="margin-bottom:10px; display:flex; flex-wrap:wrap; gap:4px;">{pills_html}</div>', unsafe_allow_html=True)
            chart = alt.Chart(d["chart"]).mark_area(line={"color": b_col}, color=alt.Gradient(gradient="linear", stops=[alt.GradientStop(color=b_col, offset=0), alt.GradientStop(color="white", offset=1)], x1=1, x2=1, y1=1, y2=0)).encode(x=alt.X("Idx", axis=None), y=alt.Y("Stock", axis=None), tooltip=[]).configure_view(strokeWidth=0).properties(height=45)
            st.altair_chart(chart, use_container_width=True)
            st.markdown(f"""<div class="metric-label"><span>Day Range</span><span style="color:#555">${d['l']:,.2f} - ${d['h']:,.2f}</span></div><div class="bar-bg"><div class="bar-fill" style="width:{d['range_pos']}%; background: linear-gradient(90deg, #ff4b4b, #f1c40f, #4caf50);"></div></div>""", unsafe_allow_html=True)
            rsi, rsi_bg = d["rsi"], "#ff4b4b" if d["rsi"] > 70 else "#4caf50" if d["rsi"] < 30 else "#999"
            st.markdown(f"""<div class="metric-label"><span>RSI ({int(rsi)})</span><span class="tag" style="background:{rsi_bg}">{ "HOT" if rsi>70 else "COLD" if rsi<30 else "NEUTRAL" }</span></div><div class="bar-bg"><div class="bar-fill" style="width:{rsi}%; background:{rsi_bg};"></div></div>""", unsafe_allow_html=True)
            st.markdown(f"""<div class="metric-label"><span>Volume ({d['vol_pct']:.0f}%)</span><span style="color:#3498db; font-weight:bold;">{ "HEAVY" if d['vol_pct']>120 else "LIGHT" if d['vol_pct']<80 else "NORMAL" }</span></div><div class="bar-bg"><div class="bar-fill" style="width:{min(d['vol_pct'], 100)}%; background:#3498db;"></div></div>""", unsafe_allow_html=True)
            if port:
                gain = (d["p"] - port["e"]) * port["q"]
                st.markdown(f"""<div style="background:#f9f9f9; padding:5px; margin-top:10px; border-radius:5px; display:flex; justify-content:space-between; font-size:12px;"><span>Qty: <b>{port['q']}</b></span><span>Avg: <b>${port['e']}</b></span><span style="color:{'#4caf50' if gain>=0 else '#ff4b4b'}; font-weight:bold;">${gain:+,.0f}</span></div>""", unsafe_allow_html=True)
            st.divider()

    def render_news(n):
        col, disp = ("#4caf50" if n["sentiment"]=="BULLISH" else "#ff4b4b" if n["sentiment"]=="BEARISH" else "#333"), n["ticker"] if n["ticker"] else "MARKET"
        st.markdown(f"""<div class="news-card" style="border-left-color: {col};"><div style="display:flex; align-items:center;"><span class='ticker-badge' style='background-color:{col}'>{disp}</span><a href="{n['link']}" target="_blank" class="news-title">{n['title']}</a></div><div class="news-meta">{n['published']}</div></div>""", unsafe_allow_html=True)

    with t1:
        tickers = [x.strip().upper() for x in USER.get("w_input", "").split(",") if x.strip()]
        cols = st.columns(3)
        for i, t in enumerate(tickers):
            with cols[i % 3]: draw(t)
    with t2:
        port = GLOBAL.get("portfolio", {})
        if not port: st.info("No Picks Published.")
        else:
            total_val, total_cost, day_pl_sum = 0.0, 0.0, 0.0
            for k, v in port.items():
                d = get_pro_data(k)
                if d:
                    total_val += d["p"] * v["q"]; total_cost += v["e"] * v["q"]
                    if d["d"] != 0: day_pl_sum += (d["p"] - (d["p"] / (1 + (d["d"] / 100)))) * v["q"]
            day_col, tot_col = ("#4caf50" if day_pl_sum >= 0 else "#ff4b4b"), ("#4caf50" if (total_val - total_cost) >= 0 else "#ff4b4b")
            day_pct = (day_pl_sum / (total_val - day_pl_sum) * 100) if (total_val - day_pl_sum) > 0 else 0
            tot_pct = ((total_val - total_cost) / total_cost * 100) if total_cost > 0 else 0
            st.markdown(f"""<div style="background-color:white; border-radius:12px; padding:15px; box-shadow:0 4px 10px rgba(0,0,0,0.05); border:1px solid #f0f0f0; margin-bottom:20px;"><div style="display:flex; justify-content:space-between; margin-bottom:10px;"><div><div style="font-size:11px; color:#888; font-weight:bold;">NET ASSETS</div><div style="font-size:24px; font-weight:900; color:#333;">${total_val:,.2f}</div></div><div style="text-align:right;"><div style="font-size:11px; color:#888; font-weight:bold;">INVESTED</div><div style="font-size:24px; font-weight:900; color:#555;">${total_cost:,.2f}</div></div></div><div style="height:1px; background:#eee; margin:10px 0;"></div><div style="display:flex; justify-content:space-between;"><div><div style="font-size:11px; color:#888; font-weight:bold;">DAY P/L</div><div style="font-size:16px; font-weight:bold; color:{day_col};">${day_pl_sum:+,.2f} ({day_pct:+.2f}%)</div></div><div style="text-align:right;"><div style="font-size:11px; color:#888; font-weight:bold;">TOTAL P/L</div><div style="font-size:16px; font-weight:bold; color:{tot_col};">${total_val - total_cost:+,.2f} ({tot_pct:+.2f}%)</div></div></div></div>""", unsafe_allow_html=True)
            cols = st.columns(3)
            for i, (k, v) in enumerate(port.items()):
                with cols[i % 3]: draw(k, v)
    with t3:
        c_head, c_btn = st.columns([4, 1]); c_head.subheader("Portfolio News")
        if c_btn.button("🔄 Refresh", key="btn_n1"):
            with st.spinner("Analyzing market news..."): fetch_news.clear(); fetch_news([], list(set([x.strip().upper() for x in USER.get("w_input", "").split(",") if x.strip()] + list(GLOBAL.get("portfolio", {}).keys()))), ACTIVE_KEY); st.rerun()
        if not NEWS_LIB_READY: st.error("Missing Libraries.")
        else:
            combined = list(set([x.strip().upper() for x in USER.get("w_input", "").split(",") if x.strip()] + list(GLOBAL.get("portfolio", {}).keys())))
            news_items = fetch_news([], combined, ACTIVE_KEY)
            if not news_items: st.info("No news for your tickers.")
            else:
                for n in news_items: render_news(n)
    with t4:
        c_head, c_btn = st.columns([4, 1]); c_head.subheader("Market Discovery")
        if c_btn.button("🔄 Refresh", key="btn_n2"):
            with st.spinner("Analyzing market news..."): fetch_news.clear(); fetch_news(GLOBAL.get("rss_feeds", ["https://finance.yahoo.com/news/rssindex"]), [], ACTIVE_KEY); st.rerun()
        if not NEWS_LIB_READY: st.error("Missing Libraries.")
        else:
            news_items = fetch_news(GLOBAL.get("rss_feeds", ["https://finance.yahoo.com/news/rssindex"]), [], ACTIVE_KEY)
            if not news_items: st.info("No discovery news found.")
            else:
                for n in news_items: render_news(n)

    # --- SILENT REFRESH (Keep Data Fresh) ---
    time.sleep(60)
    st.rerun()
