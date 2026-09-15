"""
Dopamine Ending Engine
=======================
Injects a CINEMATIC DOPAMINE ENDING into the last N seconds of every clip:

1. FAST CUTS — randomly picks Dopamine asset clips (Daniel lifestyle shots),
   chops them into rapid 1.0-1.5s cuts, overlays them over the final speaker footage.

2. PHONK MUSIC FADE-IN — picks a random phonk track from assets/phonk_music/,
   fades it in over the last N seconds (starts at 0 volume, peaks at ~0.8 by the end).

Architecture:
  - Works as an FFmpeg filter_complex extension bolted onto the WCE render pass.
  - Returns: (extra_input_cmds, filter_graph_extension, output_pad_rename)
  - Caller (WCE) must append extra_input_cmds to ffmpeg cmd BEFORE filter_complex,
    and append filter_graph_extension to vf_render.

Usage:
    from effects.dopamine_ending import build_dopamine_ending
    extra_inputs, filter_ext, new_pad = build_dopamine_ending(
        clip_duration=ramped_duration,
        next_input_idx=next_idx,
        current_video_pad="hs_final_v",   # or "out_v" / "out_v_broll" etc.
        target_w=1080, target_h=1920,
        dopamine_window_s=10.0,
    )
"""

import os
import random
import logging
from typing import List, Tuple, Optional

log = logging.getLogger("dopamine_ending")

# ─────────────────────────────────────────────────────────────────────────────
# ASSET PATHS
# ─────────────────────────────────────────────────────────────────────────────
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOPAMINE_ASSET_DIR = os.path.join(_ROOT, "assets", "Dopamine_assets")
PHONK_MUSIC_DIR    = os.path.join(_ROOT, "assets", "phonk_music")

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _list_videos(folder: str) -> List[str]:
    """Return sorted list of video file paths in folder."""
    exts = (".mp4", ".mov", ".MP4", ".MOV", ".avi", ".AVI")
    try:
        return sorted([
            os.path.join(folder, f)
            for f in os.listdir(folder)
            if f.endswith(exts) and os.path.isfile(os.path.join(folder, f))
        ])
    except Exception:
        return []


def _list_audio(folder: str) -> List[str]:
    """Return sorted list of audio file paths in folder."""
    exts = (".mp3", ".wav", ".aac", ".m4a", ".ogg", ".flac")
    try:
        return sorted([
            os.path.join(folder, f)
            for f in os.listdir(folder)
            if os.path.splitext(f)[1].lower() in exts
            and os.path.isfile(os.path.join(folder, f))
        ])
    except Exception:
        return []


def _probe_duration(path: str) -> float:
    """Fast ffprobe to get video duration."""
    import subprocess, json
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_entries", "format=duration", path],
            capture_output=True, text=True, timeout=10
        )
        d = json.loads(r.stdout)
        return float(d["format"]["duration"])
    except Exception:
        return 5.0


# ─────────────────────────────────────────────────────────────────────────────
# MAIN ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def build_dopamine_ending(
    clip_duration: float,
    next_input_idx: int,
    current_video_pad: str,
    target_w: int = 1080,
    target_h: int = 1920,
    dopamine_window_s: float = 10.0,
    cut_dur_s: float = 1.2,
    music_volume: float = 0.65,
    fade_in_s: float = 3.0,
) -> Tuple[List[str], str, str]:
    """
    Build the dopamine ending injection.

    Args:
        clip_duration:       Total clip duration in seconds.
        next_input_idx:      Next available FFmpeg input index.
        current_video_pad:   Current final video pad label (e.g. 'hs_final_v').
        target_w / target_h: Output resolution.
        dopamine_window_s:   How many seconds from the end to inject dopamine.
        cut_dur_s:           Duration of each fast cut (seconds).
        music_volume:        Peak volume of phonk music (0.0–1.0).
        fade_in_s:           How long the music takes to fade in.

    Returns:
        (extra_ffmpeg_args, filter_graph_str, new_video_pad)
        - extra_ffmpeg_args: list to extend FFmpeg cmd with (inputs)
        - filter_graph_str:  semicolon-prefixed filter chain to append to vf_render
        - new_video_pad:     new video output pad label after dopamine
    """
    dopamine_videos = _list_videos(DOPAMINE_ASSET_DIR)
    if not dopamine_videos:
        log.warning("[DOPAMINE] No dopamine videos found in %s — skipping.", DOPAMINE_ASSET_DIR)
        return [], "", current_video_pad

    if clip_duration < dopamine_window_s + 2.0:
        log.info("[DOPAMINE] Clip too short (%.1fs) for dopamine ending — skipping.", clip_duration)
        return [], "", current_video_pad

    phonk_tracks = _list_audio(PHONK_MUSIC_DIR)
    has_music = bool(phonk_tracks)

    # ── 1. Plan cuts ──────────────────────────────────────────────────────────
    dopamine_start = clip_duration - dopamine_window_s
    n_cuts = int(dopamine_window_s / cut_dur_s)
    n_cuts = max(3, min(n_cuts, 8))  # clamp: 3–8 cuts

    # Shuffle and repeat dopamine videos to fill n_cuts (no back-to-back repeats)
    video_pool = dopamine_videos[:]
    random.shuffle(video_pool)
    cuts = []
    last_picked = None
    for i in range(n_cuts):
        candidates = [v for v in video_pool if v != last_picked] or video_pool
        picked = random.choice(candidates)
        cuts.append(picked)
        last_picked = picked

    log.info(
        "[DOPAMINE] 🎬 Ending: %.1fs window | %d fast cuts (%.1fs each) | music=%s",
        dopamine_window_s, n_cuts, cut_dur_s, "YES" if has_music else "NO"
    )
    for i, c in enumerate(cuts):
        t = dopamine_start + i * cut_dur_s
        log.info("  Cut %d: t=%.2fs → %s", i + 1, t, os.path.basename(c))

    # ── 2. Build FFmpeg extra inputs ──────────────────────────────────────────
    extra_args = []
    video_input_indices = []
    music_input_idx = None

    idx = next_input_idx
    for i, path in enumerate(cuts):
        # Probe the asset duration to find a safe random seek
        asset_dur = _probe_duration(path)
        max_seek = max(0.0, asset_dur - cut_dur_s - 0.5)
        seek = round(random.uniform(0.0, max_seek), 3) if max_seek > 0 else 0.0
        extra_args.extend(["-ss", f"{seek:.3f}", "-t", f"{cut_dur_s + 0.3:.3f}", "-i", path])
        video_input_indices.append(idx)
        idx += 1

    if has_music:
        music_path = random.choice(phonk_tracks)
        # Seek into music randomly (avoid starting from silence at start)
        music_seek = round(random.uniform(5.0, 30.0), 3)
        extra_args.extend(["-ss", f"{music_seek:.3f}", "-t", f"{dopamine_window_s + 1.0:.3f}", "-i", music_path])
        music_input_idx = idx
        idx += 1
        log.info("[DOPAMINE] 🎵 Music: %s (seek=%.1fs)", os.path.basename(music_path), music_seek)

    # ── 3. Build filter graph ─────────────────────────────────────────────────
    filter_parts = []
    _fd = 0.12   # burn-on fade per cut (seconds)
    _fade_out_s = cut_dur_s - _fd

    for i, vinput_idx in enumerate(video_input_indices):
        _t_start = dopamine_start + i * cut_dur_s
        _t_end   = _t_start + cut_dur_s

        # Clip prep: reset pts, scale-to-fill, crop to exact portrait, burn fade
        clip_prep = (
            f"setpts=PTS-STARTPTS,"
            f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
            f"crop={target_w}:{target_h},"
            f"fps=30,format=yuv420p,"
            f"fade=t=in:st=0:d={_fd:.3f},"
            f"fade=t=out:st={_fade_out_s:.3f}:d={_fd:.3f}"
        )
        filter_parts.append(f"[{vinput_idx}:v]{clip_prep}[dp_v_{i}]")

        out_pad = "dp_final_v" if i == len(video_input_indices) - 1 else f"dp_tmp_{i}"
        in_pad  = current_video_pad if i == 0 else f"dp_tmp_{i-1}"
        filter_parts.append(
            f"[{in_pad}][dp_v_{i}]overlay="
            f"enable='between(t,{_t_start:.3f},{_t_end:.3f})'"
            f":x=0:y=0:eof_action=pass[{out_pad}]"
        )

    new_video_pad = "dp_final_v"

    # ── 4. Music fade-in ──────────────────────────────────────────────────────
    music_filter = ""
    if has_music and music_input_idx is not None:
        # adelay: push music to start exactly at dopamine_start
        delay_ms = int(dopamine_start * 1000)
        music_filter = (
            f"[{music_input_idx}:a]"
            f"adelay={delay_ms}|{delay_ms},"
            f"volume=0:enable='lt(t,{dopamine_start:.3f})',"
            f"afade=t=in:st={dopamine_start:.3f}:d={fade_in_s:.3f},"
            f"volume={music_volume:.2f}[dp_music_a]"
        )
        filter_parts.append(music_filter)

    filter_graph = ";" + ";".join(filter_parts)

    return extra_args, filter_graph, new_video_pad, (music_input_idx is not None)
