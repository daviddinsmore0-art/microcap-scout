import os
import mysql.connector
import yfinance as yf
import pandas as pd
import requests
from datetime import datetime, timezone

# --- CONFIG ---
DB_CONFIG = {
    "host": "72.55.168.16",
    "user": "penny_user",
    "password": "123456",
    "database": "penny_pulse",
    "connect_timeout": 30
}

def get_db():
    return mysql.connector.connect(**DB_CONFIG)

def calculate_rsi(series, window=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def update_stock_cache():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    # 1. Get ALL unique tickers from ALL users
    cursor.execute("SELECT user_data FROM user_profiles")
    rows = cursor.fetchall()
    
    all_tickers = set()
    import json
    for r in rows:
        try:
            data = json.loads(r['user_data'])
            # Add Watchlist
            if 'w_input' in data:
                all_tickers.update([t.strip().upper() for t in data['w_input'].split(",") if t.strip()])
            # Add Portfolio
            if 'portfolio' in data:
                all_tickers.update(data['portfolio'].keys())
        except: pass
    
    print(f"📉 Updating Cache for {len(all_tickers)} tickers: {all_tickers}")

    # 2. Fetch Data & Save to DB
    for t in all_tickers:
        try:
            tk = yf.Ticker(t)
            hist = tk.history(period="1mo", interval="1d")
            
            if not hist.empty:
                # Price Data
                curr = hist['Close'].iloc[-1]
                prev = hist['Close'].iloc[-2] if len(hist) > 1 else curr
                change = ((curr - prev) / prev) * 100
                
                # Technicals
                rsi = 50.0
                try:
                    rsi_series = calculate_rsi(hist['Close'])
                    if not rsi_series.empty: rsi = rsi_series.iloc[-1]
                except: pass
                
                vol_stat = "NORMAL"
                if not hist['Volume'].empty:
                    vol_avg = hist['Volume'].mean()
                    curr_vol = hist['Volume'].iloc[-1]
                    if curr_vol > vol_avg * 1.5: vol_stat = "HEAVY"
                    elif curr_vol < vol_avg * 0.5: vol_stat = "LIGHT"

                trend = "NEUTRAL"
                sma20 = hist['Close'].tail(20).mean()
                if curr > sma20: trend = "UPTREND"
                else: trend = "DOWNTREND"

                # SQL Upsert (Insert or Update)
                sql = """
                INSERT INTO stock_cache (ticker, current_price, day_change, rsi, volume_status, trend_status)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                current_price=%s, day_change=%s, rsi=%s, volume_status=%s, trend_status=%s
                """
                vals = (t, float(curr), float(change), float(rsi), vol_stat, trend, 
                        float(curr), float(change), float(rsi), vol_stat, trend)
                
                cursor.execute(sql, vals)
                conn.commit()
                print(f"✅ Saved {t}: ${curr:.2f}")
            else:
                print(f"⚠️ No data for {t}")

        except Exception as e:
            print(f"❌ Error {t}: {e}")

    conn.close()

if __name__ == "__main__":
    update_stock_cache()
