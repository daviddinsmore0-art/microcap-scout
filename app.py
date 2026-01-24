import streamlit as st
import mysql.connector

# --- CONFIG ---
DB_CONFIG = {
    "host": st.secrets["DB_HOST"],
    "user": st.secrets["DB_USER"],
    "password": st.secrets["DB_PASS"],
    "database": st.secrets["DB_NAME"],
    "connect_timeout": 30,
}

def get_connection():
    return mysql.connector.connect(**DB_CONFIG)

st.title("🛠️ Mega Database Upgrader")
st.info("Click below to add Ratings, Earnings, and Pre/Post Market columns.")

if st.button("RUN MEGA UPGRADE"):
    conn = get_connection()
    cursor = conn.cursor()
    
    # List of columns to add
    updates = [
        ("rating", "VARCHAR(50) DEFAULT 'N/A'"),
        ("next_earnings", "VARCHAR(50) DEFAULT 'N/A'"),
        ("pre_post_price", "DECIMAL(10, 4) DEFAULT 0"),
        ("pre_post_pct", "DECIMAL(10, 2) DEFAULT 0")
    ]
    
    for col, definition in updates:
        try:
            st.write(f"Adding column: `{col}`...")
            cursor.execute(f"ALTER TABLE stock_cache ADD COLUMN {col} {definition}")
            st.success(f"✅ Added {col}")
        except Exception as e:
            # Error 1060 means "Duplicate column name" (already exists), which is fine.
            if "1060" in str(e):
                st.warning(f"ℹ️ Column `{col}` already exists (Skipping).")
            else:
                st.error(f"❌ Error adding {col}: {e}")

    conn.close()
    st.success("🎉 Upgrade Complete! You can now restore the main app.")
