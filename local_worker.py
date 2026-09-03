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
os.environ["HS_DEBUG_FRAMES"] = "./debug_out"

import sys

# Inject local bundled bin/ directory (containing dav1d FFmpeg) into PATH
# This guarantees that ffmpeg and ffprobe execute our optimized build, not system defaults.
_local_bin = os.path.abspath(os.path.join(os.path.dirname(__file__), "bin"))
if os.path.isdir(_local_bin):
    os.environ["PATH"] = _local_bin + os.pathsep + os.environ.get("PATH", "")

import json
import time
import tempfile
import subprocess
import traceback

# ── Pipeline benchmark (one report per job) ────────────────────────────────
try:
    from pipeline_benchmark import JobBenchmark as _JobBenchmark
except Exception as _be:
    class _JobBenchmark:  # silent no-op fallback
        def __init__(self, *a, **kw): pass
        def begin(self, *a): pass
        def finish(self, *a): pass
        def save(self): pass

import requests
from dotenv import load_dotenv

try:
    from effects.insightface_detector import detect_faces_insightface, is_insightface_available
    _INSIGHTFACE_ENABLED = is_insightface_available()
except Exception:
    _INSIGHTFACE_ENABLED = False
    detect_faces_insightface = None

try:
    from effects.mediapipe_detector import detect_faces_mediapipe, is_mediapipe_available
    _MEDIAPIPE_ENABLED = True
except ImportError:
    _MEDIAPIPE_ENABLED = False
    detect_faces_mediapipe = None

def _detect_faces_best(frame_bgr, conf_threshold=0.45, min_size=(40, 40)):
    if _INSIGHTFACE_ENABLED and detect_faces_insightface is not None:
        result = detect_faces_insightface(frame_bgr, conf_threshold=conf_threshold, min_size=min_size)
        if result:
            return result
    if _MEDIAPIPE_ENABLED and detect_faces_mediapipe is not None:
        return detect_faces_mediapipe(frame_bgr, conf_threshold=conf_threshold, min_size=min_size)
    return []


# ── Load local env ────────────────────────────────────────────────────────────
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Always load .env first for global configs
_default_env = os.path.join(BASE_DIR, ".env")
if os.path.exists(_default_env):
    load_dotenv(_default_env)
    print(f"[LOCAL_WORKER] Loaded env from .env", flush=True)

# Then override with .env.local if present
_local_env = os.path.join(BASE_DIR, ".env.local")
if os.path.exists(_local_env):
    load_dotenv(_local_env, override=True)
    print(f"[LOCAL_WORKER] Overrode env with .env.local", flush=True)

# Finally override with .env.worker if present
_worker_env = os.path.join(BASE_DIR, ".env.worker")
if os.path.exists(_worker_env):
    load_dotenv(_worker_env, override=True)
    print(f"[LOCAL_WORKER] Overrode env with .env.worker", flush=True)



# ── Config ────────────────────────────────────────────────────────────────────
RAILWAY_URL   = os.getenv("RAILWAY_URL", "").rstrip("/")
WORKER_SECRET = os.getenv("WORKER_SECRET", "")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "5"))

# _LOCAL_MODE is set True by --local flag in main().
# When True: Railway checks are skipped, clips saved to scratch/hotshort_out/
_LOCAL_MODE   = False
_LOCAL_OUT_DIR = os.path.join(BASE_DIR, "scratch", "hotshort_out")

# Railway checks deferred to main() so --local can bypass them.
_HEADERS = {
    "X-Worker-Secret": WORKER_SECRET,
    "Content-Type": "application/json",
}


def _local_save_clip(src_path: str, clip_index: int, start: float, end: float) -> str:
    """Copy finished clip to scratch/hotshort_out/ and return saved path."""
    import shutil
    os.makedirs(_LOCAL_OUT_DIR, exist_ok=True)
    name = f"clip_{clip_index}_{int(start)}_{int(end)}.mp4"
    dst  = os.path.join(_LOCAL_OUT_DIR, name)
    shutil.copy2(src_path, dst)
    sz = os.path.getsize(dst) / 1e6
    print(f"[LOCAL_SAVE] clip_{clip_index} -> {dst}  ({sz:.1f} MB)", flush=True)
    return dst



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
        clips = _json_safe(clips)
        resp = requests.post(
            f"{RAILWAY_URL}/api/jobs/{job_id}/complete",
            headers=_HEADERS,
            json={"clips": clips},
            timeout=30,
        )
        if resp.status_code == 404:
            print(f"[LOCAL_WORKER] ⚠️ Server database reset detected (404). Job {job_id} lost on server, but clips are saved locally.", flush=True)
            return
        resp.raise_for_status()
        print(f"[LOCAL_WORKER] ✅ Marked complete: {job_id} ({len(clips)} clips)", flush=True)
    except Exception as e:
        print(f"[LOCAL_WORKER] ERROR marking complete {job_id}: {e}", flush=True)


def _json_safe(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return str(value)


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

_cloudinary_validated = None  # None = untested; True/False cached per-process


def _configure_cloudinary() -> bool:
    """Configure Cloudinary and validate with a one-time ping.

    The ping runs exactly once per worker process and the result is cached.
    This avoids spending 6+ seconds per clip on a network timeout when the
    cloud_name is disabled or credentials are wrong.
    """
    global _cloudinary_validated
    if _cloudinary_validated is not None:
        return _cloudinary_validated

    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME")
    api_key    = os.getenv("CLOUDINARY_API_KEY")
    api_secret = os.getenv("CLOUDINARY_API_SECRET")
    if not (cloud_name and api_key and api_secret):
        print("[LOCAL_WORKER] Cloudinary: missing credentials — upload disabled", flush=True)
        _cloudinary_validated = False
        return False
    try:
        import cloudinary
        import cloudinary.api
        cloudinary.config(cloud_name=cloud_name, api_key=api_key, api_secret=api_secret)
        cloudinary.api.ping()  # fast — raises AuthorizationRequired if cloud disabled
        print("[LOCAL_WORKER] Cloudinary OK — upload enabled", flush=True)
        _cloudinary_validated = True
        return True
    except ImportError:
        print("[LOCAL_WORKER] Cloudinary: library not installed — upload disabled", flush=True)
        _cloudinary_validated = False
        return False
    except Exception as e:
        print(f"[LOCAL_WORKER] Cloudinary ping failed ({e}) — upload disabled for this run", flush=True)
        _cloudinary_validated = False
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


def _upload_clip_to_railway(local_path: str, job_id: str) -> str | None:
    """
    Fallback: Upload clip directly to Railway when Cloudinary is unavailable.
    Uses POST /api/jobs/{job_id}/upload_clip (multipart).
    Returns a public URL served by Railway's /static/clip_files/ handler.
    """
    try:
        filename = os.path.basename(local_path)
        with open(local_path, "rb") as fh:
            resp = requests.post(
                f"{RAILWAY_URL}/api/jobs/{job_id}/upload_clip",
                headers={"X-Worker-Secret": WORKER_SECRET},
                files={"file": (filename, fh, "video/mp4")},
                timeout=120,
            )
        resp.raise_for_status()
        clip_url = resp.json().get("clip_url")
        if clip_url:
            print(f"[LOCAL_WORKER] ✅ Railway fallback upload OK: {clip_url}", flush=True)
        return clip_url
    except Exception as e:
        print(f"[LOCAL_WORKER] Railway fallback upload failed: {e}", flush=True)
        return None



# ──────────────────────────────────────────────────────────────────────────────
# RapidAPI YouTube Downloader  (youtube-media-downloader.p.rapidapi.com)
# Strategy: fetch 720p video-only + best m4a audio → FFmpeg merge for sync
# ──────────────────────────────────────────────────────────────────────────────

_RAPID_DL_HOST = "youtube-media-downloader.p.rapidapi.com"


def _extract_video_id(youtube_url: str) -> str:
    """
    Robustly extract YouTube video ID from any URL variant:
      https://youtu.be/VIDEO_ID
      https://www.youtube.com/watch?v=VIDEO_ID
      https://youtube.com/shorts/VIDEO_ID
      https://m.youtube.com/watch?v=VIDEO_ID&...
    """
    import re
    patterns = [
        r"(?:v=|/v/|youtu\.be/|/embed/|/shorts/)([A-Za-z0-9_-]{11})",
    ]
    for pat in patterns:
        m = re.search(pat, youtube_url)
        if m:
            return m.group(1)
    raise ValueError(f"Cannot extract video ID from URL: {youtube_url}")


def _rapidapi_fetch_streams(video_id: str) -> dict:
    """
    Call /v2/video/details to get all available stream URLs.
    Returns the raw API response dict.
    """
    api_key = os.environ.get("RAPIDAPI_KEY", "")
    if not api_key:
        raise RuntimeError("RAPIDAPI_KEY env var is not set")

    headers = {
        "Content-Type": "application/json",
        "x-rapidapi-host": _RAPID_DL_HOST,
        "x-rapidapi-key": api_key,
    }
    resp = requests.get(
        f"https://{_RAPID_DL_HOST}/v2/video/details",
        params={"videoId": video_id},
        headers=headers,
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"RapidAPI /v2/video/details returned {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    if data.get("errorId") and data["errorId"] not in ("Error.None", "", None, "None", "Success"):
        raise RuntimeError(f"RapidAPI error: {data.get('errorId')} — {data.get('errorMessage', '')}")
    return data


def _pick_best_streams(data: dict) -> tuple:
    """
    Choose the best video stream + best audio stream.

    Priority for VIDEO (no audio):
      720p H264 mp4  >  720p any mp4  >  480p H264  >  480p mp4  >  360p mp4

    H264 (avc1) is STRONGLY preferred over AV1 because:
      - H264 has NVDEC hardware decode path on GPU (AV1 does NOT)
      - AV1 forces CPU software decode, which dominates render time
      - H264 decode: ~1-4s. AV1 software decode: ~15-20s per clip.

    Priority for AUDIO:
      m4a  >  weba (highest bitrate wins)

    Special case: if 360p mp4 with hasAudio=True exists AND no separate audio
    stream found, return (360p_stream, None) to signal single-file download.

    Returns: (video_stream_dict, audio_stream_dict_or_None)
    """
    videos = data.get("videos", {})
    video_items = videos if isinstance(videos, list) else videos.get("items", [])

    audios = data.get("audios", {})
    audio_items = audios if isinstance(audios, list) else audios.get("items", [])

    # ── Pick video stream ──────────────────────────────────────────────────────
    # Strongly prefer H264 (avc1) over AV1 — H264 has NVDEC GPU path, AV1 does not.
    target_heights = [720, 480, 360]
    video_stream = None

    # Pass 1: Look for H264 mp4 across all heights first (Best for GPU)
    for height in target_heights:
        for v in video_items:
            codec = (v.get("codec") or v.get("mimeType") or "").lower()
            is_h264 = "avc" in codec or "h264" in codec
            if (v.get("height") == height
                    and v.get("extension") == "mp4"
                    and is_h264
                    and not v.get("hasAudio", True)
                    and v.get("url")):
                video_stream = v
                print(f"[LOCAL_WORKER] Selected H264 stream: {height}p (NVDEC capable)", flush=True)
                break
        if video_stream:
            break

    # Pass 2: If no H264 found, fallback to any mp4 (might be AV1)
    if not video_stream:
        for height in target_heights:
            for v in video_items:
                if (v.get("height") == height
                        and v.get("extension") == "mp4"
                        and not v.get("hasAudio", True)
                        and v.get("url")):
                    video_stream = v
                    codec = (v.get("codec") or v.get("mimeType") or "unknown").lower()
                    print(f"[LOCAL_WORKER] Selected {height}p stream codec={codec} (H264 not available)", flush=True)
                    break
            if video_stream:
                break

    # Pass 3: Last resort, any extension
    if not video_stream:
        for height in target_heights:
            for v in video_items:
                if (v.get("height") == height
                        and not v.get("hasAudio", True)
                        and v.get("url")):
                    video_stream = v
                    break
            if video_stream:
                break

    # Fallback: 360p mp4 WITH audio baked in (single-file, no merge needed)
    if not video_stream:
        for v in video_items:
            if (v.get("height") == 360
                    and v.get("extension") == "mp4"
                    and v.get("hasAudio")
                    and v.get("url")):
                print("[LOCAL_WORKER] No video-only stream found — using 360p+audio single file", flush=True)
                return v, None  # single-file path, skip merge

    if not video_stream:
        raise RuntimeError("No suitable video stream found from RapidAPI")

    # ── Pick audio stream ──────────────────────────────────────────────────────
    # Prefer m4a (AAC container, direct copy in mp4), then weba
    audio_stream = None
    for ext_pref in ("m4a", "weba"):
        candidates = [a for a in audio_items if a.get("extension") == ext_pref and a.get("url")]
        if candidates:
            # Sort by size (highest quality)
            candidates.sort(key=lambda a: a.get("size", 0), reverse=True)
            
            # 1. Prefer explicitly marked 'original' tracks
            original_candidates = [c for c in candidates if "acont%3Doriginal" in c.get("url", "") or "acont=original" in c.get("url", "")]
            if original_candidates:
                audio_stream = original_candidates[0]
                break
                
            # 2. Avoid explicitly marked 'dubbed' tracks
            non_dubbed = [c for c in candidates if "acont%3Ddubbed" not in c.get("url", "") and "acont=dubbed" not in c.get("url", "")]
            if non_dubbed:
                audio_stream = non_dubbed[0]
                break
                
            # 3. Fallback to largest size
            audio_stream = candidates[0]
            break

    if not audio_stream:
        raise RuntimeError("No suitable audio stream found from RapidAPI")

    return video_stream, audio_stream


def _stream_download(url: str, dest_path: str, label: str):
    """
    Download a stream URL to dest_path using parallel chunked downloading.
    Bypasses YouTube's per-connection bandwidth throttling (which causes slow DLs).
    """
    import concurrent.futures
    import threading

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.youtube.com/",
        "Origin": "https://www.youtube.com",
    }
    
    # Get total file size
    resp = requests.get(url, headers=headers, stream=True, timeout=20)
    if resp.status_code not in (200, 206):
        raise RuntimeError(f"{label} download failed: HTTP {resp.status_code}")
        
    total = int(resp.headers.get("Content-Length", 0))
    if total == 0 or resp.headers.get("Accept-Ranges") != "bytes":
        # Fallback to normal download if server doesn't support ranges
        with open(dest_path, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=512 * 1024):
                if chunk:
                    fh.write(chunk)
        print(f"[LOCAL_WORKER] {label}: done", flush=True)
        return
        
    resp.close()

    chunk_size = 2 * 1024 * 1024  # 2MB chunks
    chunks = [(i, min(i + chunk_size - 1, total - 1)) for i in range(0, total, chunk_size)]
    downloaded = 0
    last_pct = -1
    lock = threading.Lock()

    # Pre-allocate file
    with open(dest_path, "wb") as f:
        f.truncate(total)

    with open(dest_path, "r+b") as fh:
        def download_chunk(start, end):
            nonlocal downloaded, last_pct
            for attempt in range(3):
                try:
                    range_headers = headers.copy()
                    range_headers["Range"] = f"bytes={start}-{end}"
                    r = requests.get(url, headers=range_headers, timeout=30)
                    r.raise_for_status()
                    data = r.content
                    with lock:
                        fh.seek(start)
                        fh.write(data)
                        downloaded += len(data)
                        pct = int(downloaded / total * 100)
                        if pct - last_pct >= 20:
                            print(f"[LOCAL_WORKER] {label}: {pct}% ({downloaded // (1024*1024)}MB)", flush=True)
                            last_pct = pct
                    return True
                except Exception:
                    time.sleep(1)
            raise RuntimeError(f"Failed to download chunk {start}-{end}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(download_chunk, s, e) for s, e in chunks]
            for f in concurrent.futures.as_completed(futures):
                f.result()  # raise if chunk failed

    size_mb = os.path.getsize(dest_path) / (1024 * 1024)
    print(f"[LOCAL_WORKER] {label}: done ({size_mb:.1f} MB)", flush=True)


def _ffmpeg_merge_video_audio(video_path: str, audio_path: str, output_path: str):
    """
    Merge a video-only stream + audio-only stream into a single mp4.

    Key flags for PERFECT sync:
      -map 0:v:0        → take video track from first input (video file)
      -map 1:a:0        → take audio track from second input (audio file)
      -c:v copy         → NO video re-encode — preserves exact frame timing
      -c:a aac          → transcode audio to AAC (mp4 container requirement)
      -af aresample=async=1:min_hard_comp=0.100000:first_pts=0
                        → fix any PTS gaps / drift — keeps audio locked to video
      -movflags +faststart → moov atom at front (better for streaming)
      -avoid_negative_ts make_zero → clamp any negative timestamps to 0
    """
    cmd = [
        "ffmpeg", "-y",
        "-threads", "16",           # [OPTIMIZATION] Max parallel threads for reading/writing/audio-encoding
        "-i", video_path,           # input 0: video-only
        "-i", audio_path,           # input 1: audio-only
        "-map", "0:v:0",            # explicit: take video stream from file 0
        "-map", "1:a:0",            # explicit: take audio stream from file 1
        "-c:v", "copy",             # video: no re-encode (frame-perfect, fastest)
        "-c:a", "copy",             # audio: no re-encode (instantaneous, 100% original quality)
        "-avoid_negative_ts", "make_zero",
        # "-movflags", "+faststart",  # [OPTIMIZATION] REMOVED! This caused a massive I/O delay at the end
        output_path,
    ]
    print("[LOCAL_WORKER] FFmpeg merge: video + audio → final mp4", flush=True)
    result = subprocess.run(cmd, capture_output=True, timeout=300)
    if result.returncode != 0:
        err = result.stderr.decode("utf-8", errors="replace")[-800:]
        raise RuntimeError(f"FFmpeg merge failed:\n{err}")
    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"[LOCAL_WORKER] Merge complete: {size_mb:.1f} MB -> {output_path}", flush=True)


def _browser_cookie_error(stderr: str) -> bool:
    """Return True if stderr looks like a cookie/auth failure (should try next strategy)."""
    patterns = (
        "dpapi", "failed to decrypt", "cookies-from-browser",
        "keyring", "could not decrypt", "unable to read cookies",
        # 403 = YouTube refused the request -- almost always stale/missing cookies
        "http error 403", "403: forbidden", "forbidden",
        "sign in to confirm", "this video is unavailable",
    )
    low = stderr.lower()
    return any(p in low for p in patterns)


def _auto_refresh_cookies() -> bool:
    """Export fresh cookies from Firefox into cookies.txt before each download."""
    cookies_file = os.path.join(os.getcwd(), "cookies.txt")

    # Remove any existing file that may be in wrong/corrupt format
    # yt-dlp refuses to overwrite a file it can't parse as Netscape cookies
    if os.path.exists(cookies_file):
        try:
            os.remove(cookies_file)
        except Exception:
            pass

    print("[LOCAL_WORKER] Auto-refreshing cookies from Firefox...", flush=True)
    try:
        result = subprocess.run(
            [
                sys.executable, "-m", "yt_dlp",
                "--cookies-from-browser", "firefox",
                "--cookies", cookies_file,
                "--skip-download", "--quiet",
                "https://www.youtube.com",
            ],
            capture_output=True, timeout=30,
        )
        if result.returncode == 0 and os.path.exists(cookies_file) and os.path.getsize(cookies_file) > 100:
            sz = os.path.getsize(cookies_file) / 1024
            print(f"[LOCAL_WORKER] Cookies refreshed from Firefox ({sz:.0f} KB) -> cookies.txt", flush=True)
            return True
        err = result.stderr.decode("utf-8", errors="replace")[:200]
        print(f"[LOCAL_WORKER] Firefox cookie refresh failed: {err}", flush=True)
        return False
    except Exception as e:
        print(f"[LOCAL_WORKER] Cookie refresh error: {e}", flush=True)
        return False



def _download_via_ytdlp(youtube_url: str, dest_path: str):
    """
    Download using local yt-dlp. Cookie strategy (tried in order):
      1. Auto-export fresh cookies from Firefox -> cookies.txt
      2. --cookies cookies.txt
      3. --cookies-from-browser firefox  (direct live read)
      4. --cookies-from-browser chrome
      5. No cookies (last resort)

    JS runtime: Deno (~/.deno/bin/deno.exe) + EJS remote component so yt-dlp
    can solve YouTube's n-challenge. Without this every client returns 403.
    Player client forced to web_embedded,default (android_vr always 403s
    without a GVS PO token).
    """
    print(f"[LOCAL_WORKER] Downloading via yt-dlp to {dest_path}", flush=True)

    # Always refresh cookies from Firefox first
    _auto_refresh_cookies()

    cookies_file = os.path.join(os.getcwd(), "cookies.txt")
    has_cookies = os.path.exists(cookies_file) and os.path.getsize(cookies_file) > 100

    # ── Locate Deno for n-challenge solving ───────────────────────────────────
    _deno_default = os.path.join(os.path.expanduser("~"), ".deno", "bin", "deno.exe")
    _deno_path = os.getenv("HS_DENO_PATH", _deno_default if os.path.exists(_deno_default) else "")
    _js_runtime_args = (
        ["--js-runtimes", f"deno:{_deno_path}", "--remote-components", "ejs:github"]
        if _deno_path
        else []
    )
    if _deno_path:
        print(f"[LOCAL_WORKER] yt-dlp JS runtime: deno @ {_deno_path}", flush=True)
    else:
        print("[LOCAL_WORKER] WARNING: Deno not found — n-challenge may fail (403)", flush=True)

    # web_embedded avoids android_vr which always 403s without GVS PO token
    _player_client_args = ["--extractor-args", "youtube:player_client=web_embedded,default"]

    def _base_cmd(extra_args):
        return [
            sys.executable, "-m", "yt_dlp",
            *_js_runtime_args,
            *_player_client_args,
            *extra_args,
            "--format", "bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "--merge-output-format", "mp4",
            "--retries", "10",
            "--fragment-retries", "10",
            "--retry-sleep", "3",
            "--socket-timeout", "60",
            "--no-warnings",
            "--output", dest_path,
            youtube_url,
        ]

    attempts = []
    if has_cookies:
        attempts.append((["--cookies", cookies_file], "cookies.txt"))
    attempts += [
        (["--cookies-from-browser", "firefox"], "firefox"),
        (["--cookies-from-browser", "chrome"],  "chrome"),
        ([],                                     "no-cookies"),
    ]


    last_err = "unknown error"
    for extra_args, label in attempts:
        cmd = _base_cmd(extra_args)
        print(f"[LOCAL_WORKER] yt-dlp attempt [{label}]", flush=True)
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode == 0:
            break
        last_err = result.stderr.decode("utf-8", errors="replace")
        if _browser_cookie_error(last_err):
            print(
                f"[LOCAL_WORKER] yt-dlp [{label}] auth/cookie error -- trying next\n"
                f"  {last_err.splitlines()[0] if last_err else ''}",
                flush=True,
            )
            continue
        # Hard error (network, bad URL, codec) -- fail immediately
        raise RuntimeError(f"yt-dlp failed [{label}]: {last_err}")
    else:
        raise RuntimeError(f"yt-dlp failed (all strategies exhausted): {last_err}")

    if not os.path.exists(dest_path) or os.path.getsize(dest_path) < 1000:
        raise RuntimeError("yt-dlp completed but output file is missing or empty.")


def _download_via_api(youtube_url: str, dest_path: str):
    """
    Download a YouTube video to dest_path using youtube-media-downloader RapidAPI.

    Flow:
      1. Extract video ID from URL
      2. Fetch all available streams via /v2/video/details
      3. Pick best 720p video-only stream + best m4a audio stream
      4. Download both to temp files
      5. FFmpeg merge → dest_path (perfect audio/video sync)

    Falls back to 360p+audio single file if no separate streams available.
    """
    # ── 1. Extract video ID ────────────────────────────────────────────────────
    video_id = _extract_video_id(youtube_url)
    print(f"[LOCAL_WORKER] RapidAPI download: videoId={video_id}", flush=True)

    # ── 2. Fetch stream info ───────────────────────────────────────────────────
    print("[LOCAL_WORKER] Fetching stream URLs from RapidAPI...", flush=True)
    data = _rapidapi_fetch_streams(video_id)
    title = data.get("title", "unknown")[:60]
    duration = data.get("lengthSeconds", "?")
    print(f"[LOCAL_WORKER] Title: {title} | Duration: {duration}s", flush=True)

    # ── 3. Pick streams ────────────────────────────────────────────────────────
    video_stream, audio_stream = _pick_best_streams(data)
    v_quality = video_stream.get("quality", "?")
    v_size_mb = round(video_stream.get("size", 0) / 1024 / 1024, 1)
    print(f"[LOCAL_WORKER] Video stream: {v_quality} {video_stream.get('extension')} ({v_size_mb} MB)", flush=True)

    tmp_dir = os.path.dirname(dest_path)

    # ── 4a. Single-file path (360p with audio) ─────────────────────────────────
    if audio_stream is None:
        print("[LOCAL_WORKER] Single-file download (360p+audio, no merge needed)", flush=True)
        _stream_download(video_stream["url"], dest_path, "360p+audio")
        return

    # ── 4b. Separate video + audio download ────────────────────────────────────
    a_size_mb = round(audio_stream.get("size", 0) / 1024 / 1024, 1)
    print(f"[LOCAL_WORKER] Audio stream: {audio_stream.get('extension')} ({a_size_mb} MB)", flush=True)

    video_tmp  = os.path.join(tmp_dir, f"_raw_video_{video_id}.{video_stream.get('extension','mp4')}")
    audio_tmp  = os.path.join(tmp_dir, f"_raw_audio_{video_id}.{audio_stream.get('extension','m4a')}")

    print("[LOCAL_WORKER] Downloading video stream...", flush=True)
    _stream_download(video_stream["url"], video_tmp, "video")

    print("[LOCAL_WORKER] Downloading audio stream...", flush=True)
    _stream_download(audio_stream["url"], audio_tmp, "audio")

    # ── 5. FFmpeg merge ────────────────────────────────────────────────────────
    _ffmpeg_merge_video_audio(video_tmp, audio_tmp, dest_path)

    # Cleanup temp streams
    for p in (video_tmp, audio_tmp):
        try:
            os.remove(p)
        except OSError:
            pass

# ══════════════════════════════════════════════════════════════════════════════
# Core processing pipeline
# ══════════════════════════════════════════════════════════════════════════════

def _apply_distribution_branding(input_path: str, output_path: str) -> bool:
    """
    Apply cinematic blur background + watermark + outro in a SINGLE FFmpeg pass.

    OPTIMIZATION: Previously this was 2 separate NVENC encodes (watermark then outro concat).
    Now merged into 1 filtergraph — saves 1 full GPU encode (~15-20s) per clip.
    """
    outro_path = os.path.join(BASE_DIR, "static", "branding", "outro.mp4")
    watermark_path = os.path.join(BASE_DIR, "static", "branding", "logo.png")
    has_outro = os.path.exists(outro_path) and os.path.getsize(outro_path) > 1000

    ffmpeg_nvenc = False
    try:
        r = subprocess.run(
            ["ffmpeg", "-hide_banner", "-f", "lavfi", "-i",
             "nullsrc=s=64x64:d=0.1", "-c:v", "h264_nvenc",
             "-preset", "fast", "-f", "null", "-"],
            capture_output=True, timeout=10,
        )
        ffmpeg_nvenc = r.returncode == 0
    except Exception:
        pass

    try:
        print(f"[LOCAL_WORKER] Branding (single pass): blur+watermark{'+ outro' if has_outro else ''}", flush=True)

        if has_outro:
            # ── SINGLE PASS: blur + watermark + outro concat ───────────────────
            filter_complex = (
                # Main clip: cinematic blur bg + centered video
                "[0:v]fps=30,split=2[blur][vid];"
                "[blur]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20[bg];"
                "[vid]scale=1080:1920:force_original_aspect_ratio=decrease[fg];"
                "[bg][fg]overlay=(W-w)/2:(H-h)/2[merged];"
                # Watermark overlay (forced even height with -2 to prevent NVENC -22 invalid argument)
                "[1:v]scale=180:-2,format=rgba,colorchannelmixer=aa=0.8[wm];"
                "[merged][wm]overlay=W-w-50:H-h-250,format=yuv420p,setsar=1[main_v];"
                # Outro: scale to match
                "[2:v]scale=1080:1920:force_original_aspect_ratio=decrease,"
                "pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,format=yuv420p[outro_v];"
                # Resample audio to 44.1kHz Stereo to prevent sample rate/channel layout concat failures
                "[0:a]aresample=44100,aformat=channel_layouts=stereo[main_a_res];"
                "[2:a]aresample=44100,aformat=channel_layouts=stereo[outro_a_res];"
                # Concat main + outro
                "[main_v][main_a_res][outro_v][outro_a_res]concat=n=2:v=1:a=1[v][a]"
            )
            cmd = [
                "ffmpeg", "-y",
                "-hwaccel", "auto",
                "-i", input_path,        # 0: main clip
                "-i", watermark_path,    # 1: logo.png
                "-i", outro_path,        # 2: outro.mp4
                "-filter_complex", filter_complex,
                "-map", "[v]", "-map", "[a]",
                "-c:v", "h264_nvenc" if ffmpeg_nvenc else "libx264",
                "-preset", "fast" if ffmpeg_nvenc else "veryfast",
                "-b:v", "5M",
                "-c:a", "aac",
                "-b:a", "128k",
                "-movflags", "+faststart",
                output_path
            ]
        else:
            # ── NO OUTRO: blur + watermark only (single pass) ──────────────────
            print(f"[LOCAL_WORKER] WARNING: Outro not found at {outro_path}. Watermark only.", flush=True)
            filter_complex = (
                "[0:v]fps=30,split=2[blur][vid];"
                "[blur]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20[bg];"
                "[vid]scale=1080:1920:force_original_aspect_ratio=decrease[fg];"
                "[bg][fg]overlay=(W-w)/2:(H-h)/2[merged];"
                "[1:v]scale=180:-2,format=rgba,colorchannelmixer=aa=0.8[wm];"
                "[merged][wm]overlay=W-w-50:H-h-250,format=yuv420p"
            )
            cmd = [
                "ffmpeg", "-y",
                "-hwaccel", "auto",
                "-i", input_path,
                "-i", watermark_path,
                "-filter_complex", filter_complex,
                "-c:v", "h264_nvenc" if ffmpeg_nvenc else "libx264",
                "-preset", "fast" if ffmpeg_nvenc else "veryfast",
                "-b:v", "5M",
                "-c:a", "copy",
                "-movflags", "+faststart",
                output_path
            ]

        result = subprocess.run(cmd, capture_output=True, timeout=300)
        if result.returncode != 0:
            if "h264_nvenc" in cmd:
                print(f"[LOCAL_WORKER] NVENC branding failed, retrying with CPU encode...", flush=True)
                cmd = [c.replace("h264_nvenc", "libx264") if c == "h264_nvenc" else c for c in cmd]
                cmd = [c.replace("fast", "veryfast") if c == "fast" else c for c in cmd]
                result = subprocess.run(cmd, capture_output=True, timeout=300)
            
            if result.returncode != 0:
                print(f"[LOCAL_WORKER] Branding failed: {result.stderr.decode('utf-8', errors='ignore')[-500:]}", flush=True)
                return False

        return True

    except Exception as e:
        print(f"[LOCAL_WORKER] Error in distribution branding: {e}", flush=True)
        return False


import queue
import threading
from concurrent.futures import ThreadPoolExecutor
import cv2
from effects.format_analyzer import analyze_video_format, DirectorMode, detect_faces_multi_haar
from frame_clustering import find_scene_segments


ENABLE_CLUSTER_SCAN = os.getenv("HS_ENABLE_CLUSTER_SCAN", "1").strip().lower() not in ("0", "false", "no", "off")
CLUSTER_HASH_THRESHOLD = max(0, int(os.getenv("HS_CLUSTER_HASH_THRESHOLD", "18") or 18))
MIN_CLUSTER_REDETECT_ATTEMPTS = max(0, int(os.getenv("HS_MIN_CLUSTER_REDETECT_ATTEMPTS", "2") or 2))
MIN_VALID_FACE_HEIGHT_RATIO = min(1.0, max(0.0, float(os.getenv("HS_MIN_FACE_HEIGHT_RATIO", "0.05") or 0.05)))

class FaceCache:
    def __init__(self, video_path: str, clips: list):
        self.video_path = video_path
        self.cache = {}
        self.clip_caches = {}
        self.clips = clips
        self._done = False
        if clips:
            self._precompute_clips_only(clips)
        else:
            self._done = True
        
    def _detect(self, frame):
        raw_mean = float(frame.mean())
        print(
            f"[DETECT_DEBUG] frame_shape={frame.shape} dtype={frame.dtype} "
            f"mean={raw_mean:.1f} min={frame.min()} max={frame.max()}",
            flush=True,
        )
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # ── PRIMARY: Unified Detector (InsightFace -> MediaPipe) ──
        if _INSIGHTFACE_ENABLED or _MEDIAPIPE_ENABLED:
            faces = _detect_faces_best(frame, conf_threshold=0.45, min_size=(40, 40))
            
            # Adjustment scan if score is low or no faces found
            if not faces or any(getattr(f, 'score', 1.0) < 0.65 for f in faces):
                gray_for_clahe = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
                enhanced_gray = clahe.apply(gray_for_clahe)
                enhanced_bgr = cv2.cvtColor(enhanced_gray, cv2.COLOR_GRAY2BGR)
                
                faces_retry = _detect_faces_best(enhanced_bgr, conf_threshold=0.45, min_size=(40, 40))
                # Only use retry if it found faces and they have better/equal scores
                if faces_retry and (not faces or max(getattr(f, 'score', 0) for f in faces_retry) > max(getattr(f, 'score', 0) for f in faces)):
                    faces = faces_retry
                    
            print(f"[DETECT_RAW] mediapipe_faces={len(faces)}", flush=True)
            return [
                {"x": float(f[0]), "y": float(f[1]), "w": float(f[2]), "h": float(f[3]), "score": getattr(f, 'score', 1.0)}
                for f in faces
            ]

        # ── FALLBACK: Haar ──
        # CLAHE: if frame is overexposed (gray_mean > 180), Haar cannot see contrast.
        # Locally normalise contrast before detection — recovers faces on blown-out segments.
        _OVEREXPOSED_THRESHOLD = 180
        clahe_applied = False
        if gray.mean() > _OVEREXPOSED_THRESHOLD:
            clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
            gray = clahe.apply(gray)
            clahe_applied = True

        faces = detect_faces_multi_haar(gray, cv2, scale_factor=1.15, min_neighbors=3, min_size=(40, 40))
        print(
            f"[DETECT_RAW] "
            f"gray_shape={gray.shape} gray_dtype={gray.dtype} "
            f"gray_mean={gray.mean():.1f} clahe={clahe_applied}",
            flush=True,
        )
        print(
            f"[DETECT_RAW] result_count={len(faces)} "
            "call_kwargs={'scaleFactor': 1.15, 'minNeighbors': 3, "
            "'minSize': (40, 40), 'mode': 'multi_cascade_haar'}",
            flush=True,
        )
        return [
            {"x": float(x), "y": float(y), "w": float(w), "h": float(h)}
            for x, y, w, h in faces
        ]


    @staticmethod
    def _valid_face_count(faces, frame_height, sampled_frame=None):
        """Match the editor's face-size/aspect/Laplacian safety floor.

        Mirrors is_valid_face() guards in world_class_editor so that
        whatever the editor would reject at runtime is ALSO rejected here
        in FaceCache — prevents bookshelf/text FPs from being stored.
        """
        count = 0
        for face in faces:
            h = face["h"]
            w = face["w"]
            score = face.get("score", 1.0)
            if score < 0.65:
                continue
            if h < frame_height * MIN_VALID_FACE_HEIGHT_RATIO:
                continue
            if not (0.7 <= h / max(1.0, w) <= 3.0):
                continue
            # Laplacian variance guard — same thresholds as editor Guard 6
            # Real faces: 50-800. Bookshelves/text: >1200. Flat walls: <25.
            if sampled_frame is not None and not _MEDIAPIPE_ENABLED:
                try:
                    x = int(face["x"])
                    y = int(face["y"])
                    roi = sampled_frame[y:y + int(h), x:x + int(w)]
                    if roi.size > 0:
                        roi_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if roi.ndim == 3 else roi
                        lap_var = float(cv2.Laplacian(roi_gray, cv2.CV_64F).var())
                        _LAP_MIN = float(os.getenv("HS_FACE_LAP_MIN", "25"))
                        _LAP_MAX = float(os.getenv("HS_FACE_LAP_MAX", "1200"))
                        if lap_var < _LAP_MIN or lap_var > _LAP_MAX:
                            print(
                                f"[FACE_CACHE] REJECT laplacian lap_var={lap_var:.0f} "
                                f"range=[{_LAP_MIN:.0f},{_LAP_MAX:.0f}] "
                                f"face=(x={x},y={y},w={int(w)},h={int(h)})",
                                flush=True,
                            )
                            continue
                except Exception:
                    pass  # ROI out of bounds — let it through
            count += 1
        return count

    def get_clip_cache(self, clip):
        start = float(clip.get("start", 0.0) or 0.0)
        end = float(clip.get("end", start) or start)
        key = (round(start, 2), round(end, 2))
        return dict(self.clip_caches.get(key, {}))

    def _precompute_clips_only(self, clips):
        _face_cache_start = time.time()
        print(f"[FACE_CACHE] Starting targeted Haar face detection...", flush=True)
        probe = cv2.VideoCapture(self.video_path)
        fps = probe.get(cv2.CAP_PROP_FPS) or 25.0
        probe.release()

        total_scan = sum(c.get('end', 0) - c.get('start', 0) for c in clips)
        print(f"[FACE_CACHE] Scanning {len(clips)} clips = {total_scan:.0f}s total (not full video)", flush=True)

        stride = max(1, int(os.getenv("HS_FACE_CACHE_FRAME_STRIDE", "8") or 8))  # reduced 15→8: denser sampling for better accuracy
        workers = max(1, int(os.getenv("HS_FACE_CACHE_WORKERS", "4") or 4))

        def scan_one_clip(clip_idx, clip):
            t_open = 0.0
            t_seek = 0.0
            t_decode = 0.0
            t_sample = 0.0
            t_scene = 0.0
            t_rep = 0.0
            t_face = 0.0
            t_anchor = 0.0

            _clip_start = time.time()
            start = float(clip.get("start", 0.0) or 0.0)
            end = float(clip.get("end", start) or start)

            t0 = time.perf_counter()
            cap = cv2.VideoCapture(self.video_path)
            t_open += time.perf_counter() - t0
            local_fps = cap.get(cv2.CAP_PROP_FPS) or fps or 25.0
            # Cascade initialization removed (OpenCV 5.0 compatibility)

            start_frame = int(start * local_fps)
            end_frame = int(end * local_fps)
            abs_results = {}
            rel_results = {}
            sampled = []

            # AV1 random seeks restart decoding from a keyframe and dominate wall
            # time. Seek once to the clip and decode forward, retaining only the
            # sampled frames required for in-memory clustering and Haar detection.
            t0 = time.perf_counter()
            cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
            t_seek += time.perf_counter() - t0

            # ── Seek verification: confirm OpenCV actually landed where we asked ──
            actual_landed_frame = cap.get(cv2.CAP_PROP_POS_FRAMES)
            actual_landed_t = actual_landed_frame / local_fps
            seek_delta_frames = abs(actual_landed_frame - start_frame)
            if seek_delta_frames > local_fps:  # >1 second off = real problem
                print(
                    f"[SEEK_VERIFY] ⚠️ SEEK MISS clip={start:.2f}-{end:.2f} "
                    f"requested_frame={start_frame} landed_frame={actual_landed_frame:.0f} "
                    f"delta={seek_delta_frames:.0f}frames ({seek_delta_frames/local_fps:.2f}s off)",
                    flush=True,
                )
            else:
                print(
                    f"[SEEK_VERIFY] clip={start:.2f}-{end:.2f} "
                    f"requested={start:.2f}s landed={actual_landed_t:.2f}s "
                    f"delta={seek_delta_frames:.0f}frames ✓",
                    flush=True,
                )

            frames_skipped_invalid = 0
            for fn in range(start_frame, end_frame):
                rel = fn - start_frame
                is_sample = (rel % stride == 0)

                t0 = time.perf_counter()
                if is_sample:
                    # Full decode — we actually need this frame's pixels
                    ret, frame = cap.read()
                    t_decode += time.perf_counter() - t0
                    if not ret:
                        break

                    # Guard: only keep genuinely decoded frames.
                    # A stale/buffer frame from a failed seek can appear valid (ret=True)
                    # but will have an unexpected shape or be entirely overexposed.
                    if frame is None or frame.ndim != 3:
                        frames_skipped_invalid += 1
                        continue

                    t0 = time.perf_counter()
                    sampled.append((fn, frame))
                    t_sample += time.perf_counter() - t0
                else:
                    # grab() advances the decoder position WITHOUT full pixel decode.
                    # ~10-14x faster than cap.read() for non-sampled frames.
                    ret = cap.grab()
                    t_decode += time.perf_counter() - t0
                    if not ret:
                        break

            print(
                f"[CLUSTER_SCAN] clip={start:.2f}-{end:.2f} "
                f"sample_decode=grab_optimized frames_preloaded={len(sampled)} "
                f"frames_skipped_invalid={frames_skipped_invalid}",
                flush=True,
            )


            haar_calls = 0
            if ENABLE_CLUSTER_SCAN:
                t0 = time.perf_counter()
                clusters = find_scene_segments(
                    [frame for _, frame in sampled], CLUSTER_HASH_THRESHOLD
                )
                t_scene += time.perf_counter() - t0
                for cluster_id, cluster in enumerate(clusters):
                    t0 = time.perf_counter()
                    # [PERF FIX] Downsample to 160x90 before Laplacian — sharpness is
                    # a RELATIVE comparison between frames in the same cluster, so
                    # full-resolution is wasteful. This cuts ~5s → <0.1s per clip.
                    _SHARP_W, _SHARP_H = 160, 90
                    def _sharpness(idx: int) -> float:
                        f = sampled[idx][1]
                        small = cv2.resize(f, (_SHARP_W, _SHARP_H), interpolation=cv2.INTER_AREA)
                        gray  = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY) if small.ndim == 3 else small
                        return cv2.Laplacian(gray, cv2.CV_32F).var()

                    representative = max(cluster, key=_sharpness)
                    t_rep += time.perf_counter() - t0
                    
                    t0 = time.perf_counter()
                    raw_faces = self._detect(sampled[representative][1])
                    t_face += time.perf_counter() - t0
                    haar_calls += 1
                    valid_count = self._valid_face_count(
                        raw_faces, sampled[representative][1].shape[0],
                        sampled_frame=sampled[representative][1],  # pass frame for Laplacian guard
                    )

                    # A missed/invalid representative must not mark a whole scene
                    # as faceless, AND we must actively search for multiple speakers.
                    # If we found less than 2 faces, search up to 3 more frames in the cluster
                    # to see if a better frame yields 2 faces (podcast format).
                    best_raw_faces = raw_faces
                    best_valid_count = valid_count

                    if best_valid_count < 2:
                        retries = [idx for idx in cluster if idx != representative]
                        retries.sort(key=lambda idx: abs(idx - representative))
                        
                        if len(retries) > 0 and best_valid_count == 0:
                            print(
                                f"[CLUSTER_SCAN] clip={start:.2f}-{end:.2f} cluster={cluster_id} "
                                f"redetect_triggered=True reason=representative_valid_count_0 "
                                f"raw_count={len(raw_faces)} valid_count={valid_count} "
                                f"min_face_height_ratio={MIN_VALID_FACE_HEIGHT_RATIO:.2f} "
                                f"attempts={min(len(retries), MIN_CLUSTER_REDETECT_ATTEMPTS)}",
                                flush=True,
                            )
                            
                        for retry_idx in retries[:MIN_CLUSTER_REDETECT_ATTEMPTS]:
                            t0 = time.perf_counter()
                            r_faces = self._detect(sampled[retry_idx][1])
                            t_face += time.perf_counter() - t0
                            haar_calls += 1
                            r_valid = self._valid_face_count(
                                r_faces, sampled[retry_idx][1].shape[0],
                                sampled_frame=sampled[retry_idx][1]
                            )
                            if r_valid > best_valid_count:
                                best_valid_count = r_valid
                                best_raw_faces = r_faces
                                if best_valid_count >= 2:
                                    break
                    
                    raw_faces = best_raw_faces
                    valid_count = best_valid_count

                    t0 = time.perf_counter()
                    # Copy each result so callers cannot mutate a shared cluster bbox.
                    for sample_idx in cluster:
                        fn, _ = sampled[sample_idx]
                        t_abs = round(fn / local_fps, 2)
                        t_rel = round(max(0.0, t_abs - start), 2)
                        assigned_faces = [
                            {
                                **face,
                                "_cluster_id": cluster_id,
                                "_cluster_start": cluster[0],
                                "_cluster_end": cluster[-1],
                            }
                            for face in raw_faces
                        ]
                        abs_results[t_abs] = assigned_faces
                        rel_results[t_rel] = assigned_faces
                    t_anchor += time.perf_counter() - t0
                print(
                    f"[CLUSTER_SCAN] clip={start:.2f}-{end:.2f} clusters={len(clusters)} "
                    f"haar_calls={haar_calls} frames_covered={len(sampled)} "
                    f"wall_s={time.time() - _clip_start:.2f}",
                    flush=True,
                )
            else:
                # Safety-net: preserve the prior per-sampled-frame Haar scan exactly.
                for fn, frame in sampled:
                    t_abs = round(fn / local_fps, 2)
                    t_rel = round(max(0.0, t_abs - start), 2)
                    t0 = time.perf_counter()
                    raw_faces = self._detect(frame)
                    t_face += time.perf_counter() - t0
                    haar_calls += 1
                    if raw_faces:
                        abs_results[t_abs] = raw_faces
                        rel_results[t_rel] = raw_faces
                print(
                    f"[CLUSTER_SCAN] clip={start:.2f}-{end:.2f} clusters=disabled "
                    f"haar_calls={haar_calls} frames_covered={len(sampled)} "
                    f"wall_s={time.time() - _clip_start:.2f}",
                    flush=True,
                )

            print(f"\nClip {clip_idx + 1}\n"
                  f"Open Video .......... {int(t_open * 1000)} ms\n"
                  f"Seek ............... {int(t_seek * 1000)} ms\n"
                  f"Decode ........... {int(t_decode * 1000)} ms\n"
                  f"Frame Sampling ..... {int(t_sample * 1000)} ms\n"
                  f"Scene Detection ..... {int(t_scene * 1000)} ms\n"
                  f"Representative Pick.. {int(t_rep * 1000)} ms\n"
                  f"Face Detect ........ {int(t_face * 1000)} ms\n"
                  f"Anchor Build ........ {int(t_anchor * 1000)} ms\n", flush=True)

            cap.release()
            return (round(start, 2), round(end, 2)), abs_results, rel_results

        with ThreadPoolExecutor(max_workers=min(workers, max(1, len(clips)))) as ex:
            futures = [ex.submit(scan_one_clip, i, clip) for i, clip in enumerate(clips)]
            for future in futures:
                key, abs_results, rel_results = future.result()
                self.cache.update(abs_results)
                self.clip_caches[key] = rel_results

        self._done = True
        _face_cache_elapsed = time.time() - _face_cache_start
        print(
            f"[FACE_CACHE] Done - {len(self.cache)} frames cached "
            f"| wall_time={_face_cache_elapsed:.2f}s",
            flush=True,
        )

def _process_job(job: dict, cloudinary_ok: bool):
    job_id      = job["job_id"]
    youtube_url = job.get("youtube_url") or job.get("video_url", "")
    video_format = job.get("video_format", "center_crop")
    is_free     = False if os.getenv("HS_UNLIMITED_MODE", "0") == "1" else job.get("is_free_user", False)
    
    if video_format == "blur_background":
        os.environ["HS_DISABLE_BG_BLUR"] = "0"
        os.environ["HS_DISABLE_CROP"] = "1"
    elif video_format == "original_with_black_bars":
        os.environ["HS_DISABLE_BG_BLUR"] = "1"
        os.environ["HS_DISABLE_CROP"] = "1"
    elif video_format == "center_crop":
        os.environ["HS_DISABLE_BG_BLUR"] = "1"
        os.environ["HS_DISABLE_CROP"] = "0"

    print(f"[LOCAL_WORKER] dYZ Processing job {job_id}: {youtube_url[:80]}", flush=True)

    with tempfile.TemporaryDirectory() as tmp:
        video_path = os.path.join(tmp, "video.mp4")

        # "?"? Step 1: Download via RapidAPI or fallback to yt-dlp "?"?
        print(f"[LOCAL_WORKER] Downloading video...", flush=True)
        try:
            _download_via_api(youtube_url, video_path)
        except Exception as e:
            print(f"[LOCAL_WORKER] RapidAPI failed ({e}), falling back to yt-dlp...", flush=True)
            _download_via_ytdlp(youtube_url, video_path)

        if not os.path.exists(video_path) or os.path.getsize(video_path) < 1000:
            raise RuntimeError("Downloaded file is missing or too small")

        print(f"[LOCAL_WORKER] Download complete: {os.path.getsize(video_path) // (1024*1024)}MB", flush=True)

        # ── Per-job benchmark ───────────────────────────────────────────
        _bench = _JobBenchmark(job_id, youtube_url)
        _bench.finish("1_download")  # download already done above

        # "?"? PIPELINE ARCHITECTURE "?"?
        clip_queue = queue.Queue(maxsize=5)
        results = []
        results_lock = threading.Lock()
        gpu_lock = threading.Semaphore(1)
        # Track orchestrator outcome so we can distinguish "orchestrator produced
        # nothing / crashed" from "clips were produced but failed during editing".
        orch_state = {"error": None, "produced": 0}
        
        # Initialize Editor
        _editor_cls = None
        _config_cls = None
        _wce_enabled = os.getenv("HS_WORKER_EDITOR_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")
        _caption_enabled = os.getenv("HS_CAPTION_WORKER_ENABLED", "0").strip().lower() not in ("0", "false", "no", "off")
        
        if _wce_enabled or _caption_enabled:
            try:
                from effects.world_class_editor import ClipEditor, ClipEditConfig
                _editor_cls = ClipEditor
                _config_cls = ClipEditConfig
                print("[LOCAL_WORKER] world_class_editor loaded o.", flush=True)
            except Exception as e:
                print(f"[LOCAL_WORKER] world_class_editor load failed (raw cuts): {e}", flush=True)

        editor_instance = None
        editor_cfg = None
        if _editor_cls:
            _editor_work_dir = os.path.join(tmp, "wce_work")
            os.makedirs(_editor_work_dir, exist_ok=True)
            editor_instance = _editor_cls(_editor_work_dir)
            editor_cfg = _config_cls()
            # ── Pass distribution branding config so WCE merges it in-pass ──────
            _branding_on = os.getenv("HS_APPLY_BRANDING", "0") == "1"
            editor_cfg.apply_distribution_branding = _branding_on
            editor_cfg.branding_watermark_path = (
                os.path.join(BASE_DIR, "static", "branding", "logo.png")
                if _branding_on else ""
            )
            editor_cfg.branding_outro_path = (
                os.path.join(BASE_DIR, "static", "branding", "outro.mp4")
                if _branding_on else ""
            )

        # ── Director Autopsy: Load Channel DNA ────────────────────────────────
        # Derive a stable channel_id from the video URL (e.g. youtube.com/@ChannelName)
        # This way every recurring channel gets its own calibrated profile.
        _autopsy_obj = None
        try:
            from effects.director_autopsy import load_and_apply_channel_dna
            import urllib.parse as _urlparse
            _yt_parsed   = _urlparse.urlparse(youtube_url)
            _channel_raw = (_yt_parsed.path or "").strip("/").split("/")[0] or job_id[:16]
            _channel_id  = _channel_raw or "default"
            _autopsy_obj = load_and_apply_channel_dna(_channel_id)
            print(
                f"[LOCAL_WORKER] Channel DNA loaded: {_channel_id} "
                f"(runs={_autopsy_obj.profile.get('runs', 0)})",
                flush=True
            )
        except Exception as _ae:
            print(f"[LOCAL_WORKER] Director Autopsy load skipped: {_ae}", flush=True)

        # Start Global Face Cache (will be instantiated later)
        face_cache = None

        # Global precomputed captions
        precomputed_captions = {}

        def run_orchestrator():
            try:
                print(f"[LOCAL_WORKER] Running orchestrator...", flush=True)
                from viral_finder.orchestrator import orchestrate
                
                _bench.begin("2_orchestration")
                clips = orchestrate(
                    video_path,
                    top_k=int(os.getenv("HS_ORCH_TOP_K", "15")),  # raised 8→15; dynamic formula scales by video length
                    prefer_gpu=True,
                    use_cache=True,
                    allow_fallback=False,
                    pipeline_mode=os.getenv("HS_ORCH_PIPELINE_MODE", "staged"),
                    creator_intent=job.get("creator_intent")
                )
                _bench.finish("2_orchestration")

                # Pre-classify clips for the Lightning Editor
                # ── PARALLEL format_classify ──────────────────────────────────────
                _bench.begin("3_format_classify")
                haar_clips = []

                if video_format in ("blur_background", "original_with_black_bars"):
                    print(f"[FORMAT] {video_format} selected — skipping FaceCache entirely, no crop tracking needed", flush=True)
                    for c in clips:
                        c["_fmt"] = None
                        c["director_mode"] = None
                        c["focus_x"] = 0.5
                else:
                    def _classify_one(clip):
                        s = float(clip.get("start", 0.0) or 0.0)
                        e = float(clip.get("end", s) or s)
                        fmt = analyze_video_format(video_path, s, e)
                        
                        # 🚀 SPACEX FIX: Bulletproof formatting
                        _genre = str(clip.get("content_genre", "")).upper()
                        # User insight: For podcasts, a blind 50/50 split is geometrically superior 
                        # to a center crop (monologue) because stacking left+right halves perfectly 
                        # converts 16:9 into 9:16 without losing any horizontal context.
                        if _genre in ("PODCAST", "INTERVIEW"):
                            from effects.format_analyzer import DirectorMode
                            if fmt and fmt.format_type != "podcast":
                                print(f"[SPACEX FIX] Cortex tagged {_genre} but analyzer said {fmt.format_type}. Forcing BLIND SPLIT (50/50).")
                                fmt.format_type = "podcast"
                                fmt.director_mode = DirectorMode.SPLIT
                                fmt.face_count_avg = max(2.0, fmt.face_count_avg)
                                # Default left speaker to 25% of screen width, right to 75%
                                fmt.speaker_positions = [0.25, 0.75]
                                
                        clip["_fmt"] = fmt  # attach result so editor doesn't re-run
                        return clip, fmt

                    _classify_workers = min(len(clips), 4)
                    with ThreadPoolExecutor(max_workers=_classify_workers) as _pool:
                        _fmt_futures = {_pool.submit(_classify_one, c): c for c in clips}
                        for _fut in _fmt_futures:
                            _clip, _fmt = _fut.result()
                            mode_name = _fmt.director_mode.name if _fmt and _fmt.director_mode else "UNKNOWN"
                            faces_avg = _fmt.face_count_avg if _fmt else 0.0
                            spk = _fmt.speaker_positions if _fmt else []
                            print(
                                f"[FORMAT_CLASSIFY] {_clip.get('start',0):.0f}s-{_clip.get('end',0):.0f}s "
                                f"mode={mode_name} avg_faces={faces_avg:.2f} speakers={spk}",
                                flush=True,
                            )
                            haar_clips.append(_clip)

                _bench.finish("3_format_classify")

                # ── Haar scan (face cache pre-computation) ─────────────────────────
                nonlocal face_cache
                _bench.begin("4_haar_scan")
                if haar_clips and video_format == "center_crop":
                    face_cache = FaceCache(video_path, haar_clips)
                else:
                    face_cache = None
                _bench.finish("4_haar_scan")

                # Precompute captions async before releasing clips
                _bench.begin("5_caption_pregen")
                if editor_instance and clips:
                    from utils.clipper import get_video_duration
                    print(f"[LOCAL_WORKER] Orchestration done: {len(clips)} clips. Pre-generating captions...", flush=True)
                    
                    _full_transcript = clips[0].get("transcript") or clips[0].get("captions")
                    
                    def gen_cap(clip, idx):
                        start = float(clip.get("start", 0))
                        end   = float(clip.get("end", start + 30))
                        clip_transcript = clip.get("transcript") or clip.get("captions") or _full_transcript or []
                        clip_title = clip.get("opening_caption") or clip.get("title") or clip.get("text", "")
                        cortex_hints = None
                        if clip.get("cortex_enabled") or clip.get("b_roll_prompt") or clip.get("b_roll_keywords"):
                            cortex_hints = {
                                "cortex_enabled": True,
                                "editing_notes": clip.get("editing_notes", {}),
                                "opening_caption": clip.get("opening_caption", ""),
                                "title": clip.get("title", ""),
                                "hook_type": clip.get("hook_type", ""),
                                "learning_signal_for_hotshort": clip.get("learning_signal_for_hotshort", {}),
                                "content_genre": clip.get("content_genre", ""),
                                "b_roll_prompt": clip.get("b_roll_prompt", ""),
                                "b_roll_keywords": clip.get("b_roll_keywords", []),
                                "b_roll_timestamp": clip.get("b_roll_timestamp", 1.0)
                            }
                        ass_path = editor_instance.generate_caption_file(
                            input_path=video_path,
                            source_start=start,
                            source_end=end,
                            transcript=clip_transcript,
                            config=editor_cfg,
                            clip_title=clip_title,
                            cortex_hints=cortex_hints,
                            precomputed_narrative=clip.get("precomputed_narrative")
                        )
                        return idx, ass_path

                    ex = ThreadPoolExecutor(max_workers=4)
                    for i, c in enumerate(clips):
                        precomputed_captions[i] = ex.submit(gen_cap, c, i)

                _bench.finish("5_caption_pregen")
                orch_state["produced"] = len(clips)
                for i, clip in enumerate(clips):
                    clip_queue.put((i, clip))
                    print(f"[PIPELINE] Clip queued: {i}", flush=True)

            except Exception as e:
                import traceback
                orch_state["error"] = e
                print(f"[LOCAL_WORKER] Orchestrator thread failed: {e}\n{traceback.format_exc()}", flush=True)
            finally:
                clip_queue.put(None) # Signal done

        def run_editor():
            while True:
                item = clip_queue.get()
                if item is None:
                    break
                    
                i, clip = item
                start = float(clip.get("start", 0))
                end   = float(clip.get("end", start + 30))
                clip_res = {**clip, "clip_url": None, "error": None}
                
                try:
                    t_clip_total = time.perf_counter()
                    # CPU: Extract subclip (ffmpeg copy)
                    t0 = time.perf_counter()
                    raw_path = os.path.join(tmp, f"clip_{i}_{int(start)}_{int(end)}.mp4")
                    _bench.begin(f"6a_extract_clip{i}")
                    # Frame-accurate extraction (avoid -c copy keyframe drift)
                    import subprocess
                    try:
                        subprocess.run([
                            "ffmpeg", "-y", "-nostdin", "-ss", str(start), "-to", str(end),
                            "-i", video_path, "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
                            "-c:a", "aac", raw_path
                        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180, check=True)
                    except subprocess.CalledProcessError as e:
                        print(f"[PIPELINE] Extraction failed for clip {i}: {e}", flush=True)
                        continue
                    t_raw_cut = time.perf_counter() - t0
                    _bench.finish(f"6a_extract_clip{i}")

                    final_path = raw_path
                    t_wce = 0.0
                    t_branding = 0.0
                    t_upload = 0.0
                    
                    # GPU: Enhance Clip
                    if editor_instance:
                        edited_path = os.path.join(tmp, f"edited_{i}_{int(start)}_{int(end)}.mp4")
                        clip_transcript = clip.get("transcript") or clip.get("captions") or []
                        clip_title = clip.get("opening_caption") or clip.get("title") or clip.get("text", "")
                        
                        cortex_hints = None
                        if clip.get("cortex_enabled") or clip.get("b_roll_prompt") or clip.get("b_roll_keywords"):
                            cortex_hints = {
                                "cortex_enabled": True,
                                "editing_notes": clip.get("editing_notes", {}),
                                "opening_caption": clip.get("opening_caption", ""),
                                "title": clip.get("title", ""),
                                "hook_type": clip.get("hook_type", ""),
                                "learning_signal_for_hotshort": clip.get("learning_signal_for_hotshort", {}),
                                "content_genre": clip.get("content_genre", ""),
                                "b_roll_prompt": clip.get("b_roll_prompt", ""),
                                "b_roll_keywords": clip.get("b_roll_keywords", []),
                                "b_roll_timestamp": clip.get("b_roll_timestamp", 1.0)
                            }

                        _bench.begin(f"6b_wce_clip{i}")
                        with gpu_lock:
                            t0 = time.perf_counter()
                            edit_result = editor_instance.enhance_pretrimmed_clip(
                                input_path=raw_path,
                                output_path=edited_path,
                                source_start=start,
                                source_end=end,
                                transcript=clip_transcript,
                                config=editor_cfg,
                                clip_title=clip_title,
                                precomputed_narrative=clip.get("precomputed_narrative"),
                                cortex_hints=cortex_hints,
                                is_free=is_free,
                                precomputed_face_cache=face_cache.get_clip_cache(clip) if face_cache else {},
                                precomputed_ass_path=precomputed_captions[i].result()[1] if precomputed_captions.get(i) else None
                            )
                            t_wce = time.perf_counter() - t0
                        _bench.finish(f"6b_wce_clip{i}")
                        if edit_result:
                            final_path = edited_path
                            
                            # 🚀 SILENCE KILLER POST-PROCESSING
                            try:
                                from effects.silence_killer import run_silence_killer
                                nosilence_path = final_path.replace(".mp4", "_nosilence.mp4")
                                if run_silence_killer(final_path, nosilence_path):
                                    import shutil
                                    # Swap paths to keep final_path intact for upload
                                    shutil.move(nosilence_path, final_path)
                            except Exception as e:
                                print(f"[SILENCE_KILLER] Post-processing failed: {e}", flush=True)
                                
                            clip_res["edit_metadata"] = getattr(edit_result, "metadata", {}) or {}

                        # ── Director Autopsy: post-render analysis ──────────────
                        if _autopsy_obj is not None:
                            try:
                                _clip_meta    = getattr(edit_result, "metadata", {}) or {}
                                _clip_fmt     = _clip_meta.get("video_format", "unknown")
                                # ── Get clip_id from the metadata field WCE now writes ──
                                _clip_wce_id  = _clip_meta.get("wce_debug_clip_id", "")

                                # ── Extract scene-cut timestamps from face_cache ──────
                                # The face_cache stores _cluster_id per frame. Cluster
                                # boundaries = scene cuts. Convert to timestamps (seconds).
                                _scene_cuts_ts = []
                                try:
                                    _fc_clip = face_cache.get_clip_cache(clip) if face_cache else {}
                                    _last_cid = None
                                    for _ts in sorted(_fc_clip.keys()):
                                        _faces = _fc_clip[_ts]
                                        if _faces:
                                            _cid = _faces[0].get("_cluster_id")
                                            if _cid is not None and _cid != _last_cid and _last_cid is not None:
                                                _scene_cuts_ts.append(float(_ts))
                                            _last_cid = _cid
                                except Exception:
                                    pass

                                if _clip_wce_id:
                                    from effects.director_autopsy import run_post_render_autopsy
                                    _ap_report = run_post_render_autopsy(
                                        _autopsy_obj,
                                        clip_id=_clip_wce_id,
                                        clip_format=_clip_fmt,
                                        scene_seg_cuts=_scene_cuts_ts or None,
                                    )
                                    if _ap_report and _ap_report.get("total_score") is not None:
                                        clip_res["autopsy"] = {
                                            "score": round(_ap_report["total_score"], 1),
                                            "flags": _ap_report.get("flags", []),
                                            "profile": _ap_report.get("profile_params", {}),
                                        }
                                        print(
                                            f"[AUTOPSY] clip={i} score={_ap_report['total_score']:.1f}/100 "
                                            f"scene_cuts={len(_scene_cuts_ts)} "
                                            f"flags={_ap_report.get('flags', [])}",
                                            flush=True
                                        )
                                else:
                                    print(f"[AUTOPSY] clip={i} skipped — debug mode off (HS_DEBUG_FRAMES not set)", flush=True)
                            except Exception as _aex:
                                import traceback as _tb
                                print(f"[AUTOPSY] post-render failed: {_aex}\n{_tb.format_exc()}", flush=True)
                        
                    # Branding
                    # If WCE merged branding into its pass, skip the separate call.
                    # Fallback to separate pass if editor was disabled or branding wasn't merged.
                    _meta = (getattr(edit_result, "metadata", {}) or {}) if edit_result is not None else {}
                    _veg = _meta.get("visual_effect_graph", {}) or {}
                    _wce_branding_merged = bool(_meta.get("branding_merged_into_wce", False) or _veg.get("branding_merged_into_wce", False))
                    if _wce_branding_merged:
                        t_branding = 0.0  # merged into WCE — no extra pass needed
                        print(f"[LOCAL_WORKER] Branding merged into WCE pass — 0s extra", flush=True)
                    elif os.getenv("HS_APPLY_BRANDING", "1") == "1":
                        branded_path = os.path.join(tmp, f"branded_{i}_{int(start)}_{int(end)}.mp4")
                        with gpu_lock:
                            t0 = time.perf_counter()
                            if _apply_distribution_branding(final_path, branded_path):
                                final_path = branded_path
                            t_branding = time.perf_counter() - t0

                    # Upload — local save OR Cloudinary -> Railway fallback
                    url = None
                    t0 = time.perf_counter()
                    _bench.begin(f"6c_upload_clip{i}")
                    if _LOCAL_MODE:
                        saved = _local_save_clip(final_path, i, start, end)
                        url = f"local://{saved}"
                    else:
                        if cloudinary_ok:
                            url = _upload_clip_to_cloudinary(final_path)
                        if url is None:
                            url = _upload_clip_to_railway(final_path, job_id)
                    t_upload = time.perf_counter() - t0
                    _bench.finish(f"6c_upload_clip{i}")

                    clip_res["clip_url"] = url
                    clip_res["editor_timing"] = {
                        "raw_cut_s": round(t_raw_cut, 3),
                        "wce_s": round(t_wce, 3),
                        "branding_s": round(t_branding, 3),
                        "upload_s": round(t_upload, 3),
                        "total_s": round(time.perf_counter() - t_clip_total, 3),
                    }
                    with results_lock:
                        results.append(clip_res)
                        
                    print(
                        f"[EDITOR_TIMING] clip={i} raw={t_raw_cut:.2f}s wce={t_wce:.2f}s "
                        f"branding={t_branding:.2f}s upload={t_upload:.2f}s total={time.perf_counter() - t_clip_total:.2f}s",
                        flush=True,
                    )
                    print(f"[PIPELINE] Clip done + uploaded: {i}", flush=True)

                except Exception as e:
                    import traceback
                    print(f"[PIPELINE] Clip failed: {i} -> {e}\n{traceback.format_exc()}", flush=True)
                    clip_res["error"] = str(e)
                    with results_lock:
                        results.append(clip_res)
                finally:
                    clip_queue.task_done()

        producer = threading.Thread(target=run_orchestrator, name="Orchestrator")
        consumer = threading.Thread(target=run_editor, name="Editor")
        
        producer.start()
        consumer.start()
        
        producer.join()
        consumer.join()
        
        # Sort results back to original order by start time
        results.sort(key=lambda x: x.get("start", 0))

        # ── Save benchmark report for this job ─────────────────────────────
        _bench.save()

        if orch_state["error"] is not None:
            raise RuntimeError(f"Orchestrator failed before producing clips: {orch_state['error']}") from orch_state["error"]
        if orch_state["produced"] == 0:
            raise RuntimeError("Orchestrator produced 0 candidate clips — nothing to edit")

        successful = [r for r in results if not r.get("error")]
        failed = [r for r in results if r.get("error")]
        if not successful:
            summary = "; ".join(f"[{r.get('start')}-{r.get('end')}]: {r.get('error')}" for r in failed[:5])
            raise RuntimeError(f"All {len(failed)} clip(s) failed during editing → {summary}")
        if failed:
            print(f"[PIPELINE] {len(failed)}/{len(results)} clips failed during editing; returning {len(successful)} successful.", flush=True)
        return successful



def main():
    import argparse
    parser = argparse.ArgumentParser(description="HotShort Local Worker")
    parser.add_argument("--local", action="store_true",
                        help="Local mode: no Railway. Process a YouTube URL directly.")
    parser.add_argument("--url", default=None, help="YouTube URL (used with --local).")
    parser.add_argument("--intent", default=None, help="Creator Intent (used with --local).")
    parser.add_argument("--format", choices=["center_crop", "blur_background", "original_with_black_bars"], default=None, help="Video Format (used with --local).")
    parser.add_argument("--clips", type=int, default=int(os.getenv("HS_ORCH_TOP_K", "5")),
                        help="Number of clips to select (default 5).")
    args = parser.parse_args()

    _print_startup_banner()

    # ── LOCAL MODE ─────────────────────────────────────────────────────────
    if args.local:
        global _LOCAL_MODE
        _LOCAL_MODE = True
        os.environ["HS_ORCH_TOP_K"] = str(args.clips)

        youtube_url = args.url
        creator_intent = args.intent
        if not youtube_url:
            print("\n" + "=" * 55, flush=True)
            print("  LOCAL MODE - No Railway polling", flush=True)
            print("=" * 55, flush=True)
            youtube_url = input("  YouTube URL: ").strip().strip("'`\"")
            creator_intent = input("  Creator Intent (optional): ").strip()
            print("\n  Select Video Format:")
            print("  1) center_crop (Dynamic Mode A/B Face Tracking) [DEFAULT]")
            print("  2) blur_background (16:9 Uncropped with Cinematic Blur)")
            print("  3) original_with_black_bars (16:9 Uncropped with Black Padding)")
            format_choice = input("  Choice [1-3]: ").strip()
            
            if format_choice == "2":
                video_format = "blur_background"
            elif format_choice == "3":
                video_format = "original_with_black_bars"
            else:
                video_format = "center_crop"
        else:
            youtube_url = youtube_url.strip().strip("'`\"")
            if not creator_intent:
                creator_intent = None
            video_format = args.format if args.format else "center_crop"

        if not youtube_url:
            print("[LOCAL_WORKER] No URL provided. Exiting.", flush=True)
            sys.exit(1)

        print(f"\n[LOCAL_WORKER] URL      : {youtube_url}", flush=True)
        if creator_intent:
            print(f"[LOCAL_WORKER] Intent   : {creator_intent}", flush=True)
        print(f"[LOCAL_WORKER] Format    : {video_format}", flush=True)
        print(f"[LOCAL_WORKER] Clips     : {args.clips}", flush=True)
        print(f"[LOCAL_WORKER] Output    : {_LOCAL_OUT_DIR}", flush=True)

        _job_id = f"local_{int(time.time())}"
        job = {
            "job_id": _job_id, 
            "youtube_url": youtube_url, 
            "creator_intent": creator_intent if creator_intent else None,
            "video_format": video_format,
            "is_free_user": False
        }

        t0 = time.perf_counter()
        try:
            clips = _process_job(job, cloudinary_ok=False)
        except Exception as e:
            print(f"\n[LOCAL_WORKER] FAILED: {e}\n{traceback.format_exc()}", flush=True)
            sys.exit(1)

        total_s = time.perf_counter() - t0
        print("\n" + "=" * 55, flush=True)
        print(f"  DONE - {len(clips)} clips in {total_s:.0f}s ({total_s/60:.1f} min)", flush=True)
        print(f"  Output: {_LOCAL_OUT_DIR}", flush=True)
        print("=" * 55, flush=True)
        for i, c in enumerate(clips):
            title = (c.get("opening_caption") or c.get("title") or "")[:60]
            saved = c.get("clip_url", "").replace("local://", "")
            print(f"  [{i+1}] {c.get('start',0):.0f}s-{c.get('end',0):.0f}s  {title}", flush=True)
            if saved:
                print(f"        -> {os.path.basename(saved)}", flush=True)

        try:
            subprocess.Popen(["explorer", _LOCAL_OUT_DIR])
        except Exception:
            pass
        return

    # ── SERVER MODE (Railway polling) ────────────────────────────────────────
    if not RAILWAY_URL:
        print("[LOCAL_WORKER] ERROR: RAILWAY_URL not set. Use --local flag.", flush=True)
        sys.exit(1)
    if not WORKER_SECRET:
        print("[LOCAL_WORKER] ERROR: WORKER_SECRET not set. Use --local flag.", flush=True)
        sys.exit(1)

    cloudinary_ok = _configure_cloudinary()
    if not cloudinary_ok:
        print("[LOCAL_WORKER] Cloudinary not configured - Railway fallback active.", flush=True)

    while True:
        print(f"[LOCAL_WORKER] polling...", flush=True)
        job = _poll_next_job()
        if job is None:
            time.sleep(POLL_INTERVAL)
            continue
        job_id = job["job_id"]
        print(f"[LOCAL_WORKER] Job received: {job_id}", flush=True)
        try:
            clips = _process_job(job, cloudinary_ok=cloudinary_ok)
            _complete_job(job_id, clips)
        except Exception as e:
            err_msg = str(e)
            tb = traceback.format_exc()
            print(f"[LOCAL_WORKER] Job {job_id} failed:\n{tb}", flush=True)
            _fail_job(job_id, err_msg)
        time.sleep(2)


if __name__ == "__main__":
    main()

