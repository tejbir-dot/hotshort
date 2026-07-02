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

    all_triggers = []
    for chunk_idx, chunk in enumerate(chunks):
        if not chunk: continue
        
        transcript_text = ""
        for s in chunk:
            transcript_text += f"[{s.get('start', 0):.1f}-{s.get('end', 0):.1f}] {s.get('text', '')}\n"
            
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
Return ONLY valid JSON in this format:
{{
    "triggers": [
        {{"type": "belief_reversal", "start": 12.5, "end": 15.0, "phrase": "lekin sach ye hai ki", "confidence": 0.9}},
        ...
    ]
}}

Transcript:
{transcript_text}
"""
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
                triggers = data.get("triggers", [])
                for t in triggers:
                    log.info(f"[TRIGGER_FORENSIC_LLM] MATCH! Type: {t.get('type')} | Phrase: '{t.get('phrase')}' | Time: {t.get('start')}-{t.get('end')}")
                    all_triggers.append({
                        "start": float(t.get("start", 0)),
                        "end": float(t.get("end", 0)),
                        "type": str(t.get("type", "unknown")),
                        "confidence": float(t.get("confidence", 0.8)),
                        "text": str(t.get("phrase", "")),
                        "phrase": str(t.get("phrase", "")),
                        "span": {"start": float(t.get("start", 0)), "end": float(t.get("end", 0))},
                    })
            else:
                log.error(f"[TRIGGER_FORENSIC_LLM] Groq API error {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            log.error(f"[TRIGGER_FORENSIC_LLM] LLM call failed: {e}")

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
