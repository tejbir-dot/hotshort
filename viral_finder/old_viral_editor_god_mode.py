
"""
viral_editor_god_mode.py  — V22 TITAN EDITOR

High–end, production–safe editor for HotShort Studio.

- Uses FFmpeg directly (GPU first, CPU fallback)
- 9:16 face–aware crop to 1080x1920
- Gentle zoom based on motion score (passed from engine)
- Cinematic color grade (contrast + saturation)
- Optional glow layer
- Sharp ASS subtitles (with WIN path–safe handling)
- Subtitle failures auto-fallback (no crash)
- NVENC first, libx264 fallback if GPU encoder not available

Usage from app.py:

    from viral_finder.viral_editor_god_mode import viral_editor_god_mode

    success = viral_editor_god_mode(
        video_path,
        segment_dict,      # {"start": float, "end": float, "text": str, "motion": float}
        output_path
    )
"""

import os
import math
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, Any, Tuple, Optional

# cv2 is only for face detection; we fail gracefully if missing
try:
    import cv2
    _HAS_CV2 = True
except Exception:
    _HAS_CV2 = False

# ----------------- CONFIG -----------------
FFMPEG_BIN = "ffmpeg"
FFPROBE_BIN = "ffprobe"

TARGET_W = 1080
TARGET_H = 1920

# encoder preferences
USE_NVENC = True               # try h264_nvenc first
NVENC_PRESET = "p4"
NVENC_BITRATE = "6M"
X264_PRESET = "slow"
X264_BITRATE = "6M"

AUDIO_CODEC = "aac"
AUDIO_BITRATE = "128k"

# glow + grade
DEFAULT_GLOW_STRENGTH = 0.22
DEFAULT_ZOOM_MIN = 1.03
DEFAULT_ZOOM_MAX = 1.18

# subtitle appearance
FONT_PATH = "Inter-Bold.ttf"   # will use font name; file just for name
FONT_SIZE = 64
ASS_MARGIN_V = 110             # bottom margin
ASS_PRIMARY = "&H00FFD77C&"    # gold-ish
ASS_OUTLINE = "&H00000000&"

# ------------------------------------------


def _log(*args):
    print("[EDITOR V22]", *args)


def _run_ffmpeg(cmd) -> Tuple[int, bytes, bytes]:
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False
    )
    out, err = proc.communicate()
    return proc.returncode, out, err


# ---------- ASS subtitle builder ----------

def _ass_escape(text: str) -> str:
    # basic ASS escaping
    text = text.replace("\\", r"\\")
    text = text.replace("{", r"\{").replace("}", r"\}")
    text = text.replace("\n", r"\N")
    text = text.replace(",", r"\,")
    return text


def build_ass(text: str, ass_path: Path, clip_duration: float) -> Path:
    """
    Build a single-line ASS subtitle that lives for the whole clip.
    """
    text = (text or "").strip()
    if not text:
        text = " "

    esc = _ass_escape(text)

    def fmt(t: float) -> str:
        t = max(0.0, float(t))
        h = int(t // 3600)
        m = int((t % 3600) // 60)
        s = t % 60
        return f"{h:d}:{m:02d}:{s:05.2f}"

    start = fmt(0.0)
    end = fmt(clip_duration + 1.5)

    font_name = Path(FONT_PATH).stem or "Inter"

    content = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {TARGET_W}
PlayResY: {TARGET_H}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: HotShort,{font_name},{FONT_SIZE},{ASS_PRIMARY},&H00FFFFFF&,{ASS_OUTLINE},&H00000000&,0,0,0,0,100,100,0,0,1,3,0,2,20,20,{ASS_MARGIN_V},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,{start},{end},HotShort,,0,0,{ASS_MARGIN_V},,{esc}
"""

    ass_path.write_text(content, encoding="utf-8")
    return ass_path


# ---------- Probing + face center ----------

def probe_size(video_path: str) -> Tuple[int, int]:
    cmd = [
        FFPROBE_BIN,
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "default=nokey=1:noprint_wrappers=1",
        video_path,
    ]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False)
        lines = proc.stdout.decode("utf-8", errors="ignore").strip().splitlines()
        if len(lines) >= 2:
            w = int(lines[0].strip())
            h = int(lines[1].strip())
            return w, h
    except Exception:
        pass
    return 1280, 720  # safe fallback


def detect_face_center(video_path: str, sample_time: float) -> Optional[Tuple[int, int]]:
    if not _HAS_CV2:
        return None

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None

    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        duration = total / fps if fps > 0 else 0.0

        t = max(0.2, min(sample_time, max(duration - 0.2, 0.2)))
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
        ok, frame = cap.read()
        if not ok:
            cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(total // 2)))
            ok, frame = cap.read()
            if not ok:
                return None

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        faces = cascade.detectMultiScale(gray, 1.15, 4, minSize=(60, 60))
        h, w = gray.shape[:2]
        if len(faces) == 0:
            return w // 2, h // 2
        x, y, fw, fh = max(faces, key=lambda r: r[2] * r[3])
        return int(x + fw / 2), int(y + fh / 2)
    finally:
        cap.release()


def compute_crop(
    src_w: int,
    src_h: int,
    face_center: Optional[Tuple[int, int]]
) -> Tuple[int, int, int, int, int, int]:
    """
    Returns (scaled_w, scaled_h, crop_x, crop_y, crop_w, crop_h)
    for 9:16 crop centred on face if available.
    """
    src_ar = src_w / src_h
    tgt_ar = TARGET_W / TARGET_H

    if src_ar > tgt_ar:
        # source wider, fit height
        scale = TARGET_H / src_h
    else:
        # source taller, fit width
        scale = TARGET_W / src_w

    sw = max(int(round(src_w * scale)), TARGET_W)
    sh = max(int(round(src_h * scale)), TARGET_H)

    if face_center:
        fx, fy = face_center
    else:
        fx, fy = src_w // 2, src_h // 2

    fx_s = int(round(fx * scale))
    fy_s = int(round(fy * scale))

    cw, ch = TARGET_W, TARGET_H

    cx = max(0, min(sw - cw, fx_s - cw // 2))
    cy = max(0, min(sh - ch, fy_s - ch // 2))

    return sw, sh, cx, cy, cw, ch


# ---------- Filter complex builder ----------

def build_filter_complex(
    ass_path: Path,
    main_zoom: float,
    glow_strength: float
) -> str:
    """
    Build filter_complex string for:
      - scale/crop already baked into main_vf
      - gentle zoom
      - color grade
      - glow
      - subtitles (using @'file' syntax for safe Windows paths)
    main_zoom: zoom factor between 1.0 and ~1.2
    """
    glow_strength = max(0.0, min(glow_strength, 0.5))
    main_zoom = max(1.0, min(main_zoom, 1.25))

    # 1) base: already scaled+cropped in main_vf -> [base]
    # 2) zoom = scale then crop back to 1080x1920
    z_w = int(round(TARGET_W * main_zoom))
    z_h = int(round(TARGET_H * main_zoom))
    zx = (z_w - TARGET_W) // 2
    zy = (z_h - TARGET_H) // 2

    vf_parts = [
        f"scale={TARGET_W}:{TARGET_H}",
        f"scale={z_w}:{z_h}",
        f"crop={TARGET_W}:{TARGET_H}:{zx}:{zy}",
        "eq=contrast=1.10:brightness=0.02:saturation=1.10"
    ]

    main_vf = ",".join(vf_parts)

    ass_abs = ass_path.resolve()
    # make unix-style safe path and use @'file' notation
    ass_clean = ass_abs.as_posix()
    subtitle_filter = f"subtitles=@'{ass_clean}'"

    filter_complex = (
        f"[0:v]{main_vf}[base];"
        f"[base]split[o][b];"
        f"[b]boxblur=10:1[blur];"
        f"[blur][o]blend=all_mode='screen':all_opacity={glow_strength}[g];"
        f"[g]{subtitle_filter}"
    )

    return filter_complex


# ---------- MAIN ENTRY ----------

def viral_editor_god_mode(input_path: str, seg: Dict[str, Any], out_path: str) -> bool:
    """
    Main entry used by Flask app.

    input_path : full path to source video file
    seg        : dict with at least "start", "end", "text"
                 optionally "motion" -> drives zoom strength
    out_path   : where to render final clip

    Returns True on success, raises RuntimeError on hard error.
    """
    input_path = str(input_path)
    out_path = str(out_path)

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    start = float(seg.get("start", 0.0))
    end = float(seg.get("end", start + 8.0))
    duration = max(0.1, end - start)

    text = (seg.get("text") or "").strip()
    motion = float(seg.get("motion", 0.0))

    # map motion → zoom factor
    # 0–40   → 1.03–1.10
    # 40–80  → 1.10–1.18
    base_zoom = DEFAULT_ZOOM_MIN + (DEFAULT_ZOOM_MAX - DEFAULT_ZOOM_MIN) * min(motion, 80.0) / 80.0

    _log(f"START — len={duration:.1f}s, motion={motion:.2f}, zoom={base_zoom:.3f}")

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        trim_path = td_path / "trim.mp4"
        ass_path = td_path / "caption.ass"

        # 1) fast trim
        trim_cmd = [
            FFMPEG_BIN,
            "-ss", f"{start:.3f}",
            "-i", input_path,
            "-t", f"{duration:.3f}",
            "-c", "copy",
            "-y", str(trim_path),
        ]
        rc, out, err = _run_ffmpeg(trim_cmd)
        if rc != 0:
            # fallback: re-encode trim
            _log("Fast trim failed → reencode trim…")
            trim_cmd2 = [
                FFMPEG_BIN,
                "-ss", f"{start:.3f}",
                "-i", input_path,
                "-t", f"{duration:.3f}",
                "-c:v", "libx264",
                "-preset", "fast",
                "-c:a", AUDIO_CODEC,
                "-b:a", AUDIO_BITRATE,
                "-y", str(trim_path),
            ]
            rc, out, err = _run_ffmpeg(trim_cmd2)
            if rc != 0:
                raise RuntimeError(f"Trim failed:\n{err.decode(errors='ignore')}")

        # 2) probe + face
        w, h = probe_size(str(trim_path))
        face_center = detect_face_center(str(trim_path), sample_time=duration / 2.0)
        sw, sh, cx, cy, cw, ch = compute_crop(w, h, face_center)

        # 3) build ASS
        build_ass(text, ass_path, clip_duration=duration)

        # 4) build filter_complex
        filter_complex = build_filter_complex(ass_path, main_zoom=base_zoom, glow_strength=DEFAULT_GLOW_STRENGTH)

        # 5) render (NVENC → x264 fallback, subtitles → no-sub fallback)

        def _render_with(subs_enabled: bool, use_nvenc: bool) -> Tuple[int, bytes, bytes]:
            vf = f"scale={sw}:{sh},crop={cw}:{ch}:{cx}:{cy}"
            # we already fold scale/crop again inside build_filter_complex,
            # but this base stage ensures correct framing pre-grade.
            full_filter = filter_complex if subs_enabled else filter_complex.rsplit(";", 1)[0]

            # Replace first "[0:v]" chain with scaling/crop
            full_filter = full_filter.replace("[0:v]", f"[0:v]{vf},")

            cmd = [
                FFMPEG_BIN,
                "-i", str(trim_path),
                "-filter_complex", full_filter,
                "-map", "[g]" if subs_enabled else "[g]",
                "-map", "0:a?",
            ]

            if use_nvenc:
                cmd += ["-c:v", "h264_nvenc", "-preset", NVENC_PRESET, "-b:v", NVENC_BITRATE]
            else:
                cmd += ["-c:v", "libx264", "-preset", X264_PRESET, "-b:v", X264_BITRATE]

            cmd += [
                "-c:a", AUDIO_CODEC,
                "-b:a", AUDIO_BITRATE,
                "-y", out_path,
            ]
            return _run_ffmpeg(cmd)

        # Try order:
        # 1) NVENC + subtitles
        # 2) x264  + subtitles
        # 3) NVENC without subtitles
        # 4) x264  without subtitles

        tried_errors = []

        for subs, nvenc in [
            (True, USE_NVENC),
            (True, False),
            (False, USE_NVENC),
            (False, False),
        ]:
            if not USE_NVENC and nvenc:
                continue  # skip NVENC attempts if flag disabled

            mode_desc = f"{'NVENC' if nvenc else 'x264'} + {'subs' if subs else 'no-subs'}"
            _log("Render try:", mode_desc)
            rc, out, err = _render_with(subs_enabled=subs, use_nvenc=nvenc)
            if rc == 0:
                _log("Render OK with", mode_desc)
                return True

            err_text = err.decode(errors="ignore")
            tried_errors.append(f"==== {mode_desc} ====\n{err_text}\n")

            # if subtitles clearly at fault, skip further subtitle attempts
            if "subtitles" in err_text or "Unable to parse option value" in err_text:
                _log("Subtitle filter seems broken in FFmpeg → falling back to no-subs mode.")
                # continue loop; next iterations will include no-subs modes
                continue

        # if all fail
        raise RuntimeError("FFmpeg failed in all modes:\n" + "\n".join(tried_errors))


# CLI test
if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("input")
    p.add_argument("--start", type=float, default=0.0)
    p.add_argument("--end", type=float, default=8.0)
    p.add_argument("--text", type=str, default="This is a test caption")
    p.add_argument("--motion", type=float, default=20.0)
    p.add_argument("--out", type=str, default="out_edit_v22.mp4")
    args = p.parse_args()

    seg = {
        "start": args.start,
        "end": args.end,
        "text": args.text,
        "motion": args.motion,
    }
    _log("CLI test…")
    viral_editor_god_mode(args.input, seg, args.out)
    _log("Done →", args.out)
