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

st.title("📈 Chart History Upgrader")

if st.button("ADD CHART HISTORY COLUMN"):
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        # This adds a column to store the list of numbers
        st.write("Adding 'price_history' column...")
        cursor.execute("ALTER TABLE stock_cache ADD COLUMN price_history TEXT")
        st.success("✅ Success! Your database can now store real charts.")
    except Exception as e:
        if "1060" in str(e): # Duplicate column error
            st.warning("ℹ️ Column already exists. You are good to go!")
        else:
            st.error(f"❌ Error: {e}")

    conn.close()
