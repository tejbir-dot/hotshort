import os
import json
import logging
import requests
import time

log = logging.getLogger("orchestrator")

from viral_finder.groq_cortex import _get_groq_api_key, _get_groq_model, post_groq_completions

def run_tournament(candidates: list):
    """
    EXPERIMENTAL: Runs a listwise comparative tournament on the candidates.
    Does NOT modify the candidates. Just logs the results for manual comparison.
    """
    if not candidates:
        return

    api_key = _get_groq_api_key()
    if not api_key:
        log.warning("[TOURNAMENT] Missing GROQ_API_KEY")
        return

    # Filter to top 6 to fit in context window and avoid dilution
    top_candidates = candidates[:6]
    
    cards = []
    for c in top_candidates:
        cid = c.get("cid", c.get("id", "unknown"))
        text = str(c.get("text", "")).strip()
        dur = round(float(c.get("end", 0)) - float(c.get("start", 0)), 1)
        
        # Signals
        psych = c.get("signals", {}).get("psychology", {})
        nar = c.get("signals", {}).get("narrative", {})
        
        stop_scroll = psych.get("stop_scroll", 0.0)
        memorability = psych.get("memorability", 0.0)
        curiosity = psych.get("curiosity_peak", psych.get("curiosity", 0.0))
        
        loop_state = c.get("loop_state", "UNKNOWN")
        completeness = c.get("ranking_payoff_gate", 0.0)
        
        card = f"--- CANDIDATE {cid} ---\n"
        card += f"Duration: {dur}s\n"
        card += f"Transcript: \"{text}\"\n"
        card += f"Observations:\n"
        card += f" - stop_scroll (hook strength): {stop_scroll}\n"
        card += f" - curiosity_peak: {curiosity}\n"
        card += f" - memorability: {memorability}\n"
        card += f" - loop_state: {loop_state}\n"
        card += f" - completeness_gate: {completeness}\n"
        cards.append(card)

    cards_text = "\n\n".join(cards)

    prompt = f"""You are the Chief Content Officer for a short-form video platform (TikTok/Reels).
Your job is to select the absolute best viral video clip from a set of candidates.

Here are the Candidate Cards. Each card contains the transcript and raw observational signals for a clip.

{cards_text}

TASK:
1. Compare these candidates against each other.
2. Consider the Hook (stop_scroll), the narrative arc (loop_state, completeness), and the overall transcript.
3. Sort the candidates from STRONGEST (Rank 1) to WEAKEST. NO TIES ALLOWED.
4. For the top 3 comparisons (1st vs 2nd, 2nd vs 3rd, 3rd vs 4th), explain EXACTLY why the winner beat the loser.

Return ONLY a JSON object in this exact format:
{{
    "ranking": ["c_0002", "c_0005", "c_0001", ...],
    "comparisons": [
        {{
            "winner": "c_0002",
            "loser": "c_0005",
            "confidence": 0.90,
            "margin": 0.40,
            "reason": "c_0002 has a fully resolved loop and stronger hook than c_0005."
        }}
    ]
}}
"""
    log.info(f"[TOURNAMENT] Starting experiment on {len(top_candidates)} candidates...")
    
    try:
        t0 = time.time()
        response = post_groq_completions(
            payload={
                "model": _get_groq_model(),
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            },
            timeout=30,
            max_retries=3
        )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        
        parsed = json.loads(content)
        
        log.info("\n" + "="*50)
        log.info("🏆 TOURNAMENT EXPERIMENT RESULTS")
        log.info("="*50)
        
        ranking = parsed.get("ranking", [])
        log.info(f"GROQ RANKING: {ranking}")
        math_ranking = [c.get("cid", "?") for c in top_candidates]
        log.info(f"MATH RANKING: {math_ranking}")
        
        log.info("\nCOMPARISONS:")
        for comp in parsed.get("comparisons", []):
            winner = comp.get("winner")
            loser = comp.get("loser")
            margin = comp.get("margin")
            conf = comp.get("confidence")
            reason = comp.get("reason")
            log.info(f" ⚔️ {winner} > {loser} (margin: {margin}, conf: {conf})")
            log.info(f"    Reason: {reason}")
            
        log.info(f"\n[TOURNAMENT] Completed in {time.time()-t0:.2f}s")
        log.info("="*50 + "\n")
            
    except Exception as e:
        log.error(f"[TOURNAMENT] Experiment failed: {e}")
