
from db import get_all_users
from prices import get_market_movers
from notifier import send_alert

print("--- STARTING WORKER RUN ---")

# 1. Get All Users
users = get_all_users()
print(f"Found {len(users)} users.")

# 2. Loop through users
for user in users:
    print(f"Checking watchlist for {user['username']}...")
    
    # 3. Check their stocks
    movers = get_market_movers(user['watchlist'])
    
    if movers:
        # 4. Construct the Message
        msg_lines = [f"⚡ *PENNY PULSE ALERT* ⚡", f"User: {user['username']}"]
        for m in movers:
            emoji = "🟢" if m['change'] > 0 else "🔴"
            msg_lines.append(f"{emoji} *{m['ticker']}*: ${m['price']:.2f} ({m['change']:+.2f}%) - {m['trend']}")
        
        final_msg = "\n".join(msg_lines)
        
        # 5. Send Notification (If they have a telegram_id linked)
        # For now, it will just print to console log so you can see it working
        print(final_msg) 
        
        if user.get('telegram_id'):
            send_alert(user['telegram_id'], final_msg)

print("--- WORKER FINISHED ---")
