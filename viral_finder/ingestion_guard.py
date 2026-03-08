from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
import time
import wave
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional, Tuple

try:
    import numpy as np
except Exception:
    np = None


@dataclass
class CanonicalMediaObject:
    video_path: str
    audio_path: str
    duration: float
    resolution: Optional[Tuple[int, int]]
    bitrate: Optional[float]
    transcript_status: str
    acquisition_quality_score: float
    audio_integrity_score: float
    transcript_integrity_score: float
    acquisition_attempts: List[Dict]


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(x or 0.0)))


def _mean(vals: List[float]) -> float:
    if not vals:
        return 0.0
    return float(sum(vals)) / float(len(vals))


def _percentile(vals: List[float], q: float) -> float:
    if not vals:
        return 0.0
    arr = sorted(float(v or 0.0) for v in vals)
    if len(arr) == 1:
        return arr[0]
    pos = (len(arr) - 1) * _clip(q, 0.0, 100.0) / 100.0
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return arr[lo]
    w = pos - lo
    return arr[lo] + (arr[hi] - arr[lo]) * w


def probe_media(path: str) -> Dict:
    if not path or not os.path.exists(path):
        return {
            "ok": False,
            "duration": 0.0,
            "width": None,
            "height": None,
            "bit_rate": None,
            "audio_streams": 0,
            "video_streams": 0,
            "vcodec": None,
            "acodec": None,
        }
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration,bit_rate:stream=codec_type,codec_name,width,height",
        "-of",
        "json",
        path,
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, check=True)
        payload = json.loads(out.stdout or "{}")
    except Exception:
        return {
            "ok": False,
            "duration": 0.0,
            "width": None,
            "height": None,
            "bit_rate": None,
            "audio_streams": 0,
            "video_streams": 0,
            "vcodec": None,
            "acodec": None,
        }

    streams = payload.get("streams") or []
    fmt = payload.get("format") or {}
    width = None
    height = None
    vcodec = None
    acodec = None
    audio_streams = 0
    video_streams = 0
    for s in streams:
        ctype = str(s.get("codec_type") or "").lower()
        if ctype == "video":
            video_streams += 1
            width = int(s.get("width") or 0) or width
            height = int(s.get("height") or 0) or height
            vcodec = s.get("codec_name") or vcodec
        elif ctype == "audio":
            audio_streams += 1
            acodec = s.get("codec_name") or acodec

    try:
        duration = float(fmt.get("duration") or 0.0)
    except Exception:
        duration = 0.0
    try:
        bit_rate = float(fmt.get("bit_rate") or 0.0)
    except Exception:
        bit_rate = 0.0
    return {
        "ok": True,
        "duration": duration,
        "width": width,
        "height": height,
        "bit_rate": bit_rate if bit_rate > 0 else None,
        "audio_streams": audio_streams,
        "video_streams": video_streams,
        "vcodec": vcodec,
        "acodec": acodec,
    }


def score_acquisition(
    media_probe: Dict,
    expected_duration: Optional[float],
    metadata_duration: Optional[float],
    file_size_bytes: int,
) -> Tuple[float, Dict]:
    dur = float(media_probe.get("duration") or 0.0)
    expected = float(expected_duration or 0.0)
    meta_dur = float(metadata_duration or 0.0)
    audio_ok = 1.0 if int(media_probe.get("audio_streams") or 0) > 0 else 0.0
    video_ok = 1.0 if int(media_probe.get("video_streams") or 0) > 0 else 0.0
    codec_ok = 1.0 if media_probe.get("acodec") else 0.0
    size_mb = float(file_size_bytes or 0) / (1024.0 * 1024.0)
    size_ok = 1.0 if size_mb >= 0.6 else _clip(size_mb / 0.6, 0.0, 1.0)

    dur_match = 0.0
    if expected > 0.0:
        ratio = _clip(dur / expected, 0.0, 2.0)
        dur_match = 1.0 - abs(1.0 - ratio)
        dur_match = _clip(dur_match, 0.0, 1.0)
    elif meta_dur > 0.0:
        ratio = _clip(dur / meta_dur, 0.0, 2.0)
        dur_match = _clip(1.0 - abs(1.0 - ratio), 0.0, 1.0)

    resolution_ok = 1.0 if (media_probe.get("width") and media_probe.get("height")) else 0.0
    score = (
        0.33 * dur_match
        + 0.22 * audio_ok
        + 0.12 * video_ok
        + 0.10 * codec_ok
        + 0.13 * size_ok
        + 0.10 * resolution_ok
    )
    components = {
        "duration_match": round(dur_match, 4),
        "audio_presence": round(audio_ok, 4),
        "video_presence": round(video_ok, 4),
        "codec_consistency": round(codec_ok, 4),
        "size_completeness": round(size_ok, 4),
        "resolution_completeness": round(resolution_ok, 4),
    }
    return _clip(score, 0.0, 1.0), components


def analyze_audio_integrity(wav_path: str) -> Dict:
    if not wav_path or not os.path.exists(wav_path):
        return {
            "ok": False,
            "audio_integrity_score": 0.0,
            "silence_ratio": 1.0,
            "snr_estimate_db": 0.0,
            "clipping_ratio": 1.0,
            "rms_p10": 0.0,
            "rms_p90": 0.0,
            "spectral_flatness": 1.0,
        }
    try:
        with wave.open(wav_path, "rb") as wf:
            n = wf.getnframes()
            channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            fr = wf.getframerate()
            raw = wf.readframes(n)
    except Exception:
        return {
            "ok": False,
            "audio_integrity_score": 0.0,
            "silence_ratio": 1.0,
            "snr_estimate_db": 0.0,
            "clipping_ratio": 1.0,
            "rms_p10": 0.0,
            "rms_p90": 0.0,
            "spectral_flatness": 1.0,
        }

    if np is None or sampwidth != 2:
        # Conservative fallback when numpy is missing or unexpected PCM format.
        return {
            "ok": True,
            "audio_integrity_score": 0.55,
            "silence_ratio": 0.5,
            "snr_estimate_db": 8.0,
            "clipping_ratio": 0.0,
            "rms_p10": 0.0,
            "rms_p90": 0.0,
            "spectral_flatness": 0.5,
            "sample_rate": fr,
            "channels": channels,
        }

    arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32)  # type: ignore[arg-type]
    if channels > 1:
        arr = arr.reshape(-1, channels).mean(axis=1)
    arr = arr / 32768.0
    if arr.size == 0:
        return {
            "ok": False,
            "audio_integrity_score": 0.0,
            "silence_ratio": 1.0,
            "snr_estimate_db": 0.0,
            "clipping_ratio": 1.0,
            "rms_p10": 0.0,
            "rms_p90": 0.0,
            "spectral_flatness": 1.0,
            "sample_rate": fr,
            "channels": channels,
        }

    frame_len = max(1, int(0.02 * max(1, fr)))
    use = (arr.size // frame_len) * frame_len
    framed = arr[:use].reshape(-1, frame_len) if use > 0 else arr.reshape(1, -1)
    rms = np.sqrt(np.mean(np.square(framed), axis=1) + 1e-12)  # type: ignore[arg-type]
    p10 = float(np.percentile(rms, 10))
    p90 = float(np.percentile(rms, 90))
    silence_ratio = float(np.mean(rms < max(0.003, p10 * 1.15)))
    clipping_ratio = float(np.mean(np.abs(arr) >= 0.985))

    signal_power = float(np.mean(np.square(arr)) + 1e-12)
    noise_floor = float(np.mean(np.square(arr[np.abs(arr) < max(0.01, p10 * 2.2)])) + 1e-12)
    snr_db = 10.0 * math.log10(max(1e-12, signal_power / max(1e-12, noise_floor)))

    # Approx spectral flatness via magnitude spectrum geometric/arithmetic mean.
    # Use a small sample for efficiency.
    sample = arr[: min(arr.size, fr * 12)]
    if sample.size < 64:
        flatness = 1.0
    else:
        fft = np.abs(np.fft.rfft(sample)) + 1e-12  # type: ignore[arg-type]
        geom = float(np.exp(np.mean(np.log(fft))))
        arith = float(np.mean(fft))
        flatness = float(geom / max(1e-12, arith))

    score = (
        0.28 * _clip((p90 - p10) / 0.12, 0.0, 1.0)
        + 0.24 * _clip((snr_db - 4.0) / 18.0, 0.0, 1.0)
        + 0.20 * (1.0 - _clip(silence_ratio / 0.92, 0.0, 1.0))
        + 0.14 * (1.0 - _clip(clipping_ratio / 0.04, 0.0, 1.0))
        + 0.14 * (1.0 - _clip(flatness / 0.98, 0.0, 1.0))
    )
    return {
        "ok": True,
        "audio_integrity_score": _clip(score, 0.0, 1.0),
        "silence_ratio": _clip(silence_ratio, 0.0, 1.0),
        "snr_estimate_db": round(float(snr_db), 3),
        "clipping_ratio": _clip(clipping_ratio, 0.0, 1.0),
        "rms_p10": round(float(p10), 6),
        "rms_p90": round(float(p90), 6),
        "spectral_flatness": _clip(flatness, 0.0, 1.0),
        "sample_rate": fr,
        "channels": channels,
    }


def compute_vad_removed_ratio(duration_s: float, transcript_segments: List[Dict]) -> float:
    if duration_s <= 0 or not transcript_segments:
        return 1.0
    spans: List[Tuple[float, float]] = []
    for seg in transcript_segments:
        try:
            s = float(seg.get("start", 0.0))
            e = float(seg.get("end", s))
        except Exception:
            continue
        if e > s:
            spans.append((s, e))
    if not spans:
        return 1.0
    spans.sort(key=lambda x: x[0])
    covered = 0.0
    cur_s, cur_e = spans[0]
    for s, e in spans[1:]:
        if s <= cur_e:
            cur_e = max(cur_e, e)
        else:
            covered += (cur_e - cur_s)
            cur_s, cur_e = s, e
    covered += (cur_e - cur_s)
    removed = max(0.0, float(duration_s) - float(covered))
    return _clip(removed / max(0.01, float(duration_s)), 0.0, 1.0)


def analyze_transcript_integrity(transcript_segments: List[Dict], expected_duration: Optional[float]) -> Dict:
    segs = transcript_segments or []
    texts: List[str] = []
    starts: List[float] = []
    ends: List[float] = []
    for seg in segs:
        try:
            s = float(seg.get("start", 0.0))
            e = float(seg.get("end", s))
        except Exception:
            continue
        txt = str(seg.get("text", "") or "").strip()
        if e > s:
            starts.append(s)
            ends.append(e)
            texts.append(txt)

    n = len(texts)
    if n == 0:
        return {
            "ok": False,
            "transcript_integrity_score": 0.0,
            "segment_count": 0,
            "avg_words_per_segment": 0.0,
            "sentence_boundary_density": 0.0,
            "repetition_rate": 1.0,
            "truncation_risk": 1.0,
            "language_consistency": 0.0,
        }

    words = [re.findall(r"\w+", t.lower()) for t in texts]
    word_counts = [len(w) for w in words]
    avg_w = _mean([float(x) for x in word_counts])
    punct_hits = sum(1 for t in texts if t.endswith((".", "!", "?")) or "?" in t or "!" in t)
    boundary_density = float(punct_hits) / float(max(1, n))

    uniq = set(t.lower() for t in texts if t)
    repetition_rate = 1.0 - (float(len(uniq)) / float(max(1, n)))

    expected = float(expected_duration or 0.0)
    truncation_risk = 0.0
    if expected > 0.0 and ends:
        covered = max(ends) - min(starts)
        ratio = _clip(covered / max(0.01, expected), 0.0, 1.5)
        truncation_risk = _clip(1.0 - ratio, 0.0, 1.0)

    # Lightweight language consistency: script consistency and unicode class stability.
    latin_chars = 0
    nonlatin_chars = 0
    for t in texts:
        for ch in t:
            if ch.isalpha():
                if "a" <= ch.lower() <= "z":
                    latin_chars += 1
                else:
                    nonlatin_chars += 1
    total_alpha = latin_chars + nonlatin_chars
    if total_alpha == 0:
        lang_consistency = 0.5
    else:
        dominant = max(latin_chars, nonlatin_chars) / float(total_alpha)
        lang_consistency = _clip(dominant, 0.0, 1.0)

    score = (
        0.20 * _clip(avg_w / 8.0, 0.0, 1.0)
        + 0.20 * _clip(boundary_density / 0.75, 0.0, 1.0)
        + 0.18 * (1.0 - _clip(repetition_rate / 0.65, 0.0, 1.0))
        + 0.22 * (1.0 - truncation_risk)
        + 0.20 * lang_consistency
    )
    return {
        "ok": True,
        "transcript_integrity_score": _clip(score, 0.0, 1.0),
        "segment_count": n,
        "avg_words_per_segment": round(avg_w, 3),
        "sentence_boundary_density": round(boundary_density, 4),
        "repetition_rate": round(repetition_rate, 4),
        "truncation_risk": round(truncation_risk, 4),
        "language_consistency": round(lang_consistency, 4),
    }


def ingestion_cache_key(source: str) -> str:
    return hashlib.sha1(str(source or "").encode("utf-8")).hexdigest()


def load_ingestion_cache(cache_dir: str, source_key: str, max_age_s: float = 86400.0) -> Optional[Dict]:
    os.makedirs(cache_dir, exist_ok=True)
    p = os.path.join(cache_dir, f"{source_key}.json")
    if not os.path.exists(p):
        return None
    try:
        st = os.stat(p)
        if (time.time() - float(st.st_mtime)) > float(max_age_s):
            return None
    except Exception:
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_ingestion_cache(cache_dir: str, source_key: str, payload: Dict) -> None:
    os.makedirs(cache_dir, exist_ok=True)
    p = os.path.join(cache_dir, f"{source_key}.json")
    tmp = tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", dir=cache_dir, suffix=".tmp")
    try:
        with tmp as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp.name, p)
    except Exception:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass


def canonical_to_dict(obj: CanonicalMediaObject) -> Dict:
    d = asdict(obj)
    if obj.resolution is not None:
        d["resolution"] = [int(obj.resolution[0]), int(obj.resolution[1])]
    return d

