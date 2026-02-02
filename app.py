import streamlit as st
import mysql.connector
import yfinance as yf
import requests
import uuid
import os
import pandas as pd
import pytz
import json
import xml.etree.ElementTree as ET
import streamlit.components.v1 as components
from datetime import datetime, timedelta

# =========================================================
# 1. CONFIGURATION & CSS
# =========================================================
st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="centered", initial_sidebar_state="collapsed")

st.markdown("""
    <style>
        .block-container { padding-top: 0rem !important; padding-bottom: 5rem !important; }
        .stApp { background-color: #0f1219 !important; color: #e0e6ed !important; }
        
        input[type="text"], input[type="password"], input[type="number"] { 
            background-color: #1e293b !important; color: white !important; 
            border: 1px solid #4ade80 !important; border-radius: 8px; padding: 10px;
        }
        
        div[data-baseweb="select"] > div { 
            background-color: #1e293b !important; color: white !important; border: 1px solid #4ade80 !important; 
        }
        li[role="option"]:hover { background-color: #4ade80 !important; color: black !important; }
        
        .card { 
            background-color: #1a1f2b; border-radius: 16px; padding: 20px; 
            margin-bottom: 10px; border: 1px solid #2d3748; box-shadow: 0 4px 6px rgba(0,0,0,0.3); 
        }
        
        .metric-box {
            background-color: #1e293b; border: 1px solid #2d3748; border-radius: 12px;
            padding: 15px; text-align: center; margin-bottom: 10px;
        }
        
        div.stButton > button {
            background: linear-gradient(135deg, #4ade80, #16a34a) !important; 
            color: white !important; border: none; border-radius: 8px; 
            font-weight: bold; width: 100%; padding: 12px 20px;
        }

        .nav-container { 
            position: fixed; bottom: 0; left: 0; width: 100%; height: 65px; 
            background-color: #0f1219; border-top: 1px solid #2d3748; 
            display: flex; justify-content: space-around; align-items: center; z-index: 99999; 
        }
        
        .scrolling-wrapper { 
            display: flex; flex-wrap: nowrap; overflow-x: auto; gap: 12px; 
            padding-bottom: 20px; margin-top: 10px; -ms-overflow-style: none; scrollbar-width: none; 
        }
        .scrolling-wrapper::-webkit-scrollbar { display: none; }
        
        .risk-pill { padding: 4px 10px; border-radius: 20px; font-size: 0.75rem; font-weight: bold; text-transform: uppercase; }
        .pill-low { background: rgba(74, 222, 128, 0.2); color: #4ade80; }
        .pill-med { background: rgba(251, 191, 36, 0.2); color: #fbbf24; }
        .pill-high { background: rgba(239, 68, 68, 0.2); color: #ef4444; }
        .risk-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; border-bottom: 1px solid #2d3748; padding-bottom: 5px; }
        
        header {visibility: hidden;} footer {visibility: hidden;} 
    </style>
""", unsafe_allow_html=True)

DB_CONFIG = {"host": "atlanticcanadaschoice.com", "user": "atlantic", "password": "1q2w3e4R!!", "database": "atlantic_pennypulse", "connect_timeout": 30}
OPENAI_KEY = st.secrets["openai"]["api_key"] if "openai" in st.secrets else None
token = st.query_params.get("token", None)

# =========================================================
# 2. CORE FUNCTIONS
# =========================================================

def get_connection(): return mysql.connector.connect(**DB_CONFIG)

def parse_smart_date(date_str):
    if not date_str or str(date_str).lower() in ['n/a', 'none', '', '999']: return 999
    try:
        now = datetime.now()
        target = datetime.strptime(f"{date_str} {now.year}", "%b %d %Y")
        if target < now: target = datetime.strptime(f"{date_str} {now.year + 1}", "%b %d %Y")
        return (target - now).days
    except: return 999

def get_user_from_token(t):
    conn = get_connection(); cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT s.username, p.display_name, p.paper_balance, p.email FROM user_sessions s JOIN user_profiles p ON s.username=p.username WHERE s.token=%s", (t,))
    row = cursor.fetchone(); conn.close(); return row

def calculate_risk(row, ai_score=None):
    s = 50
    rsi = float(row.get('rsi') or 50)
    if rsi > 70: s += 10
    elif rsi < 30: s -= 10
    vol = float(row.get('volatility') or 0)
    if vol > 3.0: s += 15
    if ai_score: s += (50 - ai_score) * 0.5
    final = max(0, min(100, int(s)))
    color = "#4ade80" if final < 35 else "#fbbf24" if final < 65 else "#ef4444"
    label = "LOW" if final < 35 else "MEDIUM" if final < 65 else "HIGH"
    return final, label, color, "badge-mix", []

def get_portfolio_summary(username, ptype):
    conn = get_connection(); cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT SUM(realized_pl) as realized FROM user_portfolio WHERE username=%s AND portfolio_type=%s AND is_active=FALSE", (username, ptype))
    realized = float(cursor.fetchone()['realized'] or 0)
    cursor.execute("SELECT p.shares, p.entry_price, s.current_price, s.day_change FROM user_portfolio p LEFT JOIN stock_cache s ON p.ticker = s.ticker WHERE p.username=%s AND p.portfolio_type=%s AND p.is_active=TRUE", (username, ptype))
    active_rows = cursor.fetchall(); conn.close()
    unrealized = 0.0; day_pl = 0.0; active_cost = 0.0; curr_val = 0.0
    for r in active_rows:
        if r['current_price']:
            c = float(r['current_price']); e = float(r['entry_price']); s = float(r['shares'])
            unrealized += (c - e) * s; active_cost += (e * s); curr_val += (c * s)
            pct = float(r['day_change'] or 0); prev = c / (1 + (pct/100))
            day_pl += (c - prev) * s
    total_pl = realized + unrealized
    total_pct = (total_pl / active_cost) * 100 if active_cost > 0 else 0
    day_pct = (day_pl / (curr_val - day_pl)) * 100 if (curr_val - day_pl) > 0 else 0
    return total_pl, total_pct, day_pl, day_pct

# =========================================================
# 3. UI COMPONENTS
# =========================================================

def create_gauge_html(score, label, color, size="big"):
    rad = 80 if size == "big" else 60
    vb = "0 0 200 120" if size == "big" else "0 0 160 100"
    fill = (score / 100) * (3.14159 * rad)
    header = f'<div style="text-align:center; color:#94a3b8; font-size:0.8rem; font-weight:bold; letter-spacing:1px; margin-bottom:5px;">PORTFOLIO RISK</div>'
    return f"""
    <div class="card" style="padding-bottom:0; margin-bottom:0;">
        {header}
        <svg viewBox="{vb}" style="width:100%; height:auto;">
            <defs>
                <linearGradient id="gGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                    <stop offset="0%" style="stop-color:#4ade80;" /><stop offset="50%" style="stop-color:#fbbf24;" /><stop offset="100%" style="stop-color:#ef4444;" />
                </linearGradient>
            </defs>
            <path d="M 20 100 A {rad} {rad} 0 0 1 {20+rad*2} 100" fill="none" stroke="#334155" stroke-width="15" stroke-linecap="round"/>
            <path d="M 20 100 A {rad} {rad} 0 0 1 {20+rad*2} 100" fill="none" stroke="url(#gGrad)" stroke-width="15" stroke-linecap="round" stroke-dasharray="{fill}, 1000"/>
            <text x="{20+rad}" y="80" font-family="sans-serif" font-size="38" font-weight="bold" fill="white" text-anchor="middle">{score}</text>
            <text x="{20+rad}" y="100" font-family="sans-serif" font-size="12" font-weight="bold" fill="{color}" text-anchor="middle">{label}</text>
        </svg>
    </div>"""

def render_horizontal_grid(rows_dict, current_token):
    h = '<div class="scrolling-wrapper">'
    for ticker, row in rows_dict.items():
        ch = float(row['day_change']); cc = "#4ade80" if ch>=0 else "#ef4444"
        h += f'<a href="?token={current_token}&ticker={ticker}" target="_self" style="text-decoration:none;"><div class="scrolling-card"><div style="font-weight:bold; color:white;">{ticker}</div><div style="color:{cc}; font-size:0.85rem;">{"▲" if ch>=0 else "▼"} {abs(ch):.2f}%</div></div></a>'
    h += '</div>'
    st.markdown(h, unsafe_allow_html=True)

# =========================================================
# 4. TAB LOGIC
# =========================================================

user = get_user_from_token(token)
if not user: st.stop()
current_mode = st.query_params.get("mode", "REAL")
tab = st.query_params.get("tab", "home")

if tab == "home":
    # 1. Gauge & Summary Metrics
    portfolio = get_portfolio_details(user['username'], current_mode)
    if portfolio:
        tickers = [r['ticker'] for r in portfolio]
        data_map = get_cached_data_map(tickers)
        valid_rows = [data_map[t] for t in tickers if t in data_map]
        if valid_rows:
            avg_risk = sum([calculate_risk(x)[0] for x in valid_rows])/len(valid_rows)
            risk_lbl = "LOW" if avg_risk < 35 else "MEDIUM" if avg_risk < 65 else "HIGH"
            risk_col = "#4ade80" if avg_risk < 35 else "#fbbf24" if avg_risk < 65 else "#ef4444"
            st.markdown(create_gauge_html(int(avg_risk), risk_lbl, risk_col), unsafe_allow_html=True)

            # THE BIG 3 BOXES
            riskiest = max(valid_rows, key=lambda x: calculate_risk(x)[0])
            volatile = max(valid_rows, key=lambda x: abs(float(x['day_change'])))
            earn_days = [(r['ticker'], parse_smart_date(r.get('next_earnings'))) for r in valid_rows]
            next_e = min(earn_days, key=lambda x: x[1])[0] if earn_days else "N/A"

            st.markdown(f"""
                <div style="display:flex; justify-content:space-between; background:#151922; padding:15px; border-radius:0 0 16px 16px; margin-top:-14px; border:1px solid #2d3748; border-top:none; margin-bottom:20px;">
                    <div style="text-align:center; width:33%; border-right:1px solid #2d3748;">
                        <div style="color:#94a3b8; font-size:0.6rem; text-transform:uppercase;">Highest Risk</div>
                        <div style="color:white; font-weight:bold;">{riskiest['ticker']}</div>
                    </div>
                    <div style="text-align:center; width:33%; border-right:1px solid #2d3748;">
                        <div style="color:#94a3b8; font-size:0.6rem; text-transform:uppercase;">Most Volatile</div>
                        <div style="color:white; font-weight:bold;">{volatile['ticker']}</div>
                    </div>
                    <div style="text-align:center; width:33%;">
                        <div style="color:#94a3b8; font-size:0.6rem; text-transform:uppercase;">Next Earnings</div>
                        <div style="color:white; font-weight:bold;">{next_e}</div>
                    </div>
                </div>
            """, unsafe_allow_html=True)
            render_horizontal_grid(data_map, token)
    
    # 2. Watchlist Section
    st.markdown(f"### {datetime.now().strftime('%b %d')} Watchlist")
    candidates = get_watchlist_candidates()
    render_compact_watchlist(candidates, token)

# Navigation
render_navbar(token, current_mode)
