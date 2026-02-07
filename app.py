import streamlit as st
import mysql.connector
import requests
import uuid
import os
import pandas as pd
import pytz
import json
import xml.etree.ElementTree as ET
import streamlit.components.v1 as components
import textwrap
from datetime import datetime, timedelta

# =========================================================
# 1. CONFIGURATION & CSS (MUST BE FIRST)
# =========================================================
st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="centered", initial_sidebar_state="collapsed")

# STRICT CSS: Dark Theme + Clean UI + HEADLINE COLOR FIX + DROPDOWNS
st.markdown("""
    <style>
        /* REMOVE DEFAULT PADDING */
        .block-container { padding-top: 0rem !important; padding-bottom: calc(8rem + env(safe-area-inset-bottom)) !important; }
        
        /* Force Dark Background */
        .stApp { background-color: #0f1219 !important; color: #e0e6ed !important; }
        
        /* Input Fields */
        input[type="text"], input[type="password"], input[type="number"] { 
            background-color: #1e293b !important; 
            color: white !important; 
            border: 1px solid #4ade80 !important; 
            border-radius: 8px; 
            padding: 10px;
        }
        div[data-baseweb="input"] { background-color: transparent !important; border: none; }
        
        /* Dropdowns & Select Boxes (FIXED) */
        div[data-baseweb="select"] > div { 
            background-color: #1e293b !important; 
            color: white !important; 
            border: 1px solid #4ade80 !important; 
        }
        div[role="listbox"] ul { background-color: #1e293b !important; }
        li[role="option"] { color: white !important; background-color: #1e293b !important; }
        li[role="option"]:hover { background-color: #4ade80 !important; color: black !important; }
        div[data-baseweb="popover"] { background-color: #1e293b !important; }
        
        /* Cards WITH CLICK EFFECT ADDED */
        .card { 
            background-color: #1a1f2b; 
            border-radius: 16px; 
            padding: 20px; 
            margin-bottom: 10px; 
            border: 1px solid #2d3748; 
            box-shadow: 0 4px 6px rgba(0,0,0,0.3); 
            transition: transform 0.1s ease, border-color 0.1s ease;
        }
        .card:active {
            transform: scale(0.97);
            border-color: #4ade80 !important;
        }

        /* Portfolio reorder animation helper */
        .port-row { will-change: transform; }

        /* Clickable tiles (button-like press feedback) */
        .click-tile {
            transition: transform 0.1s ease, border-color 0.1s ease;
        }
        .click-tile:active {
            transform: scale(0.97);
            border-color: #4ade80 !important;
        }
        a.nav-link:active { transform: scale(0.92); }

        
        /* Metric Boxes */
        .metric-box {
            background-color: #1e293b;
            border: 1px solid #2d3748;
            border-radius: 12px;
            padding: 15px;
            text-align: center;
            margin-bottom: 10px;
        }
        .metric-label { font-size: 0.75rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 5px; }
        .metric-value { font-size: 1.5rem; font-weight: bold; color: white; margin-bottom: 2px; line-height: 1.1; }
        .metric-sub { font-size: 0.9rem; font-weight: bold; }
        
        /* Buttons */
        div.stButton > button {
            background: linear-gradient(135deg, #4ade80, #16a34a) !important; 
            color: white !important; 
            border: none; 
            border-radius: 8px; 
            font-weight: bold;
            width: 100%;
            padding: 12px 20px;
        }
        
        /* Delete/Remove Buttons */
        button[kind="secondary"] {
            background: #334155 !important;
            border: 1px solid #ef4444 !important;
            color: #ef4444 !important;
        }

        h1, h2, h3, p, label, span, div { color: #e0e6ed; }

        /* HEADLINE COLOR FIX */
        a { color: #ffffff !important; text-decoration: none !important; }
        a:hover { color: #4ade80 !important; }
        
        /* Navigation */
        .nav-container { 
            position: fixed; bottom: 0; left: 0; width: 100%; height: 65px; 
            background-color: #0f1219; border-top: 1px solid #2d3748; 
            display: flex; justify-content: space-around; align-items: center; z-index: 99999; 
        }
        a.nav-link { text-decoration: none; font-size: 24px; text-align: center; cursor: pointer;}
        a.nav-link:hover { transform: scale(1.1); }
        
        /* Scrolling Wrapper */
        .scrolling-wrapper { 
            display: flex; 
            flex-wrap: nowrap; 
            overflow-x: auto; 
            gap: 12px; 
            padding-bottom: 10px; 
            -ms-overflow-style: none; 
            scrollbar-width: none; 
        }
        .scrolling-wrapper::-webkit-scrollbar { display: none; }
        .scrolling-card { 
            flex: 0 0 auto; 
            width: 130px; 
            background-color: #1a1f2b; 
            border: 1px solid #2d3748; 
            border-radius: 12px; 
            padding: 15px; 
        }

        .price-block {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    text-align: right;
    gap: 2px;
    margin-left: auto;
    padding-top: 2px;
}
           
        /* Risk Pills */
        .risk-pill { padding: 4px 10px; border-radius: 20px; font-size: 0.75rem; font-weight: bold; text-transform: uppercase; }
        .pill-low { background: rgba(74, 222, 128, 0.2); color: #4ade80; }
        .pill-med { background: rgba(251, 191, 36, 0.2); color: #fbbf24; }
        .pill-high { background: rgba(239, 68, 68, 0.2); color: #ef4444; }
        .risk-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; border-bottom: 1px solid #2d3748; padding-bottom: 5px; }
        
        /* Hide default header/footer */
        header {visibility: hidden;} footer {visibility: hidden;} 
    </style>
""", unsafe_allow_html=True)

# Global Constants
DB_CONFIG = {
    "host": "atlanticcanadaschoice.com", 
    "user": "atlantic", 
    "password": "1q2w3e4R!!", 
    "database": "atlantic_pennypulse", 
    "connect_timeout": 30
}
OPENAI_KEY = st.secrets["openai"]["api_key"] if "openai" in st.secrets else None
token = st.query_params.get("token", None)

# =========================================================
# 2. FUNCTIONS
# =========================================================

def get_connection():
    return mysql.connector.connect(**DB_CONFIG)

def init_db():
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS user_profiles (username VARCHAR(255) PRIMARY KEY, pin VARCHAR(50), display_name VARCHAR(100), email VARCHAR(255), paper_balance DECIMAL(20,2) DEFAULT 10000.00)")
        cursor.execute("CREATE TABLE IF NOT EXISTS user_sessions (token VARCHAR(255) PRIMARY KEY, username VARCHAR(255))")
        cursor.execute("CREATE TABLE IF NOT EXISTS user_portfolio (id INT NOT NULL AUTO_INCREMENT, username VARCHAR(255), ticker VARCHAR(20), shares DECIMAL(10,4) DEFAULT 0, entry_price DECIMAL(20,4) DEFAULT 0, portfolio_type VARCHAR(20) DEFAULT 'REAL', is_active BOOLEAN DEFAULT TRUE, realized_pl DECIMAL(20,2) DEFAULT 0.00, PRIMARY KEY (id))")
        cursor.execute("CREATE TABLE IF NOT EXISTS user_alerts (id INT NOT NULL AUTO_INCREMENT PRIMARY KEY, username VARCHAR(255), ticker VARCHAR(20), condition_type VARCHAR(10), target_price DECIMAL(20,4), is_triggered BOOLEAN DEFAULT FALSE, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        # Ensure created_at exists for ordering (safe if column already exists)
        try:
            cursor.execute("ALTER TABLE user_alerts ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        except:
            pass
        cursor.execute("CREATE TABLE IF NOT EXISTS stock_cache (ticker VARCHAR(20) PRIMARY KEY, company_name VARCHAR(255), current_price DECIMAL(20,4), day_change DECIMAL(10,2), rsi DECIMAL(10,2), trend_status VARCHAR(20), volume_status VARCHAR(20), range_loc DECIMAL(10,2), volatility DECIMAL(10,2), debt_ratio DECIMAL(10,2), days_to_earnings INT, market_cap BIGINT, eps DECIMAL(10,2), signal_tag VARCHAR(50), last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)")
        cursor.execute("CREATE TABLE IF NOT EXISTS daily_briefing (id INT PRIMARY KEY, content TEXT, last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)")
        if OPENAI_KEY:
            cursor.execute("CREATE TABLE IF NOT EXISTS system_config (key_name VARCHAR(50) PRIMARY KEY, key_value TEXT)")
            cursor.execute("REPLACE INTO system_config (key_name, key_value) VALUES ('openai_key', %s)", (OPENAI_KEY,))
            conn.commit()
        conn.close()
    except Exception as e:
        print(f"Database Error: {e}")

def parse_smart_date(date_str):
    if not date_str or str(date_str).lower() in ['n/a', 'none', '', '999']: return 999
    try:
        now = datetime.now()
        try:
            target = datetime.strptime(f"{date_str} {now.year}", "%b %d %Y")
            if target < now: target = datetime.strptime(f"{date_str} {now.year + 1}", "%b %d %Y")
        except ValueError:
            target = datetime.strptime(str(date_str), "%Y-%m-%d")
        return (target - now).days
    except: return 999

def login_user(u, p):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM user_profiles WHERE username=%s", (u,))
    row = cursor.fetchone()
    conn.close()
    if row and str(row['pin']) == str(p): return row
    return None

def register_user(u, p, d, e):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT username FROM user_profiles WHERE username=%s", (u,))
    if cursor.fetchone(): conn.close(); return False
    cursor.execute("INSERT INTO user_profiles (username, pin, display_name, email) VALUES (%s,%s,%s,%s)", (u, p, d, e))
    conn.commit(); conn.close()
    return True

def create_session(u):
    t = str(uuid.uuid4())
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO user_sessions (token, username) VALUES (%s,%s)", (t, u))
    conn.commit(); conn.close()
    return t

def get_user_from_token(t):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT s.username, p.display_name, p.paper_balance, p.email FROM user_sessions s JOIN user_profiles p ON s.username=p.username WHERE s.token=%s", (t,))
    row = cursor.fetchone()
    conn.close()
    return row

def update_user_settings(username, display_name, email, new_pin=None):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        if new_pin: cursor.execute("UPDATE user_profiles SET display_name=%s, email=%s, pin=%s WHERE username=%s", (display_name, email, new_pin, username))
        else: cursor.execute("UPDATE user_profiles SET display_name=%s, email=%s WHERE username=%s", (display_name, email, username))
        conn.commit(); conn.close()
        return True
    except: return False

def get_news_data(ticker):
    news_results = []
    try:
        url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            root = ET.fromstring(resp.content)
            for item in root.findall('.//item')[:3]:
                title = item.find('title').text if item.find('title') is not None else "No Title"
                link = item.find('link').text if item.find('link') is not None else "#"
                news_results.append({'title': title, 'link': link, 'pub': "Yahoo", 'time': "Recent"})
    except: pass
    return news_results

def get_ai_analysis(ticker, headlines, current_data=None):
    if OPENAI_KEY and headlines and len(headlines) > 10:
        try:
            prompt = f"Analyze these headlines for {ticker}: {headlines} Return JSON: {{'summary': '1 sentence', 'score': 50}}"
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {OPENAI_KEY}"}
            data = {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": prompt}], "temperature": 0.3}
            response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=data, timeout=10)
            if response.status_code == 200:
                content = response.json()['choices'][0]['message']['content']
                if "```" in content: content = content.split("```")[1].replace("json", "").strip()
                parsed = json.loads(content)
                return parsed.get('summary'), parsed.get('score'), "AI"
        except: pass
    if current_data:
        rsi = float(current_data.get('rsi') or 50)
        trend = current_data.get('trend_status', 'NEUTRAL')
        if rsi > 70: return "Technical: Overbought (RSI > 70). Risk of pullback.", 30, "TECH"
        elif rsi < 30: return "Technical: Oversold (RSI < 30). Potential bounce.", 80, "TECH"
        elif trend == "UPTREND": return "Technical: Strong Uptrend detected.", 75, "TECH"
        return "Market sentiment is neutral. Monitor volume.", 50, "TECH"
    return "No Data Available", 50, "NONE"

def calculate_risk(row, ai_score=None):
    """Return (risk_score, label, color, badge, breakdown).

    breakdown is a list of tuples: (factor, points) where points are the
    contribution to the final risk score before clamping.
    """
    risk = 50.0
    breakdown = []

    # Trend
    trend = (row.get("trend_status") or "NEUTRAL").upper()
    if trend == "DOWNTREND":
        risk += 15
        breakdown.append(("Trend (Downtrend)", +15))
    elif trend == "UPTREND":
        risk -= 12
        breakdown.append(("Trend (Uptrend)", -12))
    else:
        risk += 3
        breakdown.append(("Trend (Neutral)", +3))

    # RSI (gradient)
    rsi = float(row.get("rsi") or 50)
    if rsi >= 80:
        risk += 15
        breakdown.append(("RSI (>=80 overbought)", +15))
    elif rsi >= 70:
        risk += 8
        breakdown.append(("RSI (70-79 overbought)", +8))
    elif rsi <= 20:
        risk += 12
        breakdown.append(("RSI (<=20 extreme)", +12))
    elif rsi <= 30:
        risk += 5
        breakdown.append(("RSI (21-30 oversold)", +5))
    else:
        breakdown.append(("RSI (normal)", 0))

    # Volatility (gradient)
    vol = float(row.get("volatility") or 0)
    if vol >= 6:
        risk += 18
        breakdown.append(("Volatility (>=6)", +18))
    elif vol >= 4:
        risk += 12
        breakdown.append(("Volatility (4-5.9)", +12))
    elif vol >= 2:
        risk += 6
        breakdown.append(("Volatility (2-3.9)", +6))
    else:
        breakdown.append(("Volatility (<2)", 0))

    # Debt / Equity (debt_ratio)
    debt = float(row.get("debt_ratio") or 0)
    if debt >= 200:
        risk += 15
        breakdown.append(("Debt/Equity (>=200)", +15))
    elif debt >= 120:
        risk += 8
        breakdown.append(("Debt/Equity (120-199)", +8))
    else:
        breakdown.append(("Debt/Equity (<120)", 0))

    # AI sentiment (small nudge)
    if ai_score is not None:
        adj = (50 - float(ai_score)) * 0.25
        risk += adj
        breakdown.append(("AI sentiment adjust", round(adj, 1)))
    else:
        breakdown.append(("AI sentiment adjust", 0))

    final = max(0, min(100, int(round(risk))))

    color = "#4ade80"
    label = "LOW"
    if final >= 70:
        color = "#ef4444"
        label = "HIGH"
    elif final >= 40:
        color = "#fbbf24"
        label = "MEDIUM"

    return final, label, color, "badge-mix", breakdown



def calculate_confidence(row, ai_score=None):
    """Return a 0-100 confidence score (higher = cleaner/healthier setup).

    This is intentionally not just (100 - risk). It adds small bonuses for
    healthy conditions (uptrend + mid RSI) and small penalties for very high
    volatility / extremes.
    """
    risk, _, _, _, _ = calculate_risk(row, ai_score)

    confidence = 100 - int(risk)

    trend = (row.get("trend_status") or "NEUTRAL").upper()
    rsi = float(row.get("rsi") or 50)
    vol = float(row.get("volatility") or 0)

    if trend == "UPTREND":
        confidence += 6
    elif trend == "DOWNTREND":
        confidence -= 4

    if 40 <= rsi <= 60:
        confidence += 6
    elif rsi >= 80 or rsi <= 20:
        confidence -= 6

    if vol >= 6:
        confidence -= 10
    elif vol >= 4:
        confidence -= 6
    elif vol >= 2:
        confidence -= 2

    if ai_score is not None:
        confidence += int((float(ai_score) - 50) * 0.15)

    return max(0, min(100, int(confidence)))


def calculate_confidence(row, ai_score=None):
    """Confidence is 'opportunity / setup quality' (0-100)."""
    conf = 50.0

    trend = (row.get("trend_status") or "NEUTRAL").upper()
    if trend == "UPTREND":
        conf += 15
    elif trend == "DOWNTREND":
        conf -= 10

    rsi = float(row.get("rsi") or 50)
    # Prefer RSI in the middle (room to run, not extreme)
    if 40 <= rsi <= 60:
        conf += 8
    elif 30 <= rsi < 40 or 60 < rsi <= 70:
        conf += 4
    elif rsi >= 80 or rsi <= 20:
        conf -= 8

    vol = float(row.get("volatility") or 0)
    if vol < 2:
        conf += 6
    elif vol >= 6:
        conf -= 12
    elif vol >= 4:
        conf -= 8

    # Volume status (if present in cache)
    vs = (row.get("volume_status") or "").lower()
    if "unusual" in vs or "surge" in vs:
        conf += 6
    elif "low" in vs:
        conf -= 3

    # Range location (if 0-100): higher can be good *if* trend is up
    try:
        rl = float(row.get("range_loc") or 0)
        if trend == "UPTREND" and rl >= 70:
            conf += 4
    except:
        pass

    if ai_score is not None:
        conf += (float(ai_score) - 50) * 0.2

    final = max(0, min(100, int(round(conf))))
    return final


def get_watchlist_date_for_home():
    """Show NEXT day's watchlist after market close (4pm NY)."""
    now_ny = datetime.now(pytz.timezone("America/New_York"))
    if now_ny.hour >= 16:
        return (now_ny + timedelta(days=1)).date()
    return now_ny.date()

def get_watchlist_header_date():
    d = get_watchlist_date_for_home()
    return datetime(d.year, d.month, d.day).strftime("%b %d")

def get_daily_watchlist(date_obj):
    """Return up to 4 rows for the given date from daily_watchlist.
    Expects table: daily_watchlist(watch_date DATE, rank_num INT, ticker VARCHAR, label VARCHAR, score DECIMAL, created_at TIMESTAMP)
    """
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT rank_num AS rank, ticker, label, score FROM daily_watchlist WHERE watch_date=%s ORDER BY rank_num ASC LIMIT 4",
            (date_obj.strftime("%Y-%m-%d"),)
        )
        rows = cursor.fetchall()
        conn.close()
        return rows or []
    except Exception:
        return []

def get_watchlist_rows_for_home():
    """Home watchlist comes from daily_watchlist only (no dynamic fallback)."""
    d = get_watchlist_date_for_home()
    rows = get_daily_watchlist(d)

    if not rows:
        return []

    # Try to enrich with stock_cache price/change for nicer tiles
    tickers = [r["ticker"] for r in rows]
    cache_map = get_cached_data_map(tickers)

    out = []
    for r in rows:
        t = r["ticker"]
        label = (r.get("label") or "Momentum")
        score = r.get("score")
        if t in cache_map:
            row = cache_map[t]
            row["signal_tag"] = label
            row["_watchlist_score"] = score
            out.append(row)
        else:
            out.append({
                "ticker": t,
                "signal_tag": label,
                "current_price": None,
                "day_change": float(score or 0),
                "_watchlist_score": score
            })
    return out[:4]


def get_cached_data_map(tickers):
    if not tickers: return {}
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    format_strings = ','.join(['%s'] * len(tickers))
    cursor.execute(f"SELECT * FROM stock_cache WHERE ticker IN ({format_strings})", tuple(tickers))
    rows = cursor.fetchall()
    conn.close()
    return {row['ticker']: row for row in rows}

def get_single_stock(ticker):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM stock_cache WHERE ticker=%s", (ticker,))
    row = cursor.fetchone()
    conn.close()
    return row

def get_portfolio_details(username, ptype):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM user_portfolio WHERE username=%s AND portfolio_type=%s AND is_active=TRUE", (username, ptype))
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_portfolio_summary(username, ptype):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT SUM(realized_pl) as realized FROM user_portfolio WHERE username=%s AND portfolio_type=%s AND is_active=FALSE", (username, ptype))
    realized_row = cursor.fetchone()
    realized = float(realized_row['realized'] or 0)
    
    cursor.execute("SELECT p.shares, p.entry_price, s.current_price, s.day_change FROM user_portfolio p LEFT JOIN stock_cache s ON p.ticker = s.ticker WHERE p.username=%s AND p.portfolio_type=%s AND p.is_active=TRUE", (username, ptype))
    active_rows = cursor.fetchall()
    
    unrealized = 0.0; day_pl = 0.0; active_cost_basis = 0.0; current_portfolio_value = 0.0
    for r in active_rows:
        if r['current_price']:
            curr = float(r['current_price']); entry = float(r['entry_price']); shares = float(r['shares'])
            unrealized += ((curr * shares) - (entry * shares))
            active_cost_basis += (entry * shares)
            current_portfolio_value += (curr * shares)
            pct = float(r['day_change'] or 0)
            prev = curr / (1 + (pct/100))
            day_pl += (curr - prev) * shares
    conn.close()
    
    total_pl_dollars = realized + unrealized
    total_pl_pct = (total_pl_dollars / active_cost_basis) * 100 if active_cost_basis > 0 else 0
    day_pl_pct = (day_pl / (current_portfolio_value - day_pl)) * 100 if (current_portfolio_value - day_pl) > 0 else 0
    return total_pl_dollars, total_pl_pct, day_pl, day_pl_pct

def execute_paper_trade(username, ticker, action, qty, price):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT paper_balance FROM user_profiles WHERE username=%s", (username,))
    row = cursor.fetchone()
    if not row: conn.close(); return False, "User not found"
    
    balance = float(row[0])
    total_cost = float(qty) * float(price)
    
    if action == "BUY":
        if balance < total_cost: conn.close(); return False, "Insufficient Balance"
        cursor.execute("UPDATE user_profiles SET paper_balance = paper_balance - %s WHERE username=%s", (total_cost, username))
        cursor.execute("INSERT INTO user_portfolio (username, ticker, shares, entry_price, portfolio_type, is_active) VALUES (%s, %s, %s, %s, 'PAPER', 1)", (username, ticker, qty, price))
        conn.commit(); conn.close()
        return True, f"Bought {qty} shares of {ticker}"
        
    elif action == "SELL":
        cursor.execute("UPDATE user_profiles SET paper_balance = paper_balance + %s WHERE username=%s", (total_cost, username))
        conn.commit(); conn.close()
        return True, f"Sold {qty} shares of {ticker}"

def deactivate_stock(username, ticker, ptype):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT p.shares, p.entry_price, s.current_price FROM user_portfolio p LEFT JOIN stock_cache s ON p.ticker = s.ticker WHERE p.username=%s AND p.ticker=%s AND p.portfolio_type=%s", (username, ticker, ptype))
    row = cursor.fetchone()
    if row:
        shares, entry, curr = row
        final_pl = (float(curr or 0) - float(entry)) * float(shares)
        cursor.execute("UPDATE user_portfolio SET is_active=FALSE, realized_pl=%s WHERE username=%s AND ticker=%s AND portfolio_type=%s", (final_pl, username, ticker, ptype))
    conn.commit()
    conn.close()

def add_ticker_to_db(username, ticker, shares, price, ptype):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO user_portfolio (username, ticker, shares, entry_price, portfolio_type, is_active) VALUES (%s,%s,%s,%s,%s, TRUE)", (username, ticker, shares, price, ptype))
    conn.commit()
    conn.close()

def update_ticker_in_db(username, ticker, shares, price, ptype):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE user_portfolio SET shares=%s, entry_price=%s WHERE username=%s AND ticker=%s AND portfolio_type=%s", (shares, price, username, ticker, ptype))
    conn.commit()
    conn.close()

def remove_ticker_from_db(username, ticker, ptype):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM user_portfolio WHERE username=%s AND ticker=%s AND portfolio_type=%s", (username, ticker, ptype))
    conn.commit()
    conn.close()

def add_alert(username, ticker, condition, price):
    conn = get_connection()
    cursor = conn.cursor()
    try: cursor.execute("INSERT INTO user_alerts (username, ticker, condition_type, target_price) VALUES (%s, %s, %s, %s)", (username, ticker, condition, price))
    except: pass
    conn.commit(); conn.close()

def delete_alert(alert_id):
    conn = get_connection()
    conn.cursor().execute("DELETE FROM user_alerts WHERE id = %s", (alert_id,))
    conn.commit(); conn.close()

def get_user_alerts(username):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM user_alerts WHERE username = %s ORDER BY is_triggered ASC, created_at DESC", (username,))
    rows = cursor.fetchall()
    conn.close()
    return rows

# --- UI Functions ---
def render_navbar(token, mode):
    mode_arg = "&mode=PAPER" if mode == "PAPER" else ""
    st.markdown(f"""
    <div class="nav-container">
        <a href="?token={token}&tab=home{mode_arg}" class="nav-link">🏠</a>
        <a href="?token={token}&tab=portfolio{mode_arg}" class="nav-link">📂</a>
        <a href="?token={token}&tab=alerts{mode_arg}" class="nav-link">🔔</a>
        <a href="?token={token}&tab=scanner{mode_arg}" class="nav-link">📡</a>
        <a href="?token={token}&tab=settings{mode_arg}" class="nav-link">⚙️</a>
    </div>
    """, unsafe_allow_html=True)

def create_gauge_html(score, label, color, size="big"):
    rad = 80 if size == "big" else 60
    vb = "0 0 200 120" if size == "big" else "0 0 160 100"
    fill = (score / 100) * (3.14159 * rad)
    header = f'<div style="text-align:center; color:#94a3b8; font-size:0.8rem; font-weight:bold; letter-spacing:1px; margin-bottom:5px;">PORTFOLIO RISK</div>' if size == "big" else ""
    svg = f"""
    <svg viewBox="{vb}" style="width:100%; height:auto;">
        <defs>
            <linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" style="stop-color:#4ade80"/><stop offset="50%" style="stop-color:#fbbf24"/><stop offset="100%" style="stop-color:#ef4444"/>
            </linearGradient>
        </defs>
        <path d="M 20 100 A {rad} {rad} 0 0 1 {20+rad*2} 100" fill="none" stroke="#334155" stroke-width="15" stroke-linecap="round"/>
        <path d="M 20 100 A {rad} {rad} 0 0 1 {20+rad*2} 100" fill="none" stroke="url(#g)" stroke-width="15" stroke-linecap="round" stroke-dasharray="{fill}, 1000"/>
        <text x="{20+rad}" y="80" font-family="sans-serif" font-size="38" font-weight="bold" fill="white" text-anchor="middle">{score}</text>
        <text x="{20+rad}" y="100" font-family="sans-serif" font-size="12" font-weight="bold" fill="{color}" text-anchor="middle" letter-spacing="2">{label}</text>
    </svg>
    """
    return f'<div class="card" style="padding-bottom:0; margin-bottom:0;">{header}{svg}</div>'


def generate_playbook(stock_row):
    """Generate a simple rule-based trade plan using cached metrics.

    Uses current_price + volatility proxy for an 'expected move' and chooses a
    playbook style from trend/RSI conditions.
    """
    price = float(stock_row.get("current_price") or 0)
    if price <= 0:
        return None

    trend = (stock_row.get("trend_status") or "NEUTRAL").upper()
    rsi = float(stock_row.get("rsi") or 50)
    vol = float(stock_row.get("volatility") or 2.5)

    move = max(price * (vol / 100.0), price * 0.01)

    if trend == "UPTREND" and rsi < 70:
        name = "Momentum Continuation"
        entry = price * 1.005
        stop = price - (move * 1.2)
        t1 = price + (move * 1.5)
        t2 = price + (move * 3.0)
        rationale = "Uptrend + non-overbought RSI. Follow-through favored."
    elif rsi <= 30:
        name = "Oversold Bounce"
        entry = price * 1.003
        stop = price - (move * 1.6)
        t1 = price + (move * 1.2)
        t2 = price + (move * 2.2)
        rationale = "RSI oversold. Bounce setups can work—manage risk tightly."
    elif rsi >= 80:
        name = "Overbought Mean Reversion (Cautious)"
        entry = price * 0.997
        stop = price + (move * 1.2)
        t1 = price - (move * 1.2)
        t2 = price - (move * 2.2)
        rationale = "RSI very high. Reversion risk—size smaller or wait for confirmation."
    else:
        name = "Range / Wait For Trigger"
        entry = price * 1.007
        stop = price - (move * 1.4)
        t1 = price + (move * 1.3)
        t2 = price + (move * 2.4)
        rationale = "Neutral conditions. Use a trigger to avoid chop."

    def r(x):
        return round(float(x), 2)

    return {
        "name": name,
        "entry": r(entry),
        "stop": r(stop),
        "t1": r(t1),
        "t2": r(t2),
        "rationale": rationale,
        "move": r(move),
    }


def render_portfolio_row(row, data, token):
    risk, label, color, _, _ = calculate_risk(data)
    conf = calculate_confidence(data)
    conf_bg = "#4ade80" if conf >= 70 else ("#fbbf24" if conf >= 40 else "#ef4444")
    price = float(data['current_price'])
    change = float(data['day_change'])
    change_color = "#4ade80" if change >= 0 else "#ef4444"
    arrow = "▲" if change >= 0 else "▼"
    shares = float(row['shares'])
    entry = float(row['entry_price'])
    
    pl_html = ""
    if shares > 0 and entry > 0:
        pl = (shares * price) - (shares * entry)
        pl_pct = (pl / (shares * entry)) * 100 if entry > 0 else 0
        pl_c = "#4ade80" if pl >= 0 else "#ef4444"
        pl_html = f"<div style='color:{pl_c}; font-size:0.85rem; margin-top:2px;'>{int(shares)} @ ${entry:.2f} • ${pl:,.2f} ({pl_pct:.1f}%)</div>"

    link = f"?token={token}&ticker={row['ticker']}"

# ---- NEW: pick fields safely (won't crash if missing) ----
company = (row.get("company_name") or row.get("company") or row.get("name") or "").strip()

# Timestamp fields (choose what you actually have)
updated_raw = row.get("updated_at") or row.get("last_updated") or row.get("ts") or row.get("timestamp") or ""

# Optional: make it pretty if it's a datetime / pandas timestamp
updated_str = ""
try:
    if updated_raw:
        # if it's already a datetime-like
        updated_str = updated_raw.strftime("%b %d, %I:%M %p")
except Exception:
    # fallback: just show whatever string you have
    updated_str = str(updated_raw) if updated_raw else ""

# ---- NEW: small HTML lines (only render if present) ----
company_html = f'<div style="font-size:0.8rem; color:#9aa4b2; margin-top:2px;">{company}</div>' if company else ""
updated_html = f'<div style="font-size:0.7rem; color:#7a8594; margin-top:2px;">Updated {updated_str}</div>' if updated_str else ""

link = f"?token={token}&ticker={row['ticker']}"
    html = f"""
    <a href="{link}" target="_self" style="text-decoration:none;">
        <div class="card port-row" data-flip-id="{row["ticker"]}" style="display:flex; justify-content:space-between; align-items:center; border-left: 4px solid {color};">
            <div>
                <div style="display:flex; align-items:center; gap:8px;">
                    <div style="font-weight:bold; font-size:1.1rem; color:white;">{row['ticker']}</div>
                    <div style="display:flex; align-items:center; gap:8px;"><div style="font-size:0.6rem; background:{color}; color:black; padding:2px 6px; border-radius:6px; font-weight:bold;">RISK: {risk}</div><div style="font-size:0.6rem; background:{conf_bg}; color:black; padding:2px 6px; border-radius:6px; font-weight:bold;">CONF: {conf}</div></div>
                </div>
                {pl_html}
            </div>
            <div style="text-align:right;">
                <div style="color:white; font-weight:bold;">${price:,.2f}</div>
                <div style="color:{change_color}; font-size:0.8rem;">{arrow} {change:.2f}%</div>
            </div>
        </div>
    </a>
    """
    st.markdown(html, unsafe_allow_html=True)

def render_compact_watchlist(rows_list, current_token):
    """Small horizontal tiles for the 3 daily_watchlist picks.

    Shows: Ticker, label, price (if available), and % score (fallback to day_change).
    """
    if not rows_list:
        st.info("No watchlist yet. The nightly job will populate it after market close.")
        return

    h = '<div class="scrolling-wrapper">'
    for row in rows_list:
        t = row.get("ticker")
        label = row.get("signal_tag") or "Momentum"

        price = row.get("current_price")
        score = row.get("_watchlist_score")
        if score is None:
            try:
                score = float(row.get("day_change") or 0)
            except Exception:
                score = 0

        # Format display
        price_txt = ""
        if price is not None:
            try:
                price_txt = f"${float(price):,.2f}"
            except Exception:
                price_txt = ""

        ch = float(score or 0)
        ch_txt = f"{ch:+.2f}%"
        ch_color = "#4ade80" if ch >= 0 else "#ef4444"

        link = f"?token={current_token}&ticker={t}"
        h += (
            f"<a href='{link}' target='_self' style='text-decoration:none; color:inherit; flex:1; min-width:0;'>"
            f"<div class='click-tile' style='background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); "
            f"border: 1px solid #334155; border-radius: 8px; padding: 10px; height: 100%; "
            f"display:flex; flex-direction:column; justify-content:space-between;'>"
            f"<div style='font-weight:bold; font-size:0.95rem; color:white; margin-bottom:2px;'>{t}</div>"
            f"<div style='font-size:0.65rem; color:#facc15; font-weight:bold; margin-bottom:6px; "
            f"white-space:nowrap; overflow:hidden; text-overflow:ellipsis;'>{label}</div>"
            f"<div style='display:flex; justify-content:space-between; align-items:center;'>"
            f"<div style='font-size:0.85rem; color:white; font-weight:bold;'>{price_txt}</div>"
            f"<div style='font-size:0.85rem; font-weight:bold; color:{ch_color};'>{ch_txt}</div>"
            f"</div>"
            f"</div></a>"
        )
    h += '</div>'
    st.markdown(h, unsafe_allow_html=True)

def _fmt_price(x):
    try:
        return f"${float(x):,.2f}"
    except Exception:
        return "—"

def _fmt_pct(x):
    try:
        return f"{float(x):+.2f}%"
    except Exception:
        return "0.00%"

def compute_anomaly_pick(rows):
    """Pick the biggest absolute % mover from the current watchlist rows."""
    if not rows:
        return None
    # Prefer true day_change if present, otherwise fall back to watchlist score
    def get_move(r):
        v = r.get("day_change")
        if v is None:
            v = r.get("_watchlist_score", 0) or 0
        try:
            return float(v)
        except Exception:
            return 0.0

    # Try to avoid duplicating the first 3 picks if possible
    primary = {r.get("ticker") for r in rows[:3] if r.get("ticker")}
    ranked = sorted(rows, key=lambda r: abs(get_move(r)), reverse=True)
    chosen = None
    for r in ranked:
        if r.get("ticker") and r.get("ticker") not in primary:
            chosen = r
            break
    if chosen is None and ranked:
        chosen = ranked[0]

    if not chosen:
        return None

    anomaly = dict(chosen)
    anomaly["signal_tag"] = "Anomaly Pick"
    anomaly["_is_anomaly"] = True
    return anomaly

def render_watchlist_pick_grid(rows, current_token=None):
    """Render 2x2 grid of pick cards: first 3 watchlist rows + anomaly pick."""
    if not rows:
        return

    cards = list(rows[:3])
    anomaly = compute_anomaly_pick(rows)
    if anomaly:
        # Avoid exact duplicate card (same ticker + label already)
        if not any((c.get("ticker")==anomaly.get("ticker") and c.get("signal_tag")==anomaly.get("signal_tag")) for c in cards):
            cards.append(anomaly)
    cards = cards[:4]

    # 2 rows of 2
    for row_i in range(0, len(cards), 2):
        cols = st.columns(2)
        for j in range(2):
            k = row_i + j
            if k >= len(cards):
                continue
            r = cards[k]
            ticker = r.get("ticker","")
            label = r.get("signal_tag","Pick")
            price = _fmt_price(r.get("current_price"))
            move = r.get("day_change")
            if move is None:
                move = r.get("_watchlist_score", 0) or 0
            pct = _fmt_pct(move)

            try:
                mv = float(move)
            except Exception:
                mv = 0.0
            color = "#22c55e" if mv > 0 else ("#ef4444" if mv < 0 else "#94a3b8")

            href = f"?tab=portfolio&ticker={ticker}"
            if current_token:
                href = f"?token={current_token}&tab=portfolio&ticker={ticker}"

            with cols[j]:
                st.markdown(f"""
<a href='{href}' style='text-decoration:none;'>
  <div class='card' style='padding:16px; min-height:118px; cursor:pointer;'>
    <div style='display:flex; align-items:flex-start; justify-content:space-between; gap:10px;'>
      <div>
        <div style='font-weight:800; font-size:1.35rem; color:#e5e7eb; line-height:1.1;'>{ticker}</div>
        <div style='margin-top:6px; font-size:0.85rem; color:#facc15; font-weight:700;'>{label}</div>
      </div>
      <div style='price-block'>
        <div style='font-weight:800; font-size:1.25rem; color:#e5e7eb;'>{price}</div>
        <div style='margin-top:6px; font-weight:800; font-size:1.05rem; color:{color};'>{pct}</div>
      </div>
      </div>
    </div>
  </div>
</a>
""", unsafe_allow_html=True)

def render_simple_card(row, current_token):
    p = float(row['current_price']); ch = float(row['day_change']); cc = "#4ade80" if ch>=0 else "#ef4444"; arr = "▲" if ch>=0 else "▼"
    link = f"?token={current_token}&ticker={row['ticker']}"
    risk, _, _, _, _ = calculate_risk(row)
    html = f'<a href="{link}" target="_self" style="text-decoration:none; color:inherit; display:block;"><div class="card clickable-card" style="display:flex; justify-content:space-between; align-items:center; padding:15px;"><div><div style="font-weight:bold; font-size:1.1rem; color:white;">{row["ticker"]}</div><div style="font-size:0.8rem; color:#94a3b8;">Risk: {risk}</div></div><div style="text-align:right;"><div style="color:white; font-weight:bold;">${p:,.2f}</div><div style="color:{cc}; font-size:0.8rem;">{arr} {ch:.2f}%</div></div></div></a>'
    st.markdown(html, unsafe_allow_html=True)

def render_horizontal_grid(rows_dict, current_token):
    # Small scroller tiles: ticker + price + % (pulled from stock_cache).
    # Layout: ticker (top) then price then % on its own line so all tiles stay the same height.
    h = '<div class="scrolling-wrapper">'
    for ticker, row in rows_dict.items():
        try:
            price = float(row.get('current_price') or 0)
        except Exception:
            price = 0.0
        try:
            ch = float(row.get('day_change') or 0)
        except Exception:
            ch = 0.0

        cc = "#4ade80" if ch >= 0 else "#ef4444"
        arr = "▲" if ch >= 0 else "▼"
        link = f"?token={current_token}&ticker={ticker}"

        price_txt = f"${price:,.2f}" if price > 0 else "—"

        h += (
            f'<a href="{link}" target="_self" style="text-decoration:none; color:inherit;">'
            f'  <div class="scrolling-card click-tile" style="display:flex; flex-direction:column; justify-content:space-between; min-height:88px;">'
            f'    <div style="font-weight:bold; font-size:1.05rem; color:white; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">{ticker}</div>'
            f'    <div style="font-size:0.95rem; color:white; font-weight:bold; margin-top:6px;">{price_txt}</div>'
            f'    <div style="font-size:0.85rem; color:{cc}; font-weight:bold; margin-top:4px;">{arr} {ch:.2f}%</div>'
            f'  </div>'
            f'</a>'
        )
    h += '</div>'
    st.markdown(h, unsafe_allow_html=True)

def get_greeting(name):
    hour = datetime.now(pytz.timezone('America/Halifax')).hour
    if hour < 12: return f"Good Morning, {name}"
    elif 12 <= hour < 18: return f"Good Afternoon, {name}"
    else: return f"Good Evening, {name}"


# =========================================================
# 3. MAIN EXECUTION
# =========================================================
init_db()

components.html("""<script>setTimeout(function(){window.parent.location.reload();}, 120000);</script>""", height=0)

if "token" not in st.query_params:
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.image("logo.png", width=220)
        st.markdown("<div style='height:10px;'></div>", unsafe_allow_html=True)
    tab1, tab2, tab3 = st.tabs(["Login", "Register", "Forgot PIN"])
    with tab1:
        with st.form("login_form"):
            u = st.text_input("Username"); p = st.text_input("PIN", type="password")
            if st.form_submit_button("Login"):
                user_record = login_user(u, p)
                if user_record:
                    new_token = create_session(u); st.query_params["token"] = new_token; st.rerun()
                else: st.error("Invalid Credentials")
    with tab2:
        with st.form("reg_form"):
            u = st.text_input("New Username"); p = st.text_input("New PIN", type="password"); d = st.text_input("Display Name")
            if st.form_submit_button("Create Account"):
                if register_user(u, p, d, ""): st.success("Account created! Please login.")
                else: st.error("Username taken.")
    st.stop()

user = get_user_from_token(token)
if not user: st.error("Session Expired"); st.stop()

current_mode = st.query_params.get("mode", "REAL")
if current_mode not in ["REAL", "PAPER"]: current_mode = "REAL"

c1, c2 = st.columns([2, 1])
with c1: st.markdown(f"### {get_greeting(user['display_name'])}")
with c2:
    is_paper = st.checkbox("Paper Trading", value=(current_mode=="PAPER"))
    new_mode = "PAPER" if is_paper else "REAL"
    if new_mode != current_mode: st.query_params["mode"] = new_mode; st.rerun()

if current_mode == "PAPER":
    st.markdown(f"<div style='background:#1e293b; padding:10px; border-radius:8px; color:#4ade80; font-weight:bold; text-align:center;'>💵 Balance: ${float(user['paper_balance']):,.2f}</div>", unsafe_allow_html=True)

if "ticker" in st.query_params:
    ticker = st.query_params["ticker"]
    stock = get_single_stock(ticker)
    if st.button("← Back", key="back_btn"): del st.query_params["ticker"]; st.rerun()
    if stock:
        news_items = get_news_data(ticker)
        headlines_txt = "\n".join([f"- {n['title']}" for n in news_items]) if news_items else ""
        ai_summary, ai_score, ai_source = get_ai_analysis(ticker, headlines_txt, stock)
        s, l, c, _, r = calculate_risk(stock, ai_score)
        confidence = calculate_confidence(stock, ai_score)
        p = float(stock['current_price']); ch = float(stock['day_change']); cc = "#4ade80" if ch>=0 else "#ef4444"
        
        st.markdown(f"<h1 style='margin:0; font-size: 2.5rem;'>{ticker}</h1>", unsafe_allow_html=True)
        st.markdown(f"<h2 style='margin:0; color:{cc}; font-size: 1.5rem;'>${p:,.2f} <span style='font-size:1rem; opacity:0.8;'>({ch:.2f}%) Today</span></h2>", unsafe_allow_html=True)
        
        if current_mode == "PAPER":
            st.markdown("---")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Buy 10", use_container_width=True):
                    ok, msg = execute_paper_trade(user['username'], ticker, "BUY", 10, p)
                    if ok: st.success("Bought 10!"); st.rerun()
                    else: st.error(msg)
            with c2:
                if st.button("Sell 10", use_container_width=True):
                    ok, msg = execute_paper_trade(user['username'], ticker, "SELL", 10, p)
                    if ok: st.success("Sold 10!"); st.rerun()
                    else: st.error(msg)
            st.markdown("---")

        st.markdown(create_gauge_html(s, l, c, "big"), unsafe_allow_html=True)
        st.markdown(f"""<div class='card' style='margin-top:12px; padding:18px;'>
            <div style='color:#94a3b8; font-size:0.8rem; font-weight:bold; letter-spacing:1px; margin-bottom:6px;'>CONFIDENCE</div>
            <div style='display:flex; align-items:center; gap:14px;'>
                <div style='font-size:2rem; font-weight:bold; color:white; line-height:1;'>{confidence}</div>
                <div style='flex:1; height:10px; background:#334155; border-radius:999px; overflow:hidden;'>
                    <div style='width:{confidence}%; height:100%; background:linear-gradient(90deg, #ef4444 0%, #fbbf24 50%, #4ade80 100%);'></div>
                </div>
            </div>
        </div>""", unsafe_allow_html=True)

        play = generate_playbook(stock)
        if play:
            st.markdown(
                textwrap.dedent(f"""
<div class='card' style='margin-top:15px;'>
  <div style='color:#94a3b8; font-size:0.8rem; font-weight:bold; letter-spacing:1px; margin-bottom:10px;'>
    SMART PLAYBOOK
  </div>

  <div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; gap:10px;'>
    <div style='font-size:1.05rem; font-weight:bold; color:white;'>{play["name"]}</div>
    <div style='font-size:0.75rem; color:#94a3b8; white-space:nowrap;'>Est. move: ${play["move"]}</div>
  </div>

  <div style='display:flex; gap:10px;'>
    <div class='metric-box' style='flex:1; padding:12px;'>
      <div class='metric-label'>Entry</div>
      <div class='metric-value'>${play["entry"]}</div>
    </div>
    <div class='metric-box' style='flex:1; padding:12px; border:1px solid #ef4444;'>
      <div class='metric-label'>Stop</div>
      <div class='metric-value' style='color:#ef4444;'>${play["stop"]}</div>
    </div>
  </div>

  <div style='display:flex; gap:10px; margin-top:10px;'>
    <div class='metric-box' style='flex:1; padding:12px; border:1px solid #4ade80;'>
      <div class='metric-label'>Target 1</div>
      <div class='metric-value' style='color:#4ade80;'>${play["t1"]}</div>
    </div>
    <div class='metric-box' style='flex:1; padding:12px; border:1px solid #4ade80;'>
      <div class='metric-label'>Target 2</div>
      <div class='metric-value' style='color:#4ade80;'>${play["t2"]}</div>
    </div>
  </div>

  <div style='margin-top:10px; font-size:0.9rem; color:#e0e6ed; line-height:1.4;'>
    {play["rationale"]}
  </div>
</div>
"""), unsafe_allow_html=True
            )
        st.markdown(f"<div class='card' style='margin-top:15px; padding: 25px;'><div style='color:#94a3b8; font-size:0.8rem; font-weight:bold; letter-spacing:1px; margin-bottom:15px;'>RISK FACTORS</div>", unsafe_allow_html=True)
        def get_pill(val, type="risk"):
            if type=="vol": return "pill-high" if val > 3 else "pill-low", "HIGH" if val > 3 else "LOW"
            if type=="debt": return "pill-high" if val > 150 else "pill-low", "HIGH" if val > 150 else "LOW"
            if type=="rsi": return "pill-med" if val > 70 or val < 30 else "pill-low", "EXTREME" if val > 70 or val < 30 else "NORMAL"
            return "pill-low", "LOW"
        
        # RISK FACTORS (Debt/Equity + Volatility + RSI)
        d_cls, d_txt = get_pill(float(stock.get('debt_ratio') or 0), "debt")
        st.markdown(f"<div class='risk-row'><div class='risk-label'>Debt/Equity</div><div class='risk-pill {d_cls}'>{d_txt}</div></div>", unsafe_allow_html=True)

        v_cls, v_txt = get_pill(float(stock.get('volatility') or 0), "vol")
        st.markdown(f"<div class='risk-row'><div class='risk-label'>Volatility</div><div class='risk-pill {v_cls}'>{v_txt}</div></div>", unsafe_allow_html=True)

        r_cls, r_txt = get_pill(float(stock.get('rsi') or 0), "rsi")
        st.markdown(f"<div class='risk-row' style='border:none;'><div class='risk-label'>RSI Momentum</div><div class='risk-pill {r_cls}'>{r_txt}</div></div></div>", unsafe_allow_html=True)
        # Risk breakdown (why the score moved)
        bd_rows = []
        for name, pts in r:
            try:
                pts_f = float(pts)
            except:
                pts_f = 0
            if abs(pts_f) < 0.1:
                continue
            bd_rows.append(
                f"<div style='padding:8px 0; border-bottom:1px solid #2d3748;'>"
                f"<div style='color:#e0e6ed; font-size:0.9rem;'>{name}</div>"
                f"</div>"
            )
        if bd_rows:
            st.markdown(
                "<div class='card' style='margin-top:12px; padding:18px;'>"
                "<div style='color:#94a3b8; font-size:0.8rem; font-weight:bold; letter-spacing:1px; margin-bottom:8px;'>WHY THIS SCORE</div>"
                + "".join(bd_rows) +
                "</div>",
                unsafe_allow_html=True
            )
        
        if ai_summary:
            ai_html = f"<div class='card' style='margin-top:15px; border:1px solid #4ade80;'><div style='color:#4ade80; font-size:0.8rem; font-weight:bold; letter-spacing:1px; margin-bottom:5px;'>{ai_source} INSIGHT (Score: {ai_score})</div><div style='font-size:0.9rem; color:white; line-height:1.4;'>{ai_summary}</div></div>"
            st.markdown(ai_html, unsafe_allow_html=True)

        if news_items:
            st.markdown(f"<div class='card' style='margin-top:15px;'><div style='color:#94a3b8; font-size:0.8rem; font-weight:bold; letter-spacing:1px; margin-bottom:15px;'>RECENT NEWS</div>", unsafe_allow_html=True)
            for item in news_items:
                st.markdown(f"<a href='{item['link']}' target='_blank' style='text-decoration:none;'><div style='font-size:0.95rem; font-weight:bold; color:#ffffff; margin-bottom:5px;'>{item['title']}</div><div style='font-size:0.75rem; color:#64748b; margin-bottom:15px;'>{item['time']} • {item['pub']}</div></a><div style='border-bottom:1px solid #2d3748; margin-bottom:15px;'></div>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)
        
        if st.button(f"🔔 Set Alert for {ticker}", key="alert_action_btn"):
            st.query_params["tab"] = "alerts"; del st.query_params["ticker"]; st.rerun()
    else: st.error("Data missing.")
    render_navbar(token, current_mode); st.stop()

tab = st.query_params.get("tab", "home")
if tab == "home":
    try:
        conn = get_connection(); cursor = conn.cursor()
        cursor.execute("SELECT content FROM daily_briefing WHERE id=1")
        row = cursor.fetchone()
        briefing_text = row[0] if row else ""
        conn.close()

        # --- Normalize briefing text for HTML rendering ---
        if briefing_text:
            # Fix common mojibake (UTF-8 interpreted as Latin-1)
            if any(x in briefing_text for x in ['â', 'Ã', 'Â']):
                try:
                    briefing_text = briefing_text.encode('latin1', errors='ignore').decode('utf-8', errors='ignore')
                except Exception:
                    pass
            briefing_text = briefing_text.replace("\r\n", "\n").replace("\r", "\n")
            briefing_text = briefing_text.replace("\n", "<br>")

        st.markdown(
            f"""<div class="card" style="border-left: 4px solid #facc15; margin-bottom: 20px;">
                <div style="color:#facc15; font-size:0.8rem; font-weight:bold; letter-spacing:1px; margin-bottom:10px;">AI MORNING BRIEFING</div>
                <div style="font-size:0.95rem; line-height:1.5; color:#e0e6ed;">{briefing_text}</div>
            </div>""",
            unsafe_allow_html=True
        )
    except:
        pass
    
    st.markdown("### Portfolio Overview")
    portfolio = get_portfolio_details(user['username'], current_mode)
    if not portfolio: st.info(f"Your {current_mode} portfolio is empty.")
    else:
        tickers = [r['ticker'] for r in portfolio]
        data_map = get_cached_data_map(tickers)
        valid_rows = [data_map[t] for t in tickers if t in data_map]
        if valid_rows:
            avg = sum([calculate_risk(x)[0] for x in valid_rows])/len(valid_rows)
            st.markdown(create_gauge_html(int(avg), "MEDIUM" if avg<65 else "HIGH", "#fbbf24" if avg<65 else "#ef4444", "big"), unsafe_allow_html=True)
            
            # THE BIG 3 METRICS ROW
            riskiest = max(valid_rows, key=lambda x: calculate_risk(x)[0])
            volatile = max(valid_rows, key=lambda x: abs(float(x['day_change'])))
            e_list = []
            for r in valid_rows:
                d_val = parse_smart_date(r.get('next_earnings'))
                if d_val < 365: e_list.append((r['ticker'], d_val))
            e_text = min(e_list, key=lambda x: x[1])[0] if e_list else "N/A"
            st.markdown(f"""<div style="display:flex; justify-content:space-between; background:#151922; padding:15px; border-radius:0 0 16px 16px; margin-top:-14px; margin-bottom:30px; border:1px solid #2d3748; border-top:none;"><div style="text-align:center; width:33%; border-right:1px solid #2d3748;"><div style="color:#94a3b8; font-size:0.6rem; text-transform:uppercase;">Highest Risk</div><div style="color:white; font-weight:bold; font-size:1rem;">{riskiest['ticker']}</div></div><div style="text-align:center; width:33%; border-right:1px solid #2d3748;"><div style="color:#94a3b8; font-size:0.6rem; text-transform:uppercase;">Most Volatile</div><div style="color:white; font-weight:bold; font-size:1rem;">{volatile['ticker']}</div></div><div style="text-align:center; width:33%;"><div style="color:#94a3b8; font-size:0.6rem; text-transform:uppercase;">Next Earnings</div><div style="color:white; font-weight:bold; font-size:1rem;">{e_text}</div></div></div>""", unsafe_allow_html=True)
            
            render_horizontal_grid(data_map, token)
            
    w_date = get_watchlist_header_date()
    st.markdown(f"### {w_date} Watchlist")
    candidates = get_watchlist_rows_for_home()
    render_watchlist_pick_grid(candidates, token)
    #render_compact_watchlist(candidates, token)

elif tab == "portfolio":
    st.markdown(f"### My Stocks ({current_mode})")
    total_pl, total_pct, day_pl, day_pct = get_portfolio_summary(user['username'], current_mode)
    c_pl = "#4ade80" if total_pl >= 0 else "#ef4444"
    c_day = "#4ade80" if day_pl >= 0 else "#ef4444"
    st.markdown(f"""<div style="display:flex; gap:10px; margin-bottom:20px;"><div class="metric-box" style="flex:1;"><div class="metric-label">Total P/L</div><div class="metric-value" style="color:{c_pl}">${total_pl:,.2f}</div><div class="metric-sub" style="color:{c_pl}">({total_pct:+.2f}%)</div></div><div class="metric-box" style="flex:1;"><div class="metric-label">Today's P/L</div><div class="metric-value" style="color:{c_day}">${day_pl:,.2f}</div><div class="metric-sub" style="color:{c_day}">({day_pct:+.2f}%)</div></div></div>""", unsafe_allow_html=True)

    if current_mode == "REAL":
        with st.expander("Manage Holdings", expanded=False):
            t1, t2, t3 = st.tabs(["Add Stock", "Edit Position", "Remove Stock"])
            with t1:
                with st.form("add_stock"):
                    c1, c2, c3 = st.columns([2, 1, 1])
                    new_t = c1.text_input("Ticker"); shares = c2.number_input("Shares"); price = c3.number_input("Avg Price")
                    if st.form_submit_button("Add to Portfolio"):
                        if new_t: add_ticker_to_db(user['username'], new_t.upper(), shares, price, 'REAL'); st.rerun()
            with t2:
                port_rows = get_portfolio_details(user['username'], 'REAL')
                if port_rows:
                    with st.form("edit_pos"):
                        edit_t = st.selectbox("Select Stock", [r['ticker'] for r in port_rows])
                        c1, c2 = st.columns(2); new_s = c1.number_input("New Shares"); new_p = c2.number_input("New Avg Price")
                        if st.form_submit_button("Update Position"):
                            update_ticker_in_db(user['username'], edit_t, new_s, new_p, 'REAL'); st.rerun()
                else: st.info("Empty Portfolio")
            with t3:
                port_rows = get_portfolio_details(user['username'], 'REAL')
                if port_rows:
                    to_remove = st.selectbox("Select Stock to Remove", [r['ticker'] for r in port_rows])
                    if st.button("Remove Selected", type="primary"):
                        deactivate_stock(user['username'], to_remove, 'REAL'); st.rerun()
                else: st.info("Portfolio is empty.")
    
    st.divider()
    port_rows = get_portfolio_details(user['username'], current_mode)
    if port_rows:
        tickers = [r['ticker'] for r in port_rows]
        market_data = get_cached_data_map(tickers)
        pairs = [(row, market_data[row['ticker']]) for row in port_rows if row['ticker'] in market_data]
        pairs.sort(key=lambda x: float(x[1].get('day_change') or 0), reverse=True)

        for row, data in pairs:
            render_portfolio_row(row, data, token)
        # (Reorder animation disabled for stability)

elif tab == "alerts":
    st.markdown("### Volatility Alerts")
    with st.expander("New Alert", expanded=True):
        port_rows = get_portfolio_details(user['username'], current_mode)
        options = ["ALL STOCKS"] + [r['ticker'] for r in port_rows]
        if port_rows:
            t = st.selectbox("Ticker", options); c = st.selectbox("Trigger", ["DOWN", "UP"]); v = st.number_input("Target Price")
            if st.button("Set Alert"): add_alert(user['username'], t, c, v); st.rerun()
        else: st.info("Add stocks first.")
    st.divider()
    alerts = get_user_alerts(user['username'])
    for a in alerts:
        bg = "#3d1111" if a['is_triggered'] else "#1a1f2b"; border = "#ef4444" if a['is_triggered'] else "#2d3748"
        st.markdown(f"""<div style="background:{bg}; border:1px solid {border}; border-radius:12px; padding:15px; margin-bottom:10px; display:flex; justify-content:space-between;"><div><div style="font-weight:bold; color:white;">{a['ticker']}</div><div style="font-size:0.85rem; color:#94a3b8;">{a['condition_type']} {a['target_price']}</div></div></div>""", unsafe_allow_html=True)
        if st.button("Clear", key=f"del_al_{a['id']}"): delete_alert(a['id']); st.rerun()

elif tab == "scanner":
    st.markdown("### Market Scanner")
    port_rows = get_portfolio_details(user['username'], current_mode)
    tickers = [r['ticker'] for r in port_rows]
    market_data = get_cached_data_map(tickers)
    if market_data:
        st.markdown("**📉 Oversold (RSI < 40)**")
        for t, data in market_data.items():
            rsi_val = data.get('rsi')
            if rsi_val is not None and float(rsi_val) < 40:
                render_simple_card(data, token)
        st.markdown("**📅 Earnings Soon**")
        for t, data in market_data.items():
            d_val = parse_smart_date(data.get('next_earnings'))
            if d_val < 14: render_simple_card(data, token)

elif tab == "settings":
    st.markdown("### Settings")
    with st.form("settings_form"):
        new_name = st.text_input("Display Name", value=user['display_name'])
        new_email = st.text_input("Recovery Email", value=user.get('email', ''))
        new_pin = st.text_input("New PIN", type="password")
        if st.form_submit_button("Save Changes"):
            if update_user_settings(user['username'], new_name, new_email, new_pin if new_pin else None): st.success("Saved!"); st.rerun()
    if st.button("Log Out"): st.query_params.clear(); st.rerun()

render_navbar(token, current_mode)
