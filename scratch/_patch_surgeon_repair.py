import re

def patch_groq_cortex():
    with open('viral_finder/groq_cortex.py', 'r', encoding='utf-8') as f:
        code = f.read()
        
    if "def repair_rejected_clips_with_groq" in code:
        return
        
    repair_func = '''
def repair_rejected_clips_with_groq(rejected_candidates: list, full_transcript: list) -> list:
    """Repairs rejected short clips using Groq."""
    if not is_groq_enabled() or not full_transcript or not rejected_candidates:
        return rejected_candidates

    api_key = _get_groq_api_key()
    if not api_key:
        return rejected_candidates

    def _find_seg_idx(ts: float) -> int:
        target = float(ts or 0.0)
        for i, seg in enumerate(full_transcript):
            ss = float(seg.get("start", 0.0) or 0.0)
            ee = float(seg.get("end", ss) or ss)
            if ss <= target <= max(ss, ee):
                return i
        return max(0, min(len(full_transcript) - 1, 0 if not full_transcript else int(min(range(len(full_transcript)), key=lambda j: abs(float(full_transcript[j].get("start", 0.0) or 0.0) - target)))))

    import time
    import json
    import requests
    
    system_prompt = """You are HotShort Cortex: a world-class Narrative Surgeon for video clips.
Your ONLY job is to REPAIR clips that were rejected because they were TOO SHORT or lacked progression.
The user explicitly requested: "grok tu iss hook complete thought clips taak extend krna geniusly"
(Extend this hook up to the complete thought clips geniusly).

You MUST repair the clip by choosing EXTEND_RIGHT and finding the exact quote where the complete thought resolves in ZONE B.

Return a JSON array of objects, one per clip, with:
- "candidate_id": the ID
- "decision": "EXTEND_RIGHT"
- "proposed_payoff_quote": 5-8 words EXACTLY matching ZONE B where the thought completes.
- "payoff_segment_index": the integer index from ZONE B.
- "resolution_strength": 10
- "repair_applied": true
"""

    batch_size = 4
    batches = [rejected_candidates[i:i + batch_size] for i in range(0, len(rejected_candidates), batch_size)]
    repaired_results = []
    
    for batch_idx, batch in enumerate(batches):
        groq_input = []
        batch_meta = {}
        for c in batch:
            s0 = float(c.get("start", 0.0))
            e0 = float(c.get("end", 0.0))
            s_idx = _find_seg_idx(s0)
            e_idx = _find_seg_idx(e0)
            
            window_start = max(0, s_idx - 4)
            window_end = min(len(full_transcript), e_idx + 25)
            
            window_text = []
            for j in range(window_start, window_end):
                text = str(full_transcript[j].get("text", "")).strip()
                window_text.append(f"[{j}] {text}")
                
            cand_text = str(c.get("text", "")).strip()
            rebuilt_clip_text = " ".join(
                str(full_transcript[j].get("text", "")).strip() 
                for j in range(s_idx, min(e_idx + 1, len(full_transcript)))
            ).strip()
            if not rebuilt_clip_text: rebuilt_clip_text = cand_text
            
            groq_input.append({
                "candidate_id": str(c["id"]),
                "current_clip_text": rebuilt_clip_text,
                "transcript_window": "\\n".join(window_text)
            })
            
            batch_meta[str(c["id"])] = c
            
        payload = {
            "model": _get_groq_model(),
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "PROCESS BATCH:\\n" + json.dumps(groq_input, indent=2)}
            ]
        }
        
        max_retries = 5
        for attempt in range(max_retries):
            try:
                log.info(f"[SURGEON_REPAIR] Attempting repair for {len(batch)} clips (attempt {attempt+1}/{max_retries})")
                r = requests.post(
                    "https://api.experientiallabs.ai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json=payload,
                    timeout=_get_timeout()
                )
                if r.status_code == 429:
                    sleep_s = 2.0 * (2 ** attempt)
                    log.warning(f"[SURGEON_REPAIR] 429 Too Many Requests. Sleeping {sleep_s}s (attempt {attempt+1}/{max_retries})")
                    time.sleep(sleep_s)
                    continue
                    
                r.raise_for_status()
                data = r.json()
                content = data["choices"][0]["message"]["content"]
                parsed = parse_groq_json_safely(content)
                
                if isinstance(parsed, dict) and "candidates" in parsed:
                    arr = parsed["candidates"]
                elif isinstance(parsed, list):
                    arr = parsed
                else:
                    arr = []
                    
                for item in arr:
                    cid = str(item.get("candidate_id", ""))
                    if cid in batch_meta:
                        orig_c = batch_meta[cid]
                        orig_c["groq_surgeon"] = item
                        orig_c["groq_surgeon"]["repair_applied"] = True
                        repaired_results.append(orig_c)
                        log.info(f"[SURGEON_REPAIR] Successfully repaired via EXTEND_RIGHT. quote='{item.get('proposed_payoff_quote', '')}'")
                
                break
            except Exception as e:
                log.error(f"[SURGEON_REPAIR] Error: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2.0 * (2 ** attempt))
                    
        if batch_idx < len(batches) - 1:
            time.sleep(2.0)
            
    return repaired_results
'''
    code = code + "\\n" + repair_func
    with open('viral_finder/groq_cortex.py', 'w', encoding='utf-8') as f:
        f.write(code)

def patch_orchestrator():
    with open('viral_finder/orchestrator.py', 'r', encoding='utf-8') as f:
        code = f.read()
        
    if "Phase 4: SURGEON_REPAIR execution active" in code:
        return
        
    # Find the end of Phase 3 (EXTEND_RIGHT)
    # The code after Phase 3 logs reject_count. Wait, let's inject after the extend right audit block.
    # Actually, orchestrator has a loop for EXTEND_RIGHT. We can just add the Phase 4 block right before:
    # "log.info(f"\\n[GROQ_POST_SURGERY] kept={len(kept_candidates)} | repaired={repaired_count}")" -> Wait, repaired_count doesn't exist.
    
    # Let's find: `for c in groq_result:` that does EXTEND_RIGHT.
    target_block = """                                                    tid = fc.get("trace_id")
                                                    if tid:
                                                        ctx.trace_state(tid, "SURGEON_VALIDATED")
                                                        ctx.trace_event(
                                                            trace_id=tid,
                                                            stage="GROQ_SURGEON",
                                                            event="EXTEND_RIGHT",
                                                            changed=(round(max(old_end, new_end), 2) != round(old_end, 2)),
                                                            impact="CRITICAL" if (round(max(old_end, new_end), 2) != round(old_end, 2)) else "LOW",
                                                            score_delta=0.0
                                                        )
                                                break
                                    else:
                                        log.info(f"[EXTEND_RIGHT_REJECTED] cid={cid} r_s={r_s} payoff_idx={payoff_idx} valid_bounds={0 <= payoff_idx < len(full_transcript)} quote='{proposed_quote}'")
                                        
                    # Filter kept_candidates to those that were KEEP, MOVE_HOOK, EXTEND_RIGHT
"""
    
    # But orchestrator.py might be different. Let's do a regex to find where to insert.
    # The end of the EXTEND_RIGHT loop:
    split_str = "                    # The candidates in groq_result are copies of final_candidates"
    if split_str not in code:
        # Fallback
        split_str = "                    kept_candidates = []"
    
    if split_str not in code:
        print("Could not find insertion point in orchestrator.py")
        return
        
    phase_4_code = '''
                    log.info("[GROQ_SURGEON] Phase 4: SURGEON_REPAIR execution active.")
                    rejected_for_repair = []
                    for c in groq_result:
                        surgeon = c.get("groq_surgeon")
                        if surgeon:
                            dec = surgeon.get("decision", "")
                            rej_type = surgeon.get("rejection_type", "")
                            # We repair short clips or specific rejection types
                            if dec == "REJECT" or rej_type == "INTERCEPTED_35S_REPAIR" or rej_type in ["TOO_SHORT", "NO_MEANINGFUL_PROGRESSION", "PAYOFF_DOES_NOT_RESOLVE_HOOK", "WEAK_HOOK"]:
                                rejected_for_repair.append(c)
                                log.info(f"[SURGEON_REPAIR] Attempting repair for rejection_type={rej_type} cid={c.get('id', '?')}")
                                
                    if rejected_for_repair:
                        from viral_finder.groq_cortex import repair_rejected_clips_with_groq
                        repaired_clips = repair_rejected_clips_with_groq(rejected_for_repair, full_transcript)
                        for rep_c in repaired_clips:
                            cid = rep_c.get("id")
                            # Apply the EXTEND_RIGHT logic to the original candidate
                            surgeon = rep_c.get("groq_surgeon", {})
                            if surgeon.get("decision") == "EXTEND_RIGHT":
                                payoff_idx = int(surgeon.get("payoff_segment_index", -1))
                                if 0 <= payoff_idx < len(full_transcript):
                                    old_end = float(rep_c.get("end", 0.0))
                                    new_end = float(full_transcript[payoff_idx].get("end", 0.0))
                                    
                                    for fc in final_candidates:
                                        if fc.get("cid") == cid or fc.get("id") == cid:
                                            fc["end"] = max(old_end, new_end)
                                            fc["groq_surgeon"] = surgeon
                                            fc["groq_surgeon"]["repair_applied"] = True
                                            break
                                    
                                    # Update in groq_result so it gets kept
                                    for gc in groq_result:
                                        if gc.get("id") == cid:
                                            gc["end"] = max(old_end, new_end)
                                            gc["groq_surgeon"] = surgeon
                                            break
                                            
                                log.info(f"[SURGEON_REPAIR] Repair accepted. cid={cid}")
'''

    # Insert phase_4_code right before `kept_candidates = []`
    idx = code.rfind("                    kept_candidates = []")
    if idx != -1:
        code = code[:idx] + phase_4_code + code[idx:]
        with open('viral_finder/orchestrator.py', 'w', encoding='utf-8') as f:
            f.write(code)
        print("Patched orchestrator.py successfully.")
    else:
        print("Could not find 'kept_candidates = []'")

if __name__ == "__main__":
    patch_groq_cortex()
    patch_orchestrator()
