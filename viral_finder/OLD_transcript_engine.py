
"""
transcript_engine.py

Production-ready transcription engine for Hotshort (final, fast + trust).

Features
- Single public API: extract_transcript(...)
- Two modes: TRUST (simple, single-pass Whisper for maximal context/accuracy)
             and FAST (VAD + chunked faster-whisper for throughput)
- GPU auto-detect and safe fallbacks
- faster-whisper compatibility (generator vs tuple handling)
- VAD chunking using webrtcvad + pydub when available (graceful fallback)
- ThreadPoolExecutor with GPU-friendly worker throttling
- Simple file-level caching (hash + mtime) to avoid re-transcribing
- Streaming generator mode

Drop this file into viral_finder/transcript_engine.py (overwrite existing).
"""

from __future__ import annotations
import os
import sys
import math
import time
import json
import shutil
import hashlib
import tempfile
import subprocess
from typing import List, Dict, Generator, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

# Optional backends
try:
    import whisper
except Exception:
    whisper = None

try:
    from faster_whisper import WhisperModel as FasterWhisperModel
except Exception:
    FasterWhisperModel = None

try:
    import webrtcvad
except Exception:
    webrtcvad = None

try:
    from pydub import AudioSegment
except Exception:
    AudioSegment = None

try:
    import numpy as np
except Exception:
    np = None

try:
    import torch
except Exception:
    torch = None

# lightweight progress bar if available
try:
    from tqdm import tqdm
except Exception:
    def tqdm(x, **k):
        return x

# -----------------------
# Config knobs (tweakable)
# -----------------------
DEFAULT_MODEL = os.environ.get("HS_TRANSCRIPT_MODEL", "base")
DEFAULT_PRETEND_GPU = True
CHUNK_PADDING_S = 0.22
VAD_AGGRESSIVENESS = 1
MIN_CHUNK_DURATION = 0.8
MAX_CHUNK_DURATION = 30.0
CPU_WORKER_FACTOR = 0.6  # fraction of cores to use
CACHE_DIR = os.environ.get("HS_TRANSCRIPT_CACHE", ".hotshort_transcripts_cache")
LOG_LEVEL = os.environ.get("HS_LOG_LEVEL", "INFO").upper()

# model cache
_MODEL_CACHE: Dict[Tuple[str, str], Tuple[str, object, str]] = {}

# -----------------------
# Logging helper
# -----------------------

def _log(level: str, *args):
    levels = ["DEBUG", "INFO", "WARN", "ERROR"]
    if levels.index(level) >= levels.index(LOG_LEVEL):
        print(f"[{level}]", *args)

# -----------------------
# Utilities
# -----------------------

def resolve_device(prefer_gpu: bool = DEFAULT_PRETEND_GPU) -> str:
    try:
        if prefer_gpu and torch is not None and torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


def ensure_ffmpeg() -> bool:
    for cmd in ("ffprobe", "ffmpeg"):
        if shutil.which(cmd) is None:
            return False
    return True


def get_audio_duration(path: str) -> float:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return float(out.stdout.strip())
    except Exception:
        if AudioSegment:
            seg = AudioSegment.from_file(path)
            return len(seg) / 1000.0
        return 0.0


def _ensure_cache_dir():
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR, exist_ok=True)


def _file_fingerprint(path: str) -> str:
    st = os.stat(path)
    key = f"{path}:{st.st_mtime_ns}:{st.st_size}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


def _cache_path_for(path: str) -> str:
    _ensure_cache_dir()
    return os.path.join(CACHE_DIR, _file_fingerprint(path) + ".json")

# -----------------------
# Model loader
# -----------------------

def load_whisper_model(model_name: str = DEFAULT_MODEL, prefer_gpu: bool = DEFAULT_PRETEND_GPU):
    device = resolve_device(prefer_gpu)
    key = (model_name, device)
    if key in _MODEL_CACHE:
        return _MODEL_CACHE[key]

    # try faster-whisper first
    if FasterWhisperModel is not None:
        try:
            _log("INFO", f"Loading faster-whisper '{model_name}' on {device}")
            compute_type = "float16" if device == "cuda" else "int8"
            model = FasterWhisperModel(model_name, device=device, compute_type=compute_type)
            _MODEL_CACHE[key] = ("faster", model, device)
            return _MODEL_CACHE[key]
        except Exception as e:
            _log("WARN", "faster-whisper load failed:", e)

    # try openai whisper
    if whisper is not None:
        try:
            _log("INFO", f"Loading openai whisper '{model_name}' on {device}")
            m = whisper.load_model(model_name, device=device)
            _MODEL_CACHE[key] = ("whisper", m, device)
            return _MODEL_CACHE[key]
        except Exception as e:
            _log("WARN", "openai whisper load failed:", e)

    # last fallback: cpu whisper
    if whisper is not None:
        try:
            _log("INFO", f"Loading openai whisper '{model_name}' on cpu (fallback)")
            m = whisper.load_model(model_name, device="cpu")
            _MODEL_CACHE[(model_name, "cpu")] = ("whisper", m, "cpu")
            return _MODEL_CACHE[(model_name, "cpu")]
        except Exception as e:
            _log("ERROR", "Final load failed:", e)

    raise RuntimeError("No available whisper backend. Install 'whisper' or 'faster-whisper'.")

# -----------------------
# VAD chunking
# -----------------------

def _frame_generator(chunk_duration_ms: int, audio: bytes, sample_rate: int):
    n = int(sample_rate * (chunk_duration_ms / 1000.0) * 2)
    offset = 0
    while offset + n <= len(audio):
        yield audio[offset:offset + n]
        offset += n


def vad_chunk_audio(input_path: str, aggressiveness: int = VAD_AGGRESSIVENESS, sample_rate: int = 16000) -> List[Dict]:
    if not AudioSegment or not webrtcvad or not ensure_ffmpeg():
        dur = get_audio_duration(input_path)
        return [{"start": 0.0, "end": dur}]

    audio = AudioSegment.from_file(input_path).set_frame_rate(sample_rate).set_channels(1).set_sample_width(2)
    raw = audio.raw_data
    vad = webrtcvad.Vad(max(0, min(3, aggressiveness)))
    frame_ms = 30
    frames = list(_frame_generator(frame_ms, raw, sample_rate))

    segments = []
    triggered = False
    cur_start_ms = 0

    for i, f in enumerate(frames):
        try:
            is_speech = vad.is_speech(f, sample_rate)
        except Exception:
            is_speech = False
        if is_speech and not triggered:
            triggered = True
            cur_start_ms = i * frame_ms
        elif not is_speech and triggered:
            end_ms = i * frame_ms
            segments.append((cur_start_ms / 1000.0, end_ms / 1000.0))
            triggered = False

    if triggered:
        segments.append((cur_start_ms / 1000.0, len(frames) * frame_ms / 1000.0))

    # merge and filter
    merged = []
    for s, e in segments:
        if e - s < MIN_CHUNK_DURATION:
            continue
        if merged and s <= merged[-1][1] + 0.2:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))

    final = []
    total_dur = get_audio_duration(input_path)
    for s, e in merged:
        span = e - s
        if span <= MAX_CHUNK_DURATION:
            final.append({"start": max(0.0, s - CHUNK_PADDING_S), "end": min(total_dur, e + CHUNK_PADDING_S)})
        else:
            parts = int(math.ceil(span / MAX_CHUNK_DURATION))
            for i in range(parts):
                sub_s = s + i * MAX_CHUNK_DURATION
                sub_e = min(e, s + (i + 1) * MAX_CHUNK_DURATION)
                final.append({"start": max(0.0, sub_s - CHUNK_PADDING_S), "end": min(total_dur, sub_e + CHUNK_PADDING_S)})

    if not final:
        return [{"start": 0.0, "end": total_dur}]
    return final

# -----------------------
# Chunk transcribe helper (faster-whisper generator aware)
# -----------------------

def _transcribe_chunk_with_backend(backend_tuple, path: str, start: float, end: float) -> List[Dict]:
    typ, model, device = backend_tuple
    tmpdir = tempfile.mkdtemp(prefix="trans_chunk_")
    tmpfile = os.path.join(tmpdir, "seg.wav")

    try:
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-ss", str(max(0.0, start)), "-to", str(end),
            "-i", path, "-ar", "16000", "-ac", "1", "-f", "wav", tmpfile
        ]
        subprocess.run(cmd, check=True)

        # prefer faster-whisper path (generator or tuple)
        segments_out: List[Dict] = []

        if typ == "faster":
            # faster-whisper returns (segments_gen, info) OR generator-like depending on version
            res = model.transcribe(tmpfile, beam_size=1, vad_filter=False)
            # normalize: res may be tuple (seg_gen, info) or seg_gen
            if isinstance(res, tuple) and len(res) >= 1:
                seg_gen = res[0]
            else:
                seg_gen = res

            for seg in seg_gen:
                # seg has attributes start, end, text
                segments_out.append({
                    "start": float(seg.start) + start,
                    "end": float(seg.end) + start,
                    "text": seg.text.strip()
                })
            return segments_out

        elif typ == "whisper":
            # openai whisper (single chunk)
            result = model.transcribe(tmpfile, fp16=(device == "cuda"), verbose=False, condition_on_previous_text=False)
            for s in result.get("segments", []):
                segments_out.append({
                    "start": float(s["start"]) + start,
                    "end": float(s["end"]) + start,
                    "text": s["text"].strip()
                })
            return segments_out

        else:
            return []

    finally:
        try:
            shutil.rmtree(tmpdir)
        except Exception:
            pass

# -----------------------
# Simple trusted single-pass engine (preserves full context)
# -----------------------

def simple_transcribe(path: str, model_name: str = DEFAULT_MODEL, prefer_gpu: bool = DEFAULT_PRETEND_GPU,
                      min_text_len: int = 3, max_pause: float = 6.0) -> List[Dict]:
    """Single-pass transcription (trust mode). Keeps Whisper's internal context.
    Prefers openai whisper for best continuity; falls back to faster-whisper single-file mode.
    """
    _log("INFO", "[TRANSCRIPT] Starting simple_transcribe...")
    backend = load_whisper_model(model_name, prefer_gpu=prefer_gpu)
    typ, model, device = backend

    if typ == "whisper":
        # openai whisper: use its native transcribe
        result = model.transcribe(path, fp16=(device == "cuda"), verbose=False, condition_on_previous_text=True)
        segs = result.get("segments", [])
        cleaned = []
        prev_end = 0.0
        for seg in segs:
            text = seg.get("text", "").strip()
            if len(text) < min_text_len:
                continue
            start = float(seg.get("start", 0.0))
            end = float(seg.get("end", start + 0.01))
            pause_before = min(max(0.0, start - prev_end), max_pause)
            cleaned.append({"start": round(start, 2), "end": round(end, 2), "text": text, "pause_before": round(pause_before, 2)})
            prev_end = end
        _log("INFO", f"[TRANSCRIPT] ✅ Produced {len(cleaned)} clean segments (simple)")
        return cleaned

    else:
        # faster-whisper in single-file mode: consume whole-file generator
        res = model.transcribe(path, beam_size=1, vad_filter=False)
        if isinstance(res, tuple) and len(res) >= 1:
            seg_gen = res[0]
        else:
            seg_gen = res
        cleaned = []
        prev_end = 0.0
        for seg in seg_gen:
            text = getattr(seg, "text", "").strip()
            if len(text) < min_text_len:
                continue
            start = float(getattr(seg, "start", 0.0))
            end = float(getattr(seg, "end", start + 0.01))
            pause_before = min(max(0.0, start - prev_end), max_pause)
            cleaned.append({"start": round(start, 2), "end": round(end, 2), "text": text, "pause_before": round(pause_before, 2)})
            prev_end = end
        _log("INFO", f"[TRANSCRIPT] ✅ Produced {len(cleaned)} clean segments (simple-faster)")
        return cleaned

# -----------------------
# Fast chunked engine (VAD + parallel)
# -----------------------

def transcribe_file(path: str, model_name: str = DEFAULT_MODEL, prefer_gpu: bool = DEFAULT_PRETEND_GPU,
                    use_vad: bool = True, max_workers: Optional[int] = None) -> List[Dict]:
    _log("INFO", "[TRANSCRIPT] Starting transcribe_file (fast mode)")
    if not ensure_ffmpeg():
        raise RuntimeError("ffmpeg/ffprobe not found on PATH. Install ffmpeg.")

    backend = load_whisper_model(model_name, prefer_gpu=prefer_gpu)
    typ, model, device = backend

    duration = get_audio_duration(path)
    chunks = vad_chunk_audio(path) if use_vad else [{"start": 0.0, "end": duration}]

    if max_workers is None:
        cpu_count = max(1, os.cpu_count() or 2)
        max_workers = max(1, int(cpu_count * CPU_WORKER_FACTOR))

    # GPU throttle: don't spawn many workers on GPU
    if device == "cuda":
        max_workers = min(2, max_workers)

    results: List[Dict] = []
    futures_map = {}

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for c in chunks:
            fut = ex.submit(_transcribe_chunk_with_backend, backend, path, c["start"], c["end"])
            futures_map[fut] = c

        for fut in tqdm(as_completed(futures_map), total=len(futures_map), desc="transcribing chunks"):
            try:
                segs = fut.result()
                results.extend(segs)
            except Exception as e:
                _log("WARN", "[TRANSCRIPT] chunk failed:", e)

    # stitch & normalize
    results.sort(key=lambda x: x["start"])
    cleaned: List[Dict] = []
    for s in results:
        text = (s.get("text") or "").strip()
        if not text:
            continue
        if cleaned and s["start"] <= cleaned[-1]["end"] + 0.12:
            cleaned[-1]["end"] = max(cleaned[-1]["end"], s["end"])
            cleaned[-1]["text"] = (cleaned[-1]["text"] + " " + text).strip()
        else:
            cleaned.append({"start": round(s["start"], 2), "end": round(s["end"], 2), "text": text})

    # small post-filter
    final: List[Dict] = []
    for seg in cleaned:
        if len(seg["text"].split()) < 1:
            continue
        final.append(seg)

    _log("INFO", f"[TRANSCRIPT] ✅ transcribe_file done, segments={len(final)}")
    return final

# -----------------------
# Public API: decide which engine to use and cache
# -----------------------

def extract_transcript(path: str, model_name: str = DEFAULT_MODEL, prefer_gpu: bool = DEFAULT_PRETEND_GPU,
                       use_vad: bool = True, force_recompute: bool = False, prefer_trust: bool = True) -> List[Dict]:
    """Primary public API.

    - prefer_trust=True => prefer simple single-pass engine (recommended for short/creator clips)
    - set prefer_trust=False to force fast chunked engine
    - function caches JSON results per file unless force_recompute=True
    """
    cache_file = _cache_path_for(path)
    if not force_recompute and os.path.exists(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                _log("INFO", f"[TRANSCRIPT] cache hit -> {cache_file}")
                return data.get("segments", [])
        except Exception:
            _log("DEBUG", "[TRANSCRIPT] cache read failed, recomputing")

    duration = get_audio_duration(path)
    use_fast = not prefer_trust or duration > 300  # long files -> prefer fast

    try:
        if use_fast:
            segs = transcribe_file(path, model_name=model_name, prefer_gpu=prefer_gpu, use_vad=use_vad)
        else:
            segs = simple_transcribe(path, model_name=model_name, prefer_gpu=prefer_gpu)

        # persist cache
        try:
            _ensure_cache_dir()
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump({"segments": segs, "meta": {"duration": duration, "model": model_name}}, f)
        except Exception:
            _log("DEBUG", "[TRANSCRIPT] cache write failed")

        return segs
    except Exception as e:
        _log("ERROR", "[TRANSCRIPT] extract_transcript failed:", e)
        return []

# -----------------------
# Streaming generator
# -----------------------

def stream_transcribe(path: str, model_name: str = DEFAULT_MODEL, prefer_gpu: bool = DEFAULT_PRETEND_GPU,
                      chunk_size_s: float = 15.0) -> Generator[Dict, None, None]:
    backend = load_whisper_model(model_name, prefer_gpu=prefer_gpu)
    duration = get_audio_duration(path)
    start = 0.0
    while start < duration:
        end = min(duration, start + chunk_size_s)
        for s in _transcribe_chunk_with_backend(backend, path, start, end):
            yield s
        start = end

# -----------------------
# Backwards compat alias
# -----------------------
transcribe_file_alias = transcribe_file

# -----------------------
# Warmup
# -----------------------

def warmup(model_name: str = DEFAULT_MODEL, prefer_gpu: bool = DEFAULT_PRETEND_GPU):
    _log("INFO", "[TRANSCRIPT] Warmup: loading model...")
    load_whisper_model(model_name, prefer_gpu=prefer_gpu)
    _log("INFO", "[TRANSCRIPT] Warmup done.")

# -----------------------
# CLI
# -----------------------
if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("file", help="audio/video file")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--gpu", action="store_true")
    p.add_argument("--no-vad", action="store_true")
    p.add_argument("--force", action="store_true")
    args = p.parse_args()

    warmup(args.model, prefer_gpu=args.gpu)
    segs = extract_transcript(args.file, model_name=args.model, prefer_gpu=args.gpu, use_vad=not args.no_vad, force_recompute=args.force)
    print("Segments:", len(segs))
    for s in segs[:200]:
        print(f"{s['start']:.2f}-{s['end']:.2f}: {s['text']}")
