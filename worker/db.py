import mysql.connector
import json
import os

def _cfg():
    """
    Reads DB creds from environment variables.
    Set these in GitHub Secrets (Actions):
      DB_HOST, DB_USER, DB_PASS, DB_NAME
    """
    return {
        "host": os.environ["DB_HOST"],
        "user": os.environ["DB_USER"],
        "password": os.environ["DB_PASS"],
        "database": os.environ["DB_NAME"],
        "connect_timeout": 30,
    }

def get_connection():
    return mysql.connector.connect(**_cfg())

def get_all_users():
    """Fetches ALL user profiles to check their watchlists."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT username, user_data FROM user_profiles")
        users = cursor.fetchall()
        conn.close()

        results = []
        for username, data_str in users:
            try:
                data = json.loads(data_str)
                if 'w_input' in data and str(data['w_input']).strip():
                    results.append({
                        "username": username,
                        "watchlist": [x.strip().upper() for x in data['w_input'].split(",") if x.strip()],
                        "telegram_id": data.get("telegram_id")
                    })
            except:
                pass
        return results
    except Exception as e:
        print(f"DB Error: {e}")
        return []

def get_global_picks():
    """
    Reads GLOBAL_CONFIG portfolio tickers so your My Picks always refresh too.
    Your app stores GLOBAL_CONFIG in user_profiles.
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_data FROM user_profiles WHERE username='GLOBAL_CONFIG'")
        row = cursor.fetchone()
        conn.close()
        if not row or not row[0]:
            return []

        data = json.loads(row[0])
        port = data.get("portfolio", {}) or {}
        if isinstance(port, dict):
            return [k.strip().upper() for k in port.keys() if k and k.strip()]
        return []
    except Exception as e:
        print(f"Global picks read error: {e}")
        return []
