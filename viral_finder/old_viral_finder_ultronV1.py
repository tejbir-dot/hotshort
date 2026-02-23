"""
      ██████  ██    ██ ██████  ██████  ███    ██
     ██       ██    ██ ██   ██ ██   ██ ████   ██
     ██   ███ ██    ██ ██████  ██████  ██ ██  ██   ULTRON V1
     ██    ██ ██    ██ ██   ██ ██   ██ ██  ██ ██   Viral Intelligence Engine
      ██████   ██████  ██████  ██   ██ ██   ████

 This engine merges:
 - Whisper CPU-stable transcript
 - Audio RMS emotional scoring
 - Visual motion curiosity scoring
 - Neural embedding meaning engine
 - Adaptive virality fusion
 - Clip slicing intelligence
"""

import os
import time
import numpy as np
import librosa
import cv2
import torch
import whisper
from sentence_transformers import SentenceTransformer, util
from typing import Dict, List

os.environ["CUDA_VISIBLE_DEVICES"] = ""  # ULTRON runs CPU-stable

# --------------------------------------------------------
# LOAD MODELS ONCE
# --------------------------------------------------------
WHISPER_MODEL = None
MEANING_MODEL = SentenceTransformer("all-MiniLM-L6-v2")  # fast + semantic

def load_whisper():
    global WHISPER_MODEL
    if WHISPER_MODEL is None:
        print("[ULTRON] Loading Whisper tiny…")
        WHISPER_MODEL = whisper.load_model("tiny", device="cpu").float()
    return WHISPER_MODEL

# --------------------------------------------------------
# GET VIDEO DURATION
# --------------------------------------------------------
def get_duration(path):
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return 0
    fps = cap.get(cv2.CAP_PROP_FPS)
    frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    cap.release()
    return frames / fps if fps else 0

# --------------------------------------------------------
# ULTRON TRANSCRIPT ENGINE
# --------------------------------------------------------
def extract_transcript(path):
    model = load_whisper()
    print("[TRANSCRIPT] Running ULTRON Whisper…")

    audio = whisper.load_audio(path)
    audio = whisper.pad_or_trim(audio)
    mel = whisper.log_mel_spectrogram(audio).to(model.device)

    # language detection
    lang, probs = model.detect_language(mel)
    print(f"[TRANSCRIPT] Language: {lang}")

    opts = whisper.DecodingOptions(
        language=lang,
        fp16=False,
        without_timestamps=False,
        beam_size=1
    )

    res = model.decode(mel, opts)

    dur = get_duration(path)
    segments = []

    # CASE 1 — Whisper gives timestamps
    if hasattr(res, "segments") and res.segments:
        for s in res.segments:
            if not s.text.strip():
                continue

            segments.append({
                "start": max(0, float(s.start)),
                "end": min(dur, float(s.end)),
                "text": s.text.strip()
            })

        print(f"[TRANSCRIPT] {len(segments)} segments ✓")
        return segments

    # CASE 2 — fallback equal split
    print("[TRANSCRIPT] No timestamps → ULTRON fallback mode")
    full = res.text.strip()
    lines = [ln.strip() for ln in full.split(".") if ln.strip()]

    chunk = dur / max(1, len(lines))
    t = 0
    for ln in lines:
        segments.append({
            "start": round(t,2),
            "end": round(min(dur, t+chunk),2),
            "text": ln
        })
        t += chunk

    print(f"[TRANSCRIPT] Fallback {len(segments)} segments ✓")
    return segments

# --------------------------------------------------------
# AUDIO ENGINE
# --------------------------------------------------------
def analyze_audio(path, sr=16000):
    y, sr = librosa.load(path, sr=sr)
    rms = librosa.feature.rms(y=y)[0]
    times = librosa.frames_to_time(np.arange(len(rms)), sr=sr)
    return [{"time": float(t), "energy": float(r)} for t, r in zip(times, rms)]

# --------------------------------------------------------
# VISUAL MOTION ENGINE
# --------------------------------------------------------
def analyze_motion(path, sample_fps=2):
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return []

    fps = cap.get(cv2.CAP_PROP_FPS) or 24
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    step = max(1, int(fps / sample_fps))
    motion = []

    prev = None
    for i in range(0, total, step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ok, frame = cap.read()
        if not ok:
            break

        small = cv2.resize(frame, (320,180))
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

        if prev is not None:
            diff = cv2.absdiff(gray, prev)
            motion.append({
                "time": i/fps,
                "motion": float(diff.mean())
            })

        prev = gray

    cap.release()
    return motion

# --------------------------------------------------------
# MEANING BRAIN (semantic importance)
# --------------------------------------------------------
def meaning_score(sentence: str) -> float:
    topics = [
        "life changing moment",
        "important lesson",
        "deep truth",
        "emotional story",
        "startup breakthrough",
        "AI insight",
        "viral motivation"
    ]
    embeds = MEANING_MODEL.encode([sentence] + topics, convert_to_tensor=True)
    sentence_vec = embeds[0]
    topic_vecs = embeds[1:]
    sim = util.cos_sim(sentence_vec, topic_vecs).mean().item()
    return max(0.0, min(1.0, sim))

# --------------------------------------------------------
# ULTRON VIRALITY FUSION ENGINE
# --------------------------------------------------------
def fuse(hook, audio, motion, meaning):
    return float(
        0.35*hook +
        0.15*audio +
        0.20*motion +
        0.30*meaning
    )

# --------------------------------------------------------
# SHALLOW HOOK DETECTOR
# --------------------------------------------------------
def hook_score(text):
    text = text.lower()
    score = 0
    hooks = ["you won't believe", "crazy", "insane", "secret", "listen", "stop scrolling"]
    for h in hooks:
        if h in text:
            score += 0.3
    if "?" in text:
        score += 0.1
    return min(1.0, score)

# --------------------------------------------------------
# CORE ULTRON ENGINE
# --------------------------------------------------------
def ultron_find_clips(path, top_k=5):
    print("\n⚡ [ULTRON V1] Starting…")

    transcript = extract_transcript(path)
    audio = analyze_audio(path)
    motion = analyze_motion(path)
    dur = get_duration(path)

    results = []

    for seg in transcript:
        s, e = seg["start"], seg["end"]
        text = seg["text"]

        a_vals = [x["energy"] for x in audio if s <= x["time"] <= e]
        m_vals = [x["motion"] for x in motion if s <= x["time"] <= e]

        a_avg = float(np.mean(a_vals)) if a_vals else 0
        m_avg = float(np.mean(m_vals)) if m_vals else 0
        h = hook_score(text)
        m = meaning_score(text)

        final = fuse(h, a_avg, m_avg, m)

        clip_len = max(6, min(30, e - s))

        results.append({
            "start": s,
            "end": s + clip_len,
            "text": text,
            "hook": round(h,3),
            "audio": round(a_avg,3),
            "motion": round(m_avg,3),
            "meaning": round(m,3),
            "score": round(final,3)
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]
