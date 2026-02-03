import streamlit as st
import mysql.connector
from datetime import date

DB_HOST = "localhost"
DB_USER = "atlantic"
DB_PASS = "1q2w3e4R!!"
DB_NAME = "atlantic_pennypulse"

def get_conn():
    return mysql.connector.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASS,
        database=DB_NAME
    )

def load_daily_watchlist():
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT ticker, label
        FROM daily_watchlist
        WHERE watch_date = CURDATE()
        ORDER BY rank_num ASC
        LIMIT 3
    """)
    rows = cur.fetchall()
    conn.close()
    return rows

st.set_page_config(layout="wide")
st.title("Penny Pulse")

col1, col2, col3 = st.columns(3)
col1.metric("Highest Risk", "—")
col2.metric("Most Volatile", "—")
col3.metric("Next Earnings", "—")

st.markdown("---")

today = date.today().strftime("%b %d")
st.subheader(f"{today} Watchlist")

watchlist = load_daily_watchlist()

if not watchlist:
    st.warning("Watchlist not generated yet.")
else:
    cols = st.columns(3)
    for i, row in enumerate(watchlist):
        with cols[i]:
            st.markdown(
                f"""
                <div style="background:#121826;padding:20px;border-radius:12px;text-align:center">
                    <h2>{row['ticker']}</h2>
                    <p style="color:#f5c542">{row['label']}</p>
                </div>
                """,
                unsafe_allow_html=True
            )
