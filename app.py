import streamlit as st
import mysql.connector
import yfinance as yf
import requests
import uuid
import os
import pandas as pd
import pytz
import json
import xml.etree.ElementTree as ET
import streamlit.components.v1 as components
import textwrap
from datetime import datetime, timedelta

# =========================================================
# 1. CONFIGURATION & CSS (MUST BE FIRST)
# =========================================================
st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="centered", initial_sidebar_state="collapsed")

# STRICT CSS: Dark Theme + Clean UI + HEADLINE COLOR FIX + DROPDOWNS
st.markdown("""
    <style>
        /* REMOVE DEFAULT PADDING */
        .block-container { padding-top: 0rem !important; padding-bottom: calc(8rem + env(safe-area-inset-bottom)) !important; }
        
        /* Force Dark Background */
        .stApp { background-color: #0f1219 !important; color: #e0e6ed !important; }
        
        /* Input Fields */
        input[type="text"], input[type="password"], input[type="number"] { 
            background-color: #1e293b !important; 
            color: white !important; 
            border: 1px solid #4ade80 !important; 
            border-radius: 8px; 
            padding: 10px;
        }
