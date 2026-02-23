"""
=========================================
        🔥 HOTSHORT V30 VIRAL ENGINE 🔥
      Neural Multimodal Viral Detection
        (Text + Audio + Vision + Motion)
      CPU-SAFE • Ultra-Fast • Crash-Proof
=========================================
"""

import os, time, math, traceback
import numpy as np
import cv2
import librosa
import torch
import whisper
from typing import List, Dict
from transformers import AutoModel, AutoTokenizer
from viral_finder.old_meaning_brain_v32 import score_all_segments
from viral_finder.old_meaning_brain_v31 import meaning_brain_score
from viral_finder.old_viral_finder_ultronV32 import find_viral_moments


# -----------------------------------------
# GLOBAL CONFIG
# -----------------------------------------
os.environ["CUDA_VISIBLE_DEVICES"] = ""  # Force CPU-safe mode

WHISPER_MODEL = "tiny"
TEXT_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

AUDIO_SR = 16000
HOP = 512
VIS_SIZE = (320, 180)
VIS_FPS = 2.5

TOP_K = 6
MIN_CLIP = 6
MAX_CLIP = 32

VERBOSE = True

def log(*a):
    if VERBOSE:
        print(*a)

# ============================================================
#                   LOAD MODELS (SAFE MODE)
# ============================================================

_model_whisper = None
_model_text = None
_tokenizer = None

def load_whisper():
    global _model_whisper
    if _model_whisper is None:
        log("[MODEL] Loading Whisper (CPU-safe)…")
        m = whisper.load_model(WHISPER_MODEL, device="cpu")
        _model_whisper = m.float()
        log("[MODEL] Whisper ready ✓")
    return _model_whisper


def load_text_model():
    global _model_text, _tokenizer
    if _model_text is None:
        log("[MODEL] Loading MiniLM semantic model…")
        _model_text = AutoModel.from_pretrained(TEXT_MODEL_NAME)
        _tokenizer = AutoTokenizer.from_pretrained(TEXT_MODEL_NAME)
        log("[MODEL] MiniLM ready ✓")
    return _model_text, _tokenizer


# ============================================================
#                SAFE VIDEO DURATION
# ============================================================

def get_duration(path):
    try:
        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            return 0
        fps = cap.get(cv2.CAP_PROP_FPS)
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        cap.release()
        return frames / fps if fps > 0 else 0
    except:
        return 0


# ============================================================
#                TRANSCRIPTION (CPU-SAFE)
# ============================================================

def extract_transcript(video_path: str) -> List[Dict]:
    """
    Ultra-stable transcript extractor for V30/V31/V32 engines.
    Works even when Whisper cannot return timestamp segments.
    """
    try:
        t0 = time.time()
        model = load_whisper()

        print("[TRANSCRIPT] Starting CPU-stable transcription…")

        # Load & preprocess audio
        audio = whisper.load_audio(video_path)
        audio = whisper.pad_or_trim(audio)
        mel = whisper.log_mel_spectrogram(audio).to(model.device)

        # --------------------------
        # DETECT LANGUAGE (SAFE MODE)
        # --------------------------
        with torch.no_grad():
            _, lang_probs = model.detect_language(mel)

        lang = max(lang_probs, key=lang_probs.get)

        # Whisper returns lang token ID sometimes → fix it
        if not isinstance(lang, str):
            lang = "en"

        print(f"[TRANSCRIPT] Language detected: {lang}")

        # --------------------------
        # PRIMARY DECODE (with timestamps)
        # --------------------------
        options = whisper.DecodingOptions(
            language=lang,
            fp16=False,
            without_timestamps=False,  # request segments
            beam_size=1                # safe greedy decode
        )

        res = model.decode(mel, options)
        dur = get_duration(video_path)

        # ==================================================
        # CASE A: Whisper returned timestamped segments
        # ==================================================
        if hasattr(res, "segments") and res.segments:
            segments = []
            for seg in res.segments:
                txt = seg.text.strip()
                if not txt:
                    continue

                start = float(seg.start)
                end   = float(seg.end)

                # clamp to video duration
                end = min(end, dur)

                segments.append({
                    "start": round(start, 2),
                    "end": round(end, 2),
                    "text": txt
                })

            print(f"[TRANSCRIPT] Extracted {len(segments)} segments ✓ in {time.time()-t0:.2f}s")
            return segments

        # ==================================================
        # CASE B: FALLBACK MODE (NO TIMESTAMPS)
        # ==================================================
        print("[TRANSCRIPT] No segments → Fallback mode activated")

        # Try getting the full decoded text
        fallback_text = ""
        if hasattr(res, "text") and isinstance(res.text, str):
            fallback_text = res.text.strip()

        if not fallback_text:
            print("[TRANSCRIPT] ERROR: No text found in fallback decode")
            return []

        # -------------------------------
        # V32-LITE SMART FALLBACK SEGMENTER
        # -------------------------------
        raw_lines = fallback_text.replace("\n", " ").split(".")
        lines = [ln.strip() for ln in raw_lines if ln.strip()]

        if len(lines) == 0:
            print("[TRANSCRIPT] Empty fallback → no transcript")
            return []

        # merge short lines to avoid useless micro-segments
        merged = []
        temp = ""

        for ln in lines:
            if len(ln.split()) < 5:
                temp += " " + ln
            else:
                if temp:
                    merged.append(temp.strip())
                    temp = ""
                merged.append(ln)

        if temp:
            merged.append(temp.strip())

        dur = get_duration(video_path)
        chunk = dur / max(1, len(merged))

        segments = []
        t = 0.0

        for ln in merged:
            start = t
            end = min(dur, t + chunk)

            segments.append({
                "start": round(start, 2),
                "end": round(end, 2),
                "text": ln
            })

            t = end

        print(f"[TRANSCRIPT] Fallback V32-Lite generated {len(segments)} smart segments ✓ in {time.time()-t0:.2f}s")
        return segments

    except Exception as e:
        print("[TRANSCRIPT ERROR]", str(e))
        traceback.print_exc()
        return []

# ============================================================
#                 AUDIO EMOTION + ENERGY
# ============================================================

def analyze_audio(path):
    try:
        log("[AUDIO] Loading audio…")
        y, sr = librosa.load(path, sr=AUDIO_SR)
        rms = librosa.feature.rms(y=y, hop_length=HOP)[0]
        pitch = librosa.yin(y, fmin=80, fmax=400)
        flux = librosa.onset.onset_strength(y=y, sr=sr)

        t_rms = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=HOP)
        t_fpx = librosa.frames_to_time(np.arange(len(pitch)), sr=sr, hop_length=HOP)

        audio_map = []
        for i in range(len(rms)):
            t = float(t_rms[i])
            e = float(rms[i])
            p = float(pitch[i]) if i < len(pitch) else 0
            f = float(flux[i]) if i < len(flux) else 0

            audio_map.append({
                "time": t,
                "energy": e,
                "pitch": p,
                "flux": f
            })

        log(f"[AUDIO] Done: {len(audio_map)} frames ✓")
        return audio_map

    except Exception as e:
        log("[AUDIO ERROR]", e)
        return []


# ============================================================
#                 VISUAL MOTION + FER (CPU)
# ============================================================

face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

def analyze_visual(
    video_path: str,
    max_seconds: float = 1.0,
    target_samples: int = 50,
    down=(128, 72),
    skip=False
):
    """
    ULTRON V34 — LIGHTNING VISUAL ENGINE
    ------------------------------------
    - Scans only the first N seconds (default 1 sec)
    - ~50 samples max
    - Sequential read (FAST)
    - Downscaled grayscale
    - Motion = frame delta mean
    """

    if skip:
        return [{"time": 0.0, "motion": 0.5}]

    import cv2
    import time
    import numpy as np

    t0 = time.time()
    cap = cv2.VideoCapture(video_path)

    if not cap.isOpened():
        return [{"time": 0.0, "motion": 0.5}]

    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0

    # process only first N seconds
    max_frames = min(total_frames, int(fps * max_seconds))

    step = max(1, max_frames // target_samples)

    last = None
    results = []
    count = 0

    for idx in range(0, max_frames, step):

        # break hard by time
        if (time.time() - t0) > max_seconds:
            break

        ok, frame = cap.read()
        if not ok:
            break

        gray = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), down)

        if last is not None:
            # NumPy vector op
            motion = float(np.mean(cv2.absdiff(gray, last)))
            ts = round(idx / fps, 2)
            results.append({"time": ts, "motion": motion})
            count += 1

        last = gray
        if count >= target_samples:
            break

    cap.release()

    if not results:
        return [{"time": 0.0, "motion": 0.5}]

    return results

# ============================================================
#      TEXT HOOK + SEMANTIC SCORE (MiniLM Neural)
# ============================================================
# ============================================================
# TEXT HOOK + SEMANTIC SCORE (MiniLM Neural ULTRON V1)
# ============================================================

from sentence_transformers import SentenceTransformer
import numpy as np
import torch

_text_model = None

def load_text_model():
    global _text_model
    if _text_model is None:
        print("[ULTRON] Loading MiniLM semantic brain…")
        _text_model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    return _text_model


def score_text(text):
    """
    ULTRON V1 – Hybrid scoring:
    1) Hook keywords (viral / curiosity / shock)
    2) NLP structure bonus (questions / contrast)
    3) Neural semantic similarity to viral anchors
    """
    if not text or len(text.strip()) == 0:
        return 0.0

    # ---------------------------------------------------------
    # 1) Hook keyword score
    # ---------------------------------------------------------
    t = text.lower()
    hooks = [
        "you won't believe", "listen", "watch", "secret", "crazy",
        "insane", "life changing", "hack", "tip", "shocking",
        "mistake", "nobody tells you", "stop scrolling"
    ]

    hook_score = sum(1 for h in hooks if h in t) * 0.12
    hook_score = min(hook_score, 0.40)  # cap max influence

    # punctuation engagement
    if "?" in t:
        hook_score += 0.08
    if "!" in t:
        hook_score += 0.08

    # ---------------------------------------------------------
    # 2) Neural Semantic Score (ULTRON CORE)
    # ---------------------------------------------------------
    model = load_text_model()

    anchors = [
        "shocking truth",
        "listen to this",
        "this will blow your mind",
        "life lesson",
        "motivation",
        "personal transformation",
        "startup secret",
        "deep insight",
        "viral moment",
        "unexpected twist"
    ]

    emb = model.encode([text], convert_to_numpy=True)[0]
    anch = model.encode(anchors, convert_to_numpy=True)

    # cosine similarity
    sims = np.dot(anch, emb) / (np.linalg.norm(anch, axis=1) * np.linalg.norm(emb))
    semantic_score = float(np.max(sims))

    # ---------------------------------------------------------
    # 3) Combine
    # ---------------------------------------------------------
    final = (0.45 * hook_score) + (0.55 * semantic_score)
    return float(min(1.0, max(0.0, final)))

# def score_text(text):
#     if not text:
#         return 0.0

#     model, tok = load_text_model()

#     inputs = tok(text, return_tensors="pt", truncation=True, padding=True)
#     with torch.no_grad():
#         emb = model(**inputs).last_hidden_state.mean(dim=1)
#     emb = emb.numpy()[0]

#     # viral semantic anchors
#     anchors = [
#         "shocking truth",
#         "listen to this",
#         "life changing insight",
#         "crazy story",
#         "unbelievable moment",
#         "success mindset",
#         "powerful advice"
#     ]

#     sims = []
#     for a in anchors:
#         t2 = tok(a, return_tensors="pt")
#         with torch.no_grad():
#             e2 = model(**t2).last_hidden_state.mean(dim=1).numpy()[0]
#         sim = float(np.dot(emb, e2) / (np.linalg.norm(emb)*np.linalg.norm(e2)))
#         sims.append(sim)

#     semantic_score = max(sims)  # 0–1 approx
#     semantic_score = max(0, min(1, (semantic_score + 1) / 2))

#     # lightweight hook keywords
#     hooks = ["?", "!", "secret", "crazy", "insane"]
#     hook_bonus = 0.1 if any(h in text.lower() for h in hooks) else 0.0

#     return min(1.0, semantic_score + hook_bonus)


# ============================================================
#      FUSION SCORE (Neural Text + Audio + Vision)
# ============================================================

def fuse(hook, energy, motion, face):
    e = min(1.0, energy / 0.12)
    m = min(1.0, motion / 22)
    f = min(1.0, face)

    return round(
        0.45 * hook +
        0.20 * e +
        0.25 * m +
        0.10 * f,
        3
    )


# ============================================================
#              CLIP BOUNDING (Smart Trimming)
# ============================================================

def clip_bounds(s, e, dur):
    mid = (s + e) / 2
    length = min(MAX_CLIP, max(MIN_CLIP, (e - s) + 6))
    a = max(0, mid - length / 2)
    b = min(dur, a + length)
    return round(a, 2), round(b, 2)


# ============================================================
#                    MAIN VIRAL ENGINE
# ============================================================

def find_viral_moments(path, top_k=TOP_K):
    log("\n🔥 [V30 ENGINE] Starting full viral scan…")

    # -----------------------------
    # 0) duration
    # -----------------------------
    dur = get_duration(path)
    if dur == 0:
        return []

    # -----------------------------
    # 1) transcript
    # -----------------------------
    trs = extract_transcript(path)
    if not trs:
        return []

    # -----------------------------
    # 2) audio energy timeline
    # -----------------------------
    aud = analyze_audio(path)

    # -----------------------------
    # 3) visual timeline (motion + face)
    # -----------------------------
    vis = analyze_visual(path)

    out = []
    prev_text = None  # <-- For ULTRON brain chaining

    # --------------------------------------------------
    # MAIN LOOP — each transcript segment → 1 viral candidate
    # --------------------------------------------------
    for seg in trs:
        text = seg["text"]
        s, e = seg["start"], seg["end"]

        # --------------------------
        # ULTRON MEANING BRAIN (V31)
        # --------------------------
        brain = meaning_brain_score(text, prev_text)

        impact     = brain["impact"]     # neural virality (0–1)
        meaning    = brain["meaning"]
        novelty    = brain["novelty"]
        emotion    = brain["emotion"]
        clarity    = brain["clarity"]

        prev_text = text  # update for next iteration

        # --------------------------
        # text hook score
        # --------------------------
        hook = score_text(text)

        # --------------------------
        # audio slice
        # --------------------------
        a_vals = [x["energy"] for x in aud if s <= x["time"] <= e]
        a_avg  = float(np.mean(a_vals)) if a_vals else 0.0

        # --------------------------
        # motion + face slice
        # --------------------------
        m_vals = [x["motion"] for x in vis if s <= x["time"] <= e]
        f_vals = [x.get("face", 0.0) for x in vis if s <= x["time"] <= e]

        m_avg = float(np.mean(m_vals)) if m_vals else 0.0
        f_avg = float(np.mean(f_vals)) if f_vals else 0.0

        # ---------------------------------
        # FINAL FUSED VIRALITY SCORE
        # ULTRON included
        # ---------------------------------
        score = (
            0.25 * hook +
            0.20 * a_avg +
            0.20 * m_avg +
            0.35 * impact    # <-- ULTRON brain takes 35% weight
        )

        # compute clip bounds
        cs, ce = clip_bounds(s, e, dur)

        # build output
        out.append({
            "text": text,
            "start": cs,
            "end": ce,
            "score": round(score, 3),
            "hook": round(hook, 3),
            "impact": round(impact, 3),

            "audio": round(a_avg, 3),
            "motion": round(m_avg, 3),
            "face": round(f_avg, 3),

            "meaning": meaning,
            "novelty": novelty,
            "emotion": emotion,
            "clarity": clarity
        })

    # sort by final virality
    out.sort(key=lambda x: x["score"], reverse=True)

    log(f"[V30 ENGINE] DONE → {len(out[:top_k])} clips ✓")

    return out[:top_k]

# ============================================================
# TEST RUN (optional)
# ============================================================
if __name__ == "__main__":
    p = "your_video.mp4"
    print(find_viral_moments(p))
