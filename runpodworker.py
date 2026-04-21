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
    device = "cuda" if _gpu_alive() else "cpu"
    model_name = (os.getenv("WHISPER_MODEL") or "small").strip() or "small"
    compute_type = (os.getenv("WHISPER_COMPUTE_TYPE") or "").strip()

    if not compute_type:
        # Conservative defaults: keep CPU memory usage predictable and
        # prefer a GPU-friendly mixed path when CUDA is available.
        compute_type = "int8" if device == "cpu" else "float16"

    return model_name, device, compute_type


def _load_whisper_model() -> WhisperModel:
    model_name, device, compute_type = _resolve_whisper_runtime()
    print(f"Whisper runtime: model={model_name} device={device} compute_type={compute_type}")
    if device == "cuda" and torch is not None:
        try:
            print(f"GPU: {torch.cuda.get_device_name(0)}")
        except Exception as e:
            print(f"GPU: unavailable ({e})")
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
    input_data = event.get("input", {})
    task = input_data.get("task")
    youtube_url = input_data.get("youtube_url") or input_data.get("url")
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

    if task in {"download", "transcribe_youtube", "orchestrate"} and not youtube_url:
        return {"error": f"Invalid task '{task}': missing youtube_url/url"}

    if task == "analyze" and not transcript:
        return {"error": "Invalid task 'analyze': missing transcript"}

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

            ydl_opts = {
                "format": "best",
                "merge_output_format": "mp4",
                "outtmpl": video_path,
                "quiet": True,
                "no_warnings": True,
                "geo_bypass": True,
                "nocheckcertificate": True,
                "socket_timeout": 30,
                "retries": 3,
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

                segments, _ = _get_model().transcribe(audio_path)
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

                return {"status": "ok", "clips": clips}

            subprocess.run(
                ["ffmpeg", "-y", "-i", video_path, "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", audio_path],
                check=True,
                capture_output=True,
            )

            segments, _ = _get_model().transcribe(audio_path)
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

    app = Flask(__name__)

    def _local_worker_capacity() -> dict:
        max_concurrency = max(1, int(os.getenv("LOCAL_WORKER_MAX_CONCURRENCY", "1") or "1"))
        max_queue = max(0, int(os.getenv("LOCAL_WORKER_MAX_QUEUE", "0") or "0"))
        with _ACTIVE_REQUESTS_LOCK:
            inflight = int(_ACTIVE_REQUESTS)
        queue_depth = max(0, inflight - max_concurrency)
        can_accept = inflight < (max_concurrency + max_queue)
        return {
            "status": "ok",
            "gpu": _gpu_alive(),
            "inflight": inflight,
            "queue_depth": queue_depth,
            "max_concurrency": max_concurrency,
            "max_queue": max_queue,
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
        job = {"input": request.json}
        try:
            result = handler(job)
            return jsonify(result)
        finally:
            with _ACTIVE_REQUESTS_LOCK:
                _ACTIVE_REQUESTS = max(0, _ACTIVE_REQUESTS - 1)

    print("Local HTTP worker running on http://localhost:5000/run")
    app.run(host="0.0.0.0", port=5000, threaded=True)
else:
    runpod.serverless.start({"handler": handler})
