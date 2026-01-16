def analyze_batch(items, client):
    # 1. Pre-process hints
    prompt_list = ""
    for i, item in enumerate(items):
        hl = item['title']
        hint = ""
        upper_hl = hl.upper()
        for key, val in TICKER_MAP.items():
            if key in upper_hl:
                hint = f"(Hint: {val})"
                break
        prompt_list += f"{i+1}. {hl} {hint}\n"

    # 2. Strict Prompt
    prompt = f"""
    Analyze these {len(items)} headlines.
    Task: Identify Ticker (or "MACRO"), Signal (🟢/🔴/⚪), and 3-word reason.
    
    STRICT FORMATTING RULES:
    - Return ONLY the data lines.
    - NO introduction text.
    - NO markdown formatting.
    - Format: Ticker | Signal | Reason
    
    Headlines:
    {prompt_list}
    """
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400
        )
        
        # Safety Check: Did we get a response?
        if not response.choices:
            return []
            
        raw_text = response.choices[0].message.content.strip()
        
        # --- DEBUG: Store raw text ---
        st.session_state['last_ai_raw'] = raw_text
        
        lines = raw_text.split("\n")
        enriched_results = []
        
        # --- THE FIX: Independent Counter ---
        item_index = 0 
        
        for line in lines:
            # Cleanup
            clean_line = line.replace("```", "").replace("plaintext", "").strip()
            
            # Skip empty lines, but DO NOT increment item_index yet
            if not clean_line: 
                continue 
            
            # Stop if we have more AI lines than actual news stories
            if item_index >= len(items):
                break
                
            parts = clean_line.split("|")
            
            # Relaxed Logic: Attempt to parse
            if len(parts) >= 3:
                ticker = parts[0].strip()
                if "MACRO" in ticker or "MARKET" in ticker: ticker = "MACRO"
                
                enriched_results.append({
                    "ticker": ticker,
                    "signal": parts[1].strip(),
                    "reason": parts[2].strip(),
                    "title": items[item_index]['title'], # Safe access
                    "link": items[item_index]['link']    # Safe access
                })
                
                # Only move to the next news story if we successfully parsed this one
                item_index += 1
                
        return enriched_results

    except Exception as e:
        # Store the error so you can see it in the debugger
        st.session_state['last_ai_error'] = str(e)
        return []
