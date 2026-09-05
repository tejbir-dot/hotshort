"""
broll_engine.py — LEGACY STUB
==============================
This file is DEPRECATED. B-Roll is now handled by:
  - effects/smart_broll_matcher.py  (keyword → local video asset selection)
  - effects/dopamine_ending.py      (last-10s fast cuts + phonk music)

fetch_broll_asset() is kept as a no-op stub so existing imports don't break.
get_ken_burns_filter() is still used for any legacy code paths.
"""

import logging
log = logging.getLogger("broll_engine")


def fetch_broll_asset(keyword: str, output_path: str, width: int = 1080, height: int = 1920):
    """
    DEPRECATED: Used to fetch images from Pollinations.ai.
    Now returns None. B-Roll is handled by smart_broll_matcher.py.
    """
    log.warning(
        "[BROLL_ENGINE] fetch_broll_asset() called for keyword='%s' — "
        "THIS IS DEPRECATED. Use smart_broll_matcher.find_broll_cuts() instead. Skipping.",
        keyword
    )
    return None


def get_ken_burns_filter(
    start_time: float,
    duration: float,
    width: int = 1080,
    height: int = 1920,
    anchor_x: float = 0.5,
    anchor_y: float = 0.5,
    zoom_start: float = 1.0,
    zoom_end: float = 1.05,
) -> str:
    """
    Ken Burns zoompan filter for still images (kept for legacy compatibility).
    For VIDEO clips, scale+crop is used directly instead.
    """
    fps = 30
    total_frames = max(1, int(duration * fps))
    # Zoompan filter: slow zoom with anchor point
    # x/y offsets relative to zoom level
    z_expr = f"'min(zoom+0.0002,{zoom_end:.4f})'"
    x_expr = f"'iw*{anchor_x:.3f}*(1-1/zoom)'"
    y_expr = f"'ih*{anchor_y:.3f}*(1-1/zoom)'"
    return (
        f"zoompan=z={z_expr}:x={x_expr}:y={y_expr}"
        f":d={total_frames}:s={width}x{height}:fps={fps},"
        f"setpts=PTS-STARTPTS+{start_time:.3f}/TB,format=yuv420p"
    )
