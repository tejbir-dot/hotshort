from typing import Dict, List
import re

# --------------------------------
# KNOWLEDGE GRAPH (EDITING BRAIN)
# --------------------------------
BROLL_RULES = [
    {
        "name": "finance",
        "keywords": [
            "bitcoin", "btc", "crypto", "money", "million", "billion",
            "stocks", "invest", "investment", "trading", "profit"
        ],
        "overlay": "finance_chart",
        "effect": "zoom_fast",
        "tone": "neutral",
        "weight": 1.2
    },
    {
        "name": "fear",
        "keywords": [
            "fear", "danger", "dying", "kill", "risk", "crash", "down bad",
            "loss", "failure"
        ],
        "overlay": None,
        "effect": "shake",
        "tone": "dark",
        "weight": 1.4
    },
    {
        "name": "education",
        "keywords": [
            "college", "school", "student", "campus", "degree", "dropout"
        ],
        "overlay": "campus",
        "effect": "cut_flash",
        "tone": "bright",
        "weight": 1.0
    },
    {
        "name": "ai_future",
        "keywords": [
            "ai", "artificial intelligence", "agents",
            "automation", "future", "robots"
        ],
        "overlay": "matrix",
        "effect": "pulse",
        "tone": "neon",
        "weight": 1.3
    },
    {
        "name": "hype",
        "keywords": [
            "insane", "crazy", "unbelievable",
            "shocking", "truth", "real"
        ],
        "overlay": None,
        "effect": "zoom_fast",
        "tone": None,
        "weight": 1.1
    }
]

# --------------------------------
# GENIUS BROLL DETECTOR
# --------------------------------
def detect_broll(text: str) -> Dict:
    """
    Converts text → cinematic intent

    OUTPUT:
    {
        "overlays": [...],
        "effects": [...],
        "tone": "dark",
        "confidence": 0.0–1.0
    }
    """

    t = text.lower()
    t = re.sub(r"[^a-z0-9\s]", "", t)

    overlays = set()
    effects = set()
    tones = []
    score = 0.0
    hits = 0

    for rule in BROLL_RULES:
        matched = any(k in t for k in rule["keywords"])
        if not matched:
            continue

        hits += 1
        score += rule["weight"]

        if rule["overlay"]:
            overlays.add(rule["overlay"])

        if rule["effect"]:
            effects.add(rule["effect"])

        if rule["tone"]:
            tones.append(rule["tone"])

    confidence = min(1.0, score / 3.0)

    # Resolve dominant tone
    tone = max(set(tones), key=tones.count) if tones else None

    return {
        "overlays": list(overlays),
        "effects": list(effects),
        "tone": tone,
        "confidence": round(confidence, 2)
    }
