import streamlit as st
import mysql.connector
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
import base64
from pathlib import Path
from decimal import Decimal
import numbers


# ==========================
# INLINE SVG ICONS (card headers)
# ==========================
ICON_SIGNAL = """<div style="width:30px;height:30px;border-radius:12px;background:linear-gradient(135deg,rgba(251,191,36,.22),rgba(245,158,11,.10));border:1px solid rgba(255,255,255,.10);box-shadow:0 10px 24px rgba(0,0,0,.35);display:flex;align-items:center;justify-content:center;">
<svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style="opacity:.95">
<path d="M4 19V5" stroke="#FBBF24" stroke-width="2" stroke-linecap="round"/>
<path d="M4 19H20" stroke="#FBBF24" stroke-width="2" stroke-linecap="round"/>
<path d="M7 15L11 11L14 14L20 8" stroke="#FBBF24" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
<path d="M20 8V12" stroke="#FBBF24" stroke-width="2" stroke-linecap="round"/>
</svg></div>"""

ICON_ACCEL = """<div style="width:30px;height:30px;border-radius:999px;background:linear-gradient(135deg,rgba(34,197,94,.22),rgba(22,163,74,.10));border:1px solid rgba(255,255,255,.10);box-shadow:0 10px 24px rgba(0,0,0,.35);display:flex;align-items:center;justify-content:center;">
<svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style="opacity:.95">
<path d="M13 2L3 14H11L9 22L21 9H13L13 2Z" stroke="#22C55E" stroke-width="2" stroke-linejoin="round"/>
</svg></div>"""

ICON_SECTOR = """<div style="width:30px;height:30px;border-radius:12px;background:linear-gradient(135deg,rgba(96,165,250,.22),rgba(59,130,246,.10));border:1px solid rgba(255,255,255,.10);box-shadow:0 10px 24px rgba(0,0,0,.35);display:flex;align-items:center;justify-content:center;">
<svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style="opacity:.95">
<path d="M12 2L3 7L12 12L21 7L12 2Z" stroke="#60A5FA" stroke-width="2" stroke-linejoin="round"/>
<path d="M3 12L12 17L21 12" stroke="#60A5FA" stroke-width="2" stroke-linejoin="round"/>
<path d="M3 17L12 22L21 17" stroke="#60A5FA" stroke-width="2" stroke-linejoin="round"/>
</svg></div>"""

def get_logo_base64(path="logo_optimized.png"):
    try:
        p = Path(__file__).parent / path
        return base64.b64encode(p.read_bytes()).decode("utf-8")  # <- decode!
    except Exception as e:
        # st.error(f"Logo load error: {e}")  # optional (comment out if annoying)
        return ""
# =========================================================
# 1. CONFIGURATION & CSS (MUST BE FIRST)
# =========================================================
st.set_page_config(page_title="Penny Pulse", page_icon="⚡", layout="centered", initial_sidebar_state="collapsed")

# STRICT CSS: Dark Theme + Clean UI + HEADLINE COLOR FIX + DROPDOWNS
st.markdown("""
    <style>
        /* REMOVE DEFAULT PADDING */


        /* Force Dark Background */
        .stApp { background-color: #0f1219 !important; color: #e0e6ed !important; }
         header[data-testid="stHeader"] {
  display: none !important;
}
/* 1. Hide the top toolbar/header completely */
        header[data-testid="stHeader"] {
            visibility: hidden;
            height: 0%;
        }

        /* 2. Remove padding from the main container */
        .stAppViewBlockContainer {
            padding-top: 0rem !important;
            padding-bottom: 1rem !important;
            margin-top: 0rem !important;
        }
/* 3. Optional: Remove extra gap from vertical blocks if needed */
        .stVerticalBlock {
            gap: 0rem !important;
        }
         #MainMenu {visibility: hidden;}
footer {visibility: hidden;}

        /* Input Fields */
        input[type="text"], input[type="password"], input[type="number"] { 
            background-color: #1e293b !important; 
            color: white !important; 
            border: 1px solid #4ade80 !important; 
            border-radius: 8px; 
            padding: 10px;
        }
        div[data-baseweb="input"] { background-color: transparent !important; border: none; }

        /* Dropdowns & Select Boxes (FIXED) */
        div[data-baseweb="select"] > div { 
            background-color: #1e293b !important; 
            color: white !important; 
            border: 1px solid #4ade80 !important; 
        }
        div[role="listbox"] ul { background-color: #1e293b !important; }
        li[role="option"] { color: white !important; background-color: #1e293b !important; }
        li[role="option"]:hover { background-color: #4ade80 !important; color: black !important; }
        div[data-baseweb="popover"] { background-color: #1e293b !important; }

        /* Cards WITH CLICK EFFECT ADDED */
        .card { 
            background-color: #1a1f2b; 
            border-radius: 16px; 
            padding: 20px; 
            margin-bottom: 30px; 
            border: 1px solid #2d3748; 
            box-shadow: 0 4px 6px rgba(0,0,0,0.3); 
            transition: transform 0.1s ease, border-color 0.1s ease;
        }
        .card:active {
            transform: scale(0.97);
            border-color: #4ade80 !important;
        }

        /* Portfolio reorder animation helper */
        .port-row { will-change: transform; }

        /* Clickable tiles (button-like press feedback) */
        .click-tile {
            transition: transform 0.1s ease, border-color 0.1s ease;
        }
        .click-tile:active {
            transform: scale(0.97);
            border-color: #4ade80 !important;
        }
        a.nav-link:active { transform: scale(0.92); }
         /* Hide Streamlit header + toolbar completely */
header[data-testid="stHeader"] {
    display: none !important;
}

div[data-testid="stToolbar"] {
    display: none !important;
}

div[data-testid="stDecoration"] {
    display: none !important;
}

/* Kill Streamlit header + toolbar completely */
header[data-testid="stHeader"] {
    display: none !important;
}

div[data-testid="stToolbar"] {
    display: none !important;
}

div[data-testid="stDecoration"] {
    display: none !important;
}

#MainMenu {
    visibility: hidden;
}
/* Remove extra top padding caused by header */
.block-container{
    padding-top: 0.25rem !important;
}
        .pp-greeting {
          font-family: Tahoma;
          font-size: 16px;
          font-weight: 300;
          color: #A7F3D0;
          letter-spacing: 0.5px;
          margin: 10px 0 40px 0;
        }
        /* Metric Boxes */
        .metric-box {
            background-color: #1e293b;
            border: 1px solid #2d3748;
            border-radius: 12px;
            padding: 15px;
            text-align: center;
            margin-top: 10px;
            margin-bottom: 10px;
            padding-top:10px;
        }
        .metric-label { font-size: 0.75rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 5px; }
        .metric-value { font-size: 1.5rem; font-weight: bold; color: white; margin-bottom: 2px; line-height: 1.1; }
        .metric-sub { font-size: 0.9rem; font-weight: bold; }

        /* Buttons */
        div.stButton > button {
            background: linear-gradient(135deg, #4ade80, #16a34a) !important; 
            color: white !important; 
            border: none; 
            border-radius: 8px; 
            font-weight: bold;
            width: 100%;
            padding: 12px 20px;
        }

        /* Delete/Remove Buttons */
        button[kind="secondary"] {
            background: #334155 !important;
            border: 1px solid #ef4444 !important;
            color: #ef4444 !important;
        }

        h1, h2, h3, p, label, span, div { color: #e0e6ed; }

        /* HEADLINE COLOR FIX */
        a { color: #ffffff !important; text-decoration: none !important; }
        a:hover { color: #4ade80 !important; }

        /* Navigation */
        .nav-container { 
            position: fixed; bottom: 0; left: 0; width: 100%; height: 65px; 
            background-color: #0f1219; border-top: 1px solid #2d3748; 
            display: flex; justify-content: space-around; align-items: center; z-index: 99999; 
        }
        a.nav-link { text-decoration: none; font-size: 24px; text-align: center; cursor: pointer;}
        a.nav-link:hover { transform: scale(1.1); }

        /* Scrolling Wrapper */
        .scrolling-wrapper { 
            display: flex; 
            flex-wrap: nowrap; 
            overflow-x: auto; 
            scroll-behavior: smooth;
            gap: 12px;
            padding-top:0px;
            padding-bottom: 40px;
            -ms-overflow-style: none; 
            scrollbar-width: none; 
        }
        .scrolling-wrapper::-webkit-scrollbar { display: none; }
        .scrolling-card { 
            flex: 0 0 auto; 
            width: 110px; 
            background-color: #1a1f2b; 
            border: 1px solid #2d3748; 
            border-radius: 12px; 
            padding: 25px;
        }

        .price-block {
          display: flex;
          flex-direction: column;
          align-items: flex-end;
          text-align: right;
          gap: 2px;
          margin-left: auto;
         }


/* Pulse Environment / Market Pulse card */
.pulse-card{
  border-radius:22px;
  padding:18px 18px 16px 18px;
  background: linear-gradient(160deg, rgba(13,23,46,0.95), rgba(7,14,28,0.95));
  border: 1px solid rgba(255,255,255,0.06);
  box-shadow: 0 10px 26px rgba(0,0,0,0.35);
  margin: 14px 0 16px 0;
}
.pulse-top{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:12px;
  margin-bottom: 10px;
}
.pulse-title{
  font-size: 18px;
  font-weight: 900;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: #f5d07a;
}
.pulse-pill{
  display:flex;
  align-items:center;
  gap:12px;
  padding: 8px 14px;
  border-radius: 999px;
  font-size: 14px;
  font-weight: 800;
  border: 1px solid rgba(255,255,255,0.08);
  background: rgba(255,255,255,0.04);
  color: rgba(255,255,255,0.86);
  white-space:nowrap;
}
.pulse-pill .pulse-score{
  color: #49e38b;
  font-weight: 900;
}
.pulse-dot{
  width:12px;
  height:12px;
  border-radius:999px;
  box-shadow: 0 0 14px rgba(34,197,94,0.35);
}
.pulse-metrics{
  display:flex;
  gap:26px;
  flex-wrap:wrap;
  margin-top: 10px;
}
.pulse-metric{
  flex: 0 0 auto;
  display:flex;
  align-items:center;
  gap:10px;
  padding: 0;
  border: none;
  background: transparent;
}
.pulse-label{
  font-size: 18px;
  font-weight: 600;
  color: rgba(255,255,255,0.86);
  margin: 0;
}
.pulse-arrow{
  font-size: 18px;
  font-weight: 900;
  opacity: .9;
}
.pulse-sub{
  margin-top: 10px;
  font-size: 13px;
  color: rgba(255,255,255,0.62);
}

/* Risk Pills */
        .risk-pill { padding: 4px 4px; border-radius: 20px; font-size: 0.75rem; font-weight: bold; text-transform: uppercase; }
        .pill-low { background: rgba(74, 222, 128, 0.2); color: #4ade80; }
        .pill-med { background: rgba(251, 191, 36, 0.2); color: #fbbf24; }
        .pill-high { background: rgba(239, 68, 68, 0.2); color: #ef4444; }
        .risk-row { display: flex; justify-content: space-between; align-items: center; margin: 30px 0 10px 0; border-bottom: 1px solid #2d3748; padding-left:20px; padding-bottom: 5px; }

        /* Hide default header/footer */
        header {visibility: hidden;} footer {visibility: hidden;} 

  /* Make whole card tappable */
  a.card-link { display:block; text-decoration:none; color:inherit; -webkit-tap-highlight-color: transparent; }
  a.card-link:visited { color:inherit; }

/* ===== Market Scanner Trading Tiles (scanner-only classes) ===== */
.scan-grid{display:grid;grid-template-columns:1fr;gap:14px;}
@media (min-width: 780px){.scan-grid{grid-template-columns:1fr 1fr;}}
.section-divider{
margin-top:40px;
}
.scan-card{
  background:#0f1722;
  border-radius:22px;
  padding:18px 18px;
  margin:14px 0;
  border:1px solid rgba(255,255,255,0.08);
  box-shadow:0 14px 28px rgba(0,0,0,0.28);
  position:relative;
  overflow:hidden;
}
.scan-card:active{ transform:scale(0.992); }

.scan-top{ display:flex; justify-content:space-between; align-items:flex-start; gap:12px; }
.scan-left{ min-width:0; }
.scan-ticker{ font-size:30px; font-weight:900; letter-spacing:1px; line-height:1.0; color:#f1f5f9;  white-space:nowrap; }
.scan-sub{ margin-top:6px; font-size:13px; color:#94a3b8; letter-spacing:0.7px; text-transform:uppercase; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:62vw; }

.scan-right{ text-align:right; min-width:120px; }
.scan-price{ font-size:24px; font-weight:900; color:#f8fafc; line-height:1.05; }
.scan-day{ margin-top:6px; font-size:15px; font-weight:900; }

.scan-row{ display:flex; flex-wrap:wrap; gap:10px; margin-top:16px; align-items:center; }
.scan-chip{
  display:inline-flex; align-items:center; justify-content:center;
  padding:9px 14px; border-radius:999px;
  font-size:14px; font-weight:900; letter-spacing:0.4px;
  background:rgba(148,163,184,0.10);
  border:1px solid rgba(255,255,255,0.12);
  color:#e2e8f0;
}
.scan-chip.good{ background:rgba(74,222,128,0.12); border-color:rgba(74,222,128,0.35); color:#4ade80; }
.scan-chip.warn{ background:rgba(251,191,36,0.12); border-color:rgba(251,191,36,0.35); color:#fbbf24; }
.scan-chip.bad { background:rgba(239,68,68,0.12); border-color:rgba(239,68,68,0.35); color:#ef4444; }

.scan-badge{
  display:inline-block;
  margin-top:12px;
  padding:9px 14px;
  border-radius:999px;
  background:linear-gradient(90deg,#fbbf24,#f59e0b);
  color:#111827;
  font-weight:900;
  font-size:13px;
  letter-spacing:0.3px;
  box-shadow:0 8px 18px rgba(0,0,0,0.25);
}

.scan-divider{ margin-top:14px; border-top:1px solid rgba(255,255,255,0.08); }

.scan-mini{
  display:flex; justify-content:space-between; gap:10px;
  margin-top:12px; font-size:13px; color:#cbd5e1;
}
.scan-mini span{ color:#94a3b8; margin-right:6px; }

.scan-spark{ margin-top:10px; opacity:0.95; }



/* Section cards with colored left borders */
.card.border-blue { border-left: 4px solid #2b6cb0; }
.card.border-gold { border-left: 4px solid #f6c343; }

/* Global picks row layout (single HTML block) */
.global-picks-row { display:flex; justify-content:space-between; align-items:flex-start; margin-top:5px; margin-bottom:15px; }
.global-picks-left .ticker { font-weight:600; font-size:16px; margin:0; }
.global-picks-left .type { opacity:.65; font-size:16px; margin-top:2px; }
.global-picks-left .meta { opacity:.55; font-size:14px; margin-top:6px; }
.global-picks-right { text-align:right; }
.global-picks-right .price { font-weight:600; font-size:16px; margin:0; }
.global-picks-right .chg { font-weight:600; font-size:14px; margin-top:4px; }
.global-picks-divider { height:1px; background:rgba(255,255,255,.06); margin:0 6px; }

        /* --- PennyPulse hardening: prevent "big white block" on mobile --- */
        div[data-testid="stCodeBlock"], pre, code {
            background: #0b1220 !important;
            color: #94a3b8 !important;
            border: 1px solid rgba(148,163,184,0.18) !important;
            border-radius: 16px !important;
        }
        div[data-testid="stCodeBlock"] {
            padding: 0.6rem 0.8rem !important;
            overflow-x: auto !important;
        }
        /* If an HTML component iframe appears, keep it from expanding */
        </style>
""", unsafe_allow_html=True)

# Global Constants
DB_CONFIG = {
    "host": "atlanticcanadaschoice.com", 
    "user": "atlantic", 
    "password": "1q2w3e4R!!", 
    "database": "atlantic_pennypulse", 
    "connect_timeout": 30
}
OPENAI_KEY = st.secrets["openai"]["api_key"] if "openai" in st.secrets else None
token = st.query_params.get("token", None)

# =========================================================
# 2. FUNCTIONS
# =========================================================

def get_connection():
    return mysql.connector.connect(**DB_CONFIG)

def _table_exists(cur, table_name: str) -> bool:
    try:
        cur.execute("SHOW TABLES LIKE %s", (table_name,))
        return cur.fetchone() is not None
    except Exception:
        return False

def _column_exists(cur, table_name: str, column_name: str) -> bool:
    try:
        cur.execute(
            "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s "
            "LIMIT 1",
            (table_name, column_name),
        )
        return cur.fetchone() is not None
    except Exception:
        return False

def fetch_signal_shift(cur, latest_date, prev_date):
    """
    Biggest global rank improvement between two asof_date values.
    Uses ONLY:
      - rankings_global_daily (ticker, asof_date, global_rank)
      - rankings_daily (ticker, asof_date, momentum_score, stability_score) as an optional join
    """
    if not latest_date or not prev_date:
        return None

    sql = """
        SELECT
            g1.ticker,
            g1.global_rank AS current_rank,
            g0.global_rank AS prev_rank,
            (g0.global_rank - g1.global_rank) AS rank_jump,
            d1.momentum_score,
            d1.stability_score
        FROM rankings_global_daily g1
        JOIN rankings_global_daily g0
          ON g1.ticker = g0.ticker
        LEFT JOIN rankings_daily d1
          ON d1.ticker = g1.ticker
         AND d1.asof_date = g1.asof_date
        WHERE g1.asof_date = %s
          AND g0.asof_date = %s
        ORDER BY rank_jump DESC
        LIMIT 1
    """
    cur.execute(sql, (latest_date, prev_date))
    return cur.fetchone()



def get_rank_map(tickers):
    """
    Returns {TICKER: {global_rank, sector_rank, sector}} for the latest asof_date in rankings_sector_daily.
    Safe to call even if the table/columns aren't present; returns {} on failure.
    """
    if not tickers:
        return {}

    # De-dupe + normalize
    tickers = sorted({(t or "").upper().strip() for t in tickers if t})
    if not tickers:
        return {}

    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)

        cur.execute("SELECT MAX(asof_date) AS d FROM rankings_sector_daily")
        row = cur.fetchone() or {}
        latest = row.get("d")
        if not latest:
            return {}

        placeholders = ",".join(["%s"] * len(tickers))

        # Try the expected schema first
        q = f"""
            SELECT UPPER(ticker) AS ticker,
                   sector,
                   global_rank,
                   sector_rank
            FROM rankings_sector_daily
            WHERE asof_date = %s AND UPPER(ticker) IN ({placeholders})
        """
        try:
            cur.execute(q, [latest] + tickers)
        except Exception:
            # Fallback: maybe columns are named differently
            q2 = f"""
                SELECT UPPER(ticker) AS ticker,
                       sector
                FROM rankings_sector_daily
                WHERE asof_date = %s AND UPPER(ticker) IN ({placeholders})
            """
            cur.execute(q2, [latest] + tickers)

        out = {}
        for r in cur.fetchall() or []:
            t = r.get("ticker")
            if not t:
                continue
            out[t] = {
                "sector": r.get("sector"),
                "global_rank": r.get("global_rank"),
                "sector_rank": r.get("sector_rank"),
            }
        return out
    except Exception:
        return {}
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass


def ensure_stock_cache_ticker(ticker):
    """Ensure ticker exists in stock cache table (if you use one)."""
    t = (ticker or "").strip().upper()
    if not t:
        return

    conn = get_connection()
    cur = conn.cursor(dictionary=True)

    try:
        # If your cache table is named differently, update this query.
        cur.execute("SELECT ticker FROM global_cache WHERE ticker=%s LIMIT 1", (t,))
        row = cur.fetchone()
        if not row:
            cur.execute("INSERT INTO global_cache (ticker) VALUES (%s)", (t,))
            conn.commit()
    finally:
        try:
            cur.close()
        except:
            pass
        conn.close()

def get_latest_asof_for_table(table_name: str):
    """Return MAX(asof_date) for a table, or None if table empty / error."""
    conn = get_connection()
    if conn is None:
        return None
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(f"SELECT MAX(asof_date) AS asof FROM {table_name}")
        row = cur.fetchone() or {}
        return row.get("asof")
    except Exception as e:
        print(f"get_latest_asof_for_table({table_name}) failed: {e}")
        return None
    finally:
        try:
            cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass


def get_latest_rank_asof():
    """Primary 'rank asof' for factor scores on cards (from rankings_daily)."""
    # rankings_daily is what contains momentum/quality/value/stability/composite.
    asof = get_latest_asof_for_table("rankings_daily")
    if asof:
        return asof
    # Fallbacks
    return get_latest_asof_for_table("rankings_global_daily") or get_latest_asof_for_table("rankings_sector_daily")
def get_rank_map_for_tickers(tickers):
    """
    Build a dict keyed by ticker with:
      - factor scores from rankings_daily (momentum/quality/value/stability/composite)
      - global_rank/global_percentile from rankings_global_daily (if available)
      - sector_rank/sector_percentile/sector_name from rankings_sector_daily (if available)
    Uses the latest asof_date from each table independently (tables may lag).
    """
    tickers = [t.strip().upper() for t in (tickers or []) if str(t).strip()]
    if not tickers:
        return {}

    daily_asof = get_latest_asof_for_table("rankings_daily")
    if not daily_asof:
        return {}

    global_asof = get_latest_asof_for_table("rankings_global_daily") or daily_asof
    sector_asof = get_latest_asof_for_table("rankings_sector_daily") or daily_asof

    placeholders = ",".join(["%s"] * len(tickers))
    rank_map = {t: {} for t in tickers}

    conn = get_connection()
    if conn is None:
        return rank_map

    try:
        cur = conn.cursor(dictionary=True)

        # Factor scores (PRIMARY)
        cur.execute(
            f"""
            SELECT ticker, momentum_score, quality_score, value_score, stability_score, composite_score
            FROM rankings_daily
            WHERE asof_date = %s
              AND ticker IN ({placeholders})
            """,
            [daily_asof] + tickers,
        )
        for r in (cur.fetchall() or []):
            t = (r.get("ticker") or "").upper()
            if t in rank_map:
                rank_map[t].update(
                    {
                        "asof": daily_asof,
                        "momentum_score": r.get("momentum_score"),
                        "quality_score": r.get("quality_score"),
                        "value_score": r.get("value_score"),
                        "stability_score": r.get("stability_score"),
                        "composite_score": r.get("composite_score"),
                    }
                )

        # Global ranks (best effort)
        cur.execute(
            f"""
            SELECT ticker, global_rank, global_count, global_percentile
            FROM rankings_global_daily
            WHERE asof_date = %s
              AND ticker IN ({placeholders})
            """,
            [global_asof] + tickers,
        )
        for r in (cur.fetchall() or []):
            t = (r.get("ticker") or "").upper()
            if t in rank_map:
                rank_map[t].update(
                    {
                        "global_asof": global_asof,
                        "global_rank": r.get("global_rank"),
                        "global_count": r.get("global_count"),
                        "global_percentile": r.get("global_percentile"),
                    }
                )

        # Sector ranks (best effort)
        cur.execute(
            f"""
            SELECT ticker, sector AS sector_name, sector_rank, sector_count, sector_percentile
            FROM rankings_sector_daily
            WHERE asof_date = %s
              AND ticker IN ({placeholders})
            """,
            [sector_asof] + tickers,
        )
        for r in (cur.fetchall() or []):
            t = (r.get("ticker") or "").upper()
            if t in rank_map:
                rank_map[t].update(
                    {
                        "sector_asof": sector_asof,
                        "sector_name": r.get("sector_name"),
                        "sector_rank": r.get("sector_rank"),
                        "sector_count": r.get("sector_count"),
                        "sector_percentile": r.get("sector_percentile"),
                    }
                )

    except Exception as e:
        print(f"get_rank_map_for_tickers failed: {e}")
    finally:
        try:
            cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass

    return rank_map
def ensure_stock_cache_ticker(ticker: str):
    """Ensure ticker exists in stock_cache AND in global_universe."""
    t = (ticker or "").strip().upper()
    if not t:
        return

    conn = get_connection()
    cursor = conn.cursor()

    try:
        # 1) Ensure stock_cache has a stub row (so cron/updater can fill it)
        cursor.execute(
            "INSERT INTO stock_cache (ticker) VALUES (%s) "
            "ON DUPLICATE KEY UPDATE ticker = ticker",
            (t,)
        )

        # 2) Ensure global_universe includes this ticker (so it can be ranked/featured)
        cursor.execute(
            "INSERT INTO global_universe (ticker, enabled, added_at) "
            "VALUES (%s, 1, NOW()) "
            "ON DUPLICATE KEY UPDATE enabled = VALUES(enabled)",
            (t,)
        )

        conn.commit()
    finally:
        conn.close()

def init_db():
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS user_profiles (username VARCHAR(255) PRIMARY KEY, pin VARCHAR(50), display_name VARCHAR(100), email VARCHAR(255), paper_balance DECIMAL(20,2) DEFAULT 10000.00)")
        cursor.execute("CREATE TABLE IF NOT EXISTS user_sessions (token VARCHAR(255) PRIMARY KEY, username VARCHAR(255))")
        cursor.execute("CREATE TABLE IF NOT EXISTS user_portfolio (id INT NOT NULL AUTO_INCREMENT, username VARCHAR(255), ticker VARCHAR(20), shares DECIMAL(10,4) DEFAULT 0, entry_price DECIMAL(20,4) DEFAULT 0, portfolio_type VARCHAR(20) DEFAULT 'REAL', is_active BOOLEAN DEFAULT TRUE, realized_pl DECIMAL(20,2) DEFAULT 0.00, PRIMARY KEY (id))")
        cursor.execute("CREATE TABLE IF NOT EXISTS user_alerts (id INT NOT NULL AUTO_INCREMENT PRIMARY KEY, username VARCHAR(255), ticker VARCHAR(20), condition_type VARCHAR(10), target_price DECIMAL(20,4), is_triggered BOOLEAN DEFAULT FALSE, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")

        # --- Alert settings (per user) ---
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_alert_settings (
                username VARCHAR(255) PRIMARY KEY,
                telegram_enabled TINYINT(1) DEFAULT 0,
                telegram_chat_id VARCHAR(64) DEFAULT '',
                pct_change_enabled TINYINT(1) DEFAULT 0,
                pct_change_threshold DECIMAL(6,2) DEFAULT 5.00,
                range_enabled TINYINT(1) DEFAULT 0,
                range_threshold DECIMAL(6,2) DEFAULT 8.00,
                vol_spike_enabled TINYINT(1) DEFAULT 0,
                vol_spike_mult DECIMAL(6,2) DEFAULT 2.50,
                vol_spike_min_move DECIMAL(6,2) DEFAULT 2.00,
                rsi_enabled TINYINT(1) DEFAULT 0,
                rsi_low DECIMAL(6,2) DEFAULT 30.00,
                rsi_high DECIMAL(6,2) DEFAULT 70.00,
                rsi_confirm_move DECIMAL(6,2) DEFAULT 3.00,
                rsi_confirm_rvol DECIMAL(6,2) DEFAULT 1.50,
                sniper_enabled TINYINT(1) DEFAULT 0,
                sniper_max_price DECIMAL(10,4) DEFAULT 5.0000,
                sniper_min_move DECIMAL(6,2) DEFAULT 8.00,
                sniper_min_rvol DECIMAL(6,2) DEFAULT 2.00,
                sniper_min_range DECIMAL(6,2) DEFAULT 10.00,
                sniper_max_mcap BIGINT DEFAULT 500000000,
                global_list_enabled TINYINT(1) DEFAULT 0
            )
        """)

        # Add missing columns safely (for existing installs)
        alter_stmts = [
            "ALTER TABLE user_alert_settings ADD COLUMN telegram_enabled TINYINT(1) DEFAULT 0",
            "ALTER TABLE user_alert_settings ADD COLUMN telegram_chat_id VARCHAR(64) DEFAULT ''",
            "ALTER TABLE user_alert_settings ADD COLUMN pct_change_enabled TINYINT(1) DEFAULT 0",
            "ALTER TABLE user_alert_settings ADD COLUMN pct_change_threshold DECIMAL(6,2) DEFAULT 5.00",
            "ALTER TABLE user_alert_settings ADD COLUMN range_enabled TINYINT(1) DEFAULT 0",
            "ALTER TABLE user_alert_settings ADD COLUMN range_threshold DECIMAL(6,2) DEFAULT 8.00",
            "ALTER TABLE user_alert_settings ADD COLUMN vol_spike_enabled TINYINT(1) DEFAULT 0",
            "ALTER TABLE user_alert_settings ADD COLUMN vol_spike_mult DECIMAL(6,2) DEFAULT 2.50",
            "ALTER TABLE user_alert_settings ADD COLUMN vol_spike_min_move DECIMAL(6,2) DEFAULT 2.00",
            "ALTER TABLE user_alert_settings ADD COLUMN rsi_enabled TINYINT(1) DEFAULT 0",
            "ALTER TABLE user_alert_settings ADD COLUMN rsi_low DECIMAL(6,2) DEFAULT 30.00",
            "ALTER TABLE user_alert_settings ADD COLUMN rsi_high DECIMAL(6,2) DEFAULT 70.00",
            "ALTER TABLE user_alert_settings ADD COLUMN rsi_confirm_move DECIMAL(6,2) DEFAULT 3.00",
            "ALTER TABLE user_alert_settings ADD COLUMN rsi_confirm_rvol DECIMAL(6,2) DEFAULT 1.50",
            "ALTER TABLE user_alert_settings ADD COLUMN sniper_enabled TINYINT(1) DEFAULT 0",
            "ALTER TABLE user_alert_settings ADD COLUMN sniper_max_price DECIMAL(10,4) DEFAULT 5.0000",
            "ALTER TABLE user_alert_settings ADD COLUMN sniper_min_move DECIMAL(6,2) DEFAULT 8.00",
            "ALTER TABLE user_alert_settings ADD COLUMN sniper_min_rvol DECIMAL(6,2) DEFAULT 2.00",
            "ALTER TABLE user_alert_settings ADD COLUMN sniper_min_range DECIMAL(6,2) DEFAULT 10.00",
            "ALTER TABLE user_alert_settings ADD COLUMN sniper_max_mcap BIGINT DEFAULT 500000000",
            "ALTER TABLE user_alert_settings ADD COLUMN global_list_enabled TINYINT(1) DEFAULT 0",
        ]
        for stmt in alter_stmts:
            try:
                cursor.execute(stmt)
            except Exception:
                pass
        # Ensure created_at exists for ordering (safe if column already exists)
        try:
            cursor.execute("ALTER TABLE user_alerts ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        except:
            pass
        cursor.execute("CREATE TABLE IF NOT EXISTS stock_cache (ticker VARCHAR(20) PRIMARY KEY, company_name VARCHAR(255), current_price DECIMAL(20,4), day_change DECIMAL(10,2), rsi DECIMAL(10,2), trend_status VARCHAR(20), volume_status VARCHAR(20), range_loc DECIMAL(10,2), volatility DECIMAL(10,2), debt_ratio DECIMAL(10,2), days_to_earnings INT, market_cap BIGINT, eps DECIMAL(10,2), signal_tag VARCHAR(50), last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)")
        cursor.execute("CREATE TABLE IF NOT EXISTS daily_briefing (id INT PRIMARY KEY, content TEXT, last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)")
        if OPENAI_KEY:
            cursor.execute("CREATE TABLE IF NOT EXISTS system_config (key_name VARCHAR(50) PRIMARY KEY, key_value TEXT)")
            cursor.execute("REPLACE INTO system_config (key_name, key_value) VALUES ('openai_key', %s)", (OPENAI_KEY,))
            conn.commit()
        conn.close()
    except Exception as e:
        print(f"Database Error: {e}")

def parse_smart_date(date_str):
    if not date_str or str(date_str).lower() in ['n/a', 'none', '', '999']: return 999
    try:
        now = datetime.now()
        try:
            target = datetime.strptime(f"{date_str} {now.year}", "%b %d %Y")
            if target < now: target = datetime.strptime(f"{date_str} {now.year + 1}", "%b %d %Y")
        except ValueError:
            target = datetime.strptime(str(date_str), "%Y-%m-%d")
        return (target - now).days
    except: return 999

def _to_float(val):
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0

def login_user(u, p):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM user_profiles WHERE username=%s", (u,))
    row = cursor.fetchone()
    conn.close()
    if row and str(row['pin']) == str(p): return row
    return None

def register_user(u, p, d, e):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT username FROM user_profiles WHERE username=%s", (u,))
    if cursor.fetchone(): conn.close(); return False
    cursor.execute("INSERT INTO user_profiles (username, pin, display_name, email) VALUES (%s,%s,%s,%s)", (u, p, d, e))
    conn.commit(); conn.close()
    return True

def create_session(u):
    t = str(uuid.uuid4())
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO user_sessions (token, username) VALUES (%s,%s)", (t, u))
    conn.commit(); conn.close()
    return t

def get_user_from_token(t):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT s.username, p.display_name, p.paper_balance, p.email FROM user_sessions s JOIN user_profiles p ON s.username=p.username WHERE s.token=%s", (t,))
    row = cursor.fetchone()
    conn.close()
    return row

def update_user_settings(username, display_name, email, new_pin=None):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        if new_pin: cursor.execute("UPDATE user_profiles SET display_name=%s, email=%s, pin=%s WHERE username=%s", (display_name, email, new_pin, username))
        else: cursor.execute("UPDATE user_profiles SET display_name=%s, email=%s WHERE username=%s", (display_name, email, username))
        conn.commit(); conn.close()
        return True
    except: return False

def get_news_data(ticker):
    news_results = []
    try:
        url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            root = ET.fromstring(resp.content)
            for item in root.findall('.//item')[:5]:
                title = item.find('title').text if item.find('title') is not None else "No Title"
                link = item.find('link').text if item.find('link') is not None else "#"
                news_results.append({'title': title, 'link': link, 'pub': "Yahoo", 'time': "Recent"})
    except: pass
    return news_results

def get_ai_analysis(ticker, headlines, current_data=None):
    if OPENAI_KEY and headlines and len(headlines) > 10:
        try:
            prompt = f"Analyze these headlines for {ticker}: {headlines} Return JSON: {{'summary': '1 sentence', 'score': 50}}"
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {OPENAI_KEY}"}
            data = {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": prompt}], "temperature": 0.3}
            response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=data, timeout=10)
            if response.status_code == 200:
                content = response.json()['choices'][0]['message']['content']
                if "```" in content: content = content.split("```")[1].replace("json", "").strip()
                parsed = json.loads(content)
                return parsed.get('summary'), parsed.get('score'), "AI"
        except: pass
    if current_data:
        rsi = float(current_data.get('rsi_14') or 50)
        trend = current_data.get('trend_status', 'NEUTRAL')
        if rsi > 70: return "Technical: Overbought (RSI > 70). Risk of pullback.", 30, "TECH"
        elif rsi < 30: return "Technical: Oversold (RSI < 30). Potential bounce.", 80, "TECH"
        elif trend == "UPTREND": return "Technical: Strong Uptrend detected.", 75, "TECH"
        return "Market sentiment is neutral. Monitor volume.", 50, "TECH"
    return "No Data Available", 50, "NONE"

def calculate_risk(row, ai_score=None):
    """Return (risk_score, label, color, badge, breakdown).

    breakdown is a list of tuples: (factor, points) where points are the
    contribution to the final risk score before clamping.
    """
    risk = 50.0
    breakdown = []

    # Trend
    trend = (row.get("trend_status") or "NEUTRAL").upper()
    if trend == "DOWNTREND":
        risk += 15
        breakdown.append(("Trend (Downtrend)", +15))
    elif trend == "UPTREND":
        risk -= 12
        breakdown.append(("Trend (Uptrend)", -12))
    else:
        risk += 3
        breakdown.append(("Trend (Neutral)", +3))

    # RSI (gradient)
    rsi = float(row.get("rsi_14") or 50)
    if rsi >= 80:
        risk += 15
        breakdown.append(("RSI (>=80 overbought)", +15))
    elif rsi >= 70:
        risk += 8
        breakdown.append(("RSI (70-79 overbought)", +8))
    elif rsi <= 20:
        risk += 12
        breakdown.append(("RSI (<=20 extreme)", +12))
    elif rsi <= 30:
        risk += 5
        breakdown.append(("RSI (21-30 oversold)", +5))
    else:
        breakdown.append(("RSI (normal)", 0))

    # Volatility (gradient)
    vol = float(row.get("volatility") or 0)
    if vol >= 6:
        risk += 18
        breakdown.append(("Volatility (>=6)", +18))
    elif vol >= 4:
        risk += 12
        breakdown.append(("Volatility (4-5.9)", +12))
    elif vol >= 2:
        risk += 6
        breakdown.append(("Volatility (2-3.9)", +6))
    else:
        breakdown.append(("Volatility (<2)", 0))

    # Debt / Equity (debt_ratio)
    debt = float(row.get("debt_ratio") or 0)
    if debt >= 200:
        risk += 15
        breakdown.append(("Debt/Equity (>=200)", +15))
    elif debt >= 120:
        risk += 8
        breakdown.append(("Debt/Equity (120-199)", +8))
    else:
        breakdown.append(("Debt/Equity (<120)", 0))

    # AI sentiment (small nudge)
    if ai_score is not None:
        adj = (50 - float(ai_score)) * 0.25
        risk += adj
        breakdown.append(("AI sentiment adjustment", round(adj, 1)))
    else:
        breakdown.append(("AI sentiment adjustment", 0))

    final = max(0, min(100, int(round(risk))))

    color = "#4ade80"
    label = "LOW"
    if final >= 70:
        color = "#ef4444"
        label = "HIGH"
    elif final >= 40:
        color = "#fbbf24"
        label = "MEDIUM"

    return final, label, color, "badge-mix", breakdown

def render_topbar(display_name: str = "User"):
    import datetime

    # Simple market status (ET-ish by your server/runtime). If you already compute market state elsewhere,
    # we can wire it in later. This version will not NameError.
    try:
        from zoneinfo import ZoneInfo
        now = datetime.datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        now = datetime.datetime.now()
    dow = now.weekday()  # 0=Mon
    minutes = now.hour * 60 + now.minute

    status = "Market Closed"
    dot_class = "pp-dot-closed"

    if dow < 5:
        if 570 <= minutes < 960:          # 09:30 - 16:00
            status = "Market Open"
            dot_class = "pp-dot-open"
        elif 240 <= minutes < 570:        # 04:00 - 09:30
            status = "Pre-Market"
            dot_class = "pp-dot-pre"
        elif 960 <= minutes < 1200:       # 16:00 - 20:00
            status = "After Hours"
            dot_class = "pp-dot-post"

    date_str = now.strftime("%A, %b %d")

    st.markdown(
        """
        <style>
/* --- Streamlit chrome: reduce top gap (can't go truly 0 on all hosts) --- */
header[data-testid="stHeader"] { display: none !important; }
div[data-testid="stDecoration"] { display: none !important; }
div[data-testid="stToolbar"] { display: none !important; }
.block-container { padding-top: 0rem !important; }

/* --- PennyPulse Topbar --- */
.pp-topbar{
  width:100%;
  margin:0px 0 10px 0;
  padding:10px 12px;
  border-radius:16px;
  background:rgba(18,22,30,0.55);
  border:1px solid rgba(255,255,255,0.08);
  backdrop-filter:blur(10px);
  -webkit-backdrop-filter:blur(10px);
  box-shadow:0 10px 30px rgba(0,0,0,0.28);

  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:12px;
  box-sizing:border-box;
  overflow:hidden; /* keeps pill inside on small screens */
}

.pp-brand{
  display:flex;
  align-items:center;
  gap:10px;
  min-width:0;
  flex:1 1 auto;
}

.pplogo{
  height:28px;            /* safe bump */
  width:auto;
  max-width:140px;        /* prevents pill push */
  display:block;
  object-fit:contain;
}

.pp-subpill{
  display:flex;
  align-items:center;
  transform: translateY(3px);
  gap:8px;
  padding:2px 2px;       /* tighter = more room */
  border-radius:999px;
  background:rgba(255,255,255,0.06);
  border:1px solid rgba(255,255,255,0.08);
  color:rgba(230,235,245,0.90);
  font-size:14px;
  font-weight:500;
  flex:0 1 auto;          /* 🔥 key change */
  min-width:0;
  white-space:nowrap;
  overflow:hidden;
  box-sizing:border-box;
}
/* --- PennyPulse Topbar --- */
.pp-topbar{
  width:100%;
  margin:0 0 10px 0;
  padding:16px 12px;
  border-radius:0px;
  background:rgba(18,22,30,0.55);
  border:1px solid rgba(255,255,255,0.08);
  backdrop-filter:blur(10px);
  -webkit-backdrop-filter:blur(10px);
  box-shadow:0 10px 30px rgba(0,0,0,0.28);

  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:12px;
  box-sizing:border-box;
}

.pp-brand{
  display:flex;
  align-items:center;
  gap:12px;
  flex:1 1 auto;
  min-width:0;
}

.pplogo{
  height:28px;
  width:auto;
  max-width:140px;
  object-fit:contain;
  flex:0 0 auto;
}

.pp-subpill{
  display:flex;
  align-items:center;
  gap:10px;
  padding:2px 2px;
  border-radius:999px;
  background:rgba(255,255,255,0.06);
  border:1px solid rgba(255,255,255,0.08);
  color:rgba(230,235,245,0.90);
  font-size:12.5px;
  flex:0 1 auto;
  min-width:200px;
  max-width: 85vw;     /* prevents pushing off screen */
  overflow:hidden;
}

/* date + status shrink correctly */
.pp-date,
.pp-status{
  flex:1 1 0;
  min-width:0;
  overflow:hidden;
  text-overflow:ellipsis;
  white-space:nowrap;
}

.pp-date{
  opacity:0.9;
}

.pp-status{
  font-weight:600;
}

.pp-dot{
  width:9px;
  height:9px;
  border-radius:50%;
  flex:0 0 auto;
}

.pp-dot-open  { background:#21c55d; box-shadow:0 0 0 4px rgba(33,197,93,0.14); }
.pp-dot-pre   { background:#f59e0b; box-shadow:0 0 0 4px rgba(245,158,11,0.14); }
.pp-dot-post  { background:#60a5fa; box-shadow:0 0 0 4px rgba(96,165,250,0.14); }
.pp-dot-closed{ background:rgba(148,163,184,0.75); box-shadow:0 0 0 4px rgba(148,163,184,0.10); }

/* remove unused right section */
.pp-right{ display:none !important; }
.pp-bell{ display:none !important; }
.pp-chip{ display:none !important; }
        """,
        unsafe_allow_html=True,
    )

    initials = "".join([p[0].upper() for p in str(display_name).split()[:2] if p]) or "U"
    logo_data = get_logo_base64("logo.png")    
    html = f"""
       <div class="pp-topbar">
       <div class="pp-brand">
        <img class="pplogo" src="data:image/png;base64,{logo_data}" alt="PennyPulse" />
        <div class="pp-subpill">
    <span class="pp-date">{date_str}</span>
    <span class="pp-dot {dot_class}"></span>
    <span class="pp-status">{status}</span>
</div>
         </div>
        <div class="pp-right">

         </div>
         </div>
    """
    st.markdown(textwrap.dedent(html).strip(), unsafe_allow_html=True)
def compute_regime(pulse_score: float) -> str:
    if pulse_score is None:
        return "—"
    if pulse_score >= 65:
        return "Risk-On"
    if pulse_score >= 45:
        return "Neutral"
    return "Risk-Off"


def arrow(delta: float) -> str:
    if delta is None:
        return "—"
    return "▲" if delta > 0 else ("▼" if delta < 0 else "•")


def fetch_pulse_environment(conn):
    # latest
    q_latest = """
        SELECT asof_date, pulse_score, momentum_breadth, accel_breadth,
               avg_global_percentile, avg_stability, liquidity_breadth
        FROM pulse_environment_daily
        ORDER BY asof_date DESC
        LIMIT 1
    """
    latest = None
    with conn.cursor(dictionary=True) as cur:
        cur.execute(q_latest)
        latest = cur.fetchone()

    if not latest:
        return None

    # 7th most recent for 7-day delta
    q_prev7 = """
        SELECT pulse_score
        FROM pulse_environment_daily
        ORDER BY asof_date DESC
        LIMIT 1 OFFSET 6
    """
    prev7 = None
    with conn.cursor(dictionary=True) as cur:
        cur.execute(q_prev7)
        row = cur.fetchone()
        prev7 = float(row["pulse_score"]) if row and row["pulse_score"] is not None else None

    pulse = float(latest["pulse_score"]) if latest["pulse_score"] is not None else None
    delta7 = (pulse - prev7) if (pulse is not None and prev7 is not None) else None

    latest["pulse_score"] = pulse
    latest["pulse_regime"] = compute_regime(pulse)
    latest["pulse_delta7"] = delta7
    latest["pulse_delta7_arrow"] = arrow(delta7)

    return latest

def calculate_confidence(row, ai_score=None):
    """Return a 0-100 confidence score (higher = cleaner/healthier setup).

    This is intentionally not just (100 - risk). It adds small bonuses for
    healthy conditions (uptrend + mid RSI) and small penalties for very high
    volatility / extremes.
    """
    risk, _, _, _, _ = calculate_risk(row, ai_score)

    confidence = 100 - int(risk)

    trend = (row.get("trend_status") or "NEUTRAL").upper()
    rsi = float(row.get("rsi_14") or 50)
    vol = float(row.get("volatility") or 0)

    if trend == "UPTREND":
        confidence += 6
    elif trend == "DOWNTREND":
        confidence -= 4

    if 40 <= rsi <= 60:
        confidence += 6
    elif rsi >= 80 or rsi <= 20:
        confidence -= 6

    if vol >= 6:
        confidence -= 10
    elif vol >= 4:
        confidence -= 6
    elif vol >= 2:
        confidence -= 2

    if ai_score is not None:
        confidence += int((float(ai_score) - 50) * 0.15)

    return max(0, min(100, int(confidence)))


def calculate_confidence(row, ai_score=None):
    """Confidence is 'opportunity / setup quality' (0-100)."""
    conf = 50.0

    trend = (row.get("trend_status") or "NEUTRAL").upper()
    if trend == "UPTREND":
        conf += 15
    elif trend == "DOWNTREND":
        conf -= 10

    rsi = float(row.get("rsi_14") or 50)
    # Prefer RSI in the middle (room to run, not extreme)
    if 40 <= rsi <= 60:
        conf += 8
    elif 30 <= rsi < 40 or 60 < rsi <= 70:
        conf += 4
    elif rsi >= 80 or rsi <= 20:
        conf -= 8

    vol = float(row.get("volatility") or 0)
    if vol < 2:
        conf += 6
    elif vol >= 6:
        conf -= 12
    elif vol >= 4:
        conf -= 8

    # Volume status (if present in cache)
    vs = (row.get("volume_status") or "").lower()
    if "unusual" in vs or "surge" in vs:
        conf += 6
    elif "low" in vs:
        conf -= 3

    # Range location (if 0-100): higher can be good *if* trend is up
    try:
        rl = float(row.get("range_loc") or 0)
        if trend == "UPTREND" and rl >= 70:
            conf += 4
    except:
        pass

    if ai_score is not None:
        conf += (float(ai_score) - 50) * 0.2

    final = max(0, min(100, int(round(conf))))
    return final


def get_watchlist_date_for_home():
    """Show NEXT day's watchlist after market close (4pm NY)."""
    now_ny = datetime.now(pytz.timezone("America/New_York"))
    if now_ny.hour >= 16:
        return (now_ny + timedelta(days=1)).date()
    return now_ny.date()

def get_watchlist_header_date():
    d = get_watchlist_date_for_home()
    return datetime(d.year, d.month, d.day).strftime("%b %d")

def get_daily_watchlist(date_obj):
    """Return up to 4 rows for the given date from daily_watchlist.
    Expects table: daily_watchlist(watch_date DATE, rank_num INT, ticker VARCHAR, label VARCHAR, score DECIMAL, created_at TIMESTAMP)
    """
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT rank_num AS rank, ticker, label, score FROM daily_watchlist WHERE watch_date=%s ORDER BY rank_num ASC LIMIT 4",
            (date_obj.strftime("%Y-%m-%d"),)
        )
        rows = cursor.fetchall()
        conn.close()
        return rows or []
    except Exception:
        return []
def _to_float(x):
    try:
        if x is None or x == "":
            return None
        return float(x)
    except Exception:
        return None


def format_extended_change(row):
    pre = _to_float(row.get("pre_market_change"))
    post = _to_float(row.get("post_market_change"))

    # Prefer after-hours first
    if post is not None and abs(post) > 0:
        color = "#4ade80" if post > 0 else "#ef4444"
        arrow = "▲" if post > 0 else "▼"
        return (
            f"<div style='margin-top:3px; font-size:0.80rem; "
            f"color:{color}; opacity:0.85;'>"
            f"POST {arrow} {post:.2f}%"
            f"</div>"
        )

    if pre is not None and abs(pre) > 0:
        color = "#4ade80" if pre > 0 else "#ef4444"
        arrow = "▲" if pre > 0 else "▼"
        return (
            f"<div style='margin-top:3px; font-size:0.80rem; "
            f"color:{color}; opacity:0.85;'>"
            f"PRE {arrow} {pre:.2f}%"
            f"</div>"
        )

    return ""
def get_watchlist_rows_for_home():
    """Home watchlist comes from daily_watchlist only (no dynamic fallback)."""
    d = get_watchlist_date_for_home()
    rows = get_daily_watchlist(d)

    if not rows:
        return []

    # Try to enrich with stock_cache price/change for nicer tiles
    tickers = [r["ticker"] for r in rows]
    cache_map = get_cached_data_map(tickers)

    out = []
    for r in rows:
        t = r["ticker"]
        label = (r.get("label") or "Momentum")
        score = r.get("score")
        if t in cache_map:
            row = cache_map[t]
            row["signal_tag"] = label
            row["_watchlist_score"] = score
            out.append(row)
        else:
            out.append({
                "ticker": t,
                "signal_tag": label,
                "current_price": None,
                "day_change": float(score or 0),
                "_watchlist_score": score
            })
    return out[:4]


def get_cached_data_map(tickers):
    if not tickers: return {}
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    format_strings = ','.join(['%s'] * len(tickers))
    cursor.execute(f"SELECT * FROM stock_cache WHERE ticker IN ({format_strings})", tuple(tickers))
    rows = cursor.fetchall()
    conn.close()
    return {row['ticker']: row for row in rows}

def get_single_stock(ticker):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM stock_cache WHERE ticker=%s", (ticker,))
    row = cursor.fetchone()
    conn.close()
    return row

def get_portfolio_details(username, ptype):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM user_portfolio WHERE username=%s AND portfolio_type=%s AND is_active=TRUE", (username, ptype))
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_portfolio_summary(username, ptype):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT SUM(realized_pl) as realized FROM user_portfolio WHERE username=%s AND portfolio_type=%s AND is_active=FALSE", (username, ptype))
    realized_row = cursor.fetchone()
    realized = float(realized_row['realized'] or 0)

    cursor.execute("SELECT p.shares, p.entry_price, s.current_price, s.day_change FROM user_portfolio p LEFT JOIN stock_cache s ON p.ticker = s.ticker WHERE p.username=%s AND p.portfolio_type=%s AND p.is_active=TRUE", (username, ptype))
    active_rows = cursor.fetchall()

    unrealized = 0.0; day_pl = 0.0; active_cost_basis = 0.0; current_portfolio_value = 0.0
    for r in active_rows:
        if r['current_price']:
            curr = float(r['current_price']); entry = float(r['entry_price']); shares = float(r['shares'])
            unrealized += ((curr * shares) - (entry * shares))
            active_cost_basis += (entry * shares)
            current_portfolio_value += (curr * shares)
            pct = float(r['day_change'] or 0)
            prev = curr / (1 + (pct/100))
            day_pl += (curr - prev) * shares
    conn.close()

    total_pl_dollars = realized + unrealized
    total_pl_pct = (total_pl_dollars / active_cost_basis) * 100 if active_cost_basis > 0 else 0
    day_pl_pct = (day_pl / (current_portfolio_value - day_pl)) * 100 if (current_portfolio_value - day_pl) > 0 else 0
    return total_pl_dollars, total_pl_pct, day_pl, day_pl_pct

def execute_paper_trade(username, ticker, action, qty, price):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT paper_balance FROM user_profiles WHERE username=%s", (username,))
    row = cursor.fetchone()
    if not row: conn.close(); return False, "User not found"

    balance = float(row[0])
    total_cost = float(qty) * float(price)

    if action == "BUY":
        if balance < total_cost: conn.close(); return False, "Insufficient Balance"
        cursor.execute("UPDATE user_profiles SET paper_balance = paper_balance - %s WHERE username=%s", (total_cost, username))
        cursor.execute("INSERT INTO user_portfolio (username, ticker, shares, entry_price, portfolio_type, is_active) VALUES (%s, %s, %s, %s, 'PAPER', 1)", (username, ticker, qty, price))
        conn.commit(); conn.close()
        return True, f"Bought {qty} shares of {ticker}"

    elif action == "SELL":
        cursor.execute("UPDATE user_profiles SET paper_balance = paper_balance + %s WHERE username=%s", (total_cost, username))
        conn.commit(); conn.close()
        return True, f"Sold {qty} shares of {ticker}"

def render_portfolio_ticker(data_map, tickers):

    items = []

    for t in tickers:
        row = data_map.get(t)
        if not row:
            continue

        try:
            chg = float(row.get("day_change") or 0)
        except:
            chg = 0.0

        sign = "+" if chg >= 0 else ""
        color = "#4ade80" if chg >= 0 else "#ef4444"

        items.append(
            f"<span style='font-weight:800; margin-right:6px;'>{t}</span>"
            f"<span style='color:{color}; font-weight:800;'>{sign}{chg:.2f}%</span>"
        )

    if not items:
        return

    content = " &nbsp; • &nbsp; ".join(items)

    st.markdown(f"""
    <style>
    .pp-ticker-wrap {{
        width:100%;
        overflow:hidden;
        padding:10px 16px;
        border-radius:0 0 20px 20px;
        margin:0px 0 10px 0;
        background:rgba(18,22,30,0.55);
        border:1px solid rgba(255,255,255,0.08);
        backdrop-filter:blur(10px);
    }}

    .pp-ticker {{
        white-space:nowrap;
        display:inline-block;
        padding-left:100%;
        animation: ticker-scroll 35s linear infinite;
        font-size:15px;
        color:#e5e7eb;
    }}

    .pp-ticker:hover {{
        animation-play-state: paused;
    }}

    @keyframes ticker-scroll {{
        0% {{ transform: translateX(0); }}
        100% {{ transform: translateX(-100%); }}
    }}
    </style>

    <div class="pp-ticker-wrap">
        <div class="pp-ticker">
            {content}
        </div>
        <div style="
        position: absolute;
        bottom: 0;
        left: 10%;
        width: 80%;
        height: 1px;
        background: linear-gradient(90deg, transparent, #4ade80, transparent);
        box-shadow: 0px -2px 10px rgba(74, 222, 128, 0.6);
    "></div>
    </div>
    """, unsafe_allow_html=True)
def deactivate_stock(username, ticker, ptype):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT p.shares, p.entry_price, s.current_price FROM user_portfolio p LEFT JOIN stock_cache s ON p.ticker = s.ticker WHERE p.username=%s AND p.ticker=%s AND p.portfolio_type=%s", (username, ticker, ptype))
    row = cursor.fetchone()
    if row:
        shares, entry, curr = row
        final_pl = (float(curr or 0) - float(entry)) * float(shares)
        cursor.execute("UPDATE user_portfolio SET is_active=FALSE, realized_pl=%s WHERE username=%s AND ticker=%s AND portfolio_type=%s", (final_pl, username, ticker, ptype))
    conn.commit()
    conn.close()


def add_ticker_to_db(username, ticker, shares, price, ptype):
    t = (ticker or "").strip().upper()
    if not t:
        return

    # Ensure it exists in stock_cache so market data can populate
    ensure_stock_cache_ticker(t)

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    # If an active row already exists for this user/ticker/ptype, update it (prevents duplicates)
    cursor.execute(
        "SELECT id FROM user_portfolio WHERE username=%s AND ticker=%s AND portfolio_type=%s AND is_active=TRUE ORDER BY id DESC LIMIT 1",
        (username, t, ptype)
    )
    existing = cursor.fetchone()

    if existing and existing.get("id"):
        cursor2 = conn.cursor()
        cursor2.execute(
            "UPDATE user_portfolio SET shares=%s, entry_price=%s WHERE id=%s",
            (shares, price, existing["id"])
        )
    else:
        cursor2 = conn.cursor()
        cursor2.execute(
            "INSERT INTO user_portfolio (username, ticker, shares, entry_price, portfolio_type, is_active) VALUES (%s,%s,%s,%s,%s, TRUE)",
            (username, t, shares, price, ptype)
        )

    conn.commit()
    conn.close()


def update_ticker_in_db(username, ticker, shares, price, ptype):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE user_portfolio SET shares=%s, entry_price=%s WHERE username=%s AND ticker=%s AND portfolio_type=%s", (shares, price, username, ticker, ptype))
    conn.commit()
    conn.close()


def update_position_by_id(pos_id, shares, price):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE user_portfolio SET shares=%s, entry_price=%s WHERE id=%s", (shares, price, pos_id))
    conn.commit()
    conn.close()

def deactivate_position_by_id(pos_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE user_portfolio SET is_active=FALSE WHERE id=%s", (pos_id,))
    conn.commit()
    conn.close()

def remove_ticker_from_db(username, ticker, ptype):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM user_portfolio WHERE username=%s AND ticker=%s AND portfolio_type=%s", (username, ticker, ptype))
    conn.commit()
    conn.close()

def add_alert(username, ticker, condition, price):
    conn = get_connection()
    cursor = conn.cursor()
    try: cursor.execute("INSERT INTO user_alerts (username, ticker, condition_type, target_price) VALUES (%s, %s, %s, %s)", (username, ticker, condition, price))
    except: pass
    conn.commit(); conn.close()

def delete_alert(alert_id):
    conn = get_connection()
    conn.cursor().execute("DELETE FROM user_alerts WHERE id = %s", (alert_id,))
    conn.commit(); conn.close()

def get_user_alerts(username):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM user_alerts WHERE username = %s ORDER BY is_triggered ASC, created_at DESC", (username,))
    rows = cursor.fetchall()
    conn.close()
    return rows

import textwrap
import streamlit as st

def render_navbar(token, mode):
    mode_arg = "&mode=PAPER" if mode == "PAPER" else ""
    current_tab = st.query_params.get("tab", "home")

    ICONS = {
        "home": """<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
            stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 10.5 12 3l9 7.5"></path>
            <path d="M5 10v10h14V10"></path>
        </svg>""",

        "portfolio": """<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
            stroke-linecap="round" stroke-linejoin="round">
            <rect x="3" y="6" width="18" height="14" rx="2"></rect>
            <path d="M3 10h18"></path>
        </svg>""",

        "alerts": """<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
            stroke-linecap="round" stroke-linejoin="round">
            <path d="M18 8a6 6 0 10-12 0c0 7-3 7-3 7h18s-3 0-3-7"></path>
            <path d="M13.7 21a2 2 0 01-3.4 0"></path>
        </svg>""",

        "scanner": """<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
            stroke-linecap="round" stroke-linejoin="round">
            <path d="M4 19v-7"></path>
            <path d="M8 19V5"></path>
            <path d="M12 19v-9"></path>
            <path d="M16 19v-4"></path>
            <path d="M20 19V8"></path>
        </svg>""",

        "settings": """<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
            stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="3"></circle>
            <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V22a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H2a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3h0a1.7 1.7 0 0 0 1-1.5V2a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5h0a1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8v0a1.7 1.7 0 0 0 1.5 1H22a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"></path>
        </svg>""",
    }

    def nav_item(tab, label):
        active = " active" if tab == current_tab else ""
        return f"""
<a href="?token={token}&tab={tab}{mode_arg}" class="pp-nav-item{active}" target="_self">
  <span class="pp-nav-ic">{ICONS[tab]}</span>
  <span class="pp-nav-txt">{label}</span>
</a>
"""

    html = f"""
<style>
.pp-nav {{
  position: fixed;
  left: 50%;
  bottom: 0px;
  transform: translateX(-50%);
  width: min(92vw, 620px);
  height: 68px;
  padding: 10px 14px calc(10px + env(safe-area-inset-bottom, 0px));
  display: flex;
  align-items: center;
  justify-content: space-around;
  gap: 8px;
  z-index: 99999;
  background: rgba(18,22,30,0.75);
  border: 2px solid rgba(255,255,255,0.06);
  border-radius: 18px;
  backdrop-filter: blur(18px);
  -webkit-backdrop-filter: blur(18px);
  box-shadow: 0 18px 60px rgba(0,0,0,0.55);

}}

.pp-nav-item {{
  flex: 1;
  text-align: center;
  text-decoration: none !important;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  color: rgba(230,235,245,0.55);
  transition: all 0.2s ease;
}}

.pp-nav-ic svg {{
  width: 22px;
  height: 22px;
  stroke-width: 1.8;
}}

.pp-nav-txt {{
  font-size: 10.5px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}}

.pp-nav-item.active {{
  color: #facc15;
  transform: translateY(-2px);
  transform: scale(0.94);
  filter: drop-shadow(0 0 6px rgba(250,204,21,0.35));
}}

.pp-nav-item.active::after {{
  content: "";
  position: absolute;
  top: -7px;
  width: 22px;
  height: 3px;
  border-radius: 999px;
  background: #facc15;
}}

section.main > div.block-container {{
  padding-bottom: 110px !important;
}}
</style>

<div class="pp-nav">
  {nav_item("home","Home")}
  {nav_item("portfolio","Stocks")}
  {nav_item("alerts","Alerts")}
  {nav_item("scanner","Monitor")}
  {nav_item("settings","Settings")}
</div>
"""

    st.markdown(textwrap.dedent(html), unsafe_allow_html=True)


def create_gauge_html(score, label, color, size="big"):
    rad = 80 if size == "big" else 60
    vb = "0 0 200 120" if size == "big" else "0 0 160 100"
    fill = (score / 100) * (3.14159 * rad)
    header = f'<div style="text-align:center; color:#94a3b8; font-size:0.9rem; font-weight:bold; letter-spacing:3px; margin-bottom:5px;">PORTFOLIO RISK</div>' if size == "big" else ""
    svg = f"""
    <svg viewBox="{vb}" style="width:100%; height:auto;">
        <defs>
            <linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" style="stop-color:#4ade80"/><stop offset="50%" style="stop-color:#fbbf24"/><stop offset="100%" style="stop-color:#ef4444"/>
            </linearGradient>
        </defs>
        <path d="M 20 100 A {rad} {rad} 0 0 1 {20+rad*2} 100" fill="none" stroke="#334155" stroke-width="15" stroke-linecap="round"/>
        <path d="M 20 100 A {rad} {rad} 0 0 1 {20+rad*2} 100" fill="none" stroke="url(#g)" stroke-width="15" stroke-linecap="round" stroke-dasharray="{fill}, 1000"/>
        <text x="{20+rad}" y="80" font-family="sans-serif" font-size="38" font-weight="bold" fill="white" text-anchor="middle">{score}</text>
        <text x="{20+rad}" y="100" font-family="sans-serif" font-size="12" font-weight="bold" fill="{color}" text-anchor="middle" letter-spacing="2">{label}</text>
    </svg>
    """
    return f'<div class="card" style="padding-bottom:0; margin-bottom:0;">{header}{svg}</div>'


def generate_playbook(stock_row):
    """Generate a simple rule-based trade plan using cached metrics.

    Uses current_price + volatility proxy for an 'expected move' and chooses a
    playbook style from trend/RSI conditions.
    """
    price = float(stock_row.get("current_price") or 0)
    if price <= 0:
        return None

    trend = (stock_row.get("trend_status") or "NEUTRAL").upper()
    rsi = float(stock_row.get("rsi_14") or 50)
    vol = float(stock_row.get("volatility") or 2.5)

    move = max(price * (vol / 100.0), price * 0.01)

    if trend == "UPTREND" and rsi < 70:
        name = "Momentum Continuation"
        entry = price * 1.005
        stop = price - (move * 1.2)
        t1 = price + (move * 1.5)
        t2 = price + (move * 3.0)
        rationale = "Uptrend + non-overbought RSI. Follow-through favored."
    elif rsi <= 30:
        name = "Oversold Bounce"
        entry = price * 1.003
        stop = price - (move * 1.6)
        t1 = price + (move * 1.2)
        t2 = price + (move * 2.2)
        rationale = "RSI oversold. Bounce setups can work—manage risk tightly."
    elif rsi >= 80:
        name = "Overbought Mean Reversion (Cautious)"
        entry = price * 0.997
        stop = price + (move * 1.2)
        t1 = price - (move * 1.2)
        t2 = price - (move * 2.2)
        rationale = "RSI very high. Reversion risk—size smaller or wait for confirmation."
    else:
        name = "Range / Wait For Trigger"
        entry = price * 1.007
        stop = price - (move * 1.4)
        t1 = price + (move * 1.3)
        t2 = price + (move * 2.4)
        rationale = "Neutral conditions. Use a trigger to avoid chop."

    def r(x):
        return round(float(x), 2)

    return {
        "name": name,
        "entry": r(entry),
        "stop": r(stop),
        "t1": r(t1),
        "t2": r(t2),
        "rationale": rationale,
        "move": r(move),
    }
def get_rank_color(label: str):
    """Return a subtle color for rank labels."""
    if not label:
        return "#9ca3af"  # neutral gray

    label = str(label).lower()

    if "elite" in label:
        return "#34d399"  # soft green
    if "strong" in label:
        return "#60a5fa"  # soft blue
    if "good" in label:
        return "#fbbf24"  # soft amber
    if "watch" in label:
        return "#f87171"  # soft red

    return "#cbd5e1"  # soft neutral


def get_rank_bg(label: str):
    """Subtle translucent background for rank label pills."""
    if not label:
        return "rgba(156, 163, 175, 0.12)"  # neutral
    l = str(label).lower()
    if "elite" in l:
        return "rgba(52, 211, 153, 0.14)"   # green
    if "strong" in l:
        return "rgba(96, 165, 250, 0.14)"   # blue
    if "good" in l:
        return "rgba(251, 191, 36, 0.14)"   # amber
    if "watch" in l:
        return "rgba(248, 113, 113, 0.14)"  # red
    return "rgba(203, 213, 225, 0.12)"      # neutral


def _strength_from_percentile(p):
    """p: 0-100 where higher is better."""
    try:
        p = float(p)
    except Exception:
        return None, None
    p = max(0.0, min(100.0, p))
    top = int(round(100.0 - p))
    if top < 1:
        top = 1
    # buckets (human, not school grades)
    if p >= 95:
        label = "Elite"
    elif p >= 80:
        label = "Strong"
    elif p >= 60:
        label = "Good"
    else:
        label = "Watch"
    return label, f"Top {top}%"

def render_portfolio_row(row, data, token=None, rank_map=None):
    """Clean 'middle card' portfolio layout (no shares/P&L, no loud borders)."""
    tkr = (row.get("ticker") or "").upper()
    company = (
        data.get("company_name")
        or data.get("name")
        or data.get("company")
        or data.get("companyName")
        or ""
    )

    price = float(data.get("current_price") or 0)
    change = float(data.get("day_change") or 0)
    change_color = "#4ade80" if change >= 0 else "#ef4444"
    day_txt = f"{change:+.2f}%"

    # Extended (pre/post) already formatted elsewhere
    extended_html = format_extended_change(data)

    # Rankings + factor scores (from rank_map)
    rinfo = (rank_map or {}).get(tkr, {}) if isinstance(rank_map, dict) else {}

    g_label, g_top = _strength_from_percentile(rinfo.get("global_percentile"))
    s_label, s_top = _strength_from_percentile(rinfo.get("sector_percentile"))
    sector = (rinfo.get("sector") or "").strip()

    # Factor scores (ints)
    def _int(v):
        try:
            return int(round(float(v)))
        except Exception:
            return None

    momo = _int(rinfo.get("momentum_score"))
    qual = _int(rinfo.get("quality_score"))
    val  = _int(rinfo.get("value_score"))
    stab = _int(rinfo.get("stability_score"))

    # Build clean lines
    rank_lines = []
    if g_label and g_top:
        rank_lines.append(
            f"<span style='opacity:0.75;'>Global Rank:</span> "
            f"<span style='color:{get_rank_color(g_label)}; background:{get_rank_bg(g_label)}; padding:1px 1px; font-weight:700;'>{g_label}</span> "
            f"<span style='opacity:0.8;'>• {g_top}</span>"
        )
    if s_label and s_top:
        sec_txt = f"  ({sector})" if sector else ""
        rank_lines.append(
            f"<span style='opacity:0.75;'>Sector Rank:</span> "
            f"<span style='color:{get_rank_color(s_label)}; background:{get_rank_bg(s_label)}; padding:1px 1px; font-weight:700;'>{s_label}</span> "
            f"<span style='opacity:0.8;'>• {s_top}{sec_txt}</span>"
        )

    factors = []
    if momo is not None: factors.append(f"<span style='color:#4ade80; background: rgba(74, 222, 128, 0.12); padding:2px 2px; border-radius:6px;'>Momentum <b>{momo}</b></span>")
    if qual is not None: factors.append(f"<span style='color:#60a5fa;background: rgba(96, 165, 250, 0.12); padding:2px 2px; border-radius:6px;'>Quality <b>{qual}</b></span>")
    if val  is not None: factors.append(f"<span style='color:#fb923c;background: rgba(251, 146, 60, 0.12); padding:2px 2px; border-radius:6px;'>Value <b>{val}</b></span>")
    if stab is not None: factors.append(f"<span style='color:#a78bfa;background: rgba(167, 139, 250, 0.12); padding:2px 2px; border-radius:6px;'>Stability <b>{stab}</b></span>")
    factors_line = " &nbsp;&nbsp; ".join(factors)


    html = f"""
<a href="/?token={token}&ticker={tkr}&tab=stocks" target="_self" style="text-decoration:none;">
  <div class=\"card\" style=\"padding:16px 16px 14px 16px; margin=bottom:22px; border-left:none;\">
    <div style=\"display:flex; justify-content:space-between; align-items:flex-start; gap:12px;\">
      <div style=\"flex:1; min-width:0;\">
        <div style=\"font-size:20px; font-weight:600; color:#FFB300; line-height:1.1;\">{tkr}</div>
        <div style=\"margin-top:6px; font-size:14px; color:#C08B28; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;\">{company}</div>
      </div>
      <div style=\"text-align:right; min-width:110px;\">
        <div style=\"font-size:20px; font-weight:600; color:#fff; line-height:1.1;\">${price:,.2f}</div>
        <div style=\"margin-top:6px; font-size:16px; font-weight:600; color:{change_color};\">{day_txt}</div>
        <div style=\"margin-top:6px;\">{extended_html}</div>
      </div>
    </div>

    {('<div style="margin-top:12px; margin-bottom:6px; font-size:14px; color:rgba(226,232,240,0.85);">' + '<br>'.join(rank_lines) + '</div>') if rank_lines else ''}

    {('<div style="margin-top:8px; font-size:14px; color:rgba(148,163,184,0.85);">' + factors_line + '</div>') if factors_line else ''}

  </div>
</a>
"""

    html = "\n".join(line.lstrip() for line in html.splitlines()).strip()
    st.markdown(textwrap.dedent(html).strip(), unsafe_allow_html=True)


def render_compact_watchlist(rows_list, current_token):
    """Small horizontal tiles for the 3 daily_watchlist picks.

    Shows: Ticker, label, price (if available), and % score (fallback to day_change).
    """
    if not rows_list:
        st.info("No watchlist yet. The nightly job will populate it after market close.")
        return

    h = '<div class="scrolling-wrapper">'
    for row in rows_list:
        t = row.get("ticker")
        label = row.get("signal_tag") or "Momentum"

        price = row.get("current_price")
        score = row.get("_watchlist_score")
        if score is None:
            try:
                score = float(row.get("day_change") or 0)
            except Exception:
                score = 0

        # Format display
        price_txt = ""
        if price is not None:
            try:
                price_txt = f"${float(price):,.2f}"
            except Exception:
                price_txt = ""

        ch = float(score or 0)
        ch_txt = f"{ch:+.2f}%"
        ch_color = "#4ade80" if ch >= 0 else "#ef4444"

        link = f"?token={current_token}&ticker={t}"
        h += (
            f"<a href='{link}' target='_self' style='text-decoration:none; color:inherit; flex:1; min-width:0;'>"
            f"<div class='click-tile' style='background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); "
            f"border: 1px solid #334155; border-radius: 8px; padding: 10px; height: 100%; "
            f"display:flex; flex-direction:column; justify-content:space-between;'>"
            f"<div style='font-weight:bold; font-size:0.95rem; color:white; margin-bottom:2px;'>{t}</div>"
            f"<div style='font-size:0.65rem; color:#facc15; font-weight:bold; margin-bottom:6px; "
            f"white-space:nowrap; overflow:hidden; text-overflow:ellipsis;'>{label}</div>"
            f"<div style='display:flex; justify-content:space-between; align-items:center;'>"
            f"<div style='font-size:0.85rem; color:white; font-weight:bold;'>{price_txt}</div>"
            f"<div style='font-size:0.85rem; font-weight:bold; color:{ch_color};'>{ch_txt}</div>"
            f"</div>"
            f"</div></a>"
        )
    h += '</div>'
    st.markdown(textwrap.dedent(h).strip(), unsafe_allow_html=True)

def _fmt_price(x):
    try:
        return f"${float(x):,.2f}"
    except Exception:
        return "—"

def _fmt_pct(x):
    try:
        return f"{float(x):+.2f}%"
    except Exception:
        return "0.00%"

def compute_anomaly_pick(rows):
    """Pick the biggest absolute % mover from the current watchlist rows."""
    if not rows:
        return None
    # Prefer true day_change if present, otherwise fall back to watchlist score
    def get_move(r):
        v = r.get("day_change")
        if v is None:
            v = r.get("_watchlist_score", 0) or 0
        try:
            return float(v)
        except Exception:
            return 0.0

    # Try to avoid duplicating the first 3 picks if possible
    primary = {r.get("ticker") for r in rows[:3] if r.get("ticker")}
    ranked = sorted(rows, key=lambda r: abs(get_move(r)), reverse=True)
    chosen = None
    for r in ranked:
        if r.get("ticker") and r.get("ticker") not in primary:
            chosen = r
            break
    if chosen is None and ranked:
        chosen = ranked[0]

    if not chosen:
        return None

    anomaly = dict(chosen)
    anomaly["signal_tag"] = "Anomaly Pick"
    anomaly["_is_anomaly"] = True
    return anomaly

def render_watchlist_pick_grid(rows, current_token=None):
    """Render 2x2 grid of pick cards: first 3 watchlist rows + anomaly pick."""
    if not rows:
        return

    cards = list(rows[:3])
    anomaly = compute_anomaly_pick(rows)
    if anomaly:
        # Avoid exact duplicate card (same ticker + label already)
        if not any((c.get("ticker")==anomaly.get("ticker") and c.get("signal_tag")==anomaly.get("signal_tag")) for c in cards):
            cards.append(anomaly)
    cards = cards[:4]

    # 2 rows of 2
    for row_i in range(0, len(cards), 2):
        cols = st.columns(2)
        for j in range(2):
            k = row_i + j
            if k >= len(cards):
                continue
            r = cards[k]
            ticker = r.get("ticker","")
            label = r.get("signal_tag","Pick")
            price = _fmt_price(r.get("current_price"))
            move = r.get("day_change")
            if move is None:
                move = r.get("_watchlist_score", 0) or 0
            pct = _fmt_pct(move)

            try:
                mv = float(move)
            except Exception:
                mv = 0.0
            color = "#22c55e" if mv > 0 else ("#ef4444" if mv < 0 else "#94a3b8")

            href = f"?tab=portfolio&ticker={ticker}"
            if current_token:
                href = f"?token={current_token}&tab=portfolio&ticker={ticker}"

            with cols[j]:
                st.markdown(f"""
<a href='{href}' style='text-decoration:none;'>
  <div class='card' style='padding:16px; min-height:118px; cursor:pointer;'>
    <div style='display:flex; align-items:flex-start; justify-content:space-between; gap:10px;'>
      <div>
        <div style='font-weight:400; font-size:.5rem; color:#e5e7eb; line-height:1.1;'>{ticker}</div>
        <div style='margin-top:6px; font-size:0.85rem; color:#facc15; font-weight:300;'>{label}</div>
      </div>
      <div style='price-block'>
        <div style='font-weight:800; font-size:1.25rem; color:#e5e7eb;'>{price}</div>
        <div style='margin-top:6px; font-weight:800; font-size:1.05rem; color:{color};'>{pct}</div>
      </div>
      </div>
    </div>
  </div>


</a>
""", unsafe_allow_html=True)

def render_simple_card(row, current_token):
    p = float(row['current_price']); ch = float(row['day_change']); cc = "#4ade80" if ch>=0 else "#ef4444"; arr = "▲" if ch>=0 else "▼"
    link = f"?token={current_token}&ticker={row['ticker']}"
    risk, _, _, _, _ = calculate_risk(row)
    html = f'<a href="{link}" target="_self" style="text-decoration:none; color:inherit; display:block;"><div class="card clickable-card" style="display:flex; justify-content:space-between; align-items:center; padding:15px;"><div><div style="font-weight:bold; font-size:1.1rem; color:white;">{row["ticker"]}</div><div style="font-size:0.8rem; color:#94a3b8;">Risk: {risk}</div></div><div style="text-align:right;"><div style="color:white; font-weight:bold;">${p:,.2f}</div><div style="color:{cc}; font-size:0.8rem;">{arr} {ch:.2f}%</div></div></div></a>'
    st.markdown(textwrap.dedent(html).strip(), unsafe_allow_html=True)


def render_horizontal_grid(rows_dict, current_token):
    # Small scroller tiles: ticker + price + % (pulled from stock_cache).
    # ✅ Sorted by day_change DESC (highest % to lowest %)
    def _chg(row):
        try:
            return float(row.get("day_change") or 0)
        except Exception:
            return 0.0

    items = sorted(rows_dict.items(), key=lambda kv: _chg(kv[1]), reverse=True)

    h = '<div class="scrolling-wrapper">'
    for ticker, row in items:
        try:
            price = float(row.get('current_price') or 0)
        except Exception:
            price = 0.0
        try:
            ch = float(row.get('day_change') or 0)
        except Exception:
            ch = 0.0

        cc = "#4ade80" if ch >= 0 else "#ef4444"
        arr = "▲" if ch >= 0 else "▼"
        link = f"?token={current_token}&ticker={ticker}"

        price_txt = f"${price:,.2f}" if price > 0 else "—"

        h += (
            f'<a href="{link}" target="_self" style="text-decoration:none; color:inherit;">'
            f'  <div class="scrolling-card click-tile" style="display:flex; flex-direction:column; justify-content:space-between; min-height:88px;">'
            f'    <div style="font-weight:bold; font-size:1.05rem; color:white; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">{ticker}</div>'
            f'    <div style="font-size:0.95rem; color:white; font-weight:bold; margin-top:6px;">{price_txt}</div>'
            f'    <div style="font-size:0.85rem; color:{cc}; font-weight:bold; margin-top:4px;">{arr} {ch:.2f}%</div>'
            f'  </div>'
            f'</a>'
        )
    h += '</div>'
    st.markdown(textwrap.dedent(h).strip(), unsafe_allow_html=True)
def get_greeting(name):
    hour = datetime.now(pytz.timezone('America/Halifax')).hour
    if hour < 12: return f"Good Morning, {name}"
    elif 12 <= hour < 18: return f"Good Afternoon, {name}"
    else: return f"Good Evening, {name}"


# =========================================================
# 3. MAIN EXECUTION
# =========================================================
init_db()


if "token" not in st.query_params:
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.image("logo.png", width=220)
        st.markdown("<div style='height:10px;'></div>", unsafe_allow_html=True)
    tab1, tab2, tab3 = st.tabs(["Login", "Register", "Forgot PIN"])
    with tab1:
        with st.form("login_form"):
            u = st.text_input("Username"); p = st.text_input("PIN", type="password")
            if st.form_submit_button("Login"):
                user_record = login_user(u, p)
                if user_record:
                    new_token = create_session(u); st.query_params["token"] = new_token; st.rerun()
                else: st.error("Invalid Credentials")
    with tab2:
        with st.form("reg_form"):
            u = st.text_input("New Username"); p = st.text_input("New PIN", type="password"); d = st.text_input("Display Name")
            if st.form_submit_button("Create Account"):
                if register_user(u, p, d, ""): st.success("Account created! Please login.")
                else: st.error("Username taken.")
    st.stop()

user = get_user_from_token(token)
if not user: st.error("Session Expired"); st.stop()

current_mode = "REAL"
render_topbar(user.get("display_name"))

if "ticker" in st.query_params:
    ticker = st.query_params["ticker"]
    stock = get_single_stock(ticker)
    if st.button("← Back", key="back_btn"): del st.query_params["ticker"]; st.rerun()
    if stock:
        news_items = get_news_data(ticker)
        headlines_txt = "\n".join([f"- {n['title']}" for n in news_items]) if news_items else ""
        ai_summary, ai_score, ai_source = get_ai_analysis(ticker, headlines_txt, stock)
        s, l, c, _, r = calculate_risk(stock, ai_score)
        confidence = calculate_confidence(stock, ai_score)
        p = float(stock['current_price']); ch = float(stock['day_change']); cc = "#4ade80" if ch>=0 else "#ef4444"

        st.markdown(f"<h1 style='margin:0; font-size: 2.5rem;'>{ticker}</h1>", unsafe_allow_html=True)
        st.markdown(f"<h2 style='margin:0; color:{cc}; font-size: 1.5rem;'>${p:,.2f} <span style='font-size:1rem; opacity:0.8;'>({ch:.2f}%) Today</span></h2>", unsafe_allow_html=True)

        if current_mode == "PAPER":
            st.markdown("---")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Buy 10", use_container_width=True):
                    ok, msg = execute_paper_trade(user['username'], ticker, "BUY", 10, p)
                    if ok: st.success("Bought 10!"); st.rerun()
                    else: st.error(msg)
            with c2:
                if st.button("Sell 10", use_container_width=True):
                    ok, msg = execute_paper_trade(user['username'], ticker, "SELL", 10, p)
                    if ok: st.success("Sold 10!"); st.rerun()
                    else: st.error(msg)
            st.markdown("---")

        st.markdown(create_gauge_html(s, l, c, "big"), unsafe_allow_html=True)
        st.markdown(f"""<div class='card' style='margin-top:12px; padding:18px;'>
            <div style='color:#94a3b8; font-size:0.8rem; font-weight:bold; letter-spacing:1px; margin-bottom:6px;'>CONFIDENCE</div>
            <div style='display:flex; align-items:center; gap:14px;'>
                <div style='font-size:2rem; font-weight:bold; color:white; line-height:1;'>{confidence}</div>
                <div style='flex:1; height:10px; background:#334155; border-radius:999px; overflow:hidden;'>
                    <div style='width:{confidence}%; height:100%; background:linear-gradient(90deg, #ef4444 0%, #fbbf24 50%, #4ade80 100%);'></div>
                </div>
            </div>
        </div>""", unsafe_allow_html=True)

        play = generate_playbook(stock)
        if play:
            st.markdown(textwrap.dedent(f"""
<div class='card' style='margin-top:15px;'>
  <div style='color:#94a3b8; font-size:0.8rem; font-weight:bold; letter-spacing:1px; margin-bottom:10px;'>
    SMART PLAYBOOK
  </div>

  <div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; gap:10px;'>
    <div style='font-size:1.05rem; font-weight:bold; color:white;'>{play["name"]}</div>
    <div style='font-size:0.75rem; color:#94a3b8; white-space:nowrap;'>Est. move: ${play["move"]}</div>
  </div>

  <div style='display:flex; gap:10px;'>
    <div class='metric-box' style='flex:1; padding:12px;'>
      <div class='metric-label'>Entry</div>
      <div class='metric-value'>${play["entry"]}</div>
    </div>
    <div class='metric-box' style='flex:1; padding:12px; border:1px solid #ef4444;'>
      <div class='metric-label'>Stop</div>
      <div class='metric-value' style='color:#ef4444;'>${play["stop"]}</div>
    </div>
  </div>

  <div style='display:flex; gap:10px; margin-top:10px;'>
    <div class='metric-box' style='flex:1; padding:12px; border:1px solid #4ade80;'>
      <div class='metric-label'>Target 1</div>
      <div class='metric-value' style='color:#4ade80;'>${play["t1"]}</div>
    </div>
    <div class='metric-box' style='flex:1; padding:12px; border:1px solid #4ade80;'>
      <div class='metric-label'>Target 2</div>
      <div class='metric-value' style='color:#4ade80;'>${play["t2"]}</div>
    </div>
  </div>

   <div style='margin-top:10px; font-size:0.9rem; color:#e0e6ed; line-height:1.4;'>
    {play["rationale"]}
  </div>
  </div>
  """), unsafe_allow_html=True)
        st.markdown(f"<div class='card' style='margin:0px; padding: 25px;'><div style='color:#94a3b8; font-size:0.8rem; font-weight:bold; letter-spacing:1px; margin-bottom:15px;'>RISK FACTORS</div>", unsafe_allow_html=True)
        def get_pill(val, type="risk"):
            if type=="vol": return "pill-high" if val > 3 else "pill-low", "HIGH" if val > 3 else "LOW"
            if type=="debt": return "pill-high" if val > 150 else "pill-low", "HIGH" if val > 150 else "LOW"
            if type=="rsi": return "pill-med" if val > 70 or val < 30 else "pill-low", "EXTREME" if val > 70 or val < 30 else "NORMAL"
            return "pill-low", "LOW"

        # RISK FACTORS (Debt/Equity + Volatility + RSI)
        d_cls, d_txt = get_pill(float(stock.get('debt_ratio') or 0), "debt")
        st.markdown(f"<div class='risk-row'><div class='risk-label'>Debt/Equity</div><div class='risk-pill {d_cls}'>{d_txt}</div></div>", unsafe_allow_html=True)

        v_cls, v_txt = get_pill(float(stock.get('volatility') or 0), "vol")
        st.markdown(f"<div class='risk-row'><div class='risk-label'>Volatility</div><div class='risk-pill {v_cls}'>{v_txt}</div></div>", unsafe_allow_html=True)

        r_cls, r_txt = get_pill(float(stock.get('rsi') or 0), "rsi")
        st.markdown(f"<div class='risk-row' style='border:none;'><div class='risk-label'>RSI Momentum</div><div class='risk-pill {r_cls}'>{r_txt}</div></div></div>", unsafe_allow_html=True)
        # Risk breakdown (why the score moved)
        bd_rows = []
        for name, pts in r:
            try:
                pts_f = float(pts)
            except:
                pts_f = 0
            if abs(pts_f) < 0.1:
                continue
            bd_rows.append(
                f"<div style='padding:8px 0; border-bottom:1px solid #2d3748;'>"
                f"<div style='color:#e0e6ed; font-size:0.9rem;'>{name}</div>"
                f"</div>"
            )
        if bd_rows:
            st.markdown(
                "<div class='card' style='margin-top:12px; padding:18px;'>"
                "<div style='color:#94a3b8; font-size:0.8rem; font-weight:bold; letter-spacing:1px; margin-bottom:8px;'>WHY THIS SCORE</div>"
                + "".join(bd_rows) +
                "</div>",
                unsafe_allow_html=True
            )

        if ai_summary:
            ai_html = f"<div class='card' style='margin-top:15px; border:1px solid #4ade80;'><div style='color:#4ade80; font-size:0.8rem; font-weight:bold; letter-spacing:1px; margin-bottom:5px;'>{ai_source} INSIGHT (Score: {ai_score})</div><div style='font-size:0.9rem; color:white; line-height:1.4;'>{ai_summary}</div></div>"
            st.markdown(textwrap.dedent(ai_html).strip(), unsafe_allow_html=True)

        if news_items:
            st.markdown(f"<div class='card' style='margin-top:15px;'><div style='color:#94a3b8; font-size:0.8rem; font-weight:bold; letter-spacing:1px; margin-bottom:15px;'>RECENT NEWS</div>", unsafe_allow_html=True)
            for item in news_items:
                st.markdown(f"<a href='{item['link']}' target='_blank' style='text-decoration:none;'><div style='font-size:0.95rem; font-weight:bold; color:#ffffff; margin-bottom:5px;'>{item['title']}</div><div style='font-size:0.75rem; color:#64748b; margin-bottom:15px;'>{item['time']} • {item['pub']}</div></a><div style='border-bottom:1px solid #2d3748; margin-bottom:15px;'></div>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)


# If we are on a ticker detail page, stop here so Home does not render underneath.
if "ticker" in st.query_params:
    st.stop()

tab = st.query_params.get("tab", "home")

if tab == "home":

    # --- NAVBAR ---
    render_navbar(token, current_mode)

    # --- Load portfolio safely ---
    portfolio = get_portfolio_details(user["username"], current_mode) or []
    tickers = []
    for r in portfolio:
        try:
            if isinstance(r, dict):
                t = (r.get("ticker") or "").strip().upper()
            else:
                t = (str(r[0]) or "").strip().upper()  # tuple fallback
            if t:
                tickers.append(t)
        except Exception:
            continue

    if not tickers:
        st.info(f"Your {current_mode} portfolio is empty.")
    else:
        # Pull cached market data for tickers
        data_map = get_cached_data_map(tickers) or {}

        # Sort by day_change DESC (high % to low %)
        def _chg(t):
            try:
                return float((data_map.get(t) or {}).get("day_change") or 0.0)
            except Exception:
                return 0.0

        tickers_sorted = sorted([t for t in tickers if t in data_map], key=_chg, reverse=True)

        # --- SCROLLING TICKER (right under topbar) ---
        if tickers_sorted:
            render_portfolio_ticker(data_map, tickers_sorted)
        else:
            st.caption("No price data cached yet for your tickers.")

    # -----------------------------
    # Market Pulse (Pulse Environment) - HOME CARD
    # -----------------------------
    try:
        conn = get_connection()
        env = fetch_pulse_environment(conn)  # expects a live DB connection

        if env:
            # --- derived labels/colors/arrows (keeps it simple + stable) ---
            pulse_score = env.get("pulse_score")
            pulse_txt = f"{float(pulse_score):.0f}" if pulse_score is not None else "—"

            env_label = env.get("environment_label") or env.get("env_label") or ""

        if not env_label:
            if pulse_score is None:
                env_label = "Neutral"
            elif float(pulse_score) >= 65:
                env_label = "Risk-On"
            elif float(pulse_score) >= 45:
                env_label = "Neutral"
            else:
                env_label = "Risk-Off"

        if pulse_score is None:
             dot_color = "#64748b"
        elif float(pulse_score) >= 65:
             dot_color = "#22c55e"
          elif float(pulse_score) >= 45:
             dot_color = "#fbbf24"
          else:
             dot_color = "#ef4444"
            regime = (env.get("pulse_regime") or "Neutral").strip()
            regime_l = regime.lower()
            if "risk-on" in regime_l or "risk on" in regime_l:
                pulse_label, pulse_color = "Risk-On", "#22c55e"
            elif "risk-off" in regime_l or "risk off" in regime_l:
                pulse_label, pulse_color = "Risk-Off", "#ef4444"
            else:
                pulse_label, pulse_color = "Neutral", "#f59e0b"

            def _arrow_and_color(val, good_if_high=True):
                if val is None:
                    return "—", "rgba(229,231,235,0.75)"
                v = float(val)
                good = (v >= 50) if good_if_high else (v < 50)
                arrow = "↑" if good else "↓"
                color = "#22c55e" if good else "#f59e0b"
                return arrow, color

            mom = env.get("momentum_breadth")
            brd = env.get("accel_breadth")  # breadth proxy
            stb = env.get("avg_stability")  # stability proxy (higher = lower volatility)

            mom_arrow, mom_color = _arrow_and_color(mom, good_if_high=True)
            brd_arrow, brd_color = _arrow_and_color(brd, good_if_high=True)
            vol_arrow, vol_color = _arrow_and_color(stb, good_if_high=True)
            # For volatility we want DOWN when stability is high
            if vol_arrow != "—":
                vol_arrow = "↓" if float(stb) >= 50 else "↑"

            market_pulse_html = textwrap.dedent(f"""
            <div class="pulse-card">
              <div class="pulse-top">
                <div class="pulse-title">MARKET PULSE</div>

                <div class="pulse-pill">
                  <span class="pulse-score">{pulse_txt} / 100</span>
                  <span class="pulse-dot" style="background:{dot_color}; box-shadow:0 0 14px {dot_color}55;"></span>
                  <span style="font-weight:900;">{env_label}</span>
                </div>
              </div>

              <div style="height:1px; background:rgba(255,255,255,0.08); margin:12px 0;"></div>

              <div class="pulse-metrics">
                <div class="pulse-metric">
                  <span style="color:{mom_col}; font-size:18px;">◆</span>
                  <span class="pulse-label">Momentum</span>
                  <span class="pulse-arrow">{mom_arrow}</span>
                </div>

                <div class="pulse-metric">
                  <span style="color:{breadth_col}; font-size:18px;">◆</span>
                  <span class="pulse-label">Breadth</span>
                  <span class="pulse-arrow">{breadth_arrow}</span>
                </div>

                <div class="pulse-metric">
                  <span style="color:{vol_col}; font-size:18px;">◆</span>
                  <span class="pulse-label">Volatility</span>
                  <span class="pulse-arrow">{vol_arrow}</span>
                </div>
              </div>
            </div>
            """).strip()

            st.markdown(market_pulse_html, unsafe_allow_html=True)

    except Exception as e:
        st.error(f"Market pulse error: {e}")


    # TODAY'S SIGNAL SHIFT (Biggest Rank Jump)
    # Uses the latest available asof_date (so weekends/holidays still show last run)
    # ==========================
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)

        # latest + previous available dates (GLOBAL ranks)
        cur.execute("SELECT MAX(asof_date) AS d FROM rankings_global_daily")
        latest_date = (cur.fetchone() or {}).get("d")

        prev_date = None
        if latest_date:
            cur.execute("SELECT MAX(asof_date) AS d FROM rankings_global_daily WHERE asof_date < %s", (latest_date,))
            prev_date = (cur.fetchone() or {}).get("d")

        row = fetch_signal_shift(cur, latest_date, prev_date) if latest_date and prev_date else None

        cur.close()
        conn.close()

        if row and int(row.get("rank_jump") or 0) > 0:
            ticker = (row.get("ticker") or "").upper()
            jump = int(row.get("rank_jump") or 0)

            bullets = []
            try:
                if float(row.get("momentum_score") or 0) > 70:
                    bullets.append("<span style='color:#4ade80;'>◆</span> Momentum accelerating")
            except Exception:
                pass
            try:
                if float(row.get("stability_score") or 0) > 70:
                    bullets.append("<span style='color:#818cf8;'>◆</span> Stability improving")
            except Exception:
                pass

            accel_html = "<br>".join(bullets)

            card_html = textwrap.dedent(f"""
    <div style="
    margin-top:30px;
    margin-bottom:0px;
    border-radius:20px;
    padding:10px 10px 20px 20px;
    background:linear-gradient(145deg,#0f172a,#0b1220);
    box-shadow:0 12px 35px rgba(0,0,0,0.45);
    position:relative;
    border:1px solid rgba(255,255,255,0.06);
    ">

      <!-- ICON BADGE -->


      <!-- TITLE ROW -->
      <div style="display:flex; justify-content:space-between; align-items:center; margin-top:0px; padding-bottom:5px; border-bottom: 1px solid #2d3748;">
       <div style="display:flex; align-items:center; gap:10px;">
      {ICON_SIGNAL}
      <div style="font-size:16px; font-weight:400; color:#cbd5e1;">
    Today's <span style="color:white;">Signal Shift</span>
      </div>
    </div>
    <div style="color:#22c55e; font-weight:600;"></div>
    </div>
      <div style="margin-top:16px; color:#fbbf24; font-size:14px; font-weight:400;">
    Biggest Rank Jump (24h)
      </div>

      <div style="margin-top:8px; font-size:14px; font-weight:600; color:white;">
    {ticker} <span style="color:#4ade80;">+{jump}</span> spots
      </div>

      {f'<div style="margin-top:12px; color:#cbd5e1; font-size: 14px; line-height:1.6;">{accel_html}</div>' if accel_html else ''}
    <div style="
        position: absolute;
        bottom: 0;           /* Sticks it to the very bottom edge */
        left: 10%;           /* Centers it */
        width: 80%;          /* Makes it 80% of the card width */
        height: 1px; 
        background: linear-gradient(90deg, transparent, #facc15, transparent);
        box-shadow: 0px -2px 10px rgba(250, 204, 21, 0.6); /* Negative Y pushes glow UP into the card */
    "></div>
    </div>

    """).strip()

            components.html(card_html, height=260)
        # else: show nothing (no blank card on weekends/holidays)

    except Exception as e:
        st.error(f"Signal Shift error: {e}")


    # ==========================
    # NEW ACCELERATION ALERTS
    # Using momentum_score acceleration (latest vs previous asof_date from rankings_global_daily)
    # ==========================
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)

        cur.execute("SELECT MAX(asof_date) AS d FROM rankings_global_daily")
        latest_date = (cur.fetchone() or {}).get("d")

        prev_date = None
        if latest_date:
            cur.execute("SELECT MAX(asof_date) AS d FROM rankings_global_daily WHERE asof_date < %s", (latest_date,))
            prev_date = (cur.fetchone() or {}).get("d")

        rows = []
        if latest_date and prev_date:
            cur.execute(
                """
                SELECT
                    d1.ticker,
                    (d1.momentum_score - d0.momentum_score) AS momentum_delta
                FROM rankings_daily d1
                JOIN rankings_daily d0
                  ON d1.ticker = d0.ticker
                WHERE d1.asof_date = %s
                  AND d0.asof_date = %s
                ORDER BY momentum_delta DESC
                LIMIT 3
                """,
                (latest_date, prev_date),
            )
            rows = cur.fetchall() or []

        cur.close()
        conn.close()

        items_html = ""
        if rows:
            for r in rows:
                t = (r.get("ticker") or "").upper()
                items_html += f"<div style='margin-top:6px; font-size:16px; font-weight:600; color:#e5e7eb;'>⚡ {t}</div>"
        else:
            items_html = "<div style='margin-top:10px; color:#94a3b8;'>No new accelerations on the latest run.</div>"

        card_html = textwrap.dedent(f"""
        <div style="
            margin-top:0px;
            margin-bottom:0px;
            border-radius:20px;
            padding:10px 10px 20px 20px;
            background:linear-gradient(145deg,#0f172a,#0b1220);
            box-shadow:0 12px 35px rgba(0,0,0,0.45);
            position:relative;
            border:1px solid rgba(255,255,255,0.06);
        ">



          <!-- TITLE ROW -->
          <div style="display:flex; justify-content:space-between; align-items:center; margin-top:0px; padding-bottom:5px; border-bottom: 1px solid #2d3748;">
            <div style="display:flex; align-items:center; gap:10px;">
      {ICON_ACCEL}
      <div style="font-size:16px; font-weight:400; color:#cbd5e1;">
    New <span style="color:white;">Acceleration Alerts</span>
      </div>
    </div>
    <div style="color:#22c55e; font-weight:600;"></div>
    </div>

          <div style="margin-top:16px; color:#fbbf24; font-size:16px; font-weight:400;">
            Stocks speeding up <span style="opacity:.7;"> (vs prior run)</span>
          </div>

          <div style="margin-top:12px; color:#cbd5e1; line-height:1.7; font-size:16px; font-weight:400;">
            {items_html}
          </div>
              <div style="
              position: absolute;
              bottom: 0;           /* Sticks it to the very bottom edge */
              left: 10%;           /* Centers it */
              width: 80%;          /* Makes it 80% of the card width */
              height: 1px; 
              background: linear-gradient(90deg, transparent, #facc15, transparent);
              box-shadow: 0px -2px 10px rgba(250, 204, 21, 0.6); /* Negative Y pushes glow UP into the card */
             "></div>
          </div>
          """).strip()

        components.html(card_html, height=260)

    except Exception as e:
      st.error(f"Acceleration Alerts error: {e}")


    # ==========================
    # SECTOR ROTATION SNAPSHOT
    # Uses rankings_sector_daily (asof_date, sector, ticker, composite_score, sector_rank, sector_count, sector_percentile)
    # Shows top 3 sectors by average composite_score change vs prior run.
    # ==========================
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)

        cur.execute("SELECT MAX(asof_date) AS d FROM rankings_sector_daily")
        latest_sector_date = (cur.fetchone() or {}).get("d")

        prev_sector_date = None
        if latest_sector_date:
            cur.execute("SELECT MAX(asof_date) AS d FROM rankings_sector_daily WHERE asof_date < %s", (latest_sector_date,))
            prev_sector_date = (cur.fetchone() or {}).get("d")

        sectors = []
        if latest_sector_date and prev_sector_date:
            cur.execute(
                """
                SELECT
                    s1.sector,
                    ROUND(AVG(s1.composite_score), 2) AS avg_score,
                    ROUND(AVG(s1.composite_score) - AVG(s0.composite_score), 2) AS score_delta
                FROM rankings_sector_daily s1
                JOIN rankings_sector_daily s0
                  ON s0.asof_date = %s
                 AND s0.ticker = s1.ticker
                 AND s0.sector = s1.sector
                WHERE s1.asof_date = %s
                GROUP BY s1.sector
                ORDER BY score_delta DESC
                LIMIT 3
                """,
                (prev_sector_date, latest_sector_date),
            )
            sectors = cur.fetchall() or []
        elif latest_sector_date:
            cur.execute(
                """
                SELECT
                    sector,
                    ROUND(AVG(composite_score), 2) AS avg_score,
                    0 AS score_delta
                FROM rankings_sector_daily
                WHERE asof_date = %s
                GROUP BY sector
                ORDER BY avg_score DESC
                LIMIT 3
                """,
                (latest_sector_date,),
            )
            sectors = cur.fetchall() or []

        cur.close()
        conn.close()

        items_html = ""
        if sectors:
            for i, s in enumerate(sectors, start=1):
                sec = s.get("sector") or ""
                delta = float(s.get("score_delta") or 0)
                delta_color = "#4ade80" if delta >= 0 else "#ef4444"
                sign = "+" if delta >= 0 else ""
                items_html += (
                    f"<div style='margin-top:8px; font-size:16px; font-weight:400; color:#e5e7eb;'>"
                    f"{i}. {sec} "
                    f"<span style='color:{delta_color}; opacity:.95;'>"
                    f"{sign}{delta:.2f}"
                    f"</span>"
                    f"</div>"
                )
        else:
            items_html = "<div style='margin-top:10px; color:#94a3b8;'>No sector data for the latest run.</div>"

        card_html = textwrap.dedent(f"""
        <div style="
            margin-top:0px;
            margin-bottom:0px;
            border-radius:20px;
            padding:10px 10px 20px 20px;
            background:linear-gradient(145deg,#0f172a,#0b1220);
            box-shadow:0 12px 35px rgba(0,0,0,0.45);
            position:relative;
            border:1px solid rgba(255,255,255,0.06);
        ">

          <!-- TITLE ROW -->
          <div style="display:flex; justify-content:space-between; align-items:center; margin-top:0px; padding-bottom:5px; border-bottom: 1px solid #2d3748;">
            <div style="display:flex; align-items:center; gap:10px;">
              {ICON_SECTOR}
              <div style="font-size:16px; font-weight:400; color:#cbd5e1;">
                Sector <span style="color:white;">Rotation Snapshot</span>
              </div>
            </div>
            <div style="color:#22c55e; font-weight:900;"></div>
          </div>

          <div style="margin-top:16px; color:#fbbf24; font-size:16px; font-weight:400;">
            Top Sectors Today
          </div>

          <div style="margin-top:12px; color:#cbd5e1; line-height:1.7;">
            {items_html}
          </div>


              <div style="
                position: absolute;
                bottom: 0;           /* Sticks it to the very bottom edge */
                left: 10%;           /* Centers it */
                width: 80%;          /* Makes it 80% of the card width */
                height: 1px; 
                background: linear-gradient(90deg, transparent, #facc15, transparent);
                box-shadow: 0px -2px 10px rgba(250, 204, 21, 0.6); /* Negative Y pushes glow UP into the card */
            "></div>
         </div>
         """).strip()

        components.html(card_html, height=280)

    except Exception as e:
        st.error(f"Sector snapshot error: {e}")

elif tab == "portfolio":

    st.markdown(f"")
    total_pl, total_pct, day_pl, day_pct = get_portfolio_summary(user['username'], current_mode)
    c_pl = "#4ade80" if total_pl >= 0 else "#ef4444"
    c_day = "#4ade80" if day_pl >= 0 else "#ef4444"
    st.markdown(f"""<div style="display:flex; gap:10px; margin-bottom:20px;"><div class="metric-box" style="flex:1;"><div class="metric-label">Total P/L</div><div class="metric-value" style="color:{c_pl}">${total_pl:,.2f}</div><div class="metric-sub" style="color:{c_pl}">({total_pct:+.2f}%)</div></div><div class="metric-box" style="flex:1;"><div class="metric-label">Today's P/L</div><div class="metric-value" style="color:{c_day}">${day_pl:,.2f}</div><div class="metric-sub" style="color:{c_day}">({day_pct:+.2f}%)</div></div></div>""", unsafe_allow_html=True)


    if current_mode == "REAL":
        with st.expander("Manage Holdings", expanded=False):
            t1, t2, t3 = st.tabs(["Add Stock", "Edit Position", "Remove Stock"])

            # --- Add ---
            with t1:
                with st.form("add_stock"):
                    c1, c2, c3 = st.columns([2, 1, 1])
                    new_t = c1.text_input("Ticker")
                    shares = c2.number_input("Shares", min_value=0.0, value=0.0, step=1.0)
                    price = c3.number_input("Avg Price", min_value=0.0, value=0.0, step=0.01)
                    if st.form_submit_button("Add to Portfolio"):
                        if new_t:
                            add_ticker_to_db(user['username'], new_t.upper(), shares, price, 'REAL')
                            st.rerun()

            # --- Edit (by id, with defaults) ---
            with t2:
                port_rows = get_portfolio_details(user['username'], 'REAL')
                if port_rows:
                    # Disambiguate duplicates by including id
                    options = {f"{r['ticker']} (id {r.get('id')})": r for r in port_rows}
                    label = st.selectbox("Select Position", list(options.keys()))
                    sel = options[label]

                    with st.form("edit_pos"):
                        c1, c2 = st.columns(2)
                        new_s = c1.number_input("New Shares", min_value=0.0, value=float(sel.get('shares') or 0.0), step=1.0)
                        new_p = c2.number_input("New Avg Price", min_value=0.0, value=float(sel.get('entry_price') or 0.0), step=0.01)
                        if st.form_submit_button("Update Position"):
                            update_position_by_id(sel.get('id'), new_s, new_p)
                            st.rerun()
                else:
                    st.info("Empty Portfolio")

            # --- Remove (by id) ---
            with t3:
                port_rows = get_portfolio_details(user['username'], 'REAL')
                if port_rows:
                    options = {f"{r['ticker']} (id {r.get('id')})": r for r in port_rows}
                    label = st.selectbox("Select Position to Remove", list(options.keys()), key="rm_select")
                    sel = options[label]
                    if st.button("Remove Selected", type="primary", key="rm_btn"):
                        deactivate_position_by_id(sel.get('id'))
                        st.rerun()
                else:
                    st.info("Portfolio is empty.")

    st.divider()
    port_rows = get_portfolio_details(user['username'], current_mode)
    if port_rows:
        tickers = [r['ticker'] for r in port_rows]
        market_data = get_cached_data_map(tickers)
        rank_map = get_rank_map_for_tickers(tickers)
        pairs = [(row, market_data[row['ticker']]) for row in port_rows if row['ticker'] in market_data]
        pairs.sort(key=lambda x: float(x[1].get('day_change') or 0), reverse=True)

        for row, data in pairs:
            render_portfolio_row(row, data, token, rank_map=rank_map)
        # (Reorder animation disabled for stability)


elif tab == "alerts":
    st.markdown("## Alerts")
    st.caption("Simple toggles. Portfolio-first. Optional: include your PennyPulse Global List.")

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    # Load current settings (safe defaults)
    cursor.execute("""
        SELECT
            telegram_enabled, telegram_chat_id,
            pct_change_enabled, pct_change_threshold,
            vol_spike_enabled,
            rsi_enabled,
            sniper_enabled,
            COALESCE(global_list_enabled, 0) AS global_list_enabled
        FROM user_alert_settings
        WHERE username=%s
        LIMIT 1
    """, (user["username"],))
    srow = cursor.fetchone() or {}

    telegram_enabled = int(srow.get("telegram_enabled") or 0) == 1
    telegram_chat_id = (srow.get("telegram_chat_id") or "").strip()

    pct_enabled = int(srow.get("pct_change_enabled") or 0) == 1
    vol_enabled = int(srow.get("vol_spike_enabled") or 0) == 1
    rsi_enabled = int(srow.get("rsi_enabled") or 0) == 1
    sniper_enabled = int(srow.get("sniper_enabled") or 0) == 1
    global_enabled = int(srow.get("global_list_enabled") or 0) == 1

    # ---------- UI ----------
    st.markdown(
        """
        <div class="card" style="border-left:4px solid #4ade80; margin-bottom:14px;">
          <div style="color:#4ade80; font-size:0.8rem; font-weight:900; letter-spacing:1px; margin-bottom:8px;">
            TELEGRAM DELIVERY (OPTIONAL)
          </div>
          <div style="font-size:0.92rem; color:#cbd5e1; line-height:1.45;">
            Turn this on if you want real-time alerts delivered to you. Otherwise, you can still view alerts inside the app.
          </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    telegram_enabled_ui = st.checkbox("Enable Telegram alerts", value=telegram_enabled)
    telegram_chat_id_ui = st.text_input(
        "Your Telegram Chat ID",
        value=telegram_chat_id,
        placeholder="Example: 123456789",
        disabled=not telegram_enabled_ui
    )

    st.markdown(
        """
        <div class="card" style="border-left:4px solid #fbbf24; margin-top: 10px; margin-bottom:24px;">
          <div style="color:#fbbf24; font-size:0.8rem; font-weight:900; letter-spacing:1px; margin-bottom:8px;">
            SCAN SCOPE
          </div>
          <div style="font-size:0.92rem; color:#cbd5e1; line-height:1.45;">
            By default, alerts scan <b>your portfolio</b>. Turn on Global List if you want PennyPulse to also scan your curated universe.
          </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    global_enabled_ui = st.checkbox("Include PennyPulse Global List (optional)", value=global_enabled)

    st.divider()
    st.markdown("### 🔔 Alert Types")

    # 1) Simple (fixed) price alert
    st.markdown("**Price Move Alert (Simple)**")
    st.caption("Fires if any tracked ticker moves **±5%** today. (No slider — always 5%.)")
    pct_enabled_ui = st.checkbox("Enable ±5% price alerts", value=pct_enabled)

    st.divider()

    # 2–4) Pro alerts (3 only)
    st.markdown("**Pro Alerts (3 pack)**")
    st.caption("These use your cached technicals/volume metrics. Keep them simple: toggle on/off.")

    vol_enabled_ui = st.checkbox(
        "🚀 Volume Surge Breakout",
        value=vol_enabled,
        help="Looks for unusual relative volume + meaningful move (great for breakouts)."
    )

    rsi_enabled_ui = st.checkbox(
        "🔄 RSI Reversal",
        value=rsi_enabled,
        help="Flags oversold/overbought reversals with a small move/volume confirmation."
    )

    sniper_enabled_ui = st.checkbox(
        "🧨 Penny Sniper",
        value=sniper_enabled,
        help="High-signal penny runners (price + move + RVOL + range + market-cap guardrails)."
    )

    st.divider()

    if st.button("Save Alert Settings"):
        # Fixed pro defaults (kept in DB so the PHP worker can rely on them)
        pct_change_threshold = 5.00
        vol_mult = 2.50
        vol_min_move = 3.00
        rsi_low = 30.00
        rsi_high = 70.00
        rsi_confirm_move = 3.00
        rsi_confirm_rvol = 1.50

        sniper_max_price = 5.0000
        sniper_min_move = 8.00
        sniper_min_rvol = 2.00
        sniper_min_range = 10.00
        sniper_max_mcap = 500000000

        cursor.execute("""
            INSERT INTO user_alert_settings (
                username,
                telegram_enabled, telegram_chat_id,
                global_list_enabled,
                pct_change_enabled, pct_change_threshold,
                vol_spike_enabled, vol_spike_mult, vol_spike_min_move,
                rsi_enabled, rsi_low, rsi_high, rsi_confirm_move, rsi_confirm_rvol,
                sniper_enabled, sniper_max_price, sniper_min_move, sniper_min_rvol, sniper_min_range, sniper_max_mcap
            ) VALUES (
                %s,%s,%s,
                %s,
                %s,%s,
                %s,%s,%s,
                %s,%s,%s,%s,%s,
                %s,%s,%s,%s,%s,%s
            )
            ON DUPLICATE KEY UPDATE
                telegram_enabled=VALUES(telegram_enabled),
                telegram_chat_id=VALUES(telegram_chat_id),
                global_list_enabled=VALUES(global_list_enabled),
                pct_change_enabled=VALUES(pct_change_enabled),
                pct_change_threshold=VALUES(pct_change_threshold),
                vol_spike_enabled=VALUES(vol_spike_enabled),
                vol_spike_mult=VALUES(vol_spike_mult),
                vol_spike_min_move=VALUES(vol_spike_min_move),
                rsi_enabled=VALUES(rsi_enabled),
                rsi_low=VALUES(rsi_low),
                rsi_high=VALUES(rsi_high),
                rsi_confirm_move=VALUES(rsi_confirm_move),
                rsi_confirm_rvol=VALUES(rsi_confirm_rvol),
                sniper_enabled=VALUES(sniper_enabled),
                sniper_max_price=VALUES(sniper_max_price),
                sniper_min_move=VALUES(sniper_min_move),
                sniper_min_rvol=VALUES(sniper_min_rvol),
                sniper_min_range=VALUES(sniper_min_range),
                sniper_max_mcap=VALUES(sniper_max_mcap)
        """, (
            user["username"],
            1 if telegram_enabled_ui else 0,
            telegram_chat_id_ui.strip() if telegram_enabled_ui else "",
            1 if global_enabled_ui else 0,
            1 if pct_enabled_ui else 0,
            float(pct_threshold),
            1 if vol_enabled_ui else 0,
            float(vol_mult),
            float(vol_min_move),
            1 if rsi_enabled_ui else 0,
            float(rsi_low),
            float(rsi_high),
            float(rsi_confirm_move),
            float(rsi_confirm_rvol),
            1 if sniper_enabled_ui else 0,
            float(sniper_max_price),
            float(sniper_min_move),
            float(sniper_min_rvol),
            float(sniper_min_range),
            float(sniper_max_mcap),
        ))
        conn.commit()
        st.success("Alert settings saved.")


    # Optional: show last 5 alerts (from alert_history)
    try:
        cursor.execute("""
            SELECT message, created_at
            FROM alert_history
            WHERE username=%s
            ORDER BY created_at DESC
            LIMIT 5
        """, (user["username"],))
        rows = cursor.fetchall() or []

        if rows:
            st.markdown("### Recent Alerts")
            alert_html = "".join(
                [f"<div style='margin-bottom:6px;'>🚨 { (r.get('message') or '') }</div>" for r in rows]
            )
            st.markdown(
                f"<div class='card' style='border-left:4px solid #ff4b4b; padding:10px'>{alert_html}</div>",
                unsafe_allow_html=True
            )
    except Exception:
        pass

    conn.close()


elif tab == "scanner":
    st.markdown("Global rankings — biggest signals first.")

    st.markdown(
        """
        <style>
          .rank-wrap { display: flex; flex-direction: column; gap: 16px; margin-top: 10px; }
          .rank-card {
            background: linear-gradient(180deg, rgba(17,24,39,0.92), rgba(15,23,42,0.92));
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 22px;
            padding: 16px 16px 16px 16px;
            margin-top:10px;
            margin-bottom:30px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.25);
          }
          .rank-top { display:flex; align-items:flex-start; justify-content:space-between; gap: 12px; }
          .rank-ticker { font-size: 20px; color:#FFB300; font-weight: 600; line-height: 1; }
          .rank-sub { color: rgba(255,255,255,0.55); font-size: 14px; margin-top: 4px; }
          .rank-right { display:flex; flex-direction: column; align-items: flex-end; gap: 8px; }
          .ring {
            width: 66px; height: 66px; border-radius: 999px;
            display:flex; align-items:center; justify-content:center;
            background: conic-gradient(#22c55e var(--p), rgba(255,255,255,0.10) 0);
            border: 1px solid rgba(255,255,255,0.10);
          }
          .ring-inner {
            width: 54px; height: 54px; border-radius: 999px;
            background: rgba(2,6,23,0.65);
            display:flex; align-items:center; justify-content:center;
            font-weight: 800; font-size: 18px;
          }
          .pill-row { display:flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
          .pill {
            padding: 7px 10px;
            border-radius: 999px;
            background: rgba(255,255,255,0.06);
            border: 1px solid rgba(255,255,255,0.08);
            font-weight: 700;
            font-size: 12px;
            letter-spacing: 0.3px;
          }
          .pill strong { opacity: 0.9; }
          .bars { margin-top: 12px; display:flex; flex-direction: column; gap: 10px; }
          .bar-row { display:flex; align-items:center; justify-content: space-between; gap: 10px; }
          .bar-label { width: 86px; color: font-size: 12px; font-weight:400; }
          .bar {
            flex: 1;
            height: 4px;
            border-radius: 999px;
            background: rgba(255,255,255,0.08);
            border: 1px solid rgba(255,255,255,0.10);
            overflow: hidden;
          }
          .bar > span {
            display:block; height:100%;
            width: var(--w);
            background: linear-gradient(90deg, rgba(34,197,94,0.95), rgba(250,204,21,0.95));
            border-radius: 999px;
          }
          .bar-val { width: 34px; text-align:right; font-size: 14px; font-weight: 400; }
          .section-title { margin-top: 18px; margin-bottom: 16px; font-size: 22px; font-weight: 800; }
        </style>
        """,
        unsafe_allow_html=True
    )

    def _int0(x):
        try:
            return int(round(float(x)))
        except Exception:
            return 0

    def _clamp01(x):
        try:
            x = float(x)
        except Exception:
            x = 0.0
        if x < 0: x = 0
        if x > 100: x = 100
        return x

    def fetch_rank_rows(order_col: str, limit: int):
        # whitelist only known columns
        allowed = {"composite_score","momentum_score","quality_score","value_score","stability_score"}
        if order_col not in allowed:
            order_col = "composite_score"

        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute(f"""
            SELECT
                ticker,
                asof_date,
                composite_score,
                momentum_score,
                quality_score,
                value_score,
                stability_score,
                confidence,
                why_json
            FROM rankings_daily
            WHERE asof_date = (SELECT MAX(asof_date) FROM rankings_daily)
            ORDER BY {order_col} DESC
            LIMIT %s
        """, (int(limit),))
        rows = cur.fetchall() or []
        cur.close()
        conn.close()
        return rows

    def render_rank_card(r: dict, badge: str | None = None):
        ticker = (r.get("ticker") or "").upper()

        # Pull scores (fail loudly if key missing)
        comp = int(r.get("composite_score") or 0)
        mom  = int(r["momentum_score"] or 0)
        qual = int(r["quality_score"] or 0)
        val  = int(r["value_score"] or 0)
        stab = int(r["stability_score"] or 0)

        html = f"""<div class="rank-card">
  <div class="rank-top">
    <div class="rank-ticker">{ticker}</div>
    <div class="rank-right">
      <div class="ring" style="--p:{_clamp01(comp)}%;">
        <div class="ring-inner">{comp}</div>
      </div>
    </div>
  </div>

  <div class="bars">
    <div class="bar-row">
      <div class="bar-label"><span style='color:#4ade80;'>Momentum</span></div>
      <div class="bar" style="--w:{_clamp01(mom)}%;"><span></span></div>
      <div class="bar-val">{mom}</div>
    </div>
    <div class="bar-row">
      <div class="bar-label"><span style='color:#60a5fa;'>Quality</span></div>
      <div class="bar" style="--w:{_clamp01(qual)}%;"><span></span></div>
      <div class="bar-val">{qual}</div>
    </div>
    <div class="bar-row">
      <div class="bar-label"><span style='color:#fb923c;'>Value</span></div>
      <div class="bar" style="--w:{_clamp01(val)}%;"><span></span></div>
      <div class="bar-val">{val}</div>
    </div>
    <div class="bar-row">
      <div class="bar-label"><span style='color:#a78bfa;'>Stability</span></div>
      <div class="bar" style="--w:{_clamp01(stab)}%;"><span></span></div>
      <div class="bar-val">{stab}</div>
    </div>
  </div>
</div>"""

        st.markdown(textwrap.dedent(html).strip(), unsafe_allow_html=True)


    # --- Top 5 ranked by composite_score ---
    top5 = fetch_rank_rows("composite_score", 5)
    if not top5:
        st.info("No rankings yet (rankings_daily is empty).")
    else:
        st.markdown('<div class="section-title">Top 5 — Ranked</div>', unsafe_allow_html=True)
        st.markdown('<div class="rank-wrap">', unsafe_allow_html=True)
        for i, r in enumerate(top5, start=1):
            render_rank_card(r, badge="Top ranked" if i == 1 else None)
        st.markdown('</div>', unsafe_allow_html=True)

        st.markdown("---")

        st.markdown('<div class="section-title">Top 3 Momentum</div>', unsafe_allow_html=True)
        for r in fetch_rank_rows("momentum_score", 3):
            render_rank_card(r)

        st.markdown('<div class="section-title">Top 3 Value</div>', unsafe_allow_html=True)
        for r in fetch_rank_rows("value_score", 3):
            render_rank_card(r)

        st.markdown('<div class="section-title">Top 3 Stability</div>', unsafe_allow_html=True)
        for r in fetch_rank_rows("stability_score", 3):
            render_rank_card(r)
        st.markdown('<div class="section-title">Top 3 Quality</div>', unsafe_allow_html=True)
        for r in fetch_rank_rows("quality_score", 3):
            render_rank_card(r)

elif tab == "settings":
    st.markdown("### Settings")
    with st.form("settings_form"):
        new_name = st.text_input("Display Name", value=user['display_name'])
        new_email = st.text_input("Recovery Email", value=user.get('email', ''))
        new_pin = st.text_input("New PIN", type="password")
        if st.form_submit_button("Save Changes"):
            if update_user_settings(user['username'], new_name, new_email, new_pin if new_pin else None): st.success("Saved!"); st.rerun()
    if st.button("Log Out"): st.query_params.clear(); st.rerun()

render_navbar(token, current_mode)
