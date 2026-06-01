"""
local_worker.py — HotShort Local GPU Worker
============================================
Run on your PC with an RTX GPU to process jobs from Railway.

Usage:
    python local_worker.py

Required env vars (set in .env.local or export):
    RAILWAY_URL     = https://hotshort.up.railway.app
    WORKER_SECRET   = <your shared secret>
    CLOUDINARY_CLOUD_NAME / API_KEY / API_SECRET
    GROQ_API_KEY

Optional:
    POLL_INTERVAL   = 5   (seconds between polls)
    WHISPER_MODEL   = base
    WHISPER_DEVICE  = cuda
"""

import os
import sys
import json
import time
import tempfile
import subprocess
import traceback

import requests
from dotenv import load_dotenv

# ── Load local env ────────────────────────────────────────────────────────────
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Load .env.worker (worker-specific config) first, then fall back to .env
_worker_env = os.path.join(BASE_DIR, ".env.worker")
_default_env = os.path.join(BASE_DIR, ".env")

# Always load .env first for global configs
if os.path.exists(_default_env):
    load_dotenv(_default_env)
    print(f"[LOCAL_WORKER] Loaded env from .env", flush=True)

# Then override with .env.worker if present
if os.path.exists(_worker_env):
    load_dotenv(_worker_env, override=True)
    print(f"[LOCAL_WORKER] Overrode env with .env.worker", flush=True)

# Force-enable narrative roles for local testing
os.environ["HS_GROQ_NARRATIVE_ROLES"] = "1"


# ── Config ────────────────────────────────────────────────────────────────────
RAILWAY_URL   = os.getenv("RAILWAY_URL", "").rstrip("/")
WORKER_SECRET = os.getenv("WORKER_SECRET", "")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "5"))

if not RAILWAY_URL:
    print("[LOCAL_WORKER] ERROR: RAILWAY_URL is not set. Add it to .env.local", flush=True)
    sys.exit(1)
if not WORKER_SECRET:
    print("[LOCAL_WORKER] ERROR: WORKER_SECRET is not set. Add it to .env.local", flush=True)
    sys.exit(1)

_HEADERS = {
    "X-Worker-Secret": WORKER_SECRET,
    "Content-Type": "application/json",
}


# ══════════════════════════════════════════════════════════════════════════════
# GPU / Startup Diagnostics
# ══════════════════════════════════════════════════════════════════════════════

def _print_startup_banner():
    print("", flush=True)
    print("=" * 55, flush=True)
    print("  🔥 HotShort Local Worker — Starting Up", flush=True)
    print("=" * 55, flush=True)

    # ── GPU check ─────────────────────────────────────────────────────────────
    gpu_name = "N/A"
    cuda_available = False
    try:
        import torch
        cuda_available = torch.cuda.is_available()
        if cuda_available:
            gpu_name = torch.cuda.get_device_name(0)
    except ImportError:
        pass

    # ── Whisper device ────────────────────────────────────────────────────────
    whisper_device = os.getenv("WHISPER_DEVICE", "auto")
    whisper_model  = os.getenv("WHISPER_MODEL", "base")
    if whisper_device == "auto":
        whisper_device = "cuda" if cuda_available else "cpu"

    # ── FFmpeg GPU check ─────────────────────────────────────────────────────
    ffmpeg_nvenc = False
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=5
        )
        ffmpeg_nvenc = "h264_nvenc" in (result.stdout or "")
    except Exception:
        pass

    print(f"  [LOCAL_WORKER] RAILWAY    = {RAILWAY_URL}", flush=True)
    print(f"  [LOCAL_WORKER] GPU        = {gpu_name}", flush=True)
    print(f"  [LOCAL_WORKER] CUDA       = {cuda_available}", flush=True)
    print(f"  [LOCAL_WORKER] Whisper    = {whisper_model} on {whisper_device}", flush=True)
    print(f"  [LOCAL_WORKER] FFmpeg GPU = {ffmpeg_nvenc} (h264_nvenc)", flush=True)
    print(f"  [LOCAL_WORKER] Poll every = {POLL_INTERVAL}s", flush=True)

    if whisper_device == "cpu":
        print("", flush=True)
        print("  ⚠️  WARNING: Worker will use CPU for transcription.", flush=True)
        print("     Set WHISPER_DEVICE=cuda to force GPU if you have an NVIDIA card.", flush=True)
        print("     Transcription will be SLOW without GPU.", flush=True)

    print("", flush=True)
    print("  [LOCAL_WORKER] Worker Ready — polling for jobs...", flush=True)
    print("=" * 55, flush=True)
    print("", flush=True)

    return cuda_available, whisper_device


# ══════════════════════════════════════════════════════════════════════════════
# Railway API helpers
# ══════════════════════════════════════════════════════════════════════════════

def _poll_next_job() -> dict | None:
    """GET /api/jobs/next — returns job dict or None if queue is empty."""
    try:
        resp = requests.get(
            f"{RAILWAY_URL}/api/jobs/next",
            headers=_HEADERS,
            timeout=10,
        )
        if resp.status_code == 204:
            return None  # No pending jobs
        if resp.status_code == 401:
            print("[LOCAL_WORKER] ERROR: 401 Unauthorized — check WORKER_SECRET", flush=True)
            return None
        resp.raise_for_status()
        data = resp.json()
        if not data.get("job_id"):
            return None
        return data
    except requests.exceptions.ConnectionError:
        print(f"[LOCAL_WORKER] Cannot reach Railway at {RAILWAY_URL} — retrying...", flush=True)
        return None
    except Exception as e:
        print(f"[LOCAL_WORKER] Poll error: {e}", flush=True)
        return None


def _complete_job(job_id: str, clips: list):
    """POST /api/jobs/{id}/complete"""
    try:
        resp = requests.post(
            f"{RAILWAY_URL}/api/jobs/{job_id}/complete",
            headers=_HEADERS,
            json={"clips": clips},
            timeout=30,
        )
        resp.raise_for_status()
        print(f"[LOCAL_WORKER] ✅ Marked complete: {job_id} ({len(clips)} clips)", flush=True)
    except Exception as e:
        print(f"[LOCAL_WORKER] ERROR marking complete {job_id}: {e}", flush=True)


def _fail_job(job_id: str, error: str):
    """POST /api/jobs/{id}/failed"""
    try:
        resp = requests.post(
            f"{RAILWAY_URL}/api/jobs/{job_id}/failed",
            headers=_HEADERS,
            json={"error": str(error)[:1000]},
            timeout=15,
        )
        resp.raise_for_status()
        print(f"[LOCAL_WORKER] ❌ Marked failed: {job_id} — {error[:120]}", flush=True)
    except Exception as e:
        print(f"[LOCAL_WORKER] ERROR marking failed {job_id}: {e}", flush=True)


# ══════════════════════════════════════════════════════════════════════════════
# Cloudinary upload
# ══════════════════════════════════════════════════════════════════════════════

def _configure_cloudinary() -> bool:
    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME")
    api_key    = os.getenv("CLOUDINARY_API_KEY")
    api_secret = os.getenv("CLOUDINARY_API_SECRET")
    if not (cloud_name and api_key and api_secret):
        return False
    try:
        import cloudinary
        cloudinary.config(cloud_name=cloud_name, api_key=api_key, api_secret=api_secret)
        return True
    except ImportError:
        return False


def _upload_clip_to_cloudinary(local_path: str) -> str | None:
    try:
        import cloudinary.uploader
        result = cloudinary.uploader.upload(
            local_path,
            resource_type="video",
            folder="hotshort_clips",
        )
        return result.get("secure_url")
    except Exception as e:
        print(f"[LOCAL_WORKER] Cloudinary upload failed: {e}", flush=True)
        return None


# ══════════════════════════════════════════════════════════════════════════════
# Core processing pipeline
# ══════════════════════════════════════════════════════════════════════════════

def _process_job(job: dict, cloudinary_ok: bool):
    job_id      = job["job_id"]
    youtube_url = job.get("youtube_url") or job.get("video_url", "")
    is_free     = job.get("is_free_user", False)

    print(f"[LOCAL_WORKER] 🎬 Processing job {job_id}: {youtube_url[:80]}", flush=True)

    with tempfile.TemporaryDirectory() as tmp:
        video_path = os.path.join(tmp, "video.mp4")

        # ── Step 1: Download via yt-dlp (residential IP = no YouTube block) ──
        print(f"[LOCAL_WORKER] Downloading video...", flush=True)
        cookies_path = os.path.join(BASE_DIR, "cookies.txt")
        ydl_opts = [
            "yt-dlp",
            "-f", "best[ext=mp4]/best",
            "--merge-output-format", "mp4",
            "-o", video_path,
            "--quiet",
            "--no-warnings",
        ]
        if os.path.exists(cookies_path):
            ydl_opts += ["--cookies", cookies_path]
        ydl_opts.append(youtube_url)

        result = subprocess.run(ydl_opts, capture_output=True, timeout=300)
        if result.returncode != 0:
            err = result.stderr.decode("utf-8", errors="ignore")[-500:]
            raise RuntimeError(f"yt-dlp failed: {err}")

        if not os.path.exists(video_path) or os.path.getsize(video_path) < 1000:
            raise RuntimeError("Downloaded file is missing or too small")

        print(f"[LOCAL_WORKER] Download complete: {os.path.getsize(video_path) // (1024*1024)}MB", flush=True)

        # ── Step 2: Orchestrate (full pipeline — orchestrator + Groq cortex) ──
        print(f"[LOCAL_WORKER] Running orchestrator...", flush=True)
        try:
            from viral_finder.orchestrator import orchestrate
        except Exception as e:
            raise RuntimeError(f"Failed to import orchestrator: {e}")

        from utils.clipper import format_viral_clips, get_video_duration

        clips = orchestrate(
            video_path,
            top_k=int(os.getenv("HS_ORCH_TOP_K", "8")),
            prefer_gpu=True,
            use_cache=True,
            allow_fallback=False,
            pipeline_mode=os.getenv("HS_ORCH_PIPELINE_MODE", "staged"),
        )

        video_duration = get_video_duration(video_path)
        # Trust dynamic arc-based boundaries and do not apply format_viral_clips padding
        print(f"[LOCAL_WORKER] Orchestration done: {len(clips)} clips", flush=True)

        # ── Step 3: Cut + Edit + Upload ───────────────────────────────────────
        print(f"[LOCAL_WORKER] Uploading clips to Cloudinary...", flush=True)

        # Lazy load world_class_editor
        _editor_cls = None
        _config_cls = None
        _wce_enabled = os.getenv("HS_WORKER_EDITOR_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")
        if _wce_enabled:
            try:
                from effects.world_class_editor import ClipEditor, ClipEditConfig
                _editor_cls = ClipEditor
                _config_cls = ClipEditConfig
                print("[LOCAL_WORKER] world_class_editor loaded ✅", flush=True)
            except Exception as e:
                print(f"[LOCAL_WORKER] world_class_editor load failed (raw cuts): {e}", flush=True)

        _full_transcript = None
        if clips and isinstance(clips[0], dict):
            _full_transcript = clips[0].get("transcript") or clips[0].get("captions")

        _editor_work_dir = os.path.join(tmp, "wce_work")
        os.makedirs(_editor_work_dir, exist_ok=True)

        processed_clips = []
        for i, clip in enumerate(clips):
            start = float(clip.get("start", 0))
            end   = float(clip.get("end", start + 30))
            raw_path = os.path.join(tmp, f"clip_{i}_{int(start)}_{int(end)}.mp4")

            # Raw ffmpeg cut
            cut_res = subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-ss", str(start), "-to", str(end),
                    "-i", video_path,
                    "-c", "copy",
                    "-avoid_negative_ts", "make_zero",
                    raw_path,
                ],
                capture_output=True, timeout=120
            )
            if cut_res.returncode != 0:
                print(f"[LOCAL_WORKER] ffmpeg cut failed for clip {i}", flush=True)
                processed_clips.append({**clip, "clip_url": None, "error": "ffmpeg_failed"})
                continue

            # Apply editor if available
            final_path = raw_path
            if _editor_cls and _config_cls:
                try:
                    edited_path = os.path.join(tmp, f"edited_{i}_{int(start)}_{int(end)}.mp4")
                    clip_transcript = clip.get("transcript") or clip.get("captions") or _full_transcript or []
                    clip_title = clip.get("opening_caption") or clip.get("title") or clip.get("text", "")

                    cortex_hints = None
                    if clip.get("cortex_enabled"):
                        cortex_hints = {
                            "cortex_enabled": True,
                            "opening_caption": clip.get("opening_caption", ""),
                            "title": clip.get("title", ""),
                            "hook_type": clip.get("hook_type", ""),
                            "cortex_score": clip.get("cortex_score", 0),
                            "learning_signal_for_hotshort": clip.get("learning_signal_for_hotshort", {}),
                            "editing_notes": clip.get("editing_notes", {}),
                        }

                    editor = _editor_cls(work_dir=_editor_work_dir)
                    cfg = _config_cls(
                        add_captions=True,
                        add_dynamic_overlays=True,
                        add_cta=True,
                        add_hashtags=True,
                        add_emojis=True,
                        enhance_visuals=True,
                        enhance_audio=True,
                        target_ratio="9:16",
                    )
                    edit_result = editor.enhance_pretrimmed_clip(
                        input_path=raw_path,
                        output_path=edited_path,
                        source_start=start,
                        source_end=end,
                        transcript=clip_transcript,
                        config=cfg,
                        clip_title=clip_title,
                        is_free=clip.get("is_free", False) or is_free,
                        cortex_hints=cortex_hints,
                    )
                    if edit_result and os.path.exists(edit_result.output_path):
                        final_path = edit_result.output_path
                        print(f"[LOCAL_WORKER] Editor done clip {i} (score={edit_result.engagement_score:.1f})", flush=True)
                    else:
                        print(f"[LOCAL_WORKER] Editor output missing clip {i}, using raw", flush=True)
                except Exception as edit_err:
                    print(f"[LOCAL_WORKER] Editor error clip {i}: {edit_err}", flush=True)

            # Upload to Cloudinary
            clip_url = None
            if cloudinary_ok:
                clip_url = _upload_clip_to_cloudinary(final_path)
                if clip_url:
                    print(f"[LOCAL_WORKER] Uploaded clip {i}: {clip_url[:60]}...", flush=True)
                else:
                    print(f"[LOCAL_WORKER] Cloudinary upload returned None for clip {i}", flush=True)
            else:
                print(f"[LOCAL_WORKER] Cloudinary not configured — clip {i} has no URL", flush=True)

            processed_clips.append({**clip, "clip_url": clip_url})

        return processed_clips


# ══════════════════════════════════════════════════════════════════════════════
# Main polling loop
# ══════════════════════════════════════════════════════════════════════════════

def main():
    _print_startup_banner()
    cloudinary_ok = _configure_cloudinary()
    if not cloudinary_ok:
        print("[LOCAL_WORKER] ⚠️  Cloudinary not configured — clips will have no URLs", flush=True)

    while True:
        print(f"[LOCAL_WORKER] polling...", flush=True)

        job = _poll_next_job()

        if job is None:
            time.sleep(POLL_INTERVAL)
            continue

        job_id = job["job_id"]
        print(f"[LOCAL_WORKER] 📥 Job received: {job_id}", flush=True)

        try:
            clips = _process_job(job, cloudinary_ok=cloudinary_ok)
            _complete_job(job_id, clips)
        except Exception as e:
            err_msg = str(e)
            tb = traceback.format_exc()
            print(f"[LOCAL_WORKER] 💥 Job {job_id} failed:\n{tb}", flush=True)
            _fail_job(job_id, err_msg)

        # Small sleep after processing before next poll
        time.sleep(2)


if __name__ == "__main__":
    main()
