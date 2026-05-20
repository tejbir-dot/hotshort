"""
Rule-based narrative trigger detection (O(n) over transcript segments).
"""

from __future__ import annotations

from typing import Dict, List


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

_TRIGGER_MAP = {
    "belief_reversal":    _BELIEF_REVERSAL    + _BELIEF_REVERSAL_HI,
    "secret_revelation":  _SECRET_REVELATION  + _SECRET_REVELATION_HI,
    "mistake_explanation":_MISTAKE_EXPLANATION + _MISTAKE_EXPLANATION_HI,
    "strong_claim":       _STRONG_CLAIM       + _STRONG_CLAIM_HI,
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


def detect_narrative_triggers(transcript_segments: List[Dict]) -> List[Dict]:
    triggers: List[Dict] = []
    for seg in transcript_segments or []:
        text = str(seg.get("text", "") or "")
        if not text.strip():
            continue
        t = text.lower()
        start = float(seg.get("start", 0.0) or 0.0)
        end = float(seg.get("end", start) or start)
        if end <= start:
            continue
        for trigger_type, patterns in _TRIGGER_MAP.items():
            for phrase in patterns:
                if phrase in t:
                    conf = _confidence_for_phrase(t, phrase)
                    triggers.append(
                        {
                            "start": start,
                            "end": end,
                            "type": trigger_type,
                            "confidence": round(float(conf), 4),
                            "text": text,
                            "phrase": phrase,
                            "span": {"start": start, "end": end},
                        }
                    )
                    break
    return triggers

