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
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
        """)
        conn.close()
        return True
    except Error: return False

# --- DUAL-BATCH ENGINE (The Fix) ---
def run_backend_update(force=False):
    """
    1. Fetches LIVE 1m data (for BTC/Pre-Market).
    2. Fetches HISTORY 1d data (for Charts/RSI).
    """
    try:
        conn = get_connection(); cursor = conn.cursor(dictionary=True, buffered=True)
        
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

        # 2. Check Stale
        to_fetch = []
        if force: to_fetch = list(all_tickers)
        else:
            format_strings = ','.join(['%s'] * len(all_tickers))
            cursor.execute(f"SELECT ticker, last_updated FROM stock_cache WHERE ticker IN ({format_strings})", tuple(all_tickers))
            existing = {row['ticker']: row['last_updated'] for row in cursor.fetchall()}
            now = datetime.now()
            for t in all_tickers:
                last = existing.get(t)
                # Fetch if older than 2 minutes (Aggressive for BTC)
                if not last or (now - last).total_seconds() > 120:
                    to_fetch.append(t)
        
        if not to_fetch: conn.close(); return

        tickers_str = " ".join(to_fetch)
        
        # 3. DUAL DOWNLOAD
        # Batch A: LIVE Data (1 minute interval, Pre/Post enabled) -> Fixes BTC & Extended Hours
        live_data = yf.download(tickers_str, period="5d", interval="1m", prepost=True, group_by='ticker', threads=True, progress=False)
        
        # Batch B: HISTORY Data (1 month, Daily) -> Fixes Sparklines & RSI
        hist_data = yf.download(tickers_str, period="1mo", interval="1d", group_by='ticker', threads=True, progress=False)

        # 4. PROCESS & MERGE
        for t in to_fetch:
            try:
                # --- PROCESS LIVE DATA (Batch A) ---
                if len(to_fetch) == 1: df_live = live_data
                else: 
                    if t not in live_data.columns.levels[0]: continue
                    df_live = live_data[t]
                
                df_live = df_live.dropna(subset=['Close'])
                if df_live.empty: continue

                curr_price = float(df_live['Close'].iloc[-1])
                
                # Pre/Post Logic
                pp_p, pp_pct = 0.0, 0.0
                last_time = df_live.index[-1]
                # If last timestamp is recent but market is closed, it's pre/post
                # Simple check: Is the last price different from the "regular" close?
                # We'll calculate "Change" based on yesterday's close from Batch B to be safe
                
                # --- PROCESS HISTORY DATA (Batch B) ---
                if len(to_fetch) == 1: df_hist = hist_data
                else:
                    if t in hist_data.columns.levels[0]: df_hist = hist_data[t]
                    else: df_hist = pd.DataFrame() # Fallback
                
                chart_json = "[]"
                day_change = 0.0
                rsi = 50.0
                vol_stat = "NORMAL"
                trend = "NEUTRAL"

                if not df_hist.empty:
                    df_hist = df_hist.dropna(subset=['Close'])
                    # Calculate change based on PREVIOUS DAY close vs LIVE CURRENT price
                    if len(df_hist) > 0:
                        prev_close = float(df_hist['Close'].iloc[-1])
                        # If live data is significantly newer (today) vs history (yesterday), use prev_close
                        if df_live.index[-1].date() > df_hist.index[-1].date():
                            day_change = ((curr_price - prev_close) / prev_close) * 100
                        else:
                            # Intraday
                            if len(df_hist) > 1:
                                prev_close = float(df_hist['Close'].iloc[-2])
                                day_change = ((curr_price - prev_close) / prev_close) * 100
                    
                    # Trend
                    trend = "UPTREND" if curr_price > df_hist['Close'].tail(20).mean() else "DOWNTREND"
                    
                    # RSI
                    try:
                        delta = df_hist['Close'].diff()
                        g = delta.where(delta > 0, 0).rolling(14).mean()
                        l = (-delta.where(delta < 0, 0)).rolling(14).mean()
                        if not l.empty and l.iloc[-1] != 0:
                            rsi = 100 - (100 / (1 + (g.iloc[-1]/l.iloc[-1])))
                    except: pass

                    # Volume
                    if not df_hist['Volume'].empty:
                        v_avg = df_hist['Volume'].mean()
                        if v_avg > 0:
                            v_curr = df_hist['Volume'].iloc[-1]
                            if v_curr > v_avg * 1.5: vol_stat = "HEAVY"
                            elif v_curr < v_avg * 0.5: vol_stat = "LIGHT"

                    chart_json = json.dumps(df_hist['Close'].tail(20).tolist())

                # Pre/Post Detection
                # If "Live" price is different from "Daily" close by > 1% and it's outside hours
                # Simple logic: If we have live data, use it.
                if len(df_live) > 0:
                    pp_p = curr_price # Live is always the "current"
                    # If market is closed, `curr_price` IS the pre/post price.
                    # We store it in `pre_post_price` to show the badge.
                    pp_pct = day_change # Sync percent

                sql = """
                INSERT INTO stock_cache (ticker, current_price, day_change, rsi, volume_status, trend_status, price_history, pre_post_price, pre_post_pct, last_updated)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON DUPLICATE KEY UPDATE 
                current_price=%s, day_change=%s, rsi=%s, volume_status=%s, trend_status=%s, price_history=%s, pre_post_price=%s, pre_post_pct=%s, last_updated=NOW()
                """
                v = (t, curr_price, day_change, rsi, vol_stat, trend, chart_json, pp_p, pp_pct,
                     curr_price, day_change, rsi, vol_stat, trend, chart_json, pp_p, pp_pct)
                cursor.execute(sql, v)
                
            except: pass
        
        conn.commit(); conn.close()
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

def logout_session(token):
    try:
        conn = get_connection(); cursor = conn.cursor(buffered=True)
        cursor.execute("DELETE FROM user_sessions WHERE token = %s", (token,))
        conn.commit(); conn.close()
    except: pass

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

def save_global_config(data):
    try:
        conn = get_connection(); cursor = conn.cursor(buffered=True); j_str = json.dumps(data)
        cursor.execute("INSERT INTO user_profiles (username, user_data) VALUES ('GLOBAL_CONFIG', %s) ON DUPLICATE KEY UPDATE user_data = %s", (j_str, j_str))
        conn.commit(); conn.close()
    except: pass

def get_global_config_data():
    api_key = None; rss_feeds = ["https://finance.yahoo.com/news/rssindex"]
    try: api_key = st.secrets.get("OPENAI_KEY")
    except: pass
    g = load_global_config()
    if not api_key: api_key = g.get("openai_key")
    if g.get("rss_feeds"): rss_feeds = g.get("rss_feeds")
    return api_key, rss_feeds, g

# --- NEWS & AI ---
def relative_time(date_str):
    try:
        dt = datetime.strptime(date_str, "%a, %d %b %Y %H:%M:%S %z")
        diff = datetime.now(timezone.utc) - dt
        return f"{int(diff.total_seconds()//60)}m ago" if diff.total_seconds()<3600 else f"{int(diff.total_seconds()//3600)}h ago"
    except: return "Recent"

@st.cache_data(ttl=600)
def fetch_news(feeds, tickers, api_key):
    if not NEWS_LIB_READY: return []
    all_feeds = feeds.copy()
    if tickers:
        for t in tickers: all_feeds.append(f"https://finance.yahoo.com/rss/headline?s={t}")
    articles = []; seen = set()
    for url in all_feeds:
        try:
            f = feedparser.parse(url)
            for entry in f.entries[:5]:
                if entry.link not in seen:
                    seen.add(entry.link)
                    articles.append({"title": entry.title, "link": entry.link, "published": relative_time(entry.get("published",""))})
        except: pass
    return articles

# --- DATA HELPERS ---
@st.cache_data(ttl=5)
def get_pro_data(s):
    try:
        conn = get_connection(); cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM stock_cache WHERE ticker = %s", (s,))
        row = cursor.fetchone(); conn.close()
        if not row: return None
        
        price = float(row['current_price'])
        change = float(row['day_change'])
        rsi_val = float(row['rsi'])
        trend = row['trend_status']
        vol_stat = row['volume_status']
        display_name = row.get('company_name') or s
        rating = row.get('rating') or "N/A"
        earn = row.get('next_earnings') or "N/A"
        
        pp_html = ""
        # Check Pre/Post (Using the new Dual-Batch Logic)
        # If today is Saturday/Sunday, or time is outside 9:30-16:00, show EXT tag
        # Simple Logic: If change is 0.00 but price moves, its post market.
        # But we saved pre_post_price in the DB now.
        if row.get('pre_post_price') and float(row['pre_post_price']) > 0:
             pp_p = float(row['pre_post_price'])
             # If price in chart (history) != current price (live batch), show EXT
             if abs(pp_p - price) < 0.01: # They are same, meaning market is closed or using live
                 pass 
             else:
                 # Calculate diff
                 diff_pct = ((pp_p - price) / price) * 100
                 col = "#4caf50" if diff_pct >= 0 else "#ff4b4b"
                 pp_html = f"<div style='font-size:11px; color:#888;'>EXT: <span style='color:{col}; font-weight:bold;'>${pp_p:,.2f} ({diff_pct:+.2f}%)</span></div>"

        vol_pct = 150 if vol_stat == "HEAVY" else (50 if vol_stat == "LIGHT" else 100)
        raw_hist = row.get('price_history')
        points = json.loads(raw_hist) if raw_hist else [price]*20
        chart_data = pd.DataFrame({'Idx': range(len(points)), 'Stock': points})
        base = chart_data['Stock'].iloc[0] if chart_data['Stock'].iloc[0]!=0 else 1
        chart_data['Stock'] = ((chart_data['Stock'] - base) / base) * 100
        
        return {
            "p": price, "d": change, "name": display_name, "rsi": rsi_val, "vol_pct": vol_pct, "range_pos": 50, "h": price, "l": price,
            "ai": "BULLISH" if trend == "UPTREND" else "BEARISH", "trend": trend, "pp": pp_html, "chart": chart_data,
            "rating": rating, "earn": earn
        }
    except: return None

@st.cache_data(ttl=60)
def get_tape_data(symbol_string, nickname_string=""):
    items = []
    symbols = [x.strip().upper() for x in symbol_string.split(",") if x.strip()]
    try:
        conn = get_connection(); cursor = conn.cursor(dictionary=True)
        format_strings = ','.join(['%s'] * len(symbols))
        cursor.execute(f"SELECT * FROM stock_cache WHERE ticker IN ({format_strings})", tuple(symbols))
        rows = cursor.fetchall(); conn.close()
        for r in rows:
            px, chg = float(r['current_price']), float(r['day_change'])
            col, arrow = ("#4caf50", "▲") if chg >= 0 else ("#ff4b4b", "▼")
            items.append(f"<span style='color:#ccc; margin-left:20px;'>{r['ticker']}</span> <span style='color:{col}'>{arrow} {px:,.2f} ({chg:+.2f}%)</span>")
    except: pass
    return "   ".join(items)

# --- UI START ---
init_db()
run_backend_update()

if "init" not in st.session_state:
    st.session_state["init"] = True; st.session_state["logged_in"] = False
    if st.query_params.get("token"):
        u = validate_session(st.query_params.get("token"))
        if u: st.session_state["username"]=u; st.session_state["user_data"]=load_user_profile(u); st.session_state["global_data"]=load_global_config(); st.session_state["logged_in"]=True

st.markdown("""<style>
.block-container { padding-top: 2rem !important; }
div[data-testid="stVerticalBlock"] { background-color: #ffffff; border-radius: 12px; padding: 15px; box-shadow: 0 4px 10px rgba(0,0,0,0.05); border: 1px solid #f0f0f0; margin-bottom: 10px; }
.metric-label { font-size: 10px; color: #888; font-weight: 600; display: flex; justify-content: space-between; margin-top: 8px; text-transform: uppercase; }
.bar-bg { background: #eee; height: 5px; border-radius: 3px; width: 100%; margin-top: 3px; overflow: hidden; }
.bar-fill { height: 100%; border-radius: 3px; }
.info-pill { font-size: 10px; color: #333; background: #f8f9fa; padding: 3px 8px; border-radius: 4px; font-weight: 600; margin-right: 6px; display: inline-block; border: 1px solid #eee; }
.news-card { padding: 8px 0 8px 15px; margin-bottom: 15px; border-left: 6px solid #ccc; background-color: #fff; }
</style>""", unsafe_allow_html=True)

if not st.session_state["logged_in"]:
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        st.markdown("<h1 style='text-align:center;'>⚡ Penny Pulse</h1>", unsafe_allow_html=True)
        with st.form("login"):
            user = st.text_input("Username").strip()
            pin = st.text_input("PIN", type="password")
            if st.form_submit_button("Login"):
                exists, stored_pin = check_user_exists(user)
                if exists and str(stored_pin) == str(pin):
                    st.session_state["username"] = user; st.session_state["logged_in"] = True
                    st.query_params["token"] = create_session(user); st.rerun()
                elif not exists:
                    save_user_profile(user, {"w_input": "TD.TO, SPY"}, pin)
                    st.session_state["username"] = user; st.session_state["logged_in"] = True
                    st.query_params["token"] = create_session(user); st.rerun()
else:
    USER_NAME = st.session_state["username"]
    USER_DATA = load_user_profile(USER_NAME)
    GLOBAL = load_global_config()
    ACTIVE_KEY, _, _ = get_global_config_data()

    # Tape
    tape = get_tape_data(GLOBAL.get("tape_input", "^DJI, ^IXIC, ^GSPTSE, GC=F"), GLOBAL.get("tape_nicknames", ""))
    components.html(f'<marquee style="background:#111; color:white; padding:10px; font-weight:bold;">{tape}</marquee>', height=45)

    with st.sidebar:
        st.title(f"Hi, {USER_NAME}!")
        if st.button("⚡ Force Update"): run_backend_update(force=True); st.rerun()
        new_w = st.text_area("Watchlist", value=USER_DATA.get("w_input", ""))
        if new_w != USER_DATA.get("w_input"): USER_DATA["w_input"] = new_w; save_user_profile(USER_NAME, USER_DATA); st.rerun()
        
        with st.expander("🔔 Alerts"):
            tg = st.text_input("Telegram ID", value=USER_DATA.get("telegram_id", ""))
            if tg != USER_DATA.get("telegram_id", ""): USER_DATA["telegram_id"] = tg; save_user_profile(USER_NAME, USER_DATA)
        
        with st.expander("🔐 Admin"):
            if st.text_input("Pass", type="password") == ADMIN_PASSWORD:
                if st.button("Save Global Tape"): save_global_config(GLOBAL)
        
        if st.button("Logout"): logout_session(st.query_params.get("token")); st.query_params.clear(); st.session_state["logged_in"] = False; st.rerun()

    t1, t2, t3, t4 = st.tabs(["📊 Live", "🚀 Port", "📰 News", "🌎 Disc"])

    def draw(t, port=None):
        d = get_pro_data(t)
        if not d: st.caption(f"Waiting for {t}..."); return
        
        b_col = "#4caf50" if d['d'] >= 0 else "#ff4b4b"
        st.markdown(f"""<div style='display:flex; justify-content:space-between;'><div><div style='font-size:20px; font-weight:bold;'>{t}</div><div style='font-size:12px; color:#888;'>{d['name'][:20]}</div></div><div style='text-align:right;'><div style='font-size:20px; font-weight:bold;'>${d['p']:,.2f}</div><div style='color:{b_col};'>{d['d']:+.2f}%</div></div></div>""", unsafe_allow_html=True)
        if d['pp']: st.markdown(d['pp'], unsafe_allow_html=True)
        
        chart = alt.Chart(d["chart"]).mark_area(line={'color':b_col}, color=alt.Gradient(gradient='linear', stops=[alt.GradientStop(color=b_col, offset=0), alt.GradientStop(color='white', offset=1)], x1=1, x2=1, y1=1, y2=0)).encode(x=alt.X('Idx', axis=None), y=alt.Y('Stock', axis=None)).properties(height=50)
        st.altair_chart(chart, use_container_width=True)
        
        st.markdown(f"<span class='info-pill'>AI: {d['ai']}</span> <span class='info-pill'>RSI: {int(d['rsi'])}</span> <span class='info-pill'>RATE: {d['rating']}</span>", unsafe_allow_html=True)
        st.markdown(f"<div class='metric-label'><span>RSI</span></div><div class='bar-bg'><div class='bar-fill' style='width:{d['rsi']}%; background:{b_col};'></div></div>", unsafe_allow_html=True)
        st.markdown(f"<div class='metric-label'><span>VOL</span></div><div class='bar-bg'><div class='bar-fill' style='width:{min(d['vol_pct'], 100)}%; background:#3498db;'></div></div>", unsafe_allow_html=True)
        
        if port:
            g = (d['p'] - port['e']) * port['q']
            st.markdown(f"<div style='font-size:12px; margin-top:5px; background:#f9f9f9; padding:5px;'>Qty: {port['q']} | Avg: ${port['e']} | <b style='color:{'#4caf50' if g>=0 else '#ff4b4b'}'>${g:+,.2f}</b></div>", unsafe_allow_html=True)

    with t1:
        tickers = [x.strip().upper() for x in USER_DATA.get("w_input", "").split(",") if x.strip()]
        cols = st.columns(3)
        for i, t in enumerate(tickers):
            with cols[i%3]: draw(t)

    with t2:
        port = GLOBAL.get("portfolio", {})
        if not port: st.info("No picks.")
        else:
            tot = sum([get_pro_data(k)['p']*v['q'] for k,v in port.items() if get_pro_data(k)])
            cost = sum([v['e']*v['q'] for k,v in port.items()])
            st.metric("Net Assets", f"${tot:,.2f}", f"{tot-cost:+,.2f}")
            cols = st.columns(3)
            for i, (k,v) in enumerate(port.items()):
                with cols[i%3]: draw(k, v)

    with t3:
        if st.button("Refresh News"): fetch_news.clear(); st.rerun()
        news = fetch_news([], [x.strip() for x in USER_DATA.get("w_input", "").split(",")], ACTIVE_KEY)
        for n in news: st.markdown(f"**[{n['title']}]({n['link']})** - {n['published']}")

    with t4:
        st.info("Market Discovery (AI Curated) Coming Soon")

    time.sleep(60); st.rerun()
