# emotional_surge.py
import math

EMO_WORDS = [
    "crazy","insane","secret","truth","power","fear",
    "love","hate","money","billion","viral","growth",
    "danger","proof","science","exposed","win","lose"
]

def emotional_surge(text: str) -> float:
    """
    Scores emotional momentum
    Range: 0.0 - 1.0
    """
    t = text.lower()
    hits = sum(w in t for w in EMO_WORDS)
    words = max(1, len(t.split()))

    density = hits / words
    density = min(1.0, density * 8)

    # long sentences show momentum
    long_bonus = min(0.4, len(text) / 120)

    return round(min(1.0, density + long_bonus), 4)
