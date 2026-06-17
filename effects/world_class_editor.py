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
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

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
    trim_pad_in_s: float = 0.12
    trim_pad_out_s: float = 0.22
    filler_gap_threshold_s: float = 0.9
    max_caption_words: int = 7
    generate_ab_suggestions: bool = True


@dataclass
class CaptionSegment:
    start: float
    end: float
    text: str


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
            if seg_e > clip_start and seg_s < clip_end:
                # Convert to clip-relative timing
                rel_start = max(0.0, seg_s - clip_start)
                rel_end = min(clip_duration, seg_e - clip_start)
                
                txt = (seg.get("text") or "").strip()
                if txt:
                    win.append({"start": rel_start, "end": rel_end, "text": txt})
        
        n_segments = len(win)
        n_words = sum(len((item.get("text") or "").split()) for item in win)
        log.info(f"[WCE] transcript_window segments={n_segments} words={n_words} for clip {clip_start:.2f}-{clip_end:.2f}")
        return win

    def _trim_bounds(self, clip_duration: float, source_start: float, source_end: float, transcript_window: List[Dict[str, Any]], config: ClipEditConfig) -> Tuple[float, float]:
        if not config.auto_trim or not transcript_window:
            return (0.0, max(0.0, clip_duration))
        speech_start = min(_safe_float(x.get("start"), 0.0) for x in transcript_window)
        speech_end = max(_safe_float(x.get("end"), clip_duration) for x in transcript_window)
        trim_in = _clamp(speech_start - config.trim_pad_in_s, 0.0, max(0.0, clip_duration - 0.2))
        trim_out = _clamp(speech_end + config.trim_pad_out_s, trim_in + 0.2, clip_duration)
        if (trim_out - trim_in) < 8.0:
            return (0.0, clip_duration)
        return (trim_in, trim_out)

    def _cut_with_fade(self, input_path: str, output_path: str, start_s: float, end_s: float, timeout_s: int = 120) -> None:
        duration = max(0.25, end_s - start_s)
        fade_out_start = max(0.0, duration - 0.22)
        vf = f"fade=t=in:st=0:d=0.18,fade=t=out:st={fade_out_start:.3f}:d=0.22"
        af = f"afade=t=in:st=0:d=0.15,afade=t=out:st={max(0.0, duration - 0.2):.3f}:d=0.2"
        cmd = [
            "ffmpeg",
            "-y",
            "-nostdin",
            "-ss",
            f"{start_s:.3f}",
            "-to",
            f"{end_s:.3f}",
            "-i",
            input_path,
            "-vf",
            vf,
            "-af",
            af,
            *_video_encode_args(crf=23, preset="veryfast"),
            "-c:a",
            "aac",
            "-b:a",
            _get_export_audio_bitrate(),
            "-movflags",
            "+faststart",
            output_path,
        ]
        self._run(cmd, timeout_s=timeout_s)

    def _detect_primary_focus_x(self, clip_path: str) -> Union[float, str]:
        if cv2 is None:
            return 0.5
        cap = cv2.VideoCapture(clip_path)
        if not cap.isOpened():
            return 0.5
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 1000.0
        
        # Sample across the entire clip (aim for ~15-20 samples)
        step = max(1, int(total_frames / 18))
        
        frame_i = 0
        samples_time_x = []

        face_detector = None
        if mp is not None:
            try:
                face_detector = mp.solutions.face_detection.FaceDetection(model_selection=0, min_detection_confidence=0.5)
            except Exception:
                face_detector = None

        cascade = None
        if face_detector is None:
            try:
                cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
            except Exception:
                cascade = None

        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                if frame_i % step != 0:
                    frame_i += 1
                    continue
                h, w = frame.shape[:2]
                if h <= 1 or w <= 1:
                    frame_i += 1
                    continue

                centers = []
                if face_detector is not None:
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    res = face_detector.process(rgb)
                    for det in (res.detections or []):
                        bbox = det.location_data.relative_bounding_box
                        cx = _clamp(bbox.xmin + (bbox.width / 2.0), 0.0, 1.0)
                        centers.append(cx)
                elif cascade is not None:
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(36, 36))
                    for x, y, fw, fh in faces:
                        centers.append(_clamp((x + (fw / 2.0)) / float(w), 0.0, 1.0))

                t_sec = frame_i / fps
                if centers:
                    samples_time_x.append((t_sec, float(statistics.median(centers))))
                frame_i += 1
                if len(samples_time_x) >= 25:
                    break
        finally:
            cap.release()
            if face_detector is not None:
                try:
                    face_detector.close()
                except Exception:
                    pass

        if not samples_time_x:
            return 0.5
            
        x_vals = [s[1] for s in samples_time_x]
        if len(x_vals) < 3:
            return _clamp(float(statistics.median(x_vals)), 0.15, 0.85)
            
        variance = statistics.variance(x_vals)
        median_x = float(statistics.median(x_vals))
        
        log.info(f"[WCE-VISUAL] Face Tracking Variance: {variance:.4f} (median: {median_x:.2f})")
        
        if variance < 0.005:
            # Low variance -> Lock crop
            log.info("[WCE-VISUAL] Face tracking mode: STATIC LOCK (low variance)")
            return _clamp(median_x, 0.15, 0.85)
        elif variance > 0.08:
            # Chaotic movement -> Center crop fallback
            log.info("[WCE-VISUAL] Face tracking mode: CENTER FALLBACK (chaotic movement)")
            return 0.5
        else:
            # Moderate movement -> Smooth moving crop using FFmpeg lerp
            log.info("[WCE-VISUAL] Face tracking mode: SMOOTH DYNAMIC (moderate movement)")
            
            # Smooth out points with a basic moving average
            smoothed_points = []
            for i in range(len(samples_time_x)):
                start_i = max(0, i-1)
                end_i = min(len(samples_time_x), i+2)
                avg_x = sum(s[1] for s in samples_time_x[start_i:end_i]) / (end_i - start_i)
                avg_x = _clamp(avg_x, 0.15, 0.85)
                smoothed_points.append((samples_time_x[i][0], avg_x))
                
            # Build FFmpeg expression
            expr = str(round(smoothed_points[-1][1], 3))
            for i in range(len(smoothed_points)-2, -1, -1):
                t1, x1 = smoothed_points[i]
                t2, x2 = smoothed_points[i+1]
                dt = t2 - t1
                if dt <= 0: continue
                x1, x2 = round(x1, 3), round(x2, 3)
                lerp_str = f"lerp({x1},{x2},(t-{t1})/{dt})"
                expr = f"if(lt(t,{t2}),{lerp_str},{expr})"
                
            return expr

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

    def _build_reframe_filter(self, meta: Dict[str, Any], target_wh: Tuple[int, int], focus_x: Union[float, str], config: ClipEditConfig, boring_mode: bool) -> str:
        src_w = max(1, int(meta.get("width", 1920)))
        src_h = max(1, int(meta.get("height", 1080)))
        dst_w, dst_h = target_wh
        src_ar = src_w / float(src_h)
        dst_ar = dst_w / float(dst_h)

        if src_ar >= dst_ar:
            crop_h = src_h
            crop_w = max(2, int(round(src_h * dst_ar)))
            if isinstance(focus_x, str):
                # Dynamic expression
                raw_x = f"max(0,min({src_w}-{crop_w},{src_w}*({focus_x})-({crop_w}/2.0)))"
                crop_x = raw_x.replace(",", "\\,")
            else:
                x_center = src_w * _clamp(float(focus_x), 0.0, 1.0)
                crop_x = str(int(round(_clamp(x_center - (crop_w / 2.0), 0.0, src_w - crop_w))))
            crop_y = "0"
        else:
            crop_w = src_w
            crop_h = max(2, int(round(src_w / dst_ar)))
            crop_x = "0"
            crop_y = str(int(round((src_h - crop_h) / 2.0)))

        vf_parts = [f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y}", f"scale={dst_w}:{dst_h}:flags=lanczos"]
        
        # 2. PIXEL CLARITY / SHARPNESS (Premium Cinematic Look)
        # We removed hqdn3d and unsharp as they are massive CPU bottlenecks.
        # Only keeping lightweight EQ for punchy colors.
        vf_parts.append("eq=contrast=1.10:saturation=1.15:brightness=0.02:gamma=0.95")
        
        # 3. WATERMARK
        if os.getenv("HS_WATERMARK_ENABLED", "1") == "1":
            text = os.getenv("HS_WATERMARK_TEXT", "HOTSHORT")
            # Burn watermark lightly into the top-right corner
            vf_parts.append(f"drawtext=text='{text}':fontcolor=white@0.25:fontsize=H/35:x=W-tw-40:y=40:fontfile=C\\\\:/Windows/Fonts/segoeui.ttf")

        if isinstance(focus_x, str):
            log.info(f"[WCE-VISUAL] face_detected=True crop=DYNAMIC,{crop_y},{crop_w},{crop_h}")
        else:
            log.info(f"[WCE-VISUAL] face_detected=True crop={crop_x},{crop_y},{crop_w},{crop_h}")
            
        log.info("[WCE-VISUAL] clarity_filters=fast_eq_only")

        # NOTE: format=yuv420p is intentionally NOT appended here.
        # It must come AFTER the subtitles filter so libass can do
        # RGBA compositing on the frame before pixel-format conversion.
        return ",".join(vf_parts)

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
            "-i",
            input_path,
            "-filter_complex",
            fc,
            "-map",
            "[v]",
            "-map",
            "[a]",
            *_video_encode_args(crf=23, preset="veryfast"),
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
            (r"\b(secret|nobody tells|hidden)\b", " 🔥"),
            (r"\b(money|profit|revenue|sale)\b", " 💸"),
            (r"\b(ai|tool|automation)\b", " 🤖"),
            (r"\b(grow|growth|viral)\b", " 🚀"),
            (r"\b(fast|quick|instantly)\b", " ⚡"),
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
    ) -> List[CaptionSegment]:
        if not transcript_window:
            return []
        cap_segments: List[CaptionSegment] = []
        speed = _clamp(config.hook_ramp_speed, 1.01, 1.30)
        clip_rel_max = max(0.0, trim_out - trim_in)
        for seg in transcript_window:
            raw_start = _safe_float(seg.get("start"), 0.0)
            raw_end = _safe_float(seg.get("end"), raw_start)
            rel_start = max(0.0, raw_start - trim_in)
            rel_end = max(rel_start + 0.12, raw_end - trim_in)
            if rel_end <= 0.0 or rel_start >= clip_rel_max:
                continue
            rel_start = _clamp(rel_start, 0.0, clip_rel_max)
            rel_end = _clamp(rel_end, rel_start + 0.1, clip_rel_max)
            rel_start = self._adjust_for_ramp(rel_start, ramp_window, speed)
            rel_end = self._adjust_for_ramp(rel_end, ramp_window, speed)
            text = (seg.get("text") or "").strip()
            if not text:
                continue
            text = self._translate(text, config.translate_to)
            chunks = self._split_caption_text(text, max_words=max(3, config.max_caption_words))
            if not chunks:
                continue
            chunk_dur = max(0.16, (rel_end - rel_start) / len(chunks))
            for i, chunk in enumerate(chunks):
                c_s = rel_start + (i * chunk_dur)
                c_e = rel_start + ((i + 1) * chunk_dur)
                c_txt = self._decorate_caption(chunk, config.add_emojis)
                cap_segments.append(CaptionSegment(start=c_s, end=c_e, text=c_txt))
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
        # ─ Speaker-aware logic disabled. Always use uniform bottom-center ─
        # Alignment codes in ASS: 1=bottom-left, 2=bottom-center, 3=bottom-right
        caption_alignment = 2
        margin_l, margin_r, margin_v = 40, 40, 250
        log.info("[WCE-CAPTION] speaker-aware disabled → forced bottom-center (alignment=2) to guarantee alignment")

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
            # ── Word-by-word karaoke highlight ──────────────────────────────
            # Each word in the segment lights up in gold for its proportional
            # time slice. The rest of the line shows as the ghost (dim) style.
            words = seg.text.split()
            if len(words) > 1:
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
                    events.append(f"Dialogue: 0,{_ass_time(w_start)},{_ass_time(w_end)},Caption,,0,0,0,,{line_text}")
            else:
                # Single-word segment — just highlight it
                highlighted_text = self._highlight_text(escaped_text)
                events.append(f"Dialogue: 0,{_ass_time(seg.start)},{_ass_time(seg.end)},Caption,,0,0,0,,{highlighted_text}")

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
                if transcript_window and any(_safe_float(x.get("start"), 0.0) > clip_duration for x in transcript_window):
                    new_win = []
                    for x in transcript_window:
                        xs = _safe_float(x.get("start"), 0.0)
                        xe = _safe_float(x.get("end"), xs)
                        new_win.append({
                            "start": max(0.0, xs - source_start),
                            "end": min(clip_duration, xe - source_start),
                            "text": x.get("text", "")
                        })
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
                log.info(f"[WCE-FORENSIC] Loaded {len(transcript_window)} transcript words for {source_start}-{source_end}.")

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
                )
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

            t0 = time.perf_counter()
            work_meta = self._probe_video(work_b)
            t_reframe += time.perf_counter() - t0

            if cfg.enable_active_speaker:
                t0 = time.perf_counter()
                focus_x = self._detect_primary_focus_x(work_b)
                t_face += time.perf_counter() - t0
            else:
                focus_x = 0.5

            t0 = time.perf_counter()
            target_wh = self._resolve_ratio(cfg.target_ratio)
            vf = self._build_reframe_filter(work_meta, target_wh, focus_x, cfg, boring_mode)
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
            
            # Derive speaker side for caption positioning
            if isinstance(focus_x, str):
                speaker_side = "center"
            elif focus_x < 0.42:
                speaker_side = "left"
            elif focus_x > 0.58:
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
                vf_render = f"{vf_render},subtitles='{ass_esc}':fontsdir='{fonts_dir_esc}'"

                # ── Debug: verify .ass file before FFmpeg consumes it ──
                if os.path.exists(ass_path):
                    ass_size = os.path.getsize(ass_path)
                    log.info("[WCE-DEBUG] .ass file written OK: %s (%d bytes)", ass_path, ass_size)
                    try:
                        with open(ass_path, "r", encoding="utf-8") as _dbg:
                            _lines = _dbg.readlines()
                            _events = [l.strip() for l in _lines if l.startswith("Dialogue:")]
                            log.info("[WCE-DEBUG] .ass has %d Dialogue events (showing first 3):", len(_events))
                            for _ev in _events[:3]:
                                log.info("[WCE-DEBUG]   %s", _ev)
                    except Exception as _re:
                        log.warning("[WCE-DEBUG] Could not read .ass for debug: %s", _re)
                else:
                    log.error("[WCE-DEBUG] .ass file MISSING after _write_ass()! Path: %s", ass_path)

            # format=yuv420p MUST come after subtitles for correct RGBA compositing
            vf_render = f"{vf_render},format=yuv420p"

            is_watermarked = os.getenv("HS_WATERMARK_ENABLED") == "1" and (os.getenv("HS_WATERMARK_FREE_ONLY", "1") != "1" or is_free)
            wm_path = os.path.abspath("static/branding/logo_icon.png").replace("\\", "/")

            if is_watermarked:
                vf_render = f"[0:v]{vf_render}[v_main];[1:v]scale=90:-1[wm];[v_main][wm]overlay=W-w-30:H-h-120,drawtext=text='MADE WITH HOTSHORT':fontcolor=white@0.85:fontsize=28:borderw=2:bordercolor=black@0.5:x=w-text_w-25:y=h-80[out_v]"
                log.info("[WATERMARK] premium applied=true path=wce (fast-input mode)")

            log.info("[WCE-DEBUG] Final filter: %s", vf_render)

            cmd = [
                "ffmpeg",
                "-y",
                "-nostdin",
                "-i", work_b
            ]
            
            if is_watermarked:
                cmd.extend(["-i", wm_path])
                
            cmd.extend([
                "-filter_complex" if is_watermarked else "-vf",
                vf_render,
                "-map", "[out_v]" if is_watermarked else "0:v:0",
                "-map", "0:a:0?",
                "-r",
                str(max(24, int(cfg.export_fps))),
                *_video_encode_args(
                    crf=int(cfg.quality_crf if cfg.preserve_quality else 24),
                    preset=cfg.quality_preset if cfg.preserve_quality else "veryfast",
                ),
                "-movflags",
                "+faststart",
            ])
            if bool(work_meta.get("has_audio")):
                cmd += ["-af", af, "-c:a", "aac", "-b:a", _get_export_audio_bitrate()]
            else:
                cmd += ["-an"]
            cmd.append(output_path)
            t0 = time.perf_counter()
            self._run(cmd, timeout_s=220)
            t_encode += time.perf_counter() - t0

            has_hook = bool(clip_title.strip())
            score = self._estimate_engagement(captions, transcript_window, boring_mode=boring_mode, has_hook=has_hook)
            metadata["engagement_score"] = round(score, 2)
            metadata["captions_count"] = len(captions)
            metadata["focus_x"] = "dynamic" if isinstance(focus_x, str) else round(focus_x, 3)
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
