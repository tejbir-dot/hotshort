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

# ─── Cross-Worker Plan Store (per job_id) ─────────────────────────────────────
# Backed by shared temp files so multiple Gunicorn workers share plans seamlessly.
# TTL: 2 hours (cleaned on next write).
_plan_store: Dict[str, Dict] = {}
_plan_store_lock = threading.Lock()
_PLAN_TTL_S = 7200  # 2 hours
_PLAN_DISK_DIR = os.path.join(tempfile.gettempdir(), "hotshort_agentic_plans")


def _safe_plan_path(key: str) -> str:
    safe_key = "".join(c for c in str(key or "") if c.isalnum() or c in ("-", "_"))[:64] or "default"
    return os.path.join(_PLAN_DISK_DIR, f"{safe_key}.json")


def _store_plan(key: str, plan: Dict) -> None:
    now = time.time()
    payload = dict(plan)
    payload["_ts"] = now
    with _plan_store_lock:
        expired = [k for k, v in _plan_store.items() if now - v.get("_ts", 0) > _PLAN_TTL_S]
        for k in expired:
            del _plan_store[k]
        _plan_store[key] = payload
        try:
            os.makedirs(_PLAN_DISK_DIR, exist_ok=True)
            with open(_safe_plan_path(key), "w", encoding="utf-8") as f:
                json.dump(payload, f)
        except Exception as e:
            log.warning(f"[AGENTIC] Failed to persist plan {key} to disk: {e}")


def _get_plan(key: str) -> Dict | None:
    now = time.time()
    with _plan_store_lock:
        cached = _plan_store.get(key)
        if cached and (now - float(cached.get("_ts", 0) or 0)) <= _PLAN_TTL_S:
            return cached
        path = _safe_plan_path(key)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    disk_plan = json.load(f)
                if isinstance(disk_plan, dict) and (now - float(disk_plan.get("_ts", 0) or 0)) <= _PLAN_TTL_S:
                    _plan_store[key] = disk_plan
                    return disk_plan
                os.remove(path)
            except Exception as e:
                log.warning(f"[AGENTIC] Error loading persisted plan {key}: {e}")
        return None


def _get_shared_poll_time() -> float:
    try:
        import app as hs_app
        if hasattr(hs_app, "_get_shared_worker_poll_time"):
            return float(hs_app._get_shared_worker_poll_time() or 0.0)
    except Exception:
        pass
    try:
        return float(current_app.config.get("_LAST_WORKER_POLL_TIME", 0.0) or 0.0)
    except Exception:
        return 0.0


def _has_agentic_llm_key() -> bool:
    return any(
        (os.getenv(name) or "").strip()
        for name in (
            "GEMINI_API_KEY",
            "GEMINI_API_KEY_2",
            "GEMINI_API_KEY_3",
            "GOOGLE_API_KEY",
            "OPENROUTER_API_KEY",
            "GPT_API",
        )
    )


# ─── Transcript Helper ────────────────────────────────────────────────────────

def _extract_video_id(url: str) -> str:
    import re, hashlib
    m = re.search(r"(?:v=|\/)([0-9A-Za-z_-]{11})", url)
    return m.group(1) if m else hashlib.md5(url.encode()).hexdigest()[:11]


def _fetch_captions_via_ytdlp(youtube_url: str) -> List[Dict]:
    """
    Secondary zero-GPU caption extractor using yt-dlp's native `json3` tracks.
    Prefers original/non-tlang tracks (e.g. en, en-US, en-orig, hi-orig) because
    YouTube rate-limits auto-translated `tlang=` endpoints with HTTP 429.
    """
    try:
        import yt_dlp
        import requests as _req
    except ImportError:
        return []

    try:
        with yt_dlp.YoutubeDL({
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "socket_timeout": 12,
        }) as ydl:
            info = ydl.extract_info(youtube_url, download=False)
    except Exception as e:
        log.info(f"[AGENTIC] yt-dlp caption metadata failed: {e}")
        return []

    if not isinstance(info, dict):
        return []

    subs = info.get("subtitles") or {}
    asubs = info.get("automatic_captions") or {}

    preferred = ["en", "en-US", "en-GB", "en-orig", "hi-orig", "hi", "hi-IN", "pa-orig", "pa"]

    def _pick_native_url(pool: dict) -> str | None:
        if not isinstance(pool, dict) or not pool:
            return None
        ordered_keys = [k for k in preferred if k in pool] + [k for k in pool.keys() if k not in preferred]
        # Pass 1: strictly native tracks (no tlang= parameter)
        for k in ordered_keys:
            tracks = pool.get(k) or []
            u = next((t.get("url") for t in tracks if t.get("ext") == "json3" and t.get("url") and "tlang=" not in t.get("url", "")), None)
            if u:
                return u
        # Pass 2: any json3 track
        for k in ordered_keys:
            tracks = pool.get(k) or []
            u = next((t.get("url") for t in tracks if t.get("ext") == "json3" and t.get("url")), None)
            if u:
                return u
        return None

    json3_url = _pick_native_url(subs) or _pick_native_url(asubs)
    if not json3_url:
        return []

    try:
        resp = _req.get(json3_url, timeout=15)
        if resp.status_code != 200 or not resp.text.strip():
            return []
        payload = resp.json()
    except Exception as e:
        log.info(f"[AGENTIC] yt-dlp json3 fetch failed: {e}")
        return []

    segments: List[Dict] = []
    for ev in payload.get("events") or []:
        segs_raw = ev.get("segs") or []
        if not segs_raw:
            continue
        txt = "".join(str(x.get("utf8", "") or "") for x in segs_raw)
        clean_txt = " ".join(txt.replace("\n", " ").split()).strip()
        if not clean_txt:
            continue
        start_s = float(ev.get("tStartMs", 0) or 0) / 1000.0
        dur_s = float(ev.get("dDurationMs", 2500) or 2500) / 1000.0
        segments.append({
            "start": round(start_s, 3),
            "end": round(start_s + max(0.25, dur_s), 3),
            "text": clean_txt,
        })

    if len(segments) < 5:
        return []
    return segments


def _fetch_youtube_captions(vid_id: str, youtube_url: str | None = None) -> List[Dict]:
    """
    Zero-GPU transcript fetch:
      1. youtube-transcript-api (supports both 0.6.x and 1.x)
      2. yt-dlp native json3 tracks fallback (avoids empty timedtext XML / HTTP 429 tlang blocks)
    Returns normalized List[Dict(start, end, text)] or [] if captions unavailable.
    """
    preferred_langs = ["en", "en-US", "en-GB", "hi", "hi-IN", "pa"]
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        api = YouTubeTranscriptApi()
        transcript_list = api.list(vid_id) if hasattr(api, "list") else YouTubeTranscriptApi.list_transcripts(vid_id)
        if transcript_list:
            selected = None
            try:
                selected = transcript_list.find_transcript(preferred_langs)
            except Exception:
                for tr in transcript_list:
                    selected = tr
                    break
            if selected:
                raw = selected.fetch()
                if hasattr(raw, "to_raw_data"):
                    raw = raw.to_raw_data()
                segments: List[Dict] = []
                for item in raw or []:
                    if isinstance(item, dict):
                        s = float(item.get("start", 0.0) or 0.0)
                        d = float(item.get("duration", 0.0) or 0.0)
                        txt = str(item.get("text", "") or "")
                    else:
                        s = float(getattr(item, "start", 0.0) or 0.0)
                        d = float(getattr(item, "duration", 0.0) or 0.0)
                        txt = str(getattr(item, "text", "") or "")
                    clean_txt = " ".join(txt.replace("\n", " ").split()).strip()
                    if not clean_txt:
                        continue
                    segments.append({
                        "start": round(s, 3),
                        "end": round(s + max(0.25, d), 3),
                        "text": clean_txt,
                    })
                if len(segments) >= 5:
                    return segments
    except Exception as e:
        log.info(f"[AGENTIC] youtube-transcript-api failed for {vid_id}: {e}")

    # Layer 2: yt-dlp native json3 captions (still $0.00 GPU)
    target_url = youtube_url or f"https://www.youtube.com/watch?v={vid_id}"
    return _fetch_captions_via_ytdlp(target_url)


def _get_segments_from_url(youtube_url: str, is_paid: bool = False, video_duration_s: float | None = None) -> List[Dict]:
    """
    Transcript acquisition cascade (Zero-GPU First):
      1. Persistent JSON cache
      2. Free YouTube Captions API (~1.5s, $0.00 GPU, works up to 90m+ podcasts)
      3. Whisper fallback ONLY if captions are unavailable AND duration <= Whisper cap
    """
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

    # 2. Zero-GPU YouTube Captions (enables 60-90m podcasts at $0.00 RunPod cost)
    yt_segs = _fetch_youtube_captions(vid_id, youtube_url=youtube_url)
    if yt_segs:
        log.info(f"[AGENTIC] Fetched {len(yt_segs)} YouTube caption segments for {vid_id} ($0.00 GPU)")
        try:
            with open(cache_json, "w", encoding="utf-8") as f:
                json.dump(yt_segs, f)
        except Exception as e:
            log.warning(f"[AGENTIC] Failed to save YouTube caption cache: {e}")
        return yt_segs

    # 3. Whisper Fallback Guard — prevent blowing up RunPod on un-captioned 2-hour videos
    max_whisper_s = float(os.getenv("MAX_PAID_VIDEO_DURATION_SECONDS", 5400)) if is_paid else float(os.getenv("MAX_FREE_VIDEO_DURATION_SECONDS", 1200))
    if video_duration_s and video_duration_s > max_whisper_s:
        dur_m = round(video_duration_s / 60)
        cap_m = int(max_whisper_s / 60)
        raise ValueError(
            f"YouTube captions are unavailable for this {dur_m}-minute video. "
            f"Whisper audio transcription without captions is capped at {cap_m} minutes on your current plan "
            f"(up to 90 minutes supported when YouTube captions are available)."
        )

    # Only dispatch transcription to RunPod when configured AND local worker is offline
    last_poll = _get_shared_poll_time()
    is_local_online = (last_poll > 0 and (time.time() - last_poll) < 45.0)
    if (
        not is_local_online
        and os.getenv("RUNPOD_ENDPOINT_ID")
        and os.getenv("RUNPOD_API_KEY")
        and os.getenv("USE_LOCAL_WORKER", "0").strip() != "1"
    ):
        from app import send_transcription_request

        log.info(f"[AGENTIC] Captions unavailable for {vid_id}; sending audio transcription to RunPod worker")
        segments = send_transcription_request(youtube_url)
        if segments:
            try:
                with open(cache_json, "w", encoding="utf-8") as f:
                    json.dump(segments, f)
            except Exception as e:
                log.warning(f"[AGENTIC] Failed to save RunPod transcript cache: {e}")
        log.info(f"[AGENTIC] RunPod transcription returned {len(segments)} segments for {vid_id}")
        return segments

    # 4. Local audio download + faster-whisper fallback
    audio_dir = os.path.join("static", "cache")
    os.makedirs(audio_dir, exist_ok=True)
    audio_base = os.path.join(audio_dir, f"agentic_audio_{vid_id}")

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

    try:
        with open(cache_json, "w", encoding="utf-8") as f:
            json.dump(segments, f)
    except Exception as e:
        log.warning(f"[AGENTIC] Failed to save transcript cache: {e}")

    return segments


# ─── Route 1: Plan ─────────────────────────────────────────────────────────────

@agentic_bp.route("/plan", methods=["POST"])
@login_required
def agentic_plan():
    """
    POST /api/agentic/plan

    Analyze a YouTube video using the 2-pass Agentic Planner and return
    6-10 high-precision viral moment candidates — Zero-GPU when YouTube captions exist.
    """
    from viral_finder.agentic_planner import AgenticPlanner
    import uuid
    import app as hs_app

    data = request.get_json(silent=True) or {}
    youtube_url = (data.get("youtube_url") or data.get("url") or "").strip()
    job_id = (data.get("job_id") or str(uuid.uuid4())[:12]).strip()
    pre_segments = data.get("segments")

    if not youtube_url and not pre_segments:
        return jsonify({"ok": False, "error": "Missing youtube_url or segments"}), 400

    # Quota + abuse check
    is_paid = False
    try:
        user_obj = current_user if getattr(current_user, "is_authenticated", False) else None
        free_status = hs_app.get_free_status(user_obj)
        is_paid = bool(free_status.get("is_paid"))
        left = int(free_status.get("free_clips_left", 0) or 0)
        if not is_paid and left <= 0:
            return jsonify({
                "ok": False,
                "action": "show_pricing_modal",
                "reason": "free_limit_reached",
                "error": "Free generation limit reached. Upgrade to VIP Access to continue!",
            }), 402
    except Exception as qe:
        log.warning(f"[AGENTIC] Quota check fallback: {qe}")

    if not _has_agentic_llm_key():
        return jsonify({
            "ok": False,
            "error": "Agentic planner needs GEMINI_API_KEY or OPENROUTER_API_KEY in the Railway web service Variables.",
        }), 503

    # Pre-check duration cap (allows up to 90m free via zero-GPU YouTube captions; blocks 3h+ streams)
    max_total_s = float(os.getenv("MAX_PAID_VIDEO_DURATION_SECONDS", 7200)) if is_paid else float(os.getenv("MAX_FREE_AGENTIC_VIDEO_DURATION_SECONDS", 5400))
    video_duration_s = None
    if youtube_url and not pre_segments and hasattr(hs_app, "_get_youtube_duration_fast"):
        video_duration_s = hs_app._get_youtube_duration_fast(youtube_url)
        if video_duration_s and video_duration_s > max_total_s:
            dur_m = round(video_duration_s / 60)
            max_m = int(max_total_s / 60)
            return jsonify({
                "ok": False,
                "action": "show_pricing_modal",
                "reason": "video_too_long",
                "error": f"This video is {dur_m} minutes long (plan limit: {max_m} minutes). Upgrade for longer streams!",
            }), 400

    t_start = time.time()

    try:
        # Step 1: Get transcript segments
        if pre_segments and isinstance(pre_segments, list):
            segments = pre_segments
            log.info(f"[AGENTIC] Using pre-supplied {len(segments)} segments for plan_id={job_id}")
        else:
            segments = _get_segments_from_url(youtube_url, is_paid=is_paid, video_duration_s=video_duration_s)

        if not segments:
            return jsonify({"ok": False, "error": "Transcription returned 0 segments. Check the video URL."}), 422

        try:
            inferred_dur = float(segments[-1].get("end", 0.0) or 0.0)
        except Exception:
            inferred_dur = 0.0
        if inferred_dur > max_total_s:
            dur_m = round(inferred_dur / 60)
            max_m = int(max_total_s / 60)
            return jsonify({
                "ok": False,
                "action": "show_pricing_modal",
                "reason": "video_too_long",
                "error": f"This video is {dur_m} minutes long (plan limit: {max_m} minutes).",
            }), 400

        # Step 2: Run Agentic 2-pass analysis
        planner = AgenticPlanner()
        result = planner.analyze(segments)

        # Step 3: Store plan (persisted across Gunicorn workers)
        owner_id = hs_app._effective_user_id_for_request() if hasattr(hs_app, "_effective_user_id_for_request") else 1
        plan_payload = {
            "plan_id": job_id,
            "owner_id": owner_id,
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

    except ValueError as ve:
        return jsonify({
            "ok": False,
            "action": "show_pricing_modal" if "minute" in str(ve).lower() else None,
            "reason": "video_too_long" if "minute" in str(ve).lower() else "transcript_unavailable",
            "error": str(ve),
        }), 400
    except Exception as e:
        log.exception(f"[AGENTIC] /plan error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


# ─── Route 2: Render Approved ─────────────────────────────────────────────────

@agentic_bp.route("/worker-status", methods=["GET"])
def agentic_worker_status():
    """
    GET /api/agentic/worker-status
    Returns the real-time failover routing target using the cross-process worker heartbeat.
    """
    _last_poll = _get_shared_poll_time()
    is_local_online = (_last_poll > 0 and (time.time() - _last_poll) < 45.0)
    last_seen = round(time.time() - _last_poll, 1) if _last_poll > 0 else None

    return jsonify({
        "ok": True,
        "is_local_online": is_local_online,
        "last_seen_seconds_ago": last_seen,
        "target_worker": "Local Worker (localhost RTX GPU)" if is_local_online else "RunPod GPU (serverless)",
        "worker_type": "local" if is_local_online else "runpod",
    })


def _slice_segments_for_clip(segments: List[Dict], start_s: float, end_s: float, pad_s: float = 3.0) -> List[Dict]:
    if not segments:
        return []
    win_start = max(0.0, float(start_s) - pad_s)
    win_end = float(end_s) + pad_s
    out = []
    for seg in segments:
        try:
            s = float(seg.get("start", 0.0) or 0.0)
            e = float(seg.get("end", s) or s)
        except Exception:
            continue
        if e >= win_start and s <= win_end:
            out.append(seg)
    return out


@agentic_bp.route("/render-approved", methods=["POST"])
@login_required
def agentic_render_approved():
    """
    POST /api/agentic/render-approved

    Queues ONLY user-approved clips for GPU rendering with free-tier meter guards.
    Routing priority:
      1. Local Worker if online (<45s shared heartbeat)
      2. RunPod GPU serverless failover (section-sliced to avoid full-video downloads)
    """
    from models.user import Job, db
    from datetime import datetime
    import app as hs_app

    data = request.get_json(silent=True) or {}
    plan_id = (data.get("plan_id") or "").strip()
    approved_indices = data.get("approved_indices", [])
    raw_format = (data.get("format_mode") or "tjr").strip().lower()
    format_mode = raw_format if raw_format in {"brainrot", "tjr", "cinematic", "raw_cut"} else "tjr"

    if not plan_id:
        return jsonify({"ok": False, "error": "Missing plan_id"}), 400

    if not isinstance(approved_indices, list) or len(approved_indices) == 0:
        return jsonify({"ok": False, "error": "approved_indices must be a non-empty list of integers"}), 400

    # Free quota check
    user_obj = current_user if getattr(current_user, "is_authenticated", False) else None
    free_status = hs_app.get_free_status(user_obj) if hasattr(hs_app, "get_free_status") else {"is_paid": False, "free_clips_left": 3}
    is_paid = bool(free_status.get("is_paid"))
    left = int(free_status.get("free_clips_left", 0) or 0)
    if not is_paid and left <= 0:
        return jsonify({
            "ok": False,
            "action": "show_pricing_modal",
            "reason": "free_limit_reached",
            "error": "Free generation limit reached — upgrade to VIP Access to render more clips!",
        }), 402

    # Retrieve stored plan
    plan = _get_plan(plan_id)
    if not plan:
        return jsonify({
            "ok": False,
            "error": f"Plan '{plan_id}' not found or expired. Re-run Find Viral Moments first."
        }), 404

    all_candidates = plan.get("candidates", [])
    if not all_candidates:
        return jsonify({"ok": False, "error": "Plan has no candidates."}), 422

    # Deduplicate & collect approved clips cleanly
    plan_segments = plan.get("segments") or []
    seen_idx = set()
    approved_clips = []
    max_clip_dur = float(os.getenv("MAX_PAID_CLIP_DURATION_SECONDS", 150.0)) if is_paid else float(os.getenv("MAX_FREE_CLIP_DURATION_SECONDS", 95.0))
    for idx in approved_indices:
        if isinstance(idx, int) and 0 <= idx < len(all_candidates) and idx not in seen_idx:
            seen_idx.add(idx)
            c_copy = dict(all_candidates[idx])
            s_t = float(c_copy.get("start_s", c_copy.get("start", 0.0)) or 0.0)
            e_t = float(c_copy.get("end_s", c_copy.get("end", s_t + 30.0)) or (s_t + 30.0))
            if (e_t - s_t) > max_clip_dur:
                return jsonify({
                    "ok": False,
                    "error": f"Clip duration ({int(e_t - s_t)}s) exceeds the {int(max_clip_dur)}s limit.",
                }), 400
            if not c_copy.get("transcript"):
                c_copy["transcript"] = _slice_segments_for_clip(plan_segments, s_t, e_t)
            approved_clips.append(c_copy)
        elif not isinstance(idx, int) or not (0 <= idx < len(all_candidates)):
            log.warning(f"[AGENTIC] render-approved: index {idx} out of range (0–{len(all_candidates)-1}), skipping.")

    if not approved_clips:
        return jsonify({"ok": False, "error": "No valid indices in approved_indices."}), 400

    if not is_paid:
        max_free_clips = int(os.getenv("MAX_FREE_APPROVED_CLIPS", 2))
        if len(approved_clips) > max_free_clips:
            return jsonify({
                "ok": False,
                "action": "show_pricing_modal",
                "reason": "too_many_clips",
                "error": f"Free beta renders up to {max_free_clips} clips per batch (you selected {len(approved_clips)}). Uncheck extra clips or upgrade to VIP Access!",
            }), 400

    youtube_url = plan.get("youtube_url", "")
    job_id = plan_id

    user_id = hs_app._effective_user_id_for_request() if hasattr(hs_app, "_effective_user_id_for_request") else None
    if not user_id:
        user_id = getattr(current_user, "id", None) or 1

    # Concurrency guard: prevent accidental double-clicks/spam from launching duplicate RunPod jobs
    try:
        active_job = Job.query.filter(
            Job.user_id == int(user_id),
            Job.id != job_id,
            Job.status.in_(["queued", "processing", "in_progress", "pending"]),
        ).first()
        if active_job:
            return jsonify({
                "ok": False,
                "error": "Another render job is already in progress. Please wait until it finishes."
            }), 429
    except Exception:
        pass

    analysis_payload = {
        "job_id": job_id,
        "source_url": youtube_url,
        "approved_clips": approved_clips,
        "format_mode": format_mode,
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
            job.user_id = int(user_id)
            job.status = "pending"
            job.analysis_data = json.dumps(analysis_payload)
        db.session.commit()
    except Exception as dbe:
        db.session.rollback()
        log.error(f"[AGENTIC] DB error saving approved job {job_id}: {dbe}")

    # ── Intelligent Worker Routing: Local Worker First → RunPod Failover ───────
    _last_poll = _get_shared_poll_time()
    is_local_online = (_last_poll > 0 and (time.time() - _last_poll) < 45.0)

    if is_local_online:
        worker_target = "Local Worker (localhost RTX GPU)"
        worker_type = "local"
        message = f"🚀 {len(approved_clips)} approved clip(s) queued for Local Worker via NVENC!"
        log.info(
            f"\n{'='*60}\n[AGENTIC] job={job_id} ({len(approved_clips)} clips) ASSIGNED TO LOCAL WORKER (heartbeat {time.time()-_last_poll:.1f}s ago)!\n"
            f"[AGENTIC] local_worker.py will process this job with local RTX GPU.\n{'='*60}\n"
        )
    else:
        worker_target = "RunPod GPU (serverless failover)"
        worker_type = "runpod"
        message = f"⚡ Local worker offline — {len(approved_clips)} clip(s) routed to RunPod GPU (section-sliced)!"
        log.info(
            f"\n{'='*60}\n[AGENTIC] Local worker is OFFLINE. Auto-failing over job={job_id} to RunPod GPU!\n{'='*60}\n"
        )
        try:
            run_fn = getattr(hs_app, "run_process_video_safe", None) or hs_app.process_video
            threading.Thread(target=run_fn, args=(job_id,), daemon=True).start()
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

