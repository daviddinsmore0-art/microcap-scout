
import mysql.connector
import json
import os

# Database Credentials (SAME AS APP)
DB_CONFIG = {
    "host": "72.55.168.16",
    "user": "penny_user",
    "password": "123456",
    "database": "penny_pulse",
    "connect_timeout": 30
}

def get_all_users():
    """Fetches ALL user profiles to check their watchlists."""
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute("SELECT username, user_data FROM user_profiles")
        users = cursor.fetchall()
        conn.close()
        
        results = []
        for username, data_str in users:
            try:
                data = json.loads(data_str)
                # We only care about users who have a Watchlist
                if 'w_input' in data and data['w_input'].strip():
                    results.append({
                        "username": username,
                        "watchlist": [x.strip().upper() for x in data['w_input'].split(",") if x.strip()],
                        # Future: Add their Telegram Chat ID here
                        "telegram_id": data.get("telegram_id") 
                    })
            except: pass
        return results
    except Exception as e:
        print(f"DB Error: {e}")
        return []
