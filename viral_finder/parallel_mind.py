
"""
parallel_mind.py

Parallel Mind engine for Hotshort / Viral Finder
- Embedding-based semantic matching (sentence-transformers if available; fallback to simple TF-IDF cosine)
- Tiny Torch SER (speech-emotion-recognition) model hook with graceful fallback
- Phrase/lexicon based fast pathway
- Auto-tune routine to choose mind thresholds from labeled data
- Lexicon management helpers (persist/update)

Drop this file into viral_finder/parallel_mind.py and import:
    from viral_finder.parallel_mind import ParallelMind

Public API highlights
- ParallelMind(): construct with optional config
- pm.detect_ignitions_from_segments(segments) -> per-segment ignition scores
- pm.build_angle_arcs(segments, top_k=5) -> ranked arcs/clips
- pm.auto_tune_thresholds(labeled_segments) -> tuned thresholds
- pm.add_lexicon(mind_name, phrases)

Optional dependencies:
- sentence_transformers
- torch, torchaudio, librosa (for SER)
- sklearn (used if available but not required)

This file is defensive: if heavy deps are missing it still runs reasonably fast using phrase matching + simple semantic fallback.
"""

from typing import List, Dict, Any, Tuple, Optional
import os
import json
import math
import time
import logging
import re
from collections import defaultdict, Counter

# Optional ML imports (graceful)
try:
    from sentence_transformers import SentenceTransformer
    SENTE_TRANS_AVAILABLE = True
except Exception:
    SentenceTransformer = None
    SENTE_TRANS_AVAILABLE = False

try:
    import numpy as np
    NP_AVAILABLE = True
except Exception:
    np = None
    NP_AVAILABLE = False

try:
    import torch
    TORCH_AVAILABLE = True
except Exception:
    torch = None
    TORCH_AVAILABLE = False

try:
    import torchaudio
    TORCHAUDIO_AVAILABLE = True
except Exception:
    torchaudio = None
    TORCHAUDIO_AVAILABLE = False

# sklearn helpers for vectorization if available (fallbacks provided)
try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    SKLEARN_AVAILABLE = True
except Exception:
    TfidfVectorizer = None
    cosine_similarity = None
    SKLEARN_AVAILABLE = False

logger = logging.getLogger("parallel_mind")
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

# -----------------------------
# Default lexicons (starter)
# -----------------------------
DEFAULT_LEXICONS = {
    "curiosity": [
        "why", "how", "secret", "truth", "nobody", "never",
        "what if", "the reason", "you won't believe", "guess what"
    ],
    "shock": [
        "lie", "lying", "lied", "wrong", "destroyed", "ruined", "exposed",
        "scam", "fake", "mistake", "failure", "was almost killed", "almost killed"
    ],
    "authority": [
        "i spent", "years", "decade", "experience", "expert", "learned the hard way",
        "professor", "doctor", "i built"
    ],
    "emotion": [
        "scared", "afraid", "insane", "crazy", "love", "hate",
        "panic", "fear", "heartbroken", "tears"
    ],
    "specificity": [
        "$", "%", "exactly", "only", "just", "days", "months", "years"
    ],
    "contradiction": [
        "but", "however", "does not", "is not", "are lying", "everyone is wrong",
        "most people think", "the truth is"
    ],
    "vulnerability": [
        "my career", "my life", "i almost", "this nearly", "cost me", "destroyed my"
    ]
}

# -----------------------------
# Utilities
# -----------------------------

def _norm_text(t: str) -> str:
    t = t.lower().strip()
    t = re.sub(r"[^a-z0-9\s$%,'\.\-]", " ", t)
    t = re.sub(r"\s+", " ", t)
    return t


def _cosine(a, b):
    # small, dependency-free cosine for lists or numpy arrays
    if NP_AVAILABLE:
        a = np.array(a, dtype=float)
        b = np.array(b, dtype=float)
        denom = (np.linalg.norm(a) * np.linalg.norm(b))
        if denom == 0:
            return 0.0
        return float(np.dot(a, b) / denom)
    # fallback: math-based (lists)
    try:
        denom = math.sqrt(sum(x * x for x in a) * sum(y * y for y in b))
        if denom == 0:
            return 0.0
        return sum(x * y for x, y in zip(a, b)) / denom
    except Exception:
        return 0.0

# -----------------------------
# Tiny Torch SER model (OPTIONAL)
# - This is a tiny CNN that expects mel spectrogram input
# - We provide a helper to load weights if available; otherwise a random init placeholder
# -----------------------------

SER_MODEL_DEFAULT_PATH = "./models/ser_tiny.pt"

class TinySER(torch.nn.Module if TORCH_AVAILABLE else object):
    def __init__(self, n_classes=4):
        if not TORCH_AVAILABLE:
            return
        super().__init__()
        self.conv = torch.nn.Sequential(
            torch.nn.Conv2d(1, 8, kernel_size=(3,3), padding=1),
            torch.nn.ReLU(),
            torch.nn.MaxPool2d((2,2)),
            torch.nn.Conv2d(8, 16, kernel_size=(3,3), padding=1),
            torch.nn.ReLU(),
            torch.nn.AdaptiveAvgPool2d((1,1))
        )
        self.fc = torch.nn.Linear(16, n_classes)

    def forward(self, x):
        # x shape: (B, 1, F, T)
        z = self.conv(x)
        z = z.view(z.size(0), -1)
        return self.fc(z)


# -----------------------------
# ParallelMind
# -----------------------------
class ParallelMind:
    def __init__(self,
                 lexicons: Optional[Dict[str, List[str]]] = None,
                 embed_model_name: str = "all-MiniLM-L6-v2",
                 ser_model_path: Optional[str] = None,
                 mind_weights: Optional[Dict[str, float]] = None):
        """
        lexicons: per-mind phrase lists
        embed_model_name: sentence-transformers model name (if available)
        ser_model_path: optional path to torch SER weights
        mind_weights: default importance per mind
        """
        self.lexicons = {k: list(v) for k, v in (lexicons or DEFAULT_LEXICONS).items()}
        self.embed_model_name = embed_model_name
        self.ser_model_path = ser_model_path
        self.mind_weights = mind_weights or {k: 1.0 for k in self.lexicons.keys()}

        # lazy-loaded resources
        self._embed_model = None
        self._tfidf = None
        self._tfidf_matrix = None
        self._ser_model = None

        # build text index for fast phrase matching
        self._compile_phrase_patterns()

        # load tiny SER if possible
        if TORCH_AVAILABLE and ser_model_path:
            try:
                m = TinySER(n_classes=4)
                m.load_state_dict(torch.load(ser_model_path, map_location="cpu"))
                m.eval()
                self._ser_model = m
                logger.info("[ParallelMind] Loaded SER model")
            except Exception as e:
                logger.warning("[ParallelMind] failed to load SER model: %s", e)
                self._ser_model = None

        # prepare embedding model lazily
        if SENTE_TRANS_AVAILABLE:
            try:
                self._embed_model = SentenceTransformer(embed_model_name)
                logger.info("[ParallelMind] SentenceTransformer loaded: %s", embed_model_name)
            except Exception as e:
                logger.warning("[ParallelMind] Failed to load embedding model: %s", e)
                self._embed_model = None

    # ---------- lexicon helpers ----------
    def _compile_phrase_patterns(self):
        self._patterns = {}
        for mind, phrases in self.lexicons.items():
            pats = [re.escape(p.lower()) for p in phrases if p and len(p) > 0]
            if pats:
                self._patterns[mind] = re.compile(r"\b(" + r"|".join(pats) + r")\b")
            else:
                self._patterns[mind] = re.compile(r"$^")

    def add_lexicon(self, mind: str, phrases: List[str]):
        self.lexicons.setdefault(mind, [])
        self.lexicons[mind].extend(phrases)
        # recompile
        self._compile_phrase_patterns()

    def save_lexicons(self, path: str):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.lexicons, f, indent=2, ensure_ascii=False)

    def load_lexicons(self, path: str):
        with open(path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        self.lexicons = loaded
        self._compile_phrase_patterns()

    # ---------- semantic helpers ----------
    def _ensure_tfidf(self, texts: List[str]):
        if not SKLEARN_AVAILABLE:
            return None
        if self._tfidf is None:
            try:
                self._tfidf = TfidfVectorizer().fit(texts)
                self._tfidf_matrix = self._tfidf.transform(texts)
            except Exception as e:
                logger.warning("_ensure_tfidf failed: %s", e)
                self._tfidf = None
                self._tfidf_matrix = None
        return self._tfidf, self._tfidf_matrix

    def embed_texts(self, texts: List[str]):
        texts = [t if isinstance(t, str) else str(t) for t in texts]
        if self._embed_model:
            return self._embed_model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
        # fallback: weak tfidf vector
        if SKLEARN_AVAILABLE:
            vec, mat = self._ensure_tfidf(texts)
            if vec is not None:
                return mat.toarray()
        # final fallback: char-level hashing vector
        out = []
        for t in texts:
            v = [0] * 128
            for ch in t:
                idx = ord(ch) % 128
                v[idx] += 1
            out.append(v)
        return out

    def semantic_match(self, query: str, candidates: List[str], top_k: int = 5) -> List[Tuple[int, float]]:
        """Return top_k candidate indexes with similarity scores"""
        cand_norm = [_norm_text(c) for c in candidates]
        q_norm = _norm_text(query)
        # embed
        emb = self.embed_texts([q_norm] + cand_norm)
        qv = emb[0]
        cvs = emb[1:]
        scores = [float(_cosine(qv, cv)) for cv in cvs]
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        return ranked[:top_k]

    # ---------- SER helpers (optional) ----------
    def ser_predict(self, audio_path: str) -> Optional[Dict[str, float]]:
        """
        If torchaudio + torch available and ser model loaded, returns a dict of emotion probabilities.
        Otherwise returns None.
        """
        if not (TORCHAUDIO_AVAILABLE and TORCH_AVAILABLE and self._ser_model):
            return None
        try:
            waveform, sr = torchaudio.load(audio_path)
            # convert to mono
            if waveform.size(0) > 1:
                waveform = waveform.mean(dim=0, keepdim=True)
            # resample if needed
            if sr != 16000:
                resampler = torchaudio.transforms.Resample(sr, 16000)
                waveform = resampler(waveform)
            # mel
            mel = torchaudio.transforms.MelSpectrogram(16000, n_mels=64)(waveform)
            # normalize and add batch/channel dims
            x = (mel - mel.mean()) / (mel.std() + 1e-8)
            x = x.unsqueeze(0)  # B, C, F, T
            with torch.no_grad():
                logits = self._ser_model(x)
                probs = torch.softmax(logits, dim=-1).squeeze(0).cpu().tolist()
            # name the classes generically
            labels = ["neutral", "happy", "sad", "angry"]
            return {labels[i]: probs[i] for i in range(min(len(labels), len(probs)))}
        except Exception as e:
            logger.warning("ser_predict failed: %s", e)
            return None

    # ---------- ignition detection ----------
    def detect_ignitions_from_segments(self, segments: List[Dict[str, Any]],
                                       use_semantic: bool = True,
                                       ser_on: bool = False) -> List[Dict[str, Any]]:
        """
        segments: list of {"start", "end", "text"[, "audio_path"]}
        returns list of same length with added 'mind_scores' dict and 'ignition_score'
        """
        texts = [s.get("text", "") for s in segments]
        normalized = [_norm_text(t) for t in texts]

        # precompute embeddings for segments if semantic enabled
        embeddings = None
        if use_semantic:
            embeddings = self.embed_texts(normalized)

        results = []
        for i, seg in enumerate(segments):
            t = normalized[i]
            mind_scores = {}

            # 1) phrase matching fast path
            for mind, pat in self._patterns.items():
                found = 1.0 if pat.search(t) else 0.0
                mind_scores[mind] = float(found) * self.mind_weights.get(mind, 1.0)

            # 2) semantic matching boost (if embedding model available)
            if use_semantic and embeddings is not None:
                # compare seg embedding to each lexicon phrase embedding average
                for mind, phrases in self.lexicons.items():
                    if not phrases:
                        continue
                    # compute average embedding for lexicon (cache could be added)
                    ph_embs = self.embed_texts([_norm_text(p) for p in phrases])
                    avg = None
                    if NP_AVAILABLE:
                        avg = np.mean(ph_embs, axis=0)
                        score = float(_cosine(embeddings[i], avg))
                    else:
                        # simple fallback: compare to first phrase
                        score = float(_cosine(embeddings[i], ph_embs[0]))
                    # blend: keep max of phrase match and semantic score
                    mind_scores[mind] = max(mind_scores.get(mind, 0.0), score * self.mind_weights.get(mind, 1.0))

            # 3) SER-based adjustments
            if ser_on and seg.get("audio_path"):
                ser = self.ser_predict(seg.get("audio_path"))
                if ser:
                    # map ser emotions to minds roughly
                    mind_scores["emotion"] = max(mind_scores.get("emotion", 0.0), ser.get("angry", 0.0))
                    mind_scores["vulnerability"] = max(mind_scores.get("vulnerability", 0.0), ser.get("sad", 0.0))

            # final ignition score: weighted sum normalized
            total_weight = sum(self.mind_weights.get(m, 1.0) for m in mind_scores.keys()) or 1.0
            ignition = sum(v for v in mind_scores.values()) / total_weight

            results.append({**seg, "mind_scores": mind_scores, "ignition_score": ignition})

        return results

    # ---------- build arcs / clip proposals ----------
    def build_angle_arcs(self, segments: List[Dict[str, Any]], top_k: int = 6) -> List[Dict[str, Any]]:
        """Aggregate adjacent high-ignition segments into arcs and rank by ignition intensity"""
        detected = self.detect_ignitions_from_segments(segments)
        # group contiguous segments with ignition_score > threshold (0.2 default)
        arcs = []
        cur = None
        for s in detected:
            score = s.get("ignition_score", 0.0)
            if score > 0.22:
                if cur is None:
                    cur = {"start": s["start"], "end": s["end"], "score": score, "segments": [s]}
                else:
                    cur["end"] = s["end"]
                    cur["score"] = max(cur["score"], score)
                    cur["segments"].append(s)
            else:
                if cur is not None:
                    arcs.append(cur)
                    cur = None
        if cur is not None:
            arcs.append(cur)

        # rank by score * duration heuristic
        for a in arcs:
            dur = max(0.001, a["end"] - a["start"])
            a["rank"] = a["score"] * math.log1p(dur)

        arcs.sort(key=lambda x: x["rank"], reverse=True)
        return arcs[:top_k]

    # ---------- auto-tune thresholds ----------
    def auto_tune_thresholds(self, labeled_segments: List[Dict[str, Any]], mind_name: str = None,
                             metric: str = "f1") -> Dict[str, float]:
        """
        Auto-tunes thresholds for minds using a labeled dataset.
        labeled_segments: list of {"text","label_minds": {mind:bool}, optional "audio_path"}
        If mind_name provided, tune that specific mind; else tune all minds independently.

        Returns dict mind -> best_threshold (0..1)
        """
        # build detection scores for each labeled seg
        res = self.detect_ignitions_from_segments([{"start": 0.0, "end": 0.0, "text": s["text"], "audio_path": s.get("audio_path")} for s in labeled_segments], use_semantic=True, ser_on=True)
        thresholds = {}

        def score_binary(preds, truths):
            # compute precision/recall/f1
            tp = sum(1 for p, t in zip(preds, truths) if p and t)
            fp = sum(1 for p, t in zip(preds, truths) if p and not t)
            fn = sum(1 for p, t in zip(preds, truths) if not p and t)
            prec = tp / (tp + fp) if (tp + fp) else 0.0
            rec = tp / (tp + fn) if (tp + fn) else 0.0
            f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
            return {"prec": prec, "rec": rec, "f1": f1}

        minds = [mind_name] if mind_name else list(self.lexicons.keys())
        for mind in minds:
            scores = [r["mind_scores"].get(mind, 0.0) for r in res]
            truths = [bool(s.get("label_minds", {}).get(mind, False)) for s in labeled_segments]
            best = (0.0, 0.0)
            # grid search thresholds
            for t in [i / 100.0 for i in range(0, 101, 2)]:
                preds = [sv >= t for sv in scores]
                sc = score_binary(preds, truths)[metric]
                if sc > best[1]:
                    best = (t, sc)
            thresholds[mind] = best[0]
        return thresholds


if __name__ == "__main__":
    # smoke demo
    pm = ParallelMind()
    segs = [
        {"start": 0.0, "end": 3.4, "text": "I spent years building this and you won't believe what happened"},
        {"start": 3.5, "end": 7.2, "text": "they were lying to us, the whole system was a scam"},
        {"start": 7.3, "end": 12.0, "text": "and that's why everything changed"}
    ]
    arcs = pm.build_angle_arcs(segs)
    print("Arcs:")
    for a in arcs:
        print(a)
