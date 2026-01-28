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
        cursor.execute("CREATE TABLE IF NOT EXISTS daily_briefing (date DATE PRIMARY KEY, picks JSON, sent TINYINT DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        conn.close()
        return True
    except: return False

# --- SCANNER ENGINE (INTELLIGENT VERSION) ---
@st.cache_data(ttl=900)
def run_gap_scanner(api_key):
    fh_key = st.secrets.get("FINNHUB_API_KEY")
    candidates = []
    discovery_tickers = set()
    
    # 1. RSS Discovery (Identifying Movers)
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
    if not scan_list: return []

    # 2. Bulk Technical Analysis
    try:
        # Download 30 days to calculate Average Volume for RVOL
        data = yf.download(" ".join(scan_list), period="30d", interval="1d", group_by='ticker', threads=True, progress=False)
        
        for t in scan_list:
            try:
                df = data[t] if len(scan_list) > 1 else data
                if df.empty or len(df) < 10: continue
                
                # Calculate RVOL (Current Volume / 20-day Avg Volume)
                avg_vol = df['Volume'].tail(20).mean()
                curr_vol = df['Volume'].iloc[-1]
                rvol = round(curr_vol / avg_vol, 2) if avg_vol > 0 else 1.0
                
                # Calculate Gap
                prev_close = float(df['Close'].iloc[-2])
                curr_price = float(df['Close'].iloc[-1])
                gap_pct = round(((curr_price - prev_close) / prev_close) * 100, 2)

                # Filter: At least 0.5% move and significant volume
                if abs(gap_pct) >= 0.5 and curr_vol > 50000:
                    # Fetch Sector for AI context
                    info = yf.Ticker(t).info
                    sector = info.get('sector', 'Unknown')
                    candidates.append({
                        "ticker": t, 
                        "gap": gap_pct, 
                        "rvol": rvol, 
                        "sector": sector
                    })
            except: continue
    except: return []

    # 3. AI Selection (Top 10 -> Top 3)
    if api_key and candidates:
        try:
            candidates.sort(key=lambda x: abs(x['gap']), reverse=True)
            top_10 = candidates[:10]
            
            client = openai.OpenAI(api_key=api_key)
            prompt = f"""You are a professional day trader. Pick the TOP 3 stocks for today's session.
            Criteria: Prioritize high RVOL (unusual volume) and significant Gaps. Diversify by Sector if possible.
            Candidates: {str(top_10)}
            Return ONLY a JSON object: {{"picks": ["TICKER1", "TICKER2", "TICKER3"]}}"""
            
            resp = client.chat.completions.create(
                model="gpt-4o-mini", 
                messages=[{"role": "user", "content": prompt}], 
                response_format={"type": "json_object"}
            )
            return json.loads(resp.choices[0].message.content).get("picks", [])
        except: return [c['ticker'] for c in candidates[:3]]
    
    return [c['ticker'] for c in sorted(candidates, key=lambda x: abs(x['gap']), reverse=True)[:3]]

# --- DATABASE WRAPPERS ---
def get_batch_data(tickers_list):
    if not tickers_list: return {}
    results = {}
    try:
        conn = get_connection(); cursor = conn.cursor(dictionary=True)
        format_strings = ','.join(['%s'] * len(tickers_list))
        cursor.execute(f"SELECT * FROM stock_cache WHERE ticker IN ({format_strings})", tuple(tickers_list))
        rows = cursor.fetchall(); conn.close()
        for row in rows:
            s = row['ticker']
            price = float(row['current_price']); change = float(row['day_change'])
            raw_hist = row.get('price_history')
            points = json.loads(raw_hist) if raw_hist else [price] * 20
            chart_data = pd.DataFrame({'Idx': range(len(points)), 'Stock': points})
            # Normalize chart for display
            base = chart_data['Stock'].iloc[0] if chart_data['Stock'].iloc[0] != 0 else 1
            chart_data['Stock'] = ((chart_data['Stock'] - base) / base) * 100
            
            results[s] = {
                "p": price, "d": change, "name": row.get('company_name') or s,
                "rsi": float(row['rsi']), "vol_pct": 100, "vol_label": row['volume_status'],
                "range_pos": 50, "h": float(row['day_high'] or price), "l": float(row['day_low'] or price),
                "ai": "BULLISH" if row['trend_status'] == "UPTREND" else "BEARISH",
                "trend": row['trend_status'], "pp": "", "chart": chart_data
            }
    except: pass
    return results

# --- AUTH & SESSION LOGIC ---
def validate_session(token):
    try:
        conn = get_connection(); cursor = conn.cursor()
        cursor.execute("SELECT username FROM user_sessions WHERE token = %s", (token,))
        res = cursor.fetchone(); conn.close()
        return res[0] if res else None
    except: return None

# --- UI MAIN ---
init_db()
if "logged_in" not in st.session_state: st.session_state["logged_in"] = False

if not st.session_state["logged_in"]:
    # Simple Login Placeholder
    user = st.sidebar.text_input("User")
    pin = st.sidebar.text_input("PIN", type="password")
    if st.sidebar.button("Login"):
        st.session_state["logged_in"] = True
        st.session_state["username"] = user
        st.rerun()
else:
    # --- ADMIN SIDEBAR ---
    with st.sidebar:
        st.title(f"👤 {st.session_state['username']}")
        if st.button("🔎 Scan Market"):
            with st.spinner("AI Analysis in progress..."):
                picks = run_gap_scanner(st.secrets.get("OPENAI_KEY"))
                if picks:
                    conn = get_connection(); cursor = conn.cursor()
                    today = datetime.now().strftime('%Y-%m-%d')
                    cursor.execute("DELETE FROM daily_briefing WHERE date = %s", (today,))
                    cursor.execute("INSERT INTO daily_briefing (date, picks, sent) VALUES (%s, %s, 0)", (today, json.dumps(picks)))
                    conn.commit(); conn.close()
                    st.success(f"Picks Saved: {', '.join(picks)}")
        
        if st.button("🚀 Dispatch Telegram"):
            requests.get("https://atlanticcanadaschoice.com/pennypulse/up.php")
            st.info("Trigger Sent.")

    # --- DASHBOARD ---
    t1, t2 = st.tabs(["📊 Market", "💼 Portfolio"])
    
    with t1:
        # DYNAMIC GREEN BANNER
        try:
            conn = get_connection(); cursor = conn.cursor(dictionary=True)
            today = datetime.now().strftime('%Y-%m-%d')
            cursor.execute("SELECT picks, created_at FROM daily_briefing WHERE date = %s", (today,))
            row = cursor.fetchone(); conn.close()
            if row:
                picks = json.loads(row['picks'])
                ts = row['created_at']
                total_min = (ts.hour * 60) + ts.minute
                label = "PRE-MARKET PICKS" if total_min < 600 else "DAILY PICKS" if total_min < 960 else "POST-MARKET PICKS"
                st.success(f"📌 **{label}:** {', '.join(picks)} | _Updated at {ts.strftime('%I:%M %p')}_")
        except: pass

        # Load Watchlist (Mocked for this example)
        w_tickers = ["TD.TO", "SHOP.TO", "NVDA", "GC=F"]
        batch = get_batch_data(w_tickers)
        cols = st.columns(3)
        for i, t in enumerate(w_tickers):
            d = batch.get(t)
            if d:
                with cols[i % 3]:
                    st.metric(t, f"${d['p']:,.2f}", f"{d['d']:+.2f}%")
                    st.altair_chart(alt.Chart(d["chart"]).mark_line().encode(x='Idx', y='Stock'), use_container_width=True)

