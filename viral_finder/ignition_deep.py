"""
ignition_deep.py

Dangerous Builder Mode: Robust Ignition Detector (v2)
- Hybrid semantic + optional SER (PyTorch/HuggingFace) pathway
- Fast, safe fallbacks (word-list first-phase) when heavy deps are missing
- No blocking temp-file churn in the hot path (but graceful fallback exists)
- Exposes API functions:
    * detect_ignitions_from_segments(segments, ...)
    * build_semantic_spectrogram(segments)
    * compute_ignition_gradient(spec)
    * analyze_segments_for_ignition(segments, ...)
    * process_audio_file(path, ...)  # optional, requires torchaudio

Usage examples:
    # Run unit tests
    python ignition_deep.py --test

    # Use on handcrafted segments
    from ignition_deep import analyze_segments_for_ignition
    spec, igns = analyze_segments_for_ignition(segments)

Notes:
- Optional extras: torchaudio, transformers, librosa, matplotlib
  The module will run fully without them; ML pipelines are enabled if available.
- This file intentionally keeps production-ready hooks (batching, caching, configs)
  while remaining interpretable and debuggable.

Author: Dangerous Builder Mode (ChatGPT-assisted)
"""

from typing import List, Dict, Any, Tuple, Optional
import re
import math
import statistics
import time
import tempfile
import os
import sys
import logging

# Optional imports -- non-fatal
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

try:
    from transformers import pipeline
    TRANSFORMERS_AVAILABLE = True
except Exception:
    pipeline = None
    TRANSFORMERS_AVAILABLE = False

try:
    import matplotlib.pyplot as plt
    MATPLOTLIB_AVAILABLE = True
except Exception:
    plt = None
    MATPLOTLIB_AVAILABLE = False
try:
    from viral_finder.parallel_mind import ParallelMind
    PARALLEL_MIND_AVAILABLE = True
except Exception:
    ParallelMind = None
    PARALLEL_MIND_AVAILABLE = False

# configure logging
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("ignition_deep")
_parallel_mind = None

def get_parallel_mind():
    global _parallel_mind
    if _parallel_mind is None and PARALLEL_MIND_AVAILABLE:
        _parallel_mind = ParallelMind()
    return _parallel_mind

# -----------------------------
# Configurable bands + weights
# -----------------------------
VIRAL_BANDS = {
    "shock": [
        "lie", "lying", "lied", "wrong", "destroyed", "ruined", "exposed",
        "scam", "fake", "mistake", "failure", "was almost killed", "almost killed"
    ],
    "curiosity": [
        "why", "how", "secret", "truth", "nobody", "never",
        "what if", "the reason", "you won't believe", "guess what"
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
        "$", "%", "exactly", "only", "just", "days", "months", "years", "42,000", "42k"
  
    ],
    "contradiction": [
    "but",
    "however",
    "does not",
    "is not",
    "are lying",
    "everyone is wrong",
    "most people think",
    "the truth is"
    ],
    "self_risk": [
    "my career",
    "my life",
    "i almost",
    "this nearly",
    "cost me",
    "destroyed my",
    "ruined my"
   ]


}

BAND_WEIGHTS = {
    "shock": 1.0,
    "curiosity": 1.0,
    "authority": 0.6,
    "emotion": 0.75,
    "specificity": 0.5,
    "contradiction": 1.2,
    "self_risk": 1.3


}

# Precompile regex patterns for speed
_BAND_PATTERNS = {b: [re.compile(r"\b" + re.escape(w) + r"\b", flags=re.I) for w in words]
                  for b, words in VIRAL_BANDS.items()}

# -----------------------------
# Utility helpers
# -----------------------------

def normalize_text(s: Optional[str]) -> str:
    if not s:
        return ""
    s = s.replace("\u2019", "'")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def safe_float(x, default=0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default

def classify_ignition_type(energy: dict, slope: float) -> str:
    """
    Classify the cognitive punch type based on semantic energy + dynamics.
    """

    if energy.get("self_risk", 0) >= 1.0:
        return "quiet_danger"

    if energy.get("contradiction", 0) >= 1.0:
        if slope > 0:
            return "belief_flip"
        else:
            return "contrarian_truth"

    if energy.get("curiosity", 0) >= 1.0:
        return "curiosity_cliff"

    if energy.get("authority", 0) >= 1.0 and energy.get("specificity", 0) >= 0.5:
        return "authority_anchor"

    if energy.get("emotion", 0) >= 1.0:
        return "emotional_spike"

    if slope < 0 and sum(energy.values()) >= 1.5:
        return "payoff_reinforcement"

    return "generic_ignition"

# -----------------------------
# Semantic spectrogram builder
# -----------------------------

def compute_semantic_energy(text: str) -> Dict[str, float]:
    """Return energy per band for the given text.

    Lightweight, interpretable scoring: counts phrase hits and applies weights.
    Uses both exact matches and short-token fuzzy additions (simple heuristics).
    """
    x = normalize_text(text or "")
    energies = {band: 0.0 for band in VIRAL_BANDS}
    if not x:
        return energies

    # token heuristics
    tokens = x.split()
    tok_len = len(tokens)

    for band, patterns in _BAND_PATTERNS.items():
        hits = 0
        for p in patterns:
            for _ in p.findall(x):
                hits += 1
        # small boost for short punchy sentences
        if tok_len <= 8 and hits:
            hits += 0.5
        energies[band] = float(hits) * BAND_WEIGHTS.get(band, 1.0)

    return energies


def build_semantic_spectrogram(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build per-segment semantic energy matrix.

    segments: list of {start,end,text, optional: audio_energy,pitch,motion,emotion}
    returns: list of {time,duration,text,energy,audio_energy,pitch,motion,emotion}
    """
    spec = []
    for seg in segments:
        start = safe_float(seg.get("start", 0.0))
        end = safe_float(seg.get("end", start + 0.5))
        dur = max(0.001, end - start)
        text = seg.get("text", "")
        energy = compute_semantic_energy(text)
        audio_energy = safe_float(seg.get("audio_energy", 0.0))
        pitch = safe_float(seg.get("pitch", 0.0))
        motion = safe_float(seg.get("motion", 0.0))
        emotion = seg.get("emotion")  # optional: {'label':str,'score':float}

        spec.append({
            "time": start,
            "duration": dur,
            "text": text,
            "energy": energy,
            "audio_energy": audio_energy,
            "pitch": pitch,
            "motion": motion,
            "emotion": emotion
        })
    return spec


# -----------------------------
# Ignition gradient computation
# -----------------------------

def compute_ignition_gradient(spec: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Compute gradient (delta) of the semantic spectrogram. Includes emotion delta when available."""
    if not spec or len(spec) < 2:
        return []

    grads = []
    for i in range(1, len(spec)):
        prev = spec[i - 1]
        curr = spec[i]
        gradient = {}
        positive_sum = 0.0

        # semantic band deltas
        for band in VIRAL_BANDS:
            pv = prev["energy"].get(band, 0.0)
            cv = curr["energy"].get(band, 0.0)
            d = cv - pv
            gradient[band] = float(round(d, 4))
            if d > 0:
                positive_sum += d

        # audio/pitch/motion deltas
        audio_delta = max(0.0, curr.get("audio_energy", 0.0) - prev.get("audio_energy", 0.0))
        pitch_delta = abs(curr.get("pitch", 0.0) - prev.get("pitch", 0.0))
        motion_delta = max(0.0, curr.get("motion", 0.0) - prev.get("motion", 0.0))

        # emotion delta (if provided by SER)
        emotion_delta = 0.0
        if prev.get("emotion") and curr.get("emotion"):
            try:
                emotion_delta = float(curr["emotion"].get("score", 0.0)) - float(prev["emotion"].get("score", 0.0))
            except Exception:
                emotion_delta = 0.0

        # Combined ignition score. Tunable: semantic dominates, emotion confirms.
        score = (positive_sum * 0.5) + (audio_delta * 0.18) + (pitch_delta * 0.12) + (motion_delta * 0.08) + (max(0.0, emotion_delta) * 0.12)

        # slope: relative semantic change normalized by previous semantic energy
        prev_total_sem = sum(prev["energy"].values())
        slope = 0.0
        if prev_total_sem > 0:
            slope = (sum(curr["energy"].values()) - prev_total_sem) / max(1e-6, prev_total_sem)

        grads.append({
            "time": curr["time"],
            "duration": curr["duration"],
            "gradient": gradient,
            "score": float(round(score, 4)),
            "slope": float(round(slope, 4)),
            "audio_delta": float(round(audio_delta, 4)),
            "pitch_delta": float(round(pitch_delta, 4)),
            "motion_delta": float(round(motion_delta, 4)),
            "emotion_delta": float(round(emotion_delta, 4)),
            "meta": {"text": curr.get("text", ""), "emotion": curr.get("emotion")}
        })

    return grads

def classify_ignition_type(energy: dict, slope: float) -> str:
    """
    Classify the cognitive punch type based on semantic energy + dynamics.
    Returns a string label.
    """

    # Quiet existential danger
    if energy.get("self_risk", 0) >= 1.0:
        return "quiet_danger"

    # Belief violation / contrarian truth
    if energy.get("contradiction", 0) >= 1.0:
        if slope > 0:
            return "belief_flip"
        else:
            return "contrarian_truth"

    # Curiosity hook
    if energy.get("curiosity", 0) >= 1.0:
        return "curiosity_cliff"

    # Authority-based hook
    if energy.get("authority", 0) >= 1.0 and energy.get("specificity", 0) >= 0.5:
        return "authority_anchor"

    # Emotional spike
    if energy.get("emotion", 0) >= 1.0:
        return "emotional_spike"

    # Late payoff / reinforcement
    if slope < 0 and sum(energy.values()) >= 1.5:
        return "payoff_reinforcement"

    return "generic_ignition"

# -----------------------------
# Ignition detection
# -----------------------------

def detect_ignitions_from_spec(
    spec: List[Dict[str, Any]],
    min_score: float = 0.6,
    min_slope: float = 0.12,
    min_band_hits: int = 1,
    collapse_window: float = 1.0
) -> List[Dict[str, Any]]:
    """Detect ignition events from built semantic spec (with optional emotions)."""

    grads = compute_ignition_gradient(spec)
    if not grads:
        return []

    candidates = []

    # iterate with index so spec aligns with grads
    for i, g in enumerate(grads, start=1):
        band_increases = sum(1 for v in g["gradient"].values() if v > 0.0)

        emotion_bonus = 0.05 if g.get("emotion_delta", 0.0) > 0.02 else 0.0
        effective_score = g["score"] + emotion_bonus

        energy_now = spec[i]["energy"]
        prev_energy = spec[i - 1]["energy"]

        # -----------------------------
        # PRIORITY: belief FLIP, not setup
        # -----------------------------
        if (
            energy_now.get("contradiction", 0.0) >= 1.0
            and prev_energy.get("contradiction", 0.0) == 0.0
            and sum(prev_energy.values()) > 0
            and energy_now.get("self_risk", 0.0) == 0.0
        ):
            effective_score += 0.15

        # -----------------------------
        # ABSOLUTE IGNITION
        # -----------------------------
        absolute_danger = False

        if energy_now.get("self_risk", 0.0) >= 1.0:
            absolute_danger = True

        if (
            energy_now.get("contradiction", 0.0) >= 1.0
            and sum(energy_now.values()) >= 1.2
            and g.get("audio_delta", 0.0) < 0.1
        ):
            absolute_danger = True

        # -----------------------------
        # GATED DECISION
        # -----------------------------
        band_ok = band_increases >= min_band_hits or absolute_danger
        slope_ok = g["slope"] >= min_slope or absolute_danger
        score_ok = effective_score >= min_score or absolute_danger
        # SUPPRESS belief setup ignitions (must be followed by violation)
        is_setup_only = (
        energy_now.get("contradiction", 0.0) >= 1.0
        and prev_energy.get("contradiction", 0.0) == 0.0
        and g["slope"] == 0.0
        and energy_now.get("self_risk", 0.0) == 0.0
        )

        if is_setup_only:
           continue

        if band_ok and slope_ok and score_ok:
            # candidates.append({
            #     "time": g["time"],
            #     "score": round(effective_score, 4),
            #     "raw_score": g["score"],
            #     "slope": g["slope"],
            #     "bands": {k: v for k, v in g["gradient"].items() if v > 0},
            #     "meta": g.get("meta", {}),
            #     "ignition_type": "absolute" if absolute_danger else "gradient"
            # })
            punch_type = classify_ignition_type(
            energy=energy_now,
            slope=g["slope"]
            )

            candidates.append({
             "time": g["time"],
             "score": round(effective_score, 4),
             "raw_score": g["score"],
             "slope": g["slope"],
             "bands": {k: v for k, v in g["gradient"].items() if v > 0},
             "meta": g.get("meta", {}),
            "ignition_type": punch_type
            })


    # -----------------------------
    # COLLAPSE NEARBY IGNITIONS (AFTER LOOP)
    # -----------------------------
    if not candidates:
        return []

    candidates.sort(key=lambda x: x["time"])
    collapsed = []
    cur = candidates[0]

    for nxt in candidates[1:]:
        same_type = nxt["ignition_type"] == cur["ignition_type"]

        if same_type and (nxt["time"] - cur["time"] <= collapse_window):
            if nxt["score"] > cur["score"]:
                cur = nxt
        else:
            collapsed.append(cur)
            cur = nxt

    collapsed.append(cur)

    # pre-roll
    for c in collapsed:
        c["pre_time"] = round(max(0.0, c["time"] - 0.5), 3)

    return collapsed

def detect_ignitions(segments: List[Dict[str, Any]],
                     min_score: float = 0.6,
                     min_slope: float = 0.12) -> List[Dict[str, Any]]:
    """Convenience wrapper: build spec and detect ignitions."""
    spec = build_semantic_spectrogram(segments)
    return detect_ignitions_from_spec(spec, min_score=min_score, min_slope=min_slope)
# --------------------
# Ignition selection (editorial intelligence)
# --------------------

# def select_independent_ignitions(
#     ignitions: list,
#     goal: str = "viral",
#     max_clips: int = 4,
#     min_time_gap: float = 20.0
# ) -> list:
#     """
#     Select diverse, independent ignitions.
#     Simulates human editor choosing multiple angles from one podcast.
#     """

#     if not ignitions:
#         return []

#     selected = []
#     used_types = set()

#     # highest score first
#     pool = sorted(ignitions, key=lambda x: x["score"], reverse=True)

#     for ig in pool:
#         if len(selected) >= max_clips:
#             break

#         # avoid repeating same cognitive angle
#         if ig["ignition_type"] in used_types:
#             continue

#         # avoid same moment phrased differently
#         if any(abs(ig["time"] - s["time"]) < min_time_gap for s in selected):
#             continue

#         selected.append(ig)
#         used_types.add(ig["ignition_type"])

#     return selected

try:
    from .ignition_memory import get_punch_weights
except ImportError:
    from ignition_memory import get_punch_weights


# def select_clip_start(ignitions: list, goal: str = "viral") -> dict:
#     """
#     Decide which ignition should be the clip starting point.
#     Parallel-mind aware selection.
#     """

#     if not ignitions:
#         return None

#     punch_priority = {
#         "viral": [
#             "belief_flip",
#             "quiet_danger",
#             "curiosity_cliff",
#             "emotional_spike",
#             "authority_anchor",
#         ],
#         "trust": [
#             "authority_anchor",
#             "quiet_danger",
#             "belief_flip",
#         ],
#         "education": [
#             "contrarian_truth",
#             "belief_flip",
#             "authority_anchor",
#         ]
#     }

#     learned_weights = get_punch_weights()
#     order = punch_priority.get(goal, [])

#     scored = []

#     for ig in ignitions:
#         base = ig["score"]
#         weight = learned_weights.get(ig["ignition_type"], 1.0)

#         priority_boost = 1.2 if ig["ignition_type"] in order else 1.0

#         # 🧠 Parallel Mind signal (soft influence)
#         pm = ig.get("parallel_mind", {})
#         pm_score = pm.get("total", 0.0)

#         # fuse brains
#         final_score = (
#             base * weight * priority_boost * 0.65
#             + pm_score * 0.35
#         )

#         scored.append((final_score, ig))

#     scored.sort(key=lambda x: x[0], reverse=True)
#     return scored[0][1]
def select_diverse_ignitions(
    ignitions,
    angle_key="mind_scores",
    min_score=0.25,
    max_per_angle=1,
    max_total=5
):
    """
    Select ignitions from different dominant angles.
    """
    buckets = {}
    selected = []

    for ig in ignitions:
        mind = ig.get("meta", {}).get(angle_key, {})
        if not mind:
            continue

        dominant_angle = max(mind, key=mind.get)

        if mind[dominant_angle] < min_score:
            continue

        buckets.setdefault(dominant_angle, [])
        buckets[dominant_angle].append(ig)

    # pick best from each angle
    for angle, items in buckets.items():
        items.sort(key=lambda x: x["score"], reverse=True)
        selected.append(items[0])

        if len(selected) >= max_total:
            break

    return selected



# -----------------------------
# Optional: Speech Emotion Recognition (SER) pipeline helpers
# -----------------------------

SER_PIPELINE = None
SER_MODEL_NAME = "speechbrain/emotion-recognition-wav2vec2-IEMOCAP"  # sensible default


def is_ser_available() -> bool:
    return TRANSFORMERS_AVAILABLE and TORCHAUDIO_AVAILABLE


def init_ser_pipeline(model_name: str = SER_MODEL_NAME, device: Optional[int] = None):
    global SER_PIPELINE
    if not TRANSFORMERS_AVAILABLE:
        logger.warning("transformers pipeline not available. SER disabled.")
        return None
    try:
        device_val = device if device is not None else (0 if TORCH_AVAILABLE and torch.cuda.is_available() else -1)
        SER_PIPELINE = pipeline("audio-classification", model=model_name, device=device_val)
        logger.info(f"Loaded SER pipeline: {model_name} (device={device_val})")
        return SER_PIPELINE
    except Exception as e:
        logger.exception("Failed to initialize SER pipeline: %s", e)
        SER_PIPELINE = None
        return None


def batch_emotion_infer(chunks: List[Tuple[float, float, Any]], batch_size: int = 8) -> List[Optional[Dict[str, Any]]]:
    """Batch inference for SER. Chunks = list of (start, end, raw_audio|filepath)

    Implementation details:
      - If pipeline accepts raw samples, we try that first.
      - Otherwise, we create temporary files in a tempdir and pass paths (cleaned after use).

    Returns list of {'label':str,'score':float} or None for a chunk.
    """
    if SER_PIPELINE is None:
        return [None for _ in chunks]

    results: List[Optional[Dict[str, Any]]] = [None] * len(chunks)
    # Try raw input path (transformers supports file paths or raw waveforms in some versions)
    supports_raw = False
    try:
        # quick probe: call pipeline with a tiny dummy if safe (skip to avoid heavy ops)
        supports_raw = True  # optimistic default; we'll handle exceptions
    except Exception:
        supports_raw = False

    # We will use temp files approach for stability (still batched)
    tmpdir = tempfile.mkdtemp(prefix="ignition_ser_")
    created_files = []
    try:
        filepaths = []
        for idx, (start, end, audio) in enumerate(chunks):
            # audio may be numpy array or torch tensor or filepath
            if isinstance(audio, str) and os.path.exists(audio):
                filepaths.append((idx, audio))
                continue
            # write to wav using torchaudio or soundfile
            fp = os.path.join(tmpdir, f"chunk_{idx}.wav")
            try:
                if TORCHAUDIO_AVAILABLE and isinstance(audio, (torch.Tensor,)):
                    torchaudio.save(fp, audio.unsqueeze(0), 16000)
                else:
                    # assume numpy array
                    import soundfile as sf
                    sf.write(fp, audio, 16000)
                filepaths.append((idx, fp))
                created_files.append(fp)
            except Exception as e:
                logger.exception("Failed to write temp chunk for SER: %s", e)
                filepaths.append((idx, None))

        # run pipeline in batches
        vector = [p for p in filepaths if p[1]]
        for i in range(0, len(vector), batch_size):
            batch = vector[i:i + batch_size]
            paths = [p[1] for p in batch]
            try:
                preds = SER_PIPELINE(paths)
                # preds is a list of lists or list of dicts depending on pipeline
                # Normalize to single prediction per path
                for j, pr in enumerate(preds):
                    idx = batch[j][0]
                    if isinstance(pr, list) and pr:
                        top = pr[0]
                    elif isinstance(pr, dict):
                        top = pr
                    else:
                        top = None
                    results[idx] = top
            except Exception as e:
                logger.exception("SER pipeline batch failed: %s", e)
                # continue; leave results None

    finally:
        # cleanup tempdir
        try:
            for f in created_files:
                if os.path.exists(f):
                    os.remove(f)
            os.rmdir(tmpdir)
        except Exception:
            pass

    return results


# -----------------------------
# Audio processing helper (optional)
# -----------------------------

def process_audio_file_to_segments(path: str,
                                   window_s: float = 1.0,
                                   hop_s: float = 0.5,
                                   min_audio_energy: float = 0.01,
                                   run_ser: bool = False) -> List[Dict[str, Any]]:
    """Create segments from audio file (requires torchaudio).

    Returns segments list like: {start,end,text:'',audio_energy,pitch,motion,emotion}
    NOTE: text is empty (no ASR here). Use your transcript pipeline to add text.
    """
    if not TORCHAUDIO_AVAILABLE:
        raise RuntimeError("torchaudio is required for processing audio files. Install torchaudio.")

    waveform, sr = torchaudio.load(path)
    # convert to mono
    if waveform.size(0) > 1:
        waveform = waveform.mean(dim=0)
    total_s = waveform.size(0) / sr

    segments: List[Dict[str, Any]] = []
    starts = [round(i * hop_s, 3) for i in range(int((total_s - window_s) // hop_s) + 1)]
    chunks_for_ser: List[Tuple[float, float, Any]] = []
    for s in starts:
        s_idx = int(s * sr)
        e_idx = int(min((s + window_s) * sr, waveform.size(0)))
        chunk = waveform[s_idx:e_idx]
        # simple audio energy metric
        audio_energy = float(chunk.abs().mean().item())
        pitch = 0.0
        motion = 0.0  # visual missing
        seg = {"start": s, "end": round(min(s + window_s, total_s), 3), "text": "", "audio_energy": audio_energy, "pitch": pitch, "motion": motion}
        segments.append(seg)
        if run_ser:
            chunks_for_ser.append((s, s + window_s, chunk))

    # run SER and attach emotions
    if run_ser and chunks_for_ser:
        if SER_PIPELINE is None:
            init_ser_pipeline()
        ser_preds = batch_emotion_infer(chunks_for_ser)
        for (s, e, _), pred in zip(chunks_for_ser, ser_preds):
            # find matching segment index
            for seg in segments:
                if abs(seg["start"] - s) < 1e-6:
                    seg["emotion"] = pred
                    break

    return segments


# -----------------------------
# High-level analyzer
# -----------------------------

def analyze_segments_for_ignition(segments: List[Dict[str, Any]],
                                  min_score: float = 0.6,
                                  min_slope: float = 0.12,
                                  run_ser_if_available: bool = False) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Run full semantic spectrogram + optional SER + ignition detection.

    If run_ser_if_available is True and SER pipeline is available, attempts to fill emotion fields.
    """
    # shallow copy segments
    segs = [dict(s) for s in segments]

    # optionally run SER if segments have no emotion and models exist
    need_ser = run_ser_if_available and any(s.get("emotion") is None for s in segs) and TRANSFORMERS_AVAILABLE
    if need_ser:
        # prepare chunks for the pipeline; audio must be provided in segment['audio'] or audio_energy as placeholder
        chunks = []
        for s in segs:
            # require raw audio in segment['raw_audio'] as torch.Tensor or numpy array for SER
            if s.get("raw_audio") is not None:
                chunks.append((s["start"], s["end"], s["raw_audio"]))
            else:
                chunks.append((s["start"], s["end"], ""))
        if SER_PIPELINE is None:
            init_ser_pipeline()
        try:
            preds = batch_emotion_infer(chunks)
            # attach
            for seg, p in zip(segs, preds):
                seg["emotion"] = p
        except Exception as e:
            logger.exception("SER integration failed: %s", e)

    spec = build_semantic_spectrogram(segs)
    ignitions = detect_ignitions_from_spec(spec, min_score=min_score, min_slope=min_slope)
    return spec, ignitions


# -----------------------------
# Simple renderer + export
# -----------------------------

def pretty_print_ignitions(ignitions: List[Dict[str, Any]]):
    if not ignitions:
        print("IGNITIONS FOUND: none")
        return
    print("IGNITIONS FOUND:")
    for ig in ignitions:
        print(f"- time={ig['time']:.3f}s pre={ig['pre_time']:.3f}s score={ig['score']} slope={ig['slope']}")
        bands = ig.get("bands", {})
        if bands:
            print("   bands:")
            for k, v in bands.items():
                print(f"     {k}: {v}")
        meta = ig.get("meta", {})
        if meta.get("text"):
            print(f"   text: {meta.get('text')}")


def plot_heatmap(spec: List[Dict[str, Any]], ignitions: List[Dict[str, Any]]):
    if not MATPLOTLIB_AVAILABLE:
        logger.warning("matplotlib not available. Skipping heatmap.")
        return
    # create band-time matrix
    times = [s["time"] for s in spec]
    band_names = list(VIRAL_BANDS.keys())
    matrix = [[s["energy"].get(b, 0.0) for s in spec] for b in band_names]

    fig, ax = plt.subplots(figsize=(10, 4))
    c = ax.pcolormesh(times + [times[-1] + spec[-1]["duration"]], range(len(band_names) + 1), matrix, shading='auto')
    ax.set_yticks([i + 0.5 for i in range(len(band_names))])
    ax.set_yticklabels(band_names)
    ax.set_xlabel('Time (s)')
    ax.set_title('Semantic Spectrogram (energy per band)')
    for ig in ignitions:
        ax.axvline(ig['time'], color='white', linestyle='--')
        ax.text(ig['time'], len(band_names) + 0.1, f"{ig['score']}", color='white')
    fig.colorbar(c, ax=ax, label='Energy')
    plt.tight_layout()
    plt.show()


# -----------------------------
# Small unit test harness
# -----------------------------

def make_segment(start, dur, text, audio=0.0, pitch=0.0, motion=0.0, raw_audio=None):
    return {"start": start, "end": round(start + dur, 3), "text": text, "audio_energy": audio, "pitch": pitch, "motion": motion, "raw_audio": raw_audio}


def run_unit_tests(verbose: bool = True):
    print("\n========== IGNITION-DEEP UNIT TESTS ==========")

    segments1 = [
        make_segment(0.0, 1.0, "so today i want to tell you something quick", audio=0.1),
        make_segment(1.0, 1.0, "most people think money makes them happy", audio=0.05),
        make_segment(2.0, 1.0, "but they are lying to you", audio=0.6),
        make_segment(3.0, 1.0, "i lost everything and built it back", audio=0.7)
    ]

    segments2 = [
        make_segment(0.0, 1.0, "listen closely", audio=0.02, pitch=100),
        make_segment(1.0, 1.0, "this secret cost me 42,000 rupees", audio=0.04),
        make_segment(2.0, 1.0, "most people never talk about this", audio=0.03)
    ]

    segments3 = [
        make_segment(0.0, 1.0, "you wont believe this secret i found", audio=0.2),
        make_segment(1.0, 1.0, "so yeah i bought apples at the market", audio=0.2),
        make_segment(2.0, 1.0, "and then it was fine", audio=0.15)
    ]

    segments4 = [
        make_segment(0.0, 1.0, "wait this almost destroyed my career", audio=0.2),
        make_segment(1.0, 1.0, "but here is the reason most people fail", audio=0.15),
        make_segment(2.0, 1.0, "i spent ten years learning this", audio=0.25),
        make_segment(3.0, 1.0, "and the secret is simple: attention", audio=0.5)
    ]

    cases = [
        ("PERFECT VIRAL", segments1, 0.6, 0.12),
        ("QUIET BUT DEADLY", segments2, 0.4, 0.05),
        ("CLICKBAIT NO PAYOFF", segments3, 0.6, 0.12),
        ("MULTIPLE IGNITIONS", segments4, 0.5, 0.1)
    ]

    for name, segs, min_score, min_slope in cases:
        print(f"\nTEST CASE: {name}")
        spec, ign = analyze_segments_for_ignition(segs, min_score=min_score, min_slope=min_slope)
        if not ign:
            print("❌ No ignitions detected")
        else:
            print("✅ Ignitions:")
            pretty_print_ignitions(ign)

    print("\nUnit tests complete. Tweak thresholds in detect_ignitions_from_spec if you want more/less sensitivity.")


# -----------------------------
# CLI
# -----------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Ignition Deep - Detector (builder mode)")
    parser.add_argument("--test", action="store_true", help="Run unit tests")
    parser.add_argument("--file", type=str, help="Optional audio file to process (requires torchaudio)")
    parser.add_argument("--plot", action="store_true", help="Show heatmap when running tests or file")
    args = parser.parse_args()

    if args.test:
        run_unit_tests()
    elif args.file:
        if not TORCHAUDIO_AVAILABLE:
            logger.error("torchaudio not available. Install torchaudio to process audio files.")
            sys.exit(1)
        logger.info("Processing audio file: %s", args.file)
        segs = process_audio_file_to_segments(args.file, window_s=1.0, hop_s=0.5, run_ser=False)
        spec, ign = analyze_segments_for_ignition(segs)
        pretty_print_ignitions(ign)
        if args.plot and MATPLOTLIB_AVAILABLE:
            plot_heatmap(spec, ign)
    else:
        parser.print_help()
