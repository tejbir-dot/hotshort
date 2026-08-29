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
try:
    import bolt
except ImportError:
    bolt = None
from effects.format_analyzer import detect_faces_multi_haar
from effects.face_tracker import FaceTracker, SmoothedPosition
from effects import debug_visualizer
from effects.b_roll_engine import fetch_b_roll_for_keywords
import time

@dataclass
class DirectorSegment:
    start_t: float
    end_t: float
    mode: str
    active_speaker: str
    crop_x: float
    left_x: float
    right_x: float
    # Per-frame face-tracking timeline: list of {t, solo_x, left_x, right_x}
    # Used by _build_reframe_filter to generate smooth per-frame crop expressions.
    frame_timeline: list = field(default_factory=list)

# Global semaphore to ensure only one GPU encode runs at a time (e.g. for GTX 1630)
_GPU_SEMAPHORE = threading.Semaphore(1)

try:
    import cv2
except Exception:
    cv2 = None

try:
    import mediapipe as mp  # type: ignore
except Exception:
    mp = None

try:
    from transformers import pipeline as hf_pipeline
except Exception:
    hf_pipeline = None

# Font directory: platform-aware (Linux RunPod vs Windows local)
# On Linux: /usr/share/fonts/truetype/montserrat (Dockerfile COPY path)
# On Windows: C:/Windows/Fonts (system fonts, always present)
# Override via HS_FONTS_DIR env var.
import platform as _platform
_DEFAULT_FONTS_DIR = (
    "C:/Windows/Fonts"
    if _platform.system() == "Windows"
    else "/usr/share/fonts/truetype/montserrat"
)
if os.path.exists("./fonts"):
    _FONTS_DIR = os.environ.get("HS_FONTS_DIR", os.path.abspath("./fonts"))
else:
    _FONTS_DIR = os.environ.get("HS_FONTS_DIR", _DEFAULT_FONTS_DIR)

log = logging.getLogger("world_class_editor")

# Face-cache cluster locks stabilize the crop anchor between scene changes.
ENABLE_CLUSTER_SCAN = os.getenv("HS_ENABLE_CLUSTER_SCAN", "1").strip().lower() not in ("0", "false", "no", "off")
CLUSTER_TRANSITION_FRAMES = max(1, int(os.getenv("HS_CLUSTER_TRANSITION_FRAMES", "12") or 12))
# Director-loop face height guard: 7% of frame height.
# At 1080p: 7% = 75px minimum. Talking-head speakers in wide shots are 8-50%.
# Rejects text/logo/mic false positives (40-60px) while accepting real faces in
# wide-angle podcast frames (86px+). Empirically validated on test clips.
MIN_VALID_FACE_HEIGHT_RATIO = min(1.0, max(0.0, float(os.getenv("HS_MIN_FACE_HEIGHT_RATIO", "0.07") or 0.07)))
MAX_VALID_FACE_HEIGHT_RATIO = min(1.0, max(0.0, float(os.getenv("HS_MAX_FACE_HEIGHT_RATIO", "0.60") or 0.60)))

def _nvenc_available() -> bool:
    """Probe once whether h264_nvenc is usable on this system."""
    force_env = os.environ.get("HS_FORCE_NVENC", "").strip().lower()
    if force_env in ("1", "true", "yes"):
        log.info("[WCE] NVENC forced via HS_FORCE_NVENC=1")
        return True
    if force_env in ("0", "false", "no"):
        return False
    if not hasattr(_nvenc_available, "_cached"):
        try:
            r = subprocess.run(
                ["ffmpeg", "-hide_banner", "-f", "lavfi", "-i",
                 "nullsrc=s=64x64:d=0.1", "-c:v", "h264_nvenc",
                 "-f", "null", "-"],
                capture_output=True, timeout=10,
            )
            # On Windows, the null muxer exits with code 1 even on success.
            # Use stderr text to confirm h264_nvenc was actually initialised.
            combined = (r.stdout + r.stderr).decode("utf-8", errors="replace")
            _nvenc_available._cached = (
                r.returncode == 0
                or "h264_nvenc" in combined.lower()
            )
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


def _ffmpeg_decoder_available(decoder_name: str) -> bool:
    cache_name = f"_decoder_{decoder_name}_cached"
    if not hasattr(_ffmpeg_decoder_available, cache_name):
        available = False
        try:
            r = subprocess.run(
                ["ffmpeg", "-hide_banner", "-decoders"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            available = r.returncode == 0 and decoder_name in (r.stdout or "")
        except Exception:
            available = False
        setattr(_ffmpeg_decoder_available, cache_name, available)
        log.info("[WCE] FFmpeg decoder %s available: %s", decoder_name, available)
    return bool(getattr(_ffmpeg_decoder_available, cache_name))


def _input_video_codec(path: Optional[str]) -> str:
    if not path:
        return ""
    try:
        out = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_name,pix_fmt",
                "-of",
                "default=nokey=0:noprint_wrappers=1",
                path,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        codec = ""
        pix_fmt = ""
        for line in (out.stdout or "").splitlines():
            if line.startswith("codec_name="):
                codec = line.split("=", 1)[1].strip().lower()
            elif line.startswith("pix_fmt="):
                pix_fmt = line.split("=", 1)[1].strip().lower()
        # av1_cuvid does NOT support yuv420p chroma — pre-emptively mark it broken
        # so we never waste a failed FFmpeg attempt on this machine/build.
        if codec == "av1" and pix_fmt == "yuv420p" and not _AV1_HWDECODE_KNOWN_BROKEN:
            log.info(
                "[AV1_HWDECODE] pix_fmt=yuv420p is unsupported by av1_cuvid on this build — "
                "skipping CUDA decode path to avoid wasted retry."
            )
            _mark_av1_hwdecode_broken()
        return codec
    except Exception:
        return ""


_AV1_HWDECODE_KNOWN_BROKEN = False  # becomes True after first confirmed failure

def _should_try_av1_hwdecode():
    global _AV1_HWDECODE_KNOWN_BROKEN
    return not _AV1_HWDECODE_KNOWN_BROKEN

def _mark_av1_hwdecode_broken():
    global _AV1_HWDECODE_KNOWN_BROKEN
    _AV1_HWDECODE_KNOWN_BROKEN = True
    print("[AV1_HWDECODE] marked broken for this run — all subsequent clips use CPU decode directly")


def _hwaccel_decode_args(input_path: Optional[str] = None) -> List[str]:
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
    codec = _input_video_codec(input_path)
    if codec == "av1":
        if os.environ.get("HS_ENABLE_AV1_NVDEC", "0").strip().lower() in ("1", "true", "yes"):
            if _should_try_av1_hwdecode() and _ffmpeg_decoder_available("av1_cuvid"):
                log.info("[WCE] input codec=av1; using AV1 NVDEC decode via av1_cuvid")
                return ["-hwaccel", "cuda", "-hwaccel_output_format", "nv12", "-c:v", "av1_cuvid"]
            log.info("[WCE] input codec=av1; HS_ENABLE_AV1_NVDEC=1 but av1_cuvid is unavailable or marked broken")
        log.info("[WCE] input codec=av1; using CPU decode while keeping NVENC encode when available")
        return []
    if _nvdec_available():
        return ["-hwaccel", "cuda", "-hwaccel_output_format", "nv12"]
    return []



def _get_export_crf(default: int = 20) -> int:
    """Read CRF from env: HS_EXPORT_CRF (default 20)."""
    try:
        return int(os.environ.get("HS_EXPORT_CRF", str(default)))
    except (ValueError, TypeError):
        return default


def _get_export_preset(default: str = "ultrafast") -> str:
    """Read FFmpeg preset from env: HS_EXPORT_PRESET (default ultrafast for CPU speed)."""
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
        log.info("[WCE] encode=NVENC codec=h264_nvenc")
        return [
            "-c:v", "h264_nvenc",
            "-preset", "fast",
            "-profile:v", "high",
            "-rc", "vbr",
            "-cq", str(_crf),
            "-b:v", "3M",
            "-maxrate", _maxrate,
            "-bufsize", _bufsize,
            "-pix_fmt", "yuv420p",
        ]
    # CPU fallback (libx264)
    log.info("[WCE] encode=CPU codec=libx264")
    return [
        "-c:v", "libx264",
        "-preset", _preset,
        "-crf", str(_crf),
        "-maxrate", _maxrate,
        "-bufsize", _bufsize,
        "-pix_fmt", "yuv420p",
    ]


def _hook_zoom_filter_expr(config: "ClipEditConfig", clip_duration: float) -> Optional[str]:
    if not config.enable_hook_zoom or clip_duration < 2.0:
        return None
    scale = _clamp(config.hook_zoom_scale, 1.01, 1.30)
    dur = _clamp(config.hook_zoom_duration_s, 0.3, min(3.0, clip_duration * 0.4))
    d = round(dur, 4)
    s = round(scale, 4)
    crop_w = f"iw/({s}-({s}-1)*min(t/{d}\\,1))"
    crop_h = f"ih/({s}-({s}-1)*min(t/{d}\\,1))"
    crop_x = f"(iw-{crop_w})/2"
    crop_y = f"(ih-{crop_h})/2"
    return (
        f"crop=w='{crop_w}':h='{crop_h}':x='{crop_x}':y='{crop_y}',"
        "scale=iw:ih:flags=lanczos"
    )


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
    enable_hook_zoom: bool = False           # subtle punch-in zoom when clip starts
    hook_zoom_scale: float = 1.08          # start zoom (1.08 = 8% tighter than final frame)
    hook_zoom_duration_s: float = 1.2      # seconds to ease from zoomed-in → normal
    # ── Color grading ────────────────────────────────────────────────────────────
    enable_color_grade: bool = True        # professional color grading (inline, zero extra pass)
    color_grade_preset: str = "premium"    # "premium" | "warm" | "cool" | "clean"
    enable_vignette: bool = True           # subtle edge darkening for cinematic depth
    # ── Distribution branding (merge into WCE pass) ─────────────────────────────
    apply_distribution_branding: bool = False  # merge blur+watermark+outro into this pass
    branding_watermark_path: str = ""      # abs path to logo.png
    branding_outro_path: str = ""          # abs path to outro.mp4 (empty = skip outro)


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
        if bolt and cmd and "ffmpeg" in str(cmd[0]).lower():
            bolt.emit("ffmpeg_encode")
        try:
            res = subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=timeout_s)
            if res.stderr:
                sys.stderr.write(res.stderr)
        except subprocess.CalledProcessError as exc:
            if exc.stderr:
                sys.stderr.write(exc.stderr)
                if "Codec av1_cuvid is not supported with this chroma format" in exc.stderr:
                    _mark_av1_hwdecode_broken()
            
            last_exc = exc
            if self._uses_cuda_decode(cmd):
                log.warning("[WCE] CUDA decode failed; retrying same FFmpeg command with CPU decode")
                cmd = self._without_cuda_decode(cmd)
                try:
                    res = subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=timeout_s)
                    return
                except subprocess.CalledProcessError as exc_decode:
                    last_exc = exc_decode
                    if exc_decode.stderr:
                        sys.stderr.write(exc_decode.stderr)

            if self._uses_nvenc_encode(cmd):
                log.warning("[WCE] NVENC encode failed (session limit or unsupported params); retrying with CPU encode")
                fallback_cmd = self._without_nvenc_encode(cmd)
                try:
                    subprocess.run(fallback_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=timeout_s)
                    return
                except subprocess.CalledProcessError as exc_encode:
                    last_exc = exc_encode
                    
            raise RuntimeError(f"FFmpeg failed with exit code {last_exc.returncode}:\n{last_exc.stderr}") from last_exc

    @staticmethod
    def _uses_cuda_decode(cmd: List[str]) -> bool:
        if "-hwaccel" in cmd and "cuda" in cmd:
            return True
        return any(
            cmd[index] == "-c:v"
            and index + 1 < len(cmd)
            and str(cmd[index + 1]).endswith("_cuvid")
            for index in range(len(cmd))
        )

    @staticmethod
    def _uses_nvenc_encode(cmd: List[str]) -> bool:
        return any(
            cmd[index] == "-c:v"
            and index + 1 < len(cmd)
            and str(cmd[index + 1]).endswith("_nvenc")
            for index in range(len(cmd))
        )

    @staticmethod
    def _without_nvenc_encode(cmd: List[str]) -> List[str]:
        new_cmd = []
        skip_next = False
        for i, val in enumerate(cmd):
            if skip_next:
                skip_next = False
                continue
            if val == "h264_nvenc":
                new_cmd.append("libx264")
            elif val == "hevc_nvenc":
                new_cmd.append("libx265")
            elif val == "-preset" and i+1 < len(cmd) and cmd[i+1] in ("p1", "p2", "p3", "p4", "p5", "p6", "p7", "fast"):
                new_cmd.append("-preset")
                new_cmd.append("veryfast")
                skip_next = True
            elif val == "-rc":
                skip_next = True
            elif val == "vbr" and i > 0 and cmd[i-1] == "-rc":
                continue
            elif val == "-cq":
                new_cmd.append("-crf")
            elif val == "-b:v" and i+1 < len(cmd) and cmd[i+1] == "3M":
                # Drop NVENC specific target bitrate logic for VBR
                skip_next = True
            else:
                new_cmd.append(val)
        return new_cmd

    @staticmethod
    def _without_cuda_decode(cmd: List[str]) -> List[str]:
        out: List[str] = []
        i = 0
        while i < len(cmd):
            if cmd[i] == "-hwaccel" and i + 1 < len(cmd):
                i += 2
                continue
            if cmd[i] == "-hwaccel_output_format" and i + 1 < len(cmd):
                i += 2
                continue
            # av1_cuvid is itself a hardware decoder. Leaving it in the retry
            # command means the alleged CPU fallback repeats the same failure.
            if cmd[i] == "-c:v" and i + 1 < len(cmd) and cmd[i + 1] == "av1_cuvid":
                i += 2
                continue
            out.append(cmd[i])
            i += 1
        return out

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
        segs_without_words = sum(1 for item in win if not item.get("words"))
        n_words = sum(len(item.get("words", [])) for item in win) if any(item.get("words") for item in win) else sum(len((item.get("text") or "").split()) for item in win)
        log.info(f"[WCE-SYNC-FORENSIC] _window_transcript: segments={n_segments} words={n_words} missing_words_in_segs={segs_without_words} for clip {clip_start:.2f}-{clip_end:.2f}")
        if segs_without_words > 0:
            log.warning(f"[WCE-SYNC-FORENSIC] WARNING: {segs_without_words}/{n_segments} segments lack 'words' array! They will fall back to math division.")
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
            *_hwaccel_decode_args(input_path),   # GPU decode when supported by input codec
            "-ss",
            f"{start_s:.3f}",
            "-to",
            f"{end_s:.3f}",
            "-i",
            input_path,
            "-af",
            af,
            *_video_encode_args(crf=23, preset="ultrafast"),  # ← CPU encode (ultrafast ~25% faster, imperceptible quality diff)
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

        if bolt:
            bolt.emit("video_open")
        cap = cv2.VideoCapture(clip_path)
        if not cap.isOpened():
            return _null

        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 1000.0
        step = max(1, int(total_frames / 15))

        cascade = None
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
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                faces = detect_faces_multi_haar(gray, cv2, scale_factor=1.15, min_neighbors=3, min_size=(40, 40))
                # Minimum face height for podcast classification: 8% of frame height.
                # Gaming/scene objects and tiny background faces are typically <7%.
                _min_face_h_classify = max(40, int(h * 0.08))
                for x, y, fw, fh in faces:
                    # Guard: too small or off vertical edges
                    if fh < _min_face_h_classify:
                        continue
                    if not (0.05 < (y + fh / 2.0) / h < 0.95):
                        continue
                    # Guard: reject center-zone detections (0.42-0.58 cx ratio).
                    # In 2-person podcasts, speakers are on left/right sides (not center).
                    # Center-zone faces are almost always FPs (game objects, tables, etc.).
                    _cx_ratio = (x + fw / 2.0) / float(w)
                    if 0.42 <= _cx_ratio <= 0.58:
                        continue  # center FP — skip for podcast classification
                    # Guard: reject bright light sources (lamps, ring-lights, globes).
                    # Real skin: gray mean 55-145. Lamps: >185.
                    try:
                        _roi_mean = float(gray[int(y):int(y + fh), int(x):int(x + fw)].mean())
                    except Exception:
                        _roi_mean = 0.0
                    if _roi_mean > 185.0:
                        continue  # bright object — not a face
                    face_xs.append(_clamp(_cx_ratio, 0.0, 1.0))

                if face_xs:
                    samples.append((target_frame / fps, face_xs))
        finally:
            cap.release()

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
        # Per-frame bimodal check: count frames where BOTH a left AND right face
        # were detected simultaneously. This is more robust than pooling all xs.
        frames_with_both = sum(
            1 for _, fxs in samples
            if any(x < 0.45 for x in fxs) and any(x > 0.55 for x in fxs)
        )
        co_occ_rate = frames_with_both / max(1, len(samples))
        is_bimodal = (
            (len(left_xs) >= 2 and len(right_xs) >= 2) or  # enough face samples on both sides
            (co_occ_rate >= 0.15)                           # OR >=15% frames had both speakers
        )
        log.info(
            "[WCE-FORMAT] bimodal_check: left=%d right=%d co_occ_frames=%d/%d (%.2f) is_bimodal=%s",
            len(left_xs), len(right_xs), frames_with_both, len(samples), co_occ_rate, is_bimodal
        )

        if is_bimodal:
            lc = (sum(left_xs) / len(left_xs)) if left_xs else 0.25
            rc = (sum(right_xs) / len(right_xs)) if right_xs else 0.75
            spk_positions = [round(lc, 3), round(rc, 3)]
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

    def _get_crop_expression(self, video_fmt, transcript_window, config, clip_path=None, face_cache=None):
        """VideoFormat -> FFmpeg crop_x expression.
        monologue: EMA lerp (smooth, stable).
        podcast active: hard jump at transcript boundaries (true active speaker).
        motion_graphic / fast_cuts: fixed 0.5.
        """
        fmt = video_fmt.format_type

        cap = None
        fps = 25.0
        frame_width = 1920
        frame_height = 1080

        if clip_path and cv2 is not None:
            try:
                if bolt:
                    bolt.emit("video_open")
                cap = cv2.VideoCapture(clip_path)
                fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
                frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1920)
                frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1080)
            except Exception:
                cap = None

        if fmt in ("motion_graphic", "fast_cuts"):
            if cap: cap.release()
            return 0.5

        if fmt == "monologue":
            if cap: cap.release()
            if face_cache and len(face_cache) > 0:
                # Mode A (Monologue) with FaceCache (Anchor Only):
                # No audio-switching needed (single speaker). Simply update anchor position per scene-segment!
                # QUALITY GATE: only use face_cache if we have genuinely large faces.
                # If Haar only detected tiny background people (h < 10% frame), fall through to EMA.
                _face_quality_threshold = frame_height * 0.10  # 10% = 108px at 1080p
                _all_max_faces = []
                for t_rel, faces in face_cache.items():
                    if not faces:
                        continue
                    f = max(faces, key=lambda item: item['w'] * item['h'])
                    _all_max_faces.append(f['h'])
                _median_face_h = sorted(_all_max_faces)[len(_all_max_faces) // 2] if _all_max_faces else 0
                log.info(
                    "[WCE-VISUAL] monologue face_cache check: median_largest_face_h=%.0fpx threshold=%.0fpx frames=%d",
                    _median_face_h, _face_quality_threshold, len(_all_max_faces)
                )

                if _median_face_h >= _face_quality_threshold:
                    clusters_map = {}
                    for t_rel, faces in face_cache.items():
                        if not faces:
                            continue
                        f = max(faces, key=lambda item: item['w'] * item['h'])
                        # Skip this frame if the best face is still tiny (background noise)
                        if f['h'] < _face_quality_threshold * 0.7:
                            continue
                        cid = f.get("_cluster_id", 0)
                        cend = f.get("_cluster_end", int(t_rel * fps)) / max(1.0, float(fps))
                        cx = (f['x'] + f['w'] / 2.0) / max(1.0, float(frame_width))
                        if cid not in clusters_map:
                            clusters_map[cid] = {"end_t": cend, "x_vals": []}
                        clusters_map[cid]["x_vals"].append(cx)
                        clusters_map[cid]["end_t"] = max(clusters_map[cid]["end_t"], cend)

                    if clusters_map:
                        sorted_clusters = sorted(clusters_map.items(), key=lambda item: item[0])
                        cluster_anchors = [
                            (data["end_t"], _clamp(sum(data["x_vals"]) / len(data["x_vals"]), 0.15, 0.85))
                            for _, data in sorted_clusters if data["x_vals"]
                        ]
                        if len(cluster_anchors) == 1:
                            log.info("[WCE-VISUAL] mode=MONOLOGUE_ANCHOR_SINGLE x=%.3f", cluster_anchors[0][1])
                            return cluster_anchors[0][1]
                        elif len(cluster_anchors) > 1:
                            log.info("[WCE-VISUAL] mode=MONOLOGUE_ANCHOR_SEGMENTED clusters=%d", len(cluster_anchors))
                            expr = str(round(cluster_anchors[-1][1], 3))
                            for i in range(len(cluster_anchors) - 2, -1, -1):
                                end_t, x_val = cluster_anchors[i]
                                expr = "if(lt(t,%s),%s,%s)" % (round(end_t, 3), round(x_val, 3), expr)
                            return expr
                else:
                    log.info(
                        "[WCE-VISUAL] face_cache REJECTED (tiny faces=%.0fpx < threshold=%.0fpx) "
                        "— falling back to format_analyzer EMA",
                        _median_face_h, _face_quality_threshold
                    )

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

            if not cap or not cap.isOpened():
                return 0.5

            # ── Tunable constants (env-overridable) ──────────────────────────────
            TALKING_THRESHOLD = float(os.environ.get("HS_TALKING_THRESHOLD", "80"))
            VOTE_WINDOW_S = float(os.environ.get("HS_VOTE_WINDOW_S", "2.0"))       # 2s window → mode flip needs sustained 2s evidence
            MIN_SOLO_DURATION_S = float(os.environ.get("HS_MIN_SOLO_S", "2.5"))    # raised 1.5→2.5s: brief detections can't cause cuts
            EMA_ALPHA = float(os.environ.get("HS_EMA_ALPHA", "0.20"))  # mouth EMA rise speed
            EMA_FLOOR = float(os.environ.get("HS_EMA_FLOOR", "0.0"))   # prevent crash to 0 on scene cuts
            SMOOTH_ALPHA = 0.07        # position smoothing (ultra-smooth camera pan)

            active_detector = None
            if False and mp is not None:
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

            def is_valid_face(det, _log_reason=False, frame=None):
                """Filter: reject mics, hands, logos, background objects.

                Guards (all must pass):
                  1. Height in [MIN_VALID_FACE_HEIGHT_RATIO, MAX_VALID_FACE_HEIGHT_RATIO]
                  2. Aspect ratio w/h in [0.60, 1.45]  — real faces are near-square
                  3. Vertical centroid cy in [12%, 92%]  — logos sit at top-center
                  4. Horizontal centroid cx in [3%, 97%] — avoid extreme-edge noise
                  5. Face ROI brightness < 185 (mean gray) — rejects lamp/light-source FPs
                     Lamps: round bright objects (glob lights, ring lights) pass all shape
                     guards but are pure white. Real skin: 60-140 gray mean.
                """
                h = det['h']
                w = det['w']
                x = det['x']
                y = det['y']
                min_h = frame_height * MIN_VALID_FACE_HEIGHT_RATIO
                max_h = frame_height * MAX_VALID_FACE_HEIGHT_RATIO

                # ── guard 1: height range ────────────────────────────────────────
                if h < min_h:
                    if _log_reason:
                        log.info(
                            f"[FACE_FILTER] REJECT too_small  h={h:.0f}px "
                            f"min={min_h:.0f}px  face=({x:.0f},{y:.0f},{w:.0f},{h:.0f})"
                        )
                    return False
                if h > max_h:
                    if _log_reason:
                        log.info(
                            f"[FACE_FILTER] REJECT too_big    h={h:.0f}px "
                            f"max={max_h:.0f}px  face=({x:.0f},{y:.0f},{w:.0f},{h:.0f})"
                        )
                    return False

                # ── guard 2: aspect ratio ─────────────────────────────────────────
                # Faces: 0.60–1.45. Mics/hands: <0.55 (tall-narrow). Wide logos: >1.5
                aspect_wh = w / max(1.0, h)
                if aspect_wh < 0.60 or aspect_wh > 1.45:
                    if _log_reason:
                        log.info(
                            f"[FACE_FILTER] REJECT bad_aspect wh={aspect_wh:.2f} "
                            f"face=({x:.0f},{y:.0f},{w:.0f},{h:.0f})"
                        )
                    return False

                # ── guard 3: vertical position (reject top logo zone) ─────────────
                # Logos / watermarks cluster in top 10-12% of frame.
                # Real speakers in podcast/monologue sit between 12%-92%.
                cy = y + h / 2.0
                if cy < frame_height * 0.12 or cy > frame_height * 0.92:
                    if _log_reason:
                        log.info(
                            f"[FACE_FILTER] REJECT edge_cy    cy={cy:.0f}px "
                            f"limits=({frame_height*0.12:.0f},{frame_height*0.92:.0f}) "
                            f"face=({x:.0f},{y:.0f},{w:.0f},{h:.0f})"
                        )
                    return False

                # ── guard 4: horizontal position (reject extreme edges) ───────────
                cx = x + w / 2.0
                if cx < frame_width * 0.03 or cx > frame_width * 0.97:
                    if _log_reason:
                        log.info(
                            f"[FACE_FILTER] REJECT edge_cx    cx={cx:.0f}px "
                            f"limits=({frame_width*0.03:.0f},{frame_width*0.97:.0f}) "
                            f"face=({x:.0f},{y:.0f},{w:.0f},{h:.0f})"
                        )
                    return False

                # ── guard 5: brightness — reject lamps, ring-lights, logos ────────
                _BASE_BRIGHT_REJECT = float(os.environ.get("HS_FACE_BRIGHT_REJECT", "185"))
                if frame is not None:
                    try:
                        _frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                        _frame_mean = float(_frame_gray.mean())
                        _adaptive_thresh = max(_BASE_BRIGHT_REJECT, _frame_mean + 45.0)

                        _roi_gray = cv2.cvtColor(
                            frame[int(y):int(y + h), int(x):int(x + w)],
                            cv2.COLOR_BGR2GRAY,
                        )
                        _roi_mean = float(_roi_gray.mean())
                        if _roi_mean > _adaptive_thresh:
                            if _log_reason:
                                log.info(
                                    f"[FACE_FILTER] REJECT bright_src roi_mean={_roi_mean:.1f} "
                                    f"thresh={_adaptive_thresh:.1f} (frame={_frame_mean:.1f}) "
                                    f"face=({x:.0f},{y:.0f},{w:.0f},{h:.0f})"
                                )
                            return False

                        # ── guard 6: Laplacian variance ───────────────────────────
                        # Real faces have medium-frequency texture (skin, hair, eyes):
                        #   Laplacian variance ≈ 50-800.
                        # Bookshelves/text backgrounds have very high-frequency edges:
                        #   Laplacian variance > 1200.
                        # Flat walls / plain background have near-zero edges:
                        #   Laplacian variance < 25.
                        _LAP_MIN = float(os.environ.get("HS_FACE_LAP_MIN", "25"))
                        _LAP_MAX = float(os.environ.get("HS_FACE_LAP_MAX", "1200"))
                        _lap_var = float(
                            cv2.Laplacian(_roi_gray, cv2.CV_64F).var()
                        )
                        if _lap_var < _LAP_MIN or _lap_var > _LAP_MAX:
                            if _log_reason:
                                log.info(
                                    f"[FACE_FILTER] REJECT laplacian  lap_var={_lap_var:.1f} "
                                    f"range=[{_LAP_MIN:.0f},{_LAP_MAX:.0f}] "
                                    f"face=({x:.0f},{y:.0f},{w:.0f},{h:.0f})"
                                )
                            return False

                    except Exception:
                        pass  # ROI out-of-bounds on edge clips — skip gracefully

                if _log_reason:
                    log.info(
                        f"[FACE_FILTER] OK  h={h:.0f}px aspect={aspect_wh:.2f} "
                        f"cy={cy:.0f} cx={cx:.0f}  face=({x:.0f},{y:.0f},{w:.0f},{h:.0f})"
                    )
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

            # ── State initialisation ───────────────────────────────────────────
            SPLIT_MIN_GAP = float(os.environ.get("HS_SPLIT_MIN_GAP", str(config.split_min_gap_ratio)))
            frame_stats = []
            prev_gray = None
            frame_idx = 0
            # Seed speaker position once — both solo_x AND last_mode use the same value.
            _spk = video_fmt.speaker_positions if video_fmt and video_fmt.speaker_positions else [0.5]
            _seed_x = float(statistics.median(_spk)) if _spk else 0.5

            # Seed last_mode from format_analyzer dominant speaker side.
            # If median speaker position is far left (<0.38) → SOLO_LEFT,
            # far right (>0.62) → SOLO_RIGHT, otherwise ACTIVE_CENTER.
            # ACTIVE_CENTER is safer: it keeps the full frame visible until
            # the first real Haar detection fires (frame 0 or frame 5).
            if _seed_x < 0.38:
                last_mode = "SOLO_LEFT"
            elif _seed_x > 0.62:
                last_mode = "SOLO_RIGHT"
            else:
                last_mode = "ACTIVE_CENTER"  # safe fallback — no face bias at start
            log.info(f"[INIT] last_mode seeded={last_mode} speaker_positions={_spk} median={_seed_x:.3f}")


            ema_mouth_left = 0.0
            ema_mouth_right = 0.0
            smoothed_left_x = frame_width * 0.25
            smoothed_right_x = frame_width * 0.75
            
            # Physics Engine state variables
            vel_left = 0.0
            vel_right = 0.0
            vel_solo = 0.0
            
            def apply_deadzone_physics(cam_x, vel, target_x, f_width, log_prefix="SOLO", f_idx=0):
                if target_x is None or target_x == 0:
                    return cam_x, vel * 0.85
                
                deadzone = f_width * 0.10  # 20% total safe zone (10% each side)
                dist = target_x - cam_x
                
                state_str = "TRIPOD_LOCK"
                if abs(dist) < deadzone:
                    vel *= 0.5  # Tripod mode: heavy friction inside safe zone
                else:
                    state_str = "SPRING_PAN"
                    overshoot = abs(dist) - deadzone
                    # Guardrail 2: Hard cap on overshoot to prevent False-Positive spikes from exploding force
                    overshoot = min(overshoot, f_width * 0.3) 
                    
                    # Non-linear spring tension
                    force = (overshoot ** 1.2) * 0.005 
                    vel += force * (1 if dist > 0 else -1)
                
                vel *= 0.82  # Global friction to prevent endless bouncing
                cam_x += vel
                
                # Guardrail 1: Boundary Clamping to prevent camera from leaving the 16:9 canvas
                cam_x = max(f_width * 0.1, min(f_width * 0.9, cam_x))
                
                # Concrete tracking log so user can see it working!
                if f_idx % 50 == 0:
                    log.info(f"[CAPCUT_TRACKER] {log_prefix} State={state_str} Dist={int(dist)}px Vel={vel:.2f} CamX={int(cam_x)}")
                    
                return cam_x, vel

            # Seed solo_x from format_analyzer speaker_positions (not hardcoded center).
            # When director loop finds 0 faces (B-roll, small face, etc.), the crop
            # still starts at the correct position rather than defaulting to logo-zone.
            smoothed_solo_x = frame_width * _seed_x
            log.info(f"[INIT] solo_x seeded={_seed_x:.3f} px={smoothed_solo_x:.0f}")
            last_raw_faces = []
            locked_cluster_id = None
            locked_cluster_slot = None
            locked_solo_x = None
            cluster_transition_from_x = smoothed_solo_x
            cluster_transition_remaining = 0
            _first_lock_done = False
            last_solo_slot = None
            # Slot stability counters (used by mouth-motion EMA gating below)
            _left_stable = 0
            _right_stable = 0
            box_stability_map = {}
            smoothed_face_h = None  # Temporal face-size EMA (pixels). Seeded on first valid detection.
            
            ENABLE_CONTINUOUS_TRACKING = False

            # ── Mode switch gating state ──────────────────────────────────────────
            # Tracks how many consecutive frames a pending mode switch has been requested.
            # Only commits after HS_MIN_SWITCH_FRAMES frames to prevent FP jitter.
            import types as _types
            _decide_mode_state = _types.SimpleNamespace(pending_mode=None, pending_count=0)


            # ── Debug visualizer session (no-op when HS_DEBUG_FRAMES not set) ────
            _clip_id = os.path.splitext(os.path.basename(clip_path or "clip"))[0]
            _dbg = debug_visualizer.make_session(
                clip_id=_clip_id,
                clip_start=0.0,
                clip_end=0.0,
            )
            left_tracker = FaceTracker("left")
            right_tracker = FaceTracker("right")
            left_tracker_smooth = SmoothedPosition(alpha=0.3)
            right_tracker_smooth = SmoothedPosition(alpha=0.3)
            solo_tracker_smooth = SmoothedPosition(alpha=0.3)
            tracking_time = 0.0
            tracking_frames = 0
            haar_redetects = 0

            # Pre-sort face_cache keys once — enables O(log n) bisect lookup
            # instead of O(n) min() scan on every frame.
            import bisect as _bisect
            _fc_times: list = []
            if face_cache:
                _fc_times = sorted(face_cache.keys())

            def _nearest_cache_t(t: float) -> float:
                """Binary-search the sorted cache key list for the nearest timestamp."""
                if not _fc_times:
                    return 0.0
                idx = _bisect.bisect_left(_fc_times, t)
                if idx == 0:
                    return _fc_times[0]
                if idx == len(_fc_times):
                    return _fc_times[-1]
                before = _fc_times[idx - 1]
                after  = _fc_times[idx]
                return before if (t - before) <= (after - t) else after

            # ── FRAME STRIDING ─────────────────────────────────────────────
            # Instead of decoding every frame (expensive at 25fps × 70s = 1750 frames),
            # we skip N-1 frames using cap.grab() (reads but doesn't decode) and fully
            # decode only every Nth frame. face_cache is position-stamped so skipping
            # frames doesn't affect crop quality. Mouth EMA still works because we
            # scale the decay factor by stride so 1-frame EMA ≈ N-frame stride EMA.
            # Default stride=3 → ~3x speedup on director loop, ~40s saved per 70s clip.
            _DIRECTOR_STRIDE = max(1, int(os.environ.get("HS_DIRECTOR_FRAME_STRIDE", "3") or "3"))
            log.info("[WCE_PERF] director_frame_stride=%d (1=every frame, 3=every 3rd)", _DIRECTOR_STRIDE)

            while True:
                if _DIRECTOR_STRIDE > 1 and frame_idx > 0:
                    # Skip _DIRECTOR_STRIDE-1 frames cheaply (grab reads but doesn't decode)
                    for _skip in range(_DIRECTOR_STRIDE - 1):
                        ok = cap.grab()
                        if not ok:
                            break
                        frame_idx += 1
                    if not ok:
                        break

                ok, frame = cap.read()
                if not ok:
                    break

                t = frame_idx / fps
                need_debug  = (frame_idx % 25 == 0)  # [FACE_DEBUG] / [DIRECTOR_MODE] logging
                # Mouth-motion diff needs gray, but ONLY when there's at least one face
                # to compute motion on. When face_cache returns [] (B-roll, background
                # frames), skip the gray conversion entirely — saves 2-4ms per frame.
                need_motion = (prev_gray is not None) and bool(last_raw_faces)

                # Lazy gray: only convert when we actually need the grayscale pixels.
                gray = None
                if need_debug or need_motion:
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


                # 0. Update trackers if enabled
                if ENABLE_CONTINUOUS_TRACKING:
                    t_start = time.perf_counter()
                    left_tracker.update(frame)
                    right_tracker.update(frame)
                    tracking_time += (time.perf_counter() - t_start)
                    tracking_frames += 1

                # 1. Fetch from face_cache (to get cluster IDs)
                if face_cache is not None:
                    # O(log n) binary-search via pre-sorted key list
                    nearest = _nearest_cache_t(t)
                    raw_faces = face_cache.get(nearest, [])
                    last_raw_faces = raw_faces
                elif frame_idx % 5 == 0:
                    # ── Haar detection: every 5 processed frames (was 15 — too stale).
                    # Frame 0 always runs AND enforces a strict 15% minimum height to
                    # prevent b-roll thumbnails / dog paintings from poisoning the
                    # initial last_raw_faces that gets reused for the next 4 frames.
                    raw_faces = []
                    if _podcast_cascade is not None and not ENABLE_CONTINUOUS_TRACKING:
                        _min_face_px = max(40, int(frame_height * MIN_VALID_FACE_HEIGHT_RATIO))
                        _faces_hc = detect_faces_multi_haar(gray, _cv2, scale_factor=1.10, min_neighbors=5, min_size=(_min_face_px, _min_face_px))
                        _strict_first_frame = (frame_idx == 0)
                        for _x, _y, _fw, _fh in _faces_hc:
                            # On frame 0: reject anything smaller than 15% frame height.
                            # This prevents initial b-roll/painting FPs from locking
                            # last_raw_faces before any real face is seen.
                            if _strict_first_frame and _fh < frame_height * 0.15:
                                if need_debug:
                                    log.info(
                                        f"[FACE_FILTER] REJECT frame0_too_small h={_fh:.0f}px "
                                        f"min={frame_height*0.15:.0f}px — likely b-roll thumbnail"
                                    )
                                continue
                            raw_faces.append({'x': float(_x), 'y': float(_y), 'w': float(_fw), 'h': float(_fh)})
                    last_raw_faces = raw_faces
                else:
                    raw_faces = last_raw_faces

                # Extract cluster info BEFORE live override
                cluster_id = None
                cluster_frame_range = None
                if ENABLE_CLUSTER_SCAN and raw_faces:
                    cluster_id = raw_faces[0].get("_cluster_id")
                    if cluster_id is not None:
                        cluster_frame_range = (
                            raw_faces[0].get("_cluster_start"),
                            raw_faces[0].get("_cluster_end"),
                        )

                # 2. If Tracking is ENABLED, strictly override raw_faces on tracker loss
                if ENABLE_CONTINUOUS_TRACKING:
                    cluster_changed = (cluster_id is not None and cluster_id != locked_cluster_id)
                    if cluster_changed:
                        # Force tracker to re-initialize for the new scene
                        left_tracker.consecutive_low_confidence = 999
                        right_tracker.consecutive_low_confidence = 999

                    if left_tracker.is_lost() or right_tracker.is_lost():
                        if frame_idx % 15 == 0 or cluster_changed:
                            _min_face_px_strict = max(60, int(frame_height * MIN_VALID_FACE_HEIGHT_RATIO))
                            _faces_hc = detect_faces_multi_haar(gray, _cv2, scale_factor=1.10, min_neighbors=5, min_size=(_min_face_px_strict, _min_face_px_strict))
                            live_faces = []
                            for _x, _y, _fw, _fh in _faces_hc:
                                # STRICT FILTER: ignore tiny hands/mics (must be >= 12% frame height)
                                if _fh >= frame_height * 0.12:
                                    live_faces.append({
                                        'x': float(_x), 'y': float(_y),
                                        'w': float(_fw), 'h': float(_fh),
                                    })
                            if live_faces:
                                if cluster_id is not None:
                                    live_faces[0]["_cluster_id"] = cluster_id
                                    live_faces[0]["_cluster_start"] = cluster_frame_range[0]
                                    live_faces[0]["_cluster_end"] = cluster_frame_range[1]
                                raw_faces = live_faces
                                last_raw_faces = raw_faces
                                haar_redetects += 1
                            else:
                                raw_faces = []
                                last_raw_faces = raw_faces
                    else:
                        # Tracker is healthy, clear raw_faces to prevent spurious init
                        raw_faces = []
                        last_raw_faces = raw_faces

                # ── [FACE_DEBUG] Step-1 diagnostic ──────────────────────────────
                if frame_idx % 25 == 0 and len(raw_faces) > 0:
                    gray_mean = float(gray.mean()) if gray is not None else -1.0
                    reject_reasons = []
                    for _f in raw_faces:
                        _h = _f['h']
                        _w = _f['w']
                        _aspect_wh = _w / max(1.0, _h)
                        _cy = _f['y'] + _h / 2.0
                        if _h < frame_height * MIN_VALID_FACE_HEIGHT_RATIO:
                            reject_reasons.append(f"too_small(h={_h:.0f})")
                        elif _h > frame_height * MAX_VALID_FACE_HEIGHT_RATIO:
                            reject_reasons.append(f"too_big(h={_h:.0f})")
                        elif _aspect_wh < 0.55 or _aspect_wh > 1.55:
                            reject_reasons.append(f"bad_aspect_wh({_aspect_wh:.2f})")
                        elif _cy < frame_height * 0.05 or _cy > frame_height * 0.95:
                            reject_reasons.append(f"edge_cy({_cy:.0f})")
                        else:
                            reject_reasons.append("OK")
                    
                    if not ENABLE_CONTINUOUS_TRACKING:
                        log.info(
                            f"[FACE_DEBUG] t={t:.2f}s raw={len(raw_faces)} "
                            f"frame_shape=({frame_height},{frame_width},3) "
                            f"gray_mean={gray_mean:.1f} "
                            f"filters={reject_reasons}"
                        )
                        if len(raw_faces) > 4:
                            boxes_str = " | ".join(
                                f"x={_f['x']:.0f},y={_f['y']:.0f},w={_f['w']:.0f},h={_f['h']:.0f}"
                                for _f in raw_faces
                            )
                            log.warning(
                                f"[FACE_DEBUG] HIGH_RAW_COUNT raw={len(raw_faces)} t={t:.2f}s "
                                f"— likely false positives (mic/hand). Boxes: {boxes_str}"
                            )
                # ────────────────────────────────────────────────────────────────

                # Guard 7: Static Box Rejection (applied independently to otherwise valid faces)
                valid_faces_pre = [f for f in raw_faces if is_valid_face(f, _log_reason=need_debug, frame=frame)]
                
                new_stability_map = {}
                valid_faces = []
                _is_podcast_fmt = (video_fmt is not None and video_fmt.format_type == "podcast")
                for _f in valid_faces_pre:
                    _key = (round(_f['x']), round(_f['y']), round(_f['w']), round(_f['h']))
                    _static = box_stability_map.get(_key, 0) + 1
                    new_stability_map[_key] = _static
                    
                    # Reject if perfectly static for 50 frames (UI element/logo),
                    # UNLESS it's a podcast where speakers sit very still.
                    if _static > 50 and not _is_podcast_fmt:
                        if need_debug:
                            log.info(
                                f"[FACE_FILTER] REJECT static_box frames={_static} "
                                f"face=({_key[0]:.0f},{_key[1]:.0f},{_key[2]:.0f},{_key[3]:.0f})"
                            )
                        continue
                    valid_faces.append(_f)
                box_stability_map = new_stability_map

                # ── Guard 8: Temporal size consistency ───────────────────────
                # Track running EMA of valid face heights. If a detection is less than
                # 35% of the running average, it's a text/logo/mic false positive.
                # Real faces don't suddenly shrink from 400px to 60px between frames.
                _size_filtered = []
                for _f in valid_faces:
                    _fh = _f['h']
                    if smoothed_face_h is None:
                        smoothed_face_h = _fh
                        _size_filtered.append(_f)
                    elif _fh >= smoothed_face_h * 0.35:
                        smoothed_face_h = smoothed_face_h * 0.9 + _fh * 0.1  # slow EMA
                        _size_filtered.append(_f)
                    else:
                        if need_debug:
                            log.info(
                                f"[FACE_FILTER] REJECT size_mismatch h={_fh:.0f}px "
                                f"expected~={smoothed_face_h:.0f}px (threshold={smoothed_face_h*0.35:.0f}px) "
                                f"face=({_f['x']:.0f},{_f['y']:.0f},{_f['w']:.0f},{_f['h']:.0f})"
                            )
                valid_faces = _size_filtered

                if frame_idx % 25 == 0 and not ENABLE_CONTINUOUS_TRACKING:
                    log.info(f"[FACE_DEBUG] t={t:.2f}s valid={len(valid_faces)} / raw={len(raw_faces)} smoothed_h={smoothed_face_h:.0f}" if smoothed_face_h else f"[FACE_DEBUG] t={t:.2f}s valid={len(valid_faces)} / raw={len(raw_faces)}")

                # 3. Assign to named LEFT / RIGHT slots by screen position.
                # Guard: in podcast format, reject faces in the dead-center zone (42-58% cx)
                # ONLY when we already have both a left AND right face detected.
                # A single centered speaker (monologue on podcast-classified clip) must NOT be rejected.
                left_slot: Optional[dict] = None
                right_slot: Optional[dict] = None
                _is_podcast_fmt = (video_fmt is not None and video_fmt.format_type == "podcast")
                for f in valid_faces:
                    cx = f['x'] + f['w'] / 2.0
                    cx_ratio = cx / frame_width
                    if cx < frame_width / 2.0:
                        if left_slot is None or f['h'] > left_slot['h']:
                            left_slot = f
                    else:
                        if right_slot is None or f['h'] > right_slot['h']:
                            right_slot = f

                # Post-assignment: if podcast AND we have BOTH slots AND there's a 3rd spurious center face
                # → already handled by best-of-side selection above (left_slot/right_slot are the biggest)

                if frame_idx % 150 == 0:
                    log.info(
                        f"[SLOT_DEBUG] t={t:.2f}s left={'YES' if left_slot else 'NONE'} "
                        f"right={'YES' if right_slot else 'NONE'} valid_total={len(valid_faces)} podcast_fmt={_is_podcast_fmt}"
                    )
                
                if ENABLE_CONTINUOUS_TRACKING:
                    cluster_changed = (cluster_id is not None and cluster_id != locked_cluster_id)
                    cluster_length = (cluster_frame_range[1] - cluster_frame_range[0]) if cluster_frame_range else 0
                    
                    if left_tracker.is_lost() or right_tracker.is_lost() or cluster_changed:
                        if not cluster_changed or cluster_length > 5:
                            t_start = time.perf_counter()
                            if left_slot:
                                left_tracker.init(frame, (left_slot['x'], left_slot['y'], left_slot['w'], left_slot['h']))
                            if right_slot:
                                right_tracker.init(frame, (right_slot['x'], right_slot['y'], right_slot['w'], right_slot['h']))
                            tracking_time += (time.perf_counter() - t_start)
                    
                    if left_tracker.initialized and not left_tracker.is_lost() and left_tracker.last_bbox:
                        left_slot = {'x': left_tracker.last_bbox[0], 'y': left_tracker.last_bbox[1], 'w': left_tracker.last_bbox[2], 'h': left_tracker.last_bbox[3]}
                    if right_tracker.initialized and not right_tracker.is_lost() and right_tracker.last_bbox:
                        right_slot = {'x': right_tracker.last_bbox[0], 'y': right_tracker.last_bbox[1], 'w': right_tracker.last_bbox[2], 'h': right_tracker.last_bbox[3]}

                if frame_idx % 25 == 0:
                    log.info(
                        f"[SLOT_ASSIGN] t={t:.2f}s left_face={left_slot is not None} "
                        f"right_face={right_slot is not None} "
                        f"(tracked={ENABLE_CONTINUOUS_TRACKING}, live_haar_hits={len(valid_faces)})"
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

                # 3. Mouth motion per named slot — GATED on slot stability.
                # A slot must be continuously occupied for >= 2 consecutive haar-sample
                # events before we trust its mouth-motion diff. This prevents a single
                # false-positive frame (bookshelf, hand, mic) from poisoning ema_mouth.
                mouth_motion_left = 0.0
                mouth_motion_right = 0.0

                # Update stability counters (runs every frame, not just haar frames)
                _left_stable  = (_left_stable  + 1) if left_slot  is not None else 0
                _right_stable = (_right_stable + 1) if right_slot is not None else 0

                _LEFT_STABLE_MIN  = 2   # require 2+ consecutive haar samples (~30 frames)
                _RIGHT_STABLE_MIN = 2

                if prev_gray is not None and gray is not None:
                    for slot_label, slot_face, stable_count, stable_min in (
                        ("left",  left_slot,  _left_stable,  _LEFT_STABLE_MIN),
                        ("right", right_slot, _right_stable, _RIGHT_STABLE_MIN),
                    ):
                        if slot_face is None:
                            continue
                        if stable_count < stable_min:
                            # Too new — skip mouth motion to avoid poisoning EMA
                            if frame_idx % 25 == 0:
                                log.info(
                                    f"[MOUTH] {slot_label.upper()} t={t:.2f}s SKIP — "
                                    f"slot only stable for {stable_count} frames "
                                    f"(need {stable_min})"
                                )
                            continue
                        mx1, my1, mx2, my2 = get_mouth_roi(slot_face)
                        mx1 = max(0, mx1); mx2 = min(frame_width, mx2)
                        my1 = max(0, my1); my2 = min(frame_height, my2)
                        if mx2 > mx1 and my2 > my1:
                            roi_curr = gray[my1:my2, mx1:mx2]
                            roi_prev = prev_gray[my1:my2, mx1:mx2]
                            diff = cv2.absdiff(roi_curr, roi_prev)
                            _, thresh_img = cv2.threshold(diff, 12, 255, cv2.THRESH_BINARY)
                            motion = float(cv2.countNonZero(thresh_img))
                            if slot_label == "left":
                                mouth_motion_left = motion
                                if frame_idx % 25 == 0:
                                    log.info(
                                        f"[MOUTH] L t={t:.2f}s  "
                                        f"roi=({mx1},{my1},{mx2},{my2}) "
                                        f"diff={diff.mean():.2f}  nz={int(motion)}  "
                                        f"ema_after={ema_mouth_left*(1-EMA_ALPHA)+motion*EMA_ALPHA:.1f}  "
                                        f"thresh={TALKING_THRESHOLD}"
                                    )
                            else:
                                mouth_motion_right = motion
                                if frame_idx % 25 == 0:
                                    log.info(
                                        f"[MOUTH] R t={t:.2f}s  "
                                        f"roi=({mx1},{my1},{mx2},{my2}) "
                                        f"diff={diff.mean():.2f}  nz={int(motion)}  "
                                        f"ema_after={ema_mouth_right*(1-EMA_ALPHA)+motion*EMA_ALPHA:.1f}  "
                                        f"thresh={TALKING_THRESHOLD}"
                                    )

                ema_mouth_left  = max(EMA_FLOOR, ema_mouth_left  * (1 - EMA_ALPHA) + mouth_motion_left  * EMA_ALPHA)
                ema_mouth_right = max(EMA_FLOOR, ema_mouth_right * (1 - EMA_ALPHA) + mouth_motion_right * EMA_ALPHA)
                left_talking  = ema_mouth_left  > TALKING_THRESHOLD
                right_talking = ema_mouth_right > TALKING_THRESHOLD

                if frame_idx % 150 == 0:
                    log.info(
                        f"[TALKING] t={t:.2f}s L_ema={ema_mouth_left:.1f} R_ema={ema_mouth_right:.1f} "
                        f"L_talk={left_talking} R_talk={right_talking} thresh={TALKING_THRESHOLD}"
                    )

                # 4. Decide mode using strict video-editor logic
                raw_mode = decide_mode_v2(left_slot, right_slot, left_talking, right_talking, face_gap_ratio)
                if raw_mode == "HOLD":
                    mode = last_mode
                else:
                    # ── Mode Switch Gating ──────────────────────────────────────
                    # Require the new SOLO mode to be sustained for MIN_SWITCH_FRAMES
                    # before committing. This prevents one-frame FP detections from
                    # flipping the camera to the wrong speaker.
                    _MIN_SWITCH_FRAMES = int(os.environ.get("HS_MIN_SWITCH_FRAMES", "12"))
                    if raw_mode != last_mode and raw_mode in ("SOLO_LEFT", "SOLO_RIGHT"):
                        _pending_mode = getattr(_decide_mode_state, "pending_mode", None)
                        _pending_count = getattr(_decide_mode_state, "pending_count", 0)
                        if _pending_mode == raw_mode:
                            _pending_count += 1
                        else:
                            _pending_mode = raw_mode
                            _pending_count = 1
                        _decide_mode_state.pending_mode = _pending_mode
                        _decide_mode_state.pending_count = _pending_count
                        if _pending_count >= _MIN_SWITCH_FRAMES:
                            mode = raw_mode
                            last_mode = mode
                            _decide_mode_state.pending_count = 0
                        else:
                            mode = last_mode  # hold until sustained
                    else:
                        mode = raw_mode
                        last_mode = mode
                        _decide_mode_state.pending_mode = None
                        _decide_mode_state.pending_count = 0

                if frame_idx % 25 == 0:
                    log.info(
                        f"[DIR] t={t:.2f}s  mode={mode:<12s}  "
                        f"gap={face_gap_ratio:.2f}(>{SPLIT_MIN_GAP})  "
                        f"L={left_talking} R={right_talking}  "
                        f"ema_l={ema_mouth_left:.1f} ema_r={ema_mouth_right:.1f}"
                    )


                # 5. Active slot (for SPLIT highlight)
                if mode == "SOLO_LEFT":
                    active_slot = "left"
                elif mode == "SOLO_RIGHT":
                    active_slot = "right"
                else:  # SPLIT — highlight whichever has more mouth motion
                    active_slot = "left" if ema_mouth_left >= ema_mouth_right else "right"

                # 6. Compute sx (face center from cache) and solo_slot BEFORE tracking
                if mode == "SOLO_LEFT" and left_slot is not None:
                    sx = left_slot['x'] + left_slot['w'] / 2.0
                elif mode == "SOLO_RIGHT" and right_slot is not None:
                    sx = right_slot['x'] + right_slot['w'] / 2.0
                else:
                    sx = None
                solo_slot = active_slot if mode in ("SOLO_LEFT", "SOLO_RIGHT") else None

                # 6. Smooth position updates (per slot, independent) via Physics Engine
                if left_slot is not None:
                    lx = left_slot['x'] + left_slot['w'] / 2.0
                    smoothed_left_x, vel_left = apply_deadzone_physics(smoothed_left_x, vel_left, lx, frame_width, "LEFT", frame_idx)
                else:
                    _, vel_left = apply_deadzone_physics(smoothed_left_x, vel_left, None, frame_width, "LEFT", frame_idx)

                if right_slot is not None:
                    rx = right_slot['x'] + right_slot['w'] / 2.0
                    smoothed_right_x, vel_right = apply_deadzone_physics(smoothed_right_x, vel_right, rx, frame_width, "RIGHT", frame_idx)
                else:
                    _, vel_right = apply_deadzone_physics(smoothed_right_x, vel_right, None, frame_width, "RIGHT", frame_idx)

                # 7. solo_x: cluster-locked anchor with EMA transition
                if sx is not None and cluster_id is not None:
                    cluster_lock_changed = (
                        cluster_id != locked_cluster_id
                        or solo_slot != locked_cluster_slot
                    )
                    if cluster_lock_changed:
                        locked_cluster_id = cluster_id
                        locked_cluster_slot = solo_slot
                        locked_solo_x = sx
                        cluster_transition_from_x = smoothed_solo_x
                        # Side switch → snap immediately (left↔right is semantic, not drift)
                        if (last_solo_slot is not None and solo_slot != last_solo_slot) or not _first_lock_done:
                            cluster_transition_remaining = 0
                            smoothed_solo_x = locked_solo_x
                            _first_lock_done = True
                        else:
                            cluster_transition_remaining = CLUSTER_TRANSITION_FRAMES
                        log.info(
                            "[CLUSTER_SCAN] cluster=%s slot=%s locked_anchor_x=%d "
                            "frame_range=[%s-%s]",
                            cluster_id, solo_slot, int(locked_solo_x),
                            cluster_frame_range[0], cluster_frame_range[1],
                        )
                    if cluster_transition_remaining > 0:
                        progress = 1.0 - (cluster_transition_remaining / CLUSTER_TRANSITION_FRAMES)
                        smoothed_solo_x = (
                            cluster_transition_from_x * (1.0 - progress)
                            + locked_solo_x * progress
                        )
                        cluster_transition_remaining -= 1
                    else:
                        smoothed_solo_x = locked_solo_x
                elif sx is not None:
                    # No cluster layer: Use Physics Engine instead of EMA for raw face center
                    smoothed_solo_x, vel_solo = apply_deadzone_physics(smoothed_solo_x, vel_solo, sx, frame_width, "SOLO", frame_idx)
                else:
                    _, vel_solo = apply_deadzone_physics(smoothed_solo_x, vel_solo, None, frame_width, "SOLO", frame_idx)

                if solo_slot is not None:
                    last_solo_slot = solo_slot

                if frame_idx % 150 == 0:
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

                # ── Debug visualizer: record annotated frame + JSON entry ──────
                _dbg.record_frame(
                    frame=frame,
                    cv2=cv2,
                    t=t,
                    frame_idx=frame_idx,
                    mode=mode,
                    gap=face_gap_ratio,
                    split_eligible=(face_gap_ratio >= SPLIT_MIN_GAP),
                    left_slot=left_slot,
                    right_slot=right_slot,
                    raw_faces=last_raw_faces,
                    ema_left=ema_mouth_left,
                    ema_right=ema_mouth_right,
                    left_talking=left_talking,
                    right_talking=right_talking,
                    mouth_roi_left=(
                        get_mouth_roi(left_slot) if left_slot else None
                    ),
                    mouth_roi_right=(
                        get_mouth_roi(right_slot) if right_slot else None
                    ),
                    talking_threshold=TALKING_THRESHOLD,
                    frame_height=frame_height,
                    frame_width=frame_width,
                )

                # Only carry gray forward if it was actually computed this frame.
                # If gray=None (skipped frame), prev_gray stays as the last valid frame.
                if gray is not None:
                    prev_gray = gray
                frame_idx += 1

            cap.release()
            
            if ENABLE_CONTINUOUS_TRACKING:
                log.info(f"[FACE_TRACK_PERF] total_tracking_time={tracking_time:.2f}s "
                         f"frames={tracking_frames} haar_redetects={haar_redetects}")
            if active_detector:
                try:
                    active_detector.close()
                except Exception:
                    pass

            # ── Flush debug visualizer session ──────────────────────────────────
            _dbg.close()

            if not frame_stats:
                return 0.5

            # ── FORENSIC COUNTER 1: How many raw frames voted SPLIT? ─────────────
            frames_split = sum(1 for f in frame_stats if f["mode"] == "SPLIT")
            frames_solo_l = sum(1 for f in frame_stats if f["mode"] == "SOLO_LEFT")
            frames_solo_r = sum(1 for f in frame_stats if f["mode"] == "SOLO_RIGHT")
            frames_hold   = sum(1 for f in frame_stats if f["mode"] == "HOLD")
            print(
                f"\n[FORENSICS-1] FRAME DECISIONS (total={len(frame_stats)}):\n"
                f"  SPLIT={frames_split}  SOLO_LEFT={frames_solo_l}  SOLO_RIGHT={frames_solo_r}  HOLD={frames_hold}\n"
                f"  → If SPLIT=0 here: Decision Engine is the killer.\n"
                f"  → If SPLIT>0 here but 0 in final segments: Segment Builder is the killer."
            )

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

            # ── Attach per-frame timeline to each segment for smooth dynamic crop ──
            # Each segment gets the subset of frame_stats that falls within its
            # time window. _build_reframe_filter uses this to interpolate crop_x
            # smoothly per-frame instead of using a single locked average.
            for seg in stable_segments:
                seg.frame_timeline = [
                    {"t": f["t"] - seg.start_t,  # relative timestamp within segment
                     "solo_x": f["solo_x"],
                     "left_x": f["left_x"],
                     "right_x": f["right_x"]}
                    for f in frame_stats
                    if seg.start_t <= f["t"] < seg.end_t
                ]

            for seg in stable_segments:
                log.info(
                    f"[DIRECTOR_SEGMENT] t={seg.start_t}-{seg.end_t}s mode={seg.mode} "
                    f"active={seg.active_speaker} crop_x={round(seg.crop_x, 3)} "
                    f"frame_timeline_pts={len(seg.frame_timeline)}"
                )

            # ── FORENSIC COUNTER 2: How many final segments are SPLIT? ───────────
            segs_split  = sum(1 for s in stable_segments if s.mode == "SPLIT")
            segs_solo_l = sum(1 for s in stable_segments if s.mode == "SOLO_LEFT")
            segs_solo_r = sum(1 for s in stable_segments if s.mode == "SOLO_RIGHT")
            print(
                f"\n[FORENSICS-2] FINAL SEGMENTS (total={len(stable_segments)}):\n"
                f"  SPLIT={segs_split}  SOLO_LEFT={segs_solo_l}  SOLO_RIGHT={segs_solo_r}\n"
                f"  → Verdict: {'SEGMENT BUILDER killed SPLIT' if frames_split > 0 and segs_split == 0 else 'DECISION ENGINE never produced SPLIT' if frames_split == 0 else 'SPLIT survived end-to-end ✅'}"
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
                    # ── Per-frame dynamic crop via Overlay + Sendcmd ──────────────
                    # FFmpeg `crop` filter does NOT support `sendcmd`, and `eval=frame`
                    # crashes with AST stack limits (exit code -22) if > 15 terms.
                    # FIX: Scale the video up, place it on a black canvas via `overlay`, 
                    # and animate `overlay x` via `sendcmd`. `overlay` supports `sendcmd`!
                    timeline = getattr(seg, 'frame_timeline', [])

                    crop_h = max(2, src_h) & ~1
                    crop_w = max(2, int(round(crop_h * dst_ar))) & ~1
                    c_y = max(0, int(round((src_h - crop_h) * 0.35))) & ~1

                    if timeline and len(timeline) >= 2:
                        sf = dst_h / src_h
                        scaled_w = int(src_w * sf) & ~1

                        def _ox(kf):
                            c_x = int(round(_clamp(kf['solo_x'] - crop_w / 2.0, 0.0, src_w - crop_w)))
                            return int(-c_x * sf)

                        KEYFRAME_STEP = max(1, len(timeline) // 25)
                        raw_kfs = timeline[::KEYFRAME_STEP]
                        if timeline[-1] not in raw_kfs:
                            raw_kfs.append(timeline[-1])

                        dedup_kfs = [raw_kfs[0]]
                        for kf in raw_kfs[1:]:
                            if _ox(kf) != _ox(dedup_kfs[-1]):
                                dedup_kfs.append(kf)

                        import tempfile as _tf
                        sc_fd, sc_path = _tf.mkstemp(suffix=".txt", prefix="hs_crop_")
                        try:
                            with os.fdopen(sc_fd, 'w') as sc_f:
                                for kf in dedup_kfs:
                                    sc_f.write(f"{round(kf['t'], 4)} [enter] overlay x {_ox(kf)};\n")
                        except Exception:
                            os.close(sc_fd)

                        sc_escaped = sc_path.replace('\\', '/').replace(':', '\\:')
                        
                        # Fix decimal floating issues with color duration
                        seg_dur = round(seg.end_t - seg.start_t, 3) + 0.5
                        
                        log.info(
                            f"[DYNAMIC_CROP_OVERLAY] seg_idx={idx} mode={seg.mode} "
                            f"keyframes={len(dedup_kfs)} sendcmd={sc_path}"
                        )
                        chain = (
                            f"color=c=black:s={dst_w}x{dst_h}:d={seg_dur}[bg_{idx}];"
                            f"[v_{idx}_raw]scale={scaled_w}:{dst_h}:flags=lanczos,setsar=1,sendcmd=f='{sc_escaped}'[v_{idx}_scaled];"
                            f"[bg_{idx}][v_{idx}_scaled]overlay=x={_ox(dedup_kfs[0])}:y=0[v_{idx}_out]"
                        )
                    else:
                        c_x = int(round(_clamp(seg.crop_x - crop_w / 2.0, 0.0, src_w - crop_w))) & ~1
                        log.info(
                            f"[STATIC_CROP] seg_idx={idx} mode={seg.mode} "
                            f"no timeline, fixed crop_x={c_x}"
                        )
                        chain = f"[v_{idx}_raw]crop={crop_w}:{crop_h}:{c_x}:{c_y},scale={dst_w}:{dst_h}:flags=lanczos,setsar=1[v_{idx}_out]"


                    vf_parts.append(chain)

                    
                elif seg.mode == "ACTIVE_CENTER":
                    # Disabled 1.15x zoom to prevent chopping off the head
                    crop_h = src_h & ~1
                    crop_w = max(2, int(round(crop_h * dst_ar))) & ~1
                    c_x = int(round(_clamp(seg.crop_x - crop_w / 2.0, 0.0, src_w - crop_w))) & ~1
                    c_y = 0
                    chain = f"[v_{idx}_raw]crop={crop_w}:{crop_h}:{c_x}:{c_y},scale={dst_w}:{dst_h}:flags=lanczos,setsar=1[v_{idx}_out]"
                    vf_parts.append(chain)
                    
                else: # SPLIT
                    crop_h = src_h & ~1
                    crop_w = max(2, int(round(src_h * (dst_w / (dst_h / 2.0))))) & ~1
                    l_cx = int(round(_clamp(seg.left_x - crop_w / 2.0, 0.0, src_w - crop_w))) & ~1
                    r_cx = int(round(_clamp(seg.right_x - crop_w / 2.0, 0.0, src_w - crop_w))) & ~1
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
            crop_h = src_h & ~1
            crop_w = max(2, int(round(src_h * (dst_w / (dst_h / 2.0))))) & ~1
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
        elif os.getenv("HS_DISABLE_CROP", "0") == "1":
            log.info("[WCE] HS_DISABLE_CROP=1 detected. Skipping center crop.")
            vf_parts = [f"scale={dst_w}:{dst_h}:force_original_aspect_ratio=decrease"]
        elif src_ar >= dst_ar:
            crop_h = src_h & ~1
            crop_w = max(2, int(round(src_h * dst_ar))) & ~1
            if isinstance(focus_x, str):
                raw_x = f"max(0,min({src_w}-{crop_w},{src_w}*({focus_x})-({crop_w}/2.0)))"
                crop_x = raw_x.replace(",", "\\,")
            else:
                x_center = src_w * _clamp(float(focus_x), 0.0, 1.0)
                crop_x = str(int(round(_clamp(x_center - (crop_w / 2.0), 0.0, src_w - crop_w))))
            crop_y = "0"
            vf_parts = [f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y}", f"scale={dst_w}:{dst_h}:flags=lanczos"]
        else:
            crop_w = src_w & ~1
            crop_h = max(2, int(round(src_w / dst_ar))) & ~1
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
            *_hwaccel_decode_args(input_path),   # GPU decode when supported by input codec
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
            *_hwaccel_decode_args(input_path),   # GPU decode when supported by input codec
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

    def _decorate_caption(self, text: str, use_emoji: bool) -> str:
        # User explicitly requested 100% accuracy over emojis.
        # Emojis break Whisper's exact word-level timing arrays.
        return text.strip()

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
        for seg_idx, seg in enumerate(transcript_window):
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
                
                log.warning(f"[WCE-SYNC-FORENSIC] FALLBACK (No Words) for seg {seg_idx} ('{text[:30]}...'). Using proportional char division.")
                
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

                # Semantic color routing - priority: Danger > Success > HookWord > Highlight
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
        _hook_keywords = {
            "interesting", "look", "attention", "listen", "wait", "secret", "truth", 
            "nobody", "why", "how", "money", "ai", "tool", "automation", "always", "real", 
            "hack", "exposed", "hidden",
        }
        _highlight_keywords = {
            "must", "important", "crucial", "key", "remember", "focus",
        }

        def _style_for(word: str) -> str:
            clean = re.sub(r"[^\w]", "", word).lower()
            if clean in _danger_keywords:
                return "Danger"
            if clean in _success_keywords:
                return "Success"
            if clean in _hook_keywords:
                return "HookWord"
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

    def generate_caption_file(self, input_path: str, source_start: float, source_end: float, transcript: list, config, clip_title: str, cortex_hints: dict, precomputed_narrative: dict = None) -> str:
        """Standalone helper to generate .ass file for a clip before enhancing it."""
        import uuid
        import time
        from utils.clipper import get_video_duration
        
        cfg = config or ClipEditConfig()
        
        _cortex = cortex_hints or {}
        _cortex_active = bool(_cortex.get("cortex_enabled"))
        editing_notes = _cortex.get("editing_notes", {}) if isinstance(_cortex.get("editing_notes"), dict) else {}
        
        pacing_note = str(editing_notes.get("pacing_note", "")).lower().strip()
        subtitle_style = str(editing_notes.get("subtitle_style", "classic")).lower().strip()
        
        if _cortex_active:
            if pacing_note == "fast":
                cfg.max_caption_words = 3
            elif pacing_note == "slow":
                cfg.max_caption_words = 9

        base_meta = self._probe_video(input_path)
        clip_duration = max(0.01, float(base_meta.get("duration") or 0.0))
        
        if precomputed_narrative and isinstance(precomputed_narrative, dict):
            transcript_window = list(precomputed_narrative.get("transcript_window") or [])
            new_win = []
            for x in transcript_window:
                xs = _safe_float(x.get("start"), 0.0)
                xe = _safe_float(x.get("end"), xs)
                seg_offset = xs - source_start
                seg_remapped = {
                    "start": max(0.0, seg_offset),
                    "end": min(clip_duration, xe - source_start),
                    "text": x.get("text", "")
                }
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
            pre_trim = precomputed_narrative.get("trim")
        else:
            transcript_window = self._window_transcript(transcript, source_start, source_end)
            pre_trim = None
            
        if isinstance(pre_trim, dict):
            trim_in = _safe_float(pre_trim.get("in"), 0.0)
            trim_out = _safe_float(pre_trim.get("out"), clip_duration)
            trim_in = _clamp(trim_in, 0.0, max(0.0, clip_duration - 0.2))
            trim_out = _clamp(trim_out, trim_in + 0.2, clip_duration)
        else:
            trim_in = 0.0
            trim_out = clip_duration
            
        ramped_duration = trim_out - trim_in
        if cfg.enable_hook_speed_ramp:
            ramp_window = min(2.5, (trim_out - trim_in) * 0.4)
            ramped_duration = ramp_window / cfg.hook_ramp_speed + (trim_out - trim_in - ramp_window)
        else:
            ramp_window = 0.0
            
        captions = self._caption_segments(
            transcript_window=transcript_window,
            source_start=source_start,
            trim_in=trim_in,
            trim_out=trim_out,
            config=cfg,
            ramp_window=ramp_window,
            video_fmt=None,
        )
        
        if _cortex_active and _cortex.get("opening_caption"):
            hook_line = str(_cortex["opening_caption"]).strip()
        elif _cortex_active and _cortex.get("title"):
            hook_line = str(_cortex["title"]).strip()
        else:
            hook_line = clip_title.strip() if clip_title else (captions[0].text if captions else "")

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
        else:
            cta_line = "Follow for more creator breakdowns"
            
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
        hashtags_line = (cortex_hashtags or self._extract_hashtags(transcript_window)) if cfg.add_hashtags else None
        
        has_any_overlay = (cfg.add_captions and captions) or (cfg.add_dynamic_overlays and hook_line) or (cfg.add_cta and cta_line)
        if not has_any_overlay:
            return ""
            
        ass_path = os.path.join(self.work_dir, f"wc_subs_async_{uuid.uuid4().hex}.ass")
        target_wh = self._resolve_ratio(cfg.target_ratio)
        
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
            speaker_side="center",
        )
        return ass_path

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
        highlight_color = "&H0000D4FF"   # Brighter Gold/Yellow
        border_size = "5"                # Increased for 3D Pop
        shadow_size = "8"                # Increased for deep 3D shadow
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
        margin_l, margin_r, margin_v = 40, 40, 450
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
            f"Style: Hook,Outfit,55,{hook_color},&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,2,8,20,20,80,1",
            f"Style: Highlight,Montserrat,80,{highlight_color},&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{border_size},{shadow_size},{caption_alignment},{margin_l},{margin_r},{margin_v},1",
            f"Style: HookWord,Montserrat,80,&H00FFAAFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{border_size},{shadow_size},{caption_alignment},{margin_l},{margin_r},{margin_v},1",
            f"Style: Danger,Montserrat,80,&H006666FF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{border_size},{shadow_size},{caption_alignment},{margin_l},{margin_r},{margin_v},1",
            f"Style: Success,Montserrat,80,&H00AAFF88,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{border_size},{shadow_size},{caption_alignment},{margin_l},{margin_r},{margin_v},1",
            f"Style: CTA,Montserrat,45,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,2,2,20,20,100,1",
            # KaraokeWord: slightly smaller, used for the inactive (ghost) state of karaoke
            f"Style: KaraokeGhost,Montserrat,80,&H00E0E0E0,&H000000FF,&H00000000,&H80000000,{bold_val},{italic_val},0,0,100,100,0,0,1,{border_size},{shadow_size},{caption_alignment},{margin_l},{margin_r},{margin_v},1",
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
            if getattr(seg, "words", None) and len(seg.words) > 0:
                # Pad timings for any extra words (like emojis added by _decorate)
                word_timings = list(seg.words)
                while len(word_timings) < len(words):
                    word_timings.append(word_timings[-1])
                
                for wi, word_text in enumerate(words):
                    w_dict = word_timings[wi]
                    w_start = w_dict["start"]
                    w_end = w_dict["end"]
                    
                    parts = []
                    for i, w in enumerate(words):
                        w_esc = _ass_escape(w)
                        if i == wi:
                            parts.append("{\\rHighlight}" + w_esc + "{\\r}")
                        else:
                            parts.append("{\\rKaraokeGhost}" + w_esc + "{\\r}")
                            
                    line_text = " ".join(parts)
                    an_tag = {"left": "{\\an1\\blur1.5}", "right": "{\\an3\\blur1.5}"}.get(getattr(seg, "speaker_side", "center"), "{\\blur1.5}")
                    events.append(f"Dialogue: 0,{_ass_time(w_start)},{_ass_time(w_end)},Caption,,0,0,0,,{an_tag}{line_text}")
            elif len(words) > 1:
                word_dur = (seg.end - seg.start) / len(words)
                for wi, word in enumerate(words):
                    w_start = seg.start + wi * word_dur
                    w_end   = seg.start + (wi + 1) * word_dur
                    # Build line: ghost words + {\rHighlight}active_word{\r} + ghost words
                    parts = []
                    for i, w in enumerate(words):
                        w_esc = _ass_escape(w)
                        if i == wi:
                            parts.append("{\\rHighlight}" + w_esc + "{\\r}")
                        else:
                            parts.append("{\\rKaraokeGhost}" + w_esc + "{\\r}")
                            
                    line_text = " ".join(parts)
                    an_tag = {"left": "{\\an1\\blur1.5}", "right": "{\\an3\\blur1.5}"}.get(getattr(seg, "speaker_side", "center"), "{\\blur1.5}")
                    events.append(f"Dialogue: 0,{_ass_time(w_start)},{_ass_time(w_end)},Caption,,0,0,0,,{an_tag}{line_text}")
            else:
                # Single-word segment — just highlight it
                highlighted_text = self._highlight_text(escaped_text)
                an_tag = {"left": "{\\an1\\blur1.5}", "right": "{\\an3\\blur1.5}"}.get(getattr(seg, "speaker_side", "center"), "{\\blur1.5}")
                events.append(f"Dialogue: 0,{_ass_time(seg.start)},{_ass_time(seg.end)},Caption,,0,0,0,,{an_tag}{highlighted_text}")

        if hook_line:
            hook_text = self._format_hook_line(hook_line)
            if hook_text:
                hook_end = min(duration, 4.0)
                events.append(f"Dialogue: 1,{_ass_time(0.08)},{_ass_time(hook_end)},Hook,,0,0,0,,{_ass_escape(hook_text)}")
        if hashtags_line:
            start = max(0.0, duration - 3.8)
            end = max(start + 0.5, duration - 0.2)
            events.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},CTA,,0,0,0,,{_ass_escape(hashtags_line)}")
        if cta_line:
            start = max(0.0, duration - 2.6)
            end = max(start + 0.5, duration - 0.1)
            events.append(f"Dialogue: 2,{_ass_time(start)},{_ass_time(end)},CTA,,0,0,0,,{_ass_escape(cta_line)}")
            
        os.makedirs(os.path.dirname(path), exist_ok=True)
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
            *_hwaccel_decode_args(input_path),   # GPU decode when supported by input codec
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
        precomputed_face_cache: Optional[Dict[float, List[Dict[str, float]]]] = None,
        precomputed_ass_path: Optional[str] = None,
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
        ffmpeg_passes = 0
        intermediate_files_created = 0
        passes_saved = 0

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
            render_trim_in = 0.0
            render_trim_out = clip_duration
            needs_trim = (trim_in > 0.08 or (clip_duration - trim_out) > 0.08) and (trim_out - trim_in) > 1.0
            if needs_trim:
                # Materialize the trim before format/crop analysis. Previously the
                # final command limited input with -to while DirectorSegments still
                # referenced the full pretrimmed timeline, producing empty trim
                # branches and an FFmpeg concat failure.
                cut_path = os.path.join(self.work_dir, f"wc_cut_{uuid.uuid4().hex}.mp4")
                self._cut_with_fade(input_path, cut_path, trim_in, trim_out)
                ffmpeg_passes += 1
                intermediate_files_created += 1
                tmp_files.append(cut_path)
                work_a = cut_path
                clip_duration = max(0.01, trim_out - trim_in)
                render_trim_in = 0.0
                render_trim_out = clip_duration
                log.info(
                    "[WCE_TIMELINE] materialized trim %.3f-%.3f; director/render timeline reset to 0-%.3f",
                    trim_in, trim_out, clip_duration,
                )

            if cfg.enable_hook_speed_ramp:
                speed_path = os.path.join(self.work_dir, f"wc_speed_{uuid.uuid4().hex}.mp4")
                ramp_window, ramped_duration = self._apply_hook_speed_ramp(work_a, speed_path, clip_duration, cfg)
                ffmpeg_passes += 1
                intermediate_files_created += 1
                tmp_files.append(speed_path)
                work_b = speed_path
                render_trim_in = 0.0
                render_trim_out = ramped_duration
            else:
                ramp_window, ramped_duration = 0.0, clip_duration
                work_b = work_a
                passes_saved += 1
            metadata["hook_ramp"] = {"window_s": round(ramp_window, 3), "speed": round(cfg.hook_ramp_speed, 3)}

            hook_zoom_filter = _hook_zoom_filter_expr(cfg, ramped_duration)
            if hook_zoom_filter:
                passes_saved += 1
                metadata["hook_zoom"] = {
                    "scale": round(cfg.hook_zoom_scale, 3),
                    "duration_s": round(cfg.hook_zoom_duration_s, 3),
                    "compiled_into_final_graph": True,
                }
                log.info("[HOOK_ZOOM] compiled into final filter graph")

            t0 = time.perf_counter()
            work_meta = self._probe_video(work_b)
            t_reframe += time.perf_counter() - t0

            video_fmt = None
            _disable_crop = os.getenv("HS_DISABLE_CROP", "0") == "1"
            if _disable_crop:
                log.info("[WCE] HS_DISABLE_CROP=1 -> Skipping FaceCache and active speaker detection completely.")
                video_fmt = None
            elif cfg.enable_active_speaker and cfg.enable_format_detection:
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

            # --- START CAPTION THREAD (Parallel Processing) ---
            import threading
            class CaptionThread(threading.Thread):
                def __init__(self, editor, tw, ss, ti, to, cfg, rw, vf):
                    super().__init__()
                    self.editor = editor
                    self.tw = tw; self.ss = ss; self.ti = ti; self.to = to; self.cfg = cfg; self.rw = rw; self.vf = vf
                    self.captions = []
                def run(self):
                    self.captions = self.editor._caption_segments(
                        transcript_window=self.tw,
                        source_start=self.ss,
                        trim_in=self.ti,
                        trim_out=self.to,
                        config=self.cfg,
                        ramp_window=self.rw,
                        video_fmt=self.vf,
                    )
            
            cap_thread = None
            if cfg.add_captions and precomputed_ass_path is None:
                cap_thread = CaptionThread(self, transcript_window, source_start, trim_in, trim_out, cfg, ramp_window, video_fmt)
                cap_thread.start()
            # --- END CAPTION THREAD ---

            t0 = time.perf_counter()
            target_wh = self._resolve_ratio(cfg.target_ratio)
            if video_fmt is not None:
                focus_x = self._get_crop_expression(video_fmt, transcript_window, cfg, work_b, face_cache=precomputed_face_cache)
            else:
                focus_x = 0.5
            is_complex_graph, vf = self._build_reframe_filter(work_meta, target_wh, focus_x, cfg, boring_mode)
            t_reframe += time.perf_counter() - t0
            af = self._build_audio_filter(cfg)

            captions: List[CaptionSegment] = []
            if cap_thread is not None:
                cap_thread.join()
                captions = cap_thread.captions
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

            # ── B-ROLL INJECTION (Pexels) ─────────────────────────────────────────
            # Groq Cortex provides b_roll_keywords for any content type.
            # We fetch a Pexels clip and overlay it at t=1s as a visual hook enhancer.
            # Hard-cut overlay (no fade) avoids NVENC alpha channel issues.
            _broll_path = None
            _broll_start_sec = 0.0
            _broll_duration = 0.0
            if _cortex_active:
                _content_genre = str(_cortex.get("content_genre", "")).upper()
                _broll_keywords = _cortex.get("b_roll_keywords", []) or []
                _broll_hs_enabled = os.getenv("HS_BROLL_ENABLED", "1") != "0"
                _broll_enabled = bool(_broll_keywords) and _broll_hs_enabled
                log.info(
                    "[WCE-BROLL] decision: cortex_active=%s keywords=%s genre=%s "
                    "HS_BROLL_ENABLED=%s → enabled=%s",
                    _cortex_active, _broll_keywords, _content_genre,
                    _broll_hs_enabled, _broll_enabled
                )
                if _broll_enabled:
                    try:
                        _fetched = fetch_b_roll_for_keywords(_broll_keywords)
                        if _fetched and os.path.exists(_fetched):
                            _broll_probe = self._probe_video(_fetched)
                            _broll_total_dur = float(_broll_probe.get("duration", 0) or 0)
                            _broll_duration = min(4.0, max(1.5, ramped_duration * 0.12))  # ~12% of clip, 1.5-4s
                            if _broll_total_dur > _broll_duration + 1.0:
                                import random as _rand
                                _safe_end = _broll_total_dur - _broll_duration - 1.0
                                _broll_start_sec = _rand.uniform(0, _safe_end) if _safe_end > 0 else 0.0
                                _broll_path = _fetched
                                log.info(
                                    "[WCE-BROLL] Injecting B-Roll '%s' keywords=%s genre=%s "
                                    "overlay_dur=%.1fs seek=%.1fs",
                                    os.path.basename(_broll_path), _broll_keywords,
                                    _content_genre, _broll_duration, _broll_start_sec
                                )
                            else:
                                log.warning("[WCE-BROLL] B-Roll clip too short (%.1fs) for %.1fs overlay — skipping", _broll_total_dur, _broll_duration)
                    except Exception as _be:
                        log.error("[WCE-BROLL] Fetch/probe failed: %s", _be)
            # ── END B-ROLL INJECTION ──────────────────────────────────────────────

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

            graph_video_pad = "v_reframe"
            if hook_zoom_filter:
                if is_complex_graph:
                    vf_render = f"{vf_render};[v_reframe]{hook_zoom_filter}[v_zoom]"
                    graph_video_pad = "v_zoom"
                else:
                    vf_render = f"{vf_render},{hook_zoom_filter}"

            if has_any_overlay or precomputed_ass_path:
                ass_path = precomputed_ass_path
                if not ass_path:
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
                    vf_render = f"{vf_render};[{graph_video_pad}]subtitles='{ass_esc}':fontsdir='{fonts_dir_esc}'[v_subs]"
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
                last_pad = "[v_subs]" if (has_any_overlay or precomputed_ass_path) else f"[{graph_video_pad}]"
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

            # ── Distribution branding: merge blur-bg + watermark + outro into this pass ──
            # Eliminates the separate _apply_distribution_branding() call (saves ~26s/clip)
            # and avoids double-encode quality loss. Flag is set by local_worker.py.
            branding_merged = False
            branding_outro_merged = False
            if cfg.apply_distribution_branding and cfg.branding_watermark_path:
                _bwm = os.path.abspath(cfg.branding_watermark_path).replace("\\", "/")
                _has_outro = bool(
                    cfg.branding_outro_path
                    and os.path.exists(cfg.branding_outro_path)
                    and os.path.getsize(cfg.branding_outro_path) > 1000
                )
                # Input index tracking: 0=clip, 1=wm_icon (if is_watermarked), else not present
                _bwm_idx = 2 if is_watermarked else 1   # index for branding logo.png
                _outro_idx = _bwm_idx + 1               # index for outro.mp4
                _disable_bg_blur = os.getenv("HS_DISABLE_BG_BLUR", "1").strip() != "0"
                if _disable_bg_blur:
                    log.info("[WCE_PERF] Background blur set to 0 (disabled via HS_DISABLE_BG_BLUR=1) -> using instant black padding!")
                    _brand_chain = (
                        f";[out_v]scale=1080:1920:force_original_aspect_ratio=decrease,"
                        f"pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black[hs_merged]"
                        f";[{_bwm_idx}:v]scale=180:-2,format=rgba,colorchannelmixer=aa=0.8[hs_wm]"
                        f";[hs_merged][hs_wm]overlay=W-w-50:H-h-250,format=yuv420p,fps=30,setsar=1[hs_main_v]"
                    )
                else:
                    _long_heavy_render = ramped_duration >= 90.0
                    if _long_heavy_render:
                        _blur_chain = (
                            "scale=540:960:force_original_aspect_ratio=increase,"
                            "crop=540:960,boxblur=10,scale=1080:1920"
                        )
                        log.info("[WCE_PERF] long clip %.1fs: half-res background blur enabled", ramped_duration)
                    else:
                        _blur_chain = (
                            "scale=1080:1920:force_original_aspect_ratio=increase,"
                            "crop=1080:1920,boxblur=20"
                        )
                    # Build branding chain appended onto [out_v]
                    # Step 1: cinematic blur background
                    _brand_chain = (
                        f";[out_v]split=2[hs_blur_src][hs_vid_raw]"
                        f";[hs_blur_src]{_blur_chain}[hs_bg]"
                        f";[hs_vid_raw]scale=1080:1920:force_original_aspect_ratio=decrease[hs_fg]"
                        f";[hs_bg][hs_fg]overlay=(W-w)/2:(H-h)/2[hs_merged]"
                        # Step 2: branding watermark overlay
                        f";[{_bwm_idx}:v]scale=180:-2,format=rgba,colorchannelmixer=aa=0.8[hs_wm]"
                        f";[hs_merged][hs_wm]overlay=W-w-50:H-h-250,format=yuv420p,fps=30,setsar=1[hs_main_v]"
                    )
                vf_render = f"{vf_render}{_brand_chain}"

                if _has_outro:
                    # Step 3: outro concat
                    vf_render += (
                        f";[{_outro_idx}:v]scale=1080:1920:force_original_aspect_ratio=decrease,"
                        f"pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,format=yuv420p[hs_outro_v]"
                        f";[0:a]aresample=44100,aformat=channel_layouts=stereo[hs_main_a_r]"
                        f";[{_outro_idx}:a]aresample=44100,aformat=channel_layouts=stereo[hs_outro_a_r]"
                        f";[hs_main_v][hs_main_a_r][hs_outro_v][hs_outro_a_r]"
                        f"concat=n=2:v=1:a=1[hs_final_v][hs_final_a]"
                    )
                    branding_outro_merged = True
                    log.info("[WCE] Branding+outro merged into WCE pass (single encode)")
                else:
                    vf_render += ";[hs_main_v]null[hs_final_v]"
                    log.info("[WCE] Branding merged into WCE pass (no outro found at %s)", cfg.branding_outro_path)

                branding_merged = True

            cmd = [
                "ffmpeg",
                "-y",
                "-nostdin",
                *_hwaccel_decode_args(work_b),   # GPU decode when supported by input codec
            ]
            fast_seek = 0.0
            exact_seek = 0.0
            if render_trim_in > 0.001:
                fast_seek = max(0.0, render_trim_in - 5.0)
                exact_seek = render_trim_in - fast_seek
                cmd.extend(["-ss", f"{fast_seek:.3f}"])
            
            cmd.extend(["-i", work_b])
            
            if exact_seek > 0.001:
                cmd.extend(["-ss", f"{exact_seek:.3f}"])
                
            if render_trim_out > render_trim_in and render_trim_out < float((work_meta.get("duration") or render_trim_out) or render_trim_out) - 0.001:
                # duration to encode is (render_trim_out - render_trim_in)
                encode_duration = render_trim_out - render_trim_in
                cmd.extend(["-t", f"{encode_duration:.3f}"])

            if is_watermarked:
                cmd.extend(["-i", wm_path])

            if branding_merged:
                cmd.extend(["-i", os.path.abspath(cfg.branding_watermark_path)])
                if branding_outro_merged:
                    cmd.extend(["-i", os.path.abspath(cfg.branding_outro_path)])

            # B-Roll input (after all other inputs so index is known)
            _broll_input_idx = None
            if _broll_path:
                _broll_input_idx = len([x for i, x in enumerate(cmd) if i > 0 and cmd[i-1] == "-i"])
                cmd.extend(["-ss", f"{_broll_start_sec:.3f}", "-i", _broll_path])
                # Inject B-Roll overlay into filter graph BEFORE format=yuv420p step
                # We overlay on [out_v] which exists at this point (after watermark/branding).
                # Use hard-cut with trim to keep duration bounded.
                _broll_end = _broll_duration
                _broll_filter = (
                    f"[{_broll_input_idx}:v]"
                    f"trim=end={_broll_end:.3f},setpts=PTS-STARTPTS,"
                    f"scale={target_wh[0]}:{target_wh[1]}:force_original_aspect_ratio=increase,"
                    f"crop={target_wh[0]}:{target_wh[1]},setsar=1[broll_v];"
                    f"[out_v][broll_v]overlay=enable='between(t,1.0,{1.0+_broll_end:.3f})':x=0:y=0[out_v_broll]"
                )
                # Replace [out_v] terminal pad with broll-overlaid version
                if is_complex_graph:
                    vf_render = f"{vf_render};{_broll_filter}"
                    # Update all downstream references from [out_v] to [out_v_broll]
                    # The branding chain appends after [out_v] so rewrite it
                    vf_render = vf_render.replace("[out_v]null[hs_final_v]", "[out_v_broll]null[hs_final_v]")
                    vf_render = vf_render.replace("[out_v]split=2", "[out_v_broll]split=2")
                    # If branding was already added (uses [out_v] as source), patch its reference
                    # by replacing the LAST occurrence of [out_v] with [out_v_broll]
                    if not branding_merged and "[out_v]" not in vf_render:
                        pass  # already replaced above
                    _use_filter_complex = True
                log.info("[WCE-BROLL] Filter graph patched: B-Roll overlay at 1.0-%.1fs", 1.0+_broll_end)


            # Determine final output pad and audio handling
            # When broll is injected, [out_v] becomes [out_v_broll] — update the pad reference.
            _broll_active = bool(_broll_path and _broll_input_idx is not None)
            _out_video_pad = "hs_final_v" if branding_merged else ("out_v_broll" if _broll_active else ("out_v" if (is_watermarked or is_complex_graph) else None))
            _use_filter_complex = is_watermarked or is_complex_graph or branding_merged or _broll_active
            cmd.extend([
                "-filter_complex" if _use_filter_complex else "-vf",
                vf_render,
                "-map", f"[{_out_video_pad}]" if _out_video_pad else "0:v:0",
                "-map", "[hs_final_a]" if branding_outro_merged else "0:a:0?",
                "-r",
                str(max(24, int(cfg.export_fps))),
                *_video_encode_args(
                    crf=int(cfg.quality_crf if cfg.preserve_quality else 24),
                    preset=cfg.quality_preset if cfg.preserve_quality else "ultrafast",
                ),
            ])
            if branding_outro_merged:
                # Audio already handled in filter graph via concat — just encode
                cmd += ["-c:a", "aac", "-b:a", _get_export_audio_bitrate()]
            elif bool(work_meta.get("has_audio")):
                af_render = af
                fade_start = max(0.0, float(ramped_duration) - 0.05)
                if needs_trim:
                    af_render = f"{af_render},afade=t=out:st={fade_start:.3f}:d=0.05"
                cmd += ["-af", af_render, "-c:a", "aac", "-b:a", _get_export_audio_bitrate()]
            else:
                cmd += ["-an"]
            cmd.append(output_path)
            ffmpeg_passes += 1
            
            t0 = time.perf_counter()
            with _GPU_SEMAPHORE:
                gpu_start = time.perf_counter()
                render_timeout_s = 420 if ramped_duration >= 90.0 else 220
                if render_timeout_s > 220:
                    log.info("[WCE_PERF] long clip %.1fs: render timeout=%ss", ramped_duration, render_timeout_s)
                self._run(cmd, timeout_s=render_timeout_s)
                gpu_done = time.perf_counter() - gpu_start
                cpu_done = gpu_start - t_total
                log.info(f"[WCE_PARALLEL] clip={os.path.basename(output_path)} cpu_done={cpu_done:.1f}s gpu_done={gpu_done:.1f}s")
                
            t_encode += time.perf_counter() - t0

            has_hook = bool(clip_title.strip())
            score = self._estimate_engagement(captions, transcript_window, boring_mode=boring_mode, has_hook=has_hook)
            metadata["engagement_score"] = round(score, 2)
            metadata["captions_count"] = len(captions)
            metadata["branding_merged_into_wce"] = branding_merged
            metadata["visual_effect_graph"] = {
                "single_encode_path": True,
                "ffmpeg_passes": int(ffmpeg_passes),
                "intermediate_files_created": int(intermediate_files_created),
                "decode_encode_passes_saved": int(passes_saved),
                "trim_compiled_into_final_graph": bool(needs_trim and not cfg.enable_hook_speed_ramp),
                "hook_zoom_compiled_into_final_graph": bool(hook_zoom_filter),
                "branding_outro_external_pass": not branding_merged,
                "branding_merged_into_wce": branding_merged,
            }
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
                    "ffmpeg_passes": int(ffmpeg_passes),
                    "intermediate_files_created": int(intermediate_files_created),
                    "decode_encode_passes_saved": int(passes_saved),
                }
                log.info(
                    "[EDIT-PROFILE] reframe=%.2fs face=%.2fs encode=%.2fs total=%.2fs ffmpeg_passes=%d intermediates=%d saved=%d",
                    float(t_reframe),
                    float(t_face),
                    float(t_encode),
                    float(total_s),
                    int(ffmpeg_passes),
                    int(intermediate_files_created),
                    int(passes_saved),
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
