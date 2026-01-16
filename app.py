def analyze_batch(items, client):
    if not items: return []
    
    prompt_list = ""
    for i, item in enumerate(items):
        hl = item['title']
        hint = ""
        upper_hl = hl.upper()
        for key, val in TICKER_MAP.items():
            if key in upper_hl:
                hint = f"(Hint: {val})"
                break
        # We still number them for the AI's reference, but we will strip them later
        prompt_list += f"{i+1}. {hl} {hint}\n"

    prompt = f"""
    Analyze these {len(items)} headlines.
    Task: Identify Ticker (or "MACRO"), Signal (🟢/🔴/⚪), and 3-word reason.
    
    STRICT OUTPUT RULES:
    1. Do NOT include numbers (e.g., "1.", "25.") at the start of lines.
    2. Format: Ticker | Signal | Reason
    
    Headlines:
    {prompt_list}
    """
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400
        )
        lines = response.choices[0].message.content.strip().split("\n")
        enriched_results = []
        item_index = 0
        
        for line in lines:
            clean_line = line.replace("```", "").replace("plaintext", "").strip()
            
            # --- NEW: REMOVE LEADING NUMBERS ---
            # If AI says "25. TSLA | ...", this removes the "25. "
            if len(clean_line) > 0 and clean_line[0].isdigit():
                parts = clean_line.split(".", 1)
                if len(parts) > 1:
                    clean_line = parts[1].strip()

            if not clean_line: continue
            
            if item_index >= len(items): break

            parts = clean_line.split("|")
            if len(parts) >= 3:
                ticker = parts[0].strip()
                
                # Filter logic
                sectors = ["Real estate", "Retail", "Chemical", "Earnings", "Tax", "Energy", "Airlines", "Semiconductor", "Munis"]
                if any(x in ticker for x in sectors): ticker = "MACRO"
                if len(ticker) > 6 and ticker != "BTC-USD": ticker = "MACRO"
                
                try:
                    enriched_results.append({
                        "ticker": ticker,
                        "signal": parts[1].strip(),
                        "reason": parts[2].strip(),
                        "title": items[item_index]['title'],
                        "link": items[item_index]['link']
                    })
                    item_index += 1
                except IndexError:
                    break
                    
        return enriched_results
    except Exception as e:
        st.session_state['news_error'] = str(e)
        return []
