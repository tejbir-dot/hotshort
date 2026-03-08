import os
import json

try:
    import torch
except Exception:
    torch = None

try:
    import numpy as np
except Exception:
    np = None

try:
    from sentence_transformers import SentenceTransformer, util
except Exception:
    SentenceTransformer = None
    util = None

# ==============================
#   ULTRON V33-X BRAIN SYSTEM
#   GPU-AWARE - STABLE - EVOLVING
# ==============================
def get_fallback_brain():
    """
    Lightweight, error-proof brain for tests & CPU-only runs.
    No embeddings, no ML.
    """
    return {
        "pattern_memory": {},
        "semantic_enabled": False,
        "version": "fallback_v1"
    }

ULTRON_BRAIN_PATH = "ultron_brain.json"
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu") if torch is not None else "cpu"

# ---- DYNAMIC DEVICE MODEL ----
embed_model = None
if SentenceTransformer is not None:
    try:
        embed_model = SentenceTransformer(
            "sentence-transformers/all-MiniLM-L6-v2",
            device=DEVICE
        )
    except Exception:
        embed_model = None

# ==============================
# LOAD / SAVE
# ==============================

def load_ultron_brain():
    if not os.path.exists(ULTRON_BRAIN_PATH):
        brain = {
            "meaning_weight": 1.0,
            "novelty_weight": 1.0,
            "emotion_weight": 1.0,
            "clarity_weight": 1.0,
            "pattern_memory": [],
            "learning_rate": 0.03,
            "semantic_enabled": bool(embed_model is not None),
        }
        save_ultron_brain(brain)
        return brain

    with open(ULTRON_BRAIN_PATH, "r") as f:
        brain = json.load(f)
    if "semantic_enabled" not in brain:
        brain["semantic_enabled"] = bool(embed_model is not None)
    return brain

def save_ultron_brain(brain):
    with open(ULTRON_BRAIN_PATH, "w") as f:
        json.dump(brain, f, indent=4)

# ==============================
# CORE BRAIN SCORE
# ==============================

def ultron_brain_score(text: str, brain: dict):
    # --------------------------------------------------
    # SAFETY: brain fallback
    # --------------------------------------------------
    if brain is None:
        brain = get_fallback_brain()

    # Ensure required keys exist (bulletproof)
    brain.setdefault("pattern_memory", [])
    brain.setdefault("meaning_weight", 1.0)
    brain.setdefault("novelty_weight", 1.0)
    brain.setdefault("emotion_weight", 1.0)
    brain.setdefault("clarity_weight", 1.0)
    brain.setdefault("semantic_enabled", bool(embed_model is not None))

    text = (text or "").strip()
    if not text:
        return 0.0, 0.0, 0.0, 0.0, 0.0

    wc = len(text.split())
    t_low = text.lower()

    # --------------------------------------------------
    # FAST HEURISTIC MODE (NO ML / TEST / CI SAFE)
    # --------------------------------------------------
    if not brain["semantic_enabled"]:
        meaning = min(1.0, wc / 18.0)
        novelty = 1.0

        emotion_words = {
            "love","hate","amazing","insane","truth",
            "secret","exposed","crazy","fear","power"
        }
        emotion = min(1.0, sum(w in t_low for w in emotion_words) / 4.0)

        clarity = max(0.2, 1.0 - min(1.0, wc / 35.0))

        impact = (
            meaning +
            novelty +
            emotion +
            clarity
        ) / 4.0

        return (
            round(float(impact), 4),
            round(float(meaning), 4),
            round(float(novelty), 4),
            round(float(emotion), 4),
            round(float(clarity), 4),
        )

    # --------------------------------------------------
    # EMBEDDING MODE (PRODUCTION)
    # --------------------------------------------------
    if embed_model is None or util is None or torch is None:
        brain["semantic_enabled"] = False
        return ultron_brain_score(text, brain)

    try:
        emb = embed_model.encode(
            text,
            convert_to_tensor=True,
            normalize_embeddings=True
        ).to(DEVICE)
    except Exception:
        # hard fallback if model fails
        brain["semantic_enabled"] = False
        return ultron_brain_score(text, brain)

    # --------------------------------------------------
    # NOVELTY (semantic distance from memory)
    # --------------------------------------------------
    memory = brain["pattern_memory"]
    if memory:
        try:
            mem_tensor = torch.tensor(
                memory,
                dtype=torch.float32,
                device=emb.device
            )
            sim = util.cos_sim(emb, mem_tensor).max().item()
            novelty = max(0.0, 1.0 - sim)
        except Exception:
            novelty = 0.5
    else:
        novelty = 1.0

    # --------------------------------------------------
    # MEANING
    # --------------------------------------------------
    meaning = min(1.0, wc / 18.0)

    # --------------------------------------------------
    # EMOTION
    # --------------------------------------------------
    emotion_words = {
        "love","hate","amazing","insane","truth",
        "secret","exposed","crazy","fear","power"
    }
    emotion = min(1.0, sum(w in t_low for w in emotion_words) / 4.0)

    # --------------------------------------------------
    # CLARITY
    # --------------------------------------------------
    clarity = max(0.2, 1.0 - min(1.0, wc / 35.0))

    # --------------------------------------------------
    # IMPACT (weighted but normalized)
    # --------------------------------------------------
    impact = (
        meaning * brain["meaning_weight"] +
        novelty * brain["novelty_weight"] +
        emotion * brain["emotion_weight"] +
        clarity * brain["clarity_weight"]
    ) / (
        brain["meaning_weight"] +
        brain["novelty_weight"] +
        brain["emotion_weight"] +
        brain["clarity_weight"]
    )

    # --------------------------------------------------
    # MEMORY UPDATE (SAFE + BOUNDED)
    # --------------------------------------------------
    try:
        brain["pattern_memory"].append(emb.detach().cpu().tolist())
        if len(brain["pattern_memory"]) > 200:
            brain["pattern_memory"] = brain["pattern_memory"][-200:]
    except Exception:
        pass

    return (
        round(float(impact), 4),
        round(float(meaning), 4),
        round(float(novelty), 4),
        round(float(emotion), 4),
        round(float(clarity), 4),
    )


# ==============================
# LEARNING
# ==============================

def ultron_learn(brain, impact, final_score):
    if brain is None:
        return
    reward = max(0.0, impact * final_score)
    lr = brain.get("learning_rate", 0.03)

    for k in ["meaning_weight","novelty_weight","emotion_weight","clarity_weight"]:
        brain[k] = float(brain.get(k, 1.0)) + lr * (reward - 0.5)
        if np is not None:
            brain[k] = float(np.clip(brain[k], 0.3, 3.0))
        else:
            brain[k] = max(0.3, min(3.0, float(brain[k])))

    save_ultron_brain(brain)
