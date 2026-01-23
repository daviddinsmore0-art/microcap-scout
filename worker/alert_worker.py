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

def send_telegram(token, chat_id, msg):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"})

def analyze_stock(ticker, settings):
    try:
        # 1. Get Data
        tk = yf.Ticker(ticker)
        hist = tk.history(period="1mo", interval="1d")
        if hist.empty: return None
        
        # Prices
        curr_price = hist['Close'].iloc[-1]
        prev_close = hist['Close'].iloc[-2] if len(hist) > 1 else curr_price
        day_change = ((curr_price - prev_close) / prev_close) * 100
        
        # 2. Trend Detection
        sma20 = hist['Close'].tail(20).mean()
        trend_status = "NEUTRAL"
        if curr_price > sma20 and prev_close < sma20:
            trend_status = "🚀 BULLISH BREAKOUT"
        elif curr_price < sma20 and prev_close > sma20:
            trend_status = "🔻 BEARISH BREAKDOWN"
            
        # 3. Post-Market Check
        live_price = tk.fast_info.get('last_price', curr_price)
        pm_msg = ""
        if abs(live_price - curr_price) > 0.01:
            pm_change = ((live_price - curr_price) / curr_price) * 100
            # Only alert if > 0.5% (unless testing)
            if abs(pm_change) > 0.5:
                emoji = "🌙" if pm_change > 0 else "🩸"
                pm_msg = f"{emoji} <b>Post-Market:</b> ${live_price:,.2f} ({pm_change:+.2f}%)"

        # 4. Analyst Check
        rating = tk.info.get('recommendationKey', 'none').upper().replace('_', ' ')
        rating_msg = ""
        if "BUY" in rating:
            rating_msg = f"⭐ <b>Analyst Rating:</b> {rating}"

        # --- THE DECISION ENGINE (USER PREFERENCES) ---
        alerts = []
        
        # Check User Toggles (Default to True if missing)
        want_price = settings.get('alert_price', True)
        want_trend = settings.get('alert_trend', True)
        want_rating = settings.get('alert_rating', True)
        want_pm = settings.get('alert_pm', True)

        # A. Day Move (>3%)
        if want_price and abs(day_change) > 3.0:
            emoji = "🟢" if day_change > 0 else "🔴"
            alerts.append(f"{emoji} Day Move: {day_change:+.2f}%")
            
        # B. Trend Flip
        if want_trend and ("BREAKOUT" in trend_status or "BREAKDOWN" in trend_status):
            alerts.append(f"🔄 Trend Flip: {trend_status}")
            
        # C. Post Market
        if want_pm and pm_msg:
            alerts.append(pm_msg)
            
        # D. Analyst
        if want_rating and rating_msg:
            alerts.append(rating_msg)

        if not alerts:
            return None

        # Header
        lines = [f"<b>🔔 {ticker} Alert</b>"]
        lines.extend(alerts)
        return "\n".join(lines)

    except Exception as e:
        print(f"Error checking {ticker}: {e}")
        return None

def job():
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not tg_token: print("No Token Found!"); return

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT user_data FROM user_profiles")
    rows = cursor.fetchall()
    conn.close()

    import json
    for r in rows:
        try:
            data = json.loads(r['user_data'])
            chat_id = data.get('telegram_id')
            tickers = data.get('w_input', "").replace(" ", "").split(",")
            
            if chat_id and tickers:
                messages = []
                for t in tickers:
                    if t:
                        # PASS THE FULL USER DATA OBJECT (SETTINGS)
                        msg = analyze_stock(t.upper(), data)
                        if msg: messages.append(msg)
                
                if messages:
                    full_msg = "\n\n".join(messages)
                    send_telegram(tg_token, chat_id, full_msg)
                    print(f"Sent alert to {chat_id}")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    job()
