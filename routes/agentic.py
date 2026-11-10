"""
routes/agentic.py

HotShort Agentic Planner API — 2 endpoints, zero existing code touched.

Endpoints:
    POST /api/agentic/plan
        Input:  { "youtube_url": "...", "job_id": "..." (optional) }
        Output: { "candidates": [...], "priority_zones": [...], "stats": {...} }
        Cost:   ~$0.002, ~20s, NO GPU, NO render

    POST /api/agentic/render-approved
        Input:  { "job_id": "...", "approved_indices": [0, 2] }
        Output: { "queued": 2, "message": "..." }
        Action: Triggers render ONLY for user-approved candidates from a prior plan call.
"""

from __future__ import annotations

import os
import json
import logging
import tempfile
import threading
import time
from typing import List, Dict, Any

from flask import Blueprint, jsonify, request, g, current_app
from flask_login import login_required, current_user

log = logging.getLogger(__name__)

# Load .env.worker so GEMINI_API_KEY is available (it lives there, not in .env)
try:
    from dotenv import load_dotenv as _load_dotenv
    _worker_env = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env.worker")
    if os.path.exists(_worker_env):
        _load_dotenv(_worker_env, override=False)
        log.info("[AGENTIC] Loaded .env.worker for GEMINI_API_KEY")
except Exception:
    pass

agentic_bp = Blueprint("agentic", __name__, url_prefix="/api/agentic")

# ─── In-Memory Plan Store (per job_id) ───────────────────────────────────────
# Stores the plan result keyed by job_id so the render endpoint can reference it.
# TTL: 2 hours (cleaned on next write).
_plan_store: Dict[str, Dict] = {}
_plan_store_lock = threading.Lock()
_PLAN_TTL_S = 7200  # 2 hours


def _store_plan(key: str, plan: Dict) -> None:
    now = time.time()
    with _plan_store_lock:
        # Expire old entries
        expired = [k for k, v in _plan_store.items() if now - v.get("_ts", 0) > _PLAN_TTL_S]
        for k in expired:
            del _plan_store[k]
        plan["_ts"] = now
        _plan_store[key] = plan


def _get_plan(key: str) -> Dict | None:
    with _plan_store_lock:
        return _plan_store.get(key)


# ─── Transcript Helper ────────────────────────────────────────────────────────

def _extract_video_id(url: str) -> str:
    import re, hashlib
    m = re.search(r"(?:v=|\/)([0-9A-Za-z_-]{11})", url)
    return m.group(1) if m else hashlib.md5(url.encode()).hexdigest()[:11]


def _get_segments_from_url(youtube_url: str) -> List[Dict]:
    """
    Download audio from YouTube URL and transcribe using the PRODUCTION
    transcript_engine (same path as the live pipeline — full cache parity).
    Caches transcripts persistently in .hotshort_transcripts_cache for instant replay.

    Returns List[Dict] with keys: start, end, text
    """
    import hashlib
    import yt_dlp
    from viral_finder.transcript_engine import extract_transcript, CACHE_DIR

    vid_id = _extract_video_id(youtube_url)
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_json = os.path.join(CACHE_DIR, f"agentic_{vid_id}.json")

    # 1. Fast Cache Hit
    if os.path.exists(cache_json):
        try:
            with open(cache_json, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list) and len(data) > 0:
                    log.info(f"[AGENTIC] Instant transcript cache hit for {vid_id} ({len(data)} segs)")
                    return data
        except Exception as e:
            log.warning(f"[AGENTIC] Error reading cached transcript: {e}")

    # 2. Download audio to static/cache (persistent)
    audio_dir = os.path.join("static", "cache")
    os.makedirs(audio_dir, exist_ok=True)
    audio_base = os.path.join(audio_dir, f"agentic_audio_{vid_id}")

    # Check if audio already downloaded
    wav_path = None
    for ext in (".wav", ".mp3", ".m4a", ".webm"):
        cand = f"{audio_base}{ext}"
        if os.path.exists(cand) and os.path.getsize(cand) > 1000:
            wav_path = cand
            break

    if not wav_path:
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": f"{audio_base}.%(ext)s",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav",
                "preferredquality": "0",
            }],
            "quiet": True,
            "no_warnings": True,
        }

        log.info(f"[AGENTIC] Downloading audio for {vid_id}: {youtube_url}")
        t0 = time.time()
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([youtube_url])

        for ext in (".wav", ".mp3", ".m4a", ".webm"):
            cand = f"{audio_base}{ext}"
            if os.path.exists(cand):
                wav_path = cand
                break

    if not wav_path:
        raise RuntimeError(f"Audio download failed for {youtube_url}")

    log.info(f"[AGENTIC] Transcribing audio from {wav_path}...")
    t1 = time.time()
    segments = extract_transcript(wav_path)
    log.info(f"[AGENTIC] Transcription complete in {round(time.time()-t1, 1)}s — {len(segments)} segments")

    # Save to persistent agentic cache
    try:
        with open(cache_json, "w", encoding="utf-8") as f:
            json.dump(segments, f)
    except Exception as e:
        log.warning(f"[AGENTIC] Failed to save transcript cache: {e}")

    return segments


# ─── Route 1: Plan ─────────────────────────────────────────────────────────────

@agentic_bp.route("/plan", methods=["POST"])
def agentic_plan():
    """
    POST /api/agentic/plan

    Analyze a YouTube video using the 2-pass Agentic Planner and return
    6-10 high-precision viral moment candidates — NO GPU, NO render.

    Request JSON:
        {
            "youtube_url": "https://youtu.be/...",
            "job_id": "optional-existing-job-id",
            "segments": [...]   // optional: pre-computed transcript segments
        }

    Response JSON:
        {
            "ok": true,
            "plan_id": "job_id or auto-generated",
            "candidates": [
                {
                    "start_s": 36.5,
                    "end_s": 83.0,
                    "duration_s": 46.5,
                    "hook_text": "It's not even 12 yet and we're at €86,000",
                    "arc_type": "flex_reveal",
                    "virality_score": 94,
                    "reasoning": "..."
                },
                ...
            ],
            "priority_zones": [...],
            "stats": {
                "total_segments": 810,
                "video_duration_s": 1698.9,
                "zones_found": 8,
                "candidates_raw": 10,
                "candidates_final": 8,
                "wall_time_s": 19.3
            }
        }
    """
    from viral_finder.agentic_planner import AgenticPlanner
    import uuid

    data = request.get_json(silent=True) or {}
    youtube_url = (data.get("youtube_url") or data.get("url") or "").strip()
    job_id = (data.get("job_id") or str(uuid.uuid4())[:12]).strip()
    pre_segments = data.get("segments")  # Optional: caller can pass pre-computed transcript

    if not youtube_url and not pre_segments:
        return jsonify({"ok": False, "error": "Missing youtube_url or segments"}), 400

    t_start = time.time()

    try:
        # Step 1: Get transcript segments
        if pre_segments and isinstance(pre_segments, list):
            segments = pre_segments
            log.info(f"[AGENTIC] Using pre-supplied {len(segments)} segments for plan_id={job_id}")
        else:
            segments = _get_segments_from_url(youtube_url)

        if not segments:
            return jsonify({"ok": False, "error": "Transcription returned 0 segments. Check the video URL."}), 422

        # Step 2: Run Agentic 2-pass analysis
        planner = AgenticPlanner()
        result = planner.analyze(segments)

        # Step 3: Store plan for render-approved endpoint
        plan_payload = {
            "plan_id": job_id,
            "youtube_url": youtube_url,
            "candidates": result["candidates"],
            "priority_zones": result["priority_zones"],
            "stats": result["stats"],
            "segments": segments,
        }
        _store_plan(job_id, plan_payload)

        total_wall = round(time.time() - t_start, 2)
        log.info(
            f"[AGENTIC] Plan complete — plan_id={job_id}, "
            f"{len(result['candidates'])} candidates in {total_wall}s"
        )

        return jsonify({
            "ok": True,
            "plan_id": job_id,
            "candidates": result["candidates"],
            "priority_zones": result["priority_zones"],
            "stats": {**result["stats"], "total_wall_time_s": total_wall},
        })

    except Exception as e:
        log.exception(f"[AGENTIC] /plan error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


# ─── Route 2: Render Approved ─────────────────────────────────────────────────

@agentic_bp.route("/worker-status", methods=["GET"])
def agentic_worker_status():
    """
    GET /api/agentic/worker-status
    Returns the real-time failover routing target:
    - If local_worker.py --localhost is polling: Local Worker (localhost RTX GPU)
    - If offline: RunPod GPU (serverless failover)
    """
    _last_poll = float(current_app.config.get("_LAST_WORKER_POLL_TIME", 0.0) or 0.0)
    is_local_online = (_last_poll > 0 and (time.time() - _last_poll) < 45.0)
    last_seen = round(time.time() - _last_poll, 1) if _last_poll > 0 else None

    return jsonify({
        "ok": True,
        "is_local_online": is_local_online,
        "last_seen_seconds_ago": last_seen,
        "target_worker": "Local Worker (localhost RTX GPU)" if is_local_online else "RunPod GPU (serverless)",
        "worker_type": "local" if is_local_online else "runpod",
    })


@agentic_bp.route("/render-approved", methods=["POST"])
def agentic_render_approved():
    """
    POST /api/agentic/render-approved

    Queues ONLY user-approved clips for GPU rendering.
    Routing priority:
      1. Local Worker (localhost via --localhost) if online (<45s poll)
      2. RunPod GPU serverless if local worker is offline.
    """
    from models.user import Job, db
    import uuid
    from datetime import datetime

    data = request.get_json(silent=True) or {}
    plan_id = (data.get("plan_id") or "").strip()
    approved_indices = data.get("approved_indices", [])

    if not plan_id:
        return jsonify({"ok": False, "error": "Missing plan_id"}), 400

    if not isinstance(approved_indices, list) or len(approved_indices) == 0:
        return jsonify({"ok": False, "error": "approved_indices must be a non-empty list of integers"}), 400

    # Retrieve stored plan
    plan = _get_plan(plan_id)
    if not plan:
        return jsonify({
            "ok": False,
            "error": f"Plan '{plan_id}' not found or expired. Re-run /api/agentic/plan."
        }), 404

    all_candidates = plan.get("candidates", [])
    if not all_candidates:
        return jsonify({"ok": False, "error": "Plan has no candidates."}), 422

    # Collect approved clips
    approved_clips = []
    for idx in approved_indices:
        if isinstance(idx, int) and 0 <= idx < len(all_candidates):
            approved_clips.append(all_candidates[idx])
        else:
            log.warning(f"[AGENTIC] render-approved: index {idx} out of range (0–{len(all_candidates)-1}), skipping.")

    if not approved_clips:
        return jsonify({"ok": False, "error": "No valid indices in approved_indices."}), 400

    youtube_url = plan.get("youtube_url", "")
    job_id = plan_id

    # Resolve user ID
    user_id = 1
    try:
        if hasattr(current_user, "is_authenticated") and current_user.is_authenticated:
            user_id = current_user.id
    except Exception:
        pass

    # Create or update Job record in DB
    analysis_payload = {
        "job_id": job_id,
        "source_url": youtube_url,
        "approved_clips": approved_clips,
        "format_mode": "tjr",
        "mode": "agentic",
        "requested_at": datetime.utcnow().isoformat(),
    }

    try:
        job = Job.query.filter_by(id=job_id).first()
        if not job:
            job = Job(
                id=job_id,
                user_id=int(user_id),
                status="pending",
                video_path=youtube_url,
                creator_intent="agentic_approved",
                analysis_data=json.dumps(analysis_payload),
            )
            db.session.add(job)
        else:
            job.status = "pending"
            job.analysis_data = json.dumps(analysis_payload)
        db.session.commit()
    except Exception as dbe:
        db.session.rollback()
        log.error(f"[AGENTIC] DB error saving approved job {job_id}: {dbe}")

    # ── Intelligent Worker Routing: Local Worker First → RunPod Failover ───────
    _last_poll = float(current_app.config.get("_LAST_WORKER_POLL_TIME", 0.0) or 0.0)
    is_local_online = (_last_poll > 0 and (time.time() - _last_poll) < 45.0)

    if is_local_online:
        worker_target = "Local Worker (localhost RTX GPU)"
        worker_type = "local"
        message = f"🚀 {len(approved_clips)} approved clip(s) queued for Local Worker on localhost via NVENC!"
        log.info(
            f"\n{'='*60}\n[AGENTIC] job={job_id} ({len(approved_clips)} clips) ASSIGNED TO LOCAL WORKER (localhost active)!\n"
            f"[AGENTIC] local_worker.py will process this job with local RTX GPU.\n{'='*60}\n"
        )
    else:
        worker_target = "RunPod GPU (serverless failover)"
        worker_type = "runpod"
        message = f"⚡ Local worker is offline. {len(approved_clips)} approved clip(s) auto-routed to RunPod GPU serverless!"
        log.info(
            f"\n{'='*60}\n[AGENTIC] Local worker is OFFLINE. Auto-failing over job={job_id} to RunPod GPU!\n{'='*60}\n"
        )
        try:
            import app as hs_app
            threading.Thread(target=hs_app.process_video, args=(job_id,), daemon=True).start()
        except Exception as rpe:
            log.exception(f"[AGENTIC] Error launching RunPod failover thread: {rpe}")

    return jsonify({
        "ok": True,
        "job_id": job_id,
        "queued": len(approved_clips),
        "worker": worker_target,
        "worker_type": worker_type,
        "approved_clips": [
            {
                "start_s": c["start_s"],
                "end_s": c["end_s"],
                "duration_s": c["duration_s"],
                "hook_text": c["hook_text"],
                "arc_type": c["arc_type"],
                "virality_score": c["virality_score"],
                "reasoning": c["reasoning"],
            }
            for c in approved_clips
        ],
        "message": message,
    })


# ─── Route 3: Get Stored Plan (for UI reload) ─────────────────────────────────

@agentic_bp.route("/plan/<plan_id>", methods=["GET"])
def agentic_get_plan(plan_id: str):
    """
    GET /api/agentic/plan/<plan_id>

    Retrieve a previously computed plan by plan_id (for page refresh / UI restore).
    """
    plan = _get_plan(plan_id)
    if not plan:
        return jsonify({"ok": False, "error": f"Plan '{plan_id}' not found or expired."}), 404

    return jsonify({"ok": True, **{k: v for k, v in plan.items() if not k.startswith("_")}})


# ─── Route 4: Interactive Chat with Agent ─────────────────────────────────────

@agentic_bp.route("/chat", methods=["POST"])
def agentic_chat():
    """
    POST /api/agentic/chat

    Chat directly with the clipping partner about the video.
    Can answer questions, find specific moments, or approve clips.

    Request JSON:
        {
            "plan_id": "...",
            "message": "find moment where he is teaching about lessons, money lessons"
        }
    """
    from viral_finder.agentic_planner import chat_with_agent

    data = request.get_json(silent=True) or {}
    plan_id = (data.get("plan_id") or "").strip()
    message = (data.get("message") or "").strip()

    if not message:
        return jsonify({"ok": False, "error": "Missing message"}), 400

    plan = _get_plan(plan_id)
    if not plan:
        return jsonify({
            "ok": True,
            "action": "none",
            "reply": "Please paste a video URL and click '⚡ Find Viral Moments' first so I have the video transcript to work with!",
            "matched_indices": []
        })

    segments = plan.get("segments") or []
    candidates = plan.get("candidates") or []

    result = chat_with_agent(segments, candidates, message)
    return jsonify(result)

