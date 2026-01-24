import json
from datetime import datetime, timezone

import yfinance as yf
from worker.db import get_connection, get_all_users, get_global_picks

def _safe_float(x):
    try:
        return float(x)
    except Exception:
        return None

def build_universe():
    """
    Union of:
      - all user watchlists
      - global picks
    """
    tickers = set()

    for u in get_all_users():
        for t in u.get("watchlist", []):
            if t:
                tickers.add(t.upper())

    for t in get_global_picks():
        if t:
            tickers.add(t.upper())

    # Optional: filter out weird empty tokens
    return sorted([t for t in tickers if len(t) <= 32])

def upsert_market_cache(rows):
    """
    rows: list of dict {symbol, price, change_pct}
    """
    conn = get_connection()
    cur = conn.cursor()

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    raw = json.dumps({"source": "yfinance", "ts_utc": now_utc})

    for r in rows:
        cur.execute(
            """
            INSERT INTO market_cache(symbol, price, change_pct, raw_json)
            VALUES (%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
              price=VALUES(price),
              change_pct=VALUES(change_pct),
              raw_json=VALUES(raw_json)
            """,
            (r["symbol"], r["price"], r["change_pct"], raw),
        )

    conn.commit()
    conn.close()

def refresh_market_cache():
    tickers = build_universe()
    if not tickers:
        print("No tickers found in user watchlists or global picks.")
        return {"updated": 0, "skipped": 0, "tickers": 0}

    # Bulk download (much better than per-symbol calls)
    # Use 2d to compute % change from previous close
    data = yf.download(
        tickers=" ".join(tickers),
        period="2d",
        interval="1d",
        group_by="ticker",
        threads=True,
        progress=False,
    )

    updated_rows = []
    skipped = 0
    multiple = len(tickers) > 1

    for t in tickers:
        try:
            hist = data[t] if multiple else data
            if hist is None or hist.empty:
                skipped += 1
                continue

            closes = hist["Close"].dropna()
            if closes.empty:
                skipped += 1
                continue

            last = _safe_float(closes.iloc[-1])
            prev = _safe_float(closes.iloc[-2]) if len(closes) >= 2 else None

            if last is None:
                skipped += 1
                continue

            chg_pct = None
            if prev not in (None, 0):
                chg_pct = ((last - prev) / prev) * 100.0

            updated_rows.append({"symbol": t, "price": last, "change_pct": chg_pct})
        except Exception:
            skipped += 1

    if updated_rows:
        upsert_market_cache(updated_rows)

    print(f"Tickers: {len(tickers)} | Updated: {len(updated_rows)} | Skipped: {skipped}")
    return {"updated": len(updated_rows), "skipped": skipped, "tickers": len(tickers)}

if __name__ == "__main__":
    refresh_market_cache()
