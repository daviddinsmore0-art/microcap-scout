import streamlit as st
import pandas as pd
import altair as alt
import time
import json
import mysql.connector
import requests
import yfinance as yf
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

# --- CONFIG ---
try:
    st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="wide")
except:
    pass

ADMIN_PASSWORD = st.secrets.get("ADMIN_PASSWORD", "")
LOGO_PATH = "logo.png"

# *** DATABASE CONFIG ***
DB_CONFIG = {
    "host": "atlanticcanadaschoice.com",
    "user": "atlantic",                 
    "password": "1q2w3e4R!!",   
    "database": "atlantic_pennypulse",    
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
                day_high DECIMAL(20, 4),
                day_low DECIMAL(20, 4),
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("CREATE TABLE IF NOT EXISTS daily_briefing (date DATE PRIMARY KEY, picks JSON, sent TINYINT DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        try: cursor.execute("ALTER TABLE daily_briefing ADD COLUMN sent TINYINT DEFAULT 0"); 
        except: pass
        for col in ['day_high', 'day_low', 'company_name', 'pre_post_price', 'rating', 'next_earnings']:
            try:
                dtype = "DECIMAL(20,4)" if "day" in col or "price" in col else "VARCHAR(255)"
                cursor.execute(f"ALTER TABLE stock_cache ADD COLUMN {col} {dtype}")
            except: pass
        conn.close(); return True
    except: return False

# --- BACKEND UPDATE ENGINE ---
def run_backend_update():
    try:
        conn = get_connection(); cursor = conn.cursor(dictionary=True, buffered=True)
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
        to_fetch_price = []; to_fetch_meta = []; now = datetime.now()
        for t in all_tickers:
            row = existing_rows.get(t)
            if not row or not row['last_updated'] or (now - row['last_updated']).total_seconds() > 120: to_fetch_price.append(t)
            if not row or row.get('rating') == 'N/A' or row.get('next_earnings') == 'N/A': to_fetch_meta.append(t)
        if to_fetch_price:
            tickers_str = " ".join(to_fetch_price)
            live_data = yf.download(tickers_str, period="5d", interval="1m", prepost=True, group_by='ticker', threads=True, progress=False)
            hist_data = yf.download(tickers_str, period="1mo", interval="1d", group_by='ticker', threads=True, progress=False)
            for t in to_fetch_price:
                try:
                    df_live = live_data[t] if len(to_fetch_price) > 1 else live_data
                    df_live = df_live.dropna(subset=['Close'])
                    if df_live.empty: continue
                    live_price = float(df_live['Close'].iloc[-1])
                    df_hist = hist_data[t] if len(to_fetch_price) > 1 else hist_data
                    day_change = 0.0; rsi = 50.0; vol_stat = "NORMAL"; trend = "NEUTRAL"
                    chart_json = "[]"; close_price = live_price; day_h = live_price; day_l = live_price
                    if not df_hist.empty:
                        df_hist = df_hist.dropna(subset=['Close'])
                        close_price = float(df_hist['Close'].iloc[-1]) 
                        if len(df_hist) > 0:
                            day_h = max(float(df_hist['High'].iloc[-1]), live_price)
                            day_l = min(float(df_hist['Low'].iloc[-1]), live_price)
                        if len(df_hist) > 1:
                            prev_close = float(df_hist['Close'].iloc[-2])
                            if df_live.index[-1].date() > df_hist.index[-1].date(): prev_close = float(df_hist['Close'].iloc[-1])
                            day_change = ((close_price - prev_close) / prev_close) * 100
                        trend = "UPTREND" if close_price > df_hist['Close'].tail(20).mean() else "DOWNTREND"
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
                    final_price = close_price; pp_p = 0.0; pp_pct = 0.0
                    if "-" in t or "=F" in t:
                        final_price = live_price
                        if len(df_hist) > 0: day_change = ((live_price - float(df_hist['Close'].iloc[-1])) / float(df_hist['Close'].iloc[-1])) * 100
                    else:
                        if abs(live_price - close_price) > 0.01: pp_p = live_price; pp_pct = ((live_price - close_price) / close_price) * 100
                    sql = """INSERT INTO stock_cache (ticker, current_price, day_change, rsi, volume_status, trend_status, price_history, pre_post_price, pre_post_pct, day_high, day_low, last_updated) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()) ON DUPLICATE KEY UPDATE current_price=%s, day_change=%s, rsi=%s, volume_status=%s, trend_status=%s, price_history=%s, pre_post_price=%s, pre_post_pct=%s, day_high=%s, day_low=%s, last_updated=NOW()"""
                    v = (t, final_price, day_change, rsi, vol_stat, trend, chart_json, pp_p, pp_pct, day_h, day_l, final_price, day_change, rsi, vol_stat, trend, chart_json, pp_p, pp_pct, day_h, day_l)
                    cursor.execute(sql, v); conn.commit()
                except: pass
        if to_fetch_meta:
            for t in to_fetch_meta[:3]: 
                try:
                    tk = yf.Ticker(t); info = tk.info
                    r_val = info.get('recommendationKey', 'N/A').replace('_', ' ').upper()
                    n_val = info.get('shortName') or info.get('longName') or t
                    e_val = "N/A"
                    try:
                        cal = tk.calendar; dates = []
                        if isinstance(cal, dict) and 'Earnings Date' in cal: dates = cal['Earnings Date']
                        elif hasattr(cal, 'iloc'): dates = [v for v in cal.values.flatten() if isinstance(v, (datetime, pd.Timestamp))]
                        future_dates = [d for d in dates if pd.to_datetime(d).date() >= datetime.now().date()]
                        if future_dates: e_val = min(future_dates).strftime('%b %d')
                    except: pass
                    sql = "UPDATE stock_cache SET rating=%s, next_earnings=%s, company_name=%s WHERE ticker=%s"
                    cursor.execute(sql, (r_val, e_val, n_val, t)); conn.commit()
                except: pass
        conn.close()
    except: pass

# --- SCANNER ENGINE ---
@st.cache_data(ttl=900)
def run_gap_scanner(api_key):
    fh_key = st.secrets.get("FINNHUB_API_KEY")
    candidates = []; discovery_tickers = set()
    try:
        feeds = ["https://finance.yahoo.com/rss/most-active", "https://finance.yahoo.com/news/rssindex"]
        for url in feeds:
            resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
            if resp.status_code == 200:
                f = feedparser.parse(resp.content)
                for entry in f.entries[:25]:
                    match = re.search(r'\b[A-Z]{2,5}\b', entry.title)
                    if match: discovery_tickers.add(match.group(0))
    except: pass
    scan_list = list(discovery_tickers)
    try:
        data = yf.download(" ".join(scan_list), period="5d", interval="1d", group_by='ticker', threads=True, progress=False)
        for t in scan_list:
            try:
                df = data[t] if len(scan_list) > 1 else data
                if df.empty or len(df) < 2: continue
                prev_close = float(df['Close'].iloc[-2]); curr_price = float(df['Close'].iloc[-1]) 
                try:
                    r = requests.get(f"https://finnhub.io/api/v1/quote?symbol={t}&token={fh_key}", timeout=1).json()
                    if 'c' in r and r['c'] != 0: curr_price = float(r['c'])
                except: pass
                gap_pct = ((curr_price - prev_close) / prev_close) * 100
                if abs(gap_pct) >= 0.5 and df['Volume'].mean() > 50000: candidates.append({"ticker": t, "gap": gap_pct})
            except: continue
    except: return []
    if api_key and candidates:
        try:
            candidates.sort(key=lambda x: abs(x['gap']), reverse=True); top_10 = candidates[:10]
            client = openai.OpenAI(api_key=api_key); prompt = f"Pick Top 3 for day trading. Return JSON: {{'picks': ['TICKER', 'TICKER', 'TICKER']}}\nData: {str(top_10)}"
            resp = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"})
            return json.loads(resp.choices[0].message.content).get("picks", [])
        except: return [c['ticker'] for c in candidates[:3]]
    return [c['ticker'] for c in sorted(candidates, key=lambda x: abs(x['gap']), reverse=True)[:3]]

# --- AUTH & HELPERS ---
def check_user_exists(username):
    try:
        conn = get_connection(); cursor = conn.cursor()
        cursor.execute("SELECT pin FROM user_profiles WHERE username = %s", (username,))
        res = cursor.fetchone(); conn.close(); return (True, res[0]) if res else (False, None)
    except: return False, None

def create_session(username):
    token = str(uuid.uuid4()); conn = get_connection(); cursor = conn.cursor()
    cursor.execute("DELETE FROM user_sessions WHERE username = %s", (username,))
    cursor.execute("INSERT INTO user_sessions (token, username) VALUES (%s, %s)", (token, username))
    conn.commit(); conn.close(); return token

def validate_session(token):
    try:
        conn = get_connection(); cursor = conn.cursor()
        cursor.execute("SELECT username FROM user_sessions WHERE token = %s", (token,))
        res = cursor.fetchone(); conn.close(); return res[0] if res else None
    except: return None

def load_user_profile(username):
    try:
        conn = get_connection(); cursor = conn.cursor()
        cursor.execute("SELECT user_data FROM user_profiles WHERE username = %s", (username,))
        res = cursor.fetchone(); conn.close(); return json.loads(res[0]) if res else {"w_input": "TD.TO, SPY"}
    except: return {"w_input": "TD.TO, SPY"}

def save_user_profile(username, data, pin=None):
    try:
        conn = get_connection(); cursor = conn.cursor(); j_str = json.dumps(data)
        if pin: cursor.execute("INSERT INTO user_profiles (username, user_data, pin) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE user_data = %s, pin = %s", (username, j_str, pin, j_str, pin))
        else: cursor.execute("UPDATE user_profiles SET user_data = %s WHERE username = %s", (j_str, username))
        conn.commit(); conn.close()
    except: pass

def load_global_config():
    try:
        conn = get_connection(); cursor = conn.cursor()
        cursor.execute("SELECT user_data FROM user_profiles WHERE username = 'GLOBAL_CONFIG'")
        res = cursor.fetchone(); conn.close(); return json.loads(res[0]) if res else {"portfolio": {}}
    except: return {}

def save_global_config(data):
    try:
        conn = get_connection(); cursor = conn.cursor(); j_str = json.dumps(data)
        cursor.execute("INSERT INTO user_profiles (username, user_data) VALUES ('GLOBAL_CONFIG', %s) ON DUPLICATE KEY UPDATE user_data = %s", (j_str, j_str))
        conn.commit(); conn.close()
    except: pass

def get_global_config_data():
    api_key = st.secrets.get("OPENAI_KEY"); g = load_global_config(); rss = g.get("rss_feeds", ["https://finance.yahoo.com/news/rssindex"])
    return api_key, rss, g

# --- DATA ENGINE ---
def get_batch_data(tickers_list):
    if not tickers_list: return {}
    results = {}
    try:
        conn = get_connection(); cursor = conn.cursor(dictionary=True)
        format_strings = ','.join(['%s'] * len(tickers_list))
        cursor.execute(f"SELECT * FROM stock_cache WHERE ticker IN ({format_strings})", tuple(tickers_list))
        rows = cursor.fetchall(); conn.close()
        for row in rows:
            s = row['ticker']; price = float(row['current_price']); change = float(row['day_change'])
            rsi_val = float(row['rsi']); trend = row['trend_status']; vol_stat = row['volume_status']
            pp_html = ""
            if row.get('pre_post_price') and float(row['pre_post_price']) > 0:
                pp_p = float(row['pre_post_price']); pp_c = float(row['pre_post_pct']); now = datetime.now()
                lbl = "POST" if now.hour >= 16 else "PRE" if now.hour < 9 else "LIVE"
                pp_html = f"<div style='font-size:11px; color:#888;'>{lbl}: <span style='color:{'#4caf50' if pp_c>=0 else '#ff4b4b'}; font-weight:bold;'>${pp_p:,.2f} ({pp_c:+.2f}%)</span></div>"
            day_h = float(row.get('day_high') or price); day_l = float(row.get('day_low') or price)
            range_pos = max(0, min(100, ((price - day_l) / (day_h - day_l)) * 100)) if day_h > day_l else 50
            chart_data = pd.DataFrame({'Idx': range(20), 'Stock': json.loads(row.get('price_history') or "[0]*20")})
            base = chart_data['Stock'].iloc[0] or 1; chart_data['Stock'] = ((chart_data['Stock'] - base) / base) * 100
            results[s] = {"p": price, "d": change, "name": row.get('company_name') or s, "rsi": rsi_val, "vol_label": vol_stat, "range_pos": range_pos, "h": day_h, "l": day_l, "ai": "BULLISH" if trend == "UPTREND" else "BEARISH", "trend": trend, "pp": pp_html, "chart": chart_data}
    except: pass
    return results

def get_tape_data(symbol_string):
    items = []; symbols = [x.strip().upper() for x in symbol_string.split(",") if x.strip()]
    try:
        conn = get_connection(); cursor = conn.cursor(dictionary=True)
        cursor.execute(f"SELECT ticker, current_price, day_change FROM stock_cache WHERE ticker IN ({','.join(['%s']*len(symbols))})", tuple(symbols))
        rows = cursor.fetchall(); conn.close()
        for row in rows:
            col = "#4caf50" if row['day_change'] >= 0 else "#ff4b4b"
            items.append(f"<span style='color:#ccc; margin-left:20px;'>{row['ticker']}</span> <span style='color:{col}'>{row['current_price']:,.2f} ({row['day_change']:+.2f}%)</span>")
    except: pass
    return "    ".join(items)

# --- UI START ---
init_db(); run_backend_update()
if "init" not in st.session_state:
    st.session_state["init"] = True; st.session_state["logged_in"] = False
    url_token = st.query_params.get("token")
    if url_token:
        user = validate_session(url_token)
        if user: st.session_state["username"] = user; st.session_state["user_data"] = load_user_profile(user); st.session_state["global_data"] = load_global_config(); st.session_state["logged_in"] = True

st.markdown("""<style>
.block-container { padding-top: 4.5rem !important; }
.metric-label { font-size: 10px; color: #888; font-weight: 600; display: flex; justify-content: space-between; margin-top: 8px; text-transform: uppercase; }
.bar-bg { background: #eee; height: 5px; border-radius: 3px; width: 100%; margin-top: 3px; overflow: hidden; }
.bar-fill { height: 100%; border-radius: 3px; }
.tag { font-size: 9px; padding: 1px 5px; border-radius: 3px; font-weight: bold; color: white; }
.info-pill { font-size: 10px; color: #333; background: #f8f9fa; padding: 3px 8px; border-radius: 4px; font-weight: 600; margin-right: 6px; display: inline-block; border: 1px solid #eee; }
</style>""", unsafe_allow_html=True)

if not st.session_state["logged_in"]:
    st.markdown("<h1 style='text-align:center;'>⚡ Penny Pulse</h1>", unsafe_allow_html=True)
    with st.form("login"):
        user = st.text_input("Username"); pin = st.text_input("PIN", type="password")
        if st.form_submit_button("🚀 Login"):
            exists, stored_pin = check_user_exists(user.strip())
            if exists and stored_pin == pin:
                st.query_params["token"] = create_session(user.strip())
                st.session_state["username"] = user.strip(); st.session_state["user_data"] = load_user_profile(user.strip()); st.session_state["global_data"] = load_global_config(); st.session_state["logged_in"] = True; st.rerun()
            elif not exists:
                save_user_profile(user.strip(), {"w_input": "TD.TO, SPY"}, pin)
                st.query_params["token"] = create_session(user.strip()); st.session_state["username"] = user.strip(); st.session_state["user_data"] = load_user_profile(user.strip()); st.session_state["global_data"] = load_global_config(); st.session_state["logged_in"] = True; st.rerun()
else:
    def push_user(): save_user_profile(st.session_state["username"], st.session_state["user_data"])
    def push_global(): save_global_config(st.session_state["global_data"])
    GLOBAL = st.session_state["global_data"]; USER = st.session_state["user_data"]; ACTIVE_KEY, _, _ = get_global_config_data()
    tape_content = get_tape_data(GLOBAL.get("tape_input", "^DJI,^IXIC,^GSPTSE,GC=F"))
    components.html(f"""<div style="background:#111; color:white; padding:10px; font-weight:bold; overflow:hidden; white-space:nowrap;"><marquee scrollamount="5">{tape_content}</marquee></div>""", height=50)

    with st.sidebar:
        st.markdown(f"👤 **{st.session_state['username']}**")
        USER["w_input"] = st.text_area("Watchlist", value=USER.get("w_input", ""), height=100)
        if st.button("Save"): push_user(); st.rerun()
        with st.expander("🔐 Admin"):
            if st.text_input("Pass", type="password") == ADMIN_PASSWORD:
                if st.button("🔎 Scan Market"):
                    with st.spinner("Scanning..."):
                        picks = run_gap_scanner(ACTIVE_KEY)
                        conn = get_connection(); cursor = conn.cursor(); today = datetime.now().strftime('%Y-%m-%d')
                        cursor.execute("DELETE FROM daily_briefing WHERE date = %s", (today,))
                        cursor.execute("INSERT INTO daily_briefing (date, picks, sent) VALUES (%s, %s, 0)", (today, json.dumps(picks)))
                        conn.commit(); conn.close(); st.success("Status reset to 0.")
                if st.button("🚀 Dispatch Telegram"): requests.get("https://atlanticcanadaschoice.com/pennypulse/up.php"); st.info("Sent.")
        if st.button("Logout"): st.query_params.clear(); st.session_state["logged_in"] = False; st.rerun()

    @st.fragment(run_every=60)
    def render_dashboard():
        t1, t2, t3, t4 = st.tabs(["📊 Live Market", "🚀 My Picks", "📰 News", "🌎 Discovery"])
        w_tickers = [x.strip().upper() for x in USER.get("w_input", "").split(",") if x.strip()]
        port = GLOBAL.get("portfolio", {}); batch_data = get_batch_data(list(set(w_tickers + list(port.keys()))))

        def draw_card(t, p_item=None):
            d = batch_data.get(t)
            if not d: return
            b_col = "#4caf50" if d["d"] >= 0 else "#ff4b4b"
            with st.container():
                st.markdown(f"<div style='height:4px; width:100%; background-color:{b_col}; border-radius: 4px 4px 0 0;'></div><div style='display:flex; justify-content:space-between;'><div><div style='font-size:22px; font-weight:bold;'>{t}</div><div style='font-size:12px; color:#888;'>{d['name'][:25]}</div></div><div style='text-align:right;'><div style='font-size:22px; font-weight:bold;'>${d['p']:,.2f}</div><div style='font-size:13px; font-weight:bold; color:{b_col};'>{d['d']:+.2f}%</div>{d['pp']}</div></div><div style='margin-bottom:10px;'><span class='info-pill' style='border-left:3px solid {b_col}'>AI: {d['ai']}</span><span class='info-pill' style='border-left:3px solid {b_col}'>{d['trend']}</span></div>", unsafe_allow_html=True)
                st.altair_chart(alt.Chart(d["chart"]).mark_area(line={"color": b_col}, color=alt.Gradient(gradient="linear", stops=[alt.GradientStop(color=b_col, offset=0), alt.GradientStop(color="white", offset=1)], x1=1, x2=1, y1=1, y2=0)).encode(x=alt.X("Idx", axis=None), y=alt.Y("Stock", axis=None)), use_container_width=True)
                st.markdown(f"<div class='metric-label'><span>Day Range</span><span>${d['l']:,.2f}-${d['h']:,.2f}</span></div><div class='bar-bg'><div class='bar-fill' style='width:{d['range_pos']}%; background:#4caf50;'></div></div><div class='metric-label'><span>RSI ({int(d['rsi'])})</span><span class='tag' style='background:#999;'>{d['vol_label']}</span></div>", unsafe_allow_html=True)
                if p_item: st.markdown(f"<div style='background:#f9f9f9; padding:5px; margin-top:10px; border-radius:5px; display:flex; justify-content:space-between; font-size:12px;'><span>Qty: {p_item['q']}</span><span>Avg: ${p_item['e']}</span><span style='color:{b_col}; font-weight:bold;'>${(d['p']-p_item['e'])*p_item['q']:+,.0f}</span></div>", unsafe_allow_html=True)
                st.divider()

        with t1:
            try:
                conn = get_connection(); cursor = conn.cursor(dictionary=True); today = datetime.now().strftime('%Y-%m-%d')
                cursor.execute("SELECT picks, created_at FROM daily_briefing WHERE date = %s", (today,))
                row = cursor.fetchone(); conn.close()
                if row:
                    picks = json.loads(row['picks']); ts = row['created_at']; total_min = (ts.hour * 60) + ts.minute
                    label = "PRE-MARKET PICKS" if total_min < 600 else "DAILY PICKS"
                    st.success(f"📌 **{label}:** {', '.join(picks)} | _Updated: {ts.strftime('%I:%M %p')}_")
            except: pass
            cols = st.columns(3)
            for i, t in enumerate(w_tickers):
                with cols[i % 3]: draw_card(t)

        with t2:
            if not port: st.info("No Portfolio.")
            else:
                total_val = sum(batch_data[k]['p'] * v['q'] for k, v in port.items() if k in batch_data)
                total_cost = sum(v['e'] * v['q'] for v in port.values())
                st.markdown(f"<div style='background-color:white; border-radius:12px; padding:15px; border:1px solid #f0f0f0; margin-bottom:20px;'><div style='display:flex; justify-content:space-between;'><div><div style='font-size:11px; color:#888;'>NET ASSETS</div><div style='font-size:24px; font-weight:900;'>${total_val:,.2f}</div></div><div style='text-align:right;'><div style='font-size:11px; color:#888;'>TOTAL P/L</div><div style='font-size:24px; font-weight:900; color:{'#4caf50' if total_val>=total_cost else '#ff4b4b'};'>${total_val-total_cost:+,.2f}</div></div></div></div>", unsafe_allow_html=True)
                cols = st.columns(3)
                for i, (k, v) in enumerate(port.items()):
                    with cols[i % 3]: draw_card(k, v)
    render_dashboard()
