import os
import mysql.connector
import yfinance as yf
import pandas as pd
import json
from datetime import datetime

# --- CONFIG ---
DB_HOST = os.environ.get("DB_HOST") or "72.55.168.16"
DB_USER = os.environ.get("DB_USER") or "penny_user"
DB_PASS = os.environ.get("DB_PASS") or "123456"
DB_NAME = os.environ.get("DB_NAME") or "penny_pulse"

DB_CONFIG = {"host": DB_HOST, "user": DB_USER, "password": DB_PASS, "database": DB_NAME, "connect_timeout": 30}

def get_db():
    return mysql.connector.connect(**DB_CONFIG)

def calculate_rsi(series, window=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def get_earnings_date(tk):
    try:
        cal = tk.calendar
        if hasattr(cal, 'iloc') and not cal.empty: return cal.iloc[0][0].strftime('%b %d')
        elif isinstance(cal, dict) and 'Earnings Date' in cal:
            dates = cal['Earnings Date']
            if dates: return dates[0].strftime('%b %d')
    except: pass
    return "N/A"

def update_stock_cache():
    print("🚀 Starting REAL CHART Update...")
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    # 1. Get Targets
    cursor.execute("SELECT user_data FROM user_profiles")
    rows = cursor.fetchall()
    all_tickers = set(["^DJI", "^IXIC", "^GSPTSE", "GC=F"]) 
    for r in rows:
        try:
            data = json.loads(r['user_data'])
            if 'w_input' in data: all_tickers.update([t.strip().upper() for t in data['w_input'].split(",") if t.strip()])
            if 'portfolio' in data: all_tickers.update(data['portfolio'].keys())
        except: pass
    
    # 2. Fetch & Save
    for t in all_tickers:
        try:
            tk = yf.Ticker(t)
            # Fetch 1mo to ensure we have enough points for charts
            hist = tk.history(period="1mo", interval="1d")
            
            if not hist.empty:
                curr = hist['Close'].iloc[-1]
                prev = hist['Close'].iloc[-2] if len(hist) > 1 else curr
                change = ((curr - prev) / prev) * 100
                
                rsi = 50.0
                try:
                    rsi_series = calculate_rsi(hist['Close'])
                    if not rsi_series.empty: rsi = rsi_series.iloc[-1]
                except: pass
                
                vol_stat = "NORMAL"
                if not hist['Volume'].empty:
                    vol_avg = hist['Volume'].mean()
                    if hist['Volume'].iloc[-1] > vol_avg * 1.5: vol_stat = "HEAVY"
                    elif hist['Volume'].iloc[-1] < vol_avg * 0.5: vol_stat = "LIGHT"

                trend = "UPTREND" if curr > hist['Close'].tail(20).mean() else "DOWNTREND"

                # Fundamentals
                rating = "N/A"
                try:
                    rating = tk.info.get('recommendationKey', 'N/A').replace('_', ' ').upper()
                    if rating == "NONE": rating = "N/A"
                except: pass
                earn_str = get_earnings_date(tk)

                # Pre/Post
                pp_price = 0.0
                pp_pct = 0.0
                try:
                    live = tk.history(period="1d", interval="1m", prepost=True)
                    if not live.empty:
                        last_price = live['Close'].iloc[-1]
                        if abs(last_price - curr) > 0.01:
                            pp_price = float(last_price)
                            pp_pct = float(((last_price - curr) / curr) * 100)
                except: pass

                # --- PACK HISTORY FOR CHART ---
                # Take last 20 closing prices -> Convert to List -> Convert to JSON String
                chart_points = hist['Close'].tail(20).tolist()
                chart_json = json.dumps(chart_points)

                # SQL Upsert
                sql = """
                INSERT INTO stock_cache 
                (ticker, current_price, day_change, rsi, volume_status, trend_status, rating, next_earnings, pre_post_price, pre_post_pct, price_history)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                current_price=%s, day_change=%s, rsi=%s, volume_status=%s, trend_status=%s, rating=%s, next_earnings=%s,
                pre_post_price=%s, pre_post_pct=%s, price_history=%s
                """
                vals = (t, float(curr), float(change), float(rsi), vol_stat, trend, rating, earn_str, pp_price, pp_pct, chart_json,
                        float(curr), float(change), float(rsi), vol_stat, trend, rating, earn_str, pp_price, pp_pct, chart_json)
                
                cursor.execute(sql, vals)
                conn.commit()
                print(f"✅ {t}: Saved chart with {len(chart_points)} points.")

        except Exception as e:
            print(f"❌ Error {t}: {e}")

    conn.close()

if __name__ == "__main__":
    update_stock_cache()
