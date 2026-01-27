import streamlit as st
import pandas as pd
import altair as alt
import time
import json
import mysql.connector
import requests
import yfinance as yf
# Using generic Exception to strictly prevent NameError/ImportError crashes
from datetime import datetime, timedelta, timezone
import streamlit.components.v1 as components
import os
import uuid
import re
import numpy as np

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

# *** DATABASE CONFIG (MASTER KEY) ***
DB_CONFIG = {
    "host": "atlanticcanadaschoice.com",
    "user": "atlantic",                 
    "password": "1q2w3e4R!!",   # <--- PASTE PASSWORD HERE
    "database": "atlantic_pennypulse",    
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
        # Morning Briefing Persistent Table
        cursor.execute("CREATE TABLE IF NOT EXISTS daily_briefing (date DATE PRIMARY KEY, picks JSON, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        
        # Auto-patch missing columns
        for col in ['day_high', 'day_low', 'company_name', 'pre_post_price', 'rating', 'next_earnings']:
            try:
                dtype = "DECIMAL(20,4)" if "day" in col or "price" in col else "VARCHAR(255)"
                cursor.execute(f"ALTER TABLE stock_cache ADD COLUMN {col} {dtype}")
            except: pass
        conn.close()
        return True
    except Exception:
        return False

# --- DATA HELPERS ---
@st.cache_data(ttl=600)
def get_fundamentals(s):
    try:
        conn = get_connection(); cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT rating, next_earnings FROM stock_cache WHERE ticker = %s", (s,))
        row = cursor.fetchone(); conn.close()
        return {"rating": row['rating'] or "N/A", "earn": row['next_earnings'] or "N/A"} if row else {"rating": "N/A", "earn": "N/A"}
    except: return {"rating": "N/A", "earn": "N/A"}

# --- MORNING BRIEFING ENGINE (AST OPTIMIZED + ATR FIX) ---
def run_morning_briefing(api_key):
    try:
        now = datetime.now() # Server time is AST
        if now.weekday() > 4: return 
        today_str = now.strftime('%Y-%m-%d')
        conn = get_connection(); cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT picks FROM daily_briefing WHERE date = %s", (today_str,))
        result = cursor.fetchone()
        
        # 9:45 AM AST trigger (8:45 AM EST)
        if not result and 9 <= now.hour <= 10 and 45 <= now.minute <= 59:
            fh_key = st.secrets.get("FINNHUB_API_KEY")
            movers = ["NVDA", "TSLA", "AMD", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "NFLX", "COIN", "MARA", "PLTR", "SOFI", "LCID", "RIVN", "GME", "AMC", "MSTR", "MULN"]
            candidates = []
            for t in movers:
                try:
                    r = requests.get(f"https://finnhub.io/api/v1/quote?symbol={t}&token={fh_key}", timeout=5).json()
                    if 'c' in r and r['c'] != 0:
                        gap = ((float(r['c']) - float(r['pc'])) / float(r['pc'])) * 100
                        if abs(gap) >= 1.0:
                            # ATR Calculation Patch
                            hist = yf.download(t, period="14d", interval="1d", progress=False)
                            atr = 0.0
                            if not hist.empty:
                                high_low = hist['High'] - hist['Low']
                                atr = float(high_low.mean())
                            candidates.append({"ticker": t, "gap": gap, "price": r['c'], "atr": atr})
                except: continue
            
            candidates.sort(key=lambda x: abs(x['gap']), reverse=True)
            top_5 = candidates[:5]
            if api_key and top_5:
                client = openai.OpenAI(api_key=api_key)
                prompt = f"Analyze for momentum trade: {str(top_5)}. Return JSON: {{'picks': ['TICKER', 'TICKER', 'TICKER']}}."
                resp = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"})
                picks_json = json.loads(resp.choices[0].message.content)
                picked_tickers = picks_json.get("picks", [])
                final_picks = [c for c in top_5 if c['ticker'] in picked_tickers]
                if not final_picks: final_picks = top_5[:3]
                
                cursor.execute("INSERT INTO daily_briefing (date, picks) VALUES (%s, %s)", (today_str, json.dumps(final_picks)))
                conn.commit()
        conn.close()
    except: pass

# --- BACKEND UPDATE ENGINE ---
def run_backend_update():
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True, buffered=True)
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

        format_strings = ','.join(['%s'] * len(all_tickers))
        cursor.execute(f"SELECT ticker, last_updated, rating, next_earnings FROM stock_cache WHERE ticker IN ({format_strings})", tuple(all_tickers))
        existing_rows = {row['ticker']: row for row in cursor.fetchall()}
        
        to_fetch_price = []
        to_fetch_meta = []
        now = datetime.now()
        
        for t in all_tickers:
            row = existing_rows.get(t)
            if not row or not row['last_updated'] or (now - row['last_updated']).total_seconds() > 120:
                to_fetch_price.append(t)
            if not row or row.get('rating') == 'N/A' or row.get('next_earnings') == 'N/A':
                to_fetch_meta.append(t)
        
        if to_fetch_price:
            tickers_str = " ".join(to_fetch_price)
            live_data = yf.download(tickers_str, period="5d", interval="1m", prepost=True, group_by='ticker', threads=True, progress=False)
            hist_data = yf.download(tickers_str, period="1mo", interval="1d", group_by='ticker', threads=True, progress=False) 

            for t in to_fetch_price:
                try:
                    if len(to_fetch_price) == 1: df_live = live_data
                    else: 
                        if t not in live_data.columns.levels[0]: continue
                        df_live = live_data[t]
                    df_live = df_live.dropna(subset=['Close'])
                    if df_live.empty: continue
                    live_price = float(df_live['Close'].iloc[-1]) 

                    if len(to_fetch_price) == 1: df_hist = hist_data
                    else:
                        if t in hist_data.columns.levels[0]: df_hist = hist_data[t]
                        else: df_hist = pd.DataFrame()
                    
                    day_change = 0.0; rsi = 50.0; vol_stat = "NORMAL"; trend = "NEUTRAL"
                    chart_json = "[]"
                    close_price = live_price 
                    day_h = live_price; day_l = live_price 

                    if not df_hist.empty:
                        df_hist = df_hist.dropna(subset=['Close'])
                        close_price = float(df_hist['Close'].iloc[-1]) 
                        if len(df_hist) > 0:
                            day_h = float(df_hist['High'].iloc[-1])
                            day_l = float(df_hist['Low'].iloc[-1])
                            day_h = max(day_h, live_price)
                            day_l = min(day_l, live_price) 

                        if len(df_hist) > 1:
                            prev_close = float(df_hist['Close'].iloc[-2])
                            if df_live.index[-1].date() > df_hist.index[-1].date():
                                prev_close = float(df_hist['Close'].iloc[-1])
                            day_change = ((close_price - prev_close) / prev_close) * 100
                        
                        trend = "UPTREND" if close_price > df_hist['Close'].tail(20).mean() else "DOWNTREND"
                        try:
                            delta = df_hist['Close'].diff()
                            g = delta.where(delta > 0, 0).rolling(14).mean()
                            l = (-delta.where(delta < 0, 0)).rolling(14).mean()
                            if not l.empty and l.iloc[-1] != 0: rsi = 100 - (100 / (1 + (g.iloc[-1]/l.iloc[-1])))
                        except: pass 

                        if not df_hist['Volume'].empty:
                            v_avg = df_hist['Volume'].mean()
                            if v_avg > 0:
                                v_curr = df_hist['Volume'].iloc[-1]
                                if v_curr > v_avg * 1.5: vol_stat = "HEAVY"
                                elif v_curr < v_avg * 0.5: vol_stat = "LIGHT"
                        
                        chart_json = json.dumps(df_hist['Close'].tail(20).tolist()) 

                    final_price = close_price
                    pp_p = 0.0; pp_pct = 0.0
                    is_crypto = "-" in t or "=F" in t
                    if is_crypto:
                        final_price = live_price
                        if len(df_hist) > 0:
                            day_change = ((live_price - float(df_hist['Close'].iloc[-1])) / float(df_hist['Close'].iloc[-1])) * 100
                    else:
                        if abs(live_price - close_price) > 0.01:
                            pp_p = live_price
                            pp_pct = ((live_price - close_price) / close_price) * 100 

                    sql = """INSERT INTO stock_cache (ticker, current_price, day_change, rsi, volume_status, trend_status, price_history, pre_post_price, pre_post_pct, day_high, day_low, last_updated) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()) ON DUPLICATE KEY UPDATE current_price=%s, day_change=%s, rsi=%s, volume_status=%s, trend_status=%s, price_history=%s, pre_post_price=%s, pre_post_pct=%s, day_high=%s, day_low=%s, last_updated=NOW()"""
                    v = (t, final_price, day_change, rsi, vol_stat, trend, chart_json, pp_p, pp_pct, day_h, day_l, final_price, day_change, rsi, vol_stat, trend, chart_json, pp_p, pp_pct, day_h, day_l)
                    cursor.execute(sql, v)
                    conn.commit()
                except: pass 

        if to_fetch_meta:
            for t in to_fetch_meta[:3]: 
                try:
                    time.sleep(0.5) 
                    tk = yf.Ticker(t)
                    info = tk.info
                    r_val = info.get('recommendationKey', 'N/A').replace('_', ' ').upper()
                    n_val = info.get('shortName') or info.get('longName') or t
                    e_val = "N/A"
                    try:
                        cal = tk.calendar
                        dates = []
                        if isinstance(cal, dict) and 'Earnings Date' in cal: dates = cal['Earnings Date']
                        elif hasattr(cal, 'iloc'): dates = [v for v in cal.values.flatten() if isinstance(v, (datetime, pd.Timestamp))]
                        future_dates = [d for d in dates if pd.to_datetime(d).date() >= datetime.now().date()]
                        if future_dates: e_val = min(future_dates).strftime('%b %d')
                    except: pass
                    sql = "UPDATE stock_cache SET rating=%s, next_earnings=%s, company_name=%s WHERE ticker=%s"
                    cursor.execute(sql, (r_val, e_val, n_val, t))
                    conn.commit()
                except: pass
        conn.close()
    except Exception: pass 

# --- SCANNER ENGINE (FINNHUB MANUAL SCAN + ATR FIX) ---
@st.cache_data(ttl=3600)
def run_gap_scanner(user_tickers, api_key):
    fh_key = st.secrets.get("FINNHUB_API_KEY")
    candidates = []
    for t in user_tickers[:20]:
        try:
            r = requests.get(f"https://finnhub.io/api/v1/quote?symbol={t}&token={fh_key}").json()
            if 'c' in r:
                gap = ((r['c'] - r['pc']) / r['pc']) * 100
                if abs(gap) >= 1.0:
                    hist = yf.download(t, period="14d", interval="1d", progress=False)
                    atr = 0.0
                    if not hist.empty:
                        atr = float((hist['High'] - hist['Low']).mean())
                    candidates.append({"ticker": t, "gap": gap, "price": r['c'], "atr": atr})
        except: continue
    return candidates[:3]

# --- AUTH HELPERS ---
def validate_session(token):
    try:
        conn = get_connection(); cursor = conn.cursor()
        cursor.execute("SELECT username FROM user_sessions WHERE token = %s", (token,))
        res = cursor.fetchone(); conn.close()
        return res[0] if res else None
    except: return None

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

def load_user_profile(username):
    try:
        conn = get_connection(); cursor = conn.cursor()
        cursor.execute("SELECT user_data FROM user_profiles WHERE username = %s", (username,))
        res = cursor.fetchone(); conn.close()
        return json.loads(res[0]) if res else {"w_input": "TD.TO, NKE, SPY"}
    except: return {"w_input": "TD.TO, NKE, SPY"} 

def save_user_profile(username, data, pin=None):
    try:
        conn = get_connection(); cursor = conn.cursor(); j_str = json.dumps(data)
        if pin: cursor.execute("INSERT INTO user_profiles (username, user_data, pin) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE user_data=%s, pin=%s", (username, j_str, pin, j_str, pin))
        else: cursor.execute("INSERT INTO user_profiles (username, user_data) VALUES (%s, %s) ON DUPLICATE KEY UPDATE user_data=%s", (username, j_str, j_str))
        conn.commit(); conn.close()
    except: pass 

def load_global_config():
    try:
        conn = get_connection(); cursor = conn.cursor()
        cursor.execute("SELECT user_data FROM user_profiles WHERE username = 'GLOBAL_CONFIG'")
        res = cursor.fetchone(); conn.close()
        return json.loads(res[0]) if res else {"portfolio": {}, "rss_feeds": [], "tape_input": "^DJI, ^IXIC, ^GSPTSE, GC=F"}
    except: return {} 

def save_global_config(data):
    try:
        conn = get_connection(); cursor = conn.cursor(); j_str = json.dumps(data)
        cursor.execute("INSERT INTO user_profiles (username, user_data) VALUES ('GLOBAL_CONFIG', %s) ON DUPLICATE KEY UPDATE user_data=%s", (j_str, j_str))
        conn.commit(); conn.close()
    except: pass 

# --- NEWS ENGINE (SURGICAL FIX FOR BLACK BARS) ---
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
                    found_ticker, sentiment = "", "NEUTRAL"
                    if api_key:
                        try:
                            client = openai.OpenAI(api_key=api_key)
                            prompt = f"Analyze: '{entry.title}'. Return: TICKER|SENTIMENT."
                            ans = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}], max_tokens=15).choices[0].message.content.strip().upper()
                            if "|" in ans:
                                parts = ans.split("|"); found_ticker = parts[0].strip()
                                raw = parts[1].strip()
                                # Fix Mapping to match CSS keys
                                if "BULL" in raw: sentiment = "BULLISH"
                                elif "BEAR" in raw: sentiment = "BEARISH"
                                else: sentiment = "NEUTRAL"
                        except: pass
                    articles.append({"title": entry.title, "link": entry.link, "published": entry.get("published", "Recent"), "ticker": found_ticker, "sentiment": sentiment})
        except: pass
    return articles 

# --- DATA ENGINE ---
def get_batch_data(tickers_list):
    results = {}
    try:
        conn = get_connection(); cursor = conn.cursor(dictionary=True)
        format_strings = ','.join(['%s'] * len(tickers_list))
        cursor.execute(f"SELECT * FROM stock_cache WHERE ticker IN ({format_strings})", tuple(tickers_list))
        rows = cursor.fetchall(); conn.close()
        for row in rows:
            s = row['ticker']
            price, chg, rsi, trend, vol_stat = float(row['current_price']), float(row['day_change']), float(row['rsi']), row['trend_status'], row['volume_status']
            vol_pct = 150 if vol_stat == "HEAVY" else (50 if vol_stat == "LIGHT" else 100)
            day_h, day_l = float(row.get('day_high') or price), float(row.get('day_low') or price)
            range_pos = max(0, min(100, ((price - day_l) / (day_h - day_l)) * 100)) if day_h > day_l else 50
            results[s] = {"p": price, "d": chg, "name": row.get('company_name', s), "rsi": rsi, "vol_pct": vol_pct, "vol_label": vol_stat, "range_pos": range_pos, "h": day_h, "l": day_l, "ai": "BULLISH" if trend == "UPTREND" else "BEARISH", "trend": trend, "chart": pd.DataFrame({'Idx': range(20), 'Stock': json.loads(row.get('price_history', '[0]*20'))}), "pp": ""}
    except: pass
    return results

# --- UI LOGIC ---
init_db()
ACTIVE_KEY = st.secrets.get("OPENAI_KEY") or st.secrets.get("OPENAI_API_KEY")
run_backend_update()
run_morning_briefing(ACTIVE_KEY)

if "init" not in st.session_state:
    st.session_state["init"] = True; st.session_state["logged_in"] = False
    url_token = st.query_params.get("token")
    if url_token:
        user = validate_session(url_token)
        if user: st.session_state["username"] = user; st.session_state["user_data"] = load_user_profile(user); st.session_state["global_data"] = load_global_config(); st.session_state["logged_in"] = True

st.markdown("""<style>
.metric-label { font-size: 10px; color: #888; font-weight: 600; display: flex; justify-content: space-between; margin-top: 8px; text-transform: uppercase; }
.bar-bg { background: #eee; height: 5px; border-radius: 3px; width: 100%; margin-top: 3px; overflow: hidden; }
.bar-fill { height: 100%; border-radius: 3px; }
.tag { font-size: 9px; padding: 1px 5px; border-radius: 3px; font-weight: bold; color: white; }
.info-pill { font-size: 10px; color: #333; background: #f8f9fa; padding: 3px 8px; border-radius: 4px; font-weight: 600; margin-right: 6px; display: inline-block; border: 1px solid #eee; }
.news-card { padding: 8px 15px; margin-bottom: 15px; border-left: 6px solid #ccc; background: #fff; }
.news-title { font-size: 16px; font-weight: 700; color: #333; text-decoration: none; display: block; }
.ticker-badge { font-size: 9px; padding: 2px 5px; border-radius: 3px; color: white; font-weight: bold; margin-right: 6px; display: inline-block; }
</style>""", unsafe_allow_html=True)

if not st.session_state["logged_in"]:
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        st.markdown("<h1 style='text-align:center;'>⚡ Penny Pulse</h1>", unsafe_allow_html=True)
        with st.form("login"):
            u = st.text_input("Username"); p = st.text_input("PIN", type="password")
            if st.form_submit_button("🚀 Login"):
                ex, stp = check_user_exists(u.strip())
                if (ex and stp == p) or not ex:
                    if not ex: save_user_profile(u.strip(), {"w_input": "TD.TO, SPY"}, p)
                    st.query_params["token"] = create_session(u.strip())
                    st.session_state["username"] = u.strip(); st.session_state["user_data"] = load_user_profile(u.strip()); st.session_state["global_data"] = load_global_config(); st.session_state["logged_in"] = True; st.rerun()
else:
    USER = st.session_state["user_data"]; GLOBAL = st.session_state["global_data"]
    def push_user(): save_user_profile(st.session_state["username"], USER)
    def push_global(): save_global_config(GLOBAL)

    tape_content = get_tape_data(GLOBAL.get("tape_input", "^DJI, ^IXIC, ^GSPTSE, GC=F"))
    components.html(f"""<div style="background:#111; padding:10px; white-space:nowrap; overflow:hidden;"><marquee scrollamount="5" style="color:white; font-family:sans-serif; font-weight:bold;">{tape_content}</marquee></div>""", height=45) 

    with st.sidebar:
        st.subheader(f"👤 {st.session_state['username']}")
        st.sidebar.caption(f"📡 Connection: Finnhub {'🟢' if st.secrets.get('FINNHUB_API_KEY') else '🔴'}")

        with st.expander("⚡ AI Daily Picks", expanded=True):
            if st.button("🔎 Scan Market"):
                picks = run_gap_scanner([x.strip().upper() for x in USER.get("w_input", "").split(",") if x.strip()], ACTIVE_KEY)
                for p in picks: 
                    st.markdown(f"**{p['ticker']}** (+{p['gap']:.1f}%)")
                    st.caption(f"Price: ${p['price']:.2f} | ATR: {p['atr']:.2f}")

        new_w = st.text_area("Watchlist", value=USER.get("w_input", ""), height=100)
        if new_w != USER["w_input"]:
            USER["w_input"] = new_w; save_user_profile(st.session_state["username"], USER); st.rerun() 

        with st.expander("🔔 Alert Settings"):
            USER["telegram_id"] = st.text_input("Telegram ID", value=USER.get("telegram_id", ""))
            c1, c2 = st.columns(2)
            USER["alert_price"] = c1.checkbox("Price", value=USER.get("alert_price", True))
            USER["alert_trend"] = c2.checkbox("Trend", value=USER.get("alert_trend", True))
            USER["alert_pre"] = st.checkbox("Premarket Alerts", value=USER.get("alert_pre", True))
            if st.button("Save Alerts"): save_user_profile(st.session_state["username"], USER); st.success("Saved")

        with st.expander("🔐 Admin"):
            if st.text_input("Password", type="password") == st.secrets.get("ADMIN_PASSWORD"):
                new_t = st.text_input("Ticker").upper()
                c1, c2 = st.columns(2); new_p = c1.number_input("Cost"); new_q = c2.number_input("Qty", step=1)
                if st.button("Add Pick") and new_t:
                    if "portfolio" not in GLOBAL: GLOBAL["portfolio"] = {}
                    GLOBAL["portfolio"][new_t] = {"e": new_p, "q": int(new_q)}; save_global_config(GLOBAL); st.rerun()
                rem = st.selectbox("Remove Pick", [""] + list(GLOBAL.get("portfolio", {}).keys()))
                if st.button("Delete") and rem: del GLOBAL["portfolio"][rem]; save_global_config(GLOBAL); st.rerun()
        if st.button("Logout"): st.session_state["logged_in"] = False; st.rerun()

    @st.fragment(run_every=60)
    def render_dashboard():
        t1, t2, t3, t4 = st.tabs(["📊 Market", "🚀 My Picks", "📰 News", "🌎 Discovery"])
        w_tickers = [x.strip().upper() for x in USER['w_input'].split(",") if x.strip()]
        port = GLOBAL.get("portfolio", {}); batch_data = get_batch_data(list(set(w_tickers + list(port.keys()))))

        def draw_card(t, port_item=None):
            d = batch_data.get(t)
            if not d: return
            f = get_fundamentals(t)
            b_col = "#4caf50" if d["d"] >= 0 else "#ff4b4b"
            ai_col = "#4caf50" if d["ai"] == "BULLISH" else "#ff4b4b"
            tr_col = "#4caf50" if d["trend"] == "UPTREND" else "#ff4b4b"
            pills = f'<span class="info-pill" style="border-left: 3px solid {ai_col}">AI: {d["ai"]}</span><span class="info-pill" style="border-left: 3px solid {tr_col}">{d["trend"]}</span>'
            if f["rating"] != "N/A": pills += f'<span class="info-pill" style="border-left: 3px solid #f1c40f">RATING: {f["rating"]}</span>'
            if f["earn"] != "N/A": pills += f'<span class="info-pill" style="border-left: 3px solid #333">EARN: {f["earn"]}</span>'
            with st.container():
                st.markdown(f"<div><div style='font-size:22px; font-weight:bold;'>{t}</div><div style='font-size:22px; font-weight:bold; color:{b_col};'>${d['p']:,.2f} ({d['d']:+.2f}%)</div></div><div style='margin:10px 0;'>{pills}</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='metric-label'><span>Day Range</span><span>${d['l']:,.2f} - ${d['h']:,.2f}</span></div><div class='bar-bg'><div class='bar-fill' style='width:{d['range_pos']}%; background: linear-gradient(90deg, #ff4b4b, #f1c40f, #4caf50);'></div></div>", unsafe_allow_html=True)
                
                # REVEALED VOLUME BAR & TAGS
                st.markdown(f"""
                    <div class='metric-label'><span>Volume Status</span><span class='tag' style='background:#00d4ff'>{d['vol_label']}</span></div>
                    <div class='bar-bg'>
                        <div class='bar-fill' style='width:{d['vol_pct']}%; background:#00d4ff;'></div>
                    </div>
                """, unsafe_allow_html=True)
                
                if port_item:
                    gain = (d["p"] - port_item["e"]) * port_item["q"]
                    st.markdown(f"<div style='background:#f9f9f9; padding:5px; margin-top:10px; border-radius:5px; display:flex; justify-content:space-between; font-size:12px;'><span>Qty: <b>{port_item['q']}</b></span><span style='color:{'#4caf50' if gain>=0 else '#ff4b4b'}; font-weight:bold;'>${gain:+,.0f}</span></div>", unsafe_allow_html=True)
                st.divider()

        with t1:
            try:
                conn = get_connection(); cursor = conn.cursor(dictionary=True)
                today = datetime.now().strftime('%Y-%m-%d')
                cursor.execute("SELECT picks FROM daily_briefing WHERE date = %s", (today,))
                row = cursor.fetchone(); conn.close()
                if row: 
                    picks_list = json.loads(row['picks'])
                    # Extraction logic to only show tickers
                    display_tickers = [p['ticker'] if isinstance(p, dict) else p for p in picks_list]
                    st.success(f"📌 **Morning Briefing:** Watch {', '.join(display_tickers)}")
            except: pass
            cols = st.columns(3)
            for i, t in enumerate(w_tickers):
                with cols[i % 3]: draw_card(t)
        
        with t3:
            news = fetch_news([], w_tickers, ACTIVE_KEY)
            for n in news:
                # Surgical Fix for News Colors
                s_map = {"BULLISH": "#4caf50", "BEARISH": "#ff4b4b", "NEUTRAL": "#9e9e9e"}
                col = s_map.get(n["sentiment"], "#9e9e9e")
                st.markdown(f"<div class='news-card' style='border-left-color:{col}'><span class='ticker-badge' style='background:{col}'>{n['ticker'] or 'MARKET'}</span><a href='{n['link']}' target='_blank' class='news-title'>{n['title']}</a><div style='font-size:11px; color:#888;'>{n['published']} | Sentiment: <b>{n['sentiment']}</b></div></div>", unsafe_allow_html=True)

    render_dashboard()
