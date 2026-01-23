
import requests

# You will get this Token from the "BotFather" on Telegram (It takes 30 seconds)
# For now, we can use a placeholder or an Environment Variable
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") 

def send_alert(chat_id, message):
    """Sends a push notification to a specific user via Telegram."""
    if not chat_id or not BOT_TOKEN:
        print(f"Skipping Alert: {message} (No Token/ID)")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload)
        print(f"Sent to {chat_id}: {message}")
    except Exception as e:
        print(f"Failed to send: {e}")
