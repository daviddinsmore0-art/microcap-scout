
import yfinance as yf

def get_market_movers(tickers):
    """
    Checks a list of tickers. 
    Returns a dictionary of stocks that moved MORE than 5% today.
    """
    alerts = []
    if not tickers: return []

    # Efficient Bulk Download
    data = yf.download(tickers, period="1d", group_by="ticker", progress=False)
    
    for t in tickers:
        try:
            # Handle yfinance multi-index weirdness
            if len(tickers) > 1:
                hist = data[t]
            else:
                hist = data
            
            if not hist.empty:
                current = hist['Close'].iloc[-1]
                open_price = hist['Open'].iloc[-1]
                
                pct_change = ((current - open_price) / open_price) * 100
                
                # THE ALERT TRIGGER: +/- 5% Move
                if abs(pct_change) >= 5.0:
                    trend = "🚀 MOONING" if pct_change > 0 else "🩸 DUMPING"
                    alerts.append({
                        "ticker": t,
                        "price": current,
                        "change": pct_change,
                        "trend": trend
                    })
        except: pass
        
    return alerts
