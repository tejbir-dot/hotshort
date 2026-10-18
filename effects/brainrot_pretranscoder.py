"""
brainrot_pretranscoder.py — One-time pre-transcoder and cache manager for Brainrot assets.
========================================================================================
Transcodes heavy 4K 60fps AV1 background videos to 1080x960 30fps H.264 (CRF 14, -an).
Saves ~60s of CPU decode time per podcast render.
"""

import os
import sys
import hashlib
import logging
import threading
import subprocess

log = logging.getLogger("brainrot_pretranscoder")

REPO_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BIN_FFMPEG = os.path.join(REPO_DIR, "bin", "ffmpeg.exe")
if not os.path.exists(BIN_FFMPEG):
    BIN_FFMPEG = "ffmpeg"

_TRANSCODE_LOCK = threading.Lock()
_ACTIVE_TRANSCODES = set()

def get_pretranscoded_brainrot(source_path: str, min_duration: int = 180) -> str:
    """
    Returns path to a pre-transcoded 1080x960 30fps H.264 version of source_path.
    If HS_BRAINROT_PRETRANSCODE=0, returns source_path untouched.
    If cache is missing, kicks off background transcode and returns source_path so render is never blocked.
    """
    enabled = os.getenv("HS_BRAINROT_PRETRANSCODE", "1").lower() in ("1", "true", "yes")
    if not enabled:
        return source_path

    if not source_path or not os.path.exists(source_path):
        return source_path

    try:
        source_stat = os.stat(source_path)
    except Exception as e:
        log.warning(f"[PRETRANSCODE] Could not stat {source_path}: {e}")
        return source_path

    # Cache directory: assets/brain_rot/_cache
    source_dir = os.path.dirname(os.path.abspath(source_path))
    cache_dir = os.path.join(source_dir, "_cache")
    try:
        os.makedirs(cache_dir, exist_ok=True)
    except Exception:
        pass

    # Deterministic cache key based on file size, mtime, and transcode parameters
    key_src = f"{source_stat.st_size}_{source_stat.st_mtime}_1080x960_30fps_crf14_dur{min_duration}"
    key_hash = hashlib.md5(key_src.encode("utf-8")).hexdigest()[:8]

    # Safe basename for file
    base_name = os.path.splitext(os.path.basename(source_path))[0]
    safe_base = "".join(c for c in base_name if c.isalnum() or c in ("-", "_")).strip()[:40]
    if not safe_base:
        safe_base = "brainrot"

    cache_filename = f"{safe_base}_{key_hash}_1080x960_30fps.mp4"
    cache_path = os.path.join(cache_dir, cache_filename)

    # 1. Hit: Cache exists and is non-empty
    if os.path.exists(cache_path) and os.path.getsize(cache_path) > 10000:
        log.info(f"[PRETRANSCODE] Using cached brainrot asset: {cache_filename}")
        return cache_path

    # 2. Miss: Kick off background transcode so render is NEVER blocked
    _trigger_background_transcode(source_path, cache_path, min_duration)

    # Fallback to source_path for the current render
    log.info(f"[PRETRANSCODE] Cache miss for {os.path.basename(source_path)} -> fallback to original, background transcode queued")
    return source_path


def transcode_asset_sync(source_path: str, target_path: str, duration: int = 180) -> bool:
    """
    Synchronously transcodes source_path to 1080x960 30fps H.264 CRF 14 (-an) for duration seconds.
    Writes to a .tmp file first, then atomically renames to target_path.
    """
    tmp_path = f"{target_path}.{os.getpid()}_{threading.get_ident()}.tmp.mp4"
    cmd = [
        BIN_FFMPEG, "-y", "-nostdin",
        "-i", source_path,
        "-t", str(duration),
        "-vf", "scale=1080:960:force_original_aspect_ratio=increase,crop=1080:960,fps=30",
        "-c:v", "libx264", "-crf", "14", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-an",
        tmp_path
    ]

    log.info(f"[PRETRANSCODE] Starting transcode: {os.path.basename(source_path)} -> {os.path.basename(target_path)} (dur={duration}s)")
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="ignore")
        if p.returncode == 0 and os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 10000:
            if os.path.exists(target_path):
                os.remove(target_path)
            os.replace(tmp_path, target_path)
            log.info(f"[PRETRANSCODE] Successfully created cached asset: {os.path.basename(target_path)} ({os.path.getsize(target_path)/(1024*1024):.1f} MB)")
            return True
        else:
            log.error(f"[PRETRANSCODE] FFmpeg transcode failed (exit {p.returncode}): {p.stderr[-300:]}")
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
            return False
    except Exception as e:
        log.error(f"[PRETRANSCODE] Exception during transcode: {e}")
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        return False


def _trigger_background_transcode(source_path: str, target_path: str, duration: int):
    with _TRANSCODE_LOCK:
        if target_path in _ACTIVE_TRANSCODES:
            return
        _ACTIVE_TRANSCODES.add(target_path)

    def _worker():
        try:
            transcode_asset_sync(source_path, target_path, duration)
        finally:
            with _TRANSCODE_LOCK:
                _ACTIVE_TRANSCODES.discard(target_path)

    t = threading.Thread(target=_worker, name=f"pretrans-{os.path.basename(target_path)}", daemon=True)
    t.start()
