# ========================================================
# ULTRON BRAIN 1 — TEXT MEANING ENGINE (V32)
# Semantic Scores: hook, insight, share, relatable
# Uses sentence-transformer embeddings (CPU-fast)
# ========================================================

from sentence_transformers import SentenceTransformer
import numpy as np

# Load tiny-fast model ONCE
_text_model = None

def load_text_model():
    global _text_model
    if _text_model is None:
        _text_model = SentenceTransformer("all-MiniLM-L6-v2")
    return _text_model

# --------------------------------------------------------
# UTILITY — normalized sigmoid
# --------------------------------------------------------
def norm_sigmoid(x):
    return float(1 / (1 + np.exp(-x)))

# --------------------------------------------------------
# CORE MEANING ENGINE
# --------------------------------------------------------
def meaning_scores(text: str) -> dict:
    """Return hook, insight, share, relatable scores."""
    if not text or len(text.strip()) == 0:
        return {"hook": 0, "insight": 0, "share": 0, "relatable": 0}

    model = load_text_model()
    embedding = model.encode(text, normalize_embeddings=True)

    # Key feature triggers (cheap heuristics + embedding energy)
    t = text.lower()

    # --- HOOK SCORE ---
    hook_words = [
        "you need to hear this", "listen", "the truth is", 
        "what nobody tells you", "you won't believe", "wait", 
        "stop", "look", "watch this"
    ]
    hook_boost = sum(1 for w in hook_words if w in t)
    hook = norm_sigmoid(hook_boost + np.mean(embedding[:10]) * 5)

    # --- INSIGHT SCORE ---
    insight_words = ["mindset", "success", "truth", "pattern", "system", "framework", "why", "because"]
    insight_boost = sum(1 for w in insight_words if w in t)
    insight = norm_sigmoid(insight_boost + np.mean(embedding) * 4)

    # --- SHARE SCORE ---
    share_words = ["this changed my life", "life changing", "lesson", "you should know"]
    share_boost = sum(1 for w in share_words if w in t)
    share = norm_sigmoid(share_boost + np.std(embedding) * 12)

    # --- RELATABLE SCORE ---
    relatable_words = ["i felt", "we all", "everyone", "you know when", "i used to", "realize"]
    rel_boost = sum(1 for w in relatable_words if w in t)
    relatable = norm_sigmoid(rel_boost + (embedding[0] * 5))

    return {
        "hook": round(hook, 3),
        "insight": round(insight, 3),
        "share": round(share, 3),
        "relatable": round(relatable, 3),
    }

# --------------------------------------------------------
# Batch scoring for all transcript segments
# --------------------------------------------------------
def score_all_segments(segments):
    """Segments = [{'start':.., 'end':.., 'text':..}]"""
    out = []
    for seg in segments:
        m = meaning_scores(seg["text"])
        seg_out = {
            "start": seg["start"],
            "end": seg["end"],
            "text": seg["text"],
            "hook": m["hook"],
            "insight": m["insight"],
            "share": m["share"],
            "relatable": m["relatable"],
        }
        out.append(seg_out)
    return out
