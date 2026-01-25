import os
import mysql.connector
import yfinance as yf
import pandas as pd
import json
import requests
from datetime import datetime, timedelta

# --- CONFIG ---
DB_HOST = os.environ.get("DB_HOST") or "72.55.168.16"
DB_USER = os.environ.get("DB_USER") or "penny_user"
DB_PASS = os.environ.get("DB_PASS") or "123456"
DB_NAME = os.environ.get("DB_NAME") or "penny_pulse"
TG_TOKEN = os.environ.get("TELEGRAM_TOKEN") 

DB_CONFIG = {"host": DB_HOST, "user": DB_USER, "password": DB_PASS, "database": DB_NAME, "connect_timeout": 30}

def get_db():
    return mysql.connector.connect(**DB_CONFIG)

def send_telegram(chat_id, msg):
    if not TG_TOKEN or not chat_id: return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"})
    except: pass

def check_cooldown(cursor, user, ticker, alert_type, cooldown_hours=6):
    try:
        cursor.execute(
            "SELECT last_sent FROM alert_log WHERE user_id=%s AND ticker=%s AND alert_type=%s",
            (user, ticker, alert_type)
        )
        row = cursor.fetchone()
        if row:
            last = row['last_sent']
            if datetime.now() < (last + timedelta(hours=cooldown_hours)):
                return False 
    except: pass
    return True

def log_alert(conn, cursor, user, ticker, alert_type):
    try:
        sql = """
        INSERT INTO alert_log (user_id, ticker, alert_type, last_sent)
        VALUES (%s, %s, %s, NOW())
        ON DUPLICATE KEY UPDATE last_sent=NOW()
        """
        cursor.execute(sql, (user, ticker, alert_type))
        conn.commit()
    except: pass

def calculate_rsi(series, window=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

# --- UPDATED EARNINGS LOGIC (FUTURE DATES ONLY) ---
def get_earnings_date(tk):
    try:
        now = datetime.now().date()
        cal = tk.calendar
        
        # Handle Dictionary (New yfinance format)
        if isinstance(cal, dict) and 'Earnings Date' in cal:
            dates = cal['Earnings Date']
            for d in dates:
                if d.date() >= now:
                    return d.strftime('%b %d')

        # Handle DataFrame (Old yfinance format)
        elif hasattr(cal, 'iloc') and not cal.empty:
            # Flatten values to find any valid date object
            vals = cal.values.flatten()
            for v in vals:
                if isinstance(v, (datetime, pd.Timestamp)):
                    if v.date() >= now:
                        return v.strftime('%b %d')
    except: pass
    return "N/A"
# --------------------------------------------------

def update_stock_cache():
    print("🚀 Starting DATA + ALERTS + NAMES + TAPE Worker...")
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    # 1. Get Users & Prefs
    cursor.execute("SELECT username, user_data FROM user_profiles")
    users = cursor.fetchall()
    
    # 2. Build Master Ticker List
    all_tickers = set(["^DJI", "^IXIC", "^GSPTSE", "GC=F"]) 
    user_map = [] 

    for r in users:
        try:
            data = json.loads(r['user_data'])
            user_map.append((r['username'], data))
            
            if 'w_input' in data: 
                all_tickers.update([t.strip().upper() for t in data['w_input'].split(",") if t.strip()])
            
            if 'portfolio' in data: 
                all_tickers.update(data['portfolio'].keys())

            if r['username'] == 'GLOBAL_CONFIG' and 'tape_input' in data:
                 all_tickers.update([t.strip().upper() for t in data['tape_input'].split(",") if t.strip()])
        except: pass
    
    # 3. Process Stocks
    for t in all_tickers:
        try:
            tk = yf.Ticker(t)
            hist = tk.history(period="1mo", interval="1d") 
            
            if not hist.empty:
                curr = float(hist['Close'].iloc[-1])
                prev = float(hist['Close'].iloc[-2]) if len(hist) > 1 else curr
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
                
                # Get Company Name
                rating = "N/A"
                comp_name = t 
                try:
                    info = tk.info
                    rating = info.get('recommendationKey', 'N/A').replace('_', ' ').upper()
                    if rating == "NONE": rating = "N/A"
                    comp_name = info.get('shortName') or info.get('longName') or t
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

                # History
                chart_points = hist['Close'].tail(20).tolist()
                chart_json = json.dumps(chart_points)

                # Save to DB
                sql = """
                INSERT INTO stock_cache 
                (ticker, current_price, day_change, rsi, volume_status, trend_status, rating, next_earnings, pre_post_price, pre_post_pct, price_history, company_name)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                current_price=%s, day_change=%s, rsi=%s, volume_status=%s, trend_status=%s, rating=%s, next_earnings=%s,
                pre_post_price=%s, pre_post_pct=%s, price_history=%s, company_name=%s
                """
                vals = (t, curr, change, rsi, vol_stat, trend, rating, earn_str, pp_price, pp_pct, chart_json, comp_name,
                        curr, change, rsi, vol_stat, trend, rating, earn_str, pp_price, pp_pct, chart_json, comp_name)
                cursor.execute(sql, vals)
                conn.commit()

                # Alerting (Standard)
                for username, prefs in user_map:
                    tg_id = prefs.get('telegram_id')
                    user_tickers = []
                    if 'w_input' in prefs: user_tickers += [x.strip().upper() for x in prefs['w_input'].split(",")]
                    if 'portfolio' in prefs: user_tickers += list(prefs['portfolio'].keys())
                    
                    if not tg_id or t not in user_tickers: 
                        continue

                    if prefs.get('alert_price', True) and abs(change) >= 3.0:
                        alert_type = "PRICE_SPIKE" if change > 0 else "PRICE_DROP"
                        if check_cooldown(cursor, username, t, alert_type, 6): 
                            emoji = "🚀" if change > 0 else "🔻"
                            msg = f"{emoji} <b>{comp_name} ({t})</b> Alert!\nPrice: ${curr:.2f}\nMove: {change:+.2f}%"
                            send_telegram(tg_id, msg)
                            log_alert(conn, cursor, username, t, alert_type)

        except Exception as e:
            print(f"❌ {t}: {e}")

    conn.close()
    print("🏁 Update Complete.")

if __name__ == "__main__":
    update_stock_cache()
