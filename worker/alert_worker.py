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

def analyze_stock(ticker):
    try:
        # 1. Get History for Trend Analysis
        tk = yf.Ticker(ticker)
        hist = tk.history(period="1mo", interval="1d")
        if hist.empty: return None
        
        # Current Data
        curr_price = hist['Close'].iloc[-1]
        prev_close = hist['Close'].iloc[-2] if len(hist) > 1 else curr_price
        day_change = ((curr_price - prev_close) / prev_close) * 100
        
        # 2. Trend Detection (Price vs 20-Day Average)
        sma20 = hist['Close'].tail(20).mean()
        trend_status = "NEUTRAL"
        if curr_price > sma20 and prev_close < sma20:
            trend_status = "🚀 BULLISH BREAKOUT" # Just crossed UP
        elif curr_price < sma20 and prev_close > sma20:
            trend_status = "🔻 BEARISH BREAKDOWN" # Just crossed DOWN
        elif curr_price > sma20:
            trend_status = "✅ UPTREND"
            
        # 3. Post-Market Check
        # We compare the 'Live' price to the 'Close' price
        live_price = tk.fast_info.get('last_price', curr_price)
        pm_change = 0.0
        pm_msg = ""
        
        # If the difference is real (more than 0.1%), report it
        if abs(live_price - curr_price) > 0.01:
            pm_change = ((live_price - curr_price) / curr_price) * 100
            if abs(pm_change) > 0.5: # Only alert if moves > 0.5%
                emoji = "🌙" if pm_change > 0 else "🩸"
                pm_msg = f"{emoji} <b>Post-Market:</b> {live_price:,.2f} ({pm_change:+.2f}%)"

        # 4. Analyst Check
        # We look for "Strong Buy" or "Buy"
        rating = tk.info.get('recommendationKey', 'none').upper().replace('_', ' ')
        rating_msg = ""
        if "BUY" in rating:
            rating_msg = f"⭐ <b>Analyst Rating:</b> {rating}"

        # --- THE DECISION ENGINE ---
        # When do we Alert?
        alerts = []
        
        # A. Big Price Move (>3% or <-3%)
        if abs(day_change) > 3.0:
            emoji = "🚀" if day_change > 0 else "📉"
            alerts.append(f"{emoji} Price Move: {day_change:+.1f}%")
            
        # B. Trend Change (Only alert on the CROSSOVER)
        if "BREAKOUT" in trend_status or "BREAKDOWN" in trend_status:
            alerts.append(f"🔄 Trend Flip: {trend_status}")
            
        # C. Post Market Action
        if pm_msg:
            alerts.append(pm_msg)
            
        # D. Always include Analyst Rating if it's a BUY
        if rating_msg:
            alerts.append(rating_msg)

        if not alerts:
            return None # Boring stock, stay silent

        # Format the Message
        header_emoji = "🟢" if day_change > 0 else "🔴"
        lines = [f"<b>{header_emoji} {ticker} ${curr_price:,.2f}</b>"]
        lines.extend(alerts)
        return "\n".join(lines)

    except Exception as e:
        print(f"Error checking {ticker}: {e}")
        return None

def job():
    # 1. Load Secrets
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not tg_token:
        print("No Token Found!"); return

    # 2. Get Users
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
                        msg = analyze_stock(t.upper())
                        if msg: messages.append(msg)
                
                if messages:
                    full_msg = "<b>🔔 Penny Pulse Alert</b>\n\n" + "\n\n".join(messages)
                    send_telegram(tg_token, chat_id, full_msg)
                    print(f"Sent alert to {chat_id}")
                else:
                    print(f"No alerts for {chat_id}")
        except Exception as e:
            print(f"Error processing user: {e}")

if __name__ == "__main__":
    job()
