import os
import re
import uuid
import time
import tempfile
import queue
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
import hashlib
from urllib.parse import urlparse
from typing import TYPE_CHECKING, List, Dict
from dotenv import load_dotenv

# instrumentation helpers
import logging
try:
    import psutil
except Exception:
    psutil = None

if TYPE_CHECKING:
    from psutil import Process as PsutilProcess
else:
    PsutilProcess = object

RESOURCE_LOG_ENABLED = os.getenv("HS_RESOURCE_LOG", "1").strip().lower() in ("1", "true", "yes", "on")
RESOURCE_LOG_REQUESTS = os.getenv("HS_RESOURCE_LOG_REQUESTS", "1").strip().lower() in ("1", "true", "yes", "on")
RESOURCE_INCLUDE_CHILDREN = os.getenv("HS_RESOURCE_INCLUDE_CHILDREN", "1").strip().lower() in ("1", "true", "yes", "on")
RESOURCE_LOG_HEAVY_ONLY = os.getenv("HS_RESOURCE_LOG_HEAVY_ONLY", "1").strip().lower() in ("1", "true", "yes", "on")
RESOURCE_HEAVY_PATHS = (
    "/analyze",
    "/generate",
    "/start",
    "/progress",
    "/events",
)
try:
    RESOURCE_MONITOR_INTERVAL_SECONDS = float(os.getenv("HS_RESOURCE_MONITOR_INTERVAL_SECONDS", "0") or 0)
except Exception:
    RESOURCE_MONITOR_INTERVAL_SECONDS = 0.0

_RESOURCE_MONITOR_STARTED = False
_RESOURCE_MONITOR_LOCK = threading.Lock()


def _bytes_to_mb(num_bytes: int) -> float:
    return float(num_bytes or 0) / (1024.0 * 1024.0)


def _safe_cpu_seconds(proc: PsutilProcess) -> float:
    if psutil is None:
        return 0.0
    try:
        c = proc.cpu_times()
        return float(getattr(c, "user", 0.0) + getattr(c, "system", 0.0))
    except Exception:
        return 0.0


def _safe_mem_rss(proc: PsutilProcess) -> int:
    if psutil is None:
        return 0
    try:
        return int(proc.memory_info().rss or 0)
    except Exception:
        return 0


def _snapshot_resources(include_children: bool = True) -> dict:
    if psutil is None:
        return {
            "pid": int(os.getpid()),
            "rss": 0,
            "cpu_s": 0.0,
            "threads": 0,
            "child_rss": 0,
            "child_cpu_s": 0.0,
            "child_count": 0,
            "handles": None,
        }
    proc = psutil.Process(os.getpid())
    rss = _safe_mem_rss(proc)
    cpu_s = _safe_cpu_seconds(proc)

    child_rss = 0
    child_cpu_s = 0.0
    child_count = 0
    if include_children:
        try:
            for child in proc.children(recursive=True):
                child_count += 1
                child_rss += _safe_mem_rss(child)
                child_cpu_s += _safe_cpu_seconds(child)
        except Exception:
            pass

    threads = 0
    try:
        threads = int(proc.num_threads() or 0)
    except Exception:
        threads = 0

    handles = None
    try:
        if hasattr(proc, "num_handles"):
            handles = int(proc.num_handles() or 0)
    except Exception:
        handles = None

    return {
        "pid": int(proc.pid),
        "rss": int(rss),
        "cpu_s": float(cpu_s),
        "threads": int(threads),
        "child_rss": int(child_rss),
        "child_cpu_s": float(child_cpu_s),
        "child_count": int(child_count),
        "handles": handles,
    }


def log_mem(stage: str):
    if not RESOURCE_LOG_ENABLED:
        return
    snap = _snapshot_resources(include_children=RESOURCE_INCLUDE_CHILDREN)
    total_rss_mb = _bytes_to_mb(snap["rss"] + snap["child_rss"])
    logging.info(
        "[RES] stage=%s pid=%d rss=%.1fMB child_rss=%.1fMB total_rss=%.1fMB "
        "cpu_s=%.2f child_cpu_s=%.2f threads=%d child_count=%d handles=%s",
        stage,
        snap["pid"],
        _bytes_to_mb(snap["rss"]),
        _bytes_to_mb(snap["child_rss"]),
        total_rss_mb,
        snap["cpu_s"],
        snap["child_cpu_s"],
        snap["threads"],
        snap["child_count"],
        str(snap["handles"]) if snap["handles"] is not None else "n/a",
    )


def _start_resource_monitor_thread():
    global _RESOURCE_MONITOR_STARTED
    if not RESOURCE_LOG_ENABLED or RESOURCE_MONITOR_INTERVAL_SECONDS <= 0:
        return
    with _RESOURCE_MONITOR_LOCK:
        if _RESOURCE_MONITOR_STARTED:
            return
        _RESOURCE_MONITOR_STARTED = True

    def _loop():
        while True:
            try:
                log_mem("heartbeat")
            except Exception:
                pass
            time.sleep(max(5.0, float(RESOURCE_MONITOR_INTERVAL_SECONDS)))

    t = threading.Thread(target=_loop, name="resource-monitor", daemon=True)
    t.start()


def _should_log_request_resource(path: str) -> bool:
    if not RESOURCE_LOG_HEAVY_ONLY:
        return True
    p = str(path or "")
    return any(p.startswith(prefix) for prefix in RESOURCE_HEAVY_PATHS)
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
load_dotenv(dotenv_path=os.path.join(BASE_DIR, ".env"))
import os
from flask import Flask
from flask import Flask, render_template, request, redirect, url_for, Response, send_file, session, flash, jsonify, after_this_request, g
from flask_login import LoginManager, current_user, login_required, login_user
from werkzeug.middleware.proxy_fix import ProxyFix
from models.user import db, User, Clip, Job, FreeClipClaim
from flask_migrate import Migrate
from video_pipeline import generate_clip_for_job
from routes.auth import auth  # 👈 all auth routes now separated
from flask_dance.contrib.google import make_google_blueprint, google
# from viral_finder.viral_finder_engine_v30 import find_viral_moments as backup_find
from utils.narrative_intelligence import (
    estimate_semantic_quality,
    detect_message_punch,
    detect_thought_completion,
    emotion_based_silence_minlen,
    compute_quality_scores,
)

# worker helpers (v2 async pipeline)
from worker import contracts as worker_contracts
import json

# YouTube cookie manager for professional download handling
from youtube_cookie_manager import get_cookie_manager, log_cookie_status

# RunPod controller for on-demand GPU pod management
try:
    from runpod_controller import start_pod, stop_pod, wait_until_ready
    RUNPOD_AVAILABLE = True
except ImportError:
    RUNPOD_AVAILABLE = False

# RunPod GPU integration functions
def send_transcription_request(youtube_url: str) -> List[Dict]:
    """Send YouTube URL to RunPod GPU for download, audio extraction, and transcription."""
    import requests

    endpoint = os.getenv("RUNPOD_ENDPOINT_ID")
    if not endpoint:
        raise RuntimeError("RUNPOD_ENDPOINT_ID not configured")

    url = f"https://api.runpod.ai/v2/{endpoint}/runsync"

    # Prepare request with YouTube URL
    data = {
        'task': 'transcribe_youtube',
        'youtube_url': youtube_url,
        'model': os.environ.get("HS_TRANSCRIPT_MODEL", "small")
    }

    headers = {
        'Authorization': f"Bearer {os.environ.get('RUNPOD_API_KEY')}",
        'Content-Type': 'application/json'
    }

    log.info("[RUNPOD] Sending transcription request with YouTube URL to GPU endpoint...")
    response = requests.post(url, json=data, headers=headers, timeout=600)  # Increased timeout for download

    if response.status_code != 200:
        raise RuntimeError(f"RunPod transcription failed: {response.status_code} - {response.text}")

    result = response.json()
    if result.get('status') != 'COMPLETED':
        raise RuntimeError(f"RunPod transcription incomplete: {result.get('status')}")

    # Extract transcript segments from response
    output = result.get('output', {})
    segments = output.get('segments', [])

    log.info("[RUNPOD] Transcription completed: %d segments", len(segments))
    return segments

def send_analysis_request(transcript: List[Dict], video_path: str) -> Dict:
    """Send transcript and video metadata to RunPod GPU for analysis."""
    import requests

    endpoint = os.getenv("RUNPOD_ENDPOINT_ID")
    if not endpoint:
        raise RuntimeError("RUNPOD_ENDPOINT_ID not configured")

    url = f"https://api.runpod.ai/v2/{endpoint}/runsync"

    # Prepare request data
    data = {
        'task': 'analyze',
        'transcript': transcript,
        'video_metadata': {
            'duration': get_video_duration(video_path),
            'path': video_path
        }
    }

    headers = {
        'Authorization': f"Bearer {os.environ.get('RUNPOD_API_KEY')}",
        'Content-Type': 'application/json'
    }

    log.info("[RUNPOD] Sending analysis request to GPU endpoint...")
    response = requests.post(url, json=data, headers=headers, timeout=300)

    if response.status_code != 200:
        raise RuntimeError(f"RunPod analysis failed: {response.status_code} - {response.text}")

    result = response.json()
    if result.get('status') != 'COMPLETED':
        raise RuntimeError(f"RunPod analysis incomplete: {result.get('status')}")

    log.info("[RUNPOD] Analysis completed")
    return result.get('output', {})

def get_video_duration(video_path: str) -> float:
    """Get video duration in seconds."""
    try:
        import subprocess
        result = subprocess.run([
            'ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', video_path
        ], capture_output=True, text=True)
        import json
        data = json.loads(result.stdout)
        return float(data['format']['duration'])
    except Exception:
        return 0.0

# Keep heavy editor stack lazy to avoid OOM during Render startup.
ClipEditor = None
ClipEditConfig = None


def _load_world_editor():
    global ClipEditor, ClipEditConfig
    if ClipEditor is None or ClipEditConfig is None:
        try:
            from effects.world_class_editor import ClipEditor as _ClipEditor, ClipEditConfig as _ClipEditConfig
            ClipEditor = _ClipEditor
            ClipEditConfig = _ClipEditConfig
        except Exception:
            ClipEditor = None
            ClipEditConfig = None
    return ClipEditor, ClipEditConfig

from flask import make_response
import browser_cookie3
from utils.clipper import cut_clip_segment

# heavy editor stack lazy-loaded so the web service can start with minimal RAM.
# the original top-level import pulled in torch/weights/ML pipelines and blew
# up a 512MB Render instance. delay the import until it’s actually needed.
ultron_core_editor = None

# =====================================================
# ⚡ OPTIMIZATION LAYER (Speed + Quality)
# =====================================================

# In-memory cache for semantic quality scores (avoid recomputation)
_semantic_cache = {}
_punch_log_once = set()
_punch_log_lock = threading.Lock()


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)) or default)
    except Exception:
        return float(default)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "1" if default else "0")
    return str(raw).strip().lower() in ("1", "true", "yes", "y", "on")


def validate_runtime_profile(logger):
    expected = {
        "HS_ORCH_PIPELINE_MODE": "staged",
        "HS_ORCH_STAGED_FAILOVER_TO_LEGACY": "0",
        "HS_APP_LEGACY_MOMENT_POLICY": "0",
        "HS_ORCH_BRAIN_ENABLED": "1",
        "HS_IDEA_MAX_NODE_SECONDS": "28",
        "HS_IDEA_COALESCE_TIME_TOL": "0.35",
        "HS_IDEA_COALESCE_SEM_THR": "0.45",
        "HS_SELECTOR_RELAX_CURIO_DELTA": "0.04",
        "HS_SELECTOR_RELAX_PUNCH_DELTA": "0.04",
        "HS_SELECTOR_RELAX_SEM_FLOOR": "0.50",
        "HS_DIVERSITY_MODE": "balanced",
    }
    mismatches = []
    for key, exp in expected.items():
        cur = str(os.environ.get(key, "") or "").strip()
        if cur != str(exp):
            mismatches.append((key, cur, str(exp)))
    if mismatches:
        logger.warning("[RUNTIME-PROFILE] mismatches=%d", len(mismatches))
        for key, cur, exp in mismatches:
            logger.warning("[RUNTIME-PROFILE] %s current=%r expected=%r", key, cur, exp)
    else:
        logger.info("[RUNTIME-PROFILE] profile=ok keys=%d", len(expected))

# Video download cache
_video_cache = {}

# Prevent duplicate /analyze runs from double-clicks or repeated client submits.
_analyze_locks = {}
_analyze_locks_guard = threading.Lock()
IS_RENDER_RUNTIME = (
    str(os.environ.get("RENDER", "")).strip().lower() in ("1", "true", "yes", "on")
    or bool(os.environ.get("RENDER_SERVICE_ID"))
)


def _pipeline_profile() -> str:
    raw = os.environ.get("HS_PIPELINE_PROFILE", "balanced_scientist")
    return str(raw or "balanced_scientist").strip().lower()


PIPELINE_PROFILE = _pipeline_profile()
BALANCED_SCIENTIST_PROFILE = PIPELINE_PROFILE == "balanced_scientist"

# default worker profile when /v2/analyze does not provide one
DEFAULT_WORKER_PROFILE = os.environ.get("HS_PROFILE_DEFAULT", "balanced").strip().lower()

def _acquire_analyze_lock_for_user(user_id):
    key = str(user_id)
    with _analyze_locks_guard:
        lock = _analyze_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _analyze_locks[key] = lock
    if lock.acquire(blocking=False):
        return lock
    return None

def _analyze_file_lock_path(user_id) -> str:
    return os.path.join(tempfile.gettempdir(), f"hs_analyze_user_{str(user_id)}.lock")

def _read_lock_pid(lock_path: str):
    try:
        with open(lock_path, "r", encoding="utf-8", errors="ignore") as f:
            head = f.read(128)
        m = re.search(r"pid=(\d+)", head or "")
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return None

def _pid_is_alive(pid: int) -> bool:
    try:
        if pid is None or int(pid) <= 0:
            return False
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we do not have permission to signal it.
        return True
    except Exception:
        return False

def _acquire_analyze_file_lock_for_user(user_id):
    """
    Cross-process lock to prevent duplicate analyze runs when multiple worker
    processes exist (e.g., debug reloader / multi-process serving).
    """
    lock_path = _analyze_file_lock_path(user_id)
    stale_after_s = int(os.environ.get("HS_ANALYZE_LOCK_STALE_SECONDS", "900") or 900)

    try:
        if os.path.exists(lock_path):
            # If lock owner pid is gone, recover immediately.
            lock_pid = _read_lock_pid(lock_path)
            if lock_pid is not None and not _pid_is_alive(lock_pid):
                try:
                    os.remove(lock_path)
                except Exception:
                    pass

            age_s = time.time() - os.path.getmtime(lock_path)
            if age_s > float(stale_after_s):
                try:
                    os.remove(lock_path)
                except Exception:
                    pass
    except Exception:
        pass

    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            os.write(fd, f"pid={os.getpid()} ts={time.time():.3f}\n".encode("utf-8", "ignore"))
        finally:
            os.close(fd)
        return lock_path
    except FileExistsError:
        return None
    except Exception:
        return None

def _release_analyze_file_lock(lock_path: str):
    try:
        if lock_path and os.path.exists(lock_path):
            os.remove(lock_path)
    except Exception:
        pass

def _generate_low_memory_moments(source_video_duration_s: float, top_k: int = 3):
    """
    Render-safe fallback candidate generator.
    Uses deterministic timeline windows and avoids heavy ML/transcription paths.
    """
    try:
        dur = float(source_video_duration_s or 0.0)
    except Exception:
        dur = 0.0
    if dur <= 3.0:
        return []

    k = max(1, min(6, int(top_k or 3)))
    # Keep clips short for fast ffmpeg copy and low memory.
    clip_len = 22.0 if dur > 120 else 16.0
    clip_len = max(10.0, min(30.0, clip_len))

    start_min = 0.0
    start_max = max(start_min, dur - clip_len - 0.5)
    if start_max <= start_min:
        starts = [0.0]
    elif k == 1:
        starts = [min(8.0, start_max)]
    else:
        step = (start_max - start_min) / float(k)
        starts = [start_min + (i * step) for i in range(k)]

    moments = []
    for i, s in enumerate(starts):
        e = min(dur, s + clip_len)
        moments.append({
            "start": round(float(max(0.0, s)), 2),
            "end": round(float(max(s + 2.0, e)), 2),
            "score": round(float(max(0.35, 0.62 - (i * 0.04))), 3),
            "emotion": round(float(max(0.35, 0.62 - (i * 0.04))), 3),
            "hook": round(float(max(0.35, 0.58 - (i * 0.03))), 3),
            "text": f"Auto-selected segment #{i + 1}",
        })
    return moments

def _generate_clip_ffmpeg_fast(video_path: str, start: float, end: float, output_path: str) -> bool:
    """
    ⚡ ULTRA-FAST: Use FFmpeg directly with stream copy (NO re-encoding)
    Copying streams = 10-100x faster than re-encoding
    Returns True on success
    """
    try:
        import subprocess
        cmd = [
            "ffmpeg",
            "-y",  # Overwrite output
            "-ss", str(start),
            "-to", str(end),
            "-i", video_path,
            "-c", "copy",  # ⚡ STREAM COPY - NO ENCODING
            "-avoid_negative_ts", "make_zero",
            output_path
        ]
        
        result = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30
        )
        
        return result.returncode == 0
    except Exception as e:
        print(f"[FFmpeg Error] {e}")
        return False

def _generate_clip_ffmpeg_safe(video_path: str, start: float, end: float, output_path: str):
    """
    Fast path: stream copy.
    Optional fallback: re-encode if stream copy fails (disabled by default for max speed).
    Returns: (ok: bool, elapsed_s: float, mode: str)
    """
    t0 = time.time()
    ok = _generate_clip_ffmpeg_fast(video_path, start, end, output_path)
    if ok:
        return True, (time.time() - t0), "copy"

    allow_fallback = os.environ.get("HS_CLIP_FALLBACK_REENCODE", "0").strip().lower() in ("1", "true", "yes", "on")
    if not allow_fallback:
        return False, (time.time() - t0), "copy_failed"

    try:
        reencode_preset = os.environ.get("HS_CLIP_REENCODE_PRESET", "ultrafast").strip() or "ultrafast"
        reencode_crf = int(os.environ.get("HS_CLIP_REENCODE_CRF", "23") or 23)
        import subprocess
        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            str(start),
            "-to",
            str(end),
            "-i",
            video_path,
            "-c:v",
            "libx264",
            "-preset",
            reencode_preset,
            "-crf",
            str(reencode_crf),
            "-c:a",
            "aac",
            output_path,
        ]
        rc = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=90,
        ).returncode
        return (rc == 0), (time.time() - t0), "reencode"
    except Exception:
        return False, (time.time() - t0), "reencode_failed"

# add_header moved below after app initialization to avoid referencing `app` before it's defined.

# =====================================================
# ⚡ PARALLEL PROCESSING HELPER
# =====================================================

def _process_moment_parallel(args):
    """
    DEPRECATED (route-layer intelligence path).
    Active only when HS_APP_LEGACY_MOMENT_POLICY=1.
     ⚡ FAST: Process a single moment in parallel
    Returns: (idx, final_moment, text, start_r, end_r, final_score, base_score, semantic_quality, duration)
    """
    idx, m, global_transcript, log = args
    
    try:
        text = (m.get("text") or "").strip()
        base_s = float(m.get("start", 0.0))
        base_e = float(m.get("end", base_s + 3.0))
        score = float(m.get("score", m.get("emotion", 0.5) or 0.5))

        # Get transcript for this moment
        transcript_to_check = global_transcript or m.get("transcript") or m.get("captions") or []
        # Hard thinking budget: restrict NLP scans to local timeline around this moment.
        think_window_before_s = _env_float("HS_THINK_WINDOW_BEFORE", 2.5)
        think_window_after_s = _env_float("HS_THINK_WINDOW_AFTER", 85.0)
        if transcript_to_check:
            local_start = max(0.0, base_s - think_window_before_s)
            local_end = base_s + think_window_after_s
            transcript_to_check = [
                seg for seg in transcript_to_check
                if float(seg.get("start", 0.0)) < local_end and float(seg.get("end", seg.get("start", 0.0))) > local_start
            ]

        # Estimate semantic quality (CACHED for speed)
        semantic_quality = estimate_semantic_quality(text, score)

        think_budget_on = _env_bool("HS_THINK_BUDGET", True)
        skip_score_below = _env_float("HS_THINK_SKIP_SCORE_BELOW", 0.48)
        skip_semantic_below = _env_float("HS_THINK_SKIP_SEMANTIC_BELOW", 0.50)
        low_signal = (score < skip_score_below and semantic_quality < skip_semantic_below)

        # 🎯 INTELLIGENT PUNCH DETECTION (budget-aware)
        has_message_punch = False
        if not (think_budget_on and low_signal):
            has_message_punch = detect_message_punch(base_s, base_s + 25.0, text, transcript_to_check, score)
        
        # Start with base emotion-driven duration
        ideal_len = 15.0 + (score * 20.0) + (semantic_quality * 10.0)
        end = base_s + ideal_len
        
        # Apply intelligent thought completion (budget-aware)
        thought_max_extend = _env_float("HS_THOUGHT_MAX_EXTEND", 12.0)
        if not (think_budget_on and low_signal):
            thought_end = detect_thought_completion(base_s, end, transcript_to_check, max_extend=thought_max_extend)
            if thought_end > end:
                end = thought_end
        
        # Question/List pattern detection
        text_lower = text.lower()
        if "?" in text:
            end = min(end + 8.0, base_s + 55.0)  # Allow slightly longer for Q&A
        elif any(phrase in text_lower for phrase in ["here are", "these are", "tips:", "steps:", "ways to"]):
            end = min(end + 10.0, base_s + 58.0)  # Slightly more for list-style content
        
        # 🎯 SMART BOUNDS: Adjust based on message punch and quality
        if has_message_punch:
            # If message punch detected, ensure we capture it (min 18s, max 60s for high-quality)
            TARGET_MIN = 18.0
            TARGET_MAX = 60.0 if semantic_quality > 0.6 else 55.0
            # Punch-lock: log once per unique candidate key to avoid repeated noisy triggers.
            k = f"{round(base_s, 2)}|{round(base_e, 2)}|{hash((text or '')[:96])}"
            with _punch_log_lock:
                if k not in _punch_log_once:
                    _punch_log_once.add(k)
                    if len(_punch_log_once) > 4096:
                        _punch_log_once.clear()
                    log.info("[PUNCH] Message punch detected! Allowing longer duration.")
        else:
            # Standard bounds for regular content
            TARGET_MIN = 16.0
            TARGET_MAX = 50.0

        # Base minimum depends on semantic quality: higher quality -> longer minimum
        if semantic_quality >= 0.75:
            base_min = 20.0
        elif semantic_quality >= 0.5:
            base_min = 16.0
        else:
            base_min = 12.0

        # Ensure we at least meet the smarter base minimum and respect punch preferences
        if has_message_punch:
            end = max(end, base_s + max(base_min, 18.0))
        else:
            end = max(end, base_s + base_min)

        # Additional boost for very high semantic quality
        if semantic_quality > 0.85:
            end = min(base_s + (end - base_s) * 1.15, base_s + TARGET_MAX)

        if end - base_s > TARGET_MAX:
            end = base_s + TARGET_MAX
        
        # Smooth preroll
        start_r = round(max(0.0, base_s - 0.5), 2)
        end_r = round(end, 2)
        final_duration = end_r - start_r
        
        silence_minlen = emotion_based_silence_minlen(score)
        
        final_moment = {
            "start": start_r,
            "end": end_r,
            "emotion": score,
            "hook": score,
            "confidence": semantic_quality,
            "text": text,
            "silence_min_len": silence_minlen,
            "lock_end": True
        }

        # 🔥 QUALITY MODE: score hook/open-loop/ending/duration, then compute final_score (ranking only)
        quality = compute_quality_scores(transcript_to_check, start_r, end_r) if transcript_to_check else {}
        final_score = float(quality.get("final_score", score))
        final_moment.update({
            "base_score": float(score),
            **quality,
        })

        return (idx, final_moment, text, start_r, end_r, final_score, float(score), semantic_quality, final_duration)
     
    except Exception as e:
        log.exception(f"[ANALYZE] Error processing moment {idx}: {e}")
        return None


def _polish_top_longform_moments(
    wav_path: str,
    moment_results: list,
    source_duration_s: float,
    logger=None,
) -> list:
    """
    DEPRECATED (route-layer post-curation path).
    Active only when HS_APP_LEGACY_MOMENT_POLICY=1.
    """
    if not wav_path or not moment_results:
        return moment_results

    enabled = os.environ.get("HS_POLISH_TOP_CLIPS", "1").strip().lower() in ("1", "true", "yes", "on")
    if not enabled:
        return moment_results

    apply_above_s = float(os.environ.get("HS_POLISH_ABOVE_SECONDS", "2400") or 2400.0)
    top_n = int(os.environ.get("HS_POLISH_TOP_N", "2") or 2)
    max_window_s = float(os.environ.get("HS_POLISH_MAX_WINDOW_SECONDS", "75") or 75.0)
    timeout_s = int(os.environ.get("HS_POLISH_TIMEOUT_SECONDS", "80") or 80)

    if source_duration_s < apply_above_s or top_n <= 0:
        return moment_results

    try:
        from viral_finder.gemini_transcript_engine import extract_transcript as _extract_transcript
    except Exception:
        return moment_results

    def _log_info(message: str):
        if logger is not None:
            try:
                logger.info(message)
                return
            except Exception:
                pass
        print(message)

    def _log_warn(message: str):
        if logger is not None:
            try:
                logger.warning(message)
                return
            except Exception:
                pass
        print(message)

    import subprocess
    import tempfile

    polished = []
    _log_info(f"[POLISH] longform polish enabled (duration={source_duration_s:.1f}s, top_n={top_n})")

    for pos, row in enumerate(moment_results):
        idx, final_moment, text, start_r, end_r, final_score, base_score, semantic_quality, duration = row
        if pos >= top_n:
            polished.append(row)
            continue

        clip_start = max(0.0, float(start_r or 0.0))
        clip_end = max(clip_start + 0.5, float(end_r or (clip_start + 0.5)))
        if (clip_end - clip_start) > max_window_s:
            clip_end = clip_start + max_window_s

        tmp_wav = os.path.join(tempfile.gettempdir(), f"hs_polish_{uuid.uuid4().hex}.wav")
        try:
            cmd = [
                "ffmpeg",
                "-y",
                "-nostdin",
                "-ss",
                str(clip_start),
                "-to",
                str(clip_end),
                "-i",
                wav_path,
                "-ac",
                "1",
                "-ar",
                "16000",
                "-acodec",
                "pcm_s16le",
                tmp_wav,
            ]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=timeout_s)

            refined_segments = _extract_transcript(
                tmp_wav,
                model_name=os.environ.get("HS_TRANSCRIPT_MODEL", "small"),
                prefer_gpu=True,
                force_recompute=True,
                prefer_trust=True,
            )
            refined_text = " ".join(
                (seg.get("text", "").strip() for seg in (refined_segments or []) if (seg.get("text") or "").strip())
            ).strip()
            if refined_text:
                if len(refined_text) > 220:
                    refined_text = refined_text[:217].rstrip() + "..."
                new_moment = dict(final_moment or {})
                new_moment["text"] = refined_text
                text = refined_text
                final_moment = new_moment
                _log_info(f"[POLISH] clip#{idx} text refined from trust pass ({clip_end - clip_start:.1f}s)")
        except Exception as e:
            _log_warn(f"[POLISH] clip#{idx} skipped: {e}")
        finally:
            try:
                if os.path.exists(tmp_wav):
                    os.remove(tmp_wav)
            except Exception:
                pass

        polished.append((idx, final_moment, text, start_r, end_r, final_score, base_score, semantic_quality, duration))

    return polished


def _map_orchestrator_moment_for_clipgen(moment: dict, idx: int, log) -> tuple | None:
    """
    Adapter boundary: map orchestrator-ranked moment contract to clip generation tuple.
    No scoring/policy logic here; pure shape translation + guardrails.
    """
    try:
        log.info("[ROUTE-CONTRACT] incoming idx=%d keys=%s", idx, list((moment or {}).keys()))
        m = dict(moment or {})
        start = m.get("start")
        end = m.get("end")

        if start is None or end is None:
            log.warning("[ROUTE-CONTRACT] idx=%d missing_start_or_end", idx)
            return None

        start = float(start)
        end = float(end)
        if end <= start:
            log.warning("[ROUTE-CONTRACT] skip idx=%d reason=invalid_range start=%.3f end=%.3f", idx, start, end)
            return None

        signals = m.get("signals") or {}
        validation = m.get("validation") or {}
        required_signal_families = ("psychology", "narrative", "semantic", "engagement")
        missing_families = [k for k in required_signal_families if k not in signals]
        if missing_families:
            log.warning("[ROUTE-CONTRACT] idx=%d missing_signal_families=%s", idx, ",".join(missing_families))

        accepted = bool(validation.get("accepted", True))
        if not accepted:
            log.info("[ROUTE-CONTRACT] skip idx=%d reason=validation_reject reasons=%s", idx, validation.get("reasons"))
            return None

        score = float(m.get("viral_score", m.get("score_enriched", m.get("score", 0.0))) or 0.0)
        semantic_quality = float(
            ((signals.get("semantic") or {}).get("semantic_quality"))
            if isinstance(signals.get("semantic"), dict)
            else m.get("confidence", score)
            or score
        )
        text = str(m.get("text", "") or "").strip()
        duration = max(0.01, end - start)
        original_duration = duration
        
        # COMPENSATORY FIX: Normalize durations to resolve orchestrator inconsistencies
        # Orchestrator provides inconsistent start/end based on payoff detection
        # When payoff_idx=None, duration varies wildly; when found, still inconsistent
        payoff_idx = m.get("payoff_idx")
        hook_idx = m.get("hook_idx")
        
        NORMAL_CLIP_DURATION = 40.0  # Standard clip length (seconds)
        MIN_CLIP_DURATION = 25.0     # Minimum viable clip
        MAX_CLIP_DURATION = 50.0     # Maximum before needing optimization
        MAX_EXTENSION_FOR_PAYOFF = 3.0  # Max additional seconds for payoff breathing room
        PAYOFF_BREATHING_THRESHOLD = 0.45  # Trigger breathing room extension
        
        duration_correction_reason = None
        
        if payoff_idx is None:
            # Payoff not detected - normalize to standard duration
            if duration < MIN_CLIP_DURATION or duration > MAX_CLIP_DURATION:
                duration = NORMAL_CLIP_DURATION
                end = start + duration
                duration_correction_reason = "payoff_not_found"
        elif duration < MIN_CLIP_DURATION:
            # Payoff found but clip too short (indicates payoff very close to hook)
            # Extend to minimum viable length
            if duration < 25.0:  # Very short clips need extension
                duration = MIN_CLIP_DURATION
                end = start + duration
                duration_correction_reason = "payoff_too_close"
        elif duration > MAX_CLIP_DURATION:
            # Clip too long - reduce to maximum
            duration = MAX_CLIP_DURATION
            end = start + duration
            duration_correction_reason = "exceeds_max_length"
        
        # 🎯 PAYOFF BREATHING ROOM: Allow strong payoffs to breathe
        # If payoff resolution is strong, extend the clip end by 2-3 seconds
        # This lets the final statement land fully without feeling cut off
        payoff_resolution_score = float(
            ((signals.get("narrative") or {}).get("payoff_resolution_score", 0.0))
            if isinstance(signals.get("narrative"), dict)
            else m.get("payoff_resolution_score", 0.0)
            or 0.0
        )
        payoff_breathing_applied = False
        if payoff_resolution_score > PAYOFF_BREATHING_THRESHOLD and payoff_idx is not None:
            # Extend clip end to give payoff breathing room
            extension = min(MAX_EXTENSION_FOR_PAYOFF, 2.5)  # 2.5s ideal extension
            proposed_end = end + extension
            
            # Clamp to max duration
            max_allowed_end = start + MAX_CLIP_DURATION
            final_end = min(proposed_end, max_allowed_end)
            
            if final_end > end:
                breathing_gain = final_end - end
                end = final_end
                duration = end - start
                duration_correction_reason = (duration_correction_reason or "standard") + "+payoff_breathing"
                payoff_breathing_applied = True
                log.info(
                    "[PAYOFF-BREATHING] idx=%d applied breathing_room=%.2fs "
                    "payoff_score=%.2f new_end=%.2f",
                    idx,
                    breathing_gain,
                    payoff_resolution_score,
                    end
                )
        
        if duration_correction_reason:
            log.info(
                "[DURATION-FIX] idx=%d clip_corrected reason=%s "
                "payoff_idx=%s hook_idx=%s original=%.1fs adjusted=%.1fs "
                "payoff_breathing=%s",
                idx,
                duration_correction_reason,
                payoff_idx,
                hook_idx,
                original_duration,
                duration,
                payoff_breathing_applied
            )

        final_moment = dict(m)
        final_moment["start"] = round(start, 2)
        final_moment["end"] = round(end, 2)
        final_moment["final_score"] = float(score)
        final_moment.setdefault("base_score", float(m.get("score", score) or score))
        final_moment.setdefault("confidence", float(semantic_quality))
        final_moment.setdefault("rank", int(idx + 1))
        final_moment.setdefault("is_best", idx == 0)
        final_moment.setdefault("is_recommended", idx < 3)
        final_moment["duration_corrected"] = duration_correction_reason is not None
        final_moment["original_duration"] = original_duration
        final_moment["payoff_breathing_applied"] = payoff_breathing_applied
        final_moment["payoff_resolution_score"] = payoff_resolution_score

        return (
            int(idx),
            final_moment,
            text,
            round(start, 2),
            round(end, 2),
            float(score),
            float(final_moment.get("base_score", score) or score),
            float(semantic_quality),
            float(duration),
        )
    except Exception as e:
        log.warning("[ROUTE-CONTRACT] skip idx=%d reason=exception err=%s", idx, e)
        return None

# =====================================================
# 🌟 APP CONFIGURATION
# =====================================================
app = Flask(__name__)
app.config.from_object('settings.Config')
app.secret_key = app.config["SECRET_KEY"]
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)
validate_runtime_profile(logging.getLogger(__name__))

external_base_url = (app.config.get("EXTERNAL_BASE_URL") or "").strip().rstrip("/")
if external_base_url:
    parsed_external_url = urlparse(external_base_url)
    if parsed_external_url.scheme in ("http", "https") and parsed_external_url.netloc:
        app.config["EXTERNAL_BASE_URL"] = external_base_url
        app.config["SERVER_NAME"] = parsed_external_url.netloc
        app.config["PREFERRED_URL_SCHEME"] = parsed_external_url.scheme
    else:
        app.logger.warning(
            "[OAUTH-DEBUG] Ignoring invalid EXTERNAL_BASE_URL=%r. Expected format: http(s)://host[:port]",
            external_base_url,
        )
        app.config["EXTERNAL_BASE_URL"] = ""

if app.config.get("PREFERRED_URL_SCHEME") == "https":
    os.environ.pop("OAUTHLIB_INSECURE_TRANSPORT", None)
else:
    # Local HTTP OAuth only; production should run over HTTPS.
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

# ==========================
# 🌐 GOOGLE OAUTH SETUP

# Logger for use throughout the app (used by the analyze route)
log = app.logger
_start_resource_monitor_thread()

# Initialize YouTube cookie manager and log status
log_cookie_status()

@app.after_request
def add_header(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    if RESOURCE_LOG_ENABLED and RESOURCE_LOG_REQUESTS and _should_log_request_resource(request.path):
        try:
            start_t = getattr(g, "_res_req_t0", None)
            start = getattr(g, "_res_req_snapshot", None)
            if start_t is not None and isinstance(start, dict):
                end = _snapshot_resources(include_children=RESOURCE_INCLUDE_CHILDREN)
                elapsed_s = max(0.0, float(time.perf_counter() - start_t))
                rss_delta_mb = _bytes_to_mb(int(end.get("rss", 0)) - int(start.get("rss", 0)))
                child_rss_delta_mb = _bytes_to_mb(int(end.get("child_rss", 0)) - int(start.get("child_rss", 0)))
                cpu_delta_s = float(end.get("cpu_s", 0.0)) - float(start.get("cpu_s", 0.0))
                child_cpu_delta_s = float(end.get("child_cpu_s", 0.0)) - float(start.get("child_cpu_s", 0.0))
                log.info(
                    "[RES][REQ] %s %s status=%s wall=%.2fs rss=%.1f->%.1fMB (d=%.1fMB) "
                    "child_rss=%.1f->%.1fMB (d=%.1fMB) cpu_d=%.2fs child_cpu_d=%.2fs",
                    request.method,
                    request.path,
                    response.status_code,
                    elapsed_s,
                    _bytes_to_mb(start.get("rss", 0)),
                    _bytes_to_mb(end.get("rss", 0)),
                    rss_delta_mb,
                    _bytes_to_mb(start.get("child_rss", 0)),
                    _bytes_to_mb(end.get("child_rss", 0)),
                    child_rss_delta_mb,
                    cpu_delta_s,
                    child_cpu_delta_s,
                )
        except Exception:
            pass
    return response

def _resolve_oauth_config(base_var_name):
    direct_value = (os.getenv(base_var_name, app.config.get(base_var_name, "")) or "").strip()
    if direct_value:
        return direct_value, base_var_name

    prefer_prod = app.config.get("PREFERRED_URL_SCHEME") == "https"
    suffixes = ("_PROD", "_LOCAL") if prefer_prod else ("_LOCAL", "_PROD")
    for suffix in suffixes:
        env_name = f"{base_var_name}{suffix}"
        scoped_value = (os.getenv(env_name) or "").strip()
        if scoped_value:
            return scoped_value, env_name

    return "", base_var_name


client_id, client_id_source = _resolve_oauth_config("GOOGLE_OAUTH_CLIENT_ID")
client_secret, client_secret_source = _resolve_oauth_config("GOOGLE_OAUTH_CLIENT_SECRET")
app.config["GOOGLE_OAUTH_CLIENT_ID"] = client_id
app.config["GOOGLE_OAUTH_CLIENT_SECRET"] = client_secret
app.logger.info(
    "[OAUTH-DEBUG] ENV CLIENT_ID=%r",
    os.getenv("GOOGLE_OAUTH_CLIENT_ID"),
)
app.logger.info(
    "[OAUTH-DEBUG] ENV CLIENT_SECRET_SET=%s LEN=%d",
    bool(os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")),
    len(os.getenv("GOOGLE_OAUTH_CLIENT_SECRET") or ""),
)
app.logger.info(
    "[OAUTH-DEBUG] CFG CLIENT_ID=%r",
    app.config.get("GOOGLE_OAUTH_CLIENT_ID"),
)
app.logger.info(
    "[OAUTH-DEBUG] CFG CLIENT_SECRET_SET=%s LEN=%d",
    bool(app.config.get("GOOGLE_OAUTH_CLIENT_SECRET")),
    len(app.config.get("GOOGLE_OAUTH_CLIENT_SECRET") or ""),
)
app.logger.info("[OAUTH-DEBUG] CLIENT_ID_SOURCE=%s", client_id_source)
app.logger.info("[OAUTH-DEBUG] CLIENT_SECRET_SOURCE=%s", client_secret_source)
app.logger.info(
    "[OAUTH-DEBUG] EXTERNAL_BASE_URL=%r",
    app.config.get("EXTERNAL_BASE_URL"),
)
if app.config.get("EXTERNAL_BASE_URL"):
    app.logger.info(
        "[OAUTH-DEBUG] FORCED_CALLBACK_URI=%s/login/google/authorized",
        app.config.get("EXTERNAL_BASE_URL"),
    )
else:
    app.logger.info(
        "[OAUTH-DEBUG] DEFAULT_LOCAL_CALLBACK_URI=http://127.0.0.1:%s/login/google/authorized",
        os.getenv("PORT", "10000"),
    )

from flask_dance.contrib.google import make_google_blueprint, google

with app.app_context():
    google_bp = make_google_blueprint(
        client_id=app.config["GOOGLE_OAUTH_CLIENT_ID"],
        client_secret=app.config["GOOGLE_OAUTH_CLIENT_SECRET"],
        scope=[
            "openid",
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/userinfo.profile"
        ],
        redirect_to="google_login"
    )
    app.register_blueprint(google_bp, url_prefix="/login")

# ==========================
# ⚙️ DATABASE + LOGIN
# ==========================
db.init_app(app)
with app.app_context():
    # TEMPORARY: drop and recreate tables to apply profile_pic type change
    # WARNING: this wipes all existing data!
    db.drop_all()
    db.create_all()

migrate = Migrate(app, db)
login_manager = LoginManager()
login_manager.login_view = "auth.login"  # ensure redirects go to the auth blueprint's login endpoint
login_manager.login_message = "Please log in to analyze videos."

login_manager.init_app(app)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ✅ Register blueprints AFTER all routes are defined inside them
app.register_blueprint(auth, url_prefix="/auth")

# compatibility alias: templates and redirects still point at /login.
@app.route("/login")
def login_alias():
    # preserve any query args such as next
    return redirect(url_for("auth.login", **request.args))

from routes.feedback import feedback_bp
app.register_blueprint(feedback_bp, url_prefix="/api")
from routes.admin import admin_bp
app.register_blueprint(admin_bp, url_prefix="/admin")

def init_app():
    """Initialize app state that requires an application context.

    This is called on import so Gunicorn/WSGI workers have DB tables ready
    without relying on `if __name__ == "__main__"`.
    """

    with app.app_context():
        # Ensure required database tables exist (safe to call repeatedly).
        db.create_all()


# Ensure initialization runs for Gunicorn/WSGI imports.
init_app()

# Optional warmup: disabled by default in constrained environments (e.g. Render free tier).
if os.environ.get("HS_WARMUP_ON_STARTUP", "0").strip().lower() in ("1", "true", "yes", "on"):
    try:
        from viral_finder.gemini_transcript_engine import warmup as _warmup_transcriber
        _warmup_transcriber(model_name="small", prefer_gpu=True)
    except Exception as e:
        print(f"[WARMUP] Model pre-load optional, will load on first request: {e}")

# In-memory job queues and threads for async processing
job_queues = {}
job_threads = {}

# Output directory for generated clips
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

def schedule_cleanup(paths, delay=300):
    """Remove temporary files after `delay` seconds."""
    def _cleanup():
        time.sleep(delay)
        for p in paths:
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass
    t = threading.Thread(target=_cleanup, daemon=True)
    t.start()

# ==========================
# 🌟 MAIN ROUTES
# ==========================
@app.route("/")
def home():
    return render_template("index.html")
@app.route('/prototype')
def ui_prototype():
    # sample clips for prototype
    sample_clips = [
        {
            "start": 2.48, "end": 15.14, "duration": 12.66,
            "label": "Development", "payoff_confidence": 0.75, "curiosity_peak": 0.365,
            "hook_text": "You were the youngest person to become a billionaire at 20, right?",
            "end_text": "No college has kind of started to lose its credibility.",
            "decision": "yes",
            "reason": "Curiosity rises quickly and resolves with a clear insight."
        },
        {
            "start": 26.0, "end": 40.2, "duration": 14.2,
            "label": "Setup", "payoff_confidence": 0.12, "curiosity_peak": 0.18,
            "hook_text": "Most people think saving money is hard.",
            "end_text": "Let's just jump into the platform",
            "decision": "no",
            "reason": "Strong setup, but no satisfying payoff detected."
        }
    ]
    return render_template('clip_prototype.html', clips=sample_clips)
@app.route('/subscription')
@login_required
def subscription():
    return render_template('subscription.html', current_user=current_user)

@app.route('/limit-reached')
@login_required
def limit_reached():
    return redirect(url_for("subscription"))

# ⚡ Analytics Endpoint (for frontend event tracking)
@app.route('/analytics', methods=['POST'])
def analytics():
    """
    Lightweight analytics endpoint for frontend event tracking.
    Accepts: { event: str, ...payload }
    Returns: { status: 'ok' }
    """
    try:
        data = request.get_json() or {}
        event = data.get('event', 'unknown')
        
        # Log the event (optional - can be extended for proper analytics tracking)
        log.info(f"[ANALYTICS] Event: {event} | Data: {data}")
        if event in {"download_click", "download_blocked", "download_success", "pricing_modal_view"}:
            qa_event(
                "frontend_" + str(event),
                user_id=getattr(current_user, "id", None) if getattr(current_user, "is_authenticated", False) else None,
                clip_id=data.get("clip_id"),
                quality=data.get("quality"),
                reason=data.get("reason"),
                trigger=data.get("trigger"),
                source=data.get("source"),
                job_id=data.get("job_id"),
            )
        
        # Return success
        return jsonify({'status': 'ok', 'event': event}), 200
    except Exception as e:
        log.warning(f"[ANALYTICS] Error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 200  # Return 200 to avoid frontend errors


@app.route("/api/free-status", methods=["GET"])
@login_required
def api_free_status():
    return jsonify(get_free_status(current_user))

import stripe
stripe.api_key = app.config['STRIPE_SECRET_KEY']

@app.route("/create-checkout-session/<plan>", methods=["GET"])
@login_required
def create_checkout_session(plan):
    price_lookup = {
        # Free trial is not a recurring plan; keep for legacy safety.
        "free": 0,
        # New premium structure (USD / month)
        "starter": 6,
        "pro": 14,
        "industry": 35,
    }

    # Map legacy plan slugs into the new structure without breaking Stripe.
    alias = {
        "creator": "pro",
        "studio": "industry",
    }

    plan_key = (plan or "").strip().lower()
    plan_key = alias.get(plan_key, plan_key)

    if plan_key not in price_lookup:
        return "Invalid plan", 400

    amount = price_lookup[plan_key]
    qa_event(
        "checkout_start",
        user_id=getattr(current_user, "id", None),
        plan=plan_key,
        amount_usd=amount,
    )

    if amount == 0:
        current_user.subscription_plan = "Free"
        current_user.subscription_status = "Active"
        # Free -> keep user in trial bucket.
        try:
            current_user.plan_type = "trial"
        except Exception:
            pass
        db.session.commit()
        return redirect(url_for("dashboard"))

    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        mode="subscription",
        # Attach metadata so webhooks can map subscriptions back to users.
        metadata={
            "user_id": str(getattr(current_user, "id", "")),
            "plan_type": plan_key,
        },
        subscription_data={
            "metadata": {
                "user_id": str(getattr(current_user, "id", "")),
                "plan_type": plan_key,
            }
        },
        line_items=[{
            "price_data": {
                "currency": "usd",
                "product_data": {"name": f"HotShort {plan_key.capitalize()} Plan"},
                "unit_amount": amount * 100,  # Stripe expects cents
                "recurring": {"interval": "month"},
            },
            "quantity": 1
        }],
        success_url=url_for("payment_success", plan=plan_key, _external=True),
        cancel_url=url_for("subscription", _external=True)
    )

    return redirect(session.url, code=303)


@app.route("/payment-success/<plan>")
@login_required
def payment_success(plan):
    normalized = (plan or "").strip().lower()
    # Keep legacy slugs working while normalizing plan_type.
    normalized = {"studio": "industry", "creator": "pro"}.get(normalized, normalized)

    current_user.subscription_plan = normalized.capitalize()
    current_user.subscription_status = "Active"
    if normalized in VALID_PLAN_TYPES:
        try:
            current_user.plan_type = normalized
        except Exception:
            pass
    db.session.commit()
    qa_event(
        "payment_success",
        user_id=getattr(current_user, "id", None),
        plan=normalized,
    )
    return render_template("success.html", plan=normalized.capitalize())

@app.route('/subscribe/<plan>')
@login_required
def subscribe(plan):
    normalized = (plan or "").strip().lower()
    normalized = {"studio": "industry", "creator": "pro"}.get(normalized, normalized)

    current_user.subscription_plan = normalized.capitalize()
    if normalized in VALID_PLAN_TYPES:
        try:
            current_user.plan_type = normalized
        except Exception:
            pass
    db.session.commit()
    return redirect(url_for('dashboard'))


@app.route("/stripe/webhook", methods=["POST"])
def stripe_webhook():
    """
    Stripe webhook: keeps plan_type in sync with real billing state.

    Server-side truth comes from Stripe events, not session state.
    """
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature", "")
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET") or ""

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=webhook_secret,
        )
    except stripe.error.SignatureVerificationError:
        log.warning("[STRIPE] Invalid webhook signature")
        return jsonify({"error": "invalid_signature"}), 400
    except Exception as e:
        log.warning("[STRIPE] Invalid webhook payload: %s", e)
        return jsonify({"error": "invalid_payload"}), 400

    def _find_user_from_metadata(obj) -> User | None:
        try:
            metadata = (obj.get("metadata") or {}) if isinstance(obj, dict) else {}
            user_id_raw = metadata.get("user_id")
            if not user_id_raw:
                return None
            return User.query.get(int(user_id_raw))
        except Exception:
            return None

    def _downgrade_to_trial(user: User, reason: str) -> None:
        if not user:
            return
        try:
            user.plan_type = "trial"
            user.subscription_plan = "Free"
            user.subscription_status = "Canceled"
            db.session.commit()
            log.info("[STRIPE] User %s downgraded to trial (%s)", user.id, reason)
        except Exception:
            db.session.rollback()
            log.exception("[STRIPE] Failed to downgrade user %s to trial", getattr(user, "id", None))

    etype = event.get("type")
    data_obj = event.get("data", {}).get("object", {}) or {}

    # Subscription-level lifecycle: cancellation / terminal failure / in-place upgrades.
    if etype in ("customer.subscription.deleted", "customer.subscription.updated"):
        subscription = data_obj
        status = str(subscription.get("status") or "").lower()
        user = _find_user_from_metadata(subscription)

        # Only downgrade on bad terminal states, not during normal plan changes.
        if status in ("canceled", "unpaid", "incomplete_expired"):
            _downgrade_to_trial(user, reason=f"subscription_status={status}")
        # For active subscriptions, trust metadata["plan_type"] to keep plan_type in sync
        # when users upgrade/downgrade within paid tiers (Starter ↔ Pro ↔ Industry).
        elif status == "active" and user is not None:
            try:
                metadata = (subscription.get("metadata") or {}) if isinstance(subscription, dict) else {}
                new_plan = str(metadata.get("plan_type") or "").strip().lower()
                if new_plan in VALID_PLAN_TYPES and new_plan != "trial":
                    user.plan_type = new_plan
                    user.subscription_plan = new_plan.capitalize()
                    user.subscription_status = "Active"
                    db.session.commit()
                    log.info("[STRIPE] User %s plan_type updated via webhook -> %s", user.id, new_plan)
            except Exception:
                db.session.rollback()
                log.exception("[STRIPE] Failed to sync active subscription plan_type for user %s", getattr(user, "id", None))

    # Invoice failures can also signal billing issues; be conservative and
    # downgrade only when the linked subscription is in a bad state.
    elif etype == "invoice.payment_failed":
        invoice = data_obj
        sub_id = invoice.get("subscription")
        user = None
        # Prefer metadata on subscription if available.
        if sub_id:
            try:
                sub = stripe.Subscription.retrieve(sub_id)
                status = str(sub.get("status") or "").lower()
                if status in ("canceled", "unpaid", "incomplete_expired"):
                    user = _find_user_from_metadata(sub)
                    _downgrade_to_trial(user, reason=f"invoice_failed status={status}")
            except Exception:
                log.exception("[STRIPE] Failed to inspect subscription for invoice.payment_failed")

    # Successful invoices keep subscription_status fresh but do not change plan_type.
    elif etype == "invoice.payment_succeeded":
        invoice = data_obj
        sub_id = invoice.get("subscription")
        try:
            sub = stripe.Subscription.retrieve(sub_id) if sub_id else None
        except Exception:
            sub = None
        user = _find_user_from_metadata(sub or invoice)
        if user:
            try:
                user.subscription_status = "Active"
                db.session.commit()
            except Exception:
                db.session.rollback()
                log.exception("[STRIPE] Failed to mark user %s subscription_status=Active", user.id)

    return jsonify({"received": True}), 200
@app.route('/dashboard')
@login_required
def dashboard():
    from flask import make_response
    
    # Dashboard shows upload form (no clips)
    # Results moved to /results/<job_id> (see route below)
    
    response = make_response(render_template('dashboard.html'))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


# ============================================
# 🎬 RESULTS PAGE (Elite Build - New Route)
# ============================================
@app.route('/results/<job_id>')
@login_required
def results(job_id):
    """
    Display analysis results in beautiful carousel format.
    
    This is served AFTER /analyze completes and creates a Job record.
    Uses results_new.html with confidence-first UI.
    """
    try:
        # 1. Fetch the Job record
        job = Job.query.filter_by(id=job_id, user_id=current_user.id).first()
        if not job:
            return render_template(
                'results_new.html',
                clips_json=[],
                free_status_json=get_free_status(current_user),
                pro_checkout_url=url_for("create_checkout_session", plan="pro"),
                job_id=job_id,
                error='Job not found'
            )
        
        # 2. Fetch all clips for this job (from Clip table or Job.analysis_data)
        try:
            if job.analysis_data:
                # Parse JSON analysis data
                import json as jsonmodule
                raw = jsonmodule.loads(job.analysis_data)
                # worker v2 envelope has top-level keys and a "clips" list
                if isinstance(raw, dict) and "clips" in raw:
                    # preserve envelope fields for template if needed
                    analysis_results = raw.get("clips", []) or []
                    # stash extra info for later (status/confidence)
                    job._worker_envelope = raw
                elif isinstance(raw, list):
                    analysis_results = raw
                else:
                    # unknown shape, fallback to empty
                    analysis_results = []
            else:
                analysis_results = []
        except:
            analysis_results = []

        # If job.analysis_data is empty, try to load Clip rows linked to this job
        if not analysis_results:
            try:
                clip_rows = Clip.query.filter_by(job_id=job_id).all()
                if clip_rows:
                    analysis_results = []
                    for r in clip_rows:
                        analysis_results.append({
                            "clip_id": r.id,
                            "title": r.title,
                            "clip_url": "/" + (r.file_path or ""),
                            "start": r.start or 0,
                            "end": r.end or 0,
                            "score": r.score or 0
                        })
            except Exception:
                pass

        if not analysis_results:
            return render_template(
                'results_new.html',
                clips_json=[],
                free_status_json=get_free_status(current_user),
                pro_checkout_url=url_for("create_checkout_session", plan="pro"),
                job_id=job_id,
                error='No clips found'
            )
        
        # 3. Transform simple clip structure into ViralClip schema
        try:
            import json as jsonmodule
            from utils.clip_schema import SelectionReason, ScoreBreakdown, PlatformVariants, ViralClip
            
            # Preserve server ranking if present - sort by composite quality score
            try:
                def calculate_clip_score_result(c):
                    """Composite score for ranking - higher is better"""
                    final_score = float(c.get("final_score", 0.0) or 0.0)
                    virality_confidence = float(c.get("virality_confidence", 0.0) or 0.0)
                    hook_score = float(c.get("hook_score", 0.0) or 0.0)
                    arc_score = float(c.get("arc_score", 0.0) or 0.0)
                    duration_score = float(c.get("duration_score", 0.0) or 0.0)
                    editor_score = float(c.get("editor_score", 0.0) or 0.0)
                    open_loop_score = float(c.get("open_loop_score", 0.0) or 0.0)
                    
                    return (
                        0.25 * final_score +
                        0.20 * virality_confidence +
                        0.15 * hook_score +
                        0.15 * arc_score +
                        0.10 * duration_score +
                        0.10 * editor_score +
                        0.05 * open_loop_score
                    )
                
                analysis_results = sorted(analysis_results, key=calculate_clip_score_result, reverse=True)
                
                # Re-rank clips after sorting
                for new_idx, clip in enumerate(analysis_results, 1):
                    clip["rank"] = new_idx
                    clip["is_best"] = (new_idx == 1)
                    clip["is_recommended"] = (new_idx <= 3)
            except Exception:
                pass

            def infer_hook_type(hook_score, open_loop_score, pattern_break_score, payoff_resolution_score, ending_strength):
                signal_map = [
                    ("Contradiction", pattern_break_score),
                    ("Curiosity Gap", open_loop_score),
                    ("Payoff", payoff_resolution_score),
                    ("Strong Hook", hook_score),
                    ("Clean Ending", ending_strength),
                ]
                best_label, best_value = max(signal_map, key=lambda item: float(item[1] or 0.0))
                if float(best_value or 0.0) < 0.45:
                    return "Pattern Break"
                return best_label

            def build_reasoning(hook_score, open_loop_score, pattern_break_score, ending_strength, payoff_resolution_score, rewatch_score, information_density_score, duration_score, virality_confidence):
                strongest = max(
                    ("hook", hook_score),
                    ("open_loop", open_loop_score),
                    ("pattern_break", pattern_break_score),
                    ("ending", ending_strength),
                    ("payoff", payoff_resolution_score),
                    key=lambda item: float(item[1] or 0.0),
                )[0]

                if strongest == "pattern_break":
                    primary = "Pattern interrupt lands in the opening seconds"
                elif strongest == "open_loop":
                    primary = "Curiosity gap holds attention through the middle"
                elif strongest == "payoff":
                    primary = "Setup-to-payoff arc resolves cleanly"
                elif strongest == "ending":
                    primary = "Ending lands clearly to boost completion"
                else:
                    primary = "Strong early hook with stable retention pressure"

                secondary = (
                    f"Hook {hook_score:.2f} | Loop {open_loop_score:.2f} | Pattern {pattern_break_score:.2f} | "
                    f"Payoff {payoff_resolution_score:.2f} | End {ending_strength:.2f} | Dur {duration_score:.2f}"
                )

                risk = None
                if float(virality_confidence or 0.0) < 0.45:
                    risk = "Transcript signal is sparse; review this clip manually before publishing."

                why = []
                if hook_score >= 0.60:
                    why.append("Opens with an immediate attention hook")
                if open_loop_score >= 0.60:
                    why.append("Curiosity is sustained before the payoff")
                if pattern_break_score >= 0.60:
                    why.append("Pattern-break phrasing interrupts passive scrolling")
                if payoff_resolution_score >= 0.60:
                    why.append("The narrative resolves before the clip ends")
                if rewatch_score >= 0.58:
                    why.append("Replay potential is high due to dense phrasing")
                if information_density_score >= 0.58:
                    why.append("Information density supports saves and shares")
                if ending_strength >= 0.60:
                    why.append("Closing line gives a clean takeaway")
                if not why:
                    why = [
                        "Balanced hook and retention profile",
                        "Clear narrative movement from setup to close",
                        "Duration stays in a short-form friendly range",
                    ]

                return SelectionReason(primary=primary, secondary=secondary, risk=risk), why[:4]

            def explain_clip(moment: dict) -> dict:
                m = dict(moment or {})
                hook_seg = m.get("hook_segment") if isinstance(m.get("hook_segment"), dict) else {}
                payoff_seg = m.get("payoff_segment") if isinstance(m.get("payoff_segment"), dict) else {}
                hook = str(hook_seg.get("text", "") or "").strip()
                payoff = str(payoff_seg.get("text", "") or "").strip()
                arc_complete = bool(m.get("arc_complete", False))
                signals = m.get("signals") if isinstance(m.get("signals"), dict) else {}
                narrative = signals.get("narrative", {}) if isinstance(signals.get("narrative"), dict) else {}
                engagement = signals.get("engagement", {}) if isinstance(signals.get("engagement"), dict) else {}
                energy = float(engagement.get("energy", engagement.get("classic", 0.0)) or 0.0)

                explanation = {}
                if hook:
                    explanation["hook"] = hook
                if payoff:
                    explanation["payoff"] = payoff
                if arc_complete:
                    explanation["structure"] = "Complete narrative arc detected"
                else:
                    explanation["structure"] = "Partial arc; clip selected for strongest local payoff"
                explanation["retention"] = (
                    "Strong vocal energy increases viewer retention"
                    if energy > 0.2
                    else "Calm pacing suitable for explanatory clips"
                )
                explanation["build"] = str(m.get("build_text", "") or "").strip()
                return explanation

            transformed_clips = []
            for idx, simple_clip in enumerate(analysis_results):
                signals = simple_clip.get("signals") if isinstance(simple_clip.get("signals"), dict) else {}
                narrative_sig = signals.get("narrative", {}) if isinstance(signals.get("narrative"), dict) else {}
                engagement_sig = signals.get("engagement", {}) if isinstance(signals.get("engagement"), dict) else {}
                semantic_sig = signals.get("semantic", {}) if isinstance(signals.get("semantic"), dict) else {}
                psychology_sig = signals.get("psychology", {}) if isinstance(signals.get("psychology"), dict) else {}

                base_score = float(simple_clip.get("base_score", simple_clip.get("score", 0.5)) or 0.0)
                final_score = float(simple_clip.get("final_score", simple_clip.get("score", 0.5)) or 0.0)
                hook_score = float(simple_clip.get("hook_score", narrative_sig.get("hook_score", final_score)) or 0.0)
                open_loop_score = float(simple_clip.get("open_loop_score", narrative_sig.get("open_loop_score", 0.0)) or 0.0)
                pattern_break_score = float(simple_clip.get("pattern_break_score", hook_score) or 0.0)
                ending_strength = float(simple_clip.get("ending_strength", narrative_sig.get("ending_strength", final_score)) or 0.0)
                payoff_resolution_score = float(simple_clip.get("payoff_resolution_score", narrative_sig.get("payoff_resolution_score", open_loop_score)) or 0.0)
                rewatch_score = float(simple_clip.get("rewatch_score", narrative_sig.get("rewatch_score", final_score)) or 0.0)
                information_density_score = float(simple_clip.get("information_density_score", narrative_sig.get("information_density_score", final_score)) or 0.0)
                virality_confidence = float(simple_clip.get("virality_confidence", narrative_sig.get("virality_confidence", 1.0)) or 0.0)
                duration_score = float(simple_clip.get("duration_score", final_score) or 0.0)
                retention_score = float(engagement_sig.get("energy", engagement_sig.get("classic", max(open_loop_score, payoff_resolution_score))) or 0.0)
                clarity_score = float(semantic_sig.get("semantic_quality", max(ending_strength, information_density_score)) or 0.0)
                emotion_score = float(psychology_sig.get("tension_gradient", base_score) or 0.0)
                hook_type = simple_clip.get("hook_type") or infer_hook_type(
                    hook_score,
                    open_loop_score,
                    pattern_break_score,
                    payoff_resolution_score,
                    ending_strength,
                )
                selection_reason, why_bullets = build_reasoning(
                    hook_score,
                    open_loop_score,
                    pattern_break_score,
                    ending_strength,
                    payoff_resolution_score,
                    rewatch_score,
                    information_density_score,
                    duration_score,
                    virality_confidence,
                )
                explanation = explain_clip(simple_clip)
                story_panel = {
                    "hook": explanation.get("hook", ""),
                    "build": explanation.get("build", ""),
                    "payoff": explanation.get("payoff", ""),
                }
                if explanation.get("hook"):
                    why_bullets = [f"HOOK: {explanation.get('hook')}"] + why_bullets
                if explanation.get("payoff"):
                    why_bullets = why_bullets + [f"PAYOFF: {explanation.get('payoff')}"]
                if explanation.get("structure"):
                    why_bullets = why_bullets + [f"STRUCTURE: {explanation.get('structure')}"]
                if explanation.get("retention"):
                    why_bullets = why_bullets + [f"RETENTION: {explanation.get('retention')}"]

                rank = int(simple_clip.get("rank", idx + 1) or (idx + 1))
                is_best = bool(simple_clip.get("is_best", rank == 1))
                is_recommended = bool(simple_clip.get("is_recommended", rank <= 3))
                confidence_pct = int(max(0.0, min(100.0, (final_score * (0.9 + (0.1 * virality_confidence)) * 100.0))))
                
                # 🔥 ARC QUALITY INDICATOR - Shows breakdwn of Hook/Payoff/Ending
                arc_quality_pct = int(max(0.0, min(100.0,
                    ((hook_score * 0.25) + (payoff_resolution_score * 0.35) + (ending_strength * 0.20) + (duration_score * 0.20)) * 100.0
                )))
                
                # 🔥 VIRAL POTENTIAL - Replace percentage with emoji + intensity
                viral_potential_emoji = "🔥" if confidence_pct >= 80 else "⚡" if confidence_pct >= 60 else "✨"
                viral_potential_label = f"{viral_potential_emoji} {confidence_pct}%"

                # Create proper ViralClip object from simple data
                clip = ViralClip(
                    clip_id=simple_clip.get("clip_id") or simple_clip.get("job_id") or f"clip_{idx}",
                    title=simple_clip.get("title", f"Viral Clip #{idx}"),
                    clip_url=simple_clip.get("clip_url", ""),
                    platform_variants={
                        "youtube_shorts": simple_clip.get("clip_url", ""),
                        "instagram_reels": simple_clip.get("clip_url", ""),
                        "tiktok": simple_clip.get("clip_url", ""),
                    },
                    hook_type=hook_type,
                    confidence=confidence_pct,
                    scores=ScoreBreakdown(
                        hook=hook_score,
                        retention=retention_score,
                        clarity=clarity_score,
                        emotion=emotion_score,
                    ),
                    selection_reason=selection_reason,
                    why=why_bullets[:6],
                    rank=rank,
                    is_best=is_best,
                    is_recommended=is_recommended,
                    transcript=job.transcript or "",
                    start_time=simple_clip.get("start", 0),
                    end_time=simple_clip.get("end", 15),
                    duration=simple_clip.get("end", 15) - simple_clip.get("start", 0),
                )
                clip.pattern_break_score = pattern_break_score
                clip.payoff_resolution_score = payoff_resolution_score
                clip.rewatch_score = rewatch_score
                clip.information_density_score = information_density_score
                clip.virality_confidence = virality_confidence
                clip.explanation = explanation
                clip.story_panel = story_panel
                clip.story_patterns = list(simple_clip.get("story_patterns", []) or [])
                # 🔥 ADD ARC QUALITY INDICATORS
                clip.arc_quality_pct = arc_quality_pct
                clip.viral_potential_label = viral_potential_label
                clip.viral_potential_emoji = viral_potential_emoji
                transformed_clips.append(clip)
            
            # Serialize to JSON for frontend
            def clip_to_dict(clip):
                """Convert ViralClip to dict for JSON serialization"""
                return {
                    "clip_id": clip.clip_id,
                    "title": clip.title,
                    "clip_url": clip.clip_url,
                    "platform_variants": clip.platform_variants,
                    "hook_type": clip.hook_type,
                    "confidence": clip.confidence,
                    "scores": {
                        "hook": clip.scores.hook,
                        "retention": clip.scores.retention,
                        "clarity": clip.scores.clarity,
                        "emotion": clip.scores.emotion,
                    },
                    "pattern_break_score": getattr(clip, "pattern_break_score", 0.0),
                    "payoff_resolution_score": getattr(clip, "payoff_resolution_score", 0.0),
                    "rewatch_score": getattr(clip, "rewatch_score", 0.0),
                    "information_density_score": getattr(clip, "information_density_score", 0.0),
                    "virality_confidence": getattr(clip, "virality_confidence", 0.0),
                    "selection_reason": {
                        "primary": clip.selection_reason.primary,
                        "secondary": clip.selection_reason.secondary,
                        "risk": clip.selection_reason.risk,
                    },
                    "why": clip.why,
                    "explanation": getattr(clip, "explanation", {}),
                    "story_structure": getattr(clip, "story_panel", {}),
                    "story_patterns": getattr(clip, "story_patterns", []),
                    "rank": clip.rank,
                    "is_best": clip.is_best,
                    "is_recommended": getattr(clip, "is_recommended", False),
                    "transcript": clip.transcript,
                    "start_time": clip.start_time,
                    "end_time": clip.end_time,
                    "duration": clip.duration,
                    # 🔥 ARC QUALITY INDICATORS - NEW FIELDS
                    "arc_quality_pct": getattr(clip, "arc_quality_pct", 0),
                    "arc_quality_breakdown": {
                        "hook": int(getattr(clip, "pattern_break_score", 0.0) * 25),
                        "payoff": int(getattr(clip, "payoff_resolution_score", 0.0) * 35),
                        "ending": int(getattr(clip, "scores", {}).clarity * 20) if hasattr(clip, "scores") else 0,
                        "duration": int(getattr(clip, "duration", 0) / 40 * 20) if getattr(clip, "duration", 0) <= 40 else 20,
                    },
                    # 🔥 VIRAL POTENTIAL INDICATOR - NEW FIELDS\n                    "viral_potential_emoji": getattr(clip, "viral_potential_emoji", "✨"),
                    "viral_potential_label": getattr(clip, "viral_potential_label", f"✨ {clip.confidence}%"),
                }
            
            clips_json = [clip_to_dict(c) for c in transformed_clips]
        except Exception as e:
            log.error(f"[RESULTS] Error building clips: {e}")
            import traceback
            log.error(traceback.format_exc())
            clips_json = []
        
        # 4. Render results template with data
        extra_ctx = {}
        if hasattr(job, '_worker_envelope'):
            extra_ctx['worker_envelope'] = job._worker_envelope
        response = make_response(render_template(
            'results_new.html',
            clips_json=clips_json,
            free_status_json=get_free_status(current_user),
            pro_checkout_url=url_for("create_checkout_session", plan="pro"),
            job_id=job_id,
            status=job.status,
            **extra_ctx
        ))
        response.headers['Cache-Control'] = 'private, max-age=3600'
        return response
    
    except Exception as e:
        log.error(f"[RESULTS] Error loading results: {e}")
        import traceback
        log.error(traceback.format_exc())
        return render_template(
            'results_new.html',
            clips_json=[],
            free_status_json=get_free_status(current_user),
            pro_checkout_url=url_for("create_checkout_session", plan="pro"),
            job_id=job_id,
            error='Error loading results'
        )


# ------------------------------------------------------------------
# 👉 v2 worker API (async job submission & polling)
# ------------------------------------------------------------------

@app.route('/v2/analyze', methods=['POST'])
@login_required
def v2_analyze():
    """JSON API endpoint used by Render to enqueue a worker job.

    Request schema is validated by ``worker.contracts`` and persisted in
    ``Job.analysis_data`` so the worker can read it later.  The job is
    initially created with ``status='pending'`` which the worker will pick up.
    """
    data = request.get_json(force=True, silent=True) or {}
    try:
        params = worker_contracts.validate_worker_request(data)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    job_id = params.get("job_id")
    if Job.query.filter_by(id=job_id).first():
        return jsonify({"ok": False, "error": "job_exists"}), 409

    job = Job(
        id=job_id,
        user_id=current_user.id,
        video_path=None,
        transcript=None,
        analysis_data=json.dumps(params),
        status="pending",
    )
    db.session.add(job)
    db.session.commit()

    return jsonify({"ok": True, "job_id": job_id}), 200


@app.route('/v2/result/<job_id>')
@login_required
def v2_result(job_id):
    """Return job status and, when available, the worker result envelope."""
    job = Job.query.filter_by(id=job_id, user_id=current_user.id).first()
    if not job:
        return jsonify({"ok": False, "error": "not_found"}), 404
    resp = {"ok": True, "status": job.status}
    if job.analysis_data:
        try:
            resp["result"] = json.loads(job.analysis_data)
        except Exception:
            resp["result"] = job.analysis_data
    return jsonify(resp)


@app.route('/checkout')
@login_required
def checkout():
    """
    Checkout page - user selected a plan and is ready to pay
    
    Query params:
    - plan: pro, creator
    - job_id: (optional) which job to download
    """
    plan = request.args.get('plan', 'pro')
    job_id = request.args.get('job_id')

    if plan == "starter":
        plan = "pro"
    if plan == "studio":
        plan = "creator"

    # Validate plan
    valid_plans = ['creator', 'pro']
    if plan not in valid_plans:
        plan = 'pro'
    
    # Map plan names to pricing info
    plans_info = {
        'creator': {
            'name': '🏢 Creator',
            'price': 49,
            'period': 'monthly',
            'description': 'For Teams & High-Output Creators',
            'inr_equivalent': None,
        },
        'pro': {
            'name': '⚡ Pro',
            'price': 6,
            'period': 'monthly',
            'description': '$6/month — Built for serious creators',
            'inr_equivalent': None,
        }
    }

    selected_plan = plans_info.get(plan, plans_info['pro'])
    
    # TODO: Integrate Stripe here
    # For now, this is the checkout page skeleton
    
    return render_template('checkout.html', 
                         plan=plan,
                         plan_info=selected_plan,
                         job_id=job_id)


@app.route('/google_login')
def google_login():
    def _restart_google_oauth():
        # Clear stale oauth token so Flask-Dance starts a clean auth flow.
        try:
            session.pop("google_oauth_token", None)
        except Exception:
            pass
        try:
            google.token = None
        except Exception:
            pass
        return redirect(url_for("google.login"))

    if not google.authorized:
        return _restart_google_oauth()

    # Fetch user info from Google API; recover gracefully on token expiry.
    try:
        resp = google.get("/oauth2/v2/userinfo")
    except Exception as e:
        err_name = e.__class__.__name__
        if err_name in ("TokenExpiredError", "MissingTokenError", "InvalidGrantError"):
            flash("Session expired. Please sign in again.", "info")
            return _restart_google_oauth()
        raise

    if not getattr(resp, "ok", False):
        flash("Google session invalid. Please sign in again.", "info")
        return _restart_google_oauth()

    user_info = resp.json() or {}
    print("[GOOGLE USER INFO]", user_info)  # for debugging

    email = user_info.get("email")
    name = user_info.get("name", "Unknown User")
    picture = user_info.get("picture", None)

    if not email:
        flash("Google account missing email permission. Please sign in again.", "error")
        return _restart_google_oauth()

    # Check if user already exists
    user = User.query.filter_by(email=email).first()

    if not user:
        # Create a new Google user
        user = User(
            email=email,
            password="google_auth",  # No real password needed
            name=name,
            profile_pic=picture
        )
        db.session.add(user)
        db.session.commit()

    login_user(user)
    return redirect(url_for("dashboard"))

# ==========================
# 🚀 REST OF YOUR CLIP SYSTEM
# ==========================
# (everything below: /analyze, /generate, /start, /progress, etc.)
# keep as-is — they’re fine.

# =====================================================
# 🎥 AI VIRAL ENGINE ROUTES
# =====================================================
from flask_login import login_required, current_user

import os
import glob
from flask import session
# from viral_finder.viral_finder_engine_v30 import find_viral_moments
from flask import session
from flask import session
from flask import session, flash


from datetime import datetime, timedelta
import time
from datetime import datetime, timedelta
# at top of app.py
from flask import session, flash, request, render_template, redirect, url_for
from datetime import datetime, timedelta

    # 5) Session Cache
    # ---------------------------------
from flask import request, jsonify
from flask_login import login_required, current_user
import os, logging, random, math

log = logging.getLogger(__name__)


class YoutubeRateLimitError(Exception):
    """Raised when YouTube returns HTTP 429 / rate limiting from yt-dlp."""


class YoutubeCaptchaError(Exception):
    """Raised when YouTube refuses download with a bot/captcha challenge.

    This often surfaces as ``Sign in to confirm you're not a bot`` messages
    from yt-dlp.  We treat it separately so the user can be informed that
    cookies or a different link may be needed.
    """


def _qa_mode_enabled() -> bool:
    return str(os.getenv("HS_QA_MODE", "0")).strip().lower() in ("1", "true", "yes", "on")

def _open_testing_mode_enabled() -> bool:
    """
    Global switch to temporarily open trial/free limits during internal testing.
    """
    return str(os.getenv("HS_OPEN_TESTING_MODE", "1")).strip().lower() in ("1", "true", "yes", "on")

def qa_event(event_name: str, **payload) -> None:
    if not _qa_mode_enabled():
        return
    safe = {}
    for k, v in (payload or {}).items():
        try:
            if isinstance(v, (str, int, float, bool)) or v is None:
                safe[k] = v
            else:
                safe[k] = str(v)
        except Exception:
            safe[k] = "<unserializable>"
    try:
        log.info("[QA_EVENT] %s | %s", event_name, safe)
    except Exception:
        pass

# Helpers used inside analyze_video
from config.tiers import TIERS
from datetime import datetime, timedelta
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
import json
from viral_finder.ingestion_guard import (
    CanonicalMediaObject,
    analyze_audio_integrity,
    analyze_transcript_integrity,
    canonical_to_dict,
    compute_vad_removed_ratio,
    ingestion_cache_key,
    load_ingestion_cache,
    probe_media,
    save_ingestion_cache,
    score_acquisition,
)

FREE_CLIP_LIMIT = 3

VALID_PLAN_TYPES = {"trial", "starter", "pro", "industry"}

PLAN_LIMITS = {
    "trial": {
        "max_duration_seconds": 600,
        "watermark": True,
        "priority": "standard",
        "hd_enabled": False,
        "bulk_enabled": False,
        "advanced_ai": False,
    },
    "starter": {
        "max_duration_seconds": 1200,
        "watermark": True,
        "priority": "standard",
        "hd_enabled": False,
        "bulk_enabled": False,
        "advanced_ai": False,
    },
    "pro": {
        "max_duration_seconds": 1800,
        "watermark": False,
        "priority": "fast",
        "hd_enabled": True,
        "bulk_enabled": False,
        "advanced_ai": True,
    },
    "industry": {
        "max_duration_seconds": 3600,
        "watermark": False,
        "priority": "fastest",
        "hd_enabled": True,
        "bulk_enabled": True,
        "advanced_ai": True,
    },
}


def get_user_plan_type(user) -> str:
    """
    Resolve the effective HOTSHORT plan for a user.
    Prefers the new `plan_type` field, falls back to legacy `subscription_plan`.
    """
    raw = (getattr(user, "plan_type", None) or "").strip().lower()
    if raw in VALID_PLAN_TYPES:
        return raw

    legacy = (getattr(user, "subscription_plan", None) or "").strip().lower()
    if legacy in ("pro", "creator"):
        return "pro"
    if legacy in ("starter",):
        return "starter"
    if legacy in ("studio",):
        return "industry"

    # All other legacy / unspecified users are treated as in free trial.
    return "trial"


def get_plan_limits(plan_type: str) -> dict:
    """
    HOTSHORT pricing limits for a given plan_type.

    Returns a copy of the limits dict with keys:
      - max_duration_seconds
      - watermark
      - priority
      - hd_enabled
      - bulk_enabled
      - advanced_ai
    """
    key = (plan_type or "trial").strip().lower()
    base = PLAN_LIMITS.get(key, PLAN_LIMITS["trial"])
    if key == "trial" and _open_testing_mode_enabled():
        # Testing mode: unlock trial constraints without changing stored plan_type.
        unlocked = dict(base)
        unlocked["max_duration_seconds"] = 0
        unlocked["watermark"] = False
        unlocked["priority"] = "fastest"
        unlocked["hd_enabled"] = True
        unlocked["bulk_enabled"] = True
        unlocked["advanced_ai"] = True
        return unlocked
    # Return a shallow copy so callers can modify safely.
    return dict(base)


def tier_key(user) -> str:
    p = (getattr(user, "subscription_plan", None) or "free").strip().lower()
    if p == "starter":
        return "free"
    if p == "studio":
        return "creator"
    if p in ("free", "pro", "creator"):
        return p
    return "free"

def is_paid(user) -> bool:
    # Treat any non-trial HOTSHORT plan as paid for feature gating.
    plan_type = get_user_plan_type(user)
    return plan_type in ("starter", "pro", "industry")

def _ensure_free_claim_table() -> None:
    try:
        FreeClipClaim.__table__.create(db.engine, checkfirst=True)
    except Exception:
        pass

def get_free_status(user) -> dict:
    """
    Lightweight status object for frontend to reason about trial usage.

    Under the new pricing model:
      - Only `plan_type == "trial"` is limited.
      - Starter/Pro/Industry are treated as fully paid for this API.
    """
    plan_type = get_user_plan_type(user)
    if plan_type == "trial" and _open_testing_mode_enabled():
        return {
            "is_paid": True,
            "free_clips_used": 0,
            "free_downloads_used": 0,
            "free_clips_left": FREE_CLIP_LIMIT,
            "claimed_clip_ids": [],
            "plan_type": plan_type,
        }

    if plan_type != "trial":
        return {
            "is_paid": True,
            "free_clips_used": 0,
            "free_downloads_used": 0,
            "free_clips_left": FREE_CLIP_LIMIT,
            "claimed_clip_ids": [],
            "plan_type": plan_type,
        }

    try:
        used = int(getattr(user, "trial_clip_exports", 0) or 0)
    except Exception:
        used = 0
    left = max(0, FREE_CLIP_LIMIT - used)
    return {
        "is_paid": False,
        "free_clips_used": used,
        "free_downloads_used": used,
        "free_clips_left": left,
        "claimed_clip_ids": [],
        "plan_type": plan_type,
    }

@app.route("/analyze", methods=["POST"])
@login_required
def analyze_video():
    """
    ENTERPRISE SAAS PATTERN
    - JSON for AJAX/fetch clients
    - Redirect + flash for plain form submits
    """
    def wants_json_response() -> bool:
        accept = (request.headers.get("Accept") or "").lower()
        if "application/json" in accept:
            return True
        xrw = (request.headers.get("X-Requested-With") or "").lower()
        if xrw == "xmlhttprequest":
            return True
        # fetch()/XHR calls often send this shape even when Accept is generic.
        sfm = (request.headers.get("Sec-Fetch-Mode") or "").lower()
        sfd = (request.headers.get("Sec-Fetch-Dest") or "").lower()
        if sfm in ("cors", "same-origin") and sfd == "empty":
            return True
        return False

    def analyze_error(message: str, status_code: int = 400):
        if wants_json_response():
            return jsonify({"ok": False, "error": message}), status_code
        flash(message, "error")
        return redirect(url_for("dashboard"))

    def analyze_success(job_id_value: str, clips_count: int):
        redirect_url = url_for("results", job_id=job_id_value)
        if wants_json_response():
            return jsonify({
                "ok": True,
                "job_id": job_id_value,
                "clips_count": clips_count,
                "redirect": redirect_url
            }), 200
        return redirect(redirect_url)

    # Resolve current plan + limits once for this request.
    plan_type = get_user_plan_type(current_user)
    plan_limits = get_plan_limits(plan_type)

    # Enforce trial analyze quota before doing any heavy work.
    if plan_type == "trial" and not _open_testing_mode_enabled():
        try:
            used = int(getattr(current_user, "trial_analyze_count", 0) or 0)
        except Exception:
            used = 0
        if used >= 1:
            if wants_json_response():
                return jsonify(
                    {
                        "ok": False,
                        "action": "show_pricing_modal",
                    }
                ), 200
            flash("Your free trial analyze has been used. Upgrade to continue.", "error")
            return redirect("/pricing")

    # If the worker mode is enabled we don't perform heavy analysis here;
    # instead enqueue a job and return immediately.  This keeps the web process
    # light and lets the worker pick it up.
    if os.environ.get("HS_WORKER_MODE"):
        # build request payload from form fields
        job_id_val = str(uuid.uuid4())
        req = {
            "job_id": job_id_val,
            "source_url": request.form.get("youtube_url", "").strip(),
            "profile": request.form.get("profile", DEFAULT_WORKER_PROFILE),
            "min_clips": request.form.get("min_clips", 3),
            "max_duration_sec": request.form.get("max_duration_sec"),
            "debug": request.form.get("debug", "").lower() in ("1", "true", "yes"),
        }
        try:
            params = worker_contracts.validate_worker_request(req)
        except Exception as e:
            return analyze_error(f"Worker request invalid: {e}", 400)
        # create pending job row
        job = Job(
            id=params["job_id"],
            user_id=current_user.id,
            video_path=None,
            transcript=None,
            analysis_data=json.dumps(params),
            status="pending",
        )
        db.session.add(job)
        db.session.commit()
        # respond with job id; clips_count unknown yet
        return analyze_success(job.id, 0)

    # One active analyze per user at a time (prevents duplicate jobs/log spam).
    user_id_for_lock = getattr(current_user, "id", None)
    user_analyze_lock = _acquire_analyze_lock_for_user(user_id_for_lock)
    file_analyze_lock = _acquire_analyze_file_lock_for_user(user_id_for_lock)
    if user_analyze_lock is None or file_analyze_lock is None:
        if user_analyze_lock is not None:
            try:
                user_analyze_lock.release()
            except Exception:
                pass
        if file_analyze_lock:
            _release_analyze_file_lock(file_analyze_lock)
        return analyze_error("Analysis already running. Please wait for current job to finish.", 429)

    @after_this_request
    def _release_user_analyze_lock(response):
        try:
            user_analyze_lock.release()
        except Exception:
            pass
        _release_analyze_file_lock(file_analyze_lock)
        return response

    # --------------------------------------------------
    # Helpers
    # --------------------------------------------------
    def db_has_column(table_name, column_name):
        try:
            inspector = inspect(db.engine)
            cols = [c["name"] for c in inspector.get_columns(table_name)]
            return column_name in cols
        except Exception:
            return False

    def check_media_invariants(video_path):
        """Enforce media integrity before transcription."""
        if not video_path or not os.path.exists(video_path):
            return False, "missing file"
        if os.path.exists(video_path + ".part"):
            return False, "part file present"
        size1 = os.path.getsize(video_path)
        time.sleep(0.2)
        size2 = os.path.getsize(video_path)
        if size1 != size2:
            return False, "size not stable"
        try:
            import subprocess

            # Prefer stream existence over duration (duration can fail on edge cases).
            audio_probe = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    "a:0",
                    "-show_entries",
                    "stream=codec_type",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    video_path,
                ],
                capture_output=True,
                text=True,
            )
            if audio_probe.returncode == 0 and (audio_probe.stdout or "").strip():
                return True, "ok"

            # Fallback: duration probe for diagnostic clarity
            dur_probe = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    video_path,
                ],
                capture_output=True,
                text=True,
            )
            if dur_probe.returncode == 0:
                try:
                    dur = float((dur_probe.stdout or "").strip() or 0.0)
                    if dur > 0:
                        return True, "ok"
                except Exception:
                    pass

            err = (audio_probe.stderr or "").strip() or (dur_probe.stderr or "").strip() or "ffprobe error"
            return False, f"ffprobe failed: {err[:180]}"
        except Exception:
            return False, "ffprobe failed"
        return True, "ok"

    def extract_wav(video_path):
        """Blocking audio extraction to 16k mono PCM wav."""
        wav_path = os.path.splitext(video_path)[0] + ".wav"
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            video_path,
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-acodec",
            "pcm_s16le",
            wav_path,
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return wav_path

    def probe_media_duration(video_path):
        """Best-effort duration probe in seconds."""
        try:
            import subprocess
            out = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    video_path,
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            return float((out.stdout or "").strip() or 0.0)
        except Exception:
            return 0.0

    # --------------------------------------------------
    # 0) Validate input
    # --------------------------------------------------
    # legacy form-based analyze route remains unchanged; it still does full
    # in-process extraction.  New async jobs use /v2/analyze below.
    youtube_url = request.form.get("youtube_url", "").strip()
    if not youtube_url:
        return analyze_error("Please paste a valid YouTube URL.", 400)

    ingest_cache_dir = os.environ.get("HS_INGESTION_CACHE_DIR", ".hotshort_ingestion_cache").strip() or ".hotshort_ingestion_cache"
    ingest_cache_key_value = ingestion_cache_key(youtube_url)
    ingest_signature = _ingestion_signature()
    ingest_cache = load_ingestion_cache(
        ingest_cache_dir,
        ingest_cache_key_value,
        max_age_s=float(os.environ.get("HS_INGESTION_CACHE_MAX_AGE_S", "86400") or 86400.0),
    )
    ingest_cache_valid = bool(
        isinstance(ingest_cache, dict)
        and str(ingest_cache.get("signature") or "") == str(ingest_signature)
    )
    if ingest_cache and (not ingest_cache_valid):
        log.info("[INGEST] cache invalidated source=%s reason=signature_mismatch", ingest_cache_key_value[:12])
        ingest_cache = None

    analyze_t0 = time.time()
    log.info("[ANALYZE] Starting: %s", youtube_url)
    log_mem("start")

    # Generate job_id early so downloads never collide across concurrent requests
    job_id = str(uuid.uuid4())

    # --------------------------------------------------
    # 1) Metadata prefetch + full-download-first ingest
    # --------------------------------------------------
    # Fetch lightweight metadata so we can show a preview and make decisions
    metadata = {}
    cached_metadata = dict((ingest_cache or {}).get("metadata") or {}) if isinstance(ingest_cache, dict) else {}
    refresh_metadata = _env_bool("HS_INGEST_REFRESH_METADATA", True)
    fresh_metadata = {}
    if refresh_metadata:
        try:
            fresh_metadata = fetch_youtube_metadata(youtube_url) or {}
            log.info("[ANALYZE] metadata fetched: %s", fresh_metadata)
        except Exception as e:
            log.warning("[ANALYZE] metadata fetch failed: %s", e)
            fresh_metadata = {}
    if cached_metadata and fresh_metadata:
        cached_id = str(cached_metadata.get("video_id") or "").strip()
        fresh_id = str(fresh_metadata.get("video_id") or "").strip()
        try:
            cached_d = float(cached_metadata.get("duration") or 0.0)
            fresh_d = float(fresh_metadata.get("duration") or 0.0)
        except Exception:
            cached_d = 0.0
            fresh_d = 0.0
        if (cached_id and fresh_id and cached_id != fresh_id) or (cached_d > 0 and fresh_d > 0 and abs(cached_d - fresh_d) > 3.0):
            log.info(
                "[INGEST] cache invalidated source=%s reason=metadata_drift cached(id=%s,dur=%.2f) fresh(id=%s,dur=%.2f)",
                ingest_cache_key_value[:12],
                cached_id,
                cached_d,
                fresh_id,
                fresh_d,
            )
            ingest_cache = None
            cached_metadata = {}
    if fresh_metadata:
        metadata = fresh_metadata
    elif cached_metadata:
        metadata = cached_metadata
        log.info("[INGEST] metadata cache hit source=%s", ingest_cache_key_value[:12])

    # Transcript is intentionally derived from local media only, after full
    # acquisition + audio extraction.
    transcript_segments = []

    # --------------------------------------------------
    # 2) Download full media first (deterministic ingest)
    # --------------------------------------------------
    stage_t0 = time.time()
    video_path = None
    media_probe = {}
    acquisition_attempts = []
    acquisition_quality_score = 0.0
    js_runtime_ok = True
    try:
        js_runtime_ok = _js_runtime_available()
        video_path = download_youtube_video(
            youtube_url,
            output_dir="downloads",
            job_id=job_id,
        )
        if video_path and os.path.exists(video_path):
            media_probe = probe_media(video_path)
            size_b = int(os.path.getsize(video_path) if os.path.exists(video_path) else 0)
            metadata_duration = float((metadata or {}).get("duration") or 0.0)
            expected_duration = metadata_duration if metadata_duration > 0.0 else float(
                media_probe.get("duration") or 0.0
            )
            acquisition_quality_score, components = score_acquisition(
                media_probe=media_probe,
                expected_duration=expected_duration,
                metadata_duration=metadata_duration,
                file_size_bytes=size_b,
            )
            if not js_runtime_ok:
                acquisition_quality_score *= 0.70
                components["js_runtime_penalty"] = 0.30
            acquisition_attempts = [
                {
                    "path_name": "full_default",
                    "format": str(os.environ.get("HS_YTDLP_FORMAT", "") or "default"),
                    "ok": True,
                    "path": video_path,
                    "probe": media_probe,
                    "size_bytes": size_b,
                    "score": round(float(acquisition_quality_score), 4),
                    "components": components,
                }
            ]
        else:
            acquisition_attempts = [
                {
                    "path_name": "full_default",
                    "format": str(os.environ.get("HS_YTDLP_FORMAT", "") or "default"),
                    "ok": False,
                    "error": "media_missing",
                }
            ]
        log_mem("after download")
    except YoutubeRateLimitError as e:
        log.warning("[ANALYZE] Download rate-limited by YouTube: %s", e)
        return analyze_error(
            "YouTube temporarily limited downloads from this server. Please retry in 1–2 minutes.",
            429,
        )
    except YoutubeCaptchaError as e:
        log.warning("[ANALYZE] Download blocked by YouTube captcha/bot check: %s", e)
        return analyze_error(
            "YouTube requires sign-in or cookies to fetch this video. Try using a different link or provide cookies.",
            400,
        )
    except Exception as e:
        log.warning("[ANALYZE] Download error: %s", e)
    log.info("[TIMING] stage=download wall=%.2fs", (time.time() - stage_t0))

    # Phase 1 suppression disable: do not gate cognition by acquisition score.
    # Keep telemetry/logging, but force threshold to zero.
    min_acq_score = 0.0
    if (not video_path) or (not os.path.exists(video_path)):
        return analyze_error("Ingestion failed: media acquisition unavailable.", 400)
    if not js_runtime_ok:
        log.warning("[INGEST] JS runtime missing (node/deno). YouTube extraction quality may degrade.")
    log.info(
        "[INGEST] acquisition score=%.3f attempts=%d selected=%s",
        float(acquisition_quality_score or 0.0),
        len(acquisition_attempts or []),
        os.path.basename(video_path) if video_path else "none",
    )
    if float(acquisition_quality_score or 0.0) < float(min_acq_score):
        log.warning(
            "[INGEST] Acquisition quality below threshold score=%.3f min=%.3f attempts=%d",
            float(acquisition_quality_score or 0.0),
            float(min_acq_score),
            len(acquisition_attempts or []),
        )
        return analyze_error(
            "Ingestion quality too low. Source fetch was incomplete. Please retry (or enable JS runtime: node/deno).",
            422,
        )

    ok_media, reason = check_media_invariants(video_path)
    if not ok_media:
        # Phase 3: ingestion invariants are advisory, not hard gates.
        log.warning("[ANALYZE] Media invariant warning (continuing): %s", reason)

    # Prefer metadata duration for policy checks; fall back to media probe.
    if 'metadata' in locals() and metadata.get('duration'):
        source_video_duration_s = float(metadata.get('duration') or 0.0)
    else:
        source_video_duration_s = probe_media_duration(video_path)

    # Enforce max video duration per plan using the original duration
    try:
        max_duration_s = float(plan_limits.get("max_duration_seconds", 0) or 0)
    except Exception:
        max_duration_s = 0.0
    if max_duration_s > 0 and source_video_duration_s > max_duration_s:
        minutes = int(round(max_duration_s / 60.0)) or 1
        message = f"Your plan supports up to {minutes} minutes. Upgrade to increase limit."
        log.warning(
            "[ANALYZE] Video too long for plan=%s duration=%.2fs max=%.2fs url=%s",
            plan_type,
            source_video_duration_s,
            max_duration_s,
            youtube_url,
        )
        if wants_json_response():
            return jsonify(
                {
                    "ok": False,
                    "error": "DURATION_LIMIT",
                    "message": message,
                    "max_duration_seconds": max_duration_s,
                    "plan_type": plan_type,
                }
            ), 403
        flash(message, "error")
        return redirect(url_for("subscription"))

    fast_longform_enabled = os.environ.get("HS_FAST_LONGFORM_ENABLED", "1").strip().lower() in ("1", "true", "yes", "on")
    fast_longform_threshold_s = float(os.environ.get("HS_FAST_LONGFORM_SECONDS", "480") or 480.0)  # 8m
    is_fast_longform = fast_longform_enabled and source_video_duration_s >= fast_longform_threshold_s
    log.info(
        "[FAST-LANE] duration=%.2fs enabled=%s threshold=%.2fs active=%s profile=%s",
        source_video_duration_s,
        fast_longform_enabled,
        fast_longform_threshold_s,
        is_fast_longform,
        PIPELINE_PROFILE,
    )
    # Phase 1 suppression disable: always run full cognition path (no low-memory moments).
    low_memory_mode = False

    # Transcript is produced after local audio extraction.
    transcript_segments = transcript_segments or []
    wav_path = None
    audio_integrity = {
        "audio_integrity_score": 0.0,
        "silence_ratio": 1.0,
        "snr_estimate_db": 0.0,
        "clipping_ratio": 0.0,
        "spectral_flatness": 1.0,
    }
    transcript_integrity = {
        "transcript_integrity_score": 0.0,
        "segment_count": 0,
        "sentence_boundary_density": 0.0,
    }
    vad_removed_ratio = 1.0

    if low_memory_mode:
        # Render free tier fallback: skip heavy transcription/orchestration.
        low_mem_top_k = int(os.environ.get("HS_LOW_MEMORY_TOP_K", "3") or 3)
        moments = _generate_low_memory_moments(source_video_duration_s, top_k=low_mem_top_k)
        log.info(
            "[FAST-LANE] low-memory mode active top_k=%d duration=%.1fs moments=%d",
            low_mem_top_k,
            source_video_duration_s,
            len(moments or []),
        )
    else:
        stage_t0 = time.time()
        try:
            wav_path = extract_wav(video_path)
        except Exception as e:
            log.error("[AUDIO] Extraction failed: %s", e)
            return analyze_error("Audio extraction failed. Try again.", 500)
        log.info("[TIMING] stage=extract_wav wall=%.2fs", (time.time() - stage_t0))
        # Phase 3: integrity analysis is optional telemetry only.
        try:
            audio_integrity = analyze_audio_integrity(wav_path)
            log.info(
                "[INGEST] audio_integrity score=%.3f silence=%.3f snr=%.2fdB clip=%.4f flat=%.3f",
                float(audio_integrity.get("audio_integrity_score", 0.0) or 0.0),
                float(audio_integrity.get("silence_ratio", 0.0) or 0.0),
                float(audio_integrity.get("snr_estimate_db", 0.0) or 0.0),
                float(audio_integrity.get("clipping_ratio", 0.0) or 0.0),
                float(audio_integrity.get("spectral_flatness", 0.0) or 0.0),
            )
        except Exception as e:
            log.warning("[INGEST] audio integrity telemetry skipped: %s", e)

        # --------------------------------------------------
        # RunPod GPU Pod Lifecycle Management
        # --------------------------------------------------
        # Start GPU pod if RunPod is configured
        if RUNPOD_AVAILABLE and os.environ.get("RUNPOD_API_KEY") and os.environ.get("RUNPOD_POD_ID"):
            try:
                log.info("[RUNPOD] Starting GPU pod...")
                start_pod()
                if wait_until_ready(timeout=120):
                    log.info("[RUNPOD] Pod ready for GPU work")
                else:
                    log.warning("[RUNPOD] Pod did not become ready within timeout, continuing anyway...")
            except Exception as e:
                log.warning("[RUNPOD] Failed to start pod: %s", e)

        # Precompute transcript on clean wav and seed cache for orchestrator
        stage_t0 = time.time()
        try:
            # Use RunPod GPU for transcription if available
            runpod_endpoint = os.getenv("RUNPOD_ENDPOINT_ID")
            runpod_api_key = os.getenv("RUNPOD_API_KEY")

            if runpod_endpoint and runpod_api_key:
                log.info("[TRANSCRIPT] Using RunPod GPU for transcription")
                transcript_segments = send_transcription_request(youtube_url)
            else:
                log.info("[TRANSCRIPT] Using local CPU for transcription (RunPod not configured)")
                from viral_finder.gemini_transcript_engine import extract_transcript as _extract_transcript
                from viral_finder.orchestrator import _save_cached_transcript
                transcript_model_name = os.environ.get("HS_TRANSCRIPT_MODEL", "small")
                if is_fast_longform:
                    transcript_model_name = os.environ.get("HS_TRANSCRIPT_LONGFORM_MODEL", "tiny")
                use_vad_override = None
                vad_profile_override = None
                transcript_segments = _extract_transcript(
                    wav_path,
                    model_name=transcript_model_name,
                    prefer_gpu=True,
                    prefer_trust=False,
                    use_vad_override=use_vad_override,
                    vad_profile_override=vad_profile_override,
                )

            seg_dur = float(media_probe.get("duration") or probe_media_duration(video_path) or 0.0)
            # Phase 3: transcript integrity and VAD ratios are optional telemetry only.
            try:
                vad_removed_ratio = compute_vad_removed_ratio(seg_dur, transcript_segments or [])
                transcript_integrity = analyze_transcript_integrity(transcript_segments or [], expected_duration=seg_dur)
            except Exception as e:
                log.warning("[INGEST] transcript integrity telemetry skipped: %s", e)
            log_mem("after transcript")
            log.info(
                "[TRANSCRIPT] segments=%d integrity=%.3f vad_removed=%.3f",
                len(transcript_segments or []),
                float(transcript_integrity.get("transcript_integrity_score", 0.0) or 0.0),
                float(vad_removed_ratio),
            )

            # Save transcript cache for orchestrator
            from viral_finder.orchestrator import _save_cached_transcript
            _save_cached_transcript(video_path, transcript_segments or [])
        except Exception as e:
            log.error("[TRANSCRIPT] Prefill failed: %s", e)
            # Stop pod before returning error
            if RUNPOD_AVAILABLE and os.environ.get("RUNPOD_API_KEY") and os.environ.get("RUNPOD_POD_ID"):
                try:
                    log.info("[RUNPOD] Stopping GPU pod due to error...")
                    stop_pod()
                except Exception as pod_err:
                    log.warning("[RUNPOD] Failed to stop pod: %s", pod_err)
            return analyze_error("Transcription failed. Try another video.", 500)
        log.info("[TIMING] stage=transcript wall=%.2fs", (time.time() - stage_t0))

        # --------------------------------------------------
        # 2) Find viral moments
        # --------------------------------------------------
        stage_t0 = time.time()
        try:
            # Use RunPod GPU for analysis if available
            runpod_endpoint = os.getenv("RUNPOD_ENDPOINT_ID")
            runpod_api_key = os.getenv("RUNPOD_API_KEY")

            if runpod_endpoint and runpod_api_key:
                log.info("[ANALYSIS] Using RunPod GPU for viral moment detection")
                analysis_result = send_analysis_request(transcript_segments, video_path)
                moments = analysis_result.get('moments', [])
                log.info("[RUNPOD] Analysis found %d viral moments", len(moments))
            else:
                log.info("[ANALYSIS] Using local CPU for viral moment detection (RunPod not configured)")
                from viral_finder.orchestrator import orchestrate
                top_k_default = int(os.environ.get("HS_TOP_K_DEFAULT", "6") or 6)
                top_k_longform = int(os.environ.get("HS_TOP_K_LONGFORM", "9") or 9)
                min_longform_k = int(os.environ.get("HS_MIN_LONGFORM_TOP_K", "9") or 9)

                # Simple, strong targeting:
                # - 20m+ videos: ask for 12 candidates (stable 9-12 output goal)
                # - other longform: at least longform floor
                if source_video_duration_s >= 1200:
                    top_k = int(os.environ.get("HS_TOP_K_30MIN", "12") or 12)
                elif source_video_duration_s >= fast_longform_threshold_s:
                    # Safety floor: never under-generate for longform, even if env is stale/misconfigured.
                    top_k = max(top_k_longform, min_longform_k)
                else:
                    top_k = top_k_default

                top_k = max(3, min(20, int(top_k)))
                
                # ⚡ HARD-FORCE STAGED MODE: Ensure we use the new pipeline (L4/L7/L9) instead of legacy Ultron V33.
                # We explicitly disable fallback to prevent legacy Ultron from running silently.
                os.environ["HS_ORCH_PIPELINE_MODE"] = "staged"
                clips = orchestrate(video_path, top_k=top_k, allow_fallback=False, pipeline_mode="staged")
                print("DEBUG clips returned:", type(clips), len(clips) if clips else 0)
                moments = clips

            log.info(
                "[FAST-LANE] orchestrate top_k=%d duration=%.1fs cfg(default=%d,longform=%d,min_longform=%d) pipeline_mode=staged (FORCED) allow_fallback=False",
                top_k,
                source_video_duration_s,
                top_k_default,
                top_k_longform,
                min_longform_k,
            )
        except Exception as e:
            log.exception("[ANALYZE] Orchestrator failed: %s", e)
            # Stop pod before returning error
            if RUNPOD_AVAILABLE and os.environ.get("RUNPOD_API_KEY") and os.environ.get("RUNPOD_POD_ID"):
                try:
                    log.info("[RUNPOD] Stopping GPU pod due to error...")
                    stop_pod()
                except Exception as pod_err:
                    log.warning("[RUNPOD] Failed to stop pod: %s", pod_err)
            return analyze_error("Analysis failed. Please try another video.", 500)
        log.info("[TIMING] stage=orchestrate wall=%.2fs moments=%d", (time.time() - stage_t0), len(moments or []))

        # --------------------------------------------------
        # Stop GPU pod after GPU work is complete
        # --------------------------------------------------
        if RUNPOD_AVAILABLE and os.environ.get("RUNPOD_API_KEY") and os.environ.get("RUNPOD_POD_ID"):
            try:
                log.info("[RUNPOD] Stopping GPU pod after analysis complete...")
                stop_pod()
            except Exception as e:
                log.warning("[RUNPOD] Failed to stop pod: %s", e)

    transcript_status = "missing"
    if transcript_segments:
        t_score = float(transcript_integrity.get("transcript_integrity_score", 0.0) or 0.0)
        transcript_status = "ok" if t_score >= 0.72 else "partial"
    res_w = media_probe.get("width")
    res_h = media_probe.get("height")
    canonical_media_obj = CanonicalMediaObject(
        video_path=str(video_path or ""),
        audio_path=str(wav_path or ""),
        duration=float(media_probe.get("duration") or probe_media_duration(video_path) or 0.0),
        resolution=(int(res_w), int(res_h)) if (res_w and res_h) else None,
        bitrate=float(media_probe.get("bit_rate") or 0.0) if media_probe.get("bit_rate") else None,
        transcript_status=transcript_status,
        acquisition_quality_score=float(acquisition_quality_score or 0.0),
        audio_integrity_score=float(audio_integrity.get("audio_integrity_score", 0.0) or 0.0),
        transcript_integrity_score=float(transcript_integrity.get("transcript_integrity_score", 0.0) or 0.0),
        acquisition_attempts=list(acquisition_attempts or []),
    )
    save_ingestion_cache(
        ingest_cache_dir,
        ingest_cache_key_value,
        {
            "saved_at": time.time(),
            "signature": ingest_signature,
            "source_url_hash": ingest_cache_key_value,
            "metadata": metadata or {},
            "source_transcript_segments": transcript_segments or [],
            "transcript_engine": {
                "model": os.environ.get("HS_TRANSCRIPT_MODEL", "small"),
                "longform_model": os.environ.get("HS_TRANSCRIPT_LONGFORM_MODEL", "tiny"),
                "use_vad_override": use_vad_override if "use_vad_override" in locals() else None,
                "vad_profile_override": vad_profile_override if "vad_profile_override" in locals() else None,
            },
            "canonical_media": canonical_to_dict(canonical_media_obj),
            "audio_integrity": audio_integrity,
            "transcript_integrity": transcript_integrity,
            "vad_removed_ratio": float(vad_removed_ratio),
        },
    )

    if not moments:
        return analyze_error("No viral moments detected. Try another video.", 400)

    # --------------------------------------------------
    # 3) Prepare output dir
    # --------------------------------------------------
    outputs_dir = os.path.join(app.root_path, "static", "outputs")
    os.makedirs(outputs_dir, exist_ok=True)

    # --------------------------------------------------
    # 4) Create Job (processing)
    # --------------------------------------------------
    try:
        # persist ingestion context for frontend/debug tooling
        import json
        analysis_blob = {}
        if 'metadata' in locals():
            analysis_blob['metadata'] = metadata
        analysis_blob["ingestion"] = {
            "canonical_media": canonical_to_dict(canonical_media_obj),
            "audio_integrity": audio_integrity,
            "transcript_integrity": transcript_integrity,
            "vad_removed_ratio": float(vad_removed_ratio),
            "js_runtime_available": bool(js_runtime_ok),
        }

        job = Job(
            id=job_id,
            user_id=current_user.id,
            video_path=video_path,
            transcript="",
            analysis_data=json.dumps(analysis_blob),
            status="processing"
        )
        db.session.add(job)
        db.session.commit()
    except Exception as e:
        log.exception("[ANALYZE] Job creation failed: %s", e)
        db.session.rollback()
        return analyze_error("Failed to initialize analysis job.", 500)

    # --------------------------------------------------
    # 5) Route-level moment mapping only (orchestrator owns intelligence/ranking)
    # --------------------------------------------------
    log_mem("after moments")
    legacy_route_policy = _env_bool("HS_APP_LEGACY_MOMENT_POLICY", False)
    log.info(
        "[ROUTE] ranking_owner=orchestrator legacy_policy=%s input_moments=%d",
        legacy_route_policy,
        len(moments or []),
    )
    print("DEBUG moments sample:", (moments or [])[:1])
    if isinstance(moments, dict):
        moments = moments.get("candidates") or moments.get("moments") or []
    if not isinstance(moments, list):
        moments = []

    moment_results = []
    stage_t0 = time.time()

    if legacy_route_policy:
        log.warning("[ROUTE] using legacy route moment policy (deprecated)")
        global_transcript = transcript_segments or []
        if isinstance(moments, dict):
            global_transcript = moments.get("transcript") or global_transcript

        tasks = [(idx, m, global_transcript, log) for idx, m in enumerate(moments)]
        moment_workers_cfg = int(os.environ.get("HS_MOMENT_MAX_WORKERS", "0") or 0)
        if moment_workers_cfg > 0:
            moment_workers = max(1, min(16, moment_workers_cfg))
        else:
            memory_budget_mb = max(128.0, _env_float("HS_MEMORY_BUDGET_MB", 550.0))
            if IS_RENDER_RUNTIME or (BALANCED_SCIENTIST_PROFILE and memory_budget_mb <= 650.0):
                moment_workers = 1
            else:
                moment_workers = max(2, min(8, (os.cpu_count() or 4)))
        with ThreadPoolExecutor(max_workers=moment_workers) as pool:
            futures = [pool.submit(_process_moment_parallel, t) for t in tasks]
            for f in as_completed(futures):
                r = f.result()
                if r:
                    moment_results.append(r)
        log.info(
            "[TIMING] stage=moment_process_legacy wall=%.2fs workers=%d in=%d out=%d",
            (time.time() - stage_t0),
            moment_workers,
            len(tasks),
            len(moment_results),
        )
        # legacy polish retained only for rollback mode
        try:
            source_duration_s = max(
                float(seg.get("end", seg.get("start", 0.0)) or 0.0)
                for seg in (global_transcript or [])
                if isinstance(seg, dict)
            )
        except Exception:
            source_duration_s = 0.0
        moment_results = _polish_top_longform_moments(
            wav_path=wav_path,
            moment_results=moment_results,
            source_duration_s=source_duration_s,
            logger=log,
        )
    else:
        accepted_count = 0
        for idx, m in enumerate(moments or []):
            mapped = _map_orchestrator_moment_for_clipgen(m, idx, log)
            if mapped:
                moment_results.append(mapped)
                accepted_count += 1
        log.info(
            "[TIMING] stage=moment_process_route_adapter wall=%.2fs in=%d accepted=%d",
            (time.time() - stage_t0),
            len(moments or []),
            accepted_count,
        )
        print("DEBUG mapped results:", len(moment_results))
        # preserve orchestrator order as authoritative ranking
        normalized = []
        for new_idx, r in enumerate(moment_results):
            _, final_moment, text, start_r, end_r, final_score, base_score, semantic_quality, duration = r
            try:
                final_moment["rank"] = int(new_idx + 1)
                final_moment["is_best"] = (new_idx == 0)
                final_moment["is_recommended"] = (new_idx < 3)
            except Exception:
                pass
            normalized.append((new_idx, final_moment, text, start_r, end_r, final_score, base_score, semantic_quality, duration))
        moment_results = normalized

    # --------------------------------------------------
    # 6) Generate clips (parallel)
    # --------------------------------------------------
    generated_clips = []
    enable_world_editor = os.environ.get("HS_ENABLE_WORLDCLASS_EDITING", "0").strip().lower() in ("1", "true", "yes", "on")
    edit_max_duration_s = float(os.environ.get("HS_EDIT_MAX_DURATION_SECONDS", "600") or 600.0)  # 10m
    if source_video_duration_s >= edit_max_duration_s:
        enable_world_editor = False
        log.info(
            "[FAST-LANE] world editor disabled for longform (duration=%.2fs >= %.2fs)",
            source_video_duration_s,
            edit_max_duration_s,
        )
    world_editor = None
    world_editor_config = None
    editor_cls = None
    editor_cfg_cls = None
    if enable_world_editor:
        editor_cls, editor_cfg_cls = _load_world_editor()
    if enable_world_editor and editor_cls is not None and editor_cfg_cls is not None:
        try:
            add_captions = os.environ.get("HS_EDIT_ADD_CAPTIONS", "0").strip().lower() in ("1", "true", "yes", "on")
            world_editor_config = editor_cfg_cls(
                target_ratio=os.environ.get("HS_EDIT_TARGET_RATIO", "9:16"),
                translate_to=(os.environ.get("HS_EDIT_TRANSLATE_TO", "").strip() or None),
                add_captions=add_captions,
                add_dynamic_overlays=True,
                add_cta=True,
                add_hashtags=True,
                add_emojis=True,
                enhance_visuals=True,
                enhance_audio=True,
                enable_active_speaker=True,
                enable_hook_speed_ramp=os.environ.get("HS_EDIT_HOOK_RAMP", "0").strip().lower() in ("1", "true", "yes", "on"),
                preserve_quality=True,
                quality_crf=int(os.environ.get("HS_EDIT_QUALITY_CRF", "15") or 15),
                quality_preset=os.environ.get("HS_EDIT_QUALITY_PRESET", "medium"),
            )
            log.info("[EDITOR] enabled=True add_captions=%s ratio=%s", add_captions, world_editor_config.target_ratio)
        except Exception as e:
            log.warning("[EDITOR] world editor init failed: %s", e)
            world_editor = None
            world_editor_config = None

    # One-time narrative/annotation compute phase (never inside clip loop).
    clip_narrative_cache = {}
    if world_editor_config is not None:
        narrative_t0 = time.time()
        try:
            marker_conclusion = ("so remember", "don't forget", "always remember", "bottom line", "in conclusion", "ultimately", "the point is", "and that's why", "which is why", "this is why")
            marker_cta = ("subscribe", "like", "follow", "comment", "click", "check out", "watch", "visit", "download")
            marker_punch = ("that's why", "that's how", "the truth is", "the key is", "what this means", "here's the thing")

            ann_segments = []
            for seg in (global_transcript or []):
                try:
                    s = float(seg.get("start", 0.0) or 0.0)
                    e = float(seg.get("end", s) or s)
                    t = str(seg.get("text", "") or "")
                    tl = t.lower()
                    ann_segments.append({
                        "start": s,
                        "end": e,
                        "text": t,
                        "is_cta": any(m in tl for m in marker_cta),
                        "is_conclusion": any(m in tl for m in marker_conclusion),
                        "is_punch": any(m in tl for m in marker_punch),
                    })
                except Exception:
                    continue

            # Precompute per-clip transcript windows and light narrative flags once.
            for r in moment_results:
                idx, _, text, start_r, end_r, _, _, _, _ = r
                ws = float(start_r or 0.0)
                we = float(end_r or ws)
                tw = [s for s in ann_segments if s["start"] < we and s["end"] > ws]
                # Mirror editor trim heuristic once.
                clip_duration = max(0.01, we - ws)
                trim_in = 0.0
                trim_out = clip_duration
                if world_editor_config.auto_trim and tw:
                    try:
                        speech_start = min(float(x.get("start", ws)) for x in tw)
                        speech_end = max(float(x.get("end", we)) for x in tw)
                        trim_in = max(0.0, min((speech_start - ws) - world_editor_config.trim_pad_in_s, max(0.0, clip_duration - 0.2)))
                        trim_out = max(trim_in + 0.2, min((speech_end - ws) + world_editor_config.trim_pad_out_s, clip_duration))
                        if (trim_out - trim_in) < 8.0:
                            trim_in, trim_out = 0.0, clip_duration
                    except Exception:
                        trim_in, trim_out = 0.0, clip_duration

                # Same boring-mode logic done once (kept deterministic).
                full_text = " ".join(str(seg.get("text", "")) for seg in tw)
                toks = re.findall(r"[a-zA-Z0-9']+", full_text.lower())
                lexical_diversity = (len(set(toks)) / max(1, len(toks))) if toks else 1.0
                questions = full_text.count("?")
                exclaims = full_text.count("!")
                durs = [max(0.0, float(s.get("end", 0.0)) - float(s.get("start", 0.0))) for s in tw]
                avg_seg = (sum(durs) / len(durs)) if durs else 0.0
                boring_mode = bool(toks and len(toks) >= 20 and lexical_diversity < 0.34 and questions == 0 and exclaims <= 1 and avg_seg > 2.8)

                clip_narrative_cache[idx] = {
                    "clip_idx": int(idx),
                    "clip_title": text or f"Viral Clip #{idx}",
                    "transcript_window": [{"start": s["start"], "end": s["end"], "text": s["text"]} for s in tw],
                    "markers": {
                        "cta": [float(s["start"]) for s in tw if s.get("is_cta")],
                        "conclusion": [float(s["start"]) for s in tw if s.get("is_conclusion")],
                        "punch": [float(s["start"]) for s in tw if s.get("is_punch")],
                    },
                    "boring_monologue_detected": boring_mode,
                    "trim": {"in": round(float(trim_in), 3), "out": round(float(trim_out), 3)},
                }

            log.info("[OPT] narrative_compute_phase=once clips=%d wall=%.2fs", len(clip_narrative_cache), (time.time() - narrative_t0))
        except Exception as e:
            log.warning("[OPT] narrative precompute failed, falling back safely: %s", e)
            clip_narrative_cache = {}

    clip_workers_cfg = int(os.environ.get("HS_CLIP_MAX_WORKERS", "0") or 0)
    if clip_workers_cfg > 0:
        clip_workers = max(1, min(16, clip_workers_cfg))
    else:
        # Render free tier is memory-constrained; keep clip generation single-threaded by default.
        if IS_RENDER_RUNTIME:
            clip_workers = 1
        else:
            clip_workers = 4 if (world_editor_config is None) else 2

    log.info(
        "[CLIP] mode=stream_copy workers=%d fallback_reencode=%s preset=%s crf=%s",
        clip_workers,
        os.environ.get("HS_CLIP_FALLBACK_REENCODE", "0"),
        os.environ.get("HS_CLIP_REENCODE_PRESET", "ultrafast"),
        os.environ.get("HS_CLIP_REENCODE_CRF", "23"),
    )
    log.info("[OPT] clip generation parallelism confirmed: %d workers", clip_workers)
    clip_profile_enabled = os.environ.get("HS_CLIP_PROFILE", "0").strip().lower() in ("1", "true", "yes", "on")
    clip_batch_t0 = time.time()

    def _clip_pipeline_task(
        idx: int,
        final_moment: dict,
        text: str,
        start_r: float,
        end_r: float,
        final_score: float,
        base_score: float,
        duration: float,
        filename: str,
        abs_path: str,
        submitted_ts: float,
    ) -> dict:
        t_start = time.time()
        queue_wait_s = max(0.0, t_start - float(submitted_ts or t_start))
        clip_ok, clip_wall_s, clip_mode = _generate_clip_ffmpeg_safe(
            video_path,
            start_r,
            end_r,
            abs_path,
        )
        if not clip_ok:
            return {
                "ok": False,
                "idx": idx,
                "error": "clip_generation_failed",
                "queue_wait_s": float(queue_wait_s or 0.0),
            }

        enhanced_filename = filename
        enhanced_abs_path = abs_path
        edit_metadata = {}
        edit_wall_s = 0.0
        if world_editor_config is not None and editor_cls is not None:
            t_edit = time.time()
            try:
                local_editor = editor_cls(
                    work_dir=os.path.join(outputs_dir, "_world_edit_tmp"),
                    keep_debug_files=False,
                )
                enhanced_filename = f"clip_{idx}_{start_r}_{end_r}_enhanced.mp4"
                enhanced_abs_path = os.path.join(outputs_dir, enhanced_filename)
                edit_result = local_editor.enhance_pretrimmed_clip(
                    input_path=abs_path,
                    output_path=enhanced_abs_path,
                    source_start=float(start_r),
                    source_end=float(end_r),
                    transcript=None,
                    config=world_editor_config,
                    clip_title=(text or f"Viral Clip #{idx}"),
                    precomputed_narrative=clip_narrative_cache.get(idx),
                    write_metadata_file=False,
                )
                edit_metadata = (edit_result.metadata or {})
            except Exception as e:
                log.warning("[EDITOR] clip#%d enhancement skipped: %s", idx, e)
                enhanced_filename = filename
                enhanced_abs_path = abs_path
                edit_metadata = {}
            finally:
                edit_wall_s = max(0.0, time.time() - t_edit)

        task_exec_s = max(0.0, time.time() - t_start)
        postprocess_s = max(0.0, task_exec_s - float(clip_wall_s or 0.0))
        return {
            "ok": True,
            "idx": idx,
            "final_moment": final_moment,
            "text": text,
            "start_r": start_r,
            "end_r": end_r,
            "final_score": float(final_score),
            "base_score": float(base_score),
            "duration": duration,
            "filename": filename,
            "abs_path": abs_path,
            "enhanced_filename": enhanced_filename,
            "enhanced_abs_path": enhanced_abs_path,
            "edit_metadata": edit_metadata,
            "clip_wall_s": float(clip_wall_s or 0.0),
            "clip_mode": clip_mode,
            "edit_wall_s": float(edit_wall_s or 0.0),
            "task_wall_s": task_exec_s,
            "queue_wait_s": float(queue_wait_s or 0.0),
            "postprocess_s": float(postprocess_s or 0.0),
        }

    with ThreadPoolExecutor(max_workers=clip_workers) as encoder:
        future_map = {}

        for r in moment_results:
            idx, final_moment, text, start_r, end_r, final_score, base_score, _, duration = r
            filename = f"clip_{idx}_{start_r}_{end_r}.mp4"
            abs_path = os.path.join(outputs_dir, filename)
            submitted_ts = time.time()
            future = encoder.submit(
                _clip_pipeline_task,
                idx,
                final_moment,
                text,
                start_r,
                end_r,
                float(final_score),
                float(base_score),
                duration,
                filename,
                abs_path,
                submitted_ts,
            )
            future_map[future] = idx

        pending_rows = []
        clip_profile_lines = []
        clip_log_lines = []
        for future in as_completed(future_map):
            try:
                payload = future.result()
                if not payload or not payload.get("ok"):
                    continue
                idx = int(payload.get("idx", -1))
                text = payload.get("text", "")
                start_r = float(payload.get("start_r", 0.0))
                end_r = float(payload.get("end_r", 0.0))
                final_score = float(payload.get("final_score", 0.0))
                base_score = float(payload.get("base_score", 0.0))
                duration = payload.get("duration", 0.0)
                filename = payload.get("filename", "")
                enhanced_filename = payload.get("enhanced_filename", filename)
                enhanced_abs_path = payload.get("enhanced_abs_path", "")
                final_moment = payload.get("final_moment", {}) or {}
                edit_metadata = payload.get("edit_metadata", {}) or {}
                clip_wall_s = float(payload.get("clip_wall_s", 0.0) or 0.0)
                clip_mode = str(payload.get("clip_mode", "unknown"))
                edit_wall_s = float(payload.get("edit_wall_s", 0.0) or 0.0)
                task_wall_s = float(payload.get("task_wall_s", 0.0) or 0.0)
                queue_wait_s = float(payload.get("queue_wait_s", 0.0) or 0.0)
                postprocess_s = float(payload.get("postprocess_s", 0.0) or 0.0)

                if enhanced_filename != filename and (not enhanced_abs_path or not os.path.exists(enhanced_abs_path)):
                    enhanced_abs_path = payload.get("abs_path", "")
                    enhanced_filename = filename

                db_path = f"static/outputs/{filename}"
                if enhanced_filename != filename:
                    db_path = f"static/outputs/{enhanced_filename}"

                pending_rows.append({
                    "idx": idx,
                    "title": text or f"Viral Clip #{idx}",
                    "db_path": db_path,
                    "start": start_r,
                    "end": end_r,
                    "score": float(final_score),
                    "base_score": float(base_score),
                    "hook_score": float(final_moment.get("hook_score", 0.0) or 0.0),
                    "open_loop_score": float(final_moment.get("open_loop_score", 0.0) or 0.0),
                    "pattern_break_score": float(final_moment.get("pattern_break_score", 0.0) or 0.0),
                    "ending_strength": float(final_moment.get("ending_strength", 0.0) or 0.0),
                    "payoff_resolution_score": float(final_moment.get("payoff_resolution_score", 0.0) or 0.0),
                    "rewatch_score": float(final_moment.get("rewatch_score", 0.0) or 0.0),
                    "information_density_score": float(final_moment.get("information_density_score", 0.0) or 0.0),
                    "virality_confidence": float(final_moment.get("virality_confidence", 0.0) or 0.0),
                    "duration_score": float(final_moment.get("duration_score", 0.0) or 0.0),
                    "final_score": float(final_moment.get("final_score", final_score) or final_score),
                    "arc_score": float(final_moment.get("arc_score", final_score) or final_score),
                    "editor_score": float(final_moment.get("editor_score", 0.0) or 0.0),
                    "signals": final_moment.get("signals", {}) if isinstance(final_moment.get("signals"), dict) else {},
                    "hook_segment": final_moment.get("hook_segment", {}) if isinstance(final_moment.get("hook_segment"), dict) else {},
                    "payoff_segment": final_moment.get("payoff_segment", {}) if isinstance(final_moment.get("payoff_segment"), dict) else {},
                    "build_text": str(final_moment.get("build_text", "") or ""),
                    "story_patterns": list(final_moment.get("story_patterns", []) or []),
                    "arc_complete": bool(final_moment.get("arc_complete", False)),
                    "rank": int(final_moment.get("rank", idx + 1) or (idx + 1)),
                    "is_best": bool(final_moment.get("is_best", idx == 0)),
                    "is_recommended": bool(final_moment.get("is_recommended", idx < 3)),
                    "ratio": world_editor_config.target_ratio if world_editor_config is not None else "native",
                    "edit_metadata": edit_metadata,
                })

                clip_log_lines.append(
                    "[CLIP] #%d generated dur=%.1fs wall=%.2fs edit=%.2fs total=%.2fs mode=%s" % (
                        idx,
                        float(duration or 0.0),
                        float(clip_wall_s or 0.0),
                        float(edit_wall_s or 0.0),
                        float(task_wall_s or 0.0),
                        clip_mode,
                    )
                )
                if clip_profile_enabled:
                    clip_profile_lines.append(
                        "[CLIP-PROFILE] #%d queue=%.3fs wait=%.3fs ffmpeg=%.3fs post=%.3fs" % (
                            idx,
                            float(queue_wait_s or 0.0),
                            float(queue_wait_s or 0.0),
                            float(clip_wall_s or 0.0),
                            float(postprocess_s or 0.0),
                        )
                    )

            except Exception as e:
                idx = future_map.get(future, -1)
                log.exception("[ANALYZE] Clip #%d failed: %s", idx, e)
                db.session.rollback()

    # Persist all clip rows in one DB transaction (avoids per-clip fsync/sync stalls).
    try:
        # Calculate composite quality score for proper ranking
        def calculate_clip_score(row):
            """
            Composite score: weights quality metrics to rank best clips first
            Higher score = better clip, will be sorted in descending order
            """
            final_score = float(row.get("final_score", 0.0) or 0.0)
            virality_confidence = float(row.get("virality_confidence", 0.0) or 0.0)
            hook_score = float(row.get("hook_score", 0.0) or 0.0)
            arc_score = float(row.get("arc_score", 0.0) or 0.0)
            duration_score = float(row.get("duration_score", 0.0) or 0.0)
            editor_score = float(row.get("editor_score", 0.0) or 0.0)
            open_loop_score = float(row.get("open_loop_score", 0.0) or 0.0)
            
            # Weighted composite score (best clips will have highest score)
            composite = (
                0.25 * final_score +
                0.20 * virality_confidence +
                0.15 * hook_score +
                0.15 * arc_score +
                0.10 * duration_score +
                0.10 * editor_score +
                0.05 * open_loop_score
            )
            return composite
        
        # Sort by composite score (descending - highest first)
        pending_rows.sort(key=lambda r: calculate_clip_score(r), reverse=True)
        
        # Re-rank after sorting
        for new_idx, row in enumerate(pending_rows, 1):
            row["rank"] = new_idx
            row["is_best"] = (new_idx == 1)
            row["is_recommended"] = (new_idx <= 3)
        
        clip_models = []
        for row in pending_rows:
            clip = Clip(
                title=row.get("title") or f"Viral Clip #{row.get('idx', 0)}",
                file_path=row.get("db_path"),
                user_id=current_user.id,
                job_id=job.id
            )
            if db_has_column("clip", "start"):
                clip.start = float(row.get("start", 0.0))
            if db_has_column("clip", "end"):
                clip.end = float(row.get("end", 0.0))
            if db_has_column("clip", "score"):
                clip.score = float(row.get("score", 0.0))
            clip_models.append(clip)

        if clip_models:
            db.session.add_all(clip_models)
            db.session.flush()
            for clip, row in zip(clip_models, pending_rows):
                generated_clips.append({
                    "clip_id": clip.id,
                    "title": clip.title,
                    "clip_url": "/" + row.get("db_path", ""),
                    "start": row.get("start"),
                    "end": row.get("end"),
                    "score": row.get("score"),
                    "base_score": row.get("base_score"),
                    "hook_score": row.get("hook_score"),
                    "open_loop_score": row.get("open_loop_score"),
                    "pattern_break_score": row.get("pattern_break_score"),
                    "ending_strength": row.get("ending_strength"),
                    "payoff_resolution_score": row.get("payoff_resolution_score"),
                    "rewatch_score": row.get("rewatch_score"),
                    "information_density_score": row.get("information_density_score"),
                    "virality_confidence": row.get("virality_confidence"),
                    "duration_score": row.get("duration_score"),
                    "final_score": row.get("final_score"),
                    "arc_score": row.get("arc_score"),
                    "editor_score": row.get("editor_score"),
                    "signals": row.get("signals") or {},
                    "hook_segment": row.get("hook_segment") or {},
                    "payoff_segment": row.get("payoff_segment") or {},
                    "build_text": row.get("build_text") or "",
                    "story_patterns": row.get("story_patterns") or [],
                    "arc_complete": row.get("arc_complete"),
                    "rank": row.get("rank"),
                    "is_best": row.get("is_best"),
                    "is_recommended": row.get("is_recommended"),
                    "ratio": row.get("ratio"),
                    "edit_metadata": row.get("edit_metadata") or {},
                })
            db.session.commit()

        for line in clip_log_lines:
            log.info("%s", line)
        if clip_profile_enabled:
            for line in clip_profile_lines:
                log.info("%s", line)
    except Exception as e:
        log.exception("[ANALYZE] Batch clip persistence failed: %s", e)
        db.session.rollback()
        return analyze_error("Clip save failed. Try again.", 500)

    log.info(
        "[CLIP] batch complete clips=%d wall=%.2fs",
        len(generated_clips),
        (time.time() - clip_batch_t0),
    )
    log.info("[OPT] clip_loop_nlp_calls=0")

    # Sort clips by composite quality score (best first)
    try:
        def calculate_clip_score(c):
            """Composite score for ranking - higher is better"""
            final_score = float(c.get("final_score", 0.0) or 0.0)
            virality_confidence = float(c.get("virality_confidence", 0.0) or 0.0)
            hook_score = float(c.get("hook_score", 0.0) or 0.0)
            arc_score = float(c.get("arc_score", 0.0) or 0.0)
            duration_score = float(c.get("duration_score", 0.0) or 0.0)
            editor_score = float(c.get("editor_score", 0.0) or 0.0)
            open_loop_score = float(c.get("open_loop_score", 0.0) or 0.0)
            
            return (
                0.25 * final_score +
                0.20 * virality_confidence +
                0.15 * hook_score +
                0.15 * arc_score +
                0.10 * duration_score +
                0.10 * editor_score +
                0.05 * open_loop_score
            )
        
        # Sort by score descending (best first) and re-rank
        generated_clips.sort(key=calculate_clip_score, reverse=True)
        for new_idx, clip in enumerate(generated_clips, 1):
            clip["rank"] = new_idx
            clip["is_best"] = (new_idx == 1)
            clip["is_recommended"] = (new_idx <= 3)
    except Exception:
        pass

    if not generated_clips:
        job.status = "failed"
        db.session.commit()
        return analyze_error("No clips could be generated.", 400)

    # --------------------------------------------------
    # 7) Finalize Job
    # --------------------------------------------------
    job.analysis_data = json.dumps(generated_clips)
    job.status = "completed"
    job.completed_at = datetime.utcnow()
    db.session.commit()

    try:
        schedule_cleanup([wav_path], delay=120)
    except Exception:
        pass

    log_mem("after clip render")
    log.info("[ANALYZE] Job completed: %s (%d clips)", job_id, len(generated_clips))
    log.info("[TIMING] stage=analyze_total wall=%.2fs", (time.time() - analyze_t0))

    # Count a successful full analyze against the trial quota.
    if plan_type == "trial" and not _open_testing_mode_enabled():
        try:
            used = int(getattr(current_user, "trial_analyze_count", 0) or 0)
            if used < 1:
                current_user.trial_analyze_count = used + 1
                db.session.commit()
        except Exception:
            db.session.rollback()
            log.exception("[ANALYZE] Failed to increment trial_analyze_count")

    return analyze_success(job_id, len(generated_clips))

# @app.route('/generate', methods=['POST'])
# @login_required
# def generate_clip_route():
#     import random
#     import os
#     import re
#     from flask import jsonify, url_for, session

#     youtube_url = request.form.get('video_url') or session.get('last_analyzed_url')
#     if not youtube_url:
#         return jsonify({"error": "No YouTube URL found"}), 400

#     print("=" * 60)
#     print(f"[GENERATE ⚡] Generating VIRAL clips for: {youtube_url}")
#     print("=" * 60)

#     # ---------------------------------------------------------
#     # 1. Cache system setup
#     # ---------------------------------------------------------
#     cache_dir = os.path.join("static", "cache")
#     os.makedirs(cache_dir, exist_ok=True)

#     safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', youtube_url)
#     cached_path = os.path.join(cache_dir, f"{safe_name}.mp4")

#     # ---------------------------------------------------------
#     # 2. Download video if not cached
#     # ---------------------------------------------------------
#     if not os.path.exists(cached_path):
#         print(f"[CACHE MISS] Downloading once...")

#         full_video_path = download_youtube_video(youtube_url, cache_dir)

#         if not full_video_path or not os.path.exists(full_video_path):
#             print("[❌ ERROR] Download failed — no file created.")
#             return jsonify({"error": "Failed to download video from YouTube."}), 500

#         try:
#             os.rename(full_video_path, cached_path)
#             print(f"[CACHE OK] Video cached: {cached_path}")
#         except OSError:
#             cached_path = full_video_path
#     else:
#         print("[CACHE OK] Using cached video.")

#     # ---------------------------------------------------------
#     # 3. GET VIRAL MOMENTS (from session)
#     # ---------------------------------------------------------
#     viral_moments = session.get("viral_moments")

#     if not viral_moments:
#         print("[❌] No viral moments found in session.")
#         return jsonify({"error": "Analyze video first to detect viral moments."}), 400

#     print(f"[FOUND VIRAL MOMENTS] {len(viral_moments)}")

#     # ---------------------------------------------------------
#     # 4. CUT VIRAL CLIPS instead of random clips
#     # ---------------------------------------------------------
#     all_clips = []

#     for i, moment in enumerate(viral_moments):
#         start = float(moment.get("start", 0))
#         end = float(moment.get("end", start + 10))

#         # force a min length of 10s, max 35s
#         if (end - start) < 10:
#             end = start + 10
#         if (end - start) > 35:
#             end = start + 35

#         print(f"[VIRAL CLIP {i+1}] {start:.1f}s → {end:.1f}s")

#         try:
#             clip_path = generate_clip_for_job(cached_path, start, end)

#             title = moment.get("text", f"Clip {start}-{end}")[:40]

#             new_clip = Clip(
#                 title=title,
#                 file_path=clip_path,
#                 user_id=current_user.id
#             )
#             db.session.add(new_clip)
#             db.session.commit()

#             clip_url = url_for('static', filename=f"outputs/{os.path.basename(clip_path)}")

#             all_clips.append({
#                 "title": title,
#                 "clip_url": clip_url,
#                 "start": start,
#                 "end": end,
#                 "score": moment.get("score", 0),
#                 "job_id": new_clip.id
#             })

#             print(f"[OK] Generated viral clip: {clip_url}")

#         except Exception as e:
#             print(f"[ERROR ❌] Failed to generate clip {i+1}: {e}")

#     if not all_clips:
#         return jsonify({"error": "No viral clips generated."}), 500

#     # ✅ NEW: Create Job record for this analysis (Elite Build)
#     try:
#         import json as jsonmodule
#         job_id = str(uuid.uuid4())
        
#         # Extract transcript from viral_moments if available
#         transcript_text = ""
#         if viral_moments and isinstance(viral_moments, list) and len(viral_moments) > 0:
#             if isinstance(viral_moments[0], dict) and "transcript" in viral_moments[0]:
#                 transcript_text = viral_moments[0].get("transcript", "")
        
#         job = Job(
#             id=job_id,
#             user_id=current_user.id,
#             video_path=cached_path,  # ✅ Use cached_path (the actual video file)
#             transcript=transcript_text or "",  # ✅ Use extracted transcript
#             analysis_data=jsonmodule.dumps(all_clips),  # Store all clips as JSON
#             status="completed"
#         )
#         db.session.add(job)
#         db.session.commit()
        
#         log.info(f"[GENERATE] Created Job record: {job_id}")
        
#         # ✅ Return success with job info
#         return jsonify({
#             "success": True,
#             "job_id": job_id,
#             "clips_count": len(all_clips),
#             "redirect_url": url_for('results', job_id=job_id)
#         }), 200
        
#     except Exception as e:
#         log.error(f"[GENERATE] Error creating Job record: {e}")
#         # Fall back to direct JSON return if Job creation fails
#         return jsonify(all_clips), 200


# @app.route('/generate', methods=['POST'])
# @login_required
# def generate_clip_route():
#     import random
#     import os
#     import re
#     from flask import jsonify, url_for, session

#     youtube_url = request.form.get('video_url') or session.get('last_analyzed_url')
#     if not youtube_url:
#         return jsonify({"error": "No YouTube URL found"}), 400

#     print("=" * 60)
#     print(f"[GENERATE ⚡] Generating viral clips for: {youtube_url}")
#     print("=" * 60)

#     # ---------------------------------------------------------
#     # ✅ Step 1: Cache system setup
#     # ---------------------------------------------------------
#     cache_dir = os.path.join("static", "cache")
#     os.makedirs(cache_dir, exist_ok=True)

#     safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', youtube_url)
#     cached_path = os.path.join(cache_dir, f"{safe_name}.mp4")

#     # ---------------------------------------------------------
#     # ✅ Step 2: Download video if not cached
#     # ---------------------------------------------------------
#     if not os.path.exists(cached_path):
#         print(f"[CACHE MISS] Downloading video once...")

#         full_video_path = download_youtube_video(youtube_url, cache_dir)

#         if not full_video_path or not os.path.exists(full_video_path):
#             print("[❌ ERROR] Download failed — no file created.")
#             return jsonify({"error": "Failed to download video from YouTube."}), 500

#         try:
#             os.rename(full_video_path, cached_path)
#             print(f"[CACHE ✅] Video cached at: {cached_path}")
#         except OSError as e:
#             print(f"[WARN] Rename failed: {e}. Using downloaded file path.")
#             cached_path = full_video_path
#     else:
#         print("[CACHE ✅] Using existing cached video.")

#     # ---------------------------------------------------------
#     # ✅ Step 3: Generate viral subclips
#     # ---------------------------------------------------------
#     all_clips = []
#     for i in range(5):
#         start = random.randint(10, 120)
#         end = start + 10

#         print(f"[CLIP {i+1}] 🎬 Cutting segment {start}-{end}s")

#         try:
#             clip_path = generate_clip_for_job(cached_path, start, end)
#             title = f"Clip {start}-{end}s"

#             # Save to database
#             new_clip = Clip(
#                 title=title,
#                 file_path=clip_path,
#                 user_id=current_user.id
#             )
#             db.session.add(new_clip)
#             db.session.commit()

#             clip_url = url_for('static', filename=f"outputs/{os.path.basename(clip_path)}")

#             all_clips.append({
#                 "title": title,
#                 "clip_url": clip_url,
#                 "job_id": new_clip.id
#             })

#             print(f"[CLIP {i+1}] ✅ Generated: {clip_url}")

#         except Exception as e:
#             print(f"[ERROR ❌] Failed to generate clip {i+1}: {e}")

#     # ---------------------------------------------------------
#     # ✅ Step 4: Validate and return JSON
#     # ---------------------------------------------------------
#     if not all_clips:
#         print("[FATAL ❌] No clips generated — returning 500")
#         return jsonify({"error": "No clips generated"}), 500

#     print(f"[SUCCESS ⚡] Generated {len(all_clips)} viral clips.")
#     print("=" * 60)
#     return jsonify(all_clips)

import yt_dlp
import os
import re
import shutil
import browser_cookie3


def fetch_youtube_metadata(url):
    """Fetch only metadata for a YouTube URL without downloading any media.

    Returns a dict with video_id, title, duration, thumbnail (when available).
    Uses ``yt_dlp`` in ``skip_download`` mode which avoids RAM/CPU spikes.
    """
    import yt_dlp

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        # avoid writing anything to disk
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    return {
        "video_id": info.get("id"),
        "title": info.get("title"),
        "duration": info.get("duration"),
        "thumbnail": info.get("thumbnail"),
    }


def fetch_youtube_transcript(url, languages=None):
    """Attempt to retrieve the YouTube transcript (captions) as a list of segments.

    Uses the ``youtube-transcript-api`` package, which is already a dependency
    in requirements.txt.  This runs over the network and returns text-only data
    without downloading any media.  ``languages`` may be a list like ['en'] to
    prefer English captions; if omitted the API will attempt auto-detection.
    """
    try:
        # extract id from common YouTube url formats
        m = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})", url)
        video_id = m.group(1) if m else url
    except Exception:
        video_id = url

    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        segs = YouTubeTranscriptApi.get_transcript(video_id, languages=languages or ["en"])
        # transform segments to match our usual structure
        return [{
            "text": s.get("text", ""),
            "start": float(s.get("start", 0.0)),
            "end": float(s.get("start", 0.0) + s.get("duration", 0.0)),
        } for s in segs]
    except Exception as e:
        log.warning("[TRANSCRIPT] youtube transcript fetch failed: %s", e)
        return []


def select_segment_from_transcript(transcript_segments, duration_s=None):
    """Pick a start/end timestamp based on lightweight data.

    For now this is a simple fallback that prefers the first low-memory moment
    (which only needs duration).  Later this can be replaced by a smarter NLP
    decision.  The goal is to compute timestamps *before* downloading video.
    """
    if duration_s:
        candidates = _generate_low_memory_moments(duration_s, top_k=3)
        if candidates:
            first = candidates[0]
            return first.get("start", 0.0), first.get("end", first.get("start", 0.0) + 15.0)
    # ultimate fallback
    return 0.0, min(30.0, float(duration_s or 30.0))


def _js_runtime_available() -> bool:
    try:
        return bool(shutil.which("node") or shutil.which("deno"))
    except Exception:
        return False


def _ingestion_signature() -> str:
    # Any change here invalidates ingestion cache reuse automatically.
    fields = {
        "ytdlp_format": os.environ.get("HS_YTDLP_FORMAT", ""),
        "transcript_model": os.environ.get("HS_TRANSCRIPT_MODEL", "small"),
        "transcript_long_model": os.environ.get("HS_TRANSCRIPT_LONGFORM_MODEL", "tiny"),
        "vad_profile": os.environ.get("HS_VAD_PROFILE", "quality"),
        "vad_pregate": os.environ.get("HS_VAD_PREGATE", "0"),
        "vad_skip_above": os.environ.get("HS_VAD_SKIP_ABOVE_SECONDS", "900"),
        "vad_turbo_above": os.environ.get("HS_VAD_TURBO_ABOVE_SECONDS", "300"),
        "force_vad": os.environ.get("HS_FORCE_VAD", "0"),
        "cognition_engine": os.environ.get("HS_COGNITION_ENGINE", "legacy"),
        "js_runtime": "1" if _js_runtime_available() else "0",
        "ingest_schema_rev": "v2",
    }
    raw = "|".join(f"{k}={fields[k]}" for k in sorted(fields.keys()))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _download_youtube_segment_with_format(url, start, end, output_dir="downloads", job_id=None, format_selector=None):
    os.makedirs(output_dir, exist_ok=True)
    safe_job = None
    try:
        safe_job = re.sub(r"[^a-zA-Z0-9_-]", "_", job_id) if job_id else None
    except Exception:
        safe_job = None

    fmt = (format_selector or "bestvideo+bestaudio/best").strip()
    ydl_opts = {
        "format": fmt,
        "merge_output_format": "mp4",
        "outtmpl": os.path.join(output_dir, f"{safe_job or '%(id)s'}.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "download_ranges": (lambda info, ydl: [{"start_time": start, "end_time": end}]),
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        file_path = None
        if safe_job:
            expected = os.path.join(output_dir, f"{safe_job}.mp4")
            if os.path.exists(expected):
                file_path = expected
        if not file_path:
            file_path = ydl.prepare_filename(info)
            if (not os.path.exists(file_path)) and os.path.exists(file_path + ".mp4"):
                file_path = file_path + ".mp4"
    return file_path


def _copy_segment_ffmpeg(src_path, start_s, end_s, out_path):
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        str(max(0.0, float(start_s or 0.0))),
        "-to",
        str(max(float(start_s or 0.0) + 0.2, float(end_s or 0.0))),
        "-i",
        src_path,
        "-c",
        "copy",
        out_path,
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    return out_path


def acquire_youtube_media_robust(url, start, end, output_dir="downloads", job_id=None, metadata=None):
    """
    Stage 1 ingestion: multi-path acquisition with explicit quality scoring.
    Returns (best_path, acquisition_quality_score, attempts, media_probe, js_runtime_ok).
    """
    os.makedirs(output_dir, exist_ok=True)
    attempts = []
    expected_duration = max(1.0, float(end or 0.0) - float(start or 0.0))
    metadata_duration = float((metadata or {}).get("duration") or 0.0)
    js_runtime_ok = _js_runtime_available()

    candidate_specs = [
        ("segment_default", "bestvideo+bestaudio/best", True),
        ("segment_progressive", "best[ext=mp4][protocol!=dash]/best[protocol!=dash]", True),
        ("segment_minimal", "worst[ext=mp4][protocol!=dash]/worst[protocol!=dash]", True),
    ]
    good_enough_score = max(0.0, min(1.0, _env_float("HS_ACQ_GOOD_ENOUGH_SCORE", 0.90)))
    best = None
    best_score = 0.0
    best_probe = None

    for idx, (name, fmt, is_segment) in enumerate(candidate_specs):
        try:
            candidate_job = f"{job_id}_ing_{idx}" if job_id else None
            if is_segment:
                p = _download_youtube_segment_with_format(
                    url=url,
                    start=start,
                    end=end,
                    output_dir=output_dir,
                    job_id=candidate_job,
                    format_selector=fmt,
                )
            else:
                p = download_youtube_video(url, output_dir=output_dir, job_id=candidate_job)
            if not p or (not os.path.exists(p)):
                raise RuntimeError("media_missing")
            probe = probe_media(p)
            size_b = int(os.path.getsize(p) if os.path.exists(p) else 0)

            # ✳️ Fail‑safe guard against truncated/JS-failure segments
            if probe.get("ok") and probe.get("duration", 0.0) < 60.0 and metadata_duration > 300.0:
                warning = {"starvation_detected": True, "reason": "partial_download_or_js_failure"}
                log.warning("acquisition warning: %s", warning)
                attempts.append({
                    "path_name": name,
                    "format": fmt,
                    "ok": False,
                    "path": p,
                    "probe": probe,
                    "size_bytes": size_b,
                    "warning": warning,
                })
                # don't score this attempt, move to next candidate
                continue

            score, components = score_acquisition(
                media_probe=probe,
                expected_duration=expected_duration,
                metadata_duration=metadata_duration,
                file_size_bytes=size_b,
            )
            if not js_runtime_ok:
                score *= 0.70
                components["js_runtime_penalty"] = 0.30
            attempt = {
                "path_name": name,
                "format": fmt,
                "ok": True,
                "path": p,
                "probe": probe,
                "size_bytes": size_b,
                "score": round(float(score), 4),
                "components": components,
            }
            attempts.append(attempt)
            if score > best_score:
                best = p
                best_score = float(score)
                best_probe = probe
            if best_score >= good_enough_score:
                # Early exit to avoid avoidable latency once acquisition quality is strong.
                break
        except Exception as e:
            msg = str(e) or repr(e)
            if "HTTP Error 429" in msg or "Too Many Requests" in msg or "429:" in msg:
                raise YoutubeRateLimitError(msg)
            if "Sign in to confirm" in msg or "not a bot" in msg.lower():
                raise YoutubeCaptchaError(msg)
            attempts.append(
                {
                    "path_name": name,
                    "format": fmt,
                    "ok": False,
                    "error": msg,
                }
            )

    # Path D fallback: full minimal fetch + ffmpeg copy to requested segment.
    if (best is None or best_score < 0.72):
        try:
            full_job = f"{job_id}_full_fallback" if job_id else None
            full_path = download_youtube_video(url, output_dir=output_dir, job_id=full_job)
            if full_path and os.path.exists(full_path):
                seg_path = os.path.join(output_dir, f"{job_id or ingestion_cache_key(url)}_fallback_segment.mp4")
                _copy_segment_ffmpeg(full_path, start, end, seg_path)
                probe = probe_media(seg_path)
                size_b = int(os.path.getsize(seg_path) if os.path.exists(seg_path) else 0)

                # starvation guard on fallback copy as well
                if probe.get("ok") and probe.get("duration", 0.0) < 60.0 and metadata_duration > 300.0:
                    warning = {"starvation_detected": True, "reason": "partial_download_or_js_failure"}
                    log.warning("acquisition warning (fallback): %s", warning)
                    attempts.append({
                        "path_name": "full_fallback_segment_copy",
                        "format": "full_minimal+copy",
                        "ok": False,
                        "path": seg_path,
                        "probe": probe,
                        "size_bytes": size_b,
                        "warning": warning,
                    })
                else:
                    score, components = score_acquisition(
                        media_probe=probe,
                        expected_duration=expected_duration,
                        metadata_duration=metadata_duration,
                        file_size_bytes=size_b,
                    )
                    if not js_runtime_ok:
                        score *= 0.70
                        components["js_runtime_penalty"] = 0.30
                    attempts.append(
                        {
                            "path_name": "full_fallback_segment_copy",
                            "format": "full_minimal+copy",
                            "ok": True,
                            "path": seg_path,
                            "probe": probe,
                            "size_bytes": size_b,
                            "score": round(float(score), 4),
                            "components": components,
                        }
                    )
                    if score > best_score:
                        best = seg_path
                        best_score = float(score)
                        best_probe = probe
        except Exception as e:
            msg = str(e) or repr(e)
            if "HTTP Error 429" in msg or "Too Many Requests" in msg or "429:" in msg:
                raise YoutubeRateLimitError(msg)
            if "Sign in to confirm" in msg or "not a bot" in msg.lower():
                raise YoutubeCaptchaError(msg)
            attempts.append(
                {
                    "path_name": "full_fallback_segment_copy",
                    "format": "full_minimal+copy",
                    "ok": False,
                    "error": msg,
                }
            )

    return best, float(best_score), attempts, (best_probe or {}), js_runtime_ok


def download_youtube_segment(url, start, end, output_dir="downloads", job_id=None):
    """Download only the specified time range from a YouTube URL.

    Uses ``yt_dlp`` ``download_ranges`` hook so that only the requested
    portion is fetched.  This is the core of the "segment-only" pipeline.
    """
    os.makedirs(output_dir, exist_ok=True)

    try:
        safe_job = re.sub(r"[^a-zA-Z0-9_-]", "_", job_id) if job_id else None
    except Exception:
        safe_job = None

    ydl_opts = {
        "format": "bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "outtmpl": os.path.join(output_dir, f"{safe_job or '%(id)s'}.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "download_ranges": (lambda info, ydl: [{"start_time": start, "end_time": end}]),
    }

    log.info("[ANALYZE] segment download job_id=%s url=%s range=%.2f-%.2f", safe_job, url, start, end)
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            # determine resulting filename similar to download_youtube_video
            file_path = None
            if safe_job:
                expected = os.path.join(output_dir, f"{safe_job}.mp4")
                if os.path.exists(expected):
                    file_path = expected
            if not file_path:
                file_path = ydl.prepare_filename(info)
                if (not os.path.exists(file_path)) and os.path.exists(file_path + ".mp4"):
                    file_path = file_path + ".mp4"
        return file_path
    except Exception as e:
        msg = str(e) or repr(e)
        if "HTTP Error 429" in msg or "Too Many Requests" in msg or "429:" in msg:
            log.warning(
                "[DOWNLOAD] YouTube rate limited this IP (HTTP 429 / Too Many Requests). url=%s msg=%s",
                url,
                msg,
            )
            raise YoutubeRateLimitError(msg)
        if "Sign in to confirm" in msg or "not a bot" in msg.lower():
            log.warning(
                "[DOWNLOAD] YouTube blocked download with captcha bot-check. url=%s msg=%s",
                url,
                msg,
            )
            raise YoutubeCaptchaError(msg)
        log.error("[DOWNLOAD ERROR] yt-dlp failed url=%s error=%s", url, msg)
        return None


def download_with_fallback(url, output_dir="downloads", job_id=None):
    """
    3-layer resilient YouTube download with automatic fallback strategy.
    
    Layer 1 (fast): Basic yt-dlp
    Layer 2 (cookies): yt-dlp with cookies
    Layer 3 (spoof): Android client spoof
    
    Returns file_path on success, None on complete failure.
    """
    import yt_dlp
    
    os.makedirs(output_dir, exist_ok=True)
    
    safe_job = None
    try:
        safe_job = re.sub(r"[^a-zA-Z0-9_-]", "_", job_id) if job_id else None
    except Exception:
        safe_job = None

    # Proxy support: allow routing yt-dlp through a residential proxy to avoid YouTube bot blocks.
    # Example: set YTDLP_PROXY=http://user:pass@1.2.3.4:1234
    proxy = os.environ.get("YTDLP_PROXY") or os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")

    # Ensure we resolve the cookie file path relative to the app (not cwd)
    cookies_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt")

    # Common anti-bot spoofing options
    spoof_headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }

    # Strategy definitions
    strategies = [
        {
            "name": "normal",
            "desc": "Basic yt-dlp with browser headers",
            "opts": {
                "format": "best",
                "quiet": True,
                "no_warnings": True,
                "geo_bypass": True,
                "nocheckcertificate": True,
                "socket_timeout": 30,
                "retries": 3,
                "user_agent": spoof_headers['User-Agent'],
                "http_headers": spoof_headers,
            }
        },
        {
            "name": "cookies",
            "desc": "yt-dlp with cookies and headers",
            "opts": {
                "format": "best",
                "quiet": True,
                "no_warnings": True,
                "geo_bypass": True,
                "nocheckcertificate": True,
                "socket_timeout": 30,
                "retries": 3,
                "cookiefile": "cookies.txt",
                "user_agent": spoof_headers['User-Agent'],
                "http_headers": spoof_headers,
            }
        },
        {
            "name": "android",
            "desc": "Android client spoof with headers",
            "opts": {
                "format": "best",
                "quiet": True,
                "no_warnings": True,
                "geo_bypass": True,
                "nocheckcertificate": True,
                "socket_timeout": 30,
                "retries": 3,
                "extractor_args": {
                    "youtube": {
                        "player_client": ["android"],
                    }
                },
                "user_agent": 'com.google.android.youtube/19.09.36 (Linux; U; Android 11; SM-G973F) gzip',
                "http_headers": {
                    **spoof_headers,
                    'User-Agent': 'com.google.android.youtube/19.09.36 (Linux; U; Android 11; SM-G973F) gzip',
                },
            }
        },
    ]
    
    for strategy in strategies:
        try:
            strategy_name = strategy["name"]
            strategy_desc = strategy["desc"]
            ydl_opts = strategy["opts"].copy()
            
            # Add common options
            ydl_opts.update({
                "merge_output_format": "mp4",
                "outtmpl": os.path.join(output_dir, f"{safe_job or '%(id)s'}.%(ext)s"),
                "noplaylist": True,
                "concurrent_fragment_downloads": 1,
                "postprocessors": [{
                    "key": "FFmpegVideoConvertor",
                    "preferedformat": "mp4",
                }],
            })

            # Proxy support (residential proxy helps bypass bot check)
            if proxy:
                ydl_opts["proxy"] = proxy
                log.debug("[DOWNLOAD] Using proxy for yt-dlp: %s", proxy)

            # Skip cookies layer if no cookies file exists
            if strategy_name == "cookies" and not os.path.exists(cookies_path):
                log.debug("[DOWNLOAD] Skipping cookies strategy (no cookies file found at %s)", cookies_path)
                continue

            # Ensure cookies layer uses an absolute path
            if strategy_name == "cookies":
                ydl_opts["cookiefile"] = cookies_path

            log.info(
                "[DOWNLOAD] Layer %s: %s url=%s",
                strategy_name.upper(),
                strategy_desc,
                url
            )
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                
                # Determine output file path
                file_path = None
                if safe_job:
                    expected = os.path.join(output_dir, f"{safe_job}.mp4")
                    if os.path.exists(expected):
                        file_path = expected
                
                if not file_path:
                    file_path = ydl.prepare_filename(info)
                    if (not os.path.exists(file_path)) and os.path.exists(file_path + ".mp4"):
                        file_path = file_path + ".mp4"
                
                log.info(
                    "[DOWNLOAD] ✅ SUCCESS with strategy=%s file=%s",
                    strategy_name,
                    os.path.basename(file_path) if file_path else "unknown"
                )
                return file_path
        
        except Exception as e:
            error_msg = str(e) or repr(e)
            log.debug(
                "[DOWNLOAD] ❌ Layer %s failed: %s",
                strategy_name,
                error_msg[:100]
            )
            continue
    
    # All strategies exhausted
    log.error(
        "[DOWNLOAD] ❌ ALL LAYERS FAILED url=%s. "
        "Video may be geo-blocked, age-restricted, or YouTube is blocking this IP.",
        url
    )
    return None


def download_youtube_video(url, output_dir="downloads", job_id=None):
    """
    Professional YouTube video download with 3-layer resilient fallback strategy.
    
    Implements resilient 3-layer strategy:
    1. Layer 1: Fast path with geo_bypass
    2. Layer 2: With cookies (if available)
    3. Layer 3: Android client spoof
    
    Uses youtube_cookie_manager for cookie status tracking and logging.
    
    Returns:
        file_path on success, None on failure (all layers exhausted)
    """
    os.makedirs(output_dir, exist_ok=True)

    # Get professional cookie manager for status logging
    cookie_manager = get_cookie_manager(os.path.dirname(os.path.abspath(__file__)))
    
    # Log download start with cookie status
    log.info(
        "[ANALYZE] Download starting: url=%s job_id=%s cookies_valid=%s",
        url,
        job_id,
        cookie_manager.is_valid,
    )
    
    # Use resilient 3-layer fallback strategy
    file_path = download_with_fallback(url, output_dir, job_id)
    
    if file_path:
        log.info(
            "[ANALYZE] ✅ Download successful: file=%s",
            os.path.basename(file_path),
        )
        return file_path
    else:
        log.error(
            "[ANALYZE] ❌ Download failed after all strategies. "
            "Cookie status: valid=%s url=%s",
            cookie_manager.is_valid,
            url,
        )
        return None


# def download_youtube_video(youtube_url, output_path):
#     """Download a YouTube video and return the file path."""
#     ydl_opts = {
#         'format': 'best[ext=mp4]',
#         'outtmpl': os.path.join(output_path, '%(title)s.%(ext)s'),
#         'quiet': True,
#         'no_warnings': True,
#     }
#     with yt_dlp.YoutubeDL(ydl_opts) as ydl:
#         info = ydl.extract_info(youtube_url, download=True)
#         return os.path.join(output_path, f"{info['title']}.mp4")

# @app.route('/download/<path:filename>')
# def download_clip(filename):
#     file_path = os.path.join("output", filename)
#     if not os.path.exists(file_path):
#         abort(404)
#     return send_file(file_path, as_attachment=True)


# # =====================================================
# # ⚙️ JOB PROGRESS SYSTEM (Async Processing)
# # =====================================================
# @app.route("/start", methods=["POST"])
# def start_job():
#     yt_link = request.form.get("yt_link")
#     if not yt_link:
#         return redirect(url_for("home"))

#     job_id = uuid.uuid4().hex[:12]
#     q = queue.Queue()
#     job_queues[job_id] = q

#     def worker():
#         try:
#             q.put("🎬 Downloading video…")
#             output_path = generate_clip_for_job(yt_link, job_id, lambda m: q.put(m))
#             q.put("✅ Done")
#             schedule_cleanup([output_path, f"temp_{job_id}.mp4"])
#         except Exception as e:
#             q.put(f"❌ Error: {str(e)}")
#         finally:
#             q.put(None)

#     t = threading.Thread(target=worker, daemon=True)
#     job_threads[job_id] = t
#     t.start()

#     return redirect(url_for("progress_page", job_id=job_id))


# @app.route("/progress/<job_id>")
# def progress_page(job_id):
#     if job_id not in job_queues:
#         return "Job not found", 404
#     return render_template("progress.html", job_id=job_id)


# @app.route("/events/<job_id>")
# def events(job_id):
#     """SSE stream of job progress."""
#     if job_id not in job_queues:
#         return "Job not found", 404

#     q = job_queues[job_id]

#     def stream():
#         while True:
#             msg = q.get()
#             if msg is None:
#                 break
#             yield f"data: {msg}\n\n"
#         try:
#             del job_queues[job_id]
#             del job_threads[job_id]
#         except KeyError:
#             pass

#     return Response(stream(), mimetype="text/event-stream")

# # =====================================================
# # 🎞️ CLIP MANAGEMENT ROUTES
# # =====================================================
# @app.route("/result/<job_id>")
# def result(job_id):
#     out_file = os.path.join(OUTPUT_DIR, f"hotshort_clip_{job_id}.mp4")
#     if not os.path.exists(out_file):
#         return "Result not ready or not found.", 404

#     return render_template(
#         "result.html",
#         video_url=f"/output/hotshort_clip_{job_id}.mp4",
#         job_id=job_id
#     )


from flask import send_file, abort
import tempfile
import shutil

# 
@app.route("/download/<int:clip_id>")
@login_required
def download_clip(clip_id):
    clip = Clip.query.filter_by(id=clip_id, user_id=current_user.id).first_or_404()
    qa_event(
        "download_attempt",
        user_id=getattr(current_user, "id", None),
        clip_id=clip_id,
        plan=tier_key(current_user),
        quality=request.args.get("quality"),
    )

    abs_path = os.path.join(app.root_path, (clip.file_path or ""))
    abs_path = os.path.normpath(abs_path)

    # Handle legacy outputs that were mistakenly saved as directories named *.mp4
    if os.path.isdir(abs_path):
        try:
            candidates = [
                os.path.join(abs_path, f)
                for f in os.listdir(abs_path)
                if f.lower().endswith(".mp4")
            ]
            if candidates:
                abs_path = max(candidates, key=lambda p: os.path.getmtime(p))
        except Exception:
            pass

    if not abs_path or not os.path.exists(abs_path) or os.path.isdir(abs_path):
        return f"File not found: {abs_path}", 404

    def _truthy(v: str | None) -> bool:
        return str(v or "").strip().lower() in ("1", "true", "yes", "y", "on")

    # Resolve plan + limits for this export.
    plan_type = get_user_plan_type(current_user)
    plan_limits = get_plan_limits(plan_type)
    want_quality = _truthy(request.args.get("quality"))
    hd_enabled = bool(plan_limits.get("hd_enabled"))
    watermark_required = bool(plan_limits.get("watermark"))
    is_trial_plan = plan_type == "trial"
    is_paid_plan = plan_type in ("starter", "pro", "industry")

    # Trial: enforce 3-clip export limit (server-side authoritative).
    if is_trial_plan and not _open_testing_mode_enabled():
        try:
            used = int(getattr(current_user, "trial_clip_exports", 0) or 0)
        except Exception:
            used = 0
        if used >= FREE_CLIP_LIMIT:
            qa_event(
                "download_blocked_trial_limit",
                user_id=getattr(current_user, "id", None),
                clip_id=clip_id,
                used=used,
            )
            # Return JSON response that triggers pricing modal on frontend
            return jsonify({"action": "show_pricing_modal"}), 200

    # HD export (quality mode) is only available when explicitly enabled for the plan.
    if want_quality and not hd_enabled:
        qa_event(
            "download_blocked_quality_plan",
            user_id=getattr(current_user, "id", None),
            clip_id=clip_id,
            plan_type=plan_type,
        )
        return "HD export is available on Pro and Industry plans.", 403

    def _clamp(n: int, lo: int, hi: int) -> int:
        return max(lo, min(hi, int(n)))

    def _probe_dims(video_path: str) -> tuple[int, int] | None:
        if shutil.which("ffprobe") is None:
            return None
        try:
            p = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=width,height",
                    "-of",
                    "json",
                    video_path,
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            info = json.loads(p.stdout or "{}")
            streams = info.get("streams") or []
            if not streams:
                return None
            w = int(streams[0].get("width") or 0)
            h = int(streams[0].get("height") or 0)
            if w > 0 and h > 0:
                return (w, h)
        except Exception:
            return None
        return None

    def _probe_duration(video_path: str) -> float | None:
        if shutil.which("ffprobe") is None:
            return None
        try:
            p = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    video_path,
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            val = (p.stdout or "").strip()
            if not val:
                return None
            dur = float(val)
            return dur if dur > 0 else None
        except Exception:
            return None

    def _watermark_asset() -> str | None:
        # Priority: watermark.png > logo_icon.png > logo.png
        candidates = [
            os.path.join(app.root_path, "static", "branding", "watermark.png"),
            os.path.join(app.root_path, "static", "branding", "logo_icon.png"),
            os.path.join(app.root_path, "static", "branding", "logo.png"),
        ]
        for p in candidates:
            if os.path.exists(p) and not os.path.isdir(p):
                app.logger.debug("[WATERMARK] Using asset: %s", p)
                return p
        app.logger.warning("[WATERMARK] No branding assets found in static/branding/")
        return None

    def _find_fontfile() -> str | None:
        candidates = [
            os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "segoeuib.ttf"),
            os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "arialbd.ttf"),
            os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "arial.ttf"),
            os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "segoeui.ttf"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/Library/Fonts/Arial.ttf",
        ]
        for p in candidates:
            try:
                if os.path.exists(p) and not os.path.isdir(p):
                    return p
            except Exception:
                pass
        return None

    def _escape_ffmpeg_filter_path(path_value: str) -> str:
        """
        Escape paths for use inside FFmpeg filter strings (e.g. drawtext fontfile=...).
        On Windows, the drive-letter colon must be escaped: C\\:/Windows/Fonts/arial.ttf
        """
        s = str(path_value or "").replace("\\", "/")
        if len(s) >= 2 and s[1] == ":" and s[0].isalpha():
            # FFmpeg filter arguments are parsed in multiple layers; Windows drive colon needs
            # double escaping to survive into the drawtext option parser.
            s = f"{s[0]}\\\\:{s[2:]}"
        return s

    def _cached_path(input_path: str, kind: str, asset_path: str | None, version: str) -> str:
        out_dir = os.path.join(app.root_path, "static", "outputs", kind)
        os.makedirs(out_dir, exist_ok=True)

        try:
            in_m = os.path.getmtime(input_path)
        except Exception:
            in_m = 0.0
        try:
            a_m = os.path.getmtime(asset_path) if asset_path else 0.0
        except Exception:
            a_m = 0.0

        sig = hashlib.sha1(
            f"{input_path}|{in_m}|{asset_path or ''}|{a_m}|{version}".encode("utf-8")
        ).hexdigest()[:12]
        return os.path.join(out_dir, f"clip_{clip_id}_{sig}.mp4")

    def _render_watermark(input_path: str, output_path: str) -> None:
        if shutil.which("ffmpeg") is None:
            raise RuntimeError("ffmpeg not found on PATH")
        if not input_path or not os.path.exists(input_path) or os.path.isdir(input_path):
            raise FileNotFoundError(f"input video not found: {input_path}")

        dims = _probe_dims(input_path) or (1920, 1080)
        width, height = dims
        # Premium cinematic watermark placement (subtle imprint)
        # - centered at bottom
        # - bottom offset: ~4–5% of height (never touches edge)
        # - size: 16% of width, clamped to [100..200] for better visibility
        pad_y = max(20, int(height * 0.05))
        wm_w = _clamp(int(width * 0.16), 100, 200)
        # Make a compact horizontal lockup: [logo][HOTSHORT]
        wm_h = max(32, int(round(wm_w * 0.35)))
        logo_w = max(28, int(round(wm_h * 0.95)))
        pad_x = max(8, int(round(wm_h * 0.18)))
        font_size = max(14, int(round(wm_h * 0.6)))

        asset = _watermark_asset()
        fontfile = _find_fontfile()

        def _run_ffmpeg(cmd: list[str]) -> None:
            try:
                subprocess.run(
                    cmd,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=180,
                )
            except subprocess.TimeoutExpired as e:
                ex = RuntimeError("ffmpeg watermark timed out")
                setattr(ex, "cmd", cmd)
                setattr(ex, "stderr", (getattr(e, "stderr", None) or "") + "\n(timeout)")
                raise ex
            except subprocess.CalledProcessError as e:
                ex = RuntimeError(f"ffmpeg watermark failed (exit={e.returncode})")
                setattr(ex, "cmd", cmd)
                setattr(ex, "stderr", (e.stderr or ""))
                raise ex

        fd, tmp_path = tempfile.mkstemp(prefix="wm_", suffix=".mp4", dir=os.path.dirname(output_path))
        os.close(fd)
        try:
            attempts: list[list[str]] = []
            if asset and os.path.exists(asset) and not os.path.isdir(asset):
                # Professional watermark imprint (0.18–0.25) - more visible but still elegant
                # across all content types and player overlays.
                try:
                    wm_alpha = float(os.environ.get("HS_WATERMARK_ALPHA", "0.22") or "0.22")
                except Exception:
                    wm_alpha = 0.22
                wm_alpha = max(0.18, min(0.25, wm_alpha))
                shadow_alpha = max(0.04, min(0.10, wm_alpha * 0.4))

                # Fade in for the first 0.8s; optional fade out during last 0.5s.
                dur = _probe_duration(input_path)
                fade = "fade=t=in:st=0:d=0.8:alpha=1"
                if dur and dur > 1.6:
                    st_out = max(0.0, float(dur) - 0.5)
                    fade = f"{fade},fade=t=out:st={st_out:.3f}:d=0.5:alpha=1"

                # Normal blend + reduced alpha (0.12–0.18) for cinematic imprint.
                # Soft shadow: slight blur, very low opacity, no glow.
                x = "(W-w)/2"
                y = f"H-h-{pad_y}"
                safe_font = _escape_ffmpeg_filter_path(fontfile) if fontfile else ""

                def _lockup_draw(label_out: str) -> str:
                    if safe_font:
                        return (
                            f"[b1]drawtext=fontfile={safe_font}:text=Made with HotShort:"
                            f"fontcolor=#FFD700@1.0:fontsize={font_size}:"
                            f"x={logo_w}+{pad_x}:y=(h-th)/2:"
                            f"shadowcolor=#000000@0.30:shadowx=2:shadowy=2:"
                            f"borderw=1:bordercolor=#FFFFFF@0.15[{label_out}];"
                        )
                    return (
                        f"[b1]drawtext=text=Made with HotShort:"
                        f"fontcolor=#FFD700@1.0:fontsize={font_size}:"
                        f"x={logo_w}+{pad_x}:y=(h-th)/2:"
                        f"shadowcolor=#000000@0.30:shadowx=2:shadowy=2:"
                        f"borderw=1:bordercolor=#FFFFFF@0.15[{label_out}];"
                    )

                # Attempt 1: cinematic lockup + subtle golden shine sweep (first ~1.2s).
                # If this fails for any reason, we gracefully degrade to a non-shine version.
                #
                # Premium shiny effect disabled by default (requires advanced FFmpeg support).
                # Can be enabled with: HS_WATERMARK_SHINE=1
                enable_shine = str(os.environ.get("HS_WATERMARK_SHINE", "0") or "0").strip().lower() in (
                    "1",
                    "true",
                    "yes",
                    "y",
                    "on",
                )
                if enable_shine:
                    filt_shine = (
                        f"color=c=black@0.0:s={wm_w}x{wm_h}:r=30,format=rgba[base];"
                        f"[1:v]format=rgba,scale={logo_w}:{wm_h}[logo];"
                        f"[base][logo]overlay=x=0:y=0:format=auto[b1];"
                        + _lockup_draw("b2")
                        + (
                            f"color=c=#FFD36A@1.0:s={wm_w}x{wm_h}:r=30,format=rgba,"
                            # FFmpeg 8 requires a luminance/RGB expression when using geq; alpha-only fails.
                            "geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
                            "a='if(lte(T,1.2),if(lte(abs((X+Y)-(T*(W+H)/1.2)),16),110,0),0)',"
                            "gblur=sigma=6[shine];"
                            "[b2][shine]blend=all_mode=screen:all_opacity=0.22[wm0];"
                        )
                        + (
                            f"[wm0]colorchannelmixer=aa={wm_alpha:.3f}[wm];"
                            f"[wm0]colorchannelmixer=rr=0:gg=0:bb=0:aa={shadow_alpha:.3f},gblur=sigma=2.2[sh];"
                            f"[sh][wm]overlay=1:1:format=auto[wmc];"
                            f"[wmc]{fade}[wmf];"
                            f"[0:v][wmf]overlay=x={x}:y={y}:format=auto:shortest=1[v]"
                        )
                    )
                    attempts.append(
                        [
                            "ffmpeg",
                            "-hide_banner",
                            "-nostdin",
                            "-y",
                            "-i",
                            input_path,
                            "-loop",
                            "1",
                            "-i",
                            asset,
                            "-filter_complex",
                            filt_shine,
                            "-map",
                            "[v]",
                            "-map",
                            "0:a?",
                            "-shortest",
                            "-c:v",
                            "libx264",
                            "-preset",
                            "veryfast",
                            "-crf",
                            "21",
                            "-pix_fmt",
                            "yuv420p",
                            "-c:a",
                            "copy",
                            "-movflags",
                            "+faststart",
                            tmp_path,
                        ]
                    )
                    attempts.append(
                        [
                            "ffmpeg",
                            "-hide_banner",
                            "-nostdin",
                            "-y",
                            "-i",
                            input_path,
                            "-loop",
                            "1",
                            "-i",
                            asset,
                            "-filter_complex",
                            filt_shine,
                            "-map",
                            "[v]",
                            "-map",
                            "0:a?",
                            "-shortest",
                            "-c:v",
                            "libx264",
                            "-preset",
                            "veryfast",
                            "-crf",
                            "21",
                            "-pix_fmt",
                            "yuv420p",
                            "-c:a",
                            "aac",
                            "-b:a",
                            "160k",
                            "-movflags",
                            "+faststart",
                            tmp_path,
                        ]
                    )

                # Attempt 2: lockup (logo + HOTSHORT) without shine (more robust).
                filt_simple = (
                    f"color=c=black@0.0:s={wm_w}x{wm_h}:r=30,format=rgba[base];"
                    f"[1:v]format=rgba,scale={logo_w}:{wm_h}[logo];"
                    f"[base][logo]overlay=x=0:y=0:format=auto[b1];"
                    + _lockup_draw("wm0")
                    + (
                        f"[wm0]colorchannelmixer=aa={wm_alpha:.3f}[wm];"
                        f"[wm0]colorchannelmixer=rr=0:gg=0:bb=0:aa={shadow_alpha:.3f},gblur=sigma=2.2[sh];"
                        f"[sh][wm]overlay=1:1:format=auto[wmc];"
                        f"[wmc]{fade}[wmf];"
                        f"[0:v][wmf]overlay=x={x}:y={y}:format=auto:shortest=1[v]"
                    )
                )
                attempts.append(
                    [
                        "ffmpeg",
                        "-hide_banner",
                        "-nostdin",
                        "-y",
                        "-i",
                        input_path,
                        "-loop",
                        "1",
                        "-i",
                        asset,
                        "-filter_complex",
                        filt_simple,
                        "-map",
                        "[v]",
                        "-map",
                        "0:a?",
                        "-shortest",
                        "-c:v",
                        "libx264",
                        "-preset",
                        "veryfast",
                        "-crf",
                        "21",
                        "-pix_fmt",
                        "yuv420p",
                        "-c:a",
                        "copy",
                        "-movflags",
                        "+faststart",
                        tmp_path,
                    ]
                )
                attempts.append(
                    [
                        "ffmpeg",
                        "-hide_banner",
                        "-nostdin",
                        "-y",
                        "-i",
                        input_path,
                        "-loop",
                        "1",
                        "-i",
                        asset,
                        "-filter_complex",
                        filt_simple,
                        "-map",
                        "[v]",
                        "-map",
                        "0:a?",
                        "-shortest",
                        "-c:v",
                        "libx264",
                        "-preset",
                        "veryfast",
                        "-crf",
                        "21",
                        "-pix_fmt",
                        "yuv420p",
                        "-c:a",
                        "aac",
                        "-b:a",
                        "160k",
                        "-movflags",
                        "+faststart",
                        tmp_path,
                    ]
                )

                # Attempt 3: logo-only (last-resort watermark, still keeps branding).
                filt_logo = (
                    f"[1:v]format=rgba,scale={wm_w}:-1[wm0];"
                    f"[wm0]colorchannelmixer=aa={wm_alpha:.3f}[wm];"
                    f"[wm0]colorchannelmixer=rr=0:gg=0:bb=0:aa={shadow_alpha:.3f},gblur=sigma=2.2[sh];"
                    f"[sh][wm]overlay=1:1:format=auto[wmc];"
                    f"[wmc]{fade}[wmf];"
                    f"[0:v][wmf]overlay=x={x}:y={y}:format=auto:shortest=1[v]"
                )
                attempts.append(
                    [
                        "ffmpeg",
                        "-hide_banner",
                        "-nostdin",
                        "-y",
                        "-i",
                        input_path,
                        "-loop",
                        "1",
                        "-i",
                        asset,
                        "-filter_complex",
                        filt_logo,
                        "-map",
                        "[v]",
                        "-map",
                        "0:a?",
                        "-shortest",
                        "-c:v",
                        "libx264",
                        "-preset",
                        "veryfast",
                        "-crf",
                        "21",
                        "-pix_fmt",
                        "yuv420p",
                        "-c:a",
                        "copy",
                        "-movflags",
                        "+faststart",
                        tmp_path,
                    ]
                )
                attempts.append(
                    [
                        "ffmpeg",
                        "-hide_banner",
                        "-nostdin",
                        "-y",
                        "-i",
                        input_path,
                        "-loop",
                        "1",
                        "-i",
                        asset,
                        "-filter_complex",
                        filt_logo,
                        "-map",
                        "[v]",
                        "-map",
                        "0:a?",
                        "-shortest",
                        "-c:v",
                        "libx264",
                        "-preset",
                        "veryfast",
                        "-crf",
                        "21",
                        "-pix_fmt",
                        "yuv420p",
                        "-c:a",
                        "aac",
                        "-b:a",
                        "160k",
                        "-movflags",
                        "+faststart",
                        tmp_path,
                    ]
                )
            else:
                # Premium text fallback - elegant and professional branding
                dur = _probe_duration(input_path)
                fade = "fade=t=in:st=0:d=0.8:alpha=1"
                if dur and dur > 1.6:
                    st_out = max(0.0, float(dur) - 0.5)
                    fade = f"{fade},fade=t=out:st={st_out:.3f}:d=0.5:alpha=1"

                wm_text = "HOTSHORT"
                draw = (
                    "drawtext="
                    f"text='{wm_text}':"
                    "fontcolor=#FFD700@0.20:"
                    "shadowcolor=#000000@0.40:shadowx=2:shadowy=2:"
                    "borderw=2:bordercolor=#FFFFFF@0.10:"
                    "fontsize=h*0.032:"
                    f"x=(w-tw)/2:y=h-th-{pad_y}"
                )
                if fontfile:
                    safe_font = _escape_ffmpeg_filter_path(fontfile)
                    draw = draw.replace("drawtext=", f"drawtext=fontfile={safe_font}:", 1)
                attempts.append(
                    [
                        "ffmpeg",
                        "-hide_banner",
                        "-nostdin",
                        "-y",
                        "-i",
                        input_path,
                        "-vf",
                        f"{draw},{fade}",
                        "-map",
                        "0:v:0",
                        "-map",
                        "0:a?",
                        "-c:v",
                        "libx264",
                        "-preset",
                        "veryfast",
                        "-crf",
                        "21",
                        "-pix_fmt",
                        "yuv420p",
                        "-c:a",
                        "copy",
                        "-movflags",
                        "+faststart",
                        tmp_path,
                    ]
                )
                attempts.append(
                    [
                        "ffmpeg",
                        "-hide_banner",
                        "-nostdin",
                        "-y",
                        "-i",
                        input_path,
                        "-vf",
                        f"{draw},{fade}",
                        "-map",
                        "0:v:0",
                        "-map",
                        "0:a?",
                        "-c:v",
                        "libx264",
                        "-preset",
                        "veryfast",
                        "-crf",
                        "21",
                        "-pix_fmt",
                        "yuv420p",
                        "-c:a",
                        "aac",
                        "-b:a",
                        "160k",
                        "-movflags",
                        "+faststart",
                        tmp_path,
                    ]
                )

            last_exc: Exception | None = None
            for cmd in attempts:
                try:
                    _run_ffmpeg(cmd)
                    if not os.path.exists(tmp_path) or os.path.isdir(tmp_path) or os.path.getsize(tmp_path) <= 0:
                        raise RuntimeError("ffmpeg produced empty watermark output")
                    os.replace(tmp_path, output_path)
                    return
                except Exception as e:
                    last_exc = e
                    try:
                        if os.path.exists(tmp_path):
                            os.remove(tmp_path)
                    except Exception:
                        pass
                    continue

            if last_exc is not None:
                raise last_exc
            raise RuntimeError("watermark pipeline produced no command attempts")
        finally:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass

    def _render_quality(input_path: str, output_path: str) -> None:
        if shutil.which("ffmpeg") is None:
            raise RuntimeError("ffmpeg not found on PATH")

        fd, tmp_path = tempfile.mkstemp(prefix="q_", suffix=".mp4", dir=os.path.dirname(output_path))
        os.close(fd)
        try:
            cmd = [
                "ffmpeg",
                "-y",
                "-i",
                input_path,
                "-c:v",
                "libx264",
                "-preset",
                "slow",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "160k",
                "-movflags",
                "+faststart",
                tmp_path,
            ]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            os.replace(tmp_path, output_path)
        finally:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass

    # Plans without watermark (Pro / Industry): direct export, optional HD.
    if not watermark_required:
        out_path = abs_path
        if want_quality and hd_enabled:
            out_path = _cached_path(abs_path, "quality", None, "q_v1")
            if not os.path.exists(out_path):
                try:
                    _render_quality(abs_path, out_path)
                except Exception as e:
                    return f"Quality export failed: {e}", 500
        try:
            qa_event(
                "download_success_server",
                user_id=getattr(current_user, "id", None),
                clip_id=clip_id,
                paid=is_paid_plan,
                watermarked=False,
                quality=want_quality,
                plan_type=plan_type,
            )
            return send_file(out_path, as_attachment=True)
        except Exception:
            app.logger.exception("[DOWNLOAD] send_file failed for %s", out_path)
            qa_event(
                "download_failed_server",
                user_id=getattr(current_user, "id", None),
                clip_id=clip_id,
            )
            return jsonify({"error": "download_failed"}), 500

    # Plans with enforced watermark (Trial / Starter and any watermark-on tiers).
    asset = _watermark_asset()
    out_path = _cached_path(abs_path, "watermarked", asset, "wm_v9")
    chosen_path = abs_path
    watermark_ok = False
    
    app.logger.info("[DOWNLOAD] Watermark processing: required=%s, plan=%s, asset=%s", watermark_required, plan_type, asset or "none")
    
    try:
        if not os.path.exists(out_path):
            app.logger.info("[DOWNLOAD] Generating premium watermark: %s -> %s", abs_path, out_path)
            _render_watermark(abs_path, out_path)
        watermark_ok = os.path.exists(out_path) and not os.path.isdir(out_path) and os.path.getsize(out_path) > 0
        if watermark_ok:
            app.logger.info("[DOWNLOAD] Premium watermark applied successfully: %s (size=%d)", out_path, os.path.getsize(out_path))
        else:
            app.logger.warning("[DOWNLOAD] Watermark generation failed or produced empty file")
    except Exception as e:
        cmd = getattr(e, "cmd", None)
        stderr = getattr(e, "stderr", "") or ""
        app.logger.error("[DOWNLOAD] Premium watermarking failed; blocking free-tier export for clip_id=%s", clip_id)
        if cmd:
            app.logger.error("[DOWNLOAD] Watermark cmd: %s", " ".join(map(str, cmd)))
        if stderr:
            app.logger.error("[DOWNLOAD] Watermark stderr:\n%s", stderr)
        app.logger.exception("[DOWNLOAD] Watermark exception for %s", abs_path)
        watermark_ok = False

    if watermark_ok:
        chosen_path = out_path
        app.logger.info("[DOWNLOAD] Watermark applied for clip_id=%s -> %s", clip_id, out_path)
    else:
        qa_event(
            "download_blocked_watermark_failed",
            user_id=getattr(current_user, "id", None),
            clip_id=clip_id,
        )
        return jsonify({"error": "watermark_failed"}), 503

    # If we reach here and it's a trial export, increment the trial clip counter.
    if is_trial_plan and not _open_testing_mode_enabled():
        try:
            used = int(getattr(current_user, "trial_clip_exports", 0) or 0)
            if used < FREE_CLIP_LIMIT:
                current_user.trial_clip_exports = used + 1
                db.session.commit()
        except Exception:
            db.session.rollback()
            app.logger.exception("[DOWNLOAD] Failed to increment trial_clip_exports")

    try:
        print("[DOWNLOAD]", chosen_path)
    except Exception:
        pass
    try:
        qa_event(
            "download_success_server",
            user_id=getattr(current_user, "id", None),
            clip_id=clip_id,
            paid=is_paid_plan,
            watermarked=True,
            quality=want_quality,
            plan_type=plan_type,
        )
        return send_file(chosen_path, as_attachment=True)
    except Exception:
        app.logger.exception("[DOWNLOAD] send_file failed for %s", chosen_path)
        qa_event(
            "download_failed_server",
            user_id=getattr(current_user, "id", None),
            clip_id=clip_id,
        )
        return jsonify({"error": "download_failed"}), 500

@app.route("/download-by-path")
@login_required
def download_by_path():
    raw_clip_url = (request.args.get("clip_url") or "").strip()
    if not raw_clip_url:
        return "Missing clip_url", 400

    clip_url = raw_clip_url.split("?", 1)[0].replace("\\", "/")
    if "://" in clip_url:
        return "Invalid clip_url", 400

    rel_path = clip_url.lstrip("/")
    rel_path = os.path.normpath(rel_path).replace("\\", "/")
    if not rel_path.startswith("static/outputs/"):
        return "Invalid clip_url", 400
    if rel_path.startswith("../") or "/../" in rel_path:
        return "Invalid clip_url", 400

    clip = (
        Clip.query.filter_by(user_id=current_user.id, file_path=rel_path)
        .order_by(Clip.id.desc())
        .first()
    )
    if not clip:
        clip = (
            Clip.query.filter_by(user_id=current_user.id, file_path="/" + rel_path)
            .order_by(Clip.id.desc())
            .first()
        )
    if not clip:
        return "Clip not found", 404

    return redirect(url_for("download_clip", clip_id=clip.id))

@app.route("/output/<path:filename>")
def serve_output(filename):
    out_file = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(out_file):
        return "File not found", 404
    return send_file(out_file, mimetype="video/mp4", as_attachment=False)

# =====================================================
# 🚀 LAUNCH APP
# =====================================================
# =====================================================
# 🔧 FUNCTION: Generate clip from YouTube or cached file

# =====================================================

import subprocess

def generate_clip_for_job(video_path, start, end):
    """
    Ultra-fast FFmpeg clipper using stream copy (no re-encoding)
    """
    try:
        output_dir = "static/outputs"
        os.makedirs(output_dir, exist_ok=True)

        filename = f"clip_{start}_{end}_{uuid.uuid4().hex[:6]}.mp4"
        output_path = os.path.join(output_dir, filename)

        cmd = [
            "ffmpeg",
            "-y",
            "-ss", str(start),
            "-to", str(end),
            "-i", video_path,
            "-c", "copy",    # 🔥 SUPER FAST — no re-encode
            output_path
        ]

        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        return output_path

    except Exception as e:
        print("[FFMPEG ERROR]", e)
        raise


if __name__ == "__main__":
    # When running via `python app.py`, use PORT if provided (defaults to 10000).
    # When running under Gunicorn, this block is skipped.
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
