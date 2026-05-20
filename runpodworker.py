import os
import subprocess
import tempfile
import threading

import runpod
import yt_dlp
from dotenv import load_dotenv
from faster_whisper import WhisperModel

try:
    import torch
except ImportError:
    torch = None

load_dotenv()

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except ImportError:
    boto3 = None

try:
    import cloudinary
    import cloudinary.uploader
    _CLOUDINARY_AVAILABLE = True
except ImportError:
    cloudinary = None
    _CLOUDINARY_AVAILABLE = False


def _configure_cloudinary() -> bool:
    if not _CLOUDINARY_AVAILABLE:
        return False

    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME")
    api_key = os.getenv("CLOUDINARY_API_KEY")
    api_secret = os.getenv("CLOUDINARY_API_SECRET")

    if not (cloud_name and api_key and api_secret):
        return False

    cloudinary.config(
        cloud_name=cloud_name,
        api_key=api_key,
        api_secret=api_secret,
    )
    return True


def _upload_to_cloudinary(local_path: str) -> str | None:
    if not _configure_cloudinary():
        return None

    try:
        result = cloudinary.uploader.upload(local_path, resource_type="video")
        return result.get("secure_url")
    except Exception as e:
        print("Cloudinary upload failed:", e)
        return None


def _gpu_alive() -> bool:
    try:
        return bool(torch is not None and torch.cuda.is_available())
    except Exception as e:
        print("GPU health check failed:", e)
        return False


def _resolve_whisper_runtime() -> tuple[str, str, str]:
    if torch is None:
        print("[WHISPER] torch not installed → device=cpu")
        gpu = False
    elif not torch.cuda.is_available():
        print(f"[WHISPER] torch.cuda.is_available()=False → device=cpu")
        gpu = False
    else:
        gpu = True
        try:
            print(f"[WHISPER] GPU detected: {torch.cuda.get_device_name(0)} "
                  f"| VRAM: {torch.cuda.get_device_properties(0).total_memory // 1024**2} MB")
        except Exception as e:
            print(f"[WHISPER] GPU detected but couldn't read name: {e}")

    device = "cuda" if gpu else "cpu"
    model_name = (os.getenv("WHISPER_MODEL") or "small").strip() or "small"
    compute_type = (os.getenv("WHISPER_COMPUTE_TYPE") or "").strip()

    if not compute_type:
        compute_type = "int8" if device == "cpu" else "int8_float16"

    print(f"[WHISPER] Runtime selected → model={model_name} device={device} compute_type={compute_type}")
    return model_name, device, compute_type


def _load_whisper_model() -> WhisperModel:
    model_name, device, compute_type = _resolve_whisper_runtime()
    return WhisperModel(model_name, device=device, compute_type=compute_type)


# Lazy-load: do NOT load at module level.
# Module-level loading would crash workers silently at startup —
# RunPod would show them as 'ready' but they'd be unable to process any job.
_model = None
_model_lock = threading.Lock()


def _get_model() -> WhisperModel:
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                _model = _load_whisper_model()
    return _model


_ACTIVE_REQUESTS = 0
_ACTIVE_REQUESTS_LOCK = threading.Lock()


def _upload_to_s3(local_path: str) -> str | None:
    bucket = os.environ.get("AWS_S3_BUCKET") or os.environ.get("S3_BUCKET")
    if not bucket or boto3 is None:
        return None

    region = os.environ.get("AWS_REGION", "us-east-1")
    key = os.path.basename(local_path)

    try:
        s3 = boto3.client(
            "s3",
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
            region_name=region,
        )
        s3.upload_file(local_path, bucket, key, ExtraArgs={"ACL": "public-read"})
        return f"https://{bucket}.s3.{region}.amazonaws.com/{key}"
    except (BotoCoreError, ClientError, Exception) as e:
        print("S3 upload failed:", e)
        return None


def handler(event):
    print("[WORKER] REQUEST RECEIVED")
    print(event)
    input_data = event.get("input", {})
    task = input_data.get("task")
    youtube_url = input_data.get("youtube_url") or input_data.get("url")
    media_url = (
        input_data.get("media_url")
        or input_data.get("video_url")
        or input_data.get("audio_url")
        or (input_data.get("url") if task == "transcribe_url" else None)
    )
    transcript = input_data.get("transcript") or []

    cloud_provider = input_data.get("cloud_provider", {})
    if cloud_provider and isinstance(cloud_provider, dict):
        if cloud_provider.get("cloud_name"):
            os.environ["CLOUDINARY_CLOUD_NAME"] = cloud_provider.get("cloud_name", "")
        if cloud_provider.get("api_key"):
            os.environ["CLOUDINARY_API_KEY"] = cloud_provider.get("api_key", "")
        if cloud_provider.get("api_secret"):
            os.environ["CLOUDINARY_API_SECRET"] = cloud_provider.get("api_secret", "")

    if not task:
        return {"error": "Invalid task: missing task"}

    if task == "healthcheck":
        return {
            "status": "ok",
            "gpu": _gpu_alive(),
        }

    if task in {"download", "transcribe_youtube", "orchestrate"} and not youtube_url and not media_url:
        return {"error": f"Invalid task '{task}': missing youtube_url or video_url"}

    if task == "analyze" and not transcript:
        return {"error": "Invalid task 'analyze': missing transcript"}

    if task == "transcribe_url" and not media_url:
        return {"error": "Invalid task 'transcribe_url': missing media_url/video_url/audio_url/url"}

    try:
        if task == "analyze":
            try:
                from viral_finder.idea_graph import build_idea_graph, select_candidate_clips
            except Exception as e:
                return {"error": f"Failed to import analysis pipeline: {e}"}

            top_k = int(input_data.get("top_k") or os.environ.get("HS_ORCH_TOP_K", "8"))
            nodes = build_idea_graph(transcript) or []
            moments = select_candidate_clips(
                nodes,
                top_k=top_k,
                transcript=transcript,
                ensure_sentence_complete=True,
            ) or []
            return {"status": "ok", "moments": moments}

        with tempfile.TemporaryDirectory() as temp_dir:
            video_path = os.path.join(temp_dir, "video.mp4")
            audio_path = os.path.join(temp_dir, "audio.wav")
            media_path = os.path.join(temp_dir, "media.bin")

            if task == "transcribe_url":
                try:
                    import requests
                except Exception as e:
                    return {"error": f"requests import failed: {e}"}

                if not (str(media_url).startswith("http://") or str(media_url).startswith("https://")):
                    return {"error": "Invalid media_url: must be http(s)"}

                resp = requests.get(str(media_url), stream=True, timeout=120)
                if resp.status_code != 200:
                    return {"error": f"media download failed: {resp.status_code} {resp.text[:200]}"}

                with open(media_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)

                subprocess.run(
                    ["ffmpeg", "-y", "-i", media_path, "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", audio_path],
                    check=True,
                    capture_output=True,
                )

                segments, _ = _get_model().transcribe(audio_path, beam_size=2, vad_filter=True, vad_parameters=dict(min_silence_duration_ms=500))
                transcript = []
                for s in segments:
                    transcript.append({
                        "start": s.start,
                        "end": s.end,
                        "text": s.text,
                    })

                return {"status": "ok", "segments": transcript}

            # ── Video acquisition: prefer Cloudinary relay URL over direct yt-dlp ──
            # When Railway has already downloaded and uploaded the video to Cloudinary,
            # it passes `video_url` in the payload. RunPod downloads from Cloudinary
            # (no YouTube IP blocks), so yt-dlp never runs on the datacenter IP.
            if media_url:
                # Path A: Cloudinary / pre-uploaded URL → simple HTTP download
                print(f"[WORKER] Downloading from relay URL: {media_url}")
                try:
                    import requests as _requests
                except Exception as e:
                    return {"error": f"requests import failed: {e}"}

                if not (str(media_url).startswith("http://") or str(media_url).startswith("https://")):
                    return {"error": "Invalid video_url: must be http(s)"}

                resp = _requests.get(str(media_url), stream=True, timeout=300)
                if resp.status_code != 200:
                    return {"error": f"Video relay download failed: {resp.status_code}"}

                with open(video_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=4 * 1024 * 1024):
                        if chunk:
                            f.write(chunk)
                print(f"[WORKER] Relay download complete: {os.path.getsize(video_path)} bytes")

            else:
                # Path B: Direct yt-dlp (fallback for local dev / non-RunPod environments)
                print(f"[WORKER] Falling back to yt-dlp download: {youtube_url}")
                ydl_opts = {
                    "format": "best[ext=mp4]/best",
                    "merge_output_format": "mp4",
                    "outtmpl": video_path,
                    "quiet": True,
                    "no_warnings": True,
                    "geo_bypass": True,
                    "nocheckcertificate": True,
                    "socket_timeout": 30,
                    "retries": 3,
                    "cookiefile": "/app/cookies.txt",
                    # Android client bypasses YouTube 403s on datacenter IPs
                    "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
                    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "http_headers": {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                        "Accept-Language": "en-US,en;q=0.5",
                        "Accept-Encoding": "gzip, deflate",
                        "DNT": "1",
                        "Connection": "keep-alive",
                        "Upgrade-Insecure-Requests": "1",
                    },
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([youtube_url])
            # ── End video acquisition ────────────────────────────────────────────

            if task == "download":
                video_url = _upload_to_cloudinary(video_path) or _upload_to_s3(video_path)
                if not video_url:
                    return {
                        "error": "Upload failed (no cloud provider configured), cannot provide a public video_url."
                    }

                print("DOWNLOAD DONE:", video_path, "->", video_url)
                print("UPLOAD RESULT:", video_url)
                print("VIDEO URL:", video_url)
                return {"video_url": video_url}

            if task == "transcribe_youtube":
                subprocess.run(
                    ["ffmpeg", "-y", "-i", video_path, "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", audio_path],
                    check=True,
                    capture_output=True,
                )

                segments, _ = _get_model().transcribe(audio_path, beam_size=2, vad_filter=True, vad_parameters=dict(min_silence_duration_ms=500))
                transcript = []
                for s in segments:
                    transcript.append({
                        "start": s.start,
                        "end": s.end,
                        "text": s.text,
                    })

                return {"status": "ok", "segments": transcript}

            if task == "orchestrate":
                try:
                    from viral_finder.orchestrator import orchestrate
                except Exception as e:
                    return {"error": f"Failed to import orchestrator: {e}"}

                clips = orchestrate(
                    video_path,
                    top_k=int(os.environ.get("HS_ORCH_TOP_K", "8")),
                    prefer_gpu=True,
                    use_cache=True,
                    allow_fallback=False,
                    pipeline_mode=os.environ.get("HS_ORCH_PIPELINE_MODE", None),
                )

                # ── Cut each clip + upload to Cloudinary ──────────────────────
                # orchestrate() only returns timestamps — we must actually cut
                # the video and upload each clip so Railway can serve them.
                print(f"[WORKER] Orchestration done: {len(clips or [])} clips — cutting + uploading…")
                cloudinary_ok = _configure_cloudinary()

                processed_clips = []
                for i, clip in enumerate(clips or []):
                    start = float(clip.get("start", 0))
                    end   = float(clip.get("end",   start + 30))
                    clip_filename = f"clip_{i}_{int(start)}_{int(end)}.mp4"
                    clip_path = os.path.join(temp_dir, clip_filename)

                    print(f"[WORKER] ffmpeg cut clip {i}: {start:.1f}s → {end:.1f}s")
                    try:
                        result = subprocess.run(
                            [
                                "ffmpeg", "-y",
                                "-ss", str(start),
                                "-to", str(end),
                                "-i", video_path,
                                "-c", "copy",          # stream copy = fast, no re-encode
                                "-avoid_negative_ts", "make_zero",
                                clip_path,
                            ],
                            capture_output=True,
                            timeout=120,
                        )
                        if result.returncode != 0:
                            print(f"[WORKER] ffmpeg clip {i} failed: {result.stderr[-300:]}")
                            processed_clips.append({**clip, "clip_url": None, "error": "ffmpeg_failed"})
                            continue
                    except Exception as e:
                        print(f"[WORKER] ffmpeg clip {i} exception: {e}")
                        processed_clips.append({**clip, "clip_url": None, "error": str(e)})
                        continue

                    # Upload clip to Cloudinary
                    clip_url = None
                    if cloudinary_ok:
                        try:
                            print(f"[WORKER] Uploading clip {i} to Cloudinary…")
                            up = cloudinary.uploader.upload(
                                clip_path,
                                resource_type="video",
                                folder="hotshort_clips",
                            )
                            clip_url = up.get("secure_url")
                            print(f"[WORKER] Clip {i} uploaded: {clip_url}")
                        except Exception as e:
                            print(f"[WORKER] Cloudinary upload clip {i} failed: {e}")

                    processed_clips.append({**clip, "clip_url": clip_url})

                print(f"[WORKER] All clips processed: {len(processed_clips)}")
                return {"status": "ok", "clips": processed_clips}
                # ── End cut + upload ───────────────────────────────────────────

            subprocess.run(
                ["ffmpeg", "-y", "-i", video_path, "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", audio_path],
                check=True,
                capture_output=True,
            )

            segments, _ = _get_model().transcribe(audio_path, beam_size=2, vad_filter=True, vad_parameters=dict(min_silence_duration_ms=500))
            transcript = []
            for s in segments:
                transcript.append({
                    "start": s.start,
                    "end": s.end,
                    "text": s.text,
                })

            return {"segments": transcript}

    except Exception as e:
        return {"error": str(e)}


if os.getenv("LOCAL_HTTP_WORKER") == "1":
    from flask import Flask, jsonify, request
    import queue
    import uuid

    app = Flask(__name__)

    _MAX_CONCURRENCY = max(1, int(os.getenv("LOCAL_WORKER_MAX_CONCURRENCY", "1") or "1"))
    _MAX_QUEUE = max(0, int(os.getenv("LOCAL_WORKER_MAX_QUEUE", "0") or "0"))
    
    # Proper queue implementation
    _TASK_QUEUE = queue.Queue(maxsize=_MAX_QUEUE + _MAX_CONCURRENCY)
    _TASK_RESULTS = {}
    
    def _worker_thread_func():
        while True:
            task_info = _TASK_QUEUE.get()
            if task_info is None:
                break
                
            job_id = task_info["job_id"]
            job_data = task_info["job_data"]
            event = task_info["event"]
            
            try:
                result = handler(job_data)
                _TASK_RESULTS[job_id] = result
            except Exception as e:
                _TASK_RESULTS[job_id] = {"error": str(e)}
            finally:
                _TASK_QUEUE.task_done()
                event.set()
                
    for _ in range(_MAX_CONCURRENCY):
        t = threading.Thread(target=_worker_thread_func, daemon=True)
        t.start()

    def _local_worker_capacity() -> dict:
        with _ACTIVE_REQUESTS_LOCK:
            inflight = int(_ACTIVE_REQUESTS)
        queue_depth = max(0, inflight - _MAX_CONCURRENCY)
        can_accept = inflight < (_MAX_CONCURRENCY + _MAX_QUEUE)
        return {
            "status": "ok",
            "gpu": _gpu_alive(),
            "inflight": inflight,
            "queue_depth": queue_depth,
            "max_concurrency": _MAX_CONCURRENCY,
            "max_queue": _MAX_QUEUE,
            "can_accept": can_accept,
            "busy": not can_accept,
        }

    @app.route("/", methods=["GET"])
    def health():
        payload = _local_worker_capacity()
        payload["message"] = "Worker ready. POST to /run with task data."
        return jsonify(payload)

    @app.route("/run", methods=["POST"])
    def run_local():
        global _ACTIVE_REQUESTS

        capacity = _local_worker_capacity()
        if not capacity["can_accept"]:
            return jsonify({
                "error": "local_worker_busy",
                "message": "Local worker is at capacity; route this job to fallback.",
                **capacity,
            }), 429

        with _ACTIVE_REQUESTS_LOCK:
            _ACTIVE_REQUESTS += 1
            
        try:
            job_id = str(uuid.uuid4())
            done_event = threading.Event()
            
            job_data = {"input": request.json}
            _TASK_QUEUE.put({
                "job_id": job_id,
                "job_data": job_data,
                "event": done_event
            })
            
            # Wait for the dedicated worker thread to process it
            done_event.wait()
            
            result = _TASK_RESULTS.pop(job_id, {"error": "job_lost"})
            return jsonify(result)
        finally:
            with _ACTIVE_REQUESTS_LOCK:
                _ACTIVE_REQUESTS = max(0, _ACTIVE_REQUESTS - 1)

    print("Local HTTP worker running on http://localhost:5000/run")
    app.run(host="0.0.0.0", port=5000, threaded=True)
else:
    runpod.serverless.start({"handler": handler})
