# ============================================================
#                  ULTRON V31 — MEANING BRAIN
#      Universal Virality Intelligence (Adaptive Length)
# ============================================================

import numpy as np
import torch
from transformers import AutoTokenizer, AutoModel

TEXT_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
_text_model = None
_text_tokenizer = None

# -------------------------
# LOAD MODEL (Lazy load)
# -------------------------
def load_text_brain():
    global _text_model, _text_tokenizer

    if _text_model is None:
        print("[ULTRON] Loading Meaning Brain (MiniLM)…")
        _text_tokenizer = AutoTokenizer.from_pretrained(TEXT_MODEL_NAME)
        _text_model = AutoModel.from_pretrained(TEXT_MODEL_NAME)
        _text_model.eval()

    return _text_model, _text_tokenizer


# -------------------------
# UTILITY: compute embedding
# -------------------------
def embed_text(text):
    model, tok = load_text_brain()

    enc = tok(text, return_tensors="pt", padding=True, truncation=True)

    with torch.no_grad():
        out = model(**enc).last_hidden_state.mean(dim=1)[0]

    return out.numpy()


# -------------------------
# ULTRON SEMANTIC SCORING
# -------------------------
def meaning_brain_score(text, prev_text=None):
    """
    Returns:
        meaning_score: 0..1 (semantic richness)
        novelty_score: 0..1 (difference from previous line)
        emotion_score: 0..1 (trigger words)
        clarity_score: 0..1 (signal/noise)
        impact_score: 0..1 (final combined measurement)
    """

    if not text:
        return {
            "meaning": 0.0,
            "novelty": 0.0,
            "emotion": 0.0,
            "clarity": 0.0,
            "impact": 0.0
        }

    # -------------------------------------------------------
    # 1. Meaning Density (semantic richness)
    # -------------------------------------------------------
    emb = embed_text(text)
    meaning_score = float(np.linalg.norm(emb) / 30.0)
    meaning_score = np.clip(meaning_score, 0.0, 1.0)

    # -------------------------------------------------------
    # 2. Novelty (difference from previous text)
    # -------------------------------------------------------
    if prev_text:
        prev_emb = embed_text(prev_text)
        dot = np.dot(emb, prev_emb)
        denom = np.linalg.norm(emb) * np.linalg.norm(prev_emb)
        sim = (dot / denom) if denom > 0 else 0

        novelty_score = 1.0 - sim  # more different → more viral
        novelty_score = float(np.clip(novelty_score, 0.0, 1.0))
    else:
        novelty_score = 0.5  # neutral if no context available

    # -------------------------------------------------------
    # 3. Emotion Score (word-level)
    # -------------------------------------------------------
    emotional_words = [
        "love", "hate", "fear", "insane", "crazy", "amazing", "shocking",
        "truth", "secret", "danger", "risk", "fail", "win", "genius",
        "powerful", "unbelievable", "life-changing"
    ]

    lw = text.lower()
    emo_hits = sum(w in lw for w in emotional_words)
    emotion_score = np.clip(emo_hits / 4.0, 0.0, 1.0)

    # -------------------------------------------------------
    # 4. Clarity Score (low filler words)
    # -------------------------------------------------------
    fillers = ["uh", "um", "like", "you know", "basically", "literally"]
    filler_hits = sum(w in lw for w in fillers)

    clarity_score = 1.0 - np.clip(filler_hits / 5.0, 0.0, 1.0)

    # -------------------------------------------------------
    # 5. IMPACT SCORE (ULTRON fusion)
    # Adaptive weighting for universal virality
    # -------------------------------------------------------

    impact = (
        meaning_score * 0.40 +
        novelty_score * 0.25 +
        emotion_score * 0.20 +
        clarity_score * 0.15
    )

    impact = float(np.clip(impact, 0.0, 1.0))

    return {
        "meaning": meaning_score,
        "novelty": novelty_score,
        "emotion": emotion_score,
        "clarity": clarity_score,
        "impact": impact
    }
