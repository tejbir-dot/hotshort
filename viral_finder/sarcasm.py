import re
from typing import Tuple

# Simple, fast sarcasm detector (lexical + pattern + audio flatness)
POSITIVE_WORDS = {
    "great","amazing","awesome","perfect","nice","fantastic","love","wonderful","best","brilliant"
}

NEGATION_PATTERNS = [
    r"yeah right",
    r"as if",
    r"totally",
    r"sure.*",
    r"great.*but",
    r"oh sure",
    r"I\s+love\s+how",
]


def detect_sarcasm(text: str, sentiment_score: float = 0.0, audio_flatness: float = 0.0) -> Tuple[bool, float]:
    """Return (is_sarcastic, score) where score in [0..1].

    Heuristic fuse of three signals:
    - positive lexical hit
    - negation / contrastive pattern
    - audio flatness (prosody mismatch)

    Works fast and without external models. Treat missing audio/sentiment as 0.
    """
    if not text:
        return False, 0.0

    t = text.lower()

    # 1) lexical positive hit
    pos_hit = any(w in t for w in POSITIVE_WORDS)

    # 2) explicit negation / contrast patterns
    neg_hit = any(re.search(p, t) for p in NEGATION_PATTERNS)

    # 3) tone mismatch — higher flatness implies monotone speech (0..1 expected)
    try:
        tone_mismatch = float(audio_flatness) > 0.65
    except Exception:
        tone_mismatch = False

    # If we have an explicit sentiment_score (polarity-like), consider positivity
    try:
        positive_sent = float(sentiment_score) > 0.2
    except Exception:
        positive_sent = False

    # Combine signals. Require at least two of three (where positive signal is pos_hit OR positive_sent)
    positive_signal = pos_hit or positive_sent
    matches = [positive_signal, neg_hit, tone_mismatch]
    score = sum(bool(x) for x in matches) / 3.0

    is_sarcastic = score >= 0.66
    return bool(is_sarcastic), float(round(score, 3))
