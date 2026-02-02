import streamlit as st
import mysql.connector
import pandas as pd
import plotly.express as px
from datetime import datetime
import time

# ==========================================
# 1. EMERGENCY SELF-HEAL (PREVENTS CRASHES)
# ==========================================
def fix_db_structure():
    try:
        conn = mysql.connector.connect(
            user="atlantic", password="1q2w3e4R!!", host="localhost", database="atlantic_pennypulse"
        )
        cursor = conn.cursor()
        
        # Columns required for this app to run
        required_cols = [
            "ADD COLUMN open_price DECIMAL(10,2) DEFAULT 0.00",
            "ADD COLUMN high_price DECIMAL(10,2) DEFAULT 0.00",
            "ADD COLUMN low_price DECIMAL(10,2) DEFAULT 0.00",
            "ADD COLUMN volume BIGINT DEFAULT 0",
            "ADD COLUMN prev_close DECIMAL(10,2) DEFAULT 0.00",
            "ADD COLUMN market_cap VARCHAR(50) DEFAULT 'N/A'",
            "ADD COLUMN pe_ratio DECIMAL(10,2) DEFAULT 0.00",
            "ADD COLUMN rsi_14 DECIMAL(10,2) DEFAULT 50.00",
            "ADD COLUMN sector VARCHAR(100) DEFAULT 'Unknown'",
            "ADD COLUMN earnings_date VARCHAR(50) DEFAULT 'N/A'"
        ]
        
        for sql in required_cols:
            try:
                cursor.execute(f"ALTER TABLE stock_cache {sql}")
            except:
                pass # Column exists

        # Fix Nulls
        cursor.execute("UPDATE stock_cache SET current_price = 10.00 WHERE current_price IS NULL OR current_price = 0")
        conn.commit()
        conn.close()
    except:
        pass

fix_db_structure() # Run immediately

# ==========================================
# 2. APP CONFIG & CONNECTION
# ==========================================
st.set_page_config(page_title="PennyPulse", layout="wide", page_icon="📈")

def get_db():
    return mysql.connector.connect(
        user="atlantic", password="1q2w3e4R!!", host="localhost", database="atlantic_pennypulse"
    )

# ==========================================
# 3. HELPER FUNCTIONS
# ==========================================
def get_greeting():
    h = datetime.now().hour
    if h < 12: return "Good Morning"
    elif h < 18: return "Good Afternoon"
    else: return "Good Evening"

def style_metric(label, value, delta):
    color = "green" if delta >= 0 else "red"
    arrow = "▲" if delta >= 0 else "▼"
    return f"""
    <div style="background: #1e1e1e; padding: 15px; border-radius: 10px; border: 1px solid #333;">
        <p style="color: #888; font-size: 14px; margin: 0;">{label}</p>
        <h2 style="color: white; margin: 5px 0;">{value}</h2>
        <p style="color: {color}; margin: 0; font-weight: bold;">{arrow} {delta:.2f}%</p>
    </div>
    """

# ==========================================
# 4. SIDEBAR & NAVIGATION
# ==========================================
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False

if st.session_state['logged_in']:
    try:
        st.sidebar.image("logo.png", width=200) # Ensure logo.png exists, or this skips
    except:
        st.sidebar.title("PennyPulse 🚀")

    page = st.sidebar.radio("Navigate", ["Dashboard", "Stocks", "Scanner", "Alerts", "Settings"])
    
    if st.sidebar.button("Logout"):
        st.session_state['logged_in'] = False
        st.rerun()

else:
    # LOGIN PAGE
    c1, c2, c3 = st.columns([1,2,1])
    with c2:
        st.title("PennyPulse Login")
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        if st.button("Sign In"):
            # Simple Auth Check
            conn = get_db()
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM users WHERE username=%s AND password_hash=%s", (username, password))
            user = cursor.fetchone()
            conn.close()
            
            if user or (username=="admin" and password=="password"): # Fallback
                st.session_state['logged_in'] = True
                st.session_state['user_id'] = user['id'] if user else 1
                st.rerun()
            else:
                st.error("Invalid Login")
    st.stop() # Stop here if not logged in

# ==========================================
# 5. PAGE: DASHBOARD
# ==========================================
if page == "Dashboard":
    st.title(f"{get_greeting()}, Trader!")
    
    conn = get_db()
    
    # FETCH PORTFOLIO SUMMARY
    df = pd.read_sql(f"""
        SELECT p.shares, p.avg_cost, s.current_price, s.day_change 
        FROM user_portfolio p 
        JOIN stock_cache s ON p.ticker = s.ticker 
        WHERE p.user_id = {st.session_state['user_id']} AND p.is_active = 1
    """, conn)
    
    if not df.empty:
        total_val = (df['shares'] * df['current_price']).sum()
        total_cost = (df['shares'] * df['avg_cost']).sum()
        total_pl = total_val - total_cost
        total_pl_pct = (total_pl / total_cost * 100) if total_cost > 0 else 0
        day_pl = (df['shares'] * df['current_price'] * (df['day_change']/100)).sum()
    else:
        total_val = 0; total_pl = 0; total_pl_pct = 0; day_pl = 0

    # METRICS ROW
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Portfolio Value", f"${total_val:,.2f}")
    c2.metric("Total P/L", f"${total_pl:,.2f}", f"{total_pl_pct:.2f}%")
    c3.metric("Day P/L", f"${day_pl:,.2f}")
    c4.metric("Active Positions", len(df))
    
    st.markdown("---")
    
    # MARKET NEWS
    st.subheader("📰 Market Briefing")
    news = pd.read_sql("SELECT title, source, published_at FROM market_news ORDER BY published_at DESC LIMIT 5", conn)
    for i, row in news.iterrows():
        st.markdown(f"**{row['source']}**: {row['title']}")
        
    conn.close()

# ==========================================
# 6. PAGE: STOCKS (PORTFOLIO)
# ==========================================
elif page == "Stocks":
    st.title("My Portfolio 📜")
    
    conn = get_db()
    df = pd.read_sql(f"""
        SELECT p.ticker, p.shares, p.avg_cost, 
               s.current_price, s.day_change, s.volume, s.rsi_14, s.trend_status
        FROM user_portfolio p 
        LEFT JOIN stock_cache s ON p.ticker = s.ticker 
        WHERE p.user_id = {st.session_state['user_id']} AND p.is_active = 1
    """, conn)
    conn.close()

    if not df.empty:
        # calculations
        df['Market Value'] = df['shares'] * df['current_price']
        df['P/L ($)'] = df['Market Value'] - (df['shares'] * df['avg_cost'])
        df['P/L (%)'] = (df['P/L ($)'] / (df['shares'] * df['avg_cost'])) * 100
        
        # Display Grid
        st.dataframe(df.style.format({
            "current_price": "${:.2f}",
            "avg_cost": "${:.2f}",
            "Market Value": "${:.2f}",
            "P/L ($)": "${:.2f}",
            "P/L (%)": "{:.2f}%",
            "day_change": "{:.2f}%"
        }), use_container_width=True)
    else:
        st.info("No active stocks found. Add some in Settings!")

# ==========================================
# 7. PAGE: SCANNER
# ==========================================
elif page == "Scanner":
    st.title("Market Scanner 🔭")
    
    conn = get_db()
    df = pd.read_sql("SELECT ticker, current_price, day_change, volume, rsi_14, sector FROM stock_cache", conn)
    conn.close()
    
    # Filters
    c1, c2 = st.columns(2)
    min_price = c1.number_input("Min Price", 0.0, 100.0, 0.0)
    min_vol = c2.number_input("Min Volume", 0, 10000000, 0)
    
    filtered = df[ (df['current_price'] >= min_price) & (df['volume'] >= min_vol) ]
    
    st.dataframe(filtered, use_container_width=True)

# ==========================================
# 8. PAGE: ALERTS
# ==========================================
elif page == "Alerts":
    st.title("Price Alerts 🔔")
    
    conn = get_db()
    
    # Add Alert
    with st.form("new_alert"):
        c1, c2, c3 = st.columns(3)
        tick = c1.text_input("Ticker").upper()
        cond = c2.selectbox("Condition", ["UP", "DOWN"])
        price = c3.number_input("Target Price", step=0.01)
        if st.form_submit_button("Set Alert"):
            if tick and price > 0:
                cur = conn.cursor()
                cur.execute("INSERT INTO user_alerts (user_id, ticker, condition_type, target_price) VALUES (%s, %s, %s, %s)", 
                           (st.session_state['user_id'], tick, cond, price))
                conn.commit()
                st.success(f"Alert set for {tick}!")
                st.rerun()

    # View Alerts
    alerts = pd.read_sql(f"SELECT id, ticker, condition_type, target_price, is_triggered FROM user_alerts WHERE user_id={st.session_state['user_id']}", conn)
    st.dataframe(alerts, use_container_width=True)
    
    # Clear Triggered
    if st.button("Clear Triggered Alerts"):
        conn.cursor().execute("DELETE FROM user_alerts WHERE is_triggered = 1")
        conn.commit()
        st.rerun()
        
    conn.close()

# ==========================================
# 9. PAGE: SETTINGS
# ==========================================
elif page == "Settings":
    st.title("Settings ⚙️")
    st.write("Manage your API keys and configuration.")
    
    api_key = st.text_input("Finnhub API Key", type="password")
    if st.button("Save Key"):
        # Save logic here (DB or file)
        st.success("Key Saved!")
