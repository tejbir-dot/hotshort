"""
effects/vad_speaker.py
=======================
WebRTC VAD — Voice Activity Detection gate for the Director loop.

Uses Google's webrtcvad (already in requirements.txt) to detect
whether ANYONE is speaking at each moment in a video clip.

The output is a per-frame lookup dict:
    {frame_idx: bool}   True = voice activity detected

Architecture:
    1. Extract audio from clip via ffmpeg -> raw PCM (16kHz, mono, 16-bit)
    2. Run WebRTC VAD on 30ms frames (= 480 samples @ 16kHz)
    3. Map audio frames -> video frames by timestamp
    4. Return {frame_idx: bool} for the entire clip

Integration in world_class_editor.py:
    - Called ONCE before the frame loop (cheap: ~0.2s per clip)
    - In mouth-motion section: if vad_gate[frame_idx] is False,
      force mouth_motion_left = mouth_motion_right = 0.0
    - This kills ghost talking WITHOUT touching EMA logic

Why WebRTC VAD?
    - Google-built, battle-tested in Chrome/Meet
    - 3 aggressiveness modes (0=least, 3=most aggressive)
    - Runs in microseconds per 30ms frame (pure C, Python bindings)
    - Already installed: webrtcvad==2.0.10

Env vars:
    HS_VAD_ENABLED        = 1       (0 to disable)
    HS_VAD_AGGRESSIVENESS = 2       (0-3, higher = more aggressive filtering)
    HS_VAD_FRAME_MS       = 30      (10, 20, or 30ms per VAD frame)
"""

import os
import struct
import subprocess
import logging
import tempfile
from typing import Dict, Optional

log = logging.getLogger(__name__)

VAD_ENABLED       = os.environ.get("HS_VAD_ENABLED", "1") not in ("0", "false", "no")
VAD_AGGRESSIVENESS = int(os.environ.get("HS_VAD_AGGRESSIVENESS", "2"))
VAD_FRAME_MS      = int(os.environ.get("HS_VAD_FRAME_MS", "30"))   # 10, 20, or 30
VAD_SAMPLE_RATE   = 16000   # WebRTC VAD supports: 8000, 16000, 32000, 48000


def compute_vad_gate(
    clip_path: str,
    video_fps: float,
    total_frames: int,
    aggressiveness: int = VAD_AGGRESSIVENESS,
) -> Dict[int, bool]:
    """
    Pre-compute per-frame VAD signal for a clip.

    Returns {frame_idx: bool} where True = voice detected in that frame's window.
    On any failure, returns {} (empty = VAD disabled, caller skips gating).
    """
    if not VAD_ENABLED:
        return {}

    try:
        import webrtcvad
    except ImportError:
        log.warning("[VAD] webrtcvad not installed — skipping (pip install webrtcvad)")
        return {}

    # ── 1. Extract audio to raw PCM via ffmpeg ─────────────────────────────
    # -f s16le : signed 16-bit little-endian PCM (what webrtcvad wants)
    # -ac 1    : mono (mix stereo down)
    # -ar 16000: 16kHz sample rate
    # NOTE: Use temp file instead of pipe:1 — Windows ffmpeg doesn't support
    #       stdout piping for raw PCM (returns "Invalid argument").
    import tempfile as _tempfile
    _tmp_fd, _tmp_path = _tempfile.mkstemp(suffix=".pcm")
    os.close(_tmp_fd)

    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-i", clip_path,
        "-f", "s16le",
        "-ac", "1",
        "-ar", str(VAD_SAMPLE_RATE),
        "-y", _tmp_path,
    ]

    raw_pcm = b""
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=30)
        if result.returncode != 0:
            log.warning(f"[VAD] ffmpeg audio extract failed: {result.stderr[:200]}")
            return {}
        with open(_tmp_path, "rb") as _f:
            raw_pcm = _f.read()
    except subprocess.TimeoutExpired:
        log.warning("[VAD] ffmpeg timed out extracting audio")
        return {}
    except Exception as e:
        log.warning(f"[VAD] ffmpeg error: {e}")
        return {}
    finally:
        try:
            os.unlink(_tmp_path)
        except Exception:
            pass

    if not raw_pcm:
        log.warning("[VAD] No audio data extracted from clip")
        return {}

    # ── 2. Run WebRTC VAD on 30ms frames ──────────────────────────────────
    vad    = webrtcvad.Vad(aggressiveness)
    frame_bytes = int(VAD_SAMPLE_RATE * (VAD_FRAME_MS / 1000.0) * 2)  # 2 bytes/sample (int16)
    n_samples   = frame_bytes // 2

    # Build audio-time → bool list
    audio_segments: list = []  # list of (t_start_s, is_speech)
    pos = 0
    audio_t = 0.0
    dt_audio = VAD_FRAME_MS / 1000.0

    while pos + frame_bytes <= len(raw_pcm):
        chunk = raw_pcm[pos: pos + frame_bytes]
        try:
            is_speech = vad.is_speech(chunk, VAD_SAMPLE_RATE)
        except Exception:
            is_speech = True   # on error, assume speech (safe default)
        audio_segments.append((audio_t, is_speech))
        pos      += frame_bytes
        audio_t  += dt_audio

    if not audio_segments:
        return {}

    log.info(
        f"[VAD] clip={os.path.basename(clip_path)} "
        f"audio_frames={len(audio_segments)} "
        f"speech_pct={sum(1 for _,s in audio_segments if s)/len(audio_segments)*100:.1f}%"
    )

    # ── 3. Map audio time → video frame index ─────────────────────────────
    # Each video frame covers [frame_idx/fps, (frame_idx+1)/fps).
    # A video frame is "speech" if ANY overlapping audio VAD frame is True.
    dt_video = 1.0 / max(video_fps, 1.0)
    gate: Dict[int, bool] = {}

    seg_idx = 0
    for frame_idx in range(total_frames):
        t_frame_start = frame_idx * dt_video
        t_frame_end   = t_frame_start + dt_video

        # Advance segment pointer to this video frame window
        # Any VAD segment overlapping [t_frame_start, t_frame_end] counts
        is_speech = False
        for seg_t, seg_s in audio_segments:
            if seg_t + dt_audio < t_frame_start:
                continue
            if seg_t > t_frame_end:
                break
            if seg_s:
                is_speech = True
                break

        gate[frame_idx] = is_speech

    speech_frames = sum(1 for v in gate.values() if v)
    log.info(
        f"[VAD] gate built: {speech_frames}/{total_frames} frames speech "
        f"({speech_frames/max(total_frames,1)*100:.1f}%)"
    )
    return gate


def apply_vad_gate(
    vad_gate: Dict[int, bool],
    frame_idx: int,
    mouth_motion_left: float,
    mouth_motion_right: float,
) -> tuple:
    """
    Gate mouth motion values with VAD.
    If VAD says 'no speech at this frame', zero out both motion signals.

    Returns: (gated_mouth_motion_left, gated_mouth_motion_right)
    """
    if not vad_gate:
        return mouth_motion_left, mouth_motion_right  # VAD disabled

    if not vad_gate.get(frame_idx, True):
        # No speech detected in audio at this timestamp → ghost signal
        return 0.0, 0.0

    return mouth_motion_left, mouth_motion_right
