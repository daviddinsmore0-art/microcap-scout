import streamlit as st
import mysql.connector
import yfinance as yf
import requests
import uuid
import os
import pandas as pd
import pytz
import xml.etree.ElementTree as ET
import json
from datetime import datetime, timedelta

# 1. CONFIG & GLOBALS
st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="centered", initial_sidebar_state="collapsed")

# --- USER SETTINGS ---
# PASTE YOUR KEY HERE IF NOT USING SECRETS FILE
OPENAI_KEY = None 
# Example: OPENAI_KEY = "sk-proj-12345..."

# Check secrets first, then variable
if "openai" in st.secrets:
    OPENAI_KEY = st.secrets["openai"]["api_key"]

token = st.query_params.get("token", None)

DB_CONFIG = {
    "host": "atlanticcanadaschoice.com",
    "user": "atlantic",                 
    "password": "1q2w3e4R!!",   
    "database": "atlantic_pennypulse",    
    "connect_timeout": 30,
}

def get_connection():
    return mysql.connector.connect(**DB_CONFIG)

def init_db():
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # Base Tables
        cursor.execute("CREATE TABLE IF NOT EXISTS user_profiles (username VARCHAR(255) PRIMARY KEY, pin VARCHAR(50), display_name VARCHAR(100), email VARCHAR(255), created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
        cursor.execute("CREATE TABLE IF NOT EXISTS user_sessions (token VARCHAR(255) PRIMARY KEY, username VARCHAR(255), created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
        cursor.execute("CREATE TABLE IF NOT EXISTS user_portfolio (id INT NOT NULL AUTO_INCREMENT, username VARCHAR(255), ticker VARCHAR(20), shares DECIMAL(10,4) DEFAULT 0, entry_price DECIMAL(20,4) DEFAULT 0, PRIMARY KEY (id))")
        cursor.execute("CREATE TABLE IF NOT EXISTS user_alerts (id INT NOT NULL AUTO_INCREMENT PRIMARY KEY, username VARCHAR(255), ticker VARCHAR(20), condition_type VARCHAR(10), target_price DECIMAL(20,4), is_triggered BOOLEAN DEFAULT FALSE, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
        cursor.execute("CREATE TABLE IF NOT EXISTS stock_cache (ticker VARCHAR(20) PRIMARY KEY, current_price DECIMAL(20,4), day_change DECIMAL(10,2), rsi DECIMAL(10,2), trend_status VARCHAR(20), volume_status VARCHAR(20), range_loc DECIMAL(10,2), volatility DECIMAL(10,2), debt_ratio DECIMAL(10,2), days_to_earnings INT, market_cap BIGINT, eps DECIMAL(10,2), last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)")
        
        # --- SAFE MIGRATIONS ---
        try: cursor.execute("ALTER TABLE user_profiles ADD COLUMN display_name VARCHAR(100)"); except: pass
        try: cursor.execute("ALTER TABLE user_profiles ADD COLUMN email VARCHAR(255)"); except: pass
        try: cursor.execute("ALTER TABLE stock_cache ADD COLUMN market_cap BIGINT DEFAULT 0"); except: pass
        try: cursor.execute("ALTER TABLE stock_cache ADD COLUMN eps DECIMAL(10,2) DEFAULT 0"); except: pass
        try: cursor.execute("ALTER TABLE stock_cache ADD COLUMN days_to_earnings INT DEFAULT 999"); except: pass
        try: cursor.execute("ALTER TABLE user_portfolio ADD COLUMN shares DECIMAL(10,4) DEFAULT 0"); except: pass
        try: cursor.execute("ALTER TABLE user_portfolio ADD COLUMN entry_price DECIMAL(20,4) DEFAULT 0"); except: pass
        
        conn.close()
    except Exception as e:
        st.error(f"DB Error: {e}")

# 2. DATA ENGINE
def get_ai_analysis(ticker, headlines):
    """
    Sends headlines to OpenAI for summary and sentiment rating.
    Returns: (summary_text, sentiment_score 0-100)
    """
    if not OPENAI_KEY or not headlines:
        return None, 50

    try:
        prompt = f"""
        Analyze these headlines for stock {ticker}:
        {headlines}
        
        1. Summarize the news in 1 short sentence.
        2. Rate the sentiment/risk from 0 (Bad/High Risk) to 100 (Good/Low Risk).
        
        Return ONLY valid JSON format: {{"summary": "text", "score": 50}}
        """
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENAI_KEY}"
        }
        
        data = {
            "model": "gpt-3.5-turbo",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.5
        }
        
        response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=data, timeout=8)
        
        if response.status_code == 200:
            res_json = response.json()
            content = res_json['choices'][0]['message']['content']
            # Clean response to ensure it's pure JSON
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            
            parsed = json.loads(content)
            return parsed['summary'], int(parsed['score'])
    except:
        pass
    
    return None, 50

def get_news_data(ticker):
    """
    Robust news fetcher attempting yfinance first, then RSS fallback.
    """
    news_results = []
    
    # Method 1: YFinance
    try:
        stock = yf.Ticker(ticker)
        raw_news = stock.news
        if raw_news:
            for article in raw_news[:2]:
                title = article.get('title', article.get('headline', ''))
                if not title: continue
                link = article.get('link', '#')
                pub = article.get('publisher', 'Yahoo Finance')
                ts = article.get('providerPublishTime', 0)
                time_str = "Today"
                if ts:
                    diff = datetime.now() - datetime.fromtimestamp(ts)
                    if diff.days > 0: time_str = f"{diff.days}d ago"
                    elif diff.seconds > 3600: time_str = f"{diff.seconds//3600}h ago"
                    else: time_str = f"{diff.seconds//60}m ago"
                news_results.append({'title': title, 'link': link, 'pub': pub, 'time': time_str})
    except: pass

    # Method 2: RSS Fallback
    if not news_results:
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            url = f"[https://feeds.finance.yahoo.com/rss/2.0/headline?s=](https://feeds.finance.yahoo.com/rss/2.0/headline?s=){ticker}&region=US&lang=en-US"
            resp = requests.get(url, headers=headers, timeout=4)
            if resp.status_code == 200:
                root = ET.fromstring(resp.content)
                for item in root.findall('.//item')[:2]:
                    title = item.find('title').text
                    link = item.find('link').text
                    pub_date = item.find('pubDate').text
                    if " - " in title: title = title.rsplit(" - ", 1)[0]
                    news_results.append({'title': title, 'link': link, 'pub': 'Yahoo RSS', 'time': 'Recent'})
        except: pass
            
    return news_results

def update_stock_data(tickers, username):
    if not tickers: return
    try: 
        data = yf.download(" ".join(tickers), period="1d", group_by='ticker', threads=True, progress=False)
    except: return

    conn = get_connection()
    cursor = conn.cursor()
    finnhub_key = st.secrets["finnhub"]["api_key"] if "finnhub" in st.secrets else None
    
    for t in tickers:
        try:
            if len(tickers) > 1: df = data[t]
            else: df = data
            
            df = df.dropna()
            if df.empty: continue
            
            price = float(df['Close'].iloc[-1])
            prev = float(df['Open'].iloc[0]) 
            change = ((price - prev)/prev)*100
            
            rsi = 50; trend = "NEUTRAL"; vol = 0; r_loc = 50; v_stat = "NORMAL"
            debt=0; mcap=0; eps=0; days=999
            
            try:
                io = yf.Ticker(t).info
                debt = io.get('debtToEquity',0) or 0
                mcap = io.get('marketCap',0) or 0
                eps = io.get('trailingEps',0) or 0
            except: pass

            sql = """INSERT INTO stock_cache (ticker, current_price, day_change, rsi, trend_status, volume_status, range_loc, volatility, debt_ratio, days_to_earnings, market_cap, eps) 
                     VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE 
                     current_price=%s, day_change=%s, rsi=%s, trend_status=%s, volume_status=%s, range_loc=%s, volatility=%s, debt_ratio=%s, 
                     days_to_earnings=CASE WHEN %s<999 THEN %s ELSE days_to_earnings END, market_cap=%s, eps=%s"""
            vals = (t, price, change, rsi, trend, v_stat, r_loc, vol, debt, days, mcap, eps,
                    price, change, rsi, trend, v_stat, r_loc, vol, debt, days, days, mcap, eps)
            cursor.execute(sql, vals)
        except: continue
    
    conn.commit()
    conn.close()
    
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM user_alerts WHERE username=%s AND is_triggered=FALSE", (username,))
    alerts = cursor.fetchall()
    for a in alerts:
        cursor.execute("SELECT day_change FROM stock_cache WHERE ticker=%s", (a['ticker'],))
        row = cursor.fetchone()
        if row:
            pct = float(row['day_change'])
            target = float(a['target_price'])
            cond = a['condition_type']
            hit = (cond=='UP' and pct>=target) or (cond=='DOWN' and pct<=(target*-1))
            if hit: cursor.execute("UPDATE user_alerts SET is_triggered=TRUE WHERE id=%s", (a['id'],))
    conn.commit()
    conn.close()

def get_cached_data_map(tickers):
    if not tickers: return {}
    conn = get_connection(); cursor = conn.cursor(dictionary=True)
    fmt = ','.join(['%s']*len(tickers))
    cursor.execute(f"SELECT * FROM stock_cache WHERE ticker IN ({fmt})", tuple(tickers))
    rows = cursor.fetchall(); conn.close()
    return {row['ticker']: row for row in rows}

def get_single_stock(ticker):
    conn = get_connection(); cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM stock_cache WHERE ticker=%s", (ticker,))
    row = cursor.fetchone(); conn.close()
    return row

def get_portfolio_details(username):
    conn = get_connection(); cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT ticker, shares, entry_price FROM user_portfolio WHERE username=%s", (username,))
    rows = cursor.fetchall(); conn.close()
    return rows

def add_ticker_to_db(username, ticker, shares, price):
    conn = get_connection(); cursor = conn.cursor()
    cursor.execute("INSERT IGNORE INTO user_portfolio (username, ticker, shares, entry_price) VALUES (%s,%s,%s,%s)", (username, ticker, shares, price))
    conn.commit(); conn.close(); return True

def update_ticker_in_db(username, ticker, shares, price):
    conn = get_connection(); cursor = conn.cursor()
    cursor.execute("UPDATE user_portfolio SET shares=%s, entry_price=%s WHERE username=%s AND ticker=%s", (shares, price, username, ticker))
    conn.commit(); conn.close(); return True

def remove_ticker_from_db(username, ticker):
    conn = get_connection(); cursor = conn.cursor()
    cursor.execute("DELETE FROM user_portfolio WHERE username=%s AND ticker=%s", (username, ticker))
    conn.commit(); conn.close()

# Auth
def login_user(u, p):
    conn = get_connection(); cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM user_profiles WHERE username=%s", (u,))
    row = cursor.fetchone(); conn.close()
    return row if row and row['pin']==p else None

def register_user(u, p, d, e):
    conn = get_connection(); cursor = conn.cursor()
    cursor.execute("SELECT username FROM user_profiles WHERE username=%s", (u,))
    if cursor.fetchone(): conn.close(); return False
    cursor.execute("INSERT INTO user_profiles (username, pin, display_name, email) VALUES (%s,%s,%s,%s)", (u,p,d,e))
    conn.commit(); conn.close(); return True

def update_user_settings(username, display_name, email, new_pin=None):
    try:
        conn = get_connection(); cursor = conn.cursor()
        if new_pin:
            cursor.execute("UPDATE user_profiles SET display_name=%s, email=%s, pin=%s WHERE username=%s", (display_name, email, new_pin, username))
        else:
            cursor.execute("UPDATE user_profiles SET display_name=%s, email=%s WHERE username=%s", (display_name, email, username))
        conn.commit(); conn.close()
        return True
    except: return False

def create_session(u):
    t = str(uuid.uuid4()); conn = get_connection(); cursor = conn.cursor()
    cursor.execute("INSERT INTO user_sessions (token, username) VALUES (%s,%s)", (t,u)); conn.commit(); conn.close()
    return t

def get_user_from_token(t):
    conn = get_connection(); cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT s.username, p.display_name, p.email FROM user_sessions s JOIN user_profiles p ON s.username=p.username WHERE s.token=%s", (t,))
    row = cursor.fetchone(); conn.close()
    return row if row else None

# Alerts & Risk
def add_alert(username, ticker, condition, price):
    try:
        conn = get_connection(); cursor = conn.cursor()
        cursor.execute("INSERT INTO user_alerts (username, ticker, condition_type, target_price) VALUES (%s, %s, %s, %s)", (username, ticker, condition, price))
        conn.commit(); conn.close(); return True
    except: return False

def delete_alert(alert_id):
    try:
        conn = get_connection(); cursor = conn.cursor()
        cursor.execute("DELETE FROM user_alerts WHERE id = %s", (alert_id,)); conn.commit(); conn.close()
    except: pass

def get_user_alerts(username):
    try:
        conn = get_connection(); cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM user_alerts WHERE username = %s ORDER BY is_triggered ASC, created_at DESC", (username,))
        rows = cursor.fetchall(); conn.close(); return rows
    except: return []

def calculate_risk(row, ai_score=None):
    s = 50; reasons = []
    # Technicals
    if row.get('trend_status') == 'DOWNTREND': s += 10
    else: s -= 10
    rsi = float(row.get('rsi', 50))
    if rsi > 70: s += 10; reasons.append("Overbought")
    elif rsi < 30: s -= 10; reasons.append("Oversold")
    if float(row.get('volatility', 0)) > 3.0: s += 10; reasons.append("High Volatility")
    
    # AI Factor
    if ai_score is not None:
        # ai_score is 0-100 (100 is good/low risk). 
        # Low AI score (bad news) should INCREASE risk score.
        # High AI score (good news) should DECREASE risk score.
        risk_contribution = (50 - ai_score) * 0.5 # +/- 25 points max
        s += risk_contribution
        if ai_score > 60: reasons.append("Good News")
        elif ai_score < 40: reasons.append("Bad News")
    
    final = max(0, min(100, int(s)))
    if final > 65: return final, "HIGH", "#ef4444", "badge-high", reasons
    if final > 35: return final, "MEDIUM", "#fbbf24", "badge-med", reasons
    return final, "LOW", "#4ade80", "badge-low", reasons

# UI
def create_gauge_html(score, label, color, size="big"):
    rad = 80 if size == "big" else 60
    vb = "0 0 200 120" if size == "big" else "0 0 160 100"
    fs = "38" if size == "big" else "28"
    fill = (score / 100) * (3.14159 * rad)
    header = f'<div style="text-align:center; color:#94a3b8; font-size:0.8rem; font-weight:bold; letter-spacing:1px; margin-bottom:5px;">PORTFOLIO RISK</div>' if size == "big" else ""
    svg = f'<svg viewBox="{vb}" style="width:100%; height:auto;"><defs><linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="0%"><stop offset="0%" style="stop-color:#4ade80"/><stop offset="50%" style="stop-color:#fbbf24"/><stop offset="100%" style="stop-color:#ef4444"/></linearGradient></defs><path d="M 20 100 A {rad} {rad} 0 0 1 {20+rad*2} 100" fill="none" stroke="#334155" stroke-width="15" stroke-linecap="round"/><path d="M 20 100 A {rad} {rad} 0 0 1 {20+rad*2} 100" fill="none" stroke="url(#g)" stroke-width="15" stroke-linecap="round" stroke-dasharray="{fill}, 1000"/><text x="{20+rad}" y="{80 if size=="big" else 85}" font-family="sans-serif" font-size="{fs}" font-weight="bold" fill="white" text-anchor="middle">{score}</text><text x="{20+rad}" y="100" font-family="sans-serif" font-size="12" font-weight="bold" fill="{color}" text-anchor="middle" letter-spacing="2">{label}</text></svg>'
    return f'<div class="card" style="padding-bottom:0; margin-bottom:0;">{header}{svg}</div>' if size=="big" else f'<div style="margin-bottom:15px;">{svg}</div>'

def render_portfolio_row(row, market_data, current_token):
    p = float(market_data['current_price'])
    ch = float(market_data['day_change'])
    cc = "#4ade80" if ch>=0 else "#ef4444"
    arr = "▲" if ch>=0 else "▼"
    shares = float(row['shares'])
    entry = float(row['entry_price'])
    
    pl_html = ""
    if shares > 0 and entry > 0:
        val = shares * p; cost = shares * entry; pl = val - cost; pl_pct = (pl / cost) * 100 if cost > 0 else 0
        color_code = "green" if pl >= 0 else "red"
        pl_str = f":{color_code}[${pl:,.2f} ({pl_pct:.1f}%)]"
        pl_html = f'<div style="font-size:0.75rem; color:#94a3b8; margin-top:2px;">{int(shares)} @ ${entry:.2f} • {pl_str}</div>'
    elif shares > 0:
        pl_html = f"<div style='font-size:0.75rem; color:#94a3b8; margin-top:2px;'>{int(shares)} Shares</div>"

    link = f"?token={current_token}&ticker={row['ticker']}"
    html = f'<a href="{link}" target="_self" style="text-decoration:none; color:inherit; display:block;"><div class="card clickable-card" style="display:flex; justify-content:space-between; align-items:center; padding:15px; margin-bottom:0;"><div><div style="font-weight:bold; font-size:1.1rem; color:white;">{row["ticker"]}</div>{pl_html}</div><div style="text-align:right;"><div style="color:white; font-weight:bold;">${p:,.2f}</div><div style="color:{cc}; font-size:0.8rem;">{arr} {ch:.2f}%</div></div></div></a>'
    st.markdown(html, unsafe_allow_html=True)

def render_simple_card(row, current_token):
    p = float(row['current_price']); ch = float(row['day_change']); cc = "#4ade80" if ch>=0 else "#ef4444"; arr = "▲" if ch>=0 else "▼"
    link = f"?token={current_token}&ticker={row['ticker']}"
    html = f'<a href="{link}" target="_self" style="text-decoration:none; color:inherit; display:block;"><div class="card clickable-card" style="display:flex; justify-content:space-between; align-items:center; padding:15px;"><div><div style="font-weight:bold; font-size:1.1rem; color:white;">{row["ticker"]}</div><div style="font-size:0.8rem; color:#94a3b8;">Risk: {calculate_risk(row)[1]}</div></div><div style="text-align:right;"><div style="color:white; font-weight:bold;">${p:,.2f}</div><div style="color:{cc}; font-size:0.8rem;">{arr} {ch:.2f}%</div></div></div></a>'
    st.markdown(html, unsafe_allow_html=True)

def render_horizontal_grid(rows_dict, current_token):
    h = '<div class="scrolling-wrapper">'
    for ticker, row in rows_dict.items():
        ch = float(row['day_change']); cc = "#4ade80" if ch>=0 else "#ef4444"; arr = "▲" if ch>=0 else "▼"
        status = row.get('trend_status', 'Move')
        if row.get('volume_status') == 'SPIKE': status = "VOL SPIKE"
        link = f"?token={current_token}&ticker={ticker}"
        h += f'<a href="{link}" target="_self" style="text-decoration:none; color:inherit;"><div class="scrolling-card clickable-card"><div style="font-weight:bold; font-size:1.1rem; color:white; margin-bottom:4px;">{ticker}</div><div style="font-size:0.85rem; color:{cc}; font-weight:bold; margin-bottom:8px;">{arr} {ch:.2f}%</div><div style="display:flex; align-items:center;"><div style="width:8px; height:8px; border-radius:50%; background-color:{cc}; margin-right:6px;"></div><div style="font-size:0.65rem; color:#94a3b8; text-transform:uppercase;">{status}</div></div></div></a>'
    h += '</div>'; st.markdown(h, unsafe_allow_html=True)

def get_greeting(name):
    hour = datetime.now(pytz.timezone('America/Halifax')).hour
    if hour < 12: return f"Good Morning, {name}"
    elif 12 <= hour < 18: return f"Good Afternoon, {name}"
    else: return f"Good Evening, {name}"

def render_navbar(active_tab, token):
    nav_html = f'<div class="nav-container"><a href="?token={token}&tab=home" class="nav-link {"active" if active_tab=="home" else ""}"><span class="nav-icon">🏠</span>Home</a><a href="?token={token}&tab=portfolio" class="nav-link {"active" if active_tab=="portfolio" else ""}"><span class="nav-icon">📂</span>Stocks</a><a href="?token={token}&tab=alerts" class="nav-link {"active" if active_tab=="alerts" else ""}"><span class="nav-icon">🔔</span>Alerts</a><a href="?token={token}&tab=scanner" class="nav-link {"active" if active_tab=="scanner" else ""}"><span class="nav-icon">📡</span>Scan</a><a href="?token={token}&tab=settings" class="nav-link {"active" if active_tab=="settings" else ""}"><span class="nav-icon">⚙️</span>Set</a></div>'
    st.markdown(nav_html, unsafe_allow_html=True)

init_db()

# --- CSS: NEON THEME ---
st.markdown("""<style>
    .stApp { background-color: #0f1219; color: #e0e6ed; }
    .block-container { padding-top: 0rem !important; padding-bottom: 7rem !important; }
    .card { background-color: #1a1f2b; border-radius: 16px; padding: 20px; margin-bottom: 10px; border: 1px solid #2d3748; box-shadow: 0 4px 6px rgba(0,0,0,0.3); transition: transform 0.1s; }
    .clickable-card:active, .scrolling-card:active { transform: scale(0.96) !important; background-color: #262f40 !important; border-color: #4ade80 !important; }
    
    input[type="text"], input[type="password"], input[type="number"] { background-color: #1e293b !important; color: white !important; border: 1px solid #4ade80 !important; border-radius: 8px; padding: 10px; }
    div[data-baseweb="input"] { background-color: #1e293b !important; border: none; }
    div[data-baseweb="select"] > div { background-color: #1e293b !important; color: white !important; border: 1px solid #4ade80 !important; }
    div[role="listbox"] { background-color: #1e293b !important; }
    div[role="option"] { color: white !important; }
    div[data-testid="stWidgetLabel"] p, label { color: #e0e6ed !important; font-weight: 600; font-size: 0.8rem; }
    
    div.stButton > button {
        background: linear-gradient(135deg, #4ade80, #16a34a) !important; color: white !important; border: none; border-radius: 8px; font-weight: bold; padding: 12px 20px;
    }
    
    /* FIX: Ensure Expander Button is NOT white */
    div[data-testid="stExpander"] { background-color: transparent !important; }
    div[data-testid="stExpander"] details { background-color: transparent !important; }
    div[data-testid="stExpander"] details summary { color: #4ade80 !important; background-color: transparent !important; border: none !important; }
    div[data-testid="stExpander"] details summary:hover { color: #16a34a !important; }
    
    button[key*="del_"] { background: #1e293b !important; border: 1px solid #334155 !important; color: #94a3b8 !important; padding: 0px 8px !important; margin-top: 5px; font-size: 14px; }
    button[key*="del_"]:hover { color: #ef4444 !important; border-color: #ef4444 !important; }
    button[key="back_btn"] { background: #334155 !important; border: 1px solid #475569 !important; color: white !important; }
    button[key="alert_action_btn"] { background: linear-gradient(135deg, #4ade80, #16a34a) !important; color: white !important; width: 100%; border-radius: 12px; padding: 15px; font-size: 1.1rem; }
    
    button[data-baseweb="tab"] { color: #94a3b8 !important; }
    button[data-baseweb="tab"][aria-selected="true"] { color: #4ade80 !important; border-bottom-color: #4ade80 !important; }
    
    .scrolling-wrapper { display: flex; flex-wrap: nowrap; overflow-x: auto; gap: 12px; padding-bottom: 10px; -ms-overflow-style: none; scrollbar-width: none; }
    .scrolling-wrapper::-webkit-scrollbar { display: none; }
    .scrolling-card { flex: 0 0 auto; width: 130px; background-color: #1a1f2b; border: 1px solid #2d3748; border-radius: 12px; padding: 15px; transition: transform 0.1s; }
    
    .risk-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; padding: 8px 0; border-bottom: 1px solid #2d3748; }
    .risk-label { color: #e0e6ed; font-size: 0.9rem; }
    .risk-pill { padding: 4px 10px; border-radius: 20px; font-size: 0.75rem; font-weight: bold; text-transform: uppercase; }
    .pill-low { background: rgba(74, 222, 128, 0.2); color: #4ade80; }
    .pill-med { background: rgba(251, 191, 36, 0.2); color: #fbbf24; }
    .pill-high { background: rgba(239, 68, 68, 0.2); color: #ef4444; }
    
    header {visibility: hidden;} footer {visibility: hidden;} 
    
    .nav-container { position: fixed; bottom: 0; left: 0; width: 100%; height: 65px; background-color: #0f1219; border-top: 1px solid #2d3748; display: flex; justify-content: space-around; align-items: center; z-index: 99999; padding-bottom: 5px; }
    a.nav-link { text-decoration: none; color: #64748b; font-family: sans-serif; font-size: 10px; text-align: center; width: 100%; }
    a.nav-link.active { color: #4ade80; font-weight: bold; }
    .nav-icon { font-size: 22px; display: block; margin-bottom: 2px; }
</style>""", unsafe_allow_html=True)

# --- LOGIN ---
if "token" not in st.query_params:
    col1, col2, col3 = st.columns([1,2,1])
    with col2: 
        if os.path.exists("logo.png"): 
            st.image("logo.png", width=200)
        else:
            st.markdown("""
            <div style="text-align: center; margin-bottom: 20px;">
                <div style="font-size: 60px; color: #4ade80; text-shadow: 0 0 10px #4ade80;">⚡</div>
                <h1 style="color: #4ade80; margin: 0; text-shadow: 0 0 10px rgba(74, 222, 128, 0.5);">Penny Pulse</h1>
            </div>
            """, unsafe_allow_html=True)
    
    tab1, tab2, tab3 = st.tabs(["Login", "Register", "Forgot PIN"])
    with tab1:
        with st.form("login"):
            u = st.text_input("Username"); p = st.text_input("PIN", type="password")
            if st.form_submit_button("Login", use_container_width=True):
                user = login_user(u, p)
                if user: st.query_params["token"] = create_session(u); st.rerun()
                else: st.error("Failed")
    with tab2:
        with st.form("reg"):
            u = st.text_input("User"); p = st.text_input("PIN", type="password"); d = st.text_input("Name")
            if st.form_submit_button("Create", use_container_width=True):
                if register_user(u, p, d, ""): st.success("Created! Login now.")
                else: st.error("Taken")
    with tab3:
        st.info("Contact support to reset PIN.")
        st.text_input("Username", key="forgot_u")
        st.button("Request Reset")
    st.stop()

# LOGGED IN
user_info = get_user_from_token(token)
if not user_info: st.error("Session Expired"); st.stop()
username = user_info['username']; display_name = user_info['display_name'] or username

# CHECK FOR DETAIL VIEW
if "ticker" in st.query_params:
    ticker = st.query_params["ticker"]
    stock = get_single_stock(ticker)
    
    if st.button("← Back", key="back_btn"):
        del st.query_params["ticker"]; st.rerun()
        
    if stock:
        # Get News & AI
        news_items = get_news_data(ticker)
        headlines_txt = "\n".join([f"- {n['title']}" for n in news_items]) if news_items else ""
        ai_summary, ai_score = get_ai_analysis(ticker, headlines_txt)
        
        # Calculate Risk with AI
        s, l, c, _, r = calculate_risk(stock, ai_score)
        
        p = float(stock['current_price']); ch = float(stock['day_change']); cc = "#4ade80" if ch>=0 else "#ef4444"
        
        st.markdown(f"<h1 style='margin:0; font-size: 2.5rem;'>{ticker}</h1>", unsafe_allow_html=True)
        st.markdown(f"<h2 style='margin:0; color:{cc}; font-size: 1.5rem;'>${p:,.2f} <span style='font-size:1rem; opacity:0.8;'>({ch:.2f}%) Today</span></h2>", unsafe_allow_html=True)
        
        st.markdown(create_gauge_html(s, l, c, "big"), unsafe_allow_html=True)
        
        st.markdown(f"<div class='card' style='margin-top:15px; padding: 25px;'><div style='color:#94a3b8; font-size:0.8rem; font-weight:bold; letter-spacing:1px; margin-bottom:15px;'>RISK FACTORS</div>", unsafe_allow_html=True)
        def get_pill(val, type="risk"):
            if type=="vol": return "pill-high" if val > 3 else "pill-low", "HIGH" if val > 3 else "LOW"
            if type=="debt": return "pill-high" if val > 150 else "pill-low", "HIGH" if val > 150 else "LOW"
            if type=="rsi": return "pill-med" if val > 70 or val < 30 else "pill-low", "EXTREME" if val > 70 or val < 30 else "NORMAL"
            return "pill-low", "LOW"
        v_cls, v_txt = get_pill(float(stock['volatility']), "vol")
        st.markdown(f"<div class='risk-row'><div class='risk-label'>Volatility</div><div class='risk-pill {v_cls}'>{v_txt}</div></div>", unsafe_allow_html=True)
        d_cls, d_txt = get_pill(float(stock['debt_ratio']), "debt")
        st.markdown(f"<div class='risk-row'><div class='risk-label'>Debt / Equity</div><div class='risk-pill {d_cls}'>{d_txt}</div></div>", unsafe_allow_html=True)
        r_cls, r_txt = get_pill(float(stock['rsi']), "rsi")
        st.markdown(f"<div class='risk-row' style='border:none;'><div class='risk-label'>RSI Momentum</div><div class='risk-pill {r_cls}'>{r_txt}</div></div></div>", unsafe_allow_html=True)
        
        # AI SUMMARY CARD
        if ai_summary:
            st.markdown(f"""
            <div class='card' style='margin-top:15px; border-color: #4ade80;'>
                <div style='color:#4ade80; font-size:0.8rem; font-weight:bold; letter-spacing:1px; margin-bottom:5px;'>AI INSIGHT (Score: {ai_score}/100)</div>
                <div style='font-size:0.9rem; color:white; line-height:1.4;'>{ai_summary}</div>
            </div>
            """, unsafe_allow_html=True)

        # NEWS LIST
        if news_items:
            st.markdown(f"<div class='card' style='margin-top:15px;'><div style='color:#94a3b8; font-size:0.8rem; font-weight:bold; letter-spacing:1px; margin-bottom:15px;'>RECENT NEWS</div>", unsafe_allow_html=True)
            for item in news_items:
                title = item['title']
                pub = item['pub']
                link = item['link']
                time_str = item['time']
                
                st.markdown(f"""
                <a href="{link}" target="_blank" style="text-decoration:none;">
                    <div style='font-size:0.95rem; font-weight:bold; color:white; margin-bottom:5px;'>{title}</div>
                    <div style='font-size:0.75rem; color:#64748b; margin-bottom:15px;'>{time_str} • {pub}</div>
                </a>
                <div style="border-bottom:1px solid #2d3748; margin-bottom:15px;"></div>
                """, unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)
        else:
            st.markdown(f"<div class='card' style='margin-top:15px;'><div style='color:#64748b; font-style:italic;'>No recent news found for {ticker}</div></div>", unsafe_allow_html=True)
        
        st.write("")
        if st.button(f"🔔 Set Alert for {ticker}", key="alert_action_btn"):
            st.query_params["tab"] = "alerts"; del st.query_params["ticker"]; st.rerun()
    else: st.error("Data missing. Refresh portfolio.")
    render_navbar("portfolio", token)
    st.stop()

else:
    tab = st.query_params.get("tab", "home")
    if tab == "home":
        st.markdown(f"<div style='font-size:24px; font-weight:800; color:white; margin-bottom:10px;'>{get_greeting(display_name)}</div>", unsafe_allow_html=True)
        port_rows = get_portfolio_details(username)
        tickers = [r['ticker'] for r in port_rows]
        if tickers:
            if st.button("🔄 Refresh Data", key="ref_home"):
                with st.spinner("Scanning market..."): update_stock_data(tickers, username)
            market_data = get_cached_data_map(tickers)
            valid_rows = [market_data[t] for t in tickers if t in market_data]
            if valid_rows:
                avg = sum([calculate_risk(x)[0] for x in valid_rows])/len(valid_rows)
                riskiest = max(valid_rows, key=lambda x: calculate_risk(x)[0])
                volatile = max(valid_rows, key=lambda x: abs(float(x['day_change'])))
                st.markdown(create_gauge_html(int(avg), "MEDIUM" if avg<65 else "HIGH", "#fbbf24" if avg<65 else "#ef4444", "big"), unsafe_allow_html=True)
                st.markdown(f"""<div style="display:flex; justify-content:space-between; background:#151922; padding:15px; border-radius:0 0 16px 16px; margin-top:-14px; margin-bottom:20px; border:1px solid #2d3748; border-top:none;"><div style="text-align:center; width:33%; border-right:1px solid #2d3748;"><div style="color:#94a3b8; font-size:0.6rem; text-transform:uppercase;">Highest Risk</div><div style="color:white; font-weight:bold; font-size:1rem;">{riskiest['ticker']}</div></div><div style="text-align:center; width:33%; border-right:1px solid #2d3748;"><div style="color:#94a3b8; font-size:0.6rem; text-transform:uppercase;">Most Volatile</div><div style="color:white; font-weight:bold; font-size:1rem;">{volatile['ticker']}</div></div><div style="text-align:center; width:33%;"><div style="color:#94a3b8; font-size:0.6rem; text-transform:uppercase;">Portfolio</div><div style="color:white; font-weight:bold; font-size:1rem;">{len(tickers)} Stocks</div></div></div>""", unsafe_allow_html=True)
                st.write("### At a Glance"); render_horizontal_grid(market_data, token)
        else: st.info("Welcome! Go to 'Stocks' to add your first ticker.")

    elif tab == "portfolio":
        st.markdown(f"### My Stocks")
        with st.expander("Manage Holdings", expanded=False):
            t1, t2, t3 = st.tabs(["Add Stock", "Edit Position", "Remove Stock"])
            with t1:
                with st.form("add_stock"):
                    c1, c2, c3 = st.columns([2, 1, 1])
                    new_t = c1.text_input("Ticker", placeholder="e.g. AAPL")
                    shares = c2.number_input("Shares", min_value=0.0, step=1.0)
                    price = c3.number_input("Avg Price", min_value=0.0, step=0.01)
                    if st.form_submit_button("Add to Portfolio", use_container_width=True):
                        if new_t: add_ticker_to_db(username, new_t.upper(), shares, price); st.rerun()
            with t2:
                port_rows = get_portfolio_details(username)
                if port_rows:
                    with st.form("edit_pos"):
                        edit_t = st.selectbox("Select Stock", [r['ticker'] for r in port_rows])
                        c1, c2 = st.columns(2)
                        new_s = c1.number_input("New Shares", min_value=0.0, step=1.0)
                        new_p = c2.number_input("New Avg Price", min_value=0.0, step=0.01)
                        if st.form_submit_button("Update Position", use_container_width=True):
                            update_ticker_in_db(username, edit_t, new_s, new_p); st.rerun()
                else: st.info("Empty Portfolio")
            with t3:
                port_rows = get_portfolio_details(username)
                if port_rows:
                    to_remove = st.selectbox("Select Stock to Remove", [r['ticker'] for r in port_rows])
                    if st.button("Remove Selected", type="primary", use_container_width=True):
                        remove_ticker_from_db(username, to_remove); st.rerun()
                else: st.info("Portfolio is empty.")
        st.divider()
        port_rows = get_portfolio_details(username)
        if port_rows:
            tickers = [r['ticker'] for r in port_rows]
            market_data = get_cached_data_map(tickers)
            for row in port_rows:
                t = row['ticker']
                if t in market_data: render_portfolio_row(row, market_data[t], token)
                else: st.warning(f"Loading data for {t}...")

    elif tab == "alerts":
        st.markdown("### Volatility Alerts")
        with st.expander("New Alert", expanded=True):
            port_rows = get_portfolio_details(username)
            options = [r['ticker'] for r in port_rows]
            if options:
                t = st.selectbox("Ticker", options)
                c = st.selectbox("Trigger", ["DOWN", "UP"])
                v = st.number_input("Move %", 5.0)
                if st.button("Set Alert", use_container_width=True): add_alert(username, t, c, v); st.rerun()
            else: st.info("Add stocks first.")
        st.divider()
        conn = get_connection(); cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM user_alerts WHERE username=%s", (username,)); alerts = cursor.fetchall(); conn.close()
        for a in alerts:
            bg = "#3d1111" if a['is_triggered'] else "#1a1f2b"; border = "#ef4444" if a['is_triggered'] else "#2d3748"
            st.markdown(f"""<div style="background:{bg}; border:1px solid {border}; border-radius:12px; padding:15px; margin-bottom:10px; display:flex; justify-content:space-between;"><div><div style="font-weight:bold; color:white;">{a['ticker']}</div><div style="font-size:0.85rem; color:#94a3b8;">{a['condition_type']} {a['target_price']}%</div></div></div>""", unsafe_allow_html=True)
            if st.button("Clear", key=f"del_al_{a['id']}"): delete_alert(a['id']); st.rerun()

    elif tab == "scanner":
        st.markdown("### Market Scanner")
        port_rows = get_portfolio_details(username)
        tickers = [r['ticker'] for r in port_rows]
        market_data = get_cached_data_map(tickers)
        if market_data:
            st.markdown("**📉 Oversold (RSI < 40)**")
            for t, data in market_data.items(): 
                if float(data['rsi']) < 40: render_simple_card(data, token)
            st.markdown("**📅 Earnings Soon**")
            for t, data in market_data.items():
                if int(data.get('days_to_earnings', 999)) < 14: render_simple_card(data, token)

    elif tab == "settings":
        st.markdown("### Settings")
        with st.form("settings_form"):
            new_name = st.text_input("Display Name", value=display_name)
            new_email = st.text_input("Recovery Email", value=user_info.get('email', ''))
            new_pin = st.text_input("New PIN", type="password")
            if st.form_submit_button("Save Changes"):
                if update_user_settings(username, new_name, new_email, new_pin if new_pin else None): st.success("Saved!"); st.rerun()
        if st.button("Log Out", use_container_width=True): st.query_params.clear(); st.rerun()

    render_navbar(tab, token)
