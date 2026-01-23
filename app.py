import streamlit as st
import mysql.connector
import json
import base64
import os
import yfinance as yf
import pandas as pd
import altair as alt

# *** CONFIG ***
DB_CONFIG = {
    "host": "72.55.168.16",
    "user": "penny_user",
    "password": "123456",
    "database": "penny_pulse",
    "connect_timeout": 5
}

def get_connection():
    return mysql.connector.connect(**DB_CONFIG)

# --- APP ---
st.set_page_config(page_title="Penny Pulse", layout="wide")

if 'logged_in' not in st.session_state:
    st.markdown("<h1 style='text-align:center;'>⚡ Penny Pulse</h1>", unsafe_allow_html=True)
    st.info("🔒 Secure Enterprise Login")
    
    with st.form("login"):
        user = st.text_input("Username:")
        submitted = st.form_submit_button("Login")
        
        if submitted:
            try:
                conn = get_connection()
                st.success("✅ CONNECTION SUCCESSFUL!")
                st.session_state['logged_in'] = True
                st.rerun()
            except Exception as e:
                # THIS IS THE IMPORTANT PART
                st.error(f"❌ DETAILED ERROR: {e}")
                st.warning("If the error says 'Can't connect to MySQL server', your Firewall is blocking Port 3306.")

else:
    st.write("You are logged in! The difficult part is over.")
