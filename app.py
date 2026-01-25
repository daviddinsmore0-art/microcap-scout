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
        conn.commit()
        # Force-Add missing columns
        for col in ['day_high', 'day_low', 'company_name', 'pre_post_price', 'rating', 'next_earnings']:
            cursor.execute(f"SHOW COLUMNS FROM stock_cache LIKE '{col}'")
            if not cursor.fetchone():
                dtype = "DECIMAL(20, 4)" if "day" in col or "price" in col else "VARCHAR(255)"
                cursor.execute(f"ALTER TABLE stock_cache ADD COLUMN {col} {dtype}")
                conn.commit()
        conn.close()
    except Exception: pass

# --- THE FIX: BATCH ENGINE (Prevents Crashes) ---
def run_backend_update(force=False):
    """Downloads ALL stocks in 1 request to prevent Yahoo bans."""
    try:
        conn = get_connection(); cursor = conn.cursor(dictionary=True, buffered=True)
        
        # 1. Gather Tickers
        cursor.execute("SELECT user_data FROM user_profiles")
        users = cursor.fetchall()
        needed = set(["^DJI", "^IXIC", "^GSPTSE", "GC=F"]) 
        for r in users:
            try:
                data = json.loads(r['user_data'])
                if 'w_input' in data: needed.update([t.strip().upper() for t in data['w_input'].split(",") if t.strip()])
                if 'portfolio' in data: needed.update(data['portfolio'].keys())
                if 'tape_input' in data: needed.update([t.strip().upper() for t in data['tape_input'].split(",") if t.strip()])
            except: pass
        
        # 2. Filter Stale
        to_fetch = []
        if force: to_fetch = list(needed)
        else:
            format_strings = ','.join(['%s'] * len(needed))
            cursor.execute(f"SELECT ticker, last_updated FROM stock_cache WHERE ticker IN ({format_strings})", tuple(needed))
            existing = {row['ticker']: row['last_updated'] for row in cursor.fetchall()}
            now = datetime.now()
            for t in needed:
                last = existing.get(t)
                if not last or (now - last).total_seconds() > 300: to_fetch.append(t)
        
        if not to_fetch: conn.close(); return

        # 3. BATCH DOWNLOAD (The Fix)
        tickers_str = " ".join(to_fetch)
        data = yf.download(tickers_str, period="1mo", group_by='ticker', threads=True, progress=False)
        
        # 4. PROCESS
        for t in to_fetch:
            try:
                if len(to_fetch) == 1: df = data
                else: 
                    if t not in data.columns.levels[0]: continue 
                    df = data[t]
                
                df = df.dropna(subset=['Close'])
                if df.empty: continue

                curr = float(df['Close'].iloc[-1])
                prev = float(df['Close'].iloc[-2]) if len(df) > 1 else curr
                change = ((curr - prev) / prev) * 100
                trend = "UPTREND" if curr > df['Close'].tail(20).mean() else "DOWNTREND"
                
                # Day Range (High/Low)
                day_h = float(df['High'].iloc[-1])
                day_l = float(df['Low'].iloc[-1])

                # RSI
                rsi_val = 50.0
                try:
                    delta = df['Close'].diff()
                    g = delta.where(delta > 0, 0).rolling(14).mean()
                    l = (-delta.where(delta < 0, 0)).rolling(14).mean()
                    if not l.empty and l.iloc[-1] != 0: rsi_val = 100 - (100 / (1 + (g.iloc[-1]/l.iloc[-1])))
                except: pass
                
                # Volume
                vol_stat = "NORMAL"
                if not df['Volume'].empty:
                    v_avg = df['Volume'].mean()
                    if v_avg > 0:
                        v_curr = df['Volume'].iloc[-1]
                        if v_curr > v_avg * 1.5: vol_stat = "HEAVY"
                        elif v_curr < v_avg * 0.5: vol_stat = "LIGHT"
                
                # Metadata (Lazy Defaults)
                rating = "N/A"; earn = "N/A"; comp_name = t
                pp_p = 0.0; pp_pct = 0.0

                chart_json = json.dumps(df['Close'].tail(20).tolist())
                
                sql = """
                INSERT INTO stock_cache (ticker, current_price, day_change, rsi, volume_status, trend_status, price_history, day_high, day_low, last_updated)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON DUPLICATE KEY UPDATE 
                current_price=%s, day_change=%s, rsi=%s, volume_status=%s, trend_status=%s, price_history=%s, day_high=%s, day_low=%s, last_updated=NOW()
                """
                v = (t, curr, change, rsi_val, vol_stat, trend, chart_json, day_h, day_l,
                     curr, change, rsi_val, vol_stat, trend, chart_json, day_h, day_l)
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
    for _ in range(3):
        try:
            conn = get_connection(); cursor = conn.cursor(buffered=True)
            cursor.execute("SELECT username FROM user_sessions WHERE token = %s", (token,))
            res = cursor.fetchone(); conn.close()
            if res: return res[0]
        except: time.sleep(0.5)
    return None

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
        return json.loads(res[0]) if res else {"portfolio": {}, "rss_feeds": ["https://finance.yahoo.com/news/rssindex"], "tape_input": "^DJI, ^IXIC, ^GSPTSE, GC=F"}
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

# --- NEWS ENGINE ---
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
        
        # PRE/POST LOGIC
        pp_html = ""
        if row.get('pre_post_price') and float(row['pre_post_price']) > 0:
             pp_p = float(row['pre_post_price']); pp_c = float(row['pre_post_pct'])
             if abs(pp_p - price) > 0.01:
                 col = "#4caf50" if pp_c >= 0 else "#ff4b4b"
                 pp_html = f"<div style='font-size:11px; color:#888; margin-top:-2px;'>POST: <span style='color:{col}; font-weight:bold;'>${pp_p:,.2f} ({pp_c:+.2f}%)</span></div>"

        # DAY RANGE LOGIC
        day_h = float(row.get('day_high') or price)
        day_l = float(row.get('day_low') or price)
        range_pos = 50
        if day_h > day_l:
            range_pos = ((price - day_l) / (day_h - day_l)) * 100
            range_pos = max(0, min(100, range_pos))

        vol_pct = 150 if vol_stat == "HEAVY" else (50 if vol_stat == "LIGHT" else 100)
        raw_hist = row.get('price_history')
        points = json.loads(raw_hist) if raw_hist else [price]*20
        chart_data = pd.DataFrame({'Idx': range(len(points)), 'Stock': points})
        base = chart_data['Stock'].iloc[0] if chart_data['Stock'].iloc[0]!=0 else 1
        chart_data['Stock'] = ((chart_data['Stock'] - base) / base) * 100
        
        return {
            "p": price, "d": change, "name": display_name, "rsi": rsi_val, "vol_pct": vol_pct, "range_pos": range_pos, "h": day_h, "l": day_l,
            "ai": "BULLISH" if trend == "UPTREND" else "BEARISH", "trend": trend, "pp": pp_html, "chart": chart_data,
            "rating": rating, "earn": earn, "vol_stat": vol_stat
        }
    except: return None

@st.cache_data(ttl=60)
def get_tape_data(symbol_string, nickname_string=""):
    items = []
    symbols = [x.strip().upper() for x in symbol_string.split(",") if x.strip()]
    nick_map = {}
    if nickname_string:
        try:
            for p in nickname_string.split(","):
                if ":" in p: k, v = p.split(":"); nick_map[k.strip().upper()] = v.strip().upper()
        except: pass

    try:
        conn = get_connection(); cursor = conn.cursor(dictionary=True)
        format_strings = ','.join(['%s'] * len(symbols))
        cursor.execute(f"SELECT * FROM stock_cache WHERE ticker IN ({format_strings})", tuple(symbols))
        rows = cursor.fetchall(); conn.close()
        for r in rows:
            px, chg = float(r['current_price']), float(r['day_change'])
            disp_name = nick_map.get(r['ticker'], r.get('company_name') or r['ticker'])
            if len(disp_name) > 15: disp_name = disp_name[:15].strip() + ".."
            col, arrow = ("#4caf50", "▲") if chg >= 0 else ("#ff4b4b", "▼")
            items.append(f"<span style='color:#ccc; margin-left:20px;'>{disp_name}</span> <span style='color:{col}'>{arrow} {px:,.2f} ({chg:+.2f}%)</span>")
    except: pass
    return "   ".join(items)

# --- UI LOGIC ---
check_and_fix_schema()
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
.tag { font-size: 9px; padding: 1px 5px; border-radius: 3px; font-weight: bold; color: white; float: right; margin-top: -16px; }
.info-pill { font-size: 10px; color: #333; background: #f8f9fa; padding: 3px 8px; border-radius: 4px; font-weight: 600; margin-right: 6px; display: inline-block; border: 1px solid #eee; border-left-width: 3px; border-left-style: solid; }
.news-card { padding: 8px 0 8px 15px; margin-bottom: 15px; border-left: 6px solid #ccc; background-color: #fff; }
.ticker-badge { font-size: 9px; padding: 2px 5px; border-radius: 3px; color: white; font-weight: bold; margin-right: 6px; display: inline-block; vertical-align: middle; }
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
        
        with st.expander("📰 News"):
             if st.text_input("Auth", type="password") == ADMIN_PASSWORD:
                 feed = st.text_input("Feed URL")
                 if st.button("Add Feed"): GLOBAL['rss_feeds'].append(feed); save_global_config(GLOBAL)

        if st.button("Logout"): logout_session(st.query_params.get("token")); st.query_params.clear(); st.session_state["logged_in"] = False; st.rerun()

    t1, t2, t3, t4 = st.tabs(["📊 Live", "🚀 Port", "📰 News", "🌎 Disc"])

    def draw(t, port=None):
        d = get_pro_data(t)
        if not d: st.caption(f"Waiting for {t}..."); return
        
        b_col = "#4caf50" if d['d'] >= 0 else "#ff4b4b"
        ai_col = "#4caf50" if d["ai"] == "BULLISH" else "#ff4b4b"
        tr_col = "#4caf50" if d["trend"] == "UPTREND" else "#ff4b4b"
        
        # --- HEADER (RESTORED) ---
        st.markdown(f"""<div style='display:flex; justify-content:space-between; align-items:flex-start;'><div><div style='font-size:22px; font-weight:bold;'>{t}</div><div style='font-size:12px; color:#888;'>{d['name'][:25]}</div></div><div style='text-align:right;'><div style='font-size:22px; font-weight:bold;'>${d['p']:,.2f}</div><div style='color:{b_col}; font-weight:bold; font-size:14px;'>{d['d']:+.2f}%</div>{d['pp']}</div></div>""", unsafe_allow_html=True)
        
        # --- PILLS (TOP) ---
        pills = f"<span class='info-pill' style='border-left-color:{ai_col}'>AI: {d['ai']}</span><span class='info-pill' style='border-left-color:{tr_col}'>{d['trend']}</span>"
        if d['earn'] != "N/A": pills += f"<span class='info-pill' style='border-left-color:#333'>EARN: {d['earn']}</span>"
        st.markdown(f"<div style='margin:8px 0;'>{pills}</div>", unsafe_allow_html=True)

        # --- CHART ---
        chart = alt.Chart(d["chart"]).mark_area(line={'color':b_col}, color=alt.Gradient(gradient='linear', stops=[alt.GradientStop(color=b_col, offset=0), alt.GradientStop(color='white', offset=1)], x1=1, x2=1, y1=1, y2=0)).encode(x=alt.X('Idx', axis=None), y=alt.Y('Stock', axis=None)).properties(height=50)
        st.altair_chart(chart, use_container_width=True)
        
        # --- DAY RANGE (RESTORED) ---
        st.markdown(f"""<div class="metric-label"><span>Day Range</span><span style="color:#555">${d['l']:,.2f} - ${d['h']:,.2f}</span></div><div class="bar-bg"><div class="bar-fill" style="width:{d['range_pos']}%; background: linear-gradient(90deg, #ff4b4b, #f1c40f, #4caf50);"></div></div>""", unsafe_allow_html=True)
        
        # --- RSI (RESTORED) ---
        rsi, rsi_bg = d['rsi'], "#ff4b4b" if d['rsi'] > 70 else "#4caf50" if d['rsi'] < 30 else "#999"
        st.markdown(f"""<div class='metric-label'><span>RSI ({int(rsi)})</span></div><span class='tag' style='background:{rsi_bg}'>{"HOT" if rsi>70 else "COLD" if rsi<30 else "NEUTRAL"}</span><div class='bar-bg' style='margin-top:2px'><div class='bar-fill' style='width:{rsi}%; background:{rsi_bg};'></div></div>""", unsafe_allow_html=True)
        
        # --- VOLUME (RESTORED) ---
        vol_tag = "HEAVY" if d['vol_stat']=="HEAVY" else "LIGHT" if d['vol_stat']=="LIGHT" else "NORMAL"
        st.markdown(f"<div class='metric-label'><span>VOLUME ({int(d['vol_pct'])}%)</span></div><span class='tag' style='background:#3498db; color:white'>{vol_tag}</span><div class='bar-bg' style='margin-top:2px'><div class='bar-fill' style='width:{min(d['vol_pct'], 100)}%; background:#3498db;'></div></div>", unsafe_allow_html=True)
        
        if port:
            g = (d['p'] - port['e']) * port['q']
            st.markdown(f"<div style='font-size:12px; margin-top:10px; background:#f9f9f9; padding:5px; border-radius:5px;'>Qty: {port['q']} | Avg: ${port['e']} | <b style='color:{'#4caf50' if g>=0 else '#ff4b4b'}'>${g:+,.2f}</b></div>", unsafe_allow_html=True)
        st.divider()

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
        for n in news: render_news(n)

    with t4:
        st.info("Market Discovery (AI Curated) Coming Soon")

    time.sleep(60); st.rerun()
