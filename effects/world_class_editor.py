import json
import logging
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
import uuid
import threading
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple, Union

@dataclass
class DirectorSegment:
    start_t: float
    end_t: float
    mode: str
    active_speaker: str
    crop_x: float
    left_x: float
    right_x: float

# Global semaphore to ensure only one GPU encode runs at a time (e.g. for GTX 1630)
_GPU_SEMAPHORE = threading.Semaphore(1)

try:
    import cv2
except Exception:
    cv2 = None

try:
    import mediapipe as mp
except Exception:
    mp = None

try:
    from transformers import pipeline as hf_pipeline
except Exception:
    hf_pipeline = None

# Fallback fonts dir for local Windows testing vs Linux RunPod
if os.path.exists("./fonts"):
    _FONTS_DIR = os.environ.get("HS_FONTS_DIR", os.path.abspath("./fonts"))
else:
    _FONTS_DIR = os.environ.get("HS_FONTS_DIR", "/usr/share/fonts/truetype/montserrat")

log = logging.getLogger("world_class_editor")

# Font directory: matches the COPY path in Dockerfile.worker.
# On the NVIDIA container, fontconfig may not index these correctly,
# so we pass this path directly to libass via the fontsdir= parameter.
_FONTS_DIR = os.environ.get(
    "HS_FONTS_DIR",
    "/usr/share/fonts/truetype/montserrat",
)


def _nvenc_available() -> bool:
    """Probe once whether h264_nvenc is usable on this system."""
    if not hasattr(_nvenc_available, "_cached"):
        try:
            r = subprocess.run(
                ["ffmpeg", "-hide_banner", "-f", "lavfi", "-i",
                 "nullsrc=s=64x64:d=0.1", "-c:v", "h264_nvenc",
                 "-f", "null", "-"],
                capture_output=True, timeout=10,
            )
            _nvenc_available._cached = r.returncode == 0
        except Exception:
            _nvenc_available._cached = False
        log.info("[WCE] NVENC available: %s", _nvenc_available._cached)
    return _nvenc_available._cached


def _nvdec_available() -> bool:
    """Probe once whether NVDEC (cuvid GPU decode) is usable on this system.

    Uses h264_cuvid decoder which maps to NVDEC hardware on any NVIDIA GPU.
    Falls back to False silently so all callers can safely gate on this.
    """
    if not hasattr(_nvdec_available, "_cached"):
        try:
            # Create a tiny H.264 test file in memory via nullsrc + libx264,
            # then try to decode it with h264_cuvid.
            enc = subprocess.run(
                ["ffmpeg", "-hide_banner", "-f", "lavfi", "-i",
                 "nullsrc=s=64x64:d=0.1", "-c:v", "libx264",
                 "-f", "h264", "-"],
                capture_output=True, timeout=10,
            )
            if enc.returncode != 0 or not enc.stdout:
                raise RuntimeError("Could not encode test stream")
            dec = subprocess.run(
                ["ffmpeg", "-hide_banner",
                 "-c:v", "h264_cuvid",
                 "-f", "h264", "-i", "pipe:0",
                 "-f", "null", "-"],
                input=enc.stdout, capture_output=True, timeout=10,
            )
            _nvdec_available._cached = dec.returncode == 0
        except Exception:
            _nvdec_available._cached = False
        log.info("[WCE] NVDEC available: %s", _nvdec_available._cached)
    return _nvdec_available._cached


def _hwaccel_decode_args() -> List[str]:
    """Return FFmpeg args to enable GPU (NVDEC/CUDA) decode when available.

    These args go BEFORE -i in the FFmpeg command.
    With these args FFmpeg decodes on GPU (NVDEC) and passes frames to CPU
    filters as usual — fully transparent to the rest of the filter graph.
    When NVDEC is unavailable, returns [] (pure CPU decode as before).

    GPU decode pipeline benefit:
      - Decode on NVDEC → CPU barely touches encoded bitstream
      - Filters run on CPU (crop, scale, eq, subtitles — no CUDA filters needed)
      - NVENC encodes output → GPU re-compresses final output
      Net: CPU load drops ~40-60% on a typical 30s clip encode pass.
    """
    if _nvdec_available():
        return ["-hwaccel", "cuda", "-hwaccel_output_format", "nv12"]
    return []



def _get_export_crf(default: int = 20) -> int:
    """Read CRF from env: HS_EXPORT_CRF (default 20)."""
    try:
        return int(os.environ.get("HS_EXPORT_CRF", str(default)))
    except (ValueError, TypeError):
        return default


def _get_export_preset(default: str = "veryfast") -> str:
    """Read FFmpeg preset from env: HS_EXPORT_PRESET (default veryfast)."""
    return os.environ.get("HS_EXPORT_PRESET", default).strip() or default


def _get_export_maxrate() -> str:
    return os.environ.get("HS_EXPORT_MAXRATE", "8000k").strip() or "8000k"


def _get_export_bufsize() -> str:
    return os.environ.get("HS_EXPORT_BUFSIZE", "16000k").strip() or "16000k"


def _get_export_audio_bitrate() -> str:
    return os.environ.get("HS_EXPORT_AUDIO_BITRATE", "128k").strip() or "128k"


def _video_encode_args(crf: int = 20, preset: str = "veryfast") -> List[str]:
    """Return encoder args driven by env vars (HS_EXPORT_*). NVENC if available, else libx264."""
    _crf = _get_export_crf(default=crf)
    _preset = _get_export_preset(default=preset)
    _maxrate = _get_export_maxrate()
    _bufsize = _get_export_bufsize()

    log.info(f"[WCE-VISUAL] export_quality crf={_crf} maxrate={_maxrate}")

    if _nvenc_available():
        return [
            "-c:v", "h264_nvenc",
            "-preset", "p3",
            "-tune", "hq",
            "-profile:v", "high",
            "-rc", "vbr",
            "-cq", str(_crf),
            "-b:v", "3M",
            "-maxrate", _maxrate,
            "-bufsize", _bufsize,
            "-pix_fmt", "yuv420p",
        ]
    # CPU fallback (libx264)
    return [
        "-c:v", "libx264",
        "-preset", _preset,
        "-crf", str(_crf),
        "-maxrate", _maxrate,
        "-bufsize", _bufsize,
        "-pix_fmt", "yuv420p",
    ]


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[a-zA-Z0-9']+", (text or "").lower())


def _ass_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    sec = seconds % 60
    centiseconds = int(round((sec - int(sec)) * 100))
    return f"{hours}:{minutes:02d}:{int(sec):02d}.{centiseconds:02d}"


def _ass_escape(text: str) -> str:
    t = (text or "").replace("\\", r"\\")
    t = t.replace("{", r"\{").replace("}", r"\}")
    t = t.replace("\n", r"\N")
    return t


def _ffmpeg_filter_path(path_value: str) -> str:
    """Escape a filesystem path for use inside an FFmpeg libass filter expression.

    libass requires:  \\ for backslash, \: for colon, \' for apostrophe,
    \[ and \] for brackets.  We also normalise Windows backslashes to
    forward slashes so the same code works locally and on Linux containers.
    """
    p = (path_value or "").replace("\\", "/")
    # Avoid escaping colons if we are wrapping the path in single quotes later,
    # but keep it for safety in complex graphs. Single quotes fix most Linux issues.
    p = p.replace("'", r"\'")
    p = p.replace(":", r"\:")
    p = p.replace("[", r"\[")
    p = p.replace("]", r"\]")
    return p


@dataclass
class ClipEditConfig:
    target_ratio: str = "9:16"
    caption_language: str = "en"
    translate_to: Optional[str] = None
    add_captions: bool = True
    add_dynamic_overlays: bool = True
    add_cta: bool = True
    add_hashtags: bool = True
    add_emojis: bool = True
    enhance_visuals: bool = True
    enhance_audio: bool = True
    enable_active_speaker: bool = True
    enable_hook_speed_ramp: bool = False
    hook_ramp_window_s: float = 2.8
    hook_ramp_speed: float = 1.06
    preserve_quality: bool = True
    quality_crf: int = 23
    quality_preset: str = "veryfast"
    export_fps: int = 30
    auto_trim: bool = True
    trim_pad_in_s: float = 0.05
    trim_pad_out_s: float = 0.28
    filler_gap_threshold_s: float = 0.9
    max_caption_words: int = 7
    generate_ab_suggestions: bool = True
    # ── Format detection & speaker tracking ────────────────────────────────────
    enable_format_detection: bool = True   # detect podcast/monologue/motion_graphic
    podcast_crop_mode: str = "stacked"     # "active" = jump | "wide" = keep both | "stacked" = vstack
    speaker_aware_captions: bool = True    # align captions to active speaker side
    # ── Smart clip ending ────────────────────────────────────────────────────────
    smart_ending: bool = True              # snap out-point to first silence after sentence end
    smart_ending_max_extend_s: float = 1.2  # max seconds to scan AFTER sentence end for silence
    smart_ending_silence_db: float = -38.0  # RMS threshold (dBFS) below which audio counts as silence
    smart_ending_silence_min_s: float = 0.18  # minimum silence duration to count as a breath/pause
    sentence_extend_max_s: float = 3.5     # max seconds to extend forward to capture complete sentence/thought
    # ── Split mode strictness ────────────────────────────────────────────────────
    split_min_gap_ratio: float = 0.38      # min face center gap (% frame width) required for SPLIT
    # ── Hook zoom ────────────────────────────────────────────────────────────────
    enable_hook_zoom: bool = True           # subtle punch-in zoom when clip starts
    hook_zoom_scale: float = 1.08          # start zoom (1.08 = 8% tighter than final frame)
    hook_zoom_duration_s: float = 1.2      # seconds to ease from zoomed-in → normal
    # ── Color grading ────────────────────────────────────────────────────────────
    enable_color_grade: bool = True        # professional color grading (inline, zero extra pass)
    color_grade_preset: str = "premium"    # "premium" | "warm" | "cool" | "clean"
    enable_vignette: bool = True           # subtle edge darkening for cinematic depth


@dataclass
class CaptionSegment:
    start: float
    end: float
    text: str
    speaker_side: str = "center"  # "left" | "center" | "right" — drives \an ASS alignment
    words: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class VideoFormat:
    """Result of single-pass video analysis. Drives crop expression and caption alignment."""
    format_type: str                        # "monologue" | "podcast" | "motion_graphic" | "fast_cuts"
    face_count_avg: float                   # average faces per sampled frame
    speaker_positions: List[float]          # normalized X for each detected speaker cluster
    face_switch_rate: float                 # face-position transitions per second
    samples: List[Tuple[float, List[float]]] = field(default_factory=list)  # (t_sec, [face_x, ...])


@dataclass
class EditResult:
    output_path: str
    engagement_score: float
    metadata: Dict[str, Any] = field(default_factory=dict)


class ClipEditor:
    def __init__(self, work_dir: str, fonts_dir: Optional[str] = None, keep_debug_files: bool = False):
        self.work_dir = work_dir
        self.fonts_dir = fonts_dir
        self.keep_debug_files = keep_debug_files
        self._translator = None
        _ensure_dir(self.work_dir)

    def _run(self, cmd: List[str], timeout_s: int = 120) -> None:
        # stderr ko sys.stderr pe bhej diya taaki RunPod logs mein print ho (DEVNULL hata diya)
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=sys.stderr, timeout=timeout_s)

    def _probe_video(self, path: str) -> Dict[str, Any]:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            path,
        ]
        out = subprocess.run(cmd, check=True, capture_output=True, text=True)
        payload = json.loads(out.stdout or "{}")
        streams = payload.get("streams", [])
        v = next((s for s in streams if s.get("codec_type") == "video"), {})
        duration = _safe_float(v.get("duration"), _safe_float(payload.get("format", {}).get("duration"), 0.0))
        return {
            "width": int(_safe_float(v.get("width"), 1920)),
            "height": int(_safe_float(v.get("height"), 1080)),
            "duration": max(0.0, duration),
            "fps": self._parse_fps(v.get("r_frame_rate", "30/1")),
            "has_audio": any(s.get("codec_type") == "audio" for s in streams),
        }

    def _parse_fps(self, value: str) -> float:
        if not value:
            return 30.0
        if "/" in value:
            a, b = value.split("/", 1)
            return _safe_float(a, 30.0) / max(1.0, _safe_float(b, 1.0))
        return _safe_float(value, 30.0)

    def _resolve_ratio(self, ratio: str) -> Tuple[int, int]:
        r = (ratio or "9:16").strip()
        presets = {"9:16": (1080, 1920), "1:1": (1080, 1080), "16:9": (1920, 1080), "4:5": (1080, 1350)}
        if r in presets:
            return presets[r]
        if ":" in r:
            x, y = r.split(":", 1)
            a = max(1.0, _safe_float(x, 9.0))
            b = max(1.0, _safe_float(y, 16.0))
            if a >= b:
                return (1920, int(round(1920 * (b / a))))
            return (1080, int(round(1080 * (b / a))))
        return presets["9:16"]

    def _window_transcript(self, transcript: Optional[List[Dict[str, Any]]], source_start: float, source_end: float) -> List[Dict[str, Any]]:
        if not transcript:
            return []
        clip_start = float(source_start or 0.0)
        clip_end = float(source_end or clip_start)
        clip_duration = clip_end - clip_start
        win = []
        for seg in transcript:
            seg_s = _safe_float(seg.get("start"), 0.0)
            seg_e = _safe_float(seg.get("end"), seg_s)
            
            # Select overlapping segments
            if seg_e > clip_start - 0.5 and seg_s < clip_end + 0.5:
                # Convert to clip-relative timing
                rel_start = max(0.0, seg_s - clip_start)
                rel_end = min(clip_duration, seg_e - clip_start)
                
                txt = (seg.get("text") or "").strip()
                if txt:
                    remapped_seg = {"start": rel_start, "end": rel_end, "text": txt}
                    
                    raw_words = seg.get("words", [])
                    if raw_words:
                        remapped_words = []
                        for w in raw_words:
                            ws = _safe_float(w.get("start"), seg_s)
                            we = _safe_float(w.get("end"), seg_e)
                            if we > clip_start - 0.5 and ws < clip_end + 0.5:
                                remapped_words.append({
                                    "word": w.get("word") or w.get("text", ""),
                                    "text": w.get("word") or w.get("text", ""),
                                    "start": max(0.0, ws - clip_start),
                                    "end": min(clip_duration, we - clip_start),
                                })
                        remapped_seg["words"] = remapped_words
                    win.append(remapped_seg)
        
        n_segments = len(win)
        n_words = sum(len(item.get("words", [])) for item in win) if any(item.get("words") for item in win) else sum(len((item.get("text") or "").split()) for item in win)
        log.info(f"[WCE] transcript_window segments={n_segments} words={n_words} for clip {clip_start:.2f}-{clip_end:.2f}")
        return win

    def _is_sentence_end(self, text: str) -> bool:
        """Return True if the text ends with a sentence-terminating punctuation mark."""
        clean = (text or "").strip().rstrip('"\'')
        return clean.endswith(('.', '?', '!', '…', '...', '—'))

    def _smart_trim_out(
        self,
        clip_path: str,
        last_word_end_s: float,
        clip_duration: float,
        config: "ClipEditConfig",
    ) -> float:
        """
        Find the first true silence after `last_word_end_s` in the audio track.
        Returns the timestamp where silence begins (= ideal out-point).
        Falls back to last_word_end_s + trim_pad_out_s if no silence is found.

        Algorithm:
          1. Extract a short audio window [last_word_end_s, last_word_end_s + max_extend_s]
          2. Compute RMS in 20ms hops
          3. Find the first hop where RMS < silence_db threshold
          4. Require that silence lasts for at least silence_min_s
          5. Snap out-point to start of that silence window
        """
        fallback = min(
            last_word_end_s + config.trim_pad_out_s,
            clip_duration
        )
        # Try numpy-based audio analysis
        try:
            import numpy as np
            import subprocess as sp

            search_start = last_word_end_s
            search_end = min(
                last_word_end_s + config.smart_ending_max_extend_s,
                clip_duration
            )
            search_dur = max(0.05, search_end - search_start)

            # Extract raw 16kHz mono PCM via ffmpeg into stdout
            cmd = [
                "ffmpeg", "-y", "-nostdin",
                "-ss", f"{search_start:.3f}",
                "-t",  f"{search_dur:.3f}",
                "-i",  clip_path,
                "-vn",
                "-ac", "1",
                "-ar", "16000",
                "-f",  "s16le",
                "-",
            ]
            result = sp.run(cmd, capture_output=True, timeout=15)
            if result.returncode != 0 or not result.stdout:
                log.info("[SMART_END] ffmpeg audio extract failed, using fallback")
                return fallback

            audio = np.frombuffer(result.stdout, dtype=np.int16).astype(np.float32) / 32768.0
            if len(audio) == 0:
                return fallback

            SR = 16000
            HOP = int(SR * 0.020)   # 20ms hop
            WIN = int(SR * 0.040)   # 40ms window
            SILENCE_LIN = 10 ** (config.smart_ending_silence_db / 20.0)
            MIN_SILENT_HOPS = max(1, int(config.smart_ending_silence_min_s / 0.020))

            silent_start_hop = None
            silent_count = 0

            n_hops = max(1, (len(audio) - WIN) // HOP + 1)
            for hop_i in range(n_hops):
                s = hop_i * HOP
                e = min(s + WIN, len(audio))
                rms = float(np.sqrt(np.mean(audio[s:e] ** 2))) if e > s else 0.0
                if rms < SILENCE_LIN:
                    if silent_start_hop is None:
                        silent_start_hop = hop_i
                    silent_count += 1
                    if silent_count >= MIN_SILENT_HOPS:
                        # Found a proper silence — snap to start of it
                        t_silence = search_start + (silent_start_hop * HOP) / SR
                        t_silence = _clamp(t_silence, last_word_end_s, clip_duration)
                        log.info(
                            f"[SMART_END] silence found at t={t_silence:.3f}s "
                            f"(rms={rms:.4f} thresh={SILENCE_LIN:.4f} "
                            f"after last_word={last_word_end_s:.3f}s)"
                        )
                        return t_silence
                else:
                    silent_start_hop = None
                    silent_count = 0

            log.info(
                f"[SMART_END] no silence found in [{search_start:.2f}-{search_end:.2f}s], "
                f"using fallback={fallback:.3f}s"
            )
            return fallback

        except Exception as exc:
            log.warning(f"[SMART_END] error during audio analysis: {exc}, using fallback")
            return fallback

    def _trim_bounds(
        self,
        clip_duration: float,
        source_start: float,
        source_end: float,
        transcript_window: List[Dict[str, Any]],
        config: ClipEditConfig,
        clip_path: str = "",
        full_transcript: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[float, float]:
        if not config.auto_trim or not transcript_window:
            return (0.0, max(0.0, clip_duration))

        speech_start = min(_safe_float(x.get("start"), 0.0) for x in transcript_window)
        speech_end   = max(_safe_float(x.get("end"),   clip_duration) for x in transcript_window)

        trim_in = _clamp(speech_start - config.trim_pad_in_s, 0.0, max(0.0, clip_duration - 0.2))

        # ── Smart ending ──────────────────────────────────────────────────────
        if config.smart_ending and clip_path:

            # ── STEP 1: Forward scan — look BEYOND clip end for next sentence boundary ─
            # This is the key: instead of going BACK to find the last complete sentence,
            # we try to EXTEND FORWARD by up to sentence_extend_max_s to capture the
            # current thought being spoken.
            last_sentence_end_t = None  # clip-relative time of best sentence boundary

            if full_transcript and config.sentence_extend_max_s > 0:
                # full_transcript uses original video timestamps
                search_limit_orig = source_end + config.sentence_extend_max_s
                # Find segments that START near/after the current clip end
                for seg in full_transcript:
                    seg_s_orig = _safe_float(seg.get("start"), 0.0)
                    seg_e_orig = _safe_float(seg.get("end"),   0.0)
                    # Only consider segments that end within our extension window
                    if seg_e_orig <= source_end:
                        continue
                    if seg_s_orig > search_limit_orig:
                        break
                    seg_text = (seg.get("text") or "").strip()
                    if self._is_sentence_end(seg_text):
                        # Convert sentence end to clip-relative time
                        words = seg.get("words", [])
                        if words:
                            orig_end_t = _safe_float(words[-1].get("end"), seg_e_orig)
                        else:
                            orig_end_t = seg_e_orig
                        clip_rel_t = orig_end_t - source_start
                        if clip_rel_t <= clip_duration:
                            last_sentence_end_t = clip_rel_t
                            log.info(
                                f"[SMART_END] → FORWARD extended to sentence end: "
                                f"'{seg_text[-50:]}' "
                                f"orig={orig_end_t:.3f}s clip_rel={clip_rel_t:.3f}s"
                            )
                            break

            # ── STEP 2: Backward scan fallback — find last complete sentence IN clip ──
            # Only runs if forward scan didn't find anything (clip ends mid-sentence
            # AND there's no sentence boundary within sentence_extend_max_s ahead).
            if last_sentence_end_t is None:
                last_sentence_end_t = speech_end  # default = full speech extent
                for seg in reversed(transcript_window):
                    seg_text = (seg.get("text") or "").strip()
                    if self._is_sentence_end(seg_text):
                        words = seg.get("words", [])
                        if words:
                            last_sentence_end_t = _safe_float(
                                words[-1].get("end"),
                                _safe_float(seg.get("end"), speech_end)
                            )
                        else:
                            last_sentence_end_t = _safe_float(seg.get("end"), speech_end)
                        log.info(
                            f"[SMART_END] ← BACKWARD to last complete sentence: "
                            f"'{seg_text[-50:]}' at t={last_sentence_end_t:.3f}s"
                        )
                        break

            # ── STEP 3: Silence detection — find exact breath/pause after sentence end ─
            trim_out = self._smart_trim_out(clip_path, last_sentence_end_t, clip_duration, config)

        else:
            trim_out = _clamp(speech_end + config.trim_pad_out_s, trim_in + 0.2, clip_duration)

        trim_out = _clamp(trim_out, trim_in + 0.2, clip_duration)

        if (trim_out - trim_in) < 8.0:
            return (0.0, clip_duration)
        return (trim_in, trim_out)

    def _cut_with_fade(self, input_path: str, output_path: str, start_s: float, end_s: float, timeout_s: int = 120) -> None:
        duration = max(0.25, end_s - start_s)
        # Clean hard cut (No fades). This ensures seamless looping for Shorts.
        # Added a micro 0.05s audio fade-out just to prevent speaker popping/clicking at the cut.
        af = f"afade=t=out:st={max(0.0, duration - 0.05):.3f}:d=0.05"
        cmd = [
            "ffmpeg",
            "-y",
            "-nostdin",
            *_hwaccel_decode_args(),   # ← GPU decode (NVDEC) when available
            "-ss",
            f"{start_s:.3f}",
            "-to",
            f"{end_s:.3f}",
            "-i",
            input_path,
            "-af",
            af,
            *_video_encode_args(crf=23, preset="veryfast"),  # ← NVENC encode
            "-c:a",
            "aac",
            "-b:a",
            _get_export_audio_bitrate(),
            output_path,
        ]
        self._run(cmd, timeout_s=timeout_s)

    def _ema_smooth(self, points, alpha=0.25):
        """EMA smoothing - cinema-grade easing. alpha=0.25 = conservative, no jitter."""
        if not points:
            return []
        result = [(points[0][0], _clamp(points[0][1], 0.10, 0.90))]
        for i in range(1, len(points)):
            t, x = points[i]
            new_x = _clamp(alpha * x + (1.0 - alpha) * result[-1][1], 0.10, 0.90)
            result.append((t, new_x))
        return result

    def _analyze_video_format(self, clip_path):
        """Single-pass video format classifier. 15 frame samples, one OpenCV scan.
        Returns VideoFormat: monologue | podcast | motion_graphic | fast_cuts.
        Speed: ~0.3s on a typical 30s clip.
        """
        _null = VideoFormat(
            format_type="monologue", face_count_avg=1.0,
            speaker_positions=[0.5], face_switch_rate=0.0, samples=[],
        )
        if cv2 is None:
            return _null

        cap = cv2.VideoCapture(clip_path)
        if not cap.isOpened():
            return _null

        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 1000.0
        step = max(1, int(total_frames / 15))

        face_detector = None
        if mp is not None:
            try:
                face_detector = mp.solutions.face_detection.FaceDetection(
                    model_selection=1, min_detection_confidence=0.45
                )
            except Exception:
                face_detector = None

        cascade = None
        if face_detector is None:
            try:
                cascade = cv2.CascadeClassifier(
                    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
                )
            except Exception:
                pass

        samples = []

        # ── Direct-seek sampling ───────────────────────────────────────────────
        # Jump straight to each target frame instead of reading + discarding
        # every intermediate frame. On a 30fps/30s clip this skips ~885 CPU
        # decode operations and drops face-analysis time from ~0.8s → ~0.1s.
        sample_indices = [int(i * step) for i in range(15)]

        try:
            for target_frame in sample_indices:
                cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
                ok, frame = cap.read()
                if not ok or frame is None:
                    continue
                h, w = frame.shape[:2]
                if h <= 1 or w <= 1:
                    continue

                face_xs = []
                if face_detector is not None:
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    res = face_detector.process(rgb)
                    for det in (res.detections or []):
                        bbox = det.location_data.relative_bounding_box
                        cx = _clamp(bbox.xmin + bbox.width / 2.0, 0.0, 1.0)
                        face_xs.append(cx)
                elif cascade is not None:
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    faces = cascade.detectMultiScale(gray, 1.1, 6, minSize=(30, 30))
                    for x, y, fw, fh in faces:
                        if 80 < fw < 400 and 0.05 < (y + fh / 2.0) / h < 0.95:
                            face_xs.append(_clamp((x + fw / 2.0) / float(w), 0.0, 1.0))

                if face_xs:
                    samples.append((target_frame / fps, face_xs))
        finally:
            cap.release()
            if face_detector is not None:
                try:
                    face_detector.close()
                except Exception:
                    pass

        if not samples:
            return _null

        face_counts = [len(s[1]) for s in samples]
        avg_faces = sum(face_counts) / len(face_counts)
        all_xs = [x for _, faces in samples for x in faces]

        if avg_faces < 0.25 or not all_xs:
            log.info("[WCE-FORMAT] classified=motion_graphic")
            return VideoFormat(
                format_type="motion_graphic", face_count_avg=avg_faces,
                speaker_positions=[0.5], face_switch_rate=0.0, samples=samples,
            )

        left_xs  = [x for x in all_xs if x < 0.45]
        right_xs = [x for x in all_xs if x > 0.55]
        is_bimodal = len(left_xs) >= 2 and len(right_xs) >= 2

        if is_bimodal or avg_faces >= 1.4:
            lc = (sum(left_xs) / len(left_xs)) if left_xs else 0.25
            rc = (sum(right_xs) / len(right_xs)) if right_xs else 0.75
            spk_positions = [round(lc, 3), round(rc, 3)] if is_bimodal else [0.5]
            single_sides = [
                "L" if faces[0] < 0.5 else "R"
                for _, faces in samples if len(faces) == 1
            ]
            switches = sum(1 for i in range(1, len(single_sides)) if single_sides[i] != single_sides[i - 1])
            clip_dur = max(1.0, samples[-1][0] - samples[0][0])
            log.info(
                "[WCE-FORMAT] classified=podcast left=%.2f right=%.2f switches/s=%.2f"
                % (lc, rc, switches / clip_dur)
            )
            return VideoFormat(
                format_type="podcast", face_count_avg=avg_faces,
                speaker_positions=spk_positions, face_switch_rate=switches / clip_dur, samples=samples,
            )

        single_xs = [faces[0] for _, faces in samples if len(faces) == 1]
        if len(single_xs) < 3:
            return _null

        variance = statistics.variance(single_xs)
        median_x = _clamp(float(statistics.median(single_xs)), 0.15, 0.85)
        log.info("[WCE-FORMAT] single-face variance=%.4f median_x=%.3f" % (variance, median_x))

        if variance > 0.07:
            log.info("[WCE-FORMAT] classified=fast_cuts")
            return VideoFormat(
                format_type="fast_cuts", face_count_avg=avg_faces,
                speaker_positions=[0.5], face_switch_rate=0.0, samples=samples,
            )

        log.info("[WCE-FORMAT] classified=monologue")
        return VideoFormat(
            format_type="monologue", face_count_avg=avg_faces,
            speaker_positions=[median_x], face_switch_rate=0.0, samples=samples,
        )

    def _get_crop_expression(self, video_fmt, transcript_window, config, clip_path=None):
        """VideoFormat -> FFmpeg crop_x expression.
        monologue: EMA lerp (smooth, stable).
        podcast active: hard jump at transcript boundaries (true active speaker).
        motion_graphic / fast_cuts: fixed 0.5.
        """
        fmt = video_fmt.format_type

        if fmt in ("motion_graphic", "fast_cuts"):
            return 0.5

        if fmt == "monologue":
            timed_pts = [(t, faces[0]) for t, faces in video_fmt.samples if len(faces) == 1]
            if not timed_pts:
                pos = video_fmt.speaker_positions[0] if video_fmt.speaker_positions else 0.5
                return _clamp(pos, 0.15, 0.85)
            smoothed = self._ema_smooth(timed_pts)
            x_vals = [x for _, x in smoothed]
            variance = statistics.variance(x_vals) if len(x_vals) >= 2 else 0.0
            if variance < 0.006:
                log.info("[WCE-VISUAL] mode=STATIC_LOCK")
                return _clamp(float(statistics.median(x_vals)), 0.15, 0.85)
            log.info("[WCE-VISUAL] mode=EMA_SMOOTH_DYNAMIC")
            expr = str(round(smoothed[-1][1], 3))
            for i in range(len(smoothed) - 2, -1, -1):
                t1, x1 = smoothed[i]
                t2, x2 = smoothed[i + 1]
                dt = round(t2 - t1, 4)
                if dt <= 0:
                    continue
                lerp_str = "lerp(%s,%s,(t-%s)/%s)" % (round(x1, 3), round(x2, 3), round(t1, 3), dt)
                expr = "if(lt(t,%s),%s,%s)" % (round(t2, 3), lerp_str, expr)
            return expr

        if fmt == "podcast" and config.podcast_crop_mode in ("active", "stacked"):
            # ═══════════════════════════════════════════════════════════════════════
            # GENIUS PODCAST DIRECTOR v2 — Think Like a Real Video Editor
            #
            # Core rules (stolen from every great podcast editor):
            #  1. SPLIT only when BOTH speakers are actively talking (mouth motion)
            #  2. SOLO_LEFT / SOLO_RIGHT when one person dominates the speech
            #  3. Named LEFT/RIGHT slots (never index-based) → stable tracking
            #  4. Window-voting (0.4s) → single bad frame can't corrupt a segment
            #  5. 1.05x cinematic zoom on SOLO to draw the viewer's eye
            # ═══════════════════════════════════════════════════════════════════════
            cap = None
            fps = 25.0
            frame_width = 1920
            frame_height = 1080

            if clip_path:
                try:
                    cap = cv2.VideoCapture(clip_path)
                    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
                    frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1920)
                    frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1080)
                except Exception:
                    cap = None

            if not cap or not cap.isOpened():
                return 0.5

            # ── Tunable constants (env-overridable) ──────────────────────────────
            TALKING_THRESHOLD = float(os.environ.get("HS_TALKING_THRESHOLD", "80"))
            VOTE_WINDOW_S = 1.2        # seconds — bigger window = stable mode, no flicker
            MIN_SOLO_DURATION_S = 1.5  # don't switch mode for < 1.5s (avoids juggling)
            EMA_ALPHA = 0.15           # mouth motion EMA decay (slower = less noise)
            SMOOTH_ALPHA = 0.07        # position smoothing (ultra-smooth camera pan)

            active_detector = None
            if mp is not None:
                try:
                    # Bug fix: relaxed confidence thresholds — 0.5 was too strict
                    # for typical podcast talking-head shots where faces aren't
                    # perfectly frontal every frame
                    active_detector = mp.solutions.face_mesh.FaceMesh(
                        static_image_mode=False, max_num_faces=2,
                        min_detection_confidence=0.35, min_tracking_confidence=0.3
                    )
                    log.info("[FACE_DEBUG] detector=FaceMesh(conf=0.35,track=0.3)")
                except Exception as _e:
                    log.warning(f"[FACE_DEBUG] FaceMesh init failed: {_e}")

            # Haarcascade fallback — used when MediaPipe is unavailable
            _podcast_cascade = None
            if active_detector is None:
                try:
                    import cv2 as _cv2
                    _podcast_cascade = _cv2.CascadeClassifier(
                        _cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
                    )
                    log.info("[FACE_DEBUG] detector=haarcascade_fallback")
                except Exception as _e:
                    log.warning(f"[FACE_DEBUG] haarcascade fallback also failed: {_e}")

            def is_valid_face(det):
                """Filter: reject plants, hands, tiny background objects.

                Height threshold lowered from 0.08 → 0.05:
                FaceMesh bboxes are derived from landmarks (tighter than
                haarcascade boxes), so the old 8% threshold was rejecting
                real faces — especially in wide podcast shots.
                """
                h = det['h']
                if h < frame_height * 0.08:  # Raised back to 0.08 — rejects plants/shoulders/false positives
                    return False  # too small to be a face
                ratio = h / max(1, det['w'])
                if ratio < 0.7 or ratio > 3.0:  # Tighter aspect ratio — human face only
                    return False  # wrong aspect ratio for a human face
                cy = det['y'] + h / 2.0
                if cy < frame_height * 0.05 or cy > frame_height * 0.92:
                    return False  # face centroid too close to frame edge
                return True

            def decide_mode_v2(left_face, right_face, left_talking, right_talking, face_gap_ratio=0.0):
                """
                Strict video-editor logic for mode selection.

                SPLIT fires ONLY when:
                  1. Both faces are present AND
                  2. Horizontally separated by >= split_min_gap_ratio (default 38% frame width)
                  3. At least one person is actively talking

                Otherwise: SOLO on the active speaker, clean centered crop.
                """
                if not left_face and not right_face:
                    return "HOLD"
                if left_face and not right_face:
                    return "SOLO_LEFT"
                if right_face and not left_face:
                    return "SOLO_RIGHT"

                # Both faces present — check minimum horizontal gap
                if face_gap_ratio < SPLIT_MIN_GAP:
                    # Too close together (e.g. leaning in, wide-angle shot) — SOLO on talker
                    if left_talking and not right_talking:
                        return "SOLO_LEFT"
                    if right_talking and not left_talking:
                        return "SOLO_RIGHT"
                    # Both talking or both silent while close → SOLO on whoever has more motion
                    return "SOLO_LEFT" if ema_mouth_left >= ema_mouth_right else "SOLO_RIGHT"

                # Both well-separated — now check talking state
                if left_talking and right_talking:
                    return "SPLIT"
                if left_talking and not right_talking:
                    return "SOLO_LEFT"
                if right_talking and not left_talking:
                    return "SOLO_RIGHT"

                # Both present, well-separated, but NEITHER talking (natural pause).
                # Don't snap to SPLIT during silence — stay SOLO on last active to avoid jarring cut.
                return "SOLO_LEFT" if ema_mouth_left >= ema_mouth_right else "SOLO_RIGHT"

            def get_mouth_roi(face):
                """Lower 28% of face bounding box = mouth region."""
                return (
                    int(face['x']),
                    int(face['y'] + face['h'] * 0.72),
                    int(face['x'] + face['w']),
                    int(face['y'] + face['h'])
                )

            # ── State initialisation ─────────────────────────────────────────────
            SPLIT_MIN_GAP = float(os.environ.get("HS_SPLIT_MIN_GAP", str(config.split_min_gap_ratio)))
            frame_stats = []
            prev_gray = None
            frame_idx = 0
            # Bug fix: default was "SPLIT" — when valid_count=0, HOLD resolves to SPLIT,
            # causing wrong split layout for the entire clip. SOLO_LEFT is the safe default.
            last_mode = "SOLO_LEFT"
            ema_mouth_left = 0.0
            ema_mouth_right = 0.0
            smoothed_left_x = frame_width * 0.25
            smoothed_right_x = frame_width * 0.75
            smoothed_solo_x = frame_width * 0.5

            # ── Per-frame analysis loop ──────────────────────────────────────────
            while True:
                ok, frame = cap.read()
                if not ok:
                    break

                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                t = frame_idx / fps

                # 1. Detect raw faces — FaceMesh (preferred) or haarcascade fallback
                raw_faces = []
                if active_detector:
                    res = active_detector.process(rgb)
                    if res and res.multi_face_landmarks:
                        for lm in res.multi_face_landmarks:
                            xs = [p.x for p in lm.landmark]
                            ys = [p.y for p in lm.landmark]
                            raw_faces.append({
                                'x': min(xs) * frame_width,
                                'y': min(ys) * frame_height,
                                'w': (max(xs) - min(xs)) * frame_width,
                                'h': (max(ys) - min(ys)) * frame_height,
                            })
                elif _podcast_cascade is not None:
                    # Haarcascade fallback (relaxed params — Step 3 fix)
                    _faces_hc = _podcast_cascade.detectMultiScale(
                        gray,
                        scaleFactor=1.05,   # finer scale (was 1.1)
                        minNeighbors=3,     # easier to detect (was 6)
                        minSize=(40, 40),   # smaller minimum (was 80,80)
                        flags=cv2.CASCADE_SCALE_IMAGE,
                    )
                    if len(_faces_hc):
                        for _x, _y, _fw, _fh in _faces_hc:
                            raw_faces.append({
                                'x': float(_x), 'y': float(_y),
                                'w': float(_fw), 'h': float(_fh),
                            })

                # ── [FACE_DEBUG] Step-1 diagnostic ──────────────────────────────
                if frame_idx % 25 == 0:
                    gray_mean = float(gray.mean()) if gray is not None else -1.0
                    reject_reasons = []
                    for _f in raw_faces:
                        _h = _f['h']
                        _ratio = _h / max(1, _f['w'])
                        _cy = _f['y'] + _h / 2.0
                        if _h < frame_height * 0.08:
                            reject_reasons.append(f"too_small(h={_h:.0f}<{frame_height*0.08:.0f})")
                        elif _ratio < 0.7 or _ratio > 3.2:
                            reject_reasons.append(f"bad_ratio({_ratio:.2f})")
                        elif _cy < frame_height * 0.05 or _cy > frame_height * 0.95:
                            reject_reasons.append(f"edge_cy({_cy:.0f})")
                        else:
                            reject_reasons.append("OK")
                    log.info(
                        f"[FACE_DEBUG] t={t:.2f}s raw={len(raw_faces)} "
                        f"frame_shape=({frame_height},{frame_width},3) "
                        f"gray_mean={gray_mean:.1f} "
                        f"filters={reject_reasons}"
                    )
                # ────────────────────────────────────────────────────────────────

                valid_faces = [f for f in raw_faces if is_valid_face(f)]

                if frame_idx % 25 == 0:
                    log.info(
                        f"[FACE_DEBUG] t={t:.2f}s valid={len(valid_faces)} / raw={len(raw_faces)}"
                    )

                # 2. Assign to named LEFT / RIGHT slots by screen position.
                #    Pick the LARGEST valid face in each half — most prominent person.
                left_slot: Optional[dict] = None
                right_slot: Optional[dict] = None
                for f in valid_faces:
                    cx = f['x'] + f['w'] / 2.0
                    if cx < frame_width / 2.0:
                        if left_slot is None or f['h'] > left_slot['h']:
                            left_slot = f
                    else:
                        if right_slot is None or f['h'] > right_slot['h']:
                            right_slot = f

                if frame_idx % 25 == 0:
                    log.info(
                        f"[SLOT_ASSIGN] t={t:.2f}s left_face={left_slot is not None} "
                        f"right_face={right_slot is not None} valid_count={len(valid_faces)}"
                    )

                # Compute horizontal gap between the two face centers (as fraction of frame width)
                # This is the key gate for SPLIT mode — faces must be clearly separated
                face_gap_ratio = 0.0
                if left_slot is not None and right_slot is not None:
                    left_cx  = left_slot['x']  + left_slot['w']  / 2.0
                    right_cx = right_slot['x'] + right_slot['w'] / 2.0
                    face_gap_ratio = max(0.0, right_cx - left_cx) / frame_width
                    if frame_idx % 25 == 0:
                        log.info(
                            f"[GAP_CHECK] t={t:.2f}s face_gap={face_gap_ratio:.2f} "
                            f"min_required={SPLIT_MIN_GAP:.2f} "
                            f"split_eligible={face_gap_ratio >= SPLIT_MIN_GAP}"
                        )

                # 3. Mouth motion per named slot
                mouth_motion_left = 0.0
                mouth_motion_right = 0.0
                if prev_gray is not None:
                    for slot_label, slot_face in (("left", left_slot), ("right", right_slot)):
                        if slot_face is None:
                            continue
                        mx1, my1, mx2, my2 = get_mouth_roi(slot_face)
                        mx1 = max(0, mx1); mx2 = min(frame_width, mx2)
                        my1 = max(0, my1); my2 = min(frame_height, my2)
                        if mx2 > mx1 and my2 > my1:
                            diff = cv2.absdiff(
                                gray[my1:my2, mx1:mx2],
                                prev_gray[my1:my2, mx1:mx2]
                            )
                            _, thresh = cv2.threshold(diff, 12, 255, cv2.THRESH_BINARY)
                            motion = float(cv2.countNonZero(thresh))
                            if slot_label == "left":
                                mouth_motion_left = motion
                            else:
                                mouth_motion_right = motion

                ema_mouth_left  = ema_mouth_left  * (1 - EMA_ALPHA) + mouth_motion_left  * EMA_ALPHA
                ema_mouth_right = ema_mouth_right * (1 - EMA_ALPHA) + mouth_motion_right * EMA_ALPHA
                left_talking  = ema_mouth_left  > TALKING_THRESHOLD
                right_talking = ema_mouth_right > TALKING_THRESHOLD

                if frame_idx % 25 == 0:
                    log.info(
                        f"[TALKING] t={t:.2f}s L_ema={ema_mouth_left:.1f} R_ema={ema_mouth_right:.1f} "
                        f"L_talk={left_talking} R_talk={right_talking} thresh={TALKING_THRESHOLD}"
                    )

                # 4. Decide mode using strict video-editor logic
                mode = decide_mode_v2(left_slot, right_slot, left_talking, right_talking, face_gap_ratio)
                if mode == "HOLD":
                    mode = last_mode
                else:
                    last_mode = mode

                # 5. Active slot (for SPLIT highlight)
                if mode == "SOLO_LEFT":
                    active_slot = "left"
                elif mode == "SOLO_RIGHT":
                    active_slot = "right"
                else:  # SPLIT — highlight whichever has more mouth motion
                    active_slot = "left" if ema_mouth_left >= ema_mouth_right else "right"

                # 6. Smooth position updates (per slot, independent)
                if left_slot is not None:
                    lx = left_slot['x'] + left_slot['w'] / 2.0
                    smoothed_left_x = smoothed_left_x * (1 - SMOOTH_ALPHA) + lx * SMOOTH_ALPHA

                if right_slot is not None:
                    rx = right_slot['x'] + right_slot['w'] / 2.0
                    smoothed_right_x = smoothed_right_x * (1 - SMOOTH_ALPHA) + rx * SMOOTH_ALPHA

                if mode == "SOLO_LEFT" and left_slot is not None:
                    sx = left_slot['x'] + left_slot['w'] / 2.0
                    smoothed_solo_x = smoothed_solo_x * (1 - SMOOTH_ALPHA) + sx * SMOOTH_ALPHA
                elif mode == "SOLO_RIGHT" and right_slot is not None:
                    sx = right_slot['x'] + right_slot['w'] / 2.0
                    smoothed_solo_x = smoothed_solo_x * (1 - SMOOTH_ALPHA) + sx * SMOOTH_ALPHA

                if frame_idx % 25 == 0:
                    log.info(
                        f"[DIRECTOR_MODE] t={t:.2f}s mode={mode} active_slot={active_slot} "
                        f"L_x={int(smoothed_left_x)} R_x={int(smoothed_right_x)} solo_x={int(smoothed_solo_x)}"
                    )

                frame_stats.append({
                    "t": t,
                    "mode": mode,
                    "active_slot": active_slot,
                    "left_x": smoothed_left_x,
                    "right_x": smoothed_right_x,
                    "solo_x": smoothed_solo_x,
                })

                prev_gray = gray
                frame_idx += 1

            cap.release()
            if active_detector:
                try:
                    active_detector.close()
                except Exception:
                    pass

            if not frame_stats:
                return 0.5

            # ── Window-voting stabilizer ──────────────────────────────────────────
            # Group frames into VOTE_WINDOW_S buckets and vote on majority mode.
            # A single bad frame (plant, hand) can NEVER win a bucket vote.
            voted_windows = []
            i = 0
            while i < len(frame_stats):
                win_start_t = frame_stats[i]["t"]
                win_frames = []
                while i < len(frame_stats) and frame_stats[i]["t"] < win_start_t + VOTE_WINDOW_S:
                    win_frames.append(frame_stats[i])
                    i += 1
                if not win_frames:
                    continue
                mode_counts: Dict[str, int] = {}
                for f in win_frames:
                    mode_counts[f["mode"]] = mode_counts.get(f["mode"], 0) + 1
                non_hold = {k: v for k, v in mode_counts.items() if k != "HOLD"}
                voted_mode = max(non_hold, key=non_hold.get) if non_hold else "HOLD"
                left_votes = sum(1 for f in win_frames if f["active_slot"] == "left")
                voted_slot = "left" if left_votes >= len(win_frames) / 2 else "right"
                voted_windows.append({
                    "start_t": win_start_t,
                    "end_t": win_frames[-1]["t"],
                    "mode": voted_mode,
                    "active_slot": voted_slot,
                    "left_x":  sum(f["left_x"]  for f in win_frames) / len(win_frames),
                    "right_x": sum(f["right_x"] for f in win_frames) / len(win_frames),
                    "solo_x":  sum(f["solo_x"]  for f in win_frames) / len(win_frames),
                })

            # ── Merge consecutive same-mode windows into DirectorSegments ──────────
            stable_segments: List[DirectorSegment] = []
            if not voted_windows:
                return 0.5

            cur = dict(voted_windows[0])
            for win in voted_windows[1:]:
                if win["mode"] == "HOLD":
                    cur["end_t"] = win["end_t"]  # extend silently through holds
                    continue
                same = (win["mode"] == cur["mode"] and win["active_slot"] == cur["active_slot"])
                if same:
                    cur["end_t"]  = win["end_t"]
                    cur["left_x"]  = (cur["left_x"]  + win["left_x"])  / 2
                    cur["right_x"] = (cur["right_x"] + win["right_x"]) / 2
                    cur["solo_x"]  = (cur["solo_x"]  + win["solo_x"])  / 2
                else:
                    seg_dur = cur["end_t"] - cur["start_t"]
                    if cur["mode"] in ("SOLO_LEFT", "SOLO_RIGHT") and seg_dur < MIN_SOLO_DURATION_S:
                        cur = dict(win)  # too short — skip this solo, adopt next window
                        continue
                    stable_segments.append(DirectorSegment(
                        start_t=round(cur["start_t"], 3),
                        end_t=round(cur["end_t"], 3),
                        mode=cur["mode"],
                        active_speaker=cur["active_slot"],
                        crop_x=cur["solo_x"],
                        left_x=cur["left_x"],
                        right_x=cur["right_x"],
                    ))
                    cur = dict(win)

            # Flush final segment
            stable_segments.append(DirectorSegment(
                start_t=round(cur["start_t"], 3),
                end_t=round(frame_stats[-1]["t"] + 0.1, 3),
                mode=cur["mode"],
                active_speaker=cur["active_slot"],
                crop_x=cur["solo_x"],
                left_x=cur["left_x"],
                right_x=cur["right_x"],
            ))

            for seg in stable_segments:
                log.info(
                    f"[DIRECTOR_SEGMENT] t={seg.start_t}-{seg.end_t}s mode={seg.mode} "
                    f"active={seg.active_speaker} crop_x={round(seg.crop_x, 3)}"
                )

            return stable_segments

        return _clamp(
            float(statistics.median(video_fmt.speaker_positions)) if video_fmt.speaker_positions else 0.5,
            0.15, 0.85,
        )


    def _is_boring_monologue(self, transcript_window: List[Dict[str, Any]]) -> bool:
        if not transcript_window:
            return False
        full_text = " ".join(seg.get("text", "") for seg in transcript_window)
        tokens = _tokenize(full_text)
        if len(tokens) < 20:
            return False
        lexical_diversity = len(set(tokens)) / max(1, len(tokens))
        questions = full_text.count("?")
        exclaims = full_text.count("!")
        durations = [max(0.0, _safe_float(s.get("end"), 0.0) - _safe_float(s.get("start"), 0.0)) for s in transcript_window]
        avg_seg = (sum(durations) / len(durations)) if durations else 0.0
        return lexical_diversity < 0.34 and questions == 0 and exclaims <= 1 and avg_seg > 2.8

    def _color_grade_filter(self, config: "ClipEditConfig") -> str:
        """Build a professional inline FFmpeg color-grade filter string.

        Presets:
          premium  – punchy contrast + warm skin tones + lifted shadows (default)
          warm     – golden hour feel, orange/teal Hollywood look
          cool     – crisp blue-tinted cinematic grade (tech / finance content)
          clean    – minimal touch — just contrast + saturation, no colorbalance

        All filters run inline in the existing -vf / filter_complex chain.
        Zero extra FFmpeg pass. CPU cost: ~3-8ms per 30s clip.
        """
        if not config.enable_color_grade:
            return ""

        preset = (config.color_grade_preset or "premium").lower().strip()

        # ── EQ base (contrast + brightness + saturation + gamma lift) ──────────
        # gamma < 1.0  = lifts shadows (stops them crushing to pure black)
        # saturation 1.10-1.25 is the TikTok/Reels sweet spot
        if preset == "warm":
            eq = "eq=contrast=1.06:brightness=0.03:saturation=1.22:gamma=0.95"
            cb = "colorbalance=rs=0.07:gs=0.02:bs=-0.06:rm=0.03:gm=0.01:bm=-0.04"
        elif preset == "cool":
            eq = "eq=contrast=1.10:brightness=0.01:saturation=1.12:gamma=0.97"
            cb = "colorbalance=rs=-0.03:gs=0.00:bs=0.05:rm=-0.01:gm=0.00:bm=0.03"
        elif preset == "clean":
            eq = "eq=contrast=1.06:brightness=0.01:saturation=1.10:gamma=0.98"
            cb = ""
        else:  # premium (default)
            eq = "eq=contrast=1.08:brightness=0.02:saturation=1.18:gamma=0.96"
            cb = "colorbalance=rs=0.04:gs=0.01:bs=-0.03:rm=0.01:gm=0.00:bm=-0.01"

        parts = [eq]
        if cb:
            parts.append(cb)

        # ── Vignette (subtle edge darkening — draws eye to centre / face) ──────
        # angle=PI/5 ≈ 36°  — gentle falloff, not 1990s DVD vignette
        if config.enable_vignette:
            parts.append("vignette=angle=PI/5:mode=forward")

        grade_chain = ",".join(parts)
        log.info(
            "[COLOR_GRADE] preset=%s vignette=%s",
            preset, config.enable_vignette,
        )
        return grade_chain

    def _build_reframe_filter(self, meta: Dict[str, Any], target_wh: Tuple[int, int], focus_x: Union[float, str, Tuple, List[DirectorSegment]], config: ClipEditConfig, boring_mode: bool) -> Tuple[bool, str]:
        src_w = max(1, int(meta.get("width", 1920)))
        src_h = max(1, int(meta.get("height", 1080)))
        dst_w, dst_h = target_wh
        src_ar = src_w / float(src_h)
        dst_ar = dst_w / float(dst_h)

        if isinstance(focus_x, list) and len(focus_x) > 0 and hasattr(focus_x[0], 'mode'):
            segments = focus_x
            vf_parts = []
            concat_inputs = []
            
            for idx, seg in enumerate(segments):
                seg_in = f"[0:v]trim=start={seg.start_t}:end={seg.end_t},setpts=PTS-STARTPTS[v_{idx}_raw]"
                vf_parts.append(seg_in)
                
                if seg.mode in ("SOLO", "SOLO_LEFT", "SOLO_RIGHT"):
                    # 1.05x cinematic zoom — draws the viewer's eye to the active speaker
                    SOLO_ZOOM = 1.05
                    crop_h = max(2, int(src_h / SOLO_ZOOM))
                    crop_w = max(2, int(round(crop_h * dst_ar)))
                    c_x = int(round(_clamp(seg.crop_x - crop_w / 2.0, 0.0, src_w - crop_w)))
                    c_y = max(0, int(round((src_h - crop_h) / 2.0)))
                    chain = f"[v_{idx}_raw]crop={crop_w}:{crop_h}:{c_x}:{c_y},scale={dst_w}:{dst_h}:flags=lanczos,setsar=1[v_{idx}_out]"
                    vf_parts.append(chain)
                    
                elif seg.mode == "ACTIVE_CENTER":
                    crop_h = max(2, int(src_h / 1.4))
                    crop_w = max(2, int((src_h * dst_ar) / 1.4))
                    c_x = int(round(_clamp(seg.crop_x - crop_w / 2.0, 0.0, src_w - crop_w)))
                    c_y = int(round((src_h - crop_h) / 2.0))
                    chain = f"[v_{idx}_raw]crop={crop_w}:{crop_h}:{c_x}:{c_y},scale={dst_w}:{dst_h}:flags=lanczos,setsar=1[v_{idx}_out]"
                    vf_parts.append(chain)
                    
                else: # SPLIT
                    crop_h = src_h
                    crop_w = max(2, int(round(src_h * (dst_w / (dst_h / 2.0)))))
                    l_cx = int(round(_clamp(seg.left_x - crop_w / 2.0, 0.0, src_w - crop_w)))
                    r_cx = int(round(_clamp(seg.right_x - crop_w / 2.0, 0.0, src_w - crop_w)))
                    is_left = (seg.active_speaker == "left")
                    
                    top_chain = f"crop={crop_w}:{crop_h}:{l_cx}:0,scale={dst_w}:{int(dst_h//2)}:flags=lanczos"
                    bot_chain = f"crop={crop_w}:{crop_h}:{r_cx}:0,scale={dst_w}:{int(dst_h//2)}:flags=lanczos"
                    
                    # Premium double-layer glow border for active speaker slot
                    glow = (
                        "drawbox=x=0:y=0:w=iw:h=ih:color=#FF8C00:thickness=5,"
                        "drawbox=x=5:y=5:w=iw-10:h=ih-10:color=#FFAA44:thickness=2"
                    )
                    dim = "colorchannelmixer=rr=0.6:gg=0.6:bb=0.6"
                    if is_left:
                        top_chain += f",{glow}"
                        bot_chain += f",{dim}"
                    else:
                        top_chain += f",{dim}"
                        bot_chain += f",{glow}"
                    
                    split_chain = (
                        f"[v_{idx}_raw]split=2[t_raw_{idx}][b_raw_{idx}];"
                        f"[t_raw_{idx}]{top_chain}[t_out_{idx}];"
                        f"[b_raw_{idx}]{bot_chain}[b_out_{idx}];"
                        f"[t_out_{idx}][b_out_{idx}]vstack=inputs=2,setsar=1[v_{idx}_out]"
                    )
                    vf_parts.append(split_chain)
                
                concat_inputs.append(f"[v_{idx}_out]")
                
            concat_str = "".join(concat_inputs) + f"concat=n={len(segments)}:v=1:a=0[v_concat]"
            vf_parts.append(concat_str)

            post_chain = []
            grade = self._color_grade_filter(config)
            if grade:
                post_chain.append(grade)
            if os.getenv("HS_WATERMARK_ENABLED", "1") == "1":
                text = os.getenv("HS_WATERMARK_TEXT", "HOTSHORT")
                post_chain.append(f"drawtext=text='{text}':fontcolor=white@0.25:fontsize=H/35:x=W-tw-40:y=40:fontfile=C\\\\:/Windows/Fonts/segoeui.ttf")

            if post_chain:
                vf_parts.append(f"[v_concat]{','.join(post_chain)}[v_reframe]")
            else:
                vf_parts.append("[v_concat]null[v_reframe]")
            return True, ";".join(vf_parts)

        elif isinstance(focus_x, tuple) and len(focus_x) == 3:
            expr, left_x, right_x = focus_x
            expr = expr.replace(",", "\\,")
            crop_h = src_h
            crop_w = max(2, int(round(src_h * (dst_w / (dst_h / 2.0)))))
            l_cx = str(int(round(_clamp(src_w * left_x - crop_w / 2.0, 0.0, src_w - crop_w))))
            r_cx = str(int(round(_clamp(src_w * right_x - crop_w / 2.0, 0.0, src_w - crop_w))))
            is_top = f"lt({expr}\\,{left_x + 0.02})"
            is_bot = f"gt({expr}\\,{right_x - 0.02})"
            dot = "drawbox=x=40:y=40:w=35:h=35:color=0xFF6B00:t=fill"
            top_chain = (
                f"crop={crop_w}:{crop_h}:{l_cx}:0,"
                f"scale={dst_w}:{int(dst_h//2)}:flags=lanczos,"
                f"colorchannelmixer=rr=0.6:gg=0.6:bb=0.6:enable='not({is_top})',"
                f"{dot}:enable='{is_top}'"
            )
            bot_chain = (
                f"crop={crop_w}:{crop_h}:{r_cx}:0,"
                f"scale={dst_w}:{int(dst_h//2)}:flags=lanczos,"
                f"colorchannelmixer=rr=0.6:gg=0.6:bb=0.6:enable='not({is_bot})',"
                f"{dot}:enable='{is_bot}'"
            )
            vf_str = (
                f"split=2[t_raw][b_raw];"
                f"[t_raw]{top_chain}[t_out];"
                f"[b_raw]{bot_chain}[b_out];"
                f"[t_out][b_out]vstack=inputs=2"
            )
            post_chain = []
            grade = self._color_grade_filter(config)
            if grade:
                post_chain.append(grade)
            if os.getenv("HS_WATERMARK_ENABLED", "1") == "1":
                text = os.getenv("HS_WATERMARK_TEXT", "HOTSHORT")
                post_chain.append(f"drawtext=text='{text}':fontcolor=white@0.25:fontsize=H/35:x=W-tw-40:y=40:fontfile=C\\\\:/Windows/Fonts/segoeui.ttf")

            if post_chain:
                return True, f"{vf_str}[v_stacked];[v_stacked]{','.join(post_chain)}[v_reframe]"
            return True, f"{vf_str}[v_stacked];[v_stacked]null[v_reframe]"
        elif src_ar >= dst_ar:
            crop_h = src_h
            crop_w = max(2, int(round(src_h * dst_ar)))
            if isinstance(focus_x, str):
                raw_x = f"max(0,min({src_w}-{crop_w},{src_w}*({focus_x})-({crop_w}/2.0)))"
                crop_x = raw_x.replace(",", "\\,")
            else:
                x_center = src_w * _clamp(float(focus_x), 0.0, 1.0)
                crop_x = str(int(round(_clamp(x_center - (crop_w / 2.0), 0.0, src_w - crop_w))))
            crop_y = "0"
            vf_parts = [f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y}", f"scale={dst_w}:{dst_h}:flags=lanczos"]
        else:
            crop_w = src_w
            crop_h = max(2, int(round(src_w / dst_ar)))
            crop_x = "0"
            crop_y = str(int(round((src_h - crop_h) / 2.0)))
            vf_parts = [f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y}", f"scale={dst_w}:{dst_h}:flags=lanczos"]
        
        # ── Professional color grading (inline, zero extra pass) ────────────────
        grade = self._color_grade_filter(config)
        if grade:
            vf_parts.append(grade)

        log.info(
            "[WCE-VISUAL] color_grade=%s vignette=%s",
            config.color_grade_preset if config.enable_color_grade else "off",
            config.enable_vignette,
        )

        # NOTE: format=yuv420p is intentionally NOT appended here.
        # It must come AFTER the subtitles filter so libass can do
        # RGBA compositing on the frame before pixel-format conversion.
        return False, ",".join(vf_parts)

    def _build_audio_filter(self, config: ClipEditConfig) -> str:
        if not config.enhance_audio:
            return "anull"
        return ",".join(
            [
                "highpass=f=80",
                "lowpass=f=11000",
                "dynaudnorm=f=150:g=15",
                "acompressor=threshold=-16dB:ratio=2.2:attack=18:release=180",
                "loudnorm=I=-14:LRA=7:TP=-1.5",
            ]
        )

    def _apply_hook_speed_ramp(self, input_path: str, output_path: str, clip_duration: float, config: ClipEditConfig) -> Tuple[float, float]:
        if (not config.enable_hook_speed_ramp) or clip_duration < 5.0:
            shutil.copy2(input_path, output_path)
            return 0.0, clip_duration
        ramp_window = min(max(1.6, config.hook_ramp_window_s), max(1.8, clip_duration - 1.0))
        speed = _clamp(config.hook_ramp_speed, 1.01, 1.30)
        atempo = _clamp(speed, 0.5, 2.0)
        fc = (
            "[0:v]split=2[v0][v1];"
            f"[v0]trim=0:{ramp_window:.3f},setpts=PTS/{speed:.5f}[v0s];"
            f"[v1]trim={ramp_window:.3f},setpts=PTS-STARTPTS[v1s];"
            "[0:a]asplit=2[a0][a1];"
            f"[a0]atrim=0:{ramp_window:.3f},asetpts=PTS-STARTPTS,atempo={atempo:.5f}[a0s];"
            f"[a1]atrim={ramp_window:.3f},asetpts=PTS-STARTPTS[a1s];"
            "[v0s][a0s][v1s][a1s]concat=n=2:v=1:a=1[v][a]"
        )
        cmd = [
            "ffmpeg",
            "-y",
            "-nostdin",
            *_hwaccel_decode_args(),   # ← GPU decode
            "-i",
            input_path,
            "-filter_complex",
            fc,
            "-map",
            "[v]",
            "-map",
            "[a]",
            *_video_encode_args(crf=23, preset="veryfast"),  # ← NVENC encode
            "-c:a",
            "aac",
            "-b:a",
            _get_export_audio_bitrate(),
            output_path,
        ]
        try:
            self._run(cmd, timeout_s=120)
            new_duration = (ramp_window / speed) + max(0.0, clip_duration - ramp_window)
            return ramp_window, new_duration
        except Exception:
            shutil.copy2(input_path, output_path)
            return 0.0, clip_duration

    def _apply_hook_zoom(
        self,
        input_path: str,
        output_path: str,
        clip_duration: float,
        config: "ClipEditConfig",
    ) -> None:
        """
        GPU-accelerated hook punch-in zoom.

        Creates a subtle zoom-in effect at clip start: the frame begins slightly
        tighter (hook_zoom_scale) and eases back to normal crop over
        hook_zoom_duration_s seconds.  This draws the viewer's eye to the
        speaker's face in the first moment without any jarring cuts.

        Implementation: pure FFmpeg scale + crop with a time expression.
        Works on NVENC (GPU) or libx264 (CPU fallback) via _video_encode_args().
        Does NOT use zoompan (slow per-frame CPU filter).
        """
        if not config.enable_hook_zoom or clip_duration < 2.0:
            shutil.copy2(input_path, output_path)
            return

        scale  = _clamp(config.hook_zoom_scale, 1.01, 1.30)
        dur    = _clamp(config.hook_zoom_duration_s, 0.3, min(3.0, clip_duration * 0.4))

        # Progress: 0 → 1 over dur seconds, then locked at 1
        # ease(t) = clamp(t/dur, 0, 1)   [linear — clean and fast]
        # zoom(t) = scale → 1.0   as ease goes 0 → 1
        # crop_w(t) = iw / zoom(t)  [crop tighter at t=0, full at t>=dur]
        # crop offset centers the crop on the frame at all times
        #
        # FFmpeg crop filter: crop=out_w:out_h:x:y
        #   out_w = iw/zoom   (pixel width of crop window — smaller = more zoomed in)
        #   x     = (iw - out_w) / 2   (center horizontally)
        #
        # We embed the time expression directly — no per-frame Python overhead.
        #
        # ease_t  = min(t/{dur},1)            # 0..1 ramp
        # zoom_t  = {scale} - ({scale}-1)*ease_t    # scale..1.0
        # crop_w  = iw/zoom_t
        # crop_h  = ih/zoom_t
        # x       = (iw-crop_w)/2
        # y       = (ih-crop_h)/2

        d = round(dur, 4)
        s = round(scale, 4)

        crop_w = f"iw/({s}-({s}-1)*min(t/{d}\\,1))"
        crop_h = f"ih/({s}-({s}-1)*min(t/{d}\\,1))"
        crop_x = f"(iw-{crop_w})/2"
        crop_y = f"(ih-{crop_h})/2"

        vf = (
            f"crop=w='{crop_w}':h='{crop_h}':x='{crop_x}':y='{crop_y}',"
            f"scale=iw:ih:flags=lanczos"
        )

        cmd = [
            "ffmpeg", "-y", "-nostdin",
            *_hwaccel_decode_args(),   # ← GPU decode (NVDEC)
            "-i", input_path,
            "-vf", vf,
            *_video_encode_args(crf=18, preset="veryfast"),  # ← NVENC, near-lossless intermediate
            "-c:a", "copy",   # audio passthrough — no re-encode needed
            output_path,
        ]
        try:
            self._run(cmd, timeout_s=120)
            log.info(
                f"[HOOK_ZOOM] applied scale={scale}x over {dur}s → {os.path.basename(output_path)}"
            )
        except Exception as exc:
            log.warning(f"[HOOK_ZOOM] failed ({exc}), copying original")
            shutil.copy2(input_path, output_path)

    def _adjust_for_ramp(self, t: float, ramp_window: float, speed: float) -> float:
        if ramp_window <= 0.0:
            return t
        if t <= ramp_window:
            return t / speed
        return (ramp_window / speed) + (t - ramp_window)

    def _split_caption_text(self, text: str, max_words: int) -> List[str]:
        words = (text or "").split()
        if len(words) <= max_words:
            return [text.strip()] if text.strip() else []
        chunks = []
        for i in range(0, len(words), max_words):
            chunks.append(" ".join(words[i : i + max_words]).strip())
        return [c for c in chunks if c]

    def _format_hook_line(self, text: str, words_per_line: int = 7, max_lines: int = 2) -> str:
        """
        Keep hook overlay compact and readable.
        """
        clean = " ".join((text or "").strip().split())
        if not clean:
            return ""
        words = clean.split()
        max_words = max(1, int(words_per_line)) * max(1, int(max_lines))
        truncated = len(words) > max_words
        words = words[:max_words]
        lines: List[str] = []
        step = max(1, int(words_per_line))
        for i in range(0, len(words), step):
            lines.append(" ".join(words[i : i + step]))
        out = "\n".join(lines).strip()
        if truncated:
            out += "..."
        return out

    def _load_translator(self, target_lang: str):
        if self._translator is not None:
            return self._translator
        if hf_pipeline is None:
            return None
        lang_map = {"hi": "Helsinki-NLP/opus-mt-en-hi", "pa": "Helsinki-NLP/opus-mt-en-hi"}
        model_id = lang_map.get((target_lang or "").lower())
        if not model_id:
            return None
        try:
            self._translator = hf_pipeline("translation", model=model_id)
        except Exception:
            self._translator = None
        return self._translator

    def _translate(self, text: str, target_lang: Optional[str]) -> str:
        if not text or not target_lang:
            return text
        translator = self._load_translator(target_lang)
        if translator is None:
            return text
        try:
            out = translator(text, max_length=256)
            if out and isinstance(out, list):
                return (out[0].get("translation_text") or text).strip()
        except Exception:
            pass
        return text

    def _decorate_caption(self, text: str, use_emoji: bool) -> str:
        out = text.strip()
        if not use_emoji:
            return out
        emoji_rules = [
            (r"\b(secret|nobody tells|hidden)\b", "🔥"),
            (r"\b(money|profit|revenue|sale)\b", "💸"),
            (r"\b(ai|tool|automation)\b", "🤖"),
            (r"\b(grow|growth|viral)\b", "🚀"),
            (r"\b(fast|quick|instantly)\b", "⚡"),
        ]
        low = out.lower()
        for pat, suffix in emoji_rules:
            if re.search(pat, low):
                return out + suffix
        return out

    def _caption_segments(
        self,
        transcript_window: List[Dict[str, Any]],
        source_start: float,
        trim_in: float,
        trim_out: float,
        config: ClipEditConfig,
        ramp_window: float,
        video_fmt: "VideoFormat" = None,
    ) -> List[CaptionSegment]:
        if not transcript_window:
            return []
        cap_segments: List[CaptionSegment] = []
        speed = _clamp(config.hook_ramp_speed, 1.01, 1.30)
        clip_rel_max = max(0.0, trim_out - trim_in)
        for seg in transcript_window:
            words_data = seg.get("words", [])
            
            sub_segments = []
            if words_data:
                current_words = []
                for w in words_data:
                    w_text = (w.get("word") or w.get("text", "")).strip()
                    if not w_text: continue
                    current_words.append({
                        "text": w_text,
                        "start": _safe_float(w.get("start"), 0.0),
                        "end": _safe_float(w.get("end"), 0.0)
                    })
                    if len(current_words) >= max(3, config.max_caption_words):
                        sub_segments.append({
                            "start": current_words[0]["start"],
                            "end": current_words[-1]["end"],
                            "text": " ".join(cw["text"] for cw in current_words),
                            "words": current_words
                        })
                        current_words = []
                if current_words:
                    sub_segments.append({
                        "start": current_words[0]["start"],
                        "end": current_words[-1]["end"],
                        "text": " ".join(cw["text"] for cw in current_words),
                        "words": current_words
                    })
            else:
                raw_start = _safe_float(seg.get("start"), 0.0)
                raw_end = _safe_float(seg.get("end"), raw_start)
                text = (seg.get("text") or "").strip()
                if not text: continue
                chunks = self._split_caption_text(text, max_words=max(3, config.max_caption_words))
                if not chunks: continue
                seg_dur = max(0.16, raw_end - raw_start)
                all_words = text.split()
                total_chars = max(1, sum(len(w) for w in all_words))
                # [FIX] Proportional timing: longer words get more screen time.
                # This is far more accurate than dividing duration evenly by chunk count.
                char_offset = 0
                for chunk_text in chunks:
                    chunk_words = chunk_text.split()
                    chunk_chars = sum(len(w) for w in chunk_words)
                    chunk_start = raw_start + (char_offset / total_chars) * seg_dur
                    char_offset += chunk_chars
                    chunk_end = raw_start + (char_offset / total_chars) * seg_dur
                    sub_segments.append({
                        "start": chunk_start,
                        "end": max(chunk_start + 0.16, chunk_end),
                        "text": chunk_text,
                        "words": []
                    })
                    
            for sub in sub_segments:
                rel_start = max(0.0, sub["start"] - trim_in)
                rel_end = max(rel_start + 0.12, sub["end"] - trim_in)
                if rel_end <= 0.0 or rel_start >= clip_rel_max + 0.1:
                    continue
                rel_start = _clamp(rel_start, 0.0, clip_rel_max)
                rel_end = _clamp(rel_end, rel_start + 0.1, clip_rel_max)
                rel_start = self._adjust_for_ramp(rel_start, ramp_window, speed)
                rel_end = self._adjust_for_ramp(rel_end, ramp_window, speed)
                
                c_txt = self._translate(sub["text"], config.translate_to)
                c_txt = self._decorate_caption(c_txt, config.add_emojis)
                
                final_words = []
                if sub["words"] and not config.translate_to:
                    for w in sub["words"]:
                        w_rel_start = max(0.0, w["start"] - trim_in)
                        w_rel_start = _clamp(w_rel_start, 0.0, clip_rel_max)
                        w_rel_start = self._adjust_for_ramp(w_rel_start, ramp_window, speed)
                        
                        w_rel_end = max(w_rel_start + 0.01, w["end"] - trim_in)
                        w_rel_end = _clamp(w_rel_end, w_rel_start + 0.01, clip_rel_max)
                        w_rel_end = self._adjust_for_ramp(w_rel_end, ramp_window, speed)
                        
                        final_words.append({
                            "start": w_rel_start,
                            "end": w_rel_end,
                            "text": w["text"]
                        })
                
                seg_side = "center"
                if config.speaker_aware_captions and video_fmt is not None and len(video_fmt.speaker_positions) >= 2:
                    spk = sorted(video_fmt.speaker_positions[:2])
                    closest_faces = []
                    best_dt = float("inf")
                    for t_samp, faces in video_fmt.samples:
                        dt = abs(t_samp - rel_start)
                        if dt < best_dt:
                            best_dt = dt
                            closest_faces = faces
                    if len(closest_faces) == 1:
                        seg_side = "left" if closest_faces[0] < 0.5 else "right"
                    elif len(closest_faces) >= 2:
                        seg_side = "left" if (sum(closest_faces) / len(closest_faces)) < 0.5 else "right"
                cap_segments.append(CaptionSegment(start=rel_start, end=rel_end, text=c_txt, speaker_side=seg_side, words=final_words))
        return cap_segments

    def _extract_hashtags(self, transcript_window: List[Dict[str, Any]], limit: int = 4) -> str:
        if not transcript_window:
            return "#podcast #shorts"
        stop = {
            "the", "a", "an", "and", "or", "to", "of", "for", "is", "are", "on", "in", "that",
            "this", "it", "its", "you", "we", "they", "with", "from", "be", "as", "at", "by", "was",
        }
        freq: Dict[str, int] = {}
        for seg in transcript_window:
            for tok in _tokenize(seg.get("text", "")):
                tok_norm = re.sub(r"[^a-z0-9]+", "", tok.lower())
                if tok_norm in stop or len(tok_norm) < 4:
                    continue
                freq[tok_norm] = freq.get(tok_norm, 0) + 1
        top = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:limit]
        if not top:
            return "#podcast #viralclips"
        return " ".join(f"#{w}" for w, _ in top)

    def _highlight_text(self, text: str) -> str:
        words = text.split()
        if not words:
            return text

        # Semantic color routing — priority: Danger > Success > Highlight
        _danger_keywords = {
            "wrong", "mistake", "fail", "failing", "failed", "failure", "lose", "losing", "loss",
            "bad", "never", "stop", "quit", "risk", "trap", "scam", "fake", "lie", "lies",
            "warning", "danger", "worst", "broke", "debt", "crash", "kill", "dead", "dying",
        }
        _success_keywords = {
            "win", "winning", "winner", "grow", "growth", "profit", "revenue", "sale", "sales",
            "free", "best", "top", "success", "succeed", "rich", "wealth", "power", "strong",
            "fast", "quick", "instant", "instantly", "viral", "launch", "unlock", "proven",
        }
        _highlight_keywords = {
            "secret", "truth", "nobody", "why", "how", "money", "ai", "tool", "automation",
            "always", "real", "hack", "exposed", "hidden",
        }

        def _style_for(word: str) -> str:
            clean = re.sub(r"[^\w]", "", word).lower()
            if clean in _danger_keywords:
                return "Danger"
            if clean in _success_keywords:
                return "Success"
            if clean in _highlight_keywords:
                return "Highlight"
            return ""

        # First pass: find up to 2 semantically tagged words
        tagged: list[tuple[int, str]] = []
        for idx, w in enumerate(words):
            style = _style_for(w)
            if style:
                tagged.append((idx, style))
            if len(tagged) >= 2:
                break

        # Fallback: highlight longest word with golden Highlight if nothing matched
        if not tagged:
            longest_idx, longest_len = -1, -1
            for idx, w in enumerate(words):
                clean = re.sub(r"[^\w]", "", w)
                if len(clean) > longest_len:
                    longest_len = len(clean)
                    longest_idx = idx
            if longest_idx != -1:
                tagged.append((longest_idx, "Highlight"))

        for idx, style in tagged:
            words[idx] = f"{{\\r{style}}}{words[idx]}{{\\r}}"
        return " ".join(words)

    def _write_ass(
        self,
        path: str,
        width: int,
        height: int,
        duration: float,
        captions: List[CaptionSegment],
        hook_line: Optional[str],
        cta_line: Optional[str],
        hashtags_line: Optional[str],
        subtitle_style: str = "classic",
        speaker_side: str = "center",  # "left", "right", or "center"
    ) -> None:
        style_val = str(subtitle_style or "classic").lower().strip()
        
        # Default style tokens
        caption_color = "&H00FFFFFF"     # White
        hook_color = "&H00FFAA00"        # Orange-yellow
        highlight_color = "&H0000C8FF"   # Gold
        border_size = "3"
        shadow_size = "2"
        bold_val = "-1"
        italic_val = "0"
        
        if style_val == "neon":
            caption_color = "&H00FFFF00"     # Neon Cyan
            highlight_color = "&H00FF00FF"   # Neon Pink / Magenta
            hook_color = "&H0000FFFF"        # Neon Yellow
            border_size = "3.5"
            shadow_size = "3"
        elif style_val == "beast":
            caption_color = "&H0000FFFF"     # Bright Yellow
            highlight_color = "&H00FFFF00"   # Cyan
            hook_color = "&H000088FF"        # Bright Orange
            border_size = "4"
            shadow_size = "2"
        elif style_val == "minimal":
            caption_color = "&H00FFFFFF"     # White
            highlight_color = "&H0000FF00"   # Pure Green
            hook_color = "&H00FFFFFF"
            border_size = "1"                # Thin border
            shadow_size = "0"                # No shadow
        elif style_val == "retro":
            caption_color = "&H0000FFFF"     # Yellow text
            highlight_color = "&H003300FF"   # Red Highlight
            hook_color = "&H00FFFFFF"
            italic_val = "-1"                # Italic
            border_size = "3"
            shadow_size = "3"

        # ── Speaker-aware caption positioning ──────────────────────────────
        # Global style baseline = bottom-center (alignment=2). Per-event \an tags
        # override alignment for individual captions when speaker_side is set.
        # Alignment codes in ASS: 1=bottom-left, 2=bottom-center, 3=bottom-right
        caption_alignment = 2
        margin_l, margin_r, margin_v = 40, 40, 250
        log.info("[WCE-CAPTION] per-event speaker-side \\an alignment: ACTIVE")

        header = [
            "[Script Info]",
            "ScriptType: v4.00+",
            "PlayResX: 1080",
            "PlayResY: 1920",
            "ScaledBorderAndShadow: yes",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            f"Style: Caption,Montserrat,80,{caption_color},&H000000FF,&H00000000,&H80000000,{bold_val},{italic_val},0,0,100,100,0,0,1,{border_size},{shadow_size},{caption_alignment},{margin_l},{margin_r},{margin_v},1",
            f"Style: Hook,Montserrat,75,{hook_color},&H000000FF,&H00000000,&H90000000,-1,0,0,0,100,100,0,0,1,4,3,8,20,20,150,1",
            f"Style: Highlight,Montserrat,80,{highlight_color},&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{border_size},{shadow_size},{caption_alignment},{margin_l},{margin_r},{margin_v},1",
            f"Style: Danger,Montserrat,80,&H003300FF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{border_size},{shadow_size},{caption_alignment},{margin_l},{margin_r},{margin_v},1",
            f"Style: Success,Montserrat,80,&H0055FF00,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{border_size},{shadow_size},{caption_alignment},{margin_l},{margin_r},{margin_v},1",
            f"Style: CTA,Montserrat,45,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,2,2,20,20,100,1",
            # KaraokeWord: slightly smaller, used for the inactive (ghost) state of karaoke
            f"Style: KaraokeGhost,Montserrat,80,&H80FFFFFF,&H000000FF,&H00000000,&H80000000,{bold_val},{italic_val},0,0,100,100,0,0,1,{border_size},{shadow_size},{caption_alignment},{margin_l},{margin_r},{margin_v},1",
            "",
            "[Events]",
            "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text",
        ]
        log.info("[WCE-VISUAL] caption_safe_zone=speaker_aware")
        events = []
        for seg in captions:
            if seg.end <= seg.start:
                continue
            escaped_text = _ass_escape(seg.text)
            words = seg.text.split()
            if getattr(seg, "words", None) and len(seg.words) == len(words):
                for wi, (word_text, w_dict) in enumerate(zip(words, seg.words)):
                    w_start = w_dict["start"]
                    w_end = w_dict["end"]
                    ghost_before = " ".join(words[:wi])
                    active = _ass_escape(word_text)
                    ghost_after  = " ".join(words[wi + 1:])
                    parts = []
                    if ghost_before:
                        parts.append("{\\rKaraokeGhost}" + _ass_escape(ghost_before))
                    parts.append("{\\rHighlight}" + active + "{\\r}")
                    if ghost_after:
                        parts.append("{\\rKaraokeGhost}" + _ass_escape(ghost_after))
                    line_text = " ".join(parts)
                    an_tag = {"left": "{\\an1}", "right": "{\\an3}"}.get(getattr(seg, "speaker_side", "center"), "")
                    events.append(f"Dialogue: 0,{_ass_time(w_start)},{_ass_time(w_end)},Caption,,0,0,0,,{an_tag}{line_text}")
            elif len(words) > 1:
                word_dur = (seg.end - seg.start) / len(words)
                for wi, word in enumerate(words):
                    w_start = seg.start + wi * word_dur
                    w_end   = seg.start + (wi + 1) * word_dur
                    # Build line: ghost words + {\rHighlight}active_word{\r} + ghost words
                    ghost_before = " ".join(words[:wi])
                    active = _ass_escape(word)
                    ghost_after  = " ".join(words[wi + 1:])
                    parts = []
                    if ghost_before:
                        parts.append("{\\rKaraokeGhost}" + _ass_escape(ghost_before))
                    parts.append("{\\rHighlight}" + active + "{\\r}")
                    if ghost_after:
                        parts.append("{\\rKaraokeGhost}" + _ass_escape(ghost_after))
                    line_text = " ".join(parts)
                    an_tag = {"left": "{\\an1}", "right": "{\\an3}"}.get(getattr(seg, "speaker_side", "center"), "")
                    events.append(f"Dialogue: 0,{_ass_time(w_start)},{_ass_time(w_end)},Caption,,0,0,0,,{an_tag}{line_text}")
            else:
                # Single-word segment — just highlight it
                highlighted_text = self._highlight_text(escaped_text)
                an_tag = {"left": "{\\an1}", "right": "{\\an3}"}.get(getattr(seg, "speaker_side", "center"), "")
                events.append(f"Dialogue: 0,{_ass_time(seg.start)},{_ass_time(seg.end)},Caption,,0,0,0,,{an_tag}{highlighted_text}")

        if hook_line:
            hook_text = self._format_hook_line(hook_line)
            if hook_text:
                hook_end = min(duration, 4.0)  # Extended from 2.2s → 4s so viewers can read it
                events.append(f"Dialogue: 1,{_ass_time(0.08)},{_ass_time(hook_end)},Hook,,0,0,0,,{_ass_escape(hook_text)}")
        if hashtags_line:
            start = max(0.0, duration - 3.8)
            end = max(start + 0.5, duration - 0.2)
            events.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},CTA,,0,0,0,,{_ass_escape(hashtags_line)}")
        if cta_line:
            start = max(0.0, duration - 2.6)
            end = max(start + 0.5, duration - 0.1)
            events.append(f"Dialogue: 2,{_ass_time(start)},{_ass_time(end)},CTA,,0,0,0,,{_ass_escape(cta_line)}")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(header + events))

    def _burn_ass(self, input_path: str, ass_path: str, output_path: str, fps: int, preserve_quality: bool) -> None:
        fonts_dir_esc = _ffmpeg_filter_path(_FONTS_DIR)
        ass_esc = _ffmpeg_filter_path(ass_path)
        vf = f"subtitles='{ass_esc}':fontsdir='{fonts_dir_esc}',format=yuv420p"
        cmd = [
            "ffmpeg",
            "-y",
            "-nostdin",
            *_hwaccel_decode_args(),   # ← GPU decode
            "-i",
            input_path,
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-vf",
            vf,
            "-r",
            str(max(24, int(fps))),
            *_video_encode_args(
                crf=23 if preserve_quality else 24,
                preset="veryfast",
            ),
            "-c:a",
            "aac",
            "-b:a",
            _get_export_audio_bitrate(),
            "-movflags",
            "+faststart",
            output_path,
        ]
        self._run(cmd, timeout_s=180)

    def _estimate_engagement(self, captions: List[CaptionSegment], transcript_window: List[Dict[str, Any]], boring_mode: bool, has_hook: bool) -> float:
        full_text = " ".join(seg.get("text", "") for seg in transcript_window).lower()
        tokens = _tokenize(full_text)
        words = len(tokens)
        hook_terms = {"secret", "mistake", "truth", "nobody", "stop", "why", "how", "instant", "viral", "wrong"}
        hooks = sum(1 for t in tokens[:20] if t in hook_terms)
        caption_density = len(captions) / max(1.0, words / 8.0)
        score = 56.0 + min(18.0, hooks * 4.2) + min(14.0, caption_density * 8.0)
        if has_hook:
            score += 7.0
        if boring_mode:
            score += 4.0
        if words < 40:
            score -= 5.0
        return _clamp(score, 35.0, 98.0)

    def _variant_suggestions(self, score: float, ratio: str) -> List[Dict[str, Any]]:
        return [
            {
                "variant_id": "A",
                "focus": "Hook-heavy opener",
                "first_3s": "Bold hook text + 1.08x speed ramp",
                "caption_style": "Large bottom captions",
                "target_platform": "TikTok/Reels",
                "predicted_uplift_pct": round(min(18.0, max(4.0, (score - 55.0) * 0.28)), 1),
            },
            {
                "variant_id": "B",
                "focus": "Authority clarity",
                "first_3s": "Cleaner intro, no emoji captions",
                "caption_style": "Semi-minimal subtitles + CTA",
                "target_platform": "YouTube Shorts",
                "predicted_uplift_pct": round(min(14.0, max(3.0, (score - 50.0) * 0.20)), 1),
            },
            {
                "variant_id": "RATIO",
                "focus": f"Format test {ratio}",
                "first_3s": "same hook, ratio-only test",
                "caption_style": "same",
                "target_platform": "Cross-platform",
                "predicted_uplift_pct": 3.5,
            },
        ]

    def enhance_pretrimmed_clip(
        self,
        input_path: str,
        output_path: str,
        source_start: float,
        source_end: float,
        transcript: Optional[List[Dict[str, Any]]] = None,
        config: Optional[ClipEditConfig] = None,
        clip_title: str = "",
        precomputed_narrative: Optional[Dict[str, Any]] = None,
        write_metadata_file: bool = True,
        is_free: bool = False,
        cortex_hints: Optional[Dict[str, Any]] = None,
    ) -> EditResult:
        cfg = config or ClipEditConfig()
        _ensure_dir(os.path.dirname(output_path) or ".")
        tmp_files: List[str] = []
        metadata: Dict[str, Any] = {
            "input_path": input_path,
            "output_path": output_path,
            "source_start": float(source_start or 0.0),
            "source_end": float(source_end or 0.0),
            "target_ratio": cfg.target_ratio,
            "features": {
                "captions": bool(cfg.add_captions),
                "active_speaker": bool(cfg.enable_active_speaker),
                "visual_enhance": bool(cfg.enhance_visuals),
                "audio_polish": bool(cfg.enhance_audio),
                "hook_speed_ramp": bool(cfg.enable_hook_speed_ramp),
            },
        }
        profile_enabled = str(os.environ.get("HS_EDIT_PROFILE", "0")).strip().lower() in ("1", "true", "yes", "on")
        t_total = time.perf_counter()
        t_face = 0.0
        t_reframe = 0.0
        t_encode = 0.0

        try:
            # --- CORTEX EDITING HINTS EXTRACTION ---
            _cortex = cortex_hints or {}
            _cortex_active = bool(_cortex.get("cortex_enabled"))
            editing_notes = _cortex.get("editing_notes", {}) if isinstance(_cortex.get("editing_notes"), dict) else {}
            
            pacing_note = str(editing_notes.get("pacing_note", "")).lower().strip()
            subtitle_style = str(editing_notes.get("subtitle_style", "classic")).lower().strip()
            
            if _cortex_active:
                if pacing_note == "fast":
                    cfg.max_caption_words = 3
                    log.info("[WCE-CORTEX] Overriding max_caption_words to 3 based on fast pacing note.")
                elif pacing_note == "slow":
                    cfg.max_caption_words = 9
                    log.info("[WCE-CORTEX] Overriding max_caption_words to 9 based on slow pacing note.")
            # --- END CORTEX EDITING HINTS EXTRACTION ---

            base_meta = self._probe_video(input_path)
            clip_duration = max(0.01, float(base_meta.get("duration") or 0.0))
            if precomputed_narrative and isinstance(precomputed_narrative, dict):
                transcript_window = list(precomputed_narrative.get("transcript_window") or [])
                new_win = []
                for x in transcript_window:
                    xs = _safe_float(x.get("start"), 0.0)
                    xe = _safe_float(x.get("end"), xs)
                    seg_offset = xs - source_start
                    seg_remapped: Dict[str, Any] = {
                        "start": max(0.0, seg_offset),
                        "end": min(clip_duration, xe - source_start),
                        "text": x.get("text", "")
                    }
                    # [FIX] Preserve word-level timestamps — critical for caption sync!
                    # Without this, every caption falls into the dumb equal-division fallback.
                    raw_words = x.get("words", [])
                    if raw_words:
                        remapped_words = []
                        for w in raw_words:
                            ws = _safe_float(w.get("start"), xs)
                            we = _safe_float(w.get("end"), xe)
                            remapped_words.append({
                                "word": w.get("word") or w.get("text", ""),
                                "text": w.get("word") or w.get("text", ""),
                                "start": max(0.0, ws - source_start),
                                "end": min(clip_duration, we - source_start),
                            })
                        seg_remapped["words"] = remapped_words
                    new_win.append(seg_remapped)
                transcript_window = new_win
                boring_mode = bool(precomputed_narrative.get("boring_monologue_detected", False))
                pre_trim = precomputed_narrative.get("trim")
            else:
                transcript_window = self._window_transcript(transcript, source_start, source_end)
                boring_mode = self._is_boring_monologue(transcript_window)
                pre_trim = None
            metadata["boring_monologue_detected"] = bool(boring_mode)
            
            # [WCE-DEBUG] Forensic Trace for Empty Transcripts
            if not transcript_window:
                log.warning(f"[WCE-FORENSIC] transcript_window is EMPTY for {source_start}-{source_end}! Check if transcriber sent valid data.")
            else:
                total_w = sum(len(s.get("words", [])) for s in transcript_window)
                log.info(f"[WCE-FORENSIC] Loaded {total_w} transcript words for {source_start}-{source_end}.")

            if isinstance(pre_trim, dict):
                trim_in = _safe_float(pre_trim.get("in"), 0.0)
                trim_out = _safe_float(pre_trim.get("out"), clip_duration)
                trim_in = _clamp(trim_in, 0.0, max(0.0, clip_duration - 0.2))
                trim_out = _clamp(trim_out, trim_in + 0.2, clip_duration)
            else:
                trim_in, trim_out = self._trim_bounds(
                    clip_duration=clip_duration,
                    source_start=source_start,
                    source_end=source_end,
                    transcript_window=transcript_window,
                    config=cfg,
                    clip_path=input_path,
                    full_transcript=transcript or [],
                )
                
            def snap_to_word_boundary(time_s: float, words: list, direction="left") -> float:
                if direction == "left":
                    candidates = [w for w in words if w["start"] >= time_s - 0.3]
                    return candidates[0]["start"] if candidates else time_s
                else:
                    candidates = [w for w in words if w["end"] <= time_s + 0.3]
                    return candidates[-1]["end"] if candidates else time_s

            all_words = []
            for s in transcript_window:
                all_words.extend(s.get("words", []))
                
            if all_words:
                snapped_in = snap_to_word_boundary(trim_in, all_words, "left")
                snapped_out = snap_to_word_boundary(trim_out, all_words, "right")
                
                if snapped_in != trim_in:
                    cw = next((w for w in all_words if w["start"] == snapped_in), {})
                    log.info(f"[CAPTION_SNAP] start={trim_in:.2f} -> snapped={snapped_in:.2f} (word: '{cw.get('word', cw.get('text', ''))}')")
                    trim_in = snapped_in
                    
                if snapped_out != trim_out:
                    cw = next((w for w in all_words if w["end"] == snapped_out), {})
                    log.info(f"[CAPTION_SNAP] end={trim_out:.2f} -> snapped={snapped_out:.2f} (word: '{cw.get('word', cw.get('text', ''))}')")
                    trim_out = snapped_out

            metadata["trim"] = {"in": round(trim_in, 3), "out": round(trim_out, 3)}

            work_a = input_path
            if (trim_in > 0.08 or (clip_duration - trim_out) > 0.08) and (trim_out - trim_in) > 1.0:
                cut_path = os.path.join(self.work_dir, f"wc_cut_{uuid.uuid4().hex}.mp4")
                self._cut_with_fade(input_path, cut_path, trim_in, trim_out)
                tmp_files.append(cut_path)
                work_a = cut_path
                clip_duration = max(0.01, trim_out - trim_in)

            speed_path = os.path.join(self.work_dir, f"wc_speed_{uuid.uuid4().hex}.mp4")
            ramp_window, ramped_duration = self._apply_hook_speed_ramp(work_a, speed_path, clip_duration, cfg)
            tmp_files.append(speed_path)
            work_b = speed_path
            metadata["hook_ramp"] = {"window_s": round(ramp_window, 3), "speed": round(cfg.hook_ramp_speed, 3)}

            # ── Hook Zoom (GPU-accelerated punch-in at clip start) ─────────────────
            if cfg.enable_hook_zoom:
                zoom_path = os.path.join(self.work_dir, f"wc_zoom_{uuid.uuid4().hex}.mp4")
                self._apply_hook_zoom(work_b, zoom_path, ramped_duration, cfg)
                tmp_files.append(zoom_path)
                work_b = zoom_path
                metadata["hook_zoom"] = {
                    "scale": round(cfg.hook_zoom_scale, 3),
                    "duration_s": round(cfg.hook_zoom_duration_s, 3),
                }
                log.info(
                    "[HOOK_ZOOM] ✓ punch-in %.2fx / %.2fs applied",
                    cfg.hook_zoom_scale, cfg.hook_zoom_duration_s,
                )

            t0 = time.perf_counter()
            work_meta = self._probe_video(work_b)
            t_reframe += time.perf_counter() - t0

            video_fmt = None
            if cfg.enable_active_speaker and cfg.enable_format_detection:
                t0 = time.perf_counter()
                video_fmt = self._analyze_video_format(work_b)
                t_face += time.perf_counter() - t0
                metadata["video_format"] = video_fmt.format_type
                metadata["speaker_positions"] = video_fmt.speaker_positions
                log.info(
                    "[WCE-FORMAT] format=%s avg_faces=%.2f speakers=%s",
                    video_fmt.format_type, video_fmt.face_count_avg, video_fmt.speaker_positions,
                )
            elif cfg.enable_active_speaker:
                # Legacy: no format detection, use monologue mode only
                t0 = time.perf_counter()
                video_fmt = self._analyze_video_format(work_b)
                t_face += time.perf_counter() - t0

            t0 = time.perf_counter()
            target_wh = self._resolve_ratio(cfg.target_ratio)
            if video_fmt is not None:
                focus_x = self._get_crop_expression(video_fmt, transcript_window, cfg, work_b)
            else:
                focus_x = 0.5
            is_complex_graph, vf = self._build_reframe_filter(work_meta, target_wh, focus_x, cfg, boring_mode)
            t_reframe += time.perf_counter() - t0
            af = self._build_audio_filter(cfg)

            captions: List[CaptionSegment] = []
            if cfg.add_captions:
                captions = self._caption_segments(
                    transcript_window=transcript_window,
                    source_start=source_start,
                    trim_in=trim_in,
                    trim_out=trim_out,
                    config=cfg,
                    ramp_window=ramp_window,
                    video_fmt=video_fmt,
                )
            vf_render = vf
            
            # --- CORTEX EDITING HINTS ---
            # If Groq Cortex ran on this clip, use its creative intelligence
            # for the hook overlay, CTA, and hashtags instead of generic fallbacks.

            # Hook overlay: Groq's opening_caption > title > clip_title > first caption
            if _cortex_active and _cortex.get("opening_caption"):
                hook_line = str(_cortex["opening_caption"]).strip()
                log.info("[WCE-CORTEX] Using Groq opening_caption as hook: %s", hook_line[:60])
            elif _cortex_active and _cortex.get("title"):
                hook_line = str(_cortex["title"]).strip()
                log.info("[WCE-CORTEX] Using Groq title as hook: %s", hook_line[:60])
            else:
                hook_line = clip_title.strip() if clip_title else (captions[0].text if captions else "")

            # CTA: derive context-aware CTA from Groq's hook_type / why_this_clip_works
            if _cortex_active:
                hook_type = str(_cortex.get("hook_type", "")).lower()
                if "curiosity" in hook_type or "mystery" in hook_type:
                    cta_line = "Would you do it? Comment below."
                elif "fear" in hook_type or "risk" in hook_type or "danger" in hook_type:
                    cta_line = "Share this before it's too late."
                elif "reveal" in hook_type or "twist" in hook_type or "surprise" in hook_type:
                    cta_line = "Save this — you'll want to rewatch."
                elif "inspiration" in hook_type or "motivation" in hook_type:
                    cta_line = "Follow for more of these moments."
                elif "confession" in hook_type or "personal" in hook_type:
                    cta_line = "Drop a reaction below."
                else:
                    cta_line = "Follow for more creator breakdowns."
                log.info("[WCE-CORTEX] Using Groq hook_type '%s' -> CTA: %s", hook_type, cta_line)
            else:
                cta_line = "Follow for more creator breakdowns"

            # Hashtags: use cortex topic keywords if available, else auto-extract
            cortex_hashtags = None
            if _cortex_active:
                ls = _cortex.get("learning_signal_for_hotshort", {})
                meaning_pattern = (ls.get("meaning_pattern") or "").strip() if isinstance(ls, dict) else ""
                topic_tags = [
                    w.lower().replace(" ", "")
                    for w in meaning_pattern.split(",")
                    if len(w.strip()) > 3
                ][:3]
                if topic_tags:
                    cortex_hashtags = " ".join(f"#{t}" for t in topic_tags)
                    log.info("[WCE-CORTEX] Using Groq hashtags: %s", cortex_hashtags)
            hashtags_line = (cortex_hashtags or self._extract_hashtags(transcript_window)) if cfg.add_hashtags else None

            # Log cortex usage in metadata
            if _cortex_active:
                metadata["cortex_hints_applied"] = True
                metadata["cortex_hook_type"] = _cortex.get("hook_type", "")
                metadata["cortex_score"] = _cortex.get("cortex_score", 0)
            # --- END CORTEX EDITING HINTS ---

            
            has_any_overlay = (cfg.add_captions and captions) or (cfg.add_dynamic_overlays and hook_line) or (cfg.add_cta and cta_line)
            
            # Derive global speaker_side for hook/CTA positioning (captions use per-event side)
            if video_fmt is not None and video_fmt.format_type == "podcast" and len(video_fmt.speaker_positions) >= 1:
                dom_x = video_fmt.speaker_positions[0]
                speaker_side = "left" if dom_x < 0.45 else ("right" if dom_x > 0.55 else "center")
            elif isinstance(focus_x, list):
                speaker_side = "center" # dynamic over time
            elif isinstance(focus_x, float) and focus_x < 0.42:
                speaker_side = "left"
            elif isinstance(focus_x, float) and focus_x > 0.58:
                speaker_side = "right"
            else:
                speaker_side = "center"

            if has_any_overlay:
                ass_path = os.path.join(self.work_dir, f"wc_subs_{uuid.uuid4().hex}.ass")
                tmp_files.append(ass_path)
                self._write_ass(
                    path=ass_path,
                    width=target_wh[0],
                    height=target_wh[1],
                    duration=max(0.1, ramped_duration),
                    captions=captions,
                    hook_line=hook_line if cfg.add_dynamic_overlays else None,
                    cta_line=cta_line if cfg.add_cta else None,
                    hashtags_line=hashtags_line,
                    subtitle_style=subtitle_style,
                    speaker_side=speaker_side,
                )
                fonts_dir_esc = _ffmpeg_filter_path(_FONTS_DIR)
                ass_esc = _ffmpeg_filter_path(ass_path)
                if is_complex_graph:
                    vf_render = f"{vf_render};[v_reframe]subtitles='{ass_esc}':fontsdir='{fonts_dir_esc}'[v_subs]"
                else:
                    vf_render = f"{vf_render},subtitles='{ass_esc}':fontsdir='{fonts_dir_esc}'"
                    
                # Debug logging...
                if os.path.exists(ass_path):
                    ass_size = os.path.getsize(ass_path)
                    log.info("[WCE-DEBUG] .ass file written OK: %s (%d bytes)", ass_path, ass_size)
                else:
                    log.error("[WCE-DEBUG] .ass file MISSING after _write_ass()! Path: %s", ass_path)

            if is_complex_graph:
                # If we added subtitles, the last pad is [v_subs], otherwise [v_reframe]
                last_pad = "[v_subs]" if has_any_overlay else "[v_reframe]"
                vf_render = f"{vf_render};{last_pad}format=yuv420p[v_fmt]"
            else:
                vf_render = f"{vf_render},format=yuv420p"

            is_watermarked = os.getenv("HS_WATERMARK_ENABLED") == "1" and (os.getenv("HS_WATERMARK_FREE_ONLY", "1") != "1" or is_free)
            wm_path = os.path.abspath("static/branding/logo_icon.png").replace("\\", "/")

            if is_watermarked:
                if is_complex_graph:
                    vf_render = f"{vf_render};[1:v]scale=90:-1[wm];[v_fmt][wm]overlay=W-w-30:H-h-120,drawtext=text='MADE WITH HOTSHORT':fontcolor=white@0.85:fontsize=28:borderw=2:bordercolor=black@0.5:x=w-text_w-25:y=h-80[out_v]"
                else:
                    vf_render = f"[0:v]{vf_render}[v_main];[1:v]scale=90:-1[wm];[v_main][wm]overlay=W-w-30:H-h-120,drawtext=text='MADE WITH HOTSHORT':fontcolor=white@0.85:fontsize=28:borderw=2:bordercolor=black@0.5:x=w-text_w-25:y=h-80[out_v]"
            else:
                if is_complex_graph:
                    vf_render = f"{vf_render};[v_fmt]null[out_v]"
                
            cmd = [
                "ffmpeg",
                "-y",
                "-nostdin",
                *_hwaccel_decode_args(),   # ← GPU decode (NVDEC) — full GPU pipeline
                "-i", work_b
            ]
            
            if is_watermarked:
                cmd.extend(["-i", wm_path])
                
            cmd.extend([
                "-filter_complex" if (is_watermarked or is_complex_graph) else "-vf",
                vf_render,
                "-map", "[out_v]" if (is_watermarked or is_complex_graph) else "0:v:0",
                "-map", "0:a:0?",
                "-r",
                str(max(24, int(cfg.export_fps))),
                *_video_encode_args(
                    crf=int(cfg.quality_crf if cfg.preserve_quality else 24),
                    preset=cfg.quality_preset if cfg.preserve_quality else "veryfast",
                ),
            ])
            if bool(work_meta.get("has_audio")):
                cmd += ["-af", af, "-c:a", "aac", "-b:a", _get_export_audio_bitrate()]
            else:
                cmd += ["-an"]
            cmd.append(output_path)
            
            t0 = time.perf_counter()
            with _GPU_SEMAPHORE:
                gpu_start = time.perf_counter()
                self._run(cmd, timeout_s=220)
                gpu_done = time.perf_counter() - gpu_start
                cpu_done = gpu_start - t_total
                log.info(f"[WCE_PARALLEL] clip={os.path.basename(output_path)} cpu_done={cpu_done:.1f}s gpu_done={gpu_done:.1f}s")
                
            t_encode += time.perf_counter() - t0

            has_hook = bool(clip_title.strip())
            score = self._estimate_engagement(captions, transcript_window, boring_mode=boring_mode, has_hook=has_hook)
            metadata["engagement_score"] = round(score, 2)
            metadata["captions_count"] = len(captions)
            if isinstance(focus_x, str):
                metadata["focus_x"] = "dynamic"
            elif isinstance(focus_x, tuple):
                metadata["focus_x"] = "stacked"
            elif isinstance(focus_x, list):
                metadata["focus_x"] = "dynamic_director"
            else:
                metadata["focus_x"] = round(focus_x, 3)
            metadata["platform_variants"] = self._variant_suggestions(score, cfg.target_ratio) if cfg.generate_ab_suggestions else []
            if profile_enabled:
                total_s = max(0.0, time.perf_counter() - t_total)
                metadata["edit_profile"] = {
                    "reframe_s": round(float(t_reframe), 3),
                    "face_s": round(float(t_face), 3),
                    "encode_s": round(float(t_encode), 3),
                    "total_s": round(float(total_s), 3),
                }
                log.info(
                    "[EDIT-PROFILE] reframe=%.2fs face=%.2fs encode=%.2fs total=%.2fs",
                    float(t_reframe),
                    float(t_face),
                    float(t_encode),
                    float(total_s),
                )

            if write_metadata_file:
                meta_path = os.path.splitext(output_path)[0] + ".json"
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(metadata, f, ensure_ascii=False, indent=2)

            return EditResult(output_path=output_path, engagement_score=score, metadata=metadata)
        finally:
            if not self.keep_debug_files:
                for p in tmp_files:
                    try:
                        if os.path.exists(p):
                            os.remove(p)
                    except Exception:
                        pass
