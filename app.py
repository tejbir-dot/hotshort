import os
import re
import uuid
import socket
import time
import tempfile
import queue
import threading
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
import hashlib
import zipfile
import shutil
from urllib.parse import urlparse, urljoin
from typing import TYPE_CHECKING, List, Dict
from dotenv import load_dotenv

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
load_dotenv(dotenv_path=os.path.join(BASE_DIR, ".env"))

import flask
from flask import Flask, render_template, request, redirect, url_for, Response, send_file, session, flash, jsonify, after_this_request, g, current_app
from flask_login import LoginManager, current_user, login_required, login_user
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
from models.user import db, User, Clip, Job, FreeClipClaim

# 🌟 APP CONFIGURATION
# =====================================================
app = Flask(__name__)

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

try:
    HS_RUNPOD_POLL_INTERVAL_SECONDS = int(os.getenv("HS_RUNPOD_POLL_INTERVAL_SECONDS", "2") or 2)
except Exception:
    HS_RUNPOD_POLL_INTERVAL_SECONDS = 2

try:
    HS_RUNPOD_DOWNLOAD_POLL_TIMEOUT_SECONDS = int(os.getenv("HS_RUNPOD_DOWNLOAD_POLL_TIMEOUT_SECONDS", "300") or 300)
except Exception:
    HS_RUNPOD_DOWNLOAD_POLL_TIMEOUT_SECONDS = 300

try:
    HS_RUNPOD_ANALYSIS_POLL_TIMEOUT_SECONDS = int(os.getenv("HS_RUNPOD_ANALYSIS_POLL_TIMEOUT_SECONDS", "600") or 600)
except Exception:
    HS_RUNPOD_ANALYSIS_POLL_TIMEOUT_SECONDS = 600

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
from effects.video_pipeline import generate_clip_for_job
from routes.auth import auth, build_post_login_redirect  # 👈 all auth routes now separated
from flask_dance.contrib.google import make_google_blueprint, google
from flask_dance.consumer import oauth_authorized, oauth_before_login, oauth_error
from oauthlib.oauth2.rfc6749.errors import MissingCodeError, MismatchingStateError
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

# RunPod controller for on-demand GPU pod management
try:
    from runpod_controller import start_pod, stop_pod, wait_until_ready
    RUNPOD_AVAILABLE = True
except ImportError:
    RUNPOD_AVAILABLE = False

# RunPod mode: serverless (default) or pod (direct pod lifecycle)
RUNPOD_MODE = os.getenv("RUNPOD_MODE", "serverless").strip().lower()

# Local worker URL (for hybrid dev setup with ngrok)
# Example: https://abc123.ngrok-free.app/run
# Set via env var: LOCAL_WORKER_URL=https://...ngrok-free.app/run
LOCAL_WORKER_URL = os.getenv("LOCAL_WORKER_URL", "").strip()

# Helper to build the correct RunPod endpoint URL per mode
def _runpod_task_url(endpoint: str) -> str:
    # Always use the asynchronous /run endpoint. The app architecture polls for completion.
    # /runsync can cause 404 errors if the pod is still booting and no workers are registered.
    if RUNPOD_MODE == "pod":
        return f"https://{endpoint}-8000.proxy.runpod.net/run"
    return f"https://api.runpod.ai/v2/{endpoint}/run"

def _runpod_status_url(endpoint: str, run_id: str) -> str:
    if RUNPOD_MODE == "pod":
        return f"https://{endpoint}-8000.proxy.runpod.net/status/{run_id}"
    return f"https://api.runpod.ai/v2/{endpoint}/status/{run_id}"

# RunPod GPU integration functions

def _cancel_runpod_job(endpoint: str, run_id: str, headers: dict) -> bool:
    """Attempt to cancel a queued RunPod serverless job. Returns True on success."""
    try:
        import requests as _req
        cancel_url = f"https://api.runpod.ai/v2/{endpoint}/cancel/{run_id}"
        resp = _req.post(cancel_url, headers=headers, timeout=15)
        log.info("[RUNPOD] cancel %s -> %s %s", run_id, resp.status_code, resp.text[:120])
        return resp.status_code in (200, 204)
    except Exception as e:
        log.warning("[RUNPOD] cancel request failed: %s", e)
        return False


# How long (seconds) a job may stay IN_QUEUE before we cancel and resubmit once.
try:
    _HS_RUNPOD_QUEUE_STUCK_RESUBMIT_S = int(
        os.getenv("HS_RUNPOD_QUEUE_STUCK_RESUBMIT_S", "180") or 180
    )
except Exception:
    _HS_RUNPOD_QUEUE_STUCK_RESUBMIT_S = 180


def _wait_for_runpod_completion(
    *,
    endpoint: str,
    headers: dict,
    initial_data: dict,
    request_url: str,
    request_payload: dict,
    timeout: int,
    task_label: str,
    poll_timeout_s: int,
    poll_interval_s: int = HS_RUNPOD_POLL_INTERVAL_SECONDS,
):
    """Poll RunPod until the async job reaches a terminal state.

    Cold-start handling: if the job stays IN_QUEUE past
    HS_RUNPOD_QUEUE_STUCK_RESUBMIT_S (default 180 s), cancel it and submit
    a fresh request once.  This recovers from GPU cold-boot races without
    entering an infinite resubmit loop.
    """
    import requests

    data = initial_data or {}
    status = data.get("status")
    run_id = data.get("id") or data.get("run_id")
    log.info("[RUNPOD] %s STATUS: %s (run_id=%s)", task_label, status, run_id)

    start_polling_time = time.time()
    _resubmitted = False            # guard: resubmit at most once
    _in_queue_since: float | None = None    # wall-clock when we first saw IN_QUEUE

    # Use exponential backoff (cap at 15 s) so we don't hammer the API
    # every 2 s during multi-minute GPU cold starts.
    _cur_poll_interval = max(2, int(poll_interval_s))
    _MAX_POLL_INTERVAL = 15

    while time.time() - start_polling_time < poll_timeout_s:
        if status == "COMPLETED":
            return data
        if status == "FAILED":
            raise RuntimeError(f"RunPod {task_label} failed: FAILED")

        # -- IN_QUEUE stuck-detection + cancel-and-resubmit --
        if status == "IN_QUEUE":
            if _in_queue_since is None:
                _in_queue_since = time.time()
            queue_wait_s = time.time() - _in_queue_since
            log.info(
                "[RUNPOD] %s waiting for job to finish... (status=%s, queue_wait=%.0fs)",
                task_label, status, queue_wait_s,
            )

            if (
                not _resubmitted
                and queue_wait_s >= _HS_RUNPOD_QUEUE_STUCK_RESUBMIT_S
                and RUNPOD_MODE != "pod"    # pod-mode has no serverless cancel API
            ):
                log.warning(
                    "[RUNPOD] %s job %s stuck IN_QUEUE for %.0fs â cancelling and resubmitting",
                    task_label, run_id, queue_wait_s,
                )
                if run_id:
                    _cancel_runpod_job(endpoint, run_id, headers)
                try:
                    resubmit_resp = requests.post(
                        request_url, json=request_payload, headers=headers, timeout=timeout
                    )
                    if resubmit_resp.status_code == 200:
                        data = resubmit_resp.json()
                        status = data.get("status")
                        run_id = data.get("id") or data.get("run_id")
                        _resubmitted = True
                        _in_queue_since = time.time()   # reset queue timer for new job
                        _cur_poll_interval = max(2, int(poll_interval_s))  # reset backoff
                        log.info(
                            "[RUNPOD] %s resubmitted â new run_id=%s status=%s",
                            task_label, run_id, status,
                        )
                        continue
                    else:
                        log.warning(
                            "[RUNPOD] %s resubmit failed: %s %s",
                            task_label, resubmit_resp.status_code, resubmit_resp.text[:200],
                        )
                except Exception as resub_err:
                    log.warning("[RUNPOD] %s resubmit error: %s", task_label, resub_err)
        else:
            # Job picked up by a worker -- reset the in-queue timer
            if _in_queue_since is not None:
                log.info(
                    "[RUNPOD] %s job picked up by worker after %.0fs in queue",
                    task_label, time.time() - _in_queue_since,
                )
                _in_queue_since = None
            log.info("[RUNPOD] %s waiting for job to finish... (status=%s)", task_label, status)

        time.sleep(_cur_poll_interval)
        # Back off gradually -- cold starts can take minutes
        _cur_poll_interval = min(_cur_poll_interval * 2, _MAX_POLL_INTERVAL)

        if run_id:
            status_url = _runpod_status_url(endpoint, run_id)
            resp = requests.get(status_url, headers=headers, timeout=60)
        else:
            resp = requests.post(request_url, json=request_payload, headers=headers, timeout=timeout)

        if resp.status_code != 200:
            raise RuntimeError(f"RunPod {task_label} failed: {resp.status_code} - {resp.text}")

        data = resp.json()
        status = data.get("status")
        run_id = run_id or data.get("id") or data.get("run_id")
        log.info("[RUNPOD] %s STATUS: %s (run_id=%s)", task_label, status, run_id)

    raise RuntimeError(f"RunPod {task_label} failed (non-completed status): {status}")


def send_transcription_request(youtube_url: str) -> List[Dict]:
    """Send YouTube URL to RunPod GPU for download, audio extraction, and transcription."""
    import requests

    endpoint = os.getenv("RUNPOD_ENDPOINT_ID")
    if not endpoint:
        raise RuntimeError("RUNPOD_ENDPOINT_ID not configured")

    url = _runpod_task_url(endpoint)

    # Prepare request with YouTube URL + cloud provider config for worker upload
    data = {
        'task': 'transcribe_youtube',
        'youtube_url': youtube_url,
        'model': os.environ.get("HS_TRANSCRIPT_MODEL", "base"),
        'include_visual': True,
        'cloud_provider': {
            'provider': 'cloudinary',
            'cloud_name': os.environ.get('CLOUDINARY_CLOUD_NAME'),
            'api_key': os.environ.get('CLOUDINARY_API_KEY'),
            'api_secret': os.environ.get('CLOUDINARY_API_SECRET'),
        }
    }
    payload = {"input": data}

    headers = {
        'Authorization': f"Bearer {os.environ.get('RUNPOD_API_KEY')}",
        'Content-Type': 'application/json'
    }

    log.info("[RUNPOD] Sending transcription request")
    response = requests.post(url, json=payload, headers=headers, timeout=600)  # Increased timeout for download

    if response.status_code != 200:
        raise RuntimeError(f"RunPod transcription failed: {response.status_code} - {response.text}")

    result = response.json()
    log.info("[RUNPOD] transcription response: %s", result)
    result = _wait_for_runpod_completion(
        endpoint=endpoint,
        headers=headers,
        initial_data=result,
        request_url=url,
        request_payload=payload,
        timeout=600,
        task_label="transcription",
        poll_timeout_s=HS_RUNPOD_ANALYSIS_POLL_TIMEOUT_SECONDS,
    )

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

    url = _runpod_task_url(endpoint)

    # Prepare request data + cloud provider config for worker upload
    data = {
        'task': 'analyze',
        'transcript': transcript,
        'video_metadata': {
            'duration': get_video_duration(video_path),
            'path': video_path
        },
        'cloud_provider': {
            'provider': 'cloudinary',
            'cloud_name': os.environ.get('CLOUDINARY_CLOUD_NAME'),
            'api_key': os.environ.get('CLOUDINARY_API_KEY'),
            'api_secret': os.environ.get('CLOUDINARY_API_SECRET'),
        }
    }
    payload = {"input": data}

    headers = {
        'Authorization': f"Bearer {os.environ.get('RUNPOD_API_KEY')}",
        'Content-Type': 'application/json'
    }

    log.info("[RUNPOD] Sending analysis request to GPU endpoint...")
    response = requests.post(url, json=payload, headers=headers, timeout=300)

    if response.status_code != 200:
        raise RuntimeError(f"RunPod analysis failed: {response.status_code} - {response.text}")

    result = response.json()
    log.info("[RUNPOD] analysis response: %s", result)
    result = _wait_for_runpod_completion(
        endpoint=endpoint,
        headers=headers,
        initial_data=result,
        request_url=url,
        request_payload=payload,
        timeout=300,
        task_label="analysis",
        poll_timeout_s=HS_RUNPOD_ANALYSIS_POLL_TIMEOUT_SECONDS,
    )

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
MAX_CONCURRENT_ANALYZE_PER_USER = max(
    1,
    min(8, int(os.environ.get("HS_MAX_CONCURRENT_ANALYZE_PER_USER", "2") or 2)),
)

# default worker profile when /v2/analyze does not provide one
DEFAULT_WORKER_PROFILE = os.environ.get("HS_PROFILE_DEFAULT", "balanced").strip().lower()

def _acquire_analyze_lock_for_user(user_id):
    key = str(user_id)
    with _analyze_locks_guard:
        lock = _analyze_locks.get(key)
        if lock is None:
            lock = threading.BoundedSemaphore(MAX_CONCURRENT_ANALYZE_PER_USER)
            _analyze_locks[key] = lock
    if lock.acquire(blocking=False):
        return lock
    return None

def _analyze_file_lock_path(user_id, slot_idx=None) -> str:
    base = f"hs_analyze_user_{str(user_id)}"
    if slot_idx is None:
        return os.path.join(tempfile.gettempdir(), f"{base}.lock")
    return os.path.join(tempfile.gettempdir(), f"{base}.{int(slot_idx)}.lock")

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
    Cross-process slot lock to cap same-user analyze concurrency across
    multiple processes (e.g., debug reloader / multi-process serving).
    """
    stale_after_s = int(os.environ.get("HS_ANALYZE_LOCK_STALE_SECONDS", "900") or 900)
    for slot_idx in range(MAX_CONCURRENT_ANALYZE_PER_USER):
        lock_path = _analyze_file_lock_path(user_id, slot_idx)

        try:
            if os.path.exists(lock_path):
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
                os.write(
                    fd,
                    f"pid={os.getpid()} slot={slot_idx} ts={time.time():.3f}\n".encode("utf-8", "ignore"),
                )
            finally:
                os.close(fd)
            return lock_path
        except FileExistsError:
            continue
        except Exception:
            continue
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
        reencode_preset = os.environ.get("HS_CLIP_REENCODE_PRESET", "fast").strip() or "fast"
        reencode_crf = int(os.environ.get("HS_CLIP_REENCODE_CRF", "18") or 18)
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
                model_name=os.environ.get("HS_TRANSCRIPT_MODEL", "base"),
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
        # Support both the canonical route contract (`start`/`end`) and the
        # orchestrator payload shape currently seen in logs (`start_time`/`end_time`).
        start = m.get("start", m.get("start_time"))
        end = m.get("end", m.get("end_time"))

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

app = Flask(__name__)

app.config.from_object('settings.Config')
app.secret_key = app.config["SECRET_KEY"]
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)
CORS(app, origins=["*"])
validate_runtime_profile(logging.getLogger(__name__))

external_base_url = (app.config.get("EXTERNAL_BASE_URL") or "").strip().rstrip("/")
if external_base_url:
    parsed_external_url = urlparse(external_base_url)
    if parsed_external_url.scheme in ("http", "https") and parsed_external_url.netloc:
        app.config["EXTERNAL_BASE_URL"] = external_base_url
        app.config["PREFERRED_URL_SCHEME"] = parsed_external_url.scheme
        # Do not pin SERVER_NAME from EXTERNAL_BASE_URL.
        # Flask will otherwise reject valid requests coming from ngrok or other
        # temporary hosts with 404s when the Host header differs from the local
        # development URL. Keep EXTERNAL_BASE_URL only as an outbound URL hint.
    else:
        app.logger.warning(
            "[OAUTH-DEBUG] Ignoring invalid EXTERNAL_BASE_URL=%r. Expected format: http(s)://host[:port]",
            external_base_url,
        )
        app.config["EXTERNAL_BASE_URL"] = ""

backend_url = (app.config.get("BACKEND_URL") or app.config.get("EXTERNAL_BASE_URL") or "").strip().rstrip("/")
app.config["BACKEND_URL"] = backend_url
frontend_url = (app.config.get("FRONTEND_URL") or "").strip().rstrip("/")
app.config["FRONTEND_URL"] = frontend_url
public_base_url = (
    frontend_url
    or external_base_url
    or backend_url
).strip().rstrip("/")
app.config["PUBLIC_BASE_URL"] = public_base_url
# IMPORTANT:
# Only force OAuth callback base URL when explicitly provided via env/config.
# Falling back to EXTERNAL_BASE_URL/BACKEND_URL/FRONTEND_URL breaks local dev when those
# are set to production domains in `.env`.
oauth_public_base_url = (app.config.get("OAUTH_PUBLIC_BASE_URL") or "").strip().rstrip("/")
app.config["OAUTH_PUBLIC_BASE_URL"] = oauth_public_base_url

from flask_cors import CORS
CORS(
    app,
    supports_credentials=True,
    origins=[
        frontend_url, # Use the dynamically configured frontend URL
        "https://hotshort.vercel.app" # Keep the hardcoded one if it's always allowed
    ]
)


def _origin_tuple(url_value):
    parsed = urlparse((url_value or "").strip())
    if parsed.scheme in ("http", "https") and parsed.netloc:
        return (parsed.scheme, parsed.netloc)
    return ("", "")


frontend_origin = _origin_tuple(frontend_url)
backend_origin = _origin_tuple(backend_url)
cross_site_frontend = bool(frontend_origin[1] and backend_origin[1] and frontend_origin != backend_origin)
if cross_site_frontend:
    app.config["SESSION_COOKIE_SAMESITE"] = "None"
    app.config["SESSION_COOKIE_SECURE"] = True
    app.config["REMEMBER_COOKIE_SAMESITE"] = "None"
    app.config["REMEMBER_COOKIE_SECURE"] = True

public_origin = _origin_tuple(public_base_url)
if public_origin[0] == "https":
    app.config["SESSION_COOKIE_SECURE"] = True
    app.config["REMEMBER_COOKIE_SECURE"] = True


@app.context_processor
def inject_backend_url():
    return {
        "BACKEND_URL": app.config.get("BACKEND_URL", ""),
        "FRONTEND_URL": app.config.get("FRONTEND_URL", ""),
    }


def _allowed_cors_origin():
    request_origin = (request.headers.get("Origin") or "").strip().rstrip("/")
    frontend = (app.config.get("FRONTEND_URL") or "").strip().rstrip("/")
    if request_origin and frontend and request_origin == frontend:
        return request_origin
    return ""


@app.before_request
def handle_frontend_preflight():
    if request.method == "OPTIONS":
        allowed_origin = _allowed_cors_origin()
        if allowed_origin:
            return ("", 204)

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

app.logger.info("[OAUTH-DEBUG] ENV CLIENT_ID=%r", os.getenv("GOOGLE_OAUTH_CLIENT_ID"))
app.logger.info(
    "[OAUTH-DEBUG] ENV CLIENT_SECRET_SET=%s LEN=%d",
    bool(os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")),
    len(os.getenv("GOOGLE_OAUTH_CLIENT_SECRET") or ""),
)
app.logger.info("[OAUTH-DEBUG] CFG CLIENT_ID=%r", app.config.get("GOOGLE_OAUTH_CLIENT_ID"))
app.logger.info(
    "[OAUTH-DEBUG] CFG CLIENT_SECRET_SET=%s LEN=%d",
    bool(app.config.get("GOOGLE_OAUTH_CLIENT_SECRET")),
    len(app.config.get("GOOGLE_OAUTH_CLIENT_SECRET") or ""),
)
app.logger.info("[OAUTH-DEBUG] CLIENT_ID_SOURCE=%s", client_id_source)
app.logger.info("[OAUTH-DEBUG] CLIENT_SECRET_SOURCE=%s", client_secret_source)
app.logger.info("[OAUTH-DEBUG] PUBLIC_BASE_URL=%r", app.config.get("PUBLIC_BASE_URL"))

from flask_dance.contrib.google import make_google_blueprint, google

google_bp = make_google_blueprint(
    client_id=app.config["GOOGLE_OAUTH_CLIENT_ID"],
    client_secret=app.config["GOOGLE_OAUTH_CLIENT_SECRET"],
    scope=[
        "openid",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile",
    ],
    redirect_to="dashboard",
)
app.register_blueprint(google_bp, url_prefix="/login")


def _google_authorized_absolute_url() -> str:
    public_base_url = (app.config.get("OAUTH_PUBLIC_BASE_URL") or "").strip().rstrip("/")
    authorized_path = url_for("google.authorized", _external=False)
    if public_base_url:
        return f"{public_base_url}{authorized_path}"
    return url_for("google.authorized", _external=True)


def _google_login_override():
    redirect_uri = _google_authorized_absolute_url()
    if redirect_uri.startswith("http://"):
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
    else:
        os.environ.pop("OAUTHLIB_INSECURE_TRANSPORT", None)
    app.logger.info("[OAUTH-DEBUG] GOOGLE_LOGIN_OVERRIDE redirect_uri=%s", redirect_uri)
    google_bp.session.redirect_uri = redirect_uri
    url, state = google_bp.session.authorization_url(
        google_bp.authorization_url,
        state=google_bp.state,
        **google_bp.authorization_url_params,
    )
    flask.session[f"{google_bp.name}_oauth_state"] = state
    oauth_before_login.send(google_bp, url=url)
    response = redirect(url)
    response.set_cookie(
        "hs_google_oauth_state",
        state,
        max_age=600,
        httponly=True,
        secure=bool(app.config.get("SESSION_COOKIE_SECURE")),
        samesite=str(app.config.get("SESSION_COOKIE_SAMESITE") or "Lax"),
        path="/",
    )
    return response


def _google_authorized_override():
    if google_bp.redirect_url:
        next_url = google_bp.redirect_url
    elif google_bp.redirect_to:
        next_url = url_for("dashboard")
    else:
        next_url = "/"

    error = request.args.get("error")
    if error:
        oauth_error.send(
            google_bp,
            error=error,
            error_description=request.args.get("error_description"),
            error_uri=request.args.get("error_uri"),
        )
        return redirect(next_url)

    state_key = f"{google_bp.name}_oauth_state"
    cookie_state = request.cookies.get("hs_google_oauth_state")
    request_state = request.args.get("state")
    session_state = flask.session.pop(state_key, None)
    if not session_state and cookie_state:
        app.logger.warning("[OAUTH-DEBUG] state missing in session; recovering from cookie fallback")
        session_state = cookie_state
    if not session_state and request_state:
        app.logger.warning("[OAUTH-DEBUG] state missing in session/cookie; recovering from callback query")
        session_state = request_state
    if not session_state:
        app.logger.warning("[OAUTH-DEBUG] state missing during callback; restarting google login")
        retry = redirect(url_for("google.login"))
        retry.delete_cookie("hs_google_oauth_state", path="/")
        return retry

    google_bp.session._state = session_state
    google_bp.session.redirect_uri = _google_authorized_absolute_url()
    if google_bp.session.redirect_uri.startswith("http://"):
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
    else:
        os.environ.pop("OAUTHLIB_INSECURE_TRANSPORT", None)
    app.logger.info("[OAUTH-DEBUG] GOOGLE_AUTHORIZED_OVERRIDE redirect_uri=%s", google_bp.session.redirect_uri)
    authorization_response = google_bp.session.redirect_uri
    query_string = request.query_string.decode("utf-8", errors="ignore")
    if query_string:
        authorization_response = f"{authorization_response}?{query_string}"

    try:
        token = google_bp.session.fetch_token(
            google_bp.token_url,
            authorization_response=authorization_response,
            client_secret=google_bp.client_secret,
            **google_bp.token_url_params,
        )
    except MismatchingStateError:
        app.logger.warning("[OAUTH-DEBUG] MismatchingStateError: State mismatch (double-click/stale session). Restarting flow.")
        return redirect(url_for("google.login"))
    except MissingCodeError as e:
        e.args = (
            e.args[0],
            "The redirect request did not contain the expected parameters. Instead I got: {}".format(
                json.dumps(request.args)
            ),
        )
        raise

    results = oauth_authorized.send(google_bp, token=token) or []
    set_token = True
    for _, ret in results:
        if isinstance(ret, (Response, current_app.response_class)):
            return ret
        if ret is False:
            set_token = False

    if set_token:
        try:
            google_bp.token = token
            
            # Fetch user info from Google
            resp = google.get("/oauth2/v2/userinfo")
            if resp.ok:
                user_info = resp.json()
                email = user_info.get("email")
                name = user_info.get("name", "")
                picture = user_info.get("picture", "")

                user = User.query.filter_by(email=email).first()
                if not user:
                    user = User(email=email, name=name, profile_pic=picture)
                    db.session.add(user)
                    db.session.commit()

                login_user(user)
                flask.session["user_id"] = user.id
                app.logger.info("[OAUTH-DEBUG] User %s logged in via Google", email)
        except ValueError as error:
            app.logger.warning("OAuth 2 authorization error: %s", str(error))
            oauth_error.send(google_bp, error=error)

    response = redirect(next_url)
    response.delete_cookie("hs_google_oauth_state", path="/")
    return response


app.view_functions["google.login"] = _google_login_override
app.view_functions["google.authorized"] = _google_authorized_override


# ==========================
# ⚙️ DATABASE + LOGIN
# ==========================
db.init_app(app)

def _db_create_all_safe() -> None:
    """
    Create tables if missing, but tolerate multi-worker races (common on SQLite).
    """
    import time
    for attempt in range(5):
        try:
            db.create_all()
            return
        except Exception as e:
            msg = str(e).lower()
            try:
                db.session.rollback()
            except Exception:
                pass
            
            if attempt < 4 and (("already exists" in msg and "table" in msg) or "database is locked" in msg or "operationalerror" in msg):
                time.sleep(1.0)
                continue
            
            try:
                app.logger.warning("[DB-INIT] create_all failed: %s", e)
            except Exception:
                pass
            raise


def _should_auto_create_tables() -> bool:
    explicit = (os.getenv("HS_AUTO_CREATE_TABLES") or "").strip().lower()
    if explicit in ("1", "true", "yes", "on"):
        return True
    if explicit in ("0", "false", "no", "off"):
        return False
    # Avoid extra schema work during Vercel function cold starts unless requested.
    return (os.getenv("VERCEL") or "").strip().lower() not in ("1", "true")



login_manager = LoginManager()
login_manager.login_view = "auth.login"  # ensure redirects go to the auth blueprint's login endpoint
login_manager.login_message = "Please log in to analyze videos."

login_manager.init_app(app)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def _request_wants_json_auth_response() -> bool:
    accept = (request.headers.get("Accept") or "").lower()
    if "application/json" in accept:
        return True
    xrw = (request.headers.get("X-Requested-With") or "").lower()
    if xrw == "xmlhttprequest":
        return True
    sfm = (request.headers.get("Sec-Fetch-Mode") or "").lower()
    sfd = (request.headers.get("Sec-Fetch-Dest") or "").lower()
    if sfm in ("cors", "same-origin") and sfd == "empty":
        return True
    return False


@login_manager.unauthorized_handler
def _handle_unauthorized():
    is_api = request.path.startswith('/api/') or request.path.startswith('/v2/') or request.path == '/analyze'
    template_id = (request.args.get("template_id") or "").strip()
    next_value = (request.full_path or request.path or "/").strip()
    if next_value.endswith("?"):
        next_value = request.path
    if is_api or _request_wants_json_auth_response():
        login_url = url_for("auth.login", next=next_value, template_id=(template_id or None))
        resp = jsonify({
            "ok": False,
            "authenticated": False,
            "error": "Authentication required",
            "login_url": login_url,
            "redirect": login_url,
        })
        # Force CORS headers so the browser doesn't block the 401 exception reading
        origin = request.headers.get("Origin")
        if origin:
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp, 401
    return redirect(url_for("auth.login", next=next_value, template_id=(template_id or None)))

# ✅ Register blueprints AFTER all routes are defined inside them
app.register_blueprint(auth, url_prefix="/auth")

# compatibility alias: templates and redirects still point at /login.
@app.route("/login", methods=["GET", "POST"])
def login_alias():
    if request.method == "POST":
        return auth.login()

    # preserve any query args such as next
    return redirect(url_for("auth.login", **request.args))

from routes.feedback import feedback_bp
app.register_blueprint(feedback_bp, url_prefix="/api")
from routes.admin import admin_bp
app.register_blueprint(admin_bp, url_prefix="/admin")




# NOTE: We already run DB init above during import. Keep init_app() callable,
# but don't call it unconditionally to avoid multi-worker duplicate DDL.

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
def index():
    return render_template("index.html")

@app.route("/health")
def health():
    return "ok"


def wake_hotshort_server():
    """
    Wake the HotShort worker host.

    Preferred path:
    - trigger a GitHub Actions workflow_dispatch that can relay a wake event

    Fallback path:
    - send a local Wake-on-LAN packet when a MAC is configured
    """
    if not _wake_enabled():
        log.info("[WAKE] Wake automation disabled; skipping wake workflow and WOL")
        return False

    repo = os.getenv("HOTSHORT_WAKE_GITHUB_REPO", "").strip()
    workflow = os.getenv("HOTSHORT_WAKE_GITHUB_WORKFLOW", "wake.yml").strip() or "wake.yml"
    ref = os.getenv("HOTSHORT_WAKE_GITHUB_REF", "main").strip() or "main"
    token = os.getenv("HOTSHORT_WAKE_GITHUB_TOKEN", "").strip()

    if repo and token:
        dispatch_url = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow}/dispatches"
        try:
            resp = requests.post(
                dispatch_url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                },
                json={"ref": ref},
                timeout=10,
            )
            if 200 <= resp.status_code < 300:
                log.info("[WAKE] Triggered GitHub workflow dispatch repo=%s workflow=%s ref=%s", repo, workflow, ref)
                return True
            log.warning(
                "[WAKE] GitHub workflow dispatch failed status=%s repo=%s workflow=%s body=%s",
                resp.status_code,
                repo,
                workflow,
                (resp.text or "")[:300],
            )
        except Exception:
            log.exception("[WAKE] GitHub workflow dispatch raised an exception")

    mac = os.getenv("HOTSHORT_WAKE_WOL_MAC", "30:56:0F:19:9D:1B").strip()
    if not mac:
        log.warning("[WAKE] No GitHub workflow config or WOL MAC available")
        return False

    try:
        mac_bytes = bytes.fromhex(mac.replace(":", "").replace("-", ""))
        packet = b"\xff" * 6 + mac_bytes * 16

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            sock.sendto(packet, ("255.255.255.255", 9))
            log.info("[WAKE] Wake-on-LAN packet sent to HotShort server")
            return True
        finally:
            sock.close()
    except Exception:
        log.exception("[WAKE] Wake-on-LAN send failed")
        return False


def worker_alive():
    """
    Checks if the configured local worker service is running.
    """
    local_worker_url = (LOCAL_WORKER_URL or os.getenv("LOCAL_WORKER_URL", "")).strip()
    if local_worker_url:
        return bool(_local_worker_status(local_worker_url, timeout=2).get("alive"))

    log.warning("[WAKE] LOCAL_WORKER_URL is not configured; treating worker as offline")
    return False


def _wake_wait_seconds() -> int:
    if not _wake_enabled():
        return 0
    try:
        return max(0, int(os.getenv("HOTSHORT_WAKE_WAIT_SECONDS", "35") or 35))
    except Exception:
        return 35


def _wake_enabled() -> bool:
    return (os.getenv("HOTSHORT_WAKE_ENABLED", "0") or "0").strip().lower() in ("1", "true", "yes", "on")


def ensure_worker_ready(timeout_seconds: int | None = None, retry_interval_seconds: int = 5) -> bool:
    """
    Ensure the remote/local worker is reachable before trying to analyze.

    The hosted web app owns this orchestration so the browser never needs to
    know about wake endpoints or tunnel URLs.
    """
    if worker_alive():
        return True

    if not _wake_enabled():
        log.info("[WAKE] Wake automation disabled; skipping wake wait loop")
        return False

    wake_sent = wake_hotshort_server()
    if not wake_sent:
        log.warning("[WAKE] Could not send wake signal to worker host")
        return False

    wait_budget = timeout_seconds if timeout_seconds is not None else _wake_wait_seconds()
    deadline = time.time() + max(0, wait_budget)
    sleep_for = max(1, int(retry_interval_seconds))

    while time.time() <= deadline:
        time.sleep(sleep_for)
        if worker_alive():
            log.info("[WAKE] Worker became available after wake")
            return True

    log.warning("[WAKE] Worker did not become ready within %ss", wait_budget)
    return False


@app.route("/api/worker/status", methods=["GET"])
# @login_required
def api_worker_status():
    return jsonify({
        "ok": True,
        "alive": worker_alive(),
        "wake_wait_seconds": _wake_wait_seconds(),
    })


@app.route("/api/worker/wake", methods=["POST"])
@login_required
def api_worker_wake():
    if worker_alive():
        return jsonify({
            "ok": True,
            "alive": True,
            "already_awake": True,
            "wake_wait_seconds": _wake_wait_seconds(),
        })

    wake_sent = wake_hotshort_server()
    if not wake_sent:
        return jsonify({
            "ok": False,
            "alive": False,
            "error": "Wake signal could not be sent.",
            "wake_wait_seconds": _wake_wait_seconds(),
        }), 503

    return jsonify({
        "ok": True,
        "alive": False,
        "already_awake": False,
        "wake_sent": True,
        "wake_wait_seconds": _wake_wait_seconds(),
    })

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


@app.route("/api/runpod-download", methods=["POST"])
@login_required
def api_runpod_download():
    """Trigger RunPod to download a YouTube video and return a public URL.

    Request JSON: {"url": "https://youtu.be/.."}
    Response JSON: {"video_url": "https://..."}
    """
    data = request.get_json(silent=True) or {}
    youtube_url = (data.get("url") or data.get("youtube_url") or "").strip()
    if not youtube_url:
        return jsonify({"error": "Missing url"}), 400

    pod_started = False
    runpod_start_time = None
    try:
        if RUNPOD_MODE == "pod" and RUNPOD_AVAILABLE and os.environ.get("RUNPOD_API_KEY") and os.environ.get("RUNPOD_POD_ID"):
            try:
                log.info("[RUNPOD] Starting GPU pod for download api...")
                runpod_start_time = time.time()
                start_pod()
                pod_started = True
                if wait_until_ready(timeout=120):
                    log.info("[RUNPOD] Pod ready for download api")
                else:
                    log.warning("[RUNPOD] Pod did not become ready within timeout; continuing anyway")
            except Exception as e:
                log.warning("[RUNPOD] Failed to start pod: %s", e)

        result = process_video_hybrid(youtube_url, job_id=None)

        clips = result.get("clips") if isinstance(result, dict) else None
        if clips is None:
            return jsonify({"error": "RunPod orchestrate returned unexpected output"}), 500

        return jsonify({"clips": clips})

    except Exception as e:
        log.error("[RUNPOD] orchestrate failed: %s", e)
        return jsonify({
            "error": "RunPod orchestrate failed",
            "message": str(e),
            "hint": "Set RUNPOD_ENDPOINT_ID and RUNPOD_API_KEY in .env, and make sure HS_RUNPOD_DOWNLOAD=1 if you want RunPod mode."
        }), 500

    finally:
        if RUNPOD_MODE == "pod" and pod_started and RUNPOD_AVAILABLE and os.environ.get("RUNPOD_API_KEY") and os.environ.get("RUNPOD_POD_ID"):
            try:
                if runpod_start_time:
                    duration = time.time() - runpod_start_time
                    cost = duration * (0.44 / 3600)
                    log.info(f"[RUNPOD_RUNTIME] {duration:.2f}s")
                    log.info(f"[GPU_COST] user={getattr(current_user, 'id', 'anonymous')} time={duration:.2f}s cost=${cost:.5f}")
                    MAX_GPU_RUNTIME = 300
                    if duration > MAX_GPU_RUNTIME:
                        log.warning("[WATCHDOG] GPU runtime exceeded safe window")
                        stop_pod(force=True)
                    else:
                        log.info("[RUNPOD] Stopping GPU pod after api_runpod_download...")
                        stop_pod()
                else:
                    log.info("[RUNPOD] Stopping GPU pod after api_runpod_download...")
                    stop_pod()
            except Exception as e:
                log.warning("[RUNPOD] Failed to stop pod in finalizer: %s", e)

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
@app.route('/dashboard', methods=['GET', 'POST'])
@login_required
def dashboard():
    from flask import make_response
    template_id = session.get("template_id")
    
    # Dashboard shows upload form (no clips)
    # Results moved to /results/<job_id> (see route below)
    
    # Handle POST submissions (form uploads)  
    if request.method == 'POST':
        youtube_url = request.form.get('youtube_url', '').strip()
        if youtube_url:
            # Redirect to /analyze endpoint for processing
            # (JavaScript clients POST directly to /analyze, but form submissions come here)
            return redirect(url_for('analyze_video'))
        else:
            flash('Please provide a YouTube URL', 'error')
            return redirect(url_for('dashboard'))
    
    # Handle GET requests - render the dashboard form
    response = make_response(render_template('dashboard.html', template_id=template_id))
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
                    # 🔥 VIRAL POTENTIAL INDICATOR - NEW FIELDS
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



        
        # Determine the source file - simulating logic since we don't have DB models imported here natively
        # Ideally, we query the DB. For now we assume a temp file or the generated file
        input_path = os.path.join(BASE_DIR, "output", f"hotshort_clip_{clip_id}.mp4")
        if not os.path.exists(input_path):
            return jsonify({"error": "Clip not found"}), 404
            
        output_path = os.path.join(BASE_DIR, "output", f"export_{format_type}_{clip_id}.mp4")
        
        from effects.smart_cutting_engine import render_platform_clip
        final_path = render_platform_clip(input_path, output_path, format_type, is_pro)
        
        return send_file(final_path, as_attachment=True)
    except Exception as e:
        return jsonify({"error": str(e)}), 500



# ---------------------------------------------------------
# PHASE 13: PLATFORM EXPORT API (UPDATED WITH EXPORTS HISTORY)
# ---------------------------------------------------------
@app.route("/export_clip", methods=["POST"])
@login_required
def export_clip():
    try:
        data = request.json
        format_type = data.get("format", "tiktok")
        clip_id = str(data.get("clip_id", "0"))
        is_pro = data.get("is_pro", False)
        
        input_path = os.path.join(BASE_DIR, "output", f"hotshort_clip_{clip_id}.mp4")
        if not os.path.exists(input_path):
            return jsonify({"error": "Clip not found"}), 404
            
        export_dir = os.path.join(BASE_DIR, "static", "exports")
        os.makedirs(export_dir, exist_ok=True)
        
        filename = f"export_{format_type}_{clip_id}_{int(time.time())}.mp4"
        output_path = os.path.join(export_dir, filename)
        
        from effects.smart_cutting_engine import render_platform_clip
        final_path = render_platform_clip(input_path, output_path, format_type, is_pro)
        
        # Get duration for history
        import subprocess
        dur = 0.0
        try:
            cmd_dur = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", final_path]
            dur = float(subprocess.check_output(cmd_dur).strip())
        except Exception:
            pass
            
        # Save to history
        from models.user import UserExport, db
        new_export = UserExport(
            user_id=current_user.id,
            clip_id=clip_id,
            clip_name=f"Clip {clip_id}",
            platform_format=format_type,
            duration=dur,
            file_path=f"/static/exports/{filename}"
        )
        db.session.add(new_export)
        db.session.commit()
        
        return jsonify({"url": f"/static/exports/{filename}", "success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/export_all", methods=["POST"])
@login_required
def export_all():
    try:
        data = request.json
        job_id = data.get("job_id")
        format_type = data.get("format", "tiktok")
        
        if not job_id:
            return jsonify({"error": "Job ID required"}), 400
            
        job = Job.query.filter_by(id=job_id, user_id=current_user.id).first()
        if not job:
            return jsonify({"error": "Job not found"}), 404
            
        # Get clips for this job
        clips = Clip.query.filter_by(job_id=job_id).all()
        if not clips:
             return jsonify({"error": "No clips found"}), 404
             
        is_pro = getattr(current_user, "plan_type", "trial") != "trial"
        
        export_dir = os.path.join(BASE_DIR, "static", "exports")
        os.makedirs(export_dir, exist_ok=True)
        
        batch_id = str(uuid.uuid4())[:8]
        zip_filename = f"batch_{format_type}_{job_id}_{batch_id}.zip"
        zip_path = os.path.join(export_dir, zip_filename)
        
        from effects.smart_cutting_engine import render_platform_clip
        from models.user import UserExport, db
        
        with tempfile.TemporaryDirectory() as tmp_dir:
            with zipfile.ZipFile(zip_path, 'w') as zipf:
                for clip in clips:
                    input_path = os.path.join(BASE_DIR, "output", f"hotshort_clip_{clip.id}.mp4")
                    if not os.path.exists(input_path):
                        continue
                    
                    # Clean filename for ZIP
                    title_safe = re.sub(r'[^\w\-_\. ]', '_', clip.title or f"clip_{clip.id}")
                    clip_filename = f"{title_safe}_{format_type}.mp4"
                    output_path = os.path.join(tmp_dir, clip_filename)
                    
                    try:
                        render_platform_clip(input_path, output_path, format_type, is_pro)
                        zipf.write(output_path, clip_filename)
                        
                        # Save to history (optional for batch entries, but good for tracking)
                        new_export = UserExport(
                            user_id=current_user.id,
                            clip_id=str(clip.id),
                            clip_name=f"{clip.title or 'Clip'} (Batch)",
                            platform_format=format_type,
                            duration=0.0,
                            file_path=f"/static/exports/{zip_filename}"
                        )
                        db.session.add(new_export)
                    except Exception as e:
                        app.logger.warning(f"Failed to render clip {clip.id} in batch: {e}")
                
                db.session.commit()
                
        return jsonify({"url": f"/static/exports/{zip_filename}", "success": True})
    except Exception as e:
        app.logger.exception("Batch export failed")
        return jsonify({"error": str(e)}), 500

from sqlalchemy.exc import OperationalError

@app.route("/api/exports", methods=["GET"])
@login_required
def get_my_exports():
    from models.user import UserExport
    try:
        exports = UserExport.query.filter_by(user_id=current_user.id).order_by(UserExport.created_at.desc()).all()
        result = []
        for e in exports:
            result.append({
                "id": e.id,
                "clip_name": e.clip_name,
                "platform_format": e.platform_format,
                "duration": round(e.duration, 1) if e.duration else 0.0,
                "file_path": e.file_path,
                "created_at": e.created_at.strftime("%Y-%m-%d %H:%M:%S")
            })
        return jsonify(result)
    except OperationalError:
        return jsonify([])

def init_db():
    """Production-safe database initializer."""
    if not _should_auto_create_tables():
        return

    from sqlalchemy.exc import OperationalError
    try:
        with app.app_context():
            # Ensure SQLite directory exists
            db_uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
            if db_uri and db_uri.startswith("sqlite:///"):
                db_path = db_uri.replace("sqlite:///", "")
                if db_uri.startswith("sqlite:////"):
                    db_path = "/" + db_path.lstrip("/")
                db_dir = os.path.dirname(os.path.abspath(db_path))
                if db_dir:
                    os.makedirs(db_dir, exist_ok=True)

            # Use the safe retry-logic wrapper
            _db_create_all_safe()
    except (OperationalError, Exception) as e:
        # Ignore "table already exists" or "locked" errors during multi-worker boot
        msg = str(e).lower()
        if "already exists" in msg or "locked" in msg:
            pass
        else:
            app.logger.warning(f"[DB-INIT] Suppression of init error: {e}")

def initialize_database():
    init_db()

# Replace before_first_request with direct execution in app context
with app.app_context():
    initialize_database()

if __name__ == "__main__":
    app.run(port=5000, debug=True)
