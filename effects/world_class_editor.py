import json
import logging
import os
import re
import shutil
import statistics
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

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

log = logging.getLogger("world_class_editor")


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
    p = (path_value or "").replace("\\", "/")
    p = p.replace(":", r"\:")
    p = p.replace("'", r"\'")
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
    quality_crf: int = 15
    quality_preset: str = "medium"
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
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout_s)

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
        s = float(source_start or 0.0)
        e = float(source_end or s)
        win = []
        for seg in transcript:
            seg_s = _safe_float(seg.get("start"), 0.0)
            seg_e = _safe_float(seg.get("end"), seg_s)
            if seg_e <= s or seg_s >= e:
                continue
            txt = (seg.get("text") or "").strip()
            if txt:
                win.append({"start": seg_s, "end": seg_e, "text": txt})
        return win

    def _trim_bounds(self, clip_duration: float, source_start: float, source_end: float, transcript_window: List[Dict[str, Any]], config: ClipEditConfig) -> Tuple[float, float]:
        if not config.auto_trim or not transcript_window:
            return (0.0, max(0.0, clip_duration))
        speech_start = min(_safe_float(x.get("start"), source_start) for x in transcript_window)
        speech_end = max(_safe_float(x.get("end"), source_end) for x in transcript_window)
        trim_in = _clamp((speech_start - source_start) - config.trim_pad_in_s, 0.0, max(0.0, clip_duration - 0.2))
        trim_out = _clamp((speech_end - source_start) + config.trim_pad_out_s, trim_in + 0.2, clip_duration)
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
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "16",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-movflags",
            "+faststart",
            output_path,
        ]
        self._run(cmd, timeout_s=timeout_s)

    def _detect_primary_focus_x(self, clip_path: str) -> float:
        if cv2 is None:
            return 0.5
        cap = cv2.VideoCapture(clip_path)
        if not cap.isOpened():
            return 0.5
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        step = max(1, int(round(fps * 1.2)))
        frame_i = 0
        samples = []

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

                if centers:
                    samples.append(float(statistics.median(centers)))
                frame_i += 1
                if len(samples) >= 24:
                    break
        finally:
            cap.release()
            if face_detector is not None:
                try:
                    face_detector.close()
                except Exception:
                    pass

        if not samples:
            return 0.5
        return _clamp(float(statistics.median(samples)), 0.15, 0.85)

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

    def _build_reframe_filter(self, meta: Dict[str, Any], target_wh: Tuple[int, int], focus_x: float, config: ClipEditConfig, boring_mode: bool) -> str:
        src_w = max(1, int(meta.get("width", 1920)))
        src_h = max(1, int(meta.get("height", 1080)))
        dst_w, dst_h = target_wh
        src_ar = src_w / float(src_h)
        dst_ar = dst_w / float(dst_h)

        if src_ar >= dst_ar:
            crop_h = src_h
            crop_w = max(2, int(round(src_h * dst_ar)))
            x_center = src_w * _clamp(focus_x, 0.0, 1.0)
            crop_x = int(round(_clamp(x_center - (crop_w / 2.0), 0.0, src_w - crop_w)))
            crop_y = 0
        else:
            crop_w = src_w
            crop_h = max(2, int(round(src_w / dst_ar)))
            crop_x = 0
            crop_y = int(round((src_h - crop_h) / 2.0))

        vf_parts = [f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y}", f"scale={dst_w}:{dst_h}:flags=lanczos"]
        if config.enhance_visuals:
            vf_parts.append("eq=contrast=1.06:saturation=1.11:brightness=0.01")
            vf_parts.append("unsharp=5:5:0.75:3:3:0.1")
            if boring_mode:
                vf_parts.append("scale=iw*1.03:ih*1.03")
                vf_parts.append("crop=iw/1.03:ih/1.03")
        vf_parts.append("format=yuv420p")
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
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "16",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
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
            raw_start = _safe_float(seg.get("start"), source_start) - source_start
            raw_end = _safe_float(seg.get("end"), raw_start) - source_start
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
    ) -> None:
        font_size = 50 if height >= 1700 else 38
        hook_size = max(30, int(font_size * 0.74))
        cta_size = max(26, int(font_size * 0.56))
        header = [
            "[Script Info]",
            "ScriptType: v4.00+",
            f"PlayResX: {width}",
            f"PlayResY: {height}",
            "ScaledBorderAndShadow: yes",
            "",
            "[V4+ Styles]",
            "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,"
            "Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,"
            "MarginL,MarginR,MarginV,Encoding",
            # ASS colors use AABBGGRR. Keep a neutral, high-contrast palette.
            f"Style: Caption,Arial,{font_size},&H00F8FAFC,&H00F8FAFC,&H00101214,&H6E000000,1,0,0,0,100,100,0,0,1,1.6,0.4,2,72,72,132,1",
            f"Style: Hook,Arial,{hook_size},&H00F8FAFC,&H00F8FAFC,&H00101214,&H72000000,1,0,0,0,100,100,0,0,3,0,0,8,92,92,224,1",
            f"Style: CTA,Arial,{cta_size},&H00F8FAFC,&H00F8FAFC,&H00101214,&H72000000,1,0,0,0,100,100,0,0,3,0,0,2,74,74,76,1",
            "",
            "[Events]",
            "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text",
        ]
        events = []
        for seg in captions:
            if seg.end <= seg.start:
                continue
            events.append(f"Dialogue: 0,{_ass_time(seg.start)},{_ass_time(seg.end)},Caption,,0,0,0,,{_ass_escape(seg.text)}")
        if hook_line:
            hook_text = self._format_hook_line(hook_line)
            if hook_text:
                hook_end = min(duration, 2.2)
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
        vf = f"subtitles='{_ffmpeg_filter_path(ass_path)}'"
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
            "-c:v",
            "libx264",
            "-preset",
            "slow" if preserve_quality else "veryfast",
            "-crf",
            "17" if preserve_quality else "20",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
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
            base_meta = self._probe_video(input_path)
            clip_duration = max(0.01, float(base_meta.get("duration") or 0.0))
            if precomputed_narrative and isinstance(precomputed_narrative, dict):
                transcript_window = list(precomputed_narrative.get("transcript_window") or [])
                boring_mode = bool(precomputed_narrative.get("boring_monologue_detected", False))
                pre_trim = precomputed_narrative.get("trim")
            else:
                transcript_window = self._window_transcript(transcript, source_start, source_end)
                boring_mode = self._is_boring_monologue(transcript_window)
                pre_trim = None
            metadata["boring_monologue_detected"] = bool(boring_mode)

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
            if cfg.add_captions and captions:
                ass_path = os.path.join(self.work_dir, f"wc_subs_{uuid.uuid4().hex}.ass")
                tmp_files.append(ass_path)
                hook_line = clip_title.strip() if clip_title else captions[0].text
                cta_line = "Follow for more creator breakdowns"
                hashtags_line = self._extract_hashtags(transcript_window) if cfg.add_hashtags else None
                self._write_ass(
                    path=ass_path,
                    width=target_wh[0],
                    height=target_wh[1],
                    duration=max(0.1, ramped_duration),
                    captions=captions,
                    hook_line=hook_line if cfg.add_dynamic_overlays else None,
                    cta_line=cta_line if cfg.add_cta else None,
                    hashtags_line=hashtags_line,
                )
                vf_render = f"{vf_render},subtitles='{_ffmpeg_filter_path(ass_path)}'"

            cmd = [
                "ffmpeg",
                "-y",
                "-nostdin",
                "-i",
                work_b,
                "-vf",
                vf_render,
                "-map",
                "0:v:0",
                "-map",
                "0:a:0?",
                "-r",
                str(max(24, int(cfg.export_fps))),
                "-c:v",
                "libx264",
                "-preset",
                cfg.quality_preset if cfg.preserve_quality else "veryfast",
                "-crf",
                str(int(cfg.quality_crf if cfg.preserve_quality else 20)),
                "-movflags",
                "+faststart",
            ]
            if bool(work_meta.get("has_audio")):
                cmd += ["-af", af, "-c:a", "aac", "-b:a", "192k"]
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
