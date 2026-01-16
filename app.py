import streamlit as st
import requests
import time
import yfinance as yf
from openai import OpenAI
from datetime import datetime, timedelta

# --- CONFIGURATION ---
st.set_page_config(page_title="PennyPulse Terminal", page_icon="🔎", layout="wide")

# --- 1. KEY LOADER ---
if "FINNHUB_KEY" in st.secrets:
    FINNHUB_KEY = st.secrets["FINNHUB_KEY"]
    OPENAI_KEY = st.secrets["OPENAI_KEY"]
else:
    st.sidebar.header("🔑 Login")
    FINNHUB_KEY = st.sidebar.text_input("Finnhub Key", type="password")
    OPENAI_KEY = st.sidebar.text_input("OpenAI Key", type="password")

# --- 2. UNIVERSAL SEARCH BAR ---
st.sidebar.divider()
st.sidebar.header("🔎 Scanner")
# This is the magic box - default is TSLA and MULN, but you can change it!
user_input = st.sidebar.text_input("Enter Symbols (comma separated)", value="TSLA, MULN, BTC-USD")
# Convert text to list (e.g., "gme, amc" -> ["GME", "AMC"])
stock_list = [x.strip().upper() for x in user_input.split(",")]

st.title("🔎 PennyPulse Search")
st.caption("Live AI Analysis for ANY Asset")

# --- FUNCTIONS ---
def get_ai_analysis(headline, asset, client):
    try:
        prompt = f"""
        Act as a Wall St Trader.
        Headline: "{headline}"
        Asset: {asset}
        
        Task:
        1. Signal: 🟢 (Bullish), 🔴 (Bearish), or ⚪ (Neutral).
        2. Trade: "Long", "Short", or "Wait".
        3. Reason: 5 words max.
        
        Format: [Signal] | [Trade] | [Reason]
        Example: 🔴 Bearish | Short | Production delays confirmed.
        """
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=50
        )
        return response.choices[0].message.content.strip()
    except:
        return "⚪ | Wait | AI Connecting..."

def fetch_news(symbol, api_key):
    start = (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d')
    today = datetime.now().strftime('%Y-%m-%d')
    url = f"https://finnhub.io/api/v1/company-news?symbol={symbol}&from={start}&to={today}&token={api_key}"
    return requests.get(url).json()

def fetch_forex_news(api_key):
    url = f"
