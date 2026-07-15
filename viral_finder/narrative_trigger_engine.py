"""
Rule-based narrative trigger detection (O(n) over transcript segments).
"""

from __future__ import annotations


import os
import json
import logging
import requests
from typing import Dict, List, Any

try:
    from viral_finder.groq_cortex import is_groq_enabled, _get_groq_api_key, _get_groq_model, _get_timeout, parse_groq_json_safely
except ImportError:
    def is_groq_enabled(): return False



# ── English trigger phrases ──────────────────────────────────────────────────
_BELIEF_REVERSAL = (
    "most people think",
    "but actually",
    "but the truth is",
    "in reality",
    "however",
)
_SECRET_REVELATION = (
    "the secret is",
    "what nobody tells you",
    "the real reason",
    "here is the truth",
)
_MISTAKE_EXPLANATION = (
    "the biggest mistake",
    "people get this wrong",
    "everyone does this wrong",
)
_STRONG_CLAIM = (
    "the truth is",
    "the problem is",
    "the reality is",
    "the reason is",
)

# ── Hindi / Hinglish trigger phrases ─────────────────────────────────────────
# Belief Reversal: "log sochte hain", "lekin sach ye hai", "asal mein"
_BELIEF_REVERSAL_HI = (
    "log sochte hain",
    "log mante hain",
    "lekin sach ye hai",
    "lekin asli baat",
    "asal mein",
    "असल में",
    "लेकिन सच ये है",
    "लोग सोचते हैं",
    "हकीकत ये है",
    "par sach ye hai",
    "but sach ye hai",
)
# Secret Revelation: "raaz ye hai", "koi nahi batata"
_SECRET_REVELATION_HI = (
    "raaz ye hai",
    "asli raaz",
    "koi nahi batata",
    "sabse badi baat",
    "ye koi nahi batata",
    "राज़ ये है",
    "असली राज़",
    "कोई नहीं बताता",
    "सबसे बड़ी बात",
    "sach baat ye hai",
)
# Mistake Explanation: "sabse badi galti", "log galat karte hain"
_MISTAKE_EXPLANATION_HI = (
    "sabse badi galti",
    "log galat karte hain",
    "ye galat hai",
    "galat tarika",
    "सबसे बड़ी गलती",
    "लोग गलत करते हैं",
    "ye sab galat kar rahe hain",
    "isko galat samajhte hain",
)
# Strong Claim: "sach ye hai", "problem ye hai"
_STRONG_CLAIM_HI = (
    "sach ye hai",
    "problem ye hai",
    "asli problem",
    "wajah ye hai",
    "matlab ye hai",
    "सच ये है",
    "समस्या ये है",
    "वजह ये है",
    "seedhi baat",
    "simple baat",
)

_PAYOFF = (
    "in conclusion",
    "so basically",
    "the point is",
    "at the end of the day",
    "what this means is",
    "to summarize",
)

_PAYOFF_HI = (
    "iska matlab ye hai",
    "to aakhir mein",
    "kul milakar",
    "baat ye hai ki",
    "iska nateeja",
)

_TRIGGER_MAP = {
    "belief_reversal":    _BELIEF_REVERSAL    + _BELIEF_REVERSAL_HI,
    "secret_revelation":  _SECRET_REVELATION  + _SECRET_REVELATION_HI,
    "mistake_explanation":_MISTAKE_EXPLANATION + _MISTAKE_EXPLANATION_HI,
    "strong_claim":       _STRONG_CLAIM       + _STRONG_CLAIM_HI,
    "payoff":             _PAYOFF             + _PAYOFF_HI,
}

# Contrast markers — English + Hindi Devanagari + Hinglish romanized
_CONTRAST_MARKERS = (
    "but", "however", "instead", "yet", "in reality", "actually",
    "lekin", "parantu", "magar", "par",  # Hinglish
    "लेकिन", "परंतु", "मगर", "पर",       # Devanagari
)
_NEG_WORDS = (
    "not", "never", "wrong", "can't", "dont", "don't", "no",
    "nahi", "galat", "mat",  # Hinglish
    "नहीं", "गलत", "मत",     # Devanagari
)
_POS_WORDS = (
    "best", "right", "works", "truth", "real", "clear",
    "sahi", "sach", "asli",  # Hinglish
    "सही", "सच", "असली",     # Devanagari
)


def _sentiment_proxy_shift(text: str) -> float:
    t = str(text or "").lower()
    pos = sum(1 for w in _POS_WORDS if w in t)
    neg = sum(1 for w in _NEG_WORDS if w in t)
    # normalized polarity shift proxy in [0, 1]
    if pos == 0 and neg == 0:
        return 0.0
    return min(1.0, abs(pos - neg) / float(max(1, pos + neg)))


def _confidence_for_phrase(text_lower: str, phrase: str) -> float:
    score = 0.4  # phrase match
    if any(m in text_lower for m in _CONTRAST_MARKERS):
        score += 0.3
    score += 0.3 * _sentiment_proxy_shift(text_lower)
    return max(0.0, min(1.0, score))



def _run_sliding_window_detection(transcript_segments: List[Dict], log: logging.Logger) -> List[Dict]:
    triggers: List[Dict] = []
    total_phrases_checked = 0
    total_segments = len(transcript_segments or [])
    
    # Pre-compile regexes for flexibility (ignore punctuation/spacing between words)
    import re
    compiled_patterns = {}
    for t_type, phrases in _TRIGGER_MAP.items():
        compiled_patterns[t_type] = []
        for p in phrases:
            # allow optional spaces, commas, or filler words
            regex_str = r'\b' + p.replace(' ', r'(?:\s+|,|\bu\b|\buh\b|\bum\b|\bhi\b)+') + r'\b'
            compiled_patterns[t_type].append((p, re.compile(regex_str, re.IGNORECASE)))

    # Window size of 3 segments (approx 5-10 seconds of speech)
    WINDOW_SIZE = 3
    
    for i in range(total_segments):
        window = transcript_segments[i:i+WINDOW_SIZE]
        if not window:
            continue
            
        combined_text = " ".join(str(s.get("text", "")).strip() for s in window).lower()
        if not combined_text.strip():
            continue
            
        start = float(window[0].get("start", 0.0))
        end = float(window[-1].get("end", start))
        if end <= start:
            continue
            
        for trigger_type, patterns in compiled_patterns.items():
            for original_phrase, pattern in patterns:
                total_phrases_checked += 1
                if pattern.search(combined_text) or original_phrase in combined_text:
                    conf = _confidence_for_phrase(combined_text, original_phrase)
                    
                    # Avoid duplicate overlapping triggers
                    if triggers and triggers[-1]["type"] == trigger_type and abs(triggers[-1]["start"] - start) < 10.0:
                        continue
                        
                    log.info(f"[TRIGGER_FORENSIC_SLIDING] MATCH! Phrase: '{original_phrase}' (Type: {trigger_type}) | Conf: {conf:.2f} | Text: '{combined_text[:60]}...'")
                    triggers.append({
                        "start": start,
                        "end": end,
                        "type": trigger_type,
                        "confidence": round(float(conf), 4),
                        "text": combined_text,
                        "phrase": original_phrase,
                        "span": {"start": start, "end": end},
                    })
                    break
    
    if not triggers:
        log.warning(f"[TRIGGER_FORENSIC_SLIDING] ZERO triggers found. Evaluated {total_phrases_checked} combinations in windows.")
    return triggers

def _run_llm_detection(transcript_segments: List[Dict], log: logging.Logger) -> List[Dict]:
    api_key = _get_groq_api_key()
    if not api_key:
        log.warning("Groq enabled but API key missing. Falling back to sliding window.")
        return _run_sliding_window_detection(transcript_segments, log)

    # Chunk transcript into max 4-minute chunks to avoid massive token limits
    # and provide start/end times clearly.
    chunks = []
    current_chunk = []
    current_duration = 0
    for seg in transcript_segments:
        dur = seg.get("end", 0) - seg.get("start", 0)
        current_chunk.append(seg)
        current_duration += dur
        if current_duration > 240: # 4 mins
            chunks.append(current_chunk)
            current_chunk = []
            current_duration = 0
    if current_chunk:
        chunks.append(current_chunk)

    from viral_finder.cognition import TriggerArtifact
    import uuid

    from viral_finder.cognition import TriggerArtifact
    import uuid
    import time as _time

    # ── SINGLE BATCHED CALL: send full transcript in one request ─────────────────
    # Previously capped at 120 segs — this was leaving 55%+ of the video unseen.
    # Full transcript (~275 segs × ~20 tokens ≈ 5500 tokens) is safely within Groq's
    # 32k token context window. Sending the full transcript gives the LLM full context
    # for more dynamic, diverse trigger discovery across the entire video.
    segs_to_use = transcript_segments  # no cap — send everything

    transcript_text = ""
    for s in segs_to_use:
        transcript_text += f"[{s.get('start', 0):.1f}-{s.get('end', 0):.1f}] {s.get('text', '')}\n"

    log.info(f"[TRIGGER_FORENSIC_LLM] Sending full transcript: {len(segs_to_use)} segs to LLM.")

    prompt = f"""You are an expert AI editor analyzing a video transcript.
Find "Narrative Triggers" in the text. Narrative Triggers include both semantic and structural moments where the speaker:
1. "belief_reversal": Challenges a common belief ("most people think... but actually")
2. "secret_revelation": Reveals a secret ("the real reason is", "nobody tells you this")
3. "mistake_explanation": Explains a mistake ("everyone does this wrong", "biggest mistake")
4. "strong_claim": Makes a strong definitive claim ("the reality is", "the problem is")
5. "payoff": The punchline, reward, or main takeaway ("so basically", "the point is")
6. "complete_thought": A cohesive thought from start to finish that can stand alone.

The transcript is in English, Hindi, or Hinglish.
Identify the exact timestamps where these triggers occur.

CRITICAL INSTRUCTION: For every trigger you find, you MUST also provide deep psychological metrics on a scale of 0.00 to 1.00:
- stop_scroll: How likely is this moment to stop someone from scrolling?
- curiosity: How much does this make the viewer want to keep watching?
- memorability: How memorable is this phrase?
- shareability: How likely is a user to share this?
- novelty: How new or surprising is this information?
- clarity: How clear is the speaker's point?
- belief_reversal: How strongly does this challenge a common belief?
- emotional_charge: How much emotion does this evoke?

CRITICAL INSTRUCTION: You MUST also provide a "reason" (1 short sentence) explaining exactly WHY you selected this trigger and what makes it powerful.

Return ONLY valid JSON in this format:
{{
    "triggers": [
        {{
            "type": "belief_reversal", 
            "start": 12.5, 
            "end": 15.0, 
            "phrase": "the exact phrase from transcript",
            "confidence": 0.0_to_1.0,
            "psychology": {{
                "stop_scroll": 0.0_to_1.0,
                "curiosity": 0.0_to_1.0,
                "memorability": 0.0_to_1.0,
                "shareability": 0.0_to_1.0,
                "novelty": 0.0_to_1.0,
                "clarity": 0.0_to_1.0,
                "belief_reversal": 0.0_to_1.0,
                "emotional_charge": 0.0_to_1.0
            }},
            "reason": "Your specific 1-sentence explanation for why this phrase is a powerful trigger"
        }}
    ]
}}

IMPORTANT: Each trigger MUST have different psychology scores based on the actual content. Do NOT copy-paste scores from one trigger to another.

Transcript:
{transcript_text}
"""

    all_triggers = []
    MAX_RETRIES = 3
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": _get_groq_model(),
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"}
                },
                timeout=_get_timeout()
            )
            if resp.status_code == 200:
                data = parse_groq_json_safely(resp.json()["choices"][0]["message"]["content"])
                raw_triggers = data.get("triggers", [])
                for t in raw_triggers:
                    psy = t.get("psychology", {})
                    log.info(
                        f"[TRIGGER_FORENSIC_LLM] MATCH"
                        f" | type={t.get('type')}"
                        f" | conf={t.get('confidence', 0.0):.2f}"
                        f" | time={t.get('start'):.1f}-{t.get('end'):.1f}s"
                        f" | stop_scroll={psy.get('stop_scroll', 0.0):.2f}"
                        f" curiosity={psy.get('curiosity', 0.0):.2f}"
                        f" memorability={psy.get('memorability', 0.0):.2f}"
                        f" shareability={psy.get('shareability', 0.0):.2f}"
                        f" novelty={psy.get('novelty', 0.0):.2f}"
                        f" clarity={psy.get('clarity', 0.0):.2f}"
                        f" belief_reversal={psy.get('belief_reversal', 0.0):.2f}"
                        f" emotional_charge={psy.get('emotional_charge', 0.0):.2f}"
                        f" | reason='{t.get('reason', '')}'"
                        f" | phrase='{t.get('phrase', '')[:80]}'"
                    )

                    artifact = TriggerArtifact(
                        trigger_type=str(t.get("type", "unknown")),
                        psychology=t.get("psychology", {}),
                        reason=str(t.get("reason", "")),
                        confidence=float(t.get("confidence", 0.8)),
                        trace_id=str(uuid.uuid4())
                    )

                    all_triggers.append({
                        "start": float(t.get("start", 0)),
                        "end": float(t.get("end", 0)),
                        "type": artifact.trigger_type,
                        "confidence": artifact.confidence,
                        "text": str(t.get("phrase", "")),
                        "phrase": str(t.get("phrase", "")),
                        "span": {"start": float(t.get("start", 0)), "end": float(t.get("end", 0))},
                        "artifact": artifact
                    })
                log.info(f"[TRIGGER_FORENSIC_LLM] Batch complete: {len(all_triggers)} triggers found.")
                break  # success — exit retry loop

            elif resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", 2 ** attempt))
                log.warning(f"[TRIGGER_FORENSIC_LLM] 429 rate limit (attempt {attempt+1}/{MAX_RETRIES}). "
                            f"Waiting {retry_after:.1f}s...")
                _time.sleep(retry_after)
            else:
                log.error(f"[TRIGGER_FORENSIC_LLM] Groq API error {resp.status_code}: {resp.text[:200]}")
                break
        except Exception as e:
            log.error(f"[TRIGGER_FORENSIC_LLM] LLM call failed (attempt {attempt+1}): {e}")
            if attempt < MAX_RETRIES - 1:
                _time.sleep(2 ** attempt)

    # Fallback to sliding window if LLM found 0 (it might have failed or hallucinated)
    if not all_triggers:
        log.warning("[TRIGGER_FORENSIC_LLM] LLM returned 0 triggers. Falling back to Sliding Window.")
        return _run_sliding_window_detection(transcript_segments, log)

    return all_triggers



def detect_narrative_triggers(transcript_segments: List[Dict]) -> List[Dict]:
    import logging
    log = logging.getLogger(__name__)
    
    if is_groq_enabled():
        log.info("[TRIGGER_FORENSIC] Using LLM Intelligence Dataset for trigger detection.")
        return _run_llm_detection(transcript_segments, log)
    else:
        log.info("[TRIGGER_FORENSIC] Using Sliding Window exact/regex detection.")
        return _run_sliding_window_detection(transcript_segments, log)


def build_narrative_contracts(triggers: List[Dict]) -> List[Any]:
    """
    Narrative Contract Engine (Priority 1).
    
    Pairs every debt-creating trigger (hook) with the best debt-resolving
    trigger (payoff) within a 10-180s window. Returns NarrativeContract objects.
    
    Trigger classification:
      Debt-creators (HOOKS):  strong_claim, belief_reversal, secret_revelation,
                              mistake_explanation
      Debt-resolvers (PAYOFFS): payoff, complete_thought
      Both roles:             complete_thought (can open AND close)
    
    Pairing algorithm:
      - For each hook, find the highest-scoring payoff trigger within [10s, 180s]
      - A payoff can only resolve ONE hook (greedy: best contract_score wins)
      - Unresolved hooks: contract stored with resolution_score=0.0 → penalized in UVS
    """
    import uuid
    import logging
    log = logging.getLogger(__name__)

    try:
        from viral_finder.cognition import NarrativeContract
    except ImportError:
        log.warning("[NCE] NarrativeContract not importable — skipping contract engine")
        return []

    if not triggers:
        return []

    HOOK_TYPES = {"strong_claim", "belief_reversal", "secret_revelation", "mistake_explanation"}
    PAYOFF_TYPES = {"payoff", "complete_thought"}
    # Maximum gap between hook end and payoff start
    MIN_GAP_S = 5.0
    MAX_GAP_S = 180.0

    # Compute a composite psychology score for a trigger
    def _psych_score(tr: dict) -> float:
        psy = tr.get("psychology", {}) or {}
        conf = float(tr.get("confidence", 0.5))
        stop = float(psy.get("stop_scroll", 0.0))
        cur  = float(psy.get("curiosity", 0.0))
        mem  = float(psy.get("memorability", 0.0))
        sha  = float(psy.get("shareability", 0.0))
        # Weighted average of psychology + base confidence
        raw = (0.30 * stop + 0.30 * cur + 0.25 * mem + 0.15 * sha)
        return max(conf * 0.4 + raw * 0.6, conf * 0.5)

    # Separate into hooks and payoffs
    hooks   = [t for t in triggers if t.get("type") in HOOK_TYPES]
    payoffs = [t for t in triggers if t.get("type") in PAYOFF_TYPES]

    # complete_thought can also act as a hook for the next payoff — keep both
    # Sort by time
    hooks.sort(key=lambda t: float(t.get("start", 0.0)))
    payoffs.sort(key=lambda t: float(t.get("start", 0.0)))

    used_payoffs = set()
    contracts = []

    for hook in hooks:
        h_start = float(hook.get("start", 0.0))
        h_end   = float(hook.get("end", h_start))
        hook_score = _psych_score(hook)

        # Find all candidate payoffs in the valid window
        candidates = []
        for j, p in enumerate(payoffs):
            p_start = float(p.get("start", 0.0))
            p_end   = float(p.get("end", p_start))
            gap = p_start - h_end
            if gap < MIN_GAP_S or gap > MAX_GAP_S:
                continue
            if j in used_payoffs:
                continue
            payoff_score = _psych_score(p)
            # Score this pairing: hook × payoff psychology × proximity bonus
            proximity_bonus = max(0.0, 1.0 - (gap / MAX_GAP_S))  # 1.0 at 0s gap, 0.0 at 180s
            pair_score = hook_score * payoff_score * (0.7 + 0.3 * proximity_bonus)
            candidates.append((pair_score, j, p, payoff_score))

        if candidates:
            # Pick the highest-scoring payoff pairing
            best_pair_score, best_j, best_payoff, best_resolution = max(candidates, key=lambda x: x[0])
            used_payoffs.add(best_j)
            contract = NarrativeContract(
                hook_trigger=hook,
                payoff_trigger=best_payoff,
                hook_start=h_start,
                payoff_end=float(best_payoff.get("end", 0.0)),
                debt_score=round(hook_score, 4),
                resolution_score=round(best_resolution, 4),
                contract_score=round(hook_score * best_resolution, 4),
                hook_type=str(hook.get("type", "unknown")),
                payoff_type=str(best_payoff.get("type", "unknown")),
                trace_id=str(uuid.uuid4()),
            )
            log.info(
                f"[NCE] CONTRACT: {contract.hook_type}@{h_start:.1f}s → "
                f"{contract.payoff_type}@{float(best_payoff.get('start',0)):.1f}s | "
                f"debt={contract.debt_score:.3f} resolution={contract.resolution_score:.3f} "
                f"score={contract.contract_score:.3f}"
            )
        else:
            # Unresolved hook — still a contract, but resolution_score=0
            contract = NarrativeContract(
                hook_trigger=hook,
                payoff_trigger={},
                hook_start=h_start,
                payoff_end=h_end,
                debt_score=round(hook_score, 4),
                resolution_score=0.0,
                contract_score=0.0,
                hook_type=str(hook.get("type", "unknown")),
                payoff_type="none",
                trace_id=str(uuid.uuid4()),
            )
            log.info(
                f"[NCE] UNRESOLVED HOOK: {contract.hook_type}@{h_start:.1f}s "
                f"debt={contract.debt_score:.3f} — no payoff found within {MAX_GAP_S}s"
            )
        contracts.append(contract)

    log.info(f"[NCE] Built {len(contracts)} contracts: "
             f"{sum(1 for c in contracts if c.resolution_score > 0)} resolved, "
             f"{sum(1 for c in contracts if c.resolution_score == 0)} unresolved hooks")
    return contracts

