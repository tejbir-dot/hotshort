import os
import time
import threading
from viral_finder.cognition import Evidence, IntelligenceArtifact
import json
import logging
import requests
from typing import List, Dict, Any, Optional

log = logging.getLogger("groq_cortex")

class GroqKeyPool:
    """
    Multi-Key Round-Robin & Instant 429 Failover Pool for Free-Tier Groq APIs.
    Supports comma-separated keys in GROQ_API_KEY / GROQ_API_KEYS and numbered keys GROQ_API_KEY_1..20.
    """
    _lock = threading.Lock()
    _keys: List[str] = []
    _index: int = 0
    _last_logged_count: int = 0

    @classmethod
    def refresh_keys(cls) -> List[str]:
        keys = []
        # 1. Comma/semicolon separated in GROQ_API_KEY
        raw = os.environ.get("GROQ_API_KEY", "")
        for k in raw.replace(";", ",").split(","):
            k = k.strip()
            if k and k not in keys and k != "MISSING":
                keys.append(k)
        # 2. Comma/semicolon separated in GROQ_API_KEYS
        raw_multi = os.environ.get("GROQ_API_KEYS", "")
        for k in raw_multi.replace(";", ",").split(","):
            k = k.strip()
            if k and k not in keys and k != "MISSING":
                keys.append(k)
        # 3. Numbered variables GROQ_API_KEY_1 up to 20
        for i in range(1, 21):
            k = os.environ.get(f"GROQ_API_KEY_{i}", "").strip()
            if k and k not in keys and k != "MISSING":
                keys.append(k)
        cls._keys = keys
        if keys and not os.environ.get("GROQ_API_KEY", "").strip():
            os.environ["GROQ_API_KEY"] = keys[0]
        if len(keys) > 1 and len(keys) != cls._last_logged_count:
            cls._last_logged_count = len(keys)
            msg = f"\n⚡ [GROQ_POOL] Active Multi-Key Pool loaded with {len(keys)} API keys for instant 429 failover!\n"
            print(msg, flush=True)
            log.info(msg.strip())
        return keys

    @classmethod
    def get_next_key(cls) -> str:
        with cls._lock:
            cls.refresh_keys()
            if not cls._keys:
                return ""
            key = cls._keys[cls._index % len(cls._keys)]
            cls._index += 1
            return key

    @classmethod
    def get_all_keys(cls) -> List[str]:
        with cls._lock:
            cls.refresh_keys()
            return list(cls._keys)

def is_groq_enabled() -> bool:
    # Auto-disable during pytest runs to prevent test interference
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    return os.environ.get("HS_GROQ_CORTEX_ENABLED", "0").strip() == "1"

def _get_groq_api_key() -> str:
    return GroqKeyPool.get_next_key()

def post_groq_completions(payload: dict, timeout: int = None, max_retries: int = 4) -> requests.Response:
    """
    Execute POST request to Groq API with Multi-Key Round-Robin & Instant 429 Failover.
    If a 429 occurs and another key is available in the pool, switches to the next key
    immediately. If a full lap of the pool is exhausted, it sleeps before the next lap.
    """
    if timeout is None:
        timeout = _get_timeout()
    
    keys_pool = GroqKeyPool.get_all_keys()
    if not keys_pool:
        raise ValueError("No GROQ_API_KEY configured in environment")
    
    # Scale retries dynamically so we can do at least 2 full laps of the entire pool
    actual_retries = max(max_retries, len(keys_pool) * 2 + 1)
    
    response = None
    for attempt in range(actual_retries):
        current_key = GroqKeyPool.get_next_key()
        headers = {
            "Authorization": f"Bearer {current_key}",
            "Content-Type": "application/json"
        }
        try:
            response = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=timeout
            )
            if response.status_code == 429:
                if attempt == actual_retries - 1:
                    return response # Last attempt failed, return the 429 response

                # Did we just finish a full lap of the keys?
                lap_completed = (len(keys_pool) > 0) and ((attempt + 1) % len(keys_pool) == 0)
                
                # If multiple keys exist AND we haven't finished a full lap yet, instant failover
                if len(keys_pool) > 1 and not lap_completed:
                    next_k = keys_pool[(GroqKeyPool._index) % len(keys_pool)] if keys_pool else "?"
                    msg = f"⚡ [GROQ_POOL_FAILOVER] 429 Rate Limit hit on key '...{current_key[-6:]}' ➔ Shifting instantly to next API key '...{next_k[-6:]}' (Attempt {attempt+1}/{actual_retries})!"
                    print(f"\n{msg}\n", flush=True)
                    log.warning(msg)
                    continue
                
                # Otherwise, we did a full lap (or only have 1 key), so we MUST sleep to reset tokens!
                retry_tokens = response.headers.get("x-ratelimit-reset-tokens")
                retry_reqs = response.headers.get("x-ratelimit-reset-requests")
                retry_after_hdr = response.headers.get("Retry-After")
                
                # Log the exact limits for debugging
                log.warning(f"Groq Limits for '...{current_key[-6:]}': ResetTokens={retry_tokens}s, ResetReqs={retry_reqs}s, RetryAfter={retry_after_hdr}s")
                
                retry_after = retry_tokens or retry_after_hdr
                sleep_s = float(2 ** ((attempt // max(1, len(keys_pool))) + 1))
                if retry_after:
                    try:
                        sleep_s = float(retry_after)
                    except ValueError:
                        pass
                
                # If sleep is huge (e.g. daily limit), we still cap it but log a big warning
                if sleep_s > 60.0:
                    log.error(f"[GROQ_POOL] DEAD KEY: API Key '...{current_key[-6:]}' requires {sleep_s}s cooldown! (Daily limit reached?)")
                    sleep_s = 60.0
                else:
                    sleep_s = min(sleep_s, 60.0)

                lap_msg = " (lap completed)" if len(keys_pool) > 1 else ""
                log.warning(f"[GROQ_POOL] 429 Rate Limit{lap_msg}. Sleeping {sleep_s:.1f}s before next attempt ({attempt+2}/{actual_retries})...")
                time.sleep(sleep_s)
                continue
                
            return response
        except requests.exceptions.RequestException as e:
            if attempt == actual_retries - 1:
                raise
            log.warning(f"[GROQ_POOL] Request error on attempt {attempt+1}: {e}. Retrying in 1s...")
            time.sleep(1.0)
            
    return response

def _get_groq_model() -> str:
    return os.environ.get("HS_GROQ_MODEL", "llama-3.1-8b-instant").strip()

def _get_timeout() -> int:
    try:
        return int(os.environ.get("HS_GROQ_TIMEOUT_SECONDS", "20"))
    except ValueError:
        return 20

def _get_max_clips() -> int:
    try:
        return int(os.environ.get("HS_GROQ_MAX_CLIPS", "10"))
    except ValueError:
        return 10

def _get_min_score() -> int:
    try:
        return int(os.environ.get("HS_GROQ_MIN_SCORE", "72"))
    except ValueError:
        return 72

def _is_fail_open() -> bool:
    return os.environ.get("HS_GROQ_FAIL_OPEN", "1").strip() == "1"

def _is_log_reasoning() -> bool:
    return os.environ.get("HS_GROQ_LOG_REASONING", "1").strip() == "1"

def parse_groq_json_safely(response_text: str) -> dict:
    try:
        # First attempt direct parse
        return json.loads(response_text)
    except json.JSONDecodeError:
        pass
    
    # Attempt to extract JSON from markdown block
    if "```json" in response_text:
        try:
            extracted = response_text.split("```json")[1].split("```")[0].strip()
            return json.loads(extracted)
        except Exception:
            pass
    elif "```" in response_text:
        try:
            extracted = response_text.split("```")[1].split("```")[0].strip()
            return json.loads(extracted)
        except Exception:
            pass
    
    # Try finding first { and last }
    start = response_text.find('{')
    end = response_text.rfind('}')
    if start != -1 and end != -1:
        try:
            return json.loads(response_text[start:end+1])
        except Exception:
            pass

    return {}

def validate_groq_clips(parsed_json: dict, original_candidates: list) -> list:
    valid_clips = []
    
    if not isinstance(parsed_json, dict):
        return []
    
    clips = parsed_json.get("clips", [])
    if not isinstance(clips, list):
        return []

    original_ids = {str(c.get("id")) for c in original_candidates}
    min_score = _get_min_score()

    for clip in clips:
        if not isinstance(clip, dict):
            continue

        # Accept either candidate_id or id
        cid = str(clip.get("candidate_id") or clip.get("id") or "")
        if not cid or cid not in original_ids:
            continue

        # Flatten nested 'analysis' dict if present (some models wrap fields in it)
        analysis = clip.get("analysis")
        if isinstance(analysis, dict):
            for k, v in analysis.items():
                if k not in clip:
                    clip[k] = v
            
        score = clip.get("viral_score")
        # If Groq didn't return viral_score, use the existing score or assume a passing grade
        if score is None:
            existing = clip.get("existing_score", 0)
            score = float(existing) * 100 if float(existing) <= 1.0 else float(existing)
            clip["viral_score"] = round(score, 2)
        try:
            score = float(score)
        except (ValueError, TypeError):
            continue
            
        # Handle cases where Groq outputs 0.85 instead of 85
        if score <= 1.0 and min_score > 1.0:
            score = score * 100
            
        # Allow the exception rule from the prompt: high usefulness or insight passes even if viral_score < min_score
        scores = clip.get("scores", {})
        is_exceptional = False
        if isinstance(scores, dict):
            try:
                usefulness = float(scores.get("usefulness") or 0)
                insight = float(scores.get("insight_strength") or 0)
                if usefulness >= 80 or insight >= 80:
                    is_exceptional = True
            except (ValueError, TypeError):
                pass
            
        if score < min_score and not is_exceptional:
            continue
            
        # Normalise candidate_id
        clip["candidate_id"] = cid

        # Ensure adjustments are reasonable
        try:
            clip["start_adjustment_seconds"] = float(clip.get("start_adjustment_seconds", 0))
        except (ValueError, TypeError):
            clip["start_adjustment_seconds"] = 0.0
            
        try:
            # Check if groq_surgeon appended end_adjustment_seconds during review
            surgeon_adj = float(clip.get("groq_surgeon", {}).get("end_adjustment_seconds", 0))
            clip["end_adjustment_seconds"] = float(clip.get("end_adjustment_seconds", surgeon_adj))
        except (ValueError, TypeError):
            clip["end_adjustment_seconds"] = 0.0
            
        valid_clips.append(clip)
        
    # Sort by score desc, take top MAX_CLIPS
    valid_clips.sort(key=lambda x: x.get("viral_score", 0), reverse=True)
    max_clips = _get_max_clips()
    return valid_clips[:max_clips]

def merge_groq_results_with_candidates(validated_clips: list, original_candidates: list) -> list:
    merged = []
    # Create mapping of id to original candidate
    orig_map = {str(cand.get("id")): cand for cand in original_candidates}
    
    for v_clip in validated_clips:
        cid = str(v_clip.get("candidate_id", ""))
        orig = orig_map[cid]
        
        new_cand = dict(orig)
        
        # Apply adjustments safely
        orig_start = float(orig.get("start", 0))
        orig_end = float(orig.get("end", orig_start))
        
        adj_start = v_clip.get("start_adjustment_seconds", 0)
        adj_end = v_clip.get("end_adjustment_seconds", 0)
        
        # Keep inside bounds
        new_start = max(0.0, orig_start + adj_start)
        new_end = max(new_start + 0.1, orig_end + adj_end)
        
        new_cand["start"] = round(new_start, 2)
        new_cand["end"] = round(new_end, 2)
        new_cand["duration"] = round(new_end - new_start, 2)
        
        # Attach Groq specific fields
        new_cand["cortex_enabled"] = True
        
        # Instantiate Intelligence Artifact if it doesn't exist
        artifact = new_cand.get("intelligence")
        if not artifact:
            artifact = IntelligenceArtifact()
            new_cand["intelligence"] = artifact
            
        raw_score = float(v_clip.get("viral_score", 0))
        cortex_score = raw_score / 100.0 if raw_score > 1.0 else raw_score
        
        # We no longer overwrite viral_score! We emit Evidence.
        artifact.evidence_stream.extend([
            Evidence(type="stop_scroll", value=cortex_score, producer="groq_trigger", confidence=0.95),
            Evidence(type="memorability", value=float(v_clip.get("insight_strength", 0) or 0) / 100.0, producer="groq_trigger"),
            Evidence(type="usefulness", value=float(v_clip.get("usefulness", 0) or 0) / 100.0, producer="groq_trigger"),
            Evidence(type="completeness", value=float(v_clip.get("completeness_score", 0) or 0) / 100.0, producer="groq_trigger"),
        ])
        
        new_cand["title"] = v_clip.get("title", "")
        new_cand["opening_caption"] = v_clip.get("opening_caption", "")
        new_cand["why_this_clip_works"] = (
            v_clip.get("why_this_clip_is_valuable", "")
            or v_clip.get("why_dangerous_hook", "")
            + " " + v_clip.get("why_people_keep_watching", "")
        ).strip()
        new_cand["clip_archetype"] = v_clip.get("clip_archetype", "")
        new_cand["payoff"] = v_clip.get("payoff", "")
        new_cand["clip_scores"] = v_clip.get("scores", {})
        new_cand["hook_type"] = v_clip.get("hook_type", "")
        new_cand["completeness_score"] = v_clip.get("completeness_score", 0)
        new_cand["retention_risk"] = v_clip.get("retention_risk", "")
        new_cand["learning_signal_for_hotshort"] = v_clip.get("learning_signal_for_hotshort", {})
        new_cand["editing_notes"] = v_clip.get("editing_notes", {})
        
        merged.append(new_cand)
        
    return merged

def review_candidates_with_groq(candidates: List[Dict], full_transcript: List[Dict], candidate_threads: Optional[Dict] = None, creator_intent: str = None) -> List[Dict]:
    if not is_groq_enabled() or not full_transcript:
        return candidates

    api_key = _get_groq_api_key()
    if not api_key:
        log.warning("[GROQ_CORTEX] API key missing. Falling back to original candidates.")
        return candidates

    if not candidates:
        return candidates

    # Assign IDs if missing
    for i, c in enumerate(candidates):
        if "id" not in c:
            c["id"] = f"c_cand_{i}"

    try:
        max_candidates = int(os.environ.get("HS_GROQ_MAX_CANDIDATES", "30"))
    except ValueError:
        max_candidates = 20

    top_candidates = candidates[:max_candidates]

    def _find_seg_idx(ts: float) -> int:
        target = float(ts or 0.0)
        for i, seg in enumerate(full_transcript):
            ss = float(seg.get("start", 0.0) or 0.0)
            ee = float(seg.get("end", ss) or ss)
            if ss <= target <= max(ss, ee):
                return i
        return max(0, min(len(full_transcript) - 1, 0 if not full_transcript else int(min(range(len(full_transcript)), key=lambda j: abs(float(full_transcript[j].get("start", 0.0) or 0.0) - target)))))

    batch_size = 4
    batches = [top_candidates[i:i + batch_size] for i in range(0, len(top_candidates), batch_size)]
    
    # Build the Director's Lens + Decision Matrix block (appended AFTER Main Brain)
    intent_lens_block = ""
    if creator_intent:
        intent_lens_block = f"""

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 DIRECTOR'S LENS (Creator Applied)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The creator has applied a specific lens to this video: "{creator_intent}"
Your primary goal is to find the intersection of VIRAL MECHANICS and this CREATOR'S LENS.

📊 DECISION MATRIX — Follow this priority order strictly:
  PRIORITY 1 — THE JACKPOT: A moment that matches the Creator's Lens AND has strong viral potential (hook + emotion + payoff). Score these HIGHEST.
  PRIORITY 2 — THE BACKUP: A moment with incredible viral potential that loosely or partially matches the Creator's Lens.
  PRIORITY 3 — THE FAILSAFE: If the Creator's Lens topic is completely absent from the transcript, IGNORE the lens entirely and return the absolute best viral clips. NEVER return 0 clips. NEVER return a boring flat moment just because it matches the topic.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

    system_prompt = "You are HotShort Cortex: a world-class Narrative Surgeon for video clips." + """

IMPORTANT:
You have two text zones.
ZONE A = CURRENT_CLIP_TEXT
ZONE B = TRANSCRIPT_WINDOW

You MUST extract `core_idea_identified` ONLY from ZONE A (CURRENT_CLIP_TEXT).
ZONE B (TRANSCRIPT_WINDOW) exists ONLY to locate natural boundaries before and after the clip.

LOCALIZATION AUDIT:
If your extracted core_idea_identified requires ANY sentence outside ZONE A (CURRENT_CLIP_TEXT), mark `core_idea_source` as "WINDOW_DEPENDENT".
Otherwise, mark it as "CLIP_ONLY".

If your extracted idea depends on information found only in ZONE B, RETURN REJECT.

Your job is to evaluate whether a video clip forms a complete Narrative Arc: Core Idea → Development → Resolution.

A valid payoff must resolve the core idea introduced in the hook (whether it's a claim, story, belief reversal, or question).

STRICT REJECTION RULES:
- If payoff does not advance the same idea introduced by the hook, REJECT.
- If hook and payoff express essentially the same statement with no meaningful progression (zero development), REJECT.
- If payoff starts a new topic, new example, or new analogy, REJECT.
- The payoff must resolve the SAME keywords. If more than 50% of the payoff discussion moves to a different idea cluster, REJECT.

If no valid payoff exists inside the context window, DO NOT REJECT merely because the payoff is missing. First search ZONE B.
If a resolution exists: EXTEND_RIGHT.
If no resolution exists: NO_RESOLUTION_FOUND.

Only REJECT when:
- hook and payoff are same (zero development)
- topic drift
- no narrative development

Available Actions:
- KEEP: The candidate is perfect. The idea is complete with development and resolution.
- MOVE_HOOK: The candidate started too early with filler, or missed the true hook just before it. Move the hook.
- EXTEND_RIGHT: The idea resolves, but the resolution is located later in ZONE B.

CRITICAL EMERGENCY OVERRIDE:
If you receive an `emergency_instruction` in the input payload for a specific clip, you MUST prioritize it above all else. If it warns that the clip is too short (<35s), you are FORBIDDEN from selecting 'KEEP'. You MUST choose 'EXTEND_RIGHT' and find the natural resolution further down in ZONE B, or 'REJECT' if no resolution exists.
- REJECT: The candidate fails due to one of the strict rejection rules.

EXTEND_RIGHT VALIDITY RULES:
- The hook idea remains the active narrative thread.
- The proposed payoff resolves that same idea.
- The payoff sentence exists in the transcript window.
- No topic transition occurs before the payoff.

REPAIR RULE FOR SHORT CLIPS:
If the candidate clip's duration is strictly LESS THAN 35 seconds, it is highly likely that it was cut too short and lacks a proper development/payoff.
For any clip < 35 seconds, you MUST attempt to repair it by choosing EXTEND_RIGHT and finding the rest of the idea in ZONE B. Only use REJECT if the idea is completely abandoned in the transcript.

ANTI-HALLUCINATION RULE:
A resolution must be supported by exact transcript evidence.
If proposing EXTEND_RIGHT, the proposed payoff sentence must be quoted verbatim from the transcript window in `proposed_payoff_quote`.
Never summarize, invent, infer, or paraphrase a payoff.
Discover it. Do not create it.

If you choose REJECT, you MUST provide a `rejection_type`. Valid types are:
- NO_RESOLUTION_FOUND
- TOPIC_DRIFT
- ZERO_DEVELOPMENT
- NONE (if decision is not REJECT)

FORCED REASONING STEP (SHADOW MODE - Narrative Reasoning Audit):
Before you make a decision, you must map the narrative arc.
1. Extract the hook_idea (One sentence describing the core idea introduced by the hook).
2. Summarize the development_summary (One sentence describing how the idea develops between hook and payoff). Return "NONE" if hook and payoff express essentially the same statement with no meaningful progression.
3. Rate the development_score from 0-10 (how much meaningful progression happens between hook and payoff). If development_summary is "NONE", this MUST be 0.
4. Extract the payoff_idea (One sentence describing the final resolved idea).
5. Evaluate same_idea (boolean). This should only be TRUE if the payoff resolves the exact same idea introduced by the hook.
5. Extract 3-5 idea_keywords that define the core concept.
6. Rate the resolution_strength from 0-10.
7. Rate the continuity_score from 0-10 (how stable is the narrative thread?).
8. Provide a continuity_reason explaining the score.
9. Mark the core_idea_source as "CLIP_ONLY" or "WINDOW_DEPENDENT".
10. Identify the `payoff_segment_index` (integer index from ZONE B) where the thought naturally concludes.

SYSTEM_ACTION_REQUIRED:
If the clip duration is less than 35 seconds, OR if `completeness_signal` is `UNRESOLVED_REQUIRES_EXTENSION`, you MUST extend the clip by finding the exact point in ZONE B where the thought naturally concludes. 
Do this by identifying the exact `payoff_segment_index` (the integer index like [14] in ZONE B) where the thought finishes. We will mathematically extend the clip's time to match that segment. In this case, set `decision` to `"KEEP"`.

Return JSON ONLY in this exact format:
{
  "surgeon_reports": [
    {
      "candidate_id": "c_cand_0",
      "hook_segment_index": 12,
      "payoff_segment_index": 15,
      "hook_idea": "Claim: Building product is not the hard part.",
      "development_summary": "Explains that engineers naturally want to build, but that ignores the real bottleneck.",
      "development_score": 8,
      "payoff_idea": "Customer acquisition is the actual cost and challenge of startups.",
      "same_idea": true,
      "idea_keywords": ["product", "engineers", "cost", "acquisition"],
      "core_idea_source": "CLIP_ONLY",
      "resolution_strength": 9,
      "continuity_score": 8,
      "continuity_reason": "all segments discuss the cost and challenge of building a startup",
      "decision": "EXTEND_RIGHT",
      "rejection_type": "NONE",
      "rejection_reason": "none",
      "proposed_payoff_quote": "Customer acquisition is the actual cost and challenge of startups."
    }
  ]
}
""" + intent_lens_block

    if creator_intent:
        log.info(f"\n[SURGEON_ENGINE] 🎯 INJECTING DIRECTOR'S LENS: '{creator_intent}'")
        log.info(f"[SURGEON_ENGINE] 🧠 Prompt Structure: Main Brain + Decision Matrix Failsafe Active\n")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    import time
    
    audit_data = {
        "candidates_sent": len(top_candidates),
        "batches": len(batches),
        "input_tokens": 0,
        "output_tokens": 0,
        "total_latency_ms": 0.0,
        "decisions": {
            "KEEP": 0,
            "MOVE_HOOK": 0,
            "COMPLETE_IDEA": 0,
            "REJECT": 0
        }
    }

    log.info(f"[SURGEON_ENTER]\ncandidates={len(top_candidates)}")

    for batch_idx, batch in enumerate(batches):
        log.info(f"[SURGEON_BATCH]\nbatch={batch_idx+1}\ncount={len(batch)}")
        
        groq_input = []
        batch_meta = {}
        for c in batch:
            s0 = float(c.get("start", 0.0))
            e0 = float(c.get("end", s0))
            
            s_idx = _find_seg_idx(s0)
            e_idx = _find_seg_idx(e0)
            
            # Context window: approx 10s before, 30s after
            window_start = max(0, s_idx - 4)
            window_end = min(len(full_transcript), e_idx + 10)
            
            window_text = []
            for j in range(window_start, window_end):
                text = str(full_transcript[j].get("text", "")).strip()
                window_text.append(f"[{j}] {text}")
                
            cand_text = str(c.get("text", "")).strip()
            
            # Rebuild full assembled clip text from full_transcript just to be sure
            rebuilt_clip_text = " ".join(
                str(full_transcript[j].get("text", "")).strip() 
                for j in range(s_idx, min(e_idx + 1, len(full_transcript)))
            ).strip()
            
            if not rebuilt_clip_text:
                rebuilt_clip_text = cand_text
            
            words = rebuilt_clip_text.split()
            hook_t = " ".join(words[:12]) if words else ""
            payoff_t = " ".join(words[-12:]) if words else ""
            build_t = " ".join(words[12:-12]) if len(words) > 24 else (" ".join(words[12:]) if len(words) > 12 else "")
            
            full_clip_len = len(rebuilt_clip_text)
            win_text_joined = "\n".join(window_text)
            win_len = len(win_text_joined)
            
            log.info("\n[FORENSIC_PAYLOAD_DIAGNOSTIC]")
            log.info(f"candidate_id={str(c['id'])}")
            log.info(f"hook_text={hook_t}")
            log.info(f"build_text={build_t}")
            log.info(f"payoff_text={payoff_t}")
            log.info(f"full_clip_text_length={full_clip_len}")
            log.info(f"full_clip_text={rebuilt_clip_text}")
            log.info(f"window_text_length={win_len}")
            log.info(f"window_text={win_text_joined}\n")
            
            payload_text = rebuilt_clip_text
            payload_text_length = len(payload_text)
            
            log.info(f"[PAYLOAD_FIX_VERIFY] payload_text_length={payload_text_length} full_clip_text_length={full_clip_len}")
            if full_clip_len > 0:
                assert payload_text_length >= (0.90 * full_clip_len), "Payload text length is less than 90% of full clip text!"
            
            clip_dur = max(0.0, e0 - s0)
            input_dict = {
                "candidate_id": str(c["id"]),
                "current_clip_text": payload_text,
                "transcript_window": "\n".join(window_text)
            }
            
            # User's brilliant idea: Dynamic injection directly into the payload!
            if clip_dur < 35.0:
                input_dict["emergency_instruction"] = "EMERGENCY: CLIP TOO SHORT (<35s). YOU MUST EXTEND THIS CLIP (EXTEND_RIGHT) TO A NATURAL COMPLETION POINT, OR REJECT IT. DO NOT JUST 'KEEP'."
                
            groq_input.append(input_dict)
            
            cand_tokens = len(cand_text.split())
            ctx_tokens = len(win_text_joined.split())
            
            batch_meta[str(c["id"])] = {
                "duration": clip_dur,
                "hook_text": hook_t,
                "payoff_text": payoff_t,
                "arc_score": float(c.get("scores", {}).get("curiosity", c.get("curiosity", 0.0))),
                "final_score": float(c.get("viral_score", c.get("score", 0.0))),
                "candidate_tokens": cand_tokens,
                "context_tokens": ctx_tokens,
                "original_end_idx": e_idx
            }

        # --- Build full prompt (system + user merged for Gemini, separate for Groq) ---
        groq_payload = {
            "model": _get_groq_model(),
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(groq_input, indent=2)}
            ]
        }
        gemini_prompt = system_prompt + "\n\nHere is the input data:\n" + json.dumps(groq_input, indent=2)

        # --- Batch retry: Try Gemini first, then fallback to Groq ---
        _SURGEON_RETRY_DELAYS = [2, 4, 8]  # seconds between each retry attempt
        _batch_success = False

        for _retry_attempt in range(len(_SURGEON_RETRY_DELAYS) + 1):  # 1 initial + 3 retries
            try:
                start_t = time.time()
                # ── PRIMARY: Gemini Surgeon ────────────────────────────────────────────
                from viral_finder.gemini_cortex import is_gemini_enabled, post_gemini_completions, parse_gemini_json_safely
                if is_gemini_enabled():
                    log.info(f"[GROQ_SURGEON] Batch {batch_idx+1}: Routing to Gemini (primary).")
                    raw_text = post_gemini_completions(prompt=gemini_prompt, response_format_schema={"type": "json_object"})
                    latency = time.time() - start_t
                    audit_data["total_latency_ms"] += (latency * 1000)
                    parsed = parse_gemini_json_safely(raw_text)
                else:
                    # ── FALLBACK: Groq Surgeon ─────────────────────────────────────────
                    log.info(f"[GROQ_SURGEON] Batch {batch_idx+1}: Gemini not available, using Groq.")
                    response = post_groq_completions(payload=groq_payload, timeout=60, max_retries=4)
                    latency = time.time() - start_t
                    audit_data["total_latency_ms"] += (latency * 1000)
                    response.raise_for_status()
                    data = response.json()
                    content = data["choices"][0]["message"]["content"]
                    parsed = json.loads(content)
                    usage = data.get("usage", {})
                    audit_data["input_tokens"] += usage.get("prompt_tokens", 0)
                    audit_data["output_tokens"] += usage.get("completion_tokens", 0)

                pt_per_cand = 0  # Gemini doesn't expose token count the same way

                for report in parsed.get("surgeon_reports", []):
                    cid = str(report.get("candidate_id", ""))
                    meta = batch_meta.get(cid, {})
                    dec = report.get("decision", "REJECT")

                    # Mathematical Extension from Segment Index
                    try:
                        payoff_idx = int(report.get("payoff_segment_index", -1))
                        if payoff_idx >= 0 and payoff_idx < len(full_transcript) and dec in ["KEEP", "EXTEND_RIGHT"]:
                            new_end = float(full_transcript[payoff_idx].get("end", 0))
                            orig_end = float(meta.get("end", 0))
                            if new_end > orig_end:
                                report["end_adjustment_seconds"] = round(new_end - orig_end, 2)
                                log.info(f"[SURGEON_EXTENSION] Extended candidate {cid} by +{report['end_adjustment_seconds']}s based on segment [{payoff_idx}]")
                    except (ValueError, TypeError):
                        pass

                    audit_data["decisions"][dec] = audit_data["decisions"].get(dec, 0) + 1

                    reason = str(report.get("rejection_reason", "none"))
                    c_source = str(report.get("core_idea_source", "UNKNOWN"))

                    log.info("\n[SURGEON_FORENSIC_CANDIDATE]")
                    log.info(f"candidate_id={cid}")
                    log.info(f"duration={round(meta.get('duration', 0.0), 2)}")
                    log.info(f"hook_text={meta.get('hook_text', '')}")
                    log.info(f"payoff_text={meta.get('payoff_text', '')}")
                    log.info(f"arc_score={round(meta.get('arc_score', 0.0), 4)}")
                    log.info(f"final_score={round(meta.get('final_score', 0.0), 4)}")
                    log.info(f"context_tokens={meta.get('context_tokens', 0)}")
                    log.info(f"candidate_tokens={meta.get('candidate_tokens', 0)}")
                    log.info(f"prompt_tokens={pt_per_cand}")
                    log.info(f"core_idea_source={c_source}")
                    log.info(f"decision={dec}")
                    if dec in ["REJECT", "KEEP"]:
                        log.info(f"rejection_reason={reason}")

                    rej_type = str(report.get("rejection_type", "NONE"))
                    log.info(f"rejection_type={rej_type}")

                    for c in top_candidates:
                        if str(c.get("id", "")) == cid:
                            c["groq_surgeon"] = report

                            # Provide intelligence transport for Ranking decision math
                            from viral_finder.cognition import Evidence, IntelligenceArtifact
                            artifact = c.get("intelligence")
                            if not isinstance(artifact, IntelligenceArtifact):
                                artifact = IntelligenceArtifact()
                                c["intelligence"] = artifact

                            dev_score = float(report.get("development_score", 0)) / 10.0
                            res_score = float(report.get("resolution_strength", 0)) / 10.0

                            artifact.evidence_stream.extend([
                                Evidence(type="usefulness", value=dev_score, producer="groq_surgeon", confidence=0.9),
                                Evidence(type="completeness", value=res_score, producer="groq_surgeon", confidence=0.9),
                                Evidence(type="stop_scroll", value=0.95, producer="groq_surgeon", confidence=0.9),
                                Evidence(type="memorability", value=0.8, producer="groq_surgeon", confidence=0.9),
                                Evidence(type="shareability", value=0.8, producer="groq_surgeon", confidence=0.9),
                            ])

                            break

                _batch_success = True
                break  # Success — exit retry loop

            except Exception as e:
                is_rate_limit = "429" in str(e) or (
                    hasattr(e, "response") and getattr(e.response, "status_code", None) == 429
                )
                if _retry_attempt < len(_SURGEON_RETRY_DELAYS):
                    sleep_s = _SURGEON_RETRY_DELAYS[_retry_attempt]
                    if is_rate_limit:
                        log.warning(
                            f"[GROQ_SURGEON] Batch {batch_idx+1} rate-limited (429). "
                            f"Attempt {_retry_attempt+1}/{len(_SURGEON_RETRY_DELAYS)+1}. "
                            f"Cycling both keys then waiting {sleep_s}s before retry..."
                        )
                        # Force one full lap of the key pool to reset token counters
                        for _ in range(len(GroqKeyPool.get_all_keys())):
                            GroqKeyPool.get_next_key()
                    else:
                        log.warning(
                            f"[GROQ_SURGEON] Batch {batch_idx+1} failed: {e}. "
                            f"Attempt {_retry_attempt+1}/{len(_SURGEON_RETRY_DELAYS)+1}. "
                            f"Retrying in {sleep_s}s..."
                        )
                    time.sleep(sleep_s)
                else:
                    # All retries exhausted — apply local heuristic fallback so candidates
                    # are not silently left at completeness floor 0.35.
                    log.error(
                        f"[GROQ_SURGEON] Batch {batch_idx+1} permanently failed after "
                        f"{len(_SURGEON_RETRY_DELAYS)+1} attempts: {e}. "
                        f"Applying local heuristic fallback for {len(batch)} candidates."
                    )
                    from viral_finder.cognition import Evidence, IntelligenceArtifact
                    for c in batch:
                        cid = str(c.get("id", ""))
                        meta = batch_meta.get(cid, {})
                        dur = float(meta.get("duration", 0.0))

                        # Short clips (<35s) most likely need extension — give them a KEEP
                        # with conservative completeness so downstream can still extend.
                        # Long clips already had NCE contracts — give them full credit.
                        if dur < 35.0:
                            fallback_dev = 0.6
                            fallback_res = 0.6
                            fallback_dec = "KEEP"
                        else:
                            fallback_dev = 0.75
                            fallback_res = 0.75
                            fallback_dec = "KEEP"

                        fallback_report = {
                            "candidate_id": cid,
                            "decision": fallback_dec,
                            "rejection_type": "NONE",
                            "rejection_reason": "none",
                            "development_score": round(fallback_dev * 10),
                            "resolution_strength": round(fallback_res * 10),
                            "core_idea_source": "FALLBACK_HEURISTIC",
                            "_fallback_reason": "groq_surgeon_batch_rate_limited",
                        }
                        c["groq_surgeon"] = fallback_report

                        artifact = c.get("intelligence")
                        if not isinstance(artifact, IntelligenceArtifact):
                            artifact = IntelligenceArtifact()
                            c["intelligence"] = artifact

                        artifact.evidence_stream.extend([
                            Evidence(type="usefulness", value=fallback_dev, producer="groq_surgeon_fallback", confidence=0.6),
                            Evidence(type="completeness", value=fallback_res, producer="groq_surgeon_fallback", confidence=0.6),
                            Evidence(type="stop_scroll", value=0.80, producer="groq_surgeon_fallback", confidence=0.6),
                            Evidence(type="memorability", value=0.70, producer="groq_surgeon_fallback", confidence=0.6),
                            Evidence(type="shareability", value=0.70, producer="groq_surgeon_fallback", confidence=0.6),
                        ])

                        log.info(
                            f"[SURGEON_FALLBACK] cid={cid} dur={dur:.1f}s "
                            f"→ decision={fallback_dec} dev={fallback_dev} res={fallback_res} "
                            f"(heuristic, no Groq)"
                        )
                        audit_data["decisions"][fallback_dec] = audit_data["decisions"].get(fallback_dec, 0) + 1

        # Inter-batch cooldown: only when single-key mode (multi-key pool self-manages via post_groq_completions)
        if batch_idx < len(batches) - 1 and len(GroqKeyPool.get_all_keys()) <= 1:
            time.sleep(1.5)

    total_tokens = audit_data["input_tokens"] + audit_data["output_tokens"]
    c_count = audit_data["candidates_sent"] or 1
    t_per_c = total_tokens / c_count
    # Blended estimate: $0.59/1M input, $0.79/1M output for Llama 3 70B
    cost_estimate = (audit_data["input_tokens"] / 1_000_000 * 0.59) + (audit_data["output_tokens"] / 1_000_000 * 0.79)
    avg_lat = audit_data["total_latency_ms"] / audit_data["batches"] if audit_data["batches"] else 0

    log.info("\n[GROQ_AUDIT]")
    log.info(f"candidates_sent={audit_data['candidates_sent']}")
    log.info(f"batches={audit_data['batches']}")
    log.info(f"input_tokens={audit_data['input_tokens']}")
    log.info(f"output_tokens={audit_data['output_tokens']}")
    log.info(f"tokens_per_candidate={round(t_per_c)}")
    log.info(f"cost_estimate=${cost_estimate:.5f}")
    log.info(f"avg_decision_latency={round(avg_lat)}ms")
    log.info(f"decision_distribution={json.dumps(audit_data['decisions'])}\n")

    return candidates


def _chunk_transcript(segments: list, video_duration: float, window_size: float = 240.0, overlap: float = 30.0) -> list:
    chunks = []
    if not segments:
        return chunks
    
    current_start = 0.0
    # If video is extremely short (e.g. <= window_size), just do one chunk
    if video_duration <= window_size:
        chunks.append({
            "start": 0.0,
            "end": video_duration,
            "segments": segments
        })
        return chunks
        
    while current_start < video_duration:
        current_end = current_start + window_size
        # Gather segments in this window
        chunk_segs = [
            s for s in segments
            if float(s.get("start", 0)) >= current_start
            and float(s.get("start", 0)) < current_end
        ]
        if chunk_segs:
            chunks.append({
                "start": current_start,
                "end": min(current_end, video_duration),
                "segments": chunk_segs
            })
        current_start += (window_size - overlap)
        if window_size <= overlap:
            break
            
    return chunks


def validate_groq_moments(moments: list, video_duration: float) -> list:
    valid_moments = []
    
    # 4. Add env controls: HS_GROQ_DIRECTOR_MIN_SCORE=60
    director_min_score_raw = os.environ.get("HS_GROQ_DIRECTOR_MIN_SCORE")
    if director_min_score_raw:
        try:
            min_score = float(director_min_score_raw)
        except ValueError:
            min_score = 60.0
    else:
        min_score = 60.0

    for idx, m in enumerate(moments):
        if not isinstance(m, dict):
            continue
            
        cid = str(m.get("candidate_id") or m.get("id") or f"moment_{idx}")
        title = str(m.get("title") or "Untitled")
        
        try:
            start = float(m.get("start", -1))
            end = float(m.get("end", -1))
        except (ValueError, TypeError):
            log.info(f"[GROQ_DIRECTOR_REJECT] candidate_id={cid} start=-1 end=-1 title={title} viral_score=0 usefulness=0 insight_strength=0 reject_reason=invalid_timestamps")
            continue
            
        if start < 0 or end < 0 or start >= end:
            log.info(f"[GROQ_DIRECTOR_REJECT] candidate_id={cid} start={start} end={end} title={title} viral_score=0 usefulness=0 insight_strength=0 reject_reason=negative_or_inverted_timestamps")
            continue
            
        # Ensure it fits within video duration
        if video_duration and end > video_duration + 5.0:  # allow 5s grace
            end = video_duration
            
        dur = end - start
        
        # allow 8s–75s moments
        if dur < 8.0 or dur > 75.0:
            log.info(f"[GROQ_DIRECTOR_REJECT] candidate_id={cid} start={start} end={end} title={title} viral_score=0 usefulness=0 insight_strength=0 reject_reason=duration_{round(dur,1)}s_not_between_8_and_75")
            continue
            
        m["start"] = round(start, 2)
        m["end"] = round(end, 2)
        m["duration"] = round(dur, 2)
        
        # Parse score
        score = m.get("viral_score")
        if score is None:
            score = 75.0
        try:
            score = float(score)
        except (ValueError, TypeError):
            score = 75.0
            
        # Normalize score
        if score <= 1.0:
            score = score * 100.0
        m["viral_score"] = round(score, 2)
        
        # Extract usefulness and insight_strength
        usefulness = 0.0
        insight_strength = 0.0
        try:
            usefulness = float(m.get("usefulness") or 0)
            if usefulness <= 1.0 and usefulness > 0:
                usefulness *= 100.0
        except (ValueError, TypeError):
            pass
        try:
            insight_strength = float(m.get("insight_strength") or m.get("insight") or 0)
            if insight_strength <= 1.0 and insight_strength > 0:
                insight_strength *= 100.0
        except (ValueError, TypeError):
            pass
            
        m["usefulness"] = round(usefulness, 2)
        m["insight_strength"] = round(insight_strength, 2)
        
        # allow score >= 60 if usefulness >= 75 or insight_strength >= 75
        # Chaos moments always have usefulness=0, insight_strength=0 by design.
        # Use chaos_score as the primary pass signal for ENTERTAINMENT content.
        raw_chaos_score = 0.0
        try:
            raw_chaos_score = float(m.get("chaos_score") or 0)
            if raw_chaos_score <= 1.0 and raw_chaos_score > 0:
                raw_chaos_score *= 100.0
        except (ValueError, TypeError):
            pass
        is_chaos_moment = m.get("is_chaos_moment", False) or raw_chaos_score > 0

        # For chaos moments: exceptional if chaos_score >= 70 (replaces usefulness/insight check)
        if is_chaos_moment:
            is_exceptional = raw_chaos_score >= 70.0
            chaos_min_score = 65.0  # relaxed threshold for chaos/entertainment
            effective_min = chaos_min_score
        else:
            is_exceptional = (usefulness >= 75.0 or insight_strength >= 75.0)
            effective_min = min_score

        # check score against effective thresholds
        if is_exceptional:
            if m["viral_score"] < 60.0:
                log.info(f"[GROQ_DIRECTOR_REJECT] candidate_id={cid} start={start} end={end} title={title} viral_score={m['viral_score']} usefulness={usefulness} insight_strength={insight_strength} reject_reason=score_below_60_for_exceptional")
                continue
        else:
            if m["viral_score"] < effective_min:
                log.info(f"[GROQ_DIRECTOR_REJECT] candidate_id={cid} start={start} end={end} title={title} viral_score={m['viral_score']} usefulness={usefulness} insight_strength={insight_strength} reject_reason=score_below_minimum_{effective_min}")
                continue
                
        # allow incomplete payoff if clip_archetype is curiosity_loop, bold_claim, controversy, question, or prediction
        completeness = 100.0
        try:
            completeness = float(m.get("completeness_score") or m.get("completeness") or 100.0)
            if completeness <= 1.0 and completeness > 0:
                completeness *= 100.0
        except (ValueError, TypeError):
            pass
            
        clip_archetype = str(m.get("clip_archetype") or "").strip().lower()
        # Chaos archetypes: the chaos IS the payoff — never reject for "incomplete"
        chaos_archetypes = {
            "chaotic_digression", "cursed_escalation", "unhinged_banter",
            "absurd_roleplay", "out_of_context_gold", "recurring_bit_payoff",
            "uncontrollable_reaction",
        }
        allowed_incomplete = {"curiosity_loop", "bold_claim", "controversy", "question", "prediction"} | chaos_archetypes
        if completeness < 72.0 and clip_archetype not in allowed_incomplete:
            log.info(f"[GROQ_DIRECTOR_REJECT] candidate_id={cid} start={start} end={end} title={title} viral_score={m['viral_score']} usefulness={usefulness} insight_strength={insight_strength} reject_reason=incomplete_payoff_for_archetype_{clip_archetype}")
            continue

        # do not reject just because context is sparse if hook/usefulness is strong
        text_content = str(m.get("text") or m.get("reason") or m.get("title") or "")
        word_count = len(text_content.split())
        if word_count < 3:
            # For chaos clips: chaos_score >= 70 is the "strong" signal
            # (usefulness=0, insight_strength=0 by design for entertainment)
            is_strong = (
                m["viral_score"] >= 75.0
                or usefulness >= 75.0
                or insight_strength >= 75.0
                or (is_chaos_moment and raw_chaos_score >= 70.0)
            )
            if not is_strong:
                log.info(f"[GROQ_DIRECTOR_REJECT] candidate_id={cid} start={start} end={end} title={title} viral_score={m['viral_score']} usefulness={usefulness} insight_strength={insight_strength} reject_reason=sparse_context_and_weak_scores")
                continue
                
        valid_moments.append(m)
        
    return valid_moments


def _overlap_ratio(a_start, a_end, b_start, b_end):
    try:
        inter_start = max(a_start, b_start)
        inter_end = min(a_end, b_end)
        inter = max(0.0, inter_end - inter_start)
        union_start = min(a_start, b_start)
        union_end = max(a_end, b_end)
        union = max(0.001, union_end - union_start)
        return inter / union
    except Exception:
        return 0.0


def dedupe_moments(moments: list, threshold=0.70) -> list:
    if not moments:
        return []
    sorted_m = sorted(moments, key=lambda x: float(x.get("viral_score", 0)), reverse=True)
    kept = []
    for m in sorted_m:
        m_start = m["start"]
        m_end = m["end"]
        duplicate = False
        for k in kept:
            ratio = _overlap_ratio(m_start, m_end, k["start"], k["end"])
            if ratio > threshold:
                duplicate = True
                break
        if not duplicate:
            kept.append(m)
    return sorted(kept, key=lambda x: x["start"])


def find_moments_from_transcript(transcript_segments: list, video_duration: float, max_clips: int = 8, creator_intent: str = None) -> list:
    if not is_groq_enabled():
        return []

    api_key = _get_groq_api_key()
    if not api_key:
        log.warning("[GROQ_CORTEX] API key missing for transcript-first mode.")
        return []

    if not transcript_segments:
        return []

    try:
        chunk_size = float(os.environ.get("HS_GROQ_TRANSCRIPT_CHUNK_SECONDS", "240"))
        overlap_size = float(os.environ.get("HS_GROQ_TRANSCRIPT_OVERLAP_SECONDS", "30"))
    except ValueError:
        chunk_size = 240.0
        overlap_size = 30.0

    # 1. Chunk transcript into rolling windows
    chunks = _chunk_transcript(transcript_segments, video_duration, window_size=chunk_size, overlap=overlap_size)
    
    # Apply MAX_CHUNKS control
    try:
        max_chunks = int(os.environ.get("HS_GROQ_DIRECTOR_MAX_CHUNKS", "3").strip())
    except ValueError:
        max_chunks = 3
    chunks = chunks[:max_chunks]
    
    log.info(f"[GROQ_TRANSCRIPT_FIRST] enabled=True")
    log.info(f"[GROQ_TRANSCRIPT_FIRST] chunks={len(chunks)}")
    
    all_raw_moments = []
    all_unvalidated_moments = []
    
    # 2. Iterate chunks and query Groq
    import time
    try:
        sleep_ms = int(os.environ.get("HS_GROQ_CHUNK_SLEEP_MS", "800").strip())
    except ValueError:
        sleep_ms = 800

    for idx, chunk in enumerate(chunks):
        if idx > 0 and sleep_ms > 0 and len(GroqKeyPool.get_all_keys()) <= 1:
            time.sleep(sleep_ms / 1000.0)

        groq_input = []
        for s in chunk["segments"]:
            groq_input.append({
                "start": round(float(s.get("start", 0)), 2),
                "end": round(float(s.get("end", 0)), 2),
                "text": str(s.get("text", "")).strip()
            })
            
        prompt_json = json.dumps(groq_input, indent=2)

        # ── Content mode detection ──────────────────────────────────────────────
        # Override via env: HS_CONTENT_MODE=entertainment  (or auto-detected from
        # previous chunk's content_diagnosis.content_genre)
        _env_mode = os.environ.get("HS_CONTENT_MODE", "").strip().lower()
        _is_chaos_mode = (
            _env_mode == "entertainment"
            or any(
                m.get("content_genre", "").upper() == "ENTERTAINMENT"
                for m in all_unvalidated_moments[-5:]  # last 5 from prev chunks
            )
        )

        # Build Director's Lens + Decision Matrix (always appended AFTER Main Brain, never before)
        intent_lens_block = ""
        if creator_intent:
            intent_lens_block = f"""

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 DIRECTOR'S LENS (Creator Applied)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The creator has applied a specific lens to this video: "{creator_intent}"
Your primary goal is to find the intersection of CHAOS/VIRAL ENERGY and this CREATOR'S LENS.

📊 DECISION MATRIX — Follow this priority order strictly:
  PRIORITY 1 — THE JACKPOT: A chaotic/viral moment that also matches the Creator's Lens. Score these HIGHEST.
  PRIORITY 2 — THE BACKUP: A moment with incredible chaos/viral energy that loosely or partially matches the Lens.
  PRIORITY 3 — THE FAILSAFE: If the Creator's Lens topic is completely absent from the transcript, IGNORE the lens entirely and return the most chaotic/viral moments available. NEVER return 0 clips.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

        if _is_chaos_mode:
            system_prompt = """You are HotShort Chaos Director: a world-class short-form editor specialized in streaming, gaming, and variety entertainment content.

Your ONLY job is to find moments that produce "WHAT DID I JUST HEAR?" or "HOW DID THEY GET HERE?" energy.
These are NOT educational clips. They do NOT need to teach anything. They go viral purely because they are bizarre, cursed, chaotic, or absurd.


For each chaos moment, identify:
- start (precise time in seconds, do not cut mid-sentence if avoidable)
- end (precise time in seconds, include the reaction/punchline)
- viral_score (0 to 100 based on "WHAT DID I JUST HEAR?" energy ONLY)
- chaos_score (0 to 100: How bizarre, unhinged, or chaotic is this moment?)
- quotability (0 to 100: Will this exact phrase be quoted, memed, or screenshotted?)
- reaction_energy (0 to 100: How intense is the reaction — laughter, screaming, shock, silence?)
- out_of_context_shock (0 to 100: How insane does this sound WITHOUT surrounding context?)
- escalation_wildness (0 to 100: How unexpected is the escalation from the previous normal conversation?)
- usefulness (always 0 for chaos content — these clips are NOT informational)
- insight_strength (always 0 for chaos content)
- completeness_score (0 to 100 — did we capture the full chaos arc from trigger to peak reaction?)
- completeness_signal ("RESOLVED" if reaction/punchline is captured, "UNRESOLVED_REQUIRES_EXTENSION" if cut early)
- psychology_scores (stop_scrolling, shareability, surprise, memorability)
- title (punchy, quotable title that matches the absurdity — NOT educational)
- opening_caption (the exact shocking/cursed phrase that hooks the viewer)
- clip_archetype (choose EXACTLY ONE from: chaotic_digression, cursed_escalation, unhinged_banter, absurd_roleplay, out_of_context_gold, recurring_bit_payoff, uncontrollable_reaction)
- chaos_type (one of: topic_derailment, nickname_investigation, bizarre_accusation, fake_roleplay, uncontrollable_laughter, cursed_banter, impossible_escalation, out_of_context_statement)
- hook_line (the exact line that signals the start of the chaos)
- payoff (the peak cursed moment or reaction — this IS the payoff even if it teaches nothing)
- why_viral (why this makes someone say "WHAT DID I JUST HEAR?" — be specific)
- b_roll_keywords (2-3 visual keywords, can be absurd/funny)
- editing_notes (pacing_note: fast/medium/slow, subtitle_style: beast|neon|retro|classic|minimal, face_priority: center)

CHAOS MOMENT VALIDITY RULES:
- **Duration: 15 to 60 seconds.** Chaos moments can be shorter than educational clips.
- **MINIMUM 12 seconds.** Never return fragments under 12 seconds.
- Start at the moment the conversation begins derailing, NOT before.
- End MUST include the peak reaction (laughter, screaming, the cursed punchline, the shocked silence).
- A moment is valid if it makes you say "WHAT DID I JUST HEAR?" — it does NOT need a lesson or payoff in the informational sense.
- The chaos IS the payoff.
- Reject generic gaming commentary. Reject normal conversation. Only flag GENUINE chaos.

SCORING SCALE FOR CHAOS:
- 85-100: Clip that people will repost saying "I cannot explain this out of context" — viral gold.
- 70-84: Strong chaos moment, quotable, will stop scroll.
- 60-69: Decent chaos, might work as a short.
- Below 60: Generic or too mild — reject.

CHAOS ARCHETYPES (you MUST pick exactly one):
- chaotic_digression: Normal conversation suddenly derails into something completely unrelated and bizarre.
- cursed_escalation: Harmless comment → increasingly unhinged chain reaction.
- unhinged_banter: Roasting, absurd accusations, outrageous jokes between people.
- absurd_roleplay: People start roleplaying bizarre scenarios (dictator, fake identities, surreal hypotheticals).
- out_of_context_gold: A statement that sounds completely insane without surrounding context.
- recurring_bit_payoff: A strange nickname/rumor/theory returns and peaks in absurdity.
- uncontrollable_reaction: Someone completely loses composure — wheezing, screaming, crying from laughter, unable to speak.

Return 0 to N moments. Never force moments. If none are genuinely chaotic, return 0.

OUTPUT JSON ONLY. No markdown. No explanation outside JSON.

Return this exact structure:
{
  "content_diagnosis": {
    "content_mode": "streaming | gaming | variety | podcast",
    "content_genre": "ENTERTAINMENT",
    "overall_clip_density": "low | medium | high",
    "estimated_valuable_clip_count": 0
  },
  "moments": [
    {
      "start": 12.3,
      "end": 45.6,
      "viral_score": 88,
      "chaos_score": 91,
      "quotability": 87,
      "reaction_energy": 85,
      "out_of_context_shock": 93,
      "escalation_wildness": 82,
      "usefulness": 0,
      "insight_strength": 0,
      "completeness_score": 85,
      "completeness_signal": "RESOLVED",
      "psychology_scores": {
        "stop_scrolling": 92,
        "shareability": 89,
        "surprise": 95,
        "memorability": 88
      },
      "clip_archetype": "cursed_escalation",
      "chaos_type": "impossible_escalation",
      "title": "...",
      "opening_caption": "...",
      "reason": "...",
      "hook_line": "...",
      "payoff": "...",
      "why_viral": "...",
      "b_roll_keywords": ["chaos", "reaction", "gaming"],
      "editing_notes": {
        "pacing_note": "fast",
        "subtitle_style": "beast",
        "face_priority": "center"
      }
    }
  ],
  "rejected_moments": []
}

Now review these transcript segments:
{{TRANSCRIPT_JSON}}
""".replace("{{TRANSCRIPT_JSON}}", prompt_json) + intent_lens_block
            log.info(f"[GROQ_DIRECTOR] window {idx}: using ENTERTAINMENT_CHAOS prompt mode")

        else:
            # ── STANDARD EDUCATIONAL / PROFESSIONAL MODE ────────────────────────
            system_prompt = """You are HotShort Moment Director — a world-class short-form content editor who thinks like Alex Hormozi's offer team, Iman Gadzhi's retention engineers, and a MrBeast editor combined.

You don't think like an academic. You think like a CREATOR. You know the exact moments that stop the scroll, create an open loop in the brain, and make someone send a clip to a friend saying "bro you NEED to see this."

Your job: read transcript segments and find the most powerful standalone short-form moments.

For each moment, identify:
- start (precise start time in seconds — begin at the HOOK, not before)
- end (precise end time in seconds — end at the PAYOFF, never cut it early)
- viral_score (0 to 100 — the SCROLL STOP TEST: would you stop mid-swipe for this?)
- hook_strength (0 to 100 — how powerful is the opening line as a SHORT-FORM HOOK specifically?)
- identity_challenge (0 to 100 — does this make the viewer question their current identity or choices?)
- promise_clarity (0 to 100 — how clear and specific is the value promise?)
- usefulness (0 to 100 — how actionable is this for the average viewer?)
- insight_strength (0 to 100 — how counterintuitive or genuinely surprising is this?)
- completeness_score (0 to 100 — does the clip have both a HOOK and a PAYOFF?)
- completeness_signal ("RESOLVED" or "UNRESOLVED_REQUIRES_EXTENSION")
- psychology_scores:
    - stop_scrolling (would you stop mid-swipe?)
    - curiosity_gap (does the hook create an open loop the brain must close?)
    - shareability (would someone forward this to a friend?)
    - memorability (will this be in their head tomorrow?)
    - identity_pressure (does this make the viewer feel like they're missing out or doing it wrong?)
- title (short, punchy, scroll-stopping — think Hormozi tweet, not academic title)
- opening_caption (the EXACT hook line — the first words a new viewer hears. This must be a scroll-stopper.)
- clip_archetype (choose from: pattern_interrupt, curiosity_gap_hook, bold_promise, social_proof_contrast, identity_challenge, before_after_moment, practical_insight, contrarian_take, mistake_reveal, warning, framework, case_study, emotional_truth, tactical_steps, story_payoff)
- hook_line (the opening line that stops the scroll)
- build (what context/proof comes next)
- payoff (the resolution — the "a-ha" moment or the concrete takeaway)
- why_people_STOP_scrolling (the psychological trigger that halts the scroll — be specific: "Creates belief conflict because...", "Identity challenge because viewer who does X will feel called out...")
- why_people_KEEP_watching (the open loop or curiosity gap that keeps them locked in)
- b_roll_keywords (2-3 visual keywords for stock footage)
- editing_notes (pacing_note: fast/medium/slow, subtitle_style: classic|neon|beast|retro|minimal, face_priority: center)

CLIP ARCHETYPES (pick the best fit):
- pattern_interrupt: "If you're [X] and you're not doing [Y], you're leaving [Z] on the table" — Hormozi identity-interrupt
- curiosity_gap_hook: Names the thing, withholds the HOW — brain MUST stay to resolve it (Gadzhi formula)
- bold_promise: Specific number + timeline + "without X" — "I went from 0 to $1M in 90 days without funding"
- social_proof_contrast: Rich/poor, winner/loser contrast — "Every successful person does THIS. Most people do THAT."
- identity_challenge: Directly challenges viewer's current self-concept
- before_after_moment: The inflection point where everything changed — "everything was different after this"
- practical_insight: Actionable, concrete, specific — changes what viewer does tomorrow
- contrarian_take: The unpopular opinion that is actually correct — creates cognitive dissonance
- mistake_reveal: Viewer realizes they are doing something wrong RIGHT NOW
- warning: Stakes-driven urgency — "if you keep doing X, you will lose Y"
- framework: A named system or mental model the viewer can immediately apply
- case_study: A specific story with a concrete outcome and lesson
- emotional_truth: A deeply felt observation that creates "I felt that" connection
- tactical_steps: Step-by-step actionable sequence
- story_payoff: The emotional or insight resolution of a narrative

MOMENT VALIDITY RULES:
- **Duration: 25 to 60 seconds.** Short-form can be longer if the value is there.
- **NEVER return a moment shorter than 20 seconds.**
- The HOOK must be in the first 3 seconds of the clip.
- The PAYOFF must be included — never cut before the "a-ha" moment.
- Reject a clip if it has a great hook but no payoff. Reject if it has payoff but no hook.
- One complete IDEA per clip — not a summary, not a list. ONE thing.

SCORING SCALE (THE HORMOZI TEST):
- 88-100: Viral gold. Would stop me mid-scroll. Would make me send it to 3 friends. (Less than 5% of content)
- 75-87: Very strong. Scroll-stopping hook, clear payoff, genuinely valuable. Post this.
- 65-74: Decent clip. Interesting but not urgent. Missing either a sharp hook or a strong payoff.
- Below 65: Generic. Skip.

Return 0 to N moments. NEVER force moments. If nothing passes the Hormozi test, return 0.
OUTPUT JSON ONLY. No markdown. No text outside JSON.

Return this exact structure:
{
  "content_diagnosis": {
    "content_mode": "founder/startup | educational | podcast | self-improvement | mixed",
    "content_genre": "ENTERTAINMENT | EDUCATION | PROFESSIONAL",
    "overall_clip_density": "low | medium | high",
    "estimated_valuable_clip_count": 0,
    "hook_quality": "weak | moderate | strong | exceptional",
    "creator_archetype": "hormozi | gadzhi | mrbeast | generic"
  },
  "moments": [
    {
      "start": 12.3,
      "end": 45.6,
      "viral_score": 88,
      "hook_strength": 91,
      "identity_challenge": 85,
      "promise_clarity": 87,
      "usefulness": 84,
      "insight_strength": 82,
      "completeness_score": 90,
      "completeness_signal": "RESOLVED",
      "psychology_scores": {
        "stop_scrolling": 92,
        "curiosity_gap": 88,
        "shareability": 85,
        "memorability": 89,
        "identity_pressure": 84
      },
      "clip_archetype": "pattern_interrupt",
      "title": "...",
      "opening_caption": "...",
      "hook_line": "...",
      "build": "...",
      "payoff": "...",
      "why_people_STOP_scrolling": "...",
      "why_people_KEEP_watching": "...",
      "reason": "...",
      "b_roll_keywords": ["startup", "money", "chart"],
      "editing_notes": {
        "pacing_note": "fast",
        "subtitle_style": "beast",
        "face_priority": "center"
      }
    }
  ],
  "rejected_moments": []
}

Now review these transcript segments:
{{TRANSCRIPT_JSON}}
""".replace("{{TRANSCRIPT_JSON}}", prompt_json) + intent_lens_block

        if creator_intent:
            log.info(f"\n[AI_ENGINE] 🎯 INJECTING DIRECTOR'S LENS: '{creator_intent}'")
            log.info(f"[AI_ENGINE] 🧠 Prompt Structure: Main Brain + Decision Matrix Failsafe Active\n")
        response = None
        try:
            response = post_groq_completions(
                payload={
                    "model": _get_groq_model(),
                    "temperature": 0.2,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {
                            "role": "user",
                            "content": system_prompt
                        }
                    ]
                },
                timeout=_get_timeout(),
                max_retries=3
            )
            response.raise_for_status()
        except Exception as e:
            log.error(f"[GROQ_DIRECTOR] window {idx} failed: {e}")
            continue

        if response is None or response.status_code != 200:
            continue

        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            parsed = parse_groq_json_safely(content)
            
            if parsed and "moments" in parsed:
                chunk_moments = parsed["moments"]
                if not isinstance(chunk_moments, list):
                    chunk_moments = []

                # Extract content_genre and propagate to moments
                diagnosis = parsed.get("content_diagnosis", {})
                genre = diagnosis.get("content_genre", "ENTERTAINMENT")
                is_chaos_chunk = genre.upper() == "ENTERTAINMENT" or _is_chaos_mode
                for m in chunk_moments:
                    if isinstance(m, dict):
                        m["content_genre"] = genre
                        m["is_chaos_moment"] = is_chaos_chunk
                        # ── Chaos Evidence routing (AGENTS.md: no silent signal loss) ──
                        # Chaos scores must propagate through IntelligenceArtifact so they
                        # influence downstream ranking — they cannot be silently dropped.
                        if is_chaos_chunk:
                            from viral_finder.cognition import Evidence, IntelligenceArtifact
                            artifact = m.get("intelligence")
                            if not isinstance(artifact, IntelligenceArtifact):
                                artifact = IntelligenceArtifact()
                                m["intelligence"] = artifact
                            raw_chaos    = float(m.get("chaos_score", 0) or 0)
                            raw_quot     = float(m.get("quotability", 0) or 0)
                            raw_reaction = float(m.get("reaction_energy", 0) or 0)
                            raw_ooc      = float(m.get("out_of_context_shock", 0) or 0)
                            raw_wild     = float(m.get("escalation_wildness", 0) or 0)
                            # Normalise to [0,1]
                            def _n(v): return v / 100.0 if v > 1.0 else v
                            artifact.evidence_stream.extend([
                                Evidence(type="chaos_score",         value=_n(raw_chaos),    producer="groq_chaos_director", confidence=0.90),
                                Evidence(type="quotability",          value=_n(raw_quot),     producer="groq_chaos_director", confidence=0.90),
                                Evidence(type="reaction_energy",      value=_n(raw_reaction), producer="groq_chaos_director", confidence=0.90),
                                Evidence(type="out_of_context_shock", value=_n(raw_ooc),      producer="groq_chaos_director", confidence=0.88),
                                Evidence(type="escalation_wildness",  value=_n(raw_wild),     producer="groq_chaos_director", confidence=0.88),
                                Evidence(type="stop_scroll",          value=_n(float(m.get("psychology_scores", {}).get("stop_scrolling", 0) or 0)), producer="groq_chaos_director", confidence=0.90),
                                Evidence(type="shareability",         value=_n(float(m.get("psychology_scores", {}).get("shareability", 0) or 0)),    producer="groq_chaos_director", confidence=0.90),
                            ])
                            log.info(
                                f"[CHAOS_EVIDENCE] moment={m.get('title','?')[:40]} "
                                f"chaos_score={raw_chaos:.0f} quotability={raw_quot:.0f} "
                                f"reaction_energy={raw_reaction:.0f} ooc_shock={raw_ooc:.0f} "
                                f"escalation={raw_wild:.0f} "
                                f"archetype={m.get('clip_archetype','?')}"
                            )

                # Apply per-chunk limit
                try:
                    max_moments_per_chunk = int(os.environ.get("HS_GROQ_DIRECTOR_MAX_MOMENTS_PER_CHUNK", "5").strip())
                except ValueError:
                    max_moments_per_chunk = 5

                chunk_moments = chunk_moments[:max_moments_per_chunk]

                # Store unvalidated chunk moments for rescue fallback
                all_unvalidated_moments.extend(chunk_moments)

                validated_chunk = validate_groq_moments(chunk_moments, video_duration)
                all_raw_moments.extend(validated_chunk)
                log.info(f"[GROQ_DIRECTOR] window {idx}: found {len(validated_chunk)} valid moments out of {len(chunk_moments)} (chaos_mode={is_chaos_chunk})")
                for m in validated_chunk:
                    cid = m.get("candidate_id") or m.get("id") or "unknown"
                    psy = m.get("psychology_scores", {})
                    if m.get("is_chaos_moment"):
                        log.info(f"   🔥 [CHAOS_HOOK_FOUND] id={cid} chaos={m.get('chaos_score','?')} quot={m.get('quotability','?')} archetype={m.get('clip_archetype','?')} title='{m.get('title','?')}'")
                    else:
                        log.info(f"   ✨ [HOOK_FOUND] id={cid} stop_scrolling={psy.get('stop_scrolling','?')} surprise={psy.get('surprise','?')} share={psy.get('shareability','?')} title='{m.get('title','?')}'")
            else:
                log.info(f"[GROQ_DIRECTOR] window {idx}: no moments returned or failed to parse JSON")
        except Exception as e:
            log.error(f"[GROQ_DIRECTOR] window {idx} parse failed: {e}")
            
    # 5. If Groq Director returns raw moments but validation rejects all, inject top 1-2 raw moments as fallback
    if not all_raw_moments and all_unvalidated_moments:
        log.warning("[GROQ_TRANSCRIPT_FIRST] All moments rejected by validation. Rescuing top 1-2 raw moments.")
        
        def get_score(x):
            try:
                s = float(x.get("viral_score", 0))
                return s * 100.0 if s <= 1.0 else s
            except Exception:
                return 0.0
                
        sorted_unval = sorted(all_unvalidated_moments, key=get_score, reverse=True)
        rescued = []
        for m in sorted_unval:
            if len(rescued) >= 2:
                break
            if not isinstance(m, dict):
                continue
            try:
                start = float(m.get("start", -1))
                end = float(m.get("end", -1))
                dur = end - start
                # Enforce basic sanity duration check for rescue (5s to 90s)
                if start >= 0 and end > start and 5.0 <= dur <= 90.0:
                    m["start"] = round(start, 2)
                    m["end"] = round(end, 2)
                    m["duration"] = round(dur, 2)
                    m["viral_score"] = round(get_score(m), 2)
                    m["reason"] = "groq_director_rescue"
                    m["cortex_enabled"] = True
                    m["groq_moment"] = True
                    m["needs_manual_review"] = True
                    
                    # Extract usefulness and insight
                    try:
                        u = float(m.get("usefulness") or 0)
                        m["usefulness"] = round(u * 100.0 if u <= 1.0 and u > 0 else u, 2)
                    except Exception:
                        m["usefulness"] = 0.0
                    try:
                        i = float(m.get("insight_strength") or m.get("insight") or 0)
                        m["insight_strength"] = round(i * 100.0 if i <= 1.0 and i > 0 else i, 2)
                    except Exception:
                        m["insight_strength"] = 0.0
                        
                    rescued.append(m)
            except Exception:
                pass
        all_raw_moments = rescued

    log.info(f"[GROQ_TRANSCRIPT_FIRST] moments_found={len(all_raw_moments)}")
    
    # 3. Dedupe overlapping moments across different windows
    deduped = dedupe_moments(all_raw_moments, threshold=0.70)
    log.info(f"[GROQ_TRANSCRIPT_FIRST] moments_after_dedupe={len(deduped)}")
    
    try:
        max_clips_limit = int(os.environ.get("HS_GROQ_TRANSCRIPT_MAX_CLIPS", str(max_clips)))
    except ValueError:
        max_clips_limit = max_clips

    return deduped[:max_clips_limit]

def analyze_narrative_roles(transcript_segments: List[Dict]) -> Dict[int, str]:
    """
    Experimental Groq-powered Narrative Intelligence pass.
    Analyzes the entire transcript in batches and assigns one of [HOOK, STORY, PROOF, LESSON, PAYOFF, BUILD]
    to each segment by ID.
    Returns a dictionary mapping segment index to role string.
    """
    if not is_groq_enabled() and os.environ.get("HS_GROQ_NARRATIVE_ROLES") != "1":
        return {}

    api_key = _get_groq_api_key()
    if not api_key:
        return {}

    BATCH_SIZE = 30
    master_roles_map = {}
    
    total_segments = len(transcript_segments)
    batches = [transcript_segments[i:i + BATCH_SIZE] for i in range(0, total_segments, BATCH_SIZE)]
    
    log.info(f"[GROQ_NARRATIVE] Analyzing {total_segments} segments across {len(batches)} batches...")
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    for batch_idx, batch in enumerate(batches):
        # Build input array for this batch
        groq_input = []
        for s in batch:
            # We must use the original index in the full transcript for the ID
            original_idx = transcript_segments.index(s)
            groq_input.append({
                "id": original_idx,
                "text": str(s.get("text", "")).strip()
            })
            
        prompt_json = json.dumps(groq_input, indent=2)
        tokens_est = len(prompt_json) // 4
        
        log.info(f"[GROQ_NARRATIVE] batch={batch_idx+1}/{len(batches)} segments={len(batch)} tokens_est={tokens_est}")
        
        system_prompt = """
You are a world-class Narrative Analyst for short-form video.
Read the following transcript segments and assign EXACTLY ONE narrative role to EACH segment.

Valid roles:
1. HOOK: A question, bold claim, or pattern interrupt that grabs attention.
2. STORY: A personal anecdote, example, or narrative progression.
3. PROOF: Data, evidence, or logical justification for a claim.
4. LESSON: The core teaching, framework, or actionable takeaway.
5. PAYOFF: The final resolution, result, outcome, or consequence. NOT emotion, not hustle, not tension.
6. BUILD: General context or setup that doesn't fit the above.

OUTPUT JSON ONLY.
Return this exact structure:
{
  "segments": [
    {"id": 0, "role": "HOOK"},
    {"id": 1, "role": "STORY"},
    {"id": 2, "role": "BUILD"}
  ]
}

Transcript:
""" + prompt_json
        
        payload = {
            "model": _get_groq_model(),
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "user", "content": system_prompt}
            ]
        }
        
        try:
            response = post_groq_completions(payload=payload, timeout=60, max_retries=4)
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            parsed = parse_groq_json_safely(content)
            num_parsed = len(parsed.get("segments", []))
            
            for seg in parsed.get("segments", []):
                try:
                    sid = int(seg.get("id", -1))
                    role = str(seg.get("role", "BUILD")).upper()
                    if sid >= 0:
                        master_roles_map[sid] = role
                except Exception:
                    pass
            
            log.info("\n[NARRATIVE_TRACE]")
            log.info(f"raw_response_length={len(content)}")
            log.info(f"parsed_roles={num_parsed}")
            log.info(f"master_roles_map_size={len(master_roles_map)}")
            log.info(f"fallback_reason=NONE\n")
            
            batch_success = True
        except Exception as e:
            fallback_reason = str(e)
            log.info("\n[NARRATIVE_TRACE]")
            log.info(f"raw_response_length=FAIL")
            log.info(f"parsed_roles=0")
            log.info(f"master_roles_map_size={len(master_roles_map)}")
            log.info(f"fallback_reason={fallback_reason}\n")
            log.error(f"[GROQ_NARRATIVE] Failed to analyze narrative roles for batch {batch_idx+1}: {e}")
        
        # Add a small delay between batches to avoid immediate 429 (only if single key)
        if batch_idx < len(batches) - 1 and len(GroqKeyPool.get_all_keys()) <= 1:
            import time
            time.sleep(1.5)
            
    log.info(f"[GROQ_NARRATIVE] Successfully mapped {len(master_roles_map)} total narrative roles.")
    return master_roles_map

def repair_rejected_clips_with_groq(rejected_candidates: list, full_transcript: list) -> list:
    """
    Repairs rejected short clips using Groq.
    DISABLED: The primary Surgeon engine now has 'Emergency Instruction' injected into its payload
    and natively extends clips on the first pass. This redundant repair phase only causes 429 Rate Limits.
    """
    return []

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
                "transcript_window": "\n".join(window_text)
            })
            
            batch_meta[str(c["id"])] = c
            
        payload = {
            "model": _get_groq_model(),
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "PROCESS BATCH:\n" + json.dumps(groq_input, indent=2)}
            ]
        }
        
        try:
            log.info(f"[SURGEON_REPAIR] Attempting repair for {len(batch)} clips")
            r = post_groq_completions(payload=payload, timeout=_get_timeout(), max_retries=5)
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
        except Exception as e:
            log.error(f"[SURGEON_REPAIR] Error: {e}")
                
        if batch_idx < len(batches) - 1 and len(GroqKeyPool.get_all_keys()) <= 1:
            time.sleep(2.0)
            
    return repaired_results
