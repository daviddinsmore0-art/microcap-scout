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

# --- NEWS & AI LIBS ---
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

ADMIN_PASSWORD = st.secrets.get("ADMIN_PASSWORD", "")
DB_CONFIG = {
    "host": st.secrets["DB_HOST"],
    "user": st.secrets["DB_USER"],
    "password": st.secrets["DB_PASS"],
    "database": st.secrets["DB_NAME"],
    "connect_timeout": 30,
}

def get_connection():
    return mysql.connector.connect(**DB_CONFIG)

# --- DYNAMIC UPDATE ENGINE (THE BACKUP BRAIN) ---
def run_backend_update():
    """Ensures data is fresh even if external workers sleep."""
    try:
        conn = get_connection(); cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT user_data FROM user_profiles")
        users = cursor.fetchall()
        needed = set(["^DJI", "^IXIC", "^GSPTSE", "GC=F"]) 
        for r in users:
            try:
                data = json.loads(r['user_data'])
                if 'w_input' in data: needed.update([t.strip().upper() for t in data['w_input'].split(",") if t.strip()])
                if 'portfolio' in data: needed.update(data['portfolio'].keys())
            except: pass
        
        format_strings = ','.join(['%s'] * len(needed))
        cursor.execute(f"SELECT ticker, last_updated FROM stock_cache WHERE ticker IN ({format_strings})", tuple(needed))
        existing = {row['ticker']: row['last_updated'] for row in cursor.fetchall()}
        
        to_fetch = [t for t in needed if not existing.get(t) or (datetime.now() - existing.get(t)).total_seconds() > 300]
        if not to_fetch: conn.close(); return

        for t in to_fetch:
            try:
                tk = yf.Ticker(t); hist = tk.history(period="1mo", interval="1d", timeout=10)
                if hist.empty: continue
                curr = float(hist['Close'].iloc[-1]); prev = float(hist['Close'].iloc[-2]) if len(hist)>1 else curr
                change = ((curr - prev) / prev) * 100
                trend = "UPTREND" if curr > hist['Close'].tail(20).mean() else "DOWNTREND"
                
                info = tk.info; name = info.get('shortName') or info.get('longName') or t
                rating = info.get('recommendationKey', 'N/A').upper().replace('_', ' ')
                
                # RSI & Volume
                delta = hist['Close'].diff(); g = delta.where(delta > 0, 0).rolling(14).mean(); l = (-delta.where(delta < 0, 0)).rolling(14).mean()
                rsi_val = 100 - (100 / (1 + (g / l).iloc[-1])) if not l.empty else 50.0
                vol_pct = (hist['Volume'].iloc[-1] / hist['Volume'].mean()) * 100 if not hist['Volume'].empty else 100

                # Pre/Post
                pp_p, pp_c = 0.0, 0.0
                try:
                    live = tk.history(period="1d", interval="1m", prepost=True)
                    if not live.empty:
                        lp = live['Close'].iloc[-1]
                        if abs(lp - curr) > 0.01: pp_p, pp_c = float(lp), float(((lp - curr)/curr)*100)
                except: pass

                sql = """INSERT INTO stock_cache (ticker, current_price, day_change, rsi, volume_status, trend_status, rating, price_history, company_name, pre_post_price, pre_post_pct)
                         VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE current_price=%s, day_change=%s, rsi=%s, volume_status=%s, trend_status=%s, rating=%s, price_history=%s, company_name=%s, pre_post_price=%s, pre_post_pct=%s"""
                j_p = json.dumps(hist['Close'].tail(20).tolist())
                vals = (t, curr, change, rsi_val, vol_pct, trend, rating, j_p, name, pp_p, pp_c, curr, change, rsi_val, vol_pct, trend, rating, j_p, name, pp_p, pp_c)
                cursor.execute(sql, vals); conn.commit()
            except: pass
        conn.close()
    except: pass

# --- UI LOGIC ---
st.markdown("""<style>
.block-container { padding-top: 0rem !important; }
div[data-testid="stVerticalBlock"] { background-color: #ffffff; border-radius: 12px; padding: 15px; box-shadow: 0 4px 10px rgba(0,0,0,0.05); border: 1px solid #f0f0f0; margin-bottom: 10px; }
.metric-label { font-size: 10px; color: #888; font-weight: 600; display: flex; justify-content: space-between; margin-top: 8px; text-transform: uppercase; }
.bar-bg { background: #eee; height: 5px; border-radius: 3px; width: 100%; margin-top: 3px; overflow: hidden; }
.bar-fill { height: 100%; border-radius: 3px; }
.info-pill { font-size: 10px; color: #333; background: #f8f9fa; padding: 3px 8px; border-radius: 4px; font-weight: 600; margin-right: 6px; display: inline-block; border: 1px solid #eee; }
</style>""", unsafe_allow_html=True)

# Startup
run_backend_update()

# --- LOGIN & CONTENT ---
# [Login, Session, Sidebar logic remains as per your original file]

# --- MAIN DRAW FUNCTION ---
def draw_card(t, port=None):
    """The full-featured card renderer."""
    try:
        conn = get_connection(); cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM stock_cache WHERE ticker = %s", (t,))
        d = cursor.fetchone(); conn.close()
        if not d: st.info(f"Processing {t}..."); return

        p, chg = float(d['current_price']), float(d['day_change'])
        b_col = "#4caf50" if chg >= 0 else "#ff4b4b"
        
        st.markdown(f"""<div style='display:flex; justify-content:space-between;'>
            <div><div style='font-size:20px; font-weight:bold;'>{t}</div><div style='font-size:11px; color:#888;'>{d['company_name'][:25]}</div></div>
            <div style='text-align:right;'><div style='font-size:20px; font-weight:bold;'>${p:,.2f}</div><div style='color:{b_col}; font-weight:bold;'>{chg:+.2f}%</div></div>
        </div>""", unsafe_allow_html=True)
        
        # Area Chart
        hist = json.loads(d['price_history'])
        c_df = pd.DataFrame({'x': range(len(hist)), 'y': hist})
        chart = alt.Chart(c_df).mark_area(line={'color': b_col}, color=alt.Gradient(gradient='linear', stops=[alt.GradientStop(color=b_col, offset=0), alt.GradientStop(color='white', offset=1)], x1=1, x2=1, y1=1, y2=0)).encode(x=alt.X('x', axis=None), y=alt.Y('y', axis=None, scale=alt.Scale(zero=False))).properties(height=50)
        st.altair_chart(chart, use_container_width=True)
        
        # Indicators
        rsi = float(d['rsi'])
        st.markdown(f"<div class='info-pill'>Trend: {d['trend_status']}</div><div class='info-pill'>RSI: {int(rsi)}</div><div class='info-pill'>Rating: {d['rating']}</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='metric-label'><span>RSI Strength</span></div><div class='bar-bg'><div class='bar-fill' style='width:{rsi}%; background:{b_col};'></div></div>", unsafe_allow_html=True)
    except: pass

# ... (Portfolio Math, News Tabs, and Scroller code continues here) ...

# Silent Refresh Loop
time.sleep(60)
st.rerun() # Refresh every 60s
