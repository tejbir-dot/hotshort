import os, time, math, traceback, subprocess, tempfile
import numpy as np
import cv2
import librosa
from pathlib import Path
from typing import List, Dict

os.environ["CUDA_VISIBLE_DEVICES"] = ""

import whisper
import torch
_model = None
def load_whisper_safe():
    global _model
    if _model is not None:
        return _model
    model = whisper.load_model("tiny", device="cpu").float()
    _model = model
    return model
# -----------------------------
# CONFIG
# -----------------------------
WHISPER_MODEL = "tiny"
TARGET_W = 1080
TARGET_H = 1920
AUDIO_SR = 16000
AUDIO_HOP = 512
VISUAL_RES = (320, 180)
VISUAL_FPS = 3.0
MIN_CLIP = 6.0
MAX_CLIP = 30.0
BITRATE = "6M"
AUDIO_BR = "128k"
COLOR_PRESET = "B"  # Premium punch


def log(*msg):
    print(*msg)


# =====================================================
# LOAD WHISPER SAFELY
# =====================================================
def load_whisper():
    global MODEL
    if MODEL is not None:
        return MODEL
    log("[WHISPER] Loading tiny (CPU-safe)…")
    MODEL = whisper.load_model(WHISPER_MODEL, device="cpu").float()
    log("[WHISPER] Ready ✓")
    return MODEL


# =====================================================
# VIDEO DURATION
# =====================================================

def get_video_duration(path: str) -> float:
    try:
        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            return 0.0
        fps = cap.get(cv2.CAP_PROP_FPS)
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        cap.release()
        return frames / fps if fps else 0.0
    except:
        return 0.0

# =====================================================
# TRANSCRIPT EXTRACTION
# =====================================================
def extract_transcript(video_path: str) -> List[Dict]:
    """
    V26 Ultra-Stable Transcript Extractor
    - CPU-only Whisper
    - Uses timestamped segments if available
    - Otherwise falls back to automatic equal-split segmentation
    - 100% crash-proof against .segments missing errors
    """
    try:
        t0 = time.time()
        model = load_whisper_safe()

        log("[TRANSCRIPT] Starting CPU-stable transcription (V26)")

        # Load & preprocess audio
        audio = whisper.load_audio(video_path)
        audio = whisper.pad_or_trim(audio)
        mel = whisper.log_mel_spectrogram(audio).to(model.device)

        # Detect language
        with torch.no_grad():
            _, lang_probs = model.detect_language(mel)
        lang = max(lang_probs, key=lang_probs.get)
        log(f"[TRANSCRIPT] Language detected: {lang}")

        # Decode with timestamps mode — safe settings
        decode_options = whisper.DecodingOptions(
            language=lang,
            fp16=False,
            without_timestamps=False,   # request segments
            beam_size=1                  # safe greedy decode
        )

        res = model.decode(mel, decode_options)
        dur = get_video_duration(video_path)

        # -------------------------------------------------------
        # CASE A: WHISPER RETURNED TIMESTAMPED SEGMENTS
        # -------------------------------------------------------
        if hasattr(res, "segments") and res.segments:
            segments = []
            for seg in res.segments:
                txt = seg.text.strip()
                if not txt:
                    continue

                start = float(seg.start)
                end   = float(seg.end)

                # clamp to actual video duration
                end = min(end, dur)

                segments.append({
                    "start": round(start, 2),
                    "end": round(end, 2),
                    "text": txt
                })

            log(f"[TRANSCRIPT] Extracted {len(segments)} segments ✓ in {time.time()-t0:.2f}s")
            return segments

        # -------------------------------------------------------
        # CASE B: NO SEGMENTS → FALLBACK TO EQUAL-SPLIT
        # -------------------------------------------------------
        log("[TRANSCRIPT] No segments → Fallback mode activated")

        # decode plain text (no timestamps)
        fallback_opts = whisper.DecodingOptions(
            language=lang,
            fp16=False,
            without_timestamps=True
        )
        res2 = model.decode(mel, fallback_opts)
        text = res2.text.strip()

        if not text:
            log("[TRANSCRIPT] Empty transcript in fallback!")
            return []

        # break into sentences
        raw_lines = [x.strip() for x in text.replace("\n", " ").split(".") if x.strip()]
        if not raw_lines:
            log("[TRANSCRIPT] Fallback sentences empty!")
            return []

        chunk = dur / max(1, len(raw_lines))
        ts = 0.0
        segments = []

        for line in raw_lines:
            end_ts = min(ts + chunk, dur)
            segments.append({
                "start": round(ts, 2),
                "end": round(end_ts, 2),
                "text": line
            })
            ts = end_ts

        log(f"[TRANSCRIPT] Fallback built {len(segments)} segments ✓ in {time.time()-t0:.2f}s")
        return segments

    except Exception as e:
        log("[TRANSCRIPT ERROR]", str(e))
        traceback.print_exc()
        return []

# =====================================================
# AUDIO ANALYSIS
# =====================================================
def analyze_audio(path):
    try:
        y, sr = librosa.load(path, sr=AUDIO_SR)
        rms = librosa.feature.rms(y=y, hop_length=AUDIO_HOP)[0]
        times = librosa.frames_to_time(
            np.arange(len(rms)),
            sr=sr,
            hop_length=AUDIO_HOP
        )
        return [{"time": float(t), "energy": float(r)} for t, r in zip(times, rms)]
    except Exception as e:
        log("[AUDIO ERROR]", e)
        return []


# =====================================================
# VISUAL ANALYSIS (SUPER FAST)
# =====================================================
def analyze_visual(path):
    try:
        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            return []

        fps = cap.get(cv2.CAP_PROP_FPS) or 25
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        step = max(1, int(fps / VISUAL_FPS))

        out = []
        prev = None
        for i in range(0, total, step):
            cap.set(cv2.CAP_PROP_POS_FRAMES, i)
            ok, f = cap.read()
            if not ok:
                break
            small = cv2.resize(f, VISUAL_RES)
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            if prev is not None:
                diff = cv2.absdiff(gray, prev)
                motion = diff.mean()
                out.append({"time": i / fps, "motion": float(motion)})
            prev = gray

        cap.release()
        return out
    except Exception as e:
        log("[VISUAL ERROR]", e)
        traceback.print_exc()
        return []
# =====================================================
# TEXT VIRALITY SCORE (AI LOGIC)
# =====================================================
def score_text(text: str) -> float:
    if not text:
        return 0.0

    t = text.lower()
    score = 0.0

    hooks = [
        "you won't believe", "listen", "watch this", "insane",
        "crazy", "viral", "life changing", "secret", "hack",
        "mistake", "stop scrolling", "shocking"
    ]
    for h in hooks:
        if h in t:
            score += 0.20

    if "?" in t: score += 0.07
    if "!" in t: score += 0.07

    positives = ["amazing", "incredible", "powerful", "best", "love"]
    negatives = ["terrible", "sad", "angry", "bad", "worst"]

    emo = sum(w in t for w in positives + negatives)
    score += min(0.18, emo * 0.05)

    length = len(t.split())
    if 4 <= length <= 18:
        score += 0.10

    common = {"the", "and", "to", "in", "is", "it"}
    uniq_ratio = 1 - sum(w in common for w in t.split()) / max(1, length)
    score += uniq_ratio * 0.08

    return min(1.0, score)


# =====================================================
# FUSE TEXT + AUDIO + MOTION
# =====================================================
def fuse(hook, audio, motion, text_len):
    a = min(1, audio / 0.12)
    m = min(1, motion / 20)
    h = min(1, hook)

    text_w = 0.6 if text_len > 10 else 0.45
    audio_w = 0.2
    motion_w = 1 - text_w - audio_w

    return float(text_w * h + audio_w * a + motion_w * m)


# =====================================================
# SILENCE BLOCK DETECTION
# =====================================================
def find_silence(audio_map, th=0.015, min_len=0.4):
    if not audio_map:
        return []

    s_start = None
    blocks = []
    for f in audio_map:
        if f["energy"] < th:
            if s_start is None:
                s_start = f["time"]
        else:
            if s_start is not None:
                if f["time"] - s_start >= min_len:
                    blocks.append((s_start, f["time"]))
                s_start = None

    if s_start is not None:
        blocks.append((s_start, audio_map[-1]["time"]))

    return blocks


# =====================================================
# CLIP BOUNDS
# =====================================================
def compute_bounds(start, end, a_avg, m_avg, silences, dur):
    peak = min((start + end) / 2, dur)

    base = 10 + a_avg * 6 + m_avg * 4
    base = max(MIN_CLIP, min(MAX_CLIP, base))

    s = max(0, peak - base / 2)
    e = min(dur, s + base)

    def is_silence(t):
        for ss, ee in silences:
            if ss - 0.3 < t < ee + 0.3:
                return True
        return False

    while is_silence(s) and s < e - MIN_CLIP:
        s += 0.2

    while is_silence(e) and e > s + MIN_CLIP:
        e -= 0.2

    if e - s < MIN_CLIP:
        e = min(dur, s + MIN_CLIP)

    return round(s, 2), round(e, 2)


# =====================================================
# MAIN VIRAL FINDER
# =====================================================
def find_viral_moments(path, top_k=5):
    log("\n🔥 [V26 ENGINE] Start full viral scan…")

    transcript = extract_transcript(path)
    if not transcript:
        return []

    dur = get_video_duration(path)
    audio = analyze_audio(path)
    silences = find_silence(audio)
    visual = analyze_visual(path)

    out = []

    for seg in transcript:
        text = seg["text"]
        s, e = seg["start"], seg["end"]

        hook = score_text(text)

        a_vals = [x["energy"] for x in audio if s <= x["time"] <= e]
        a_avg = float(np.mean(a_vals)) if a_vals else 0

        m_vals = [x["motion"] for x in visual if s <= x["time"] <= e]
        m_avg = float(np.mean(m_vals)) if m_vals else 0

        score = fuse(hook, a_avg, m_avg, len(text.split()))
        clip_s, clip_e = compute_bounds(s, e, a_avg, m_avg, silences, dur)

        out.append({
            "text": text,
            "start": clip_s,
            "end": clip_e,
            "hook": hook,
            "audio": a_avg,
            "motion": m_avg,
            "score": score
        })

    out.sort(key=lambda x: x["score"], reverse=True)
    log(f"[V26 ENGINE] DONE → {len(out[:top_k])} viral clips found ✓")
    return out[:top_k]
# =====================================================
# FACE CENTER
# =====================================================
def detect_face_center(video_path):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None

    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    mid = max(1, frames // 2)

    cap.set(cv2.CAP_PROP_POS_FRAMES, mid)
    ok, frame = cap.read()
    if not ok:
        return None

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    face = cv2.CascadeClassifier(cv2.data.haarcascades +
                                 "haarcascade_frontalface_default.xml")
    faces = face.detectMultiScale(gray, 1.15, 4)

    h, w = gray.shape
    if len(faces) == 0:
        return (w // 2, h // 2)

    x, y, fw, fh = max(faces, key=lambda f: f[2] * f[3])
    return (x + fw // 2, y + fh // 2)


# =====================================================
# COLOR GRADE LOOK (Preset B)
# =====================================================
def color_grade_B():
    return "eq=contrast=1.12:brightness=0.00:saturation=1.10,curves=preset=lighter"


# =====================================================
# SUBTITLE FILE CREATOR
# =====================================================
def write_ass(text, duration, out_path):
    with open(out_path, "w", encoding="utf8") as f:
        f.write(f"""[Script Info]
PlayResX: {TARGET_W}
PlayResY: {TARGET_H}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BorderStyle, Outline, Shadow, Alignment
Style: Main,Inter-Bold,62,&H00FFFFFF,&H00000000,1,4,0,2

[Events]
Format: Layer, Start, End, Style, Text
Dialogue: 0,0:00:00.00,0:00:{duration:.2f},Main,{text}
""")


# =====================================================
# RENDER ENGINE
# =====================================================
def render_clip(input_path, seg, out_path):
    s = seg["start"]
    e = seg["end"]
    dur = e - s
    text = seg["text"]

    with tempfile.TemporaryDirectory() as td:
        ass = os.path.join(td, "cap.ass")
        write_ass(text, dur, ass)

        trim = os.path.join(td, "trim.mp4")

        cmd_trim = [
            "ffmpeg", "-y",
            "-ss", str(s),
            "-i", input_path,
            "-t", str(dur),
            "-c", "copy",
            trim
        ]
        subprocess.run(cmd_trim, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        cx, cy = detect_face_center(trim) or (540, 960)

        w = TARGET_W
        h = TARGET_H

        color_filter = color_grade_B()

        vf = (
            f"scale=-1:{TARGET_H*1.2},"
            f"crop={TARGET_W}:{TARGET_H}:{cx}-{TARGET_W//2}:{cy}-{TARGET_H//2},"
            f"{color_filter},"
            f"subtitles='{ass}'"
        )

        attempts = [
            ["h264_nvenc", "nvenc"],
            ["libx264", "x264"]
        ]

        for codec, label in attempts:
            cmd = [
                "ffmpeg", "-y",
                "-i", trim,
                "-vf", vf,
                "-c:v", codec,
                "-b:v", BITRATE,
                "-c:a", "aac",
                "-b:a", AUDIO_BR,
                out_path
            ]
            p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if p.returncode == 0:
                return True

        return False
if __name__ == "__main__":
    video = "your_video.mp4"
    clips = find_viral_moments(video)

    Path("outputs").mkdir(exist_ok=True)

    for i, c in enumerate(clips):
        out_path = f"outputs/clip_{i}.mp4"
        print(f"[EDITOR] Rendering Clip {i} →", out_path)
        render_clip(video, c, out_path)
        print("DONE ✓")
