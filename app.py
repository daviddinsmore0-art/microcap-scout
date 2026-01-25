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

st.title("🔐 Security Upgrader")

if st.button("ADD PIN COLUMN"):
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()
        # Add a column to store the PIN
        cursor.execute("ALTER TABLE user_profiles ADD COLUMN pin VARCHAR(50)")
        st.success("✅ Success! Your database can now store PINs.")
        conn.close()
    except Exception as e:
        if "Duplicate column" in str(e):
             st.success("✅ Already upgraded! You are good.")
        else:
            st.error(f"Error: {e}")
