import os
import subprocess
import tempfile

import runpod
import yt_dlp
from dotenv import load_dotenv
from faster_whisper import WhisperModel

try:
    import torch
except ImportError:
    torch = None

try:
    from transformers import CLIPProcessor, CLIPModel
    import cv2
    from scenedetect import detect, ContentDetector
    from PIL import Image
    _VISUAL_AVAILABLE = True
except ImportError:
    _VISUAL_AVAILABLE = False

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


def _load_whisper_model() -> WhisperModel:
    device = "cuda" if _gpu_alive() else "cpu"
    model_name = (os.getenv("WHISPER_MODEL") or "small").strip() or "small"
    return WhisperModel(model_name, device=device)


model = _load_whisper_model()
_CLIP_MODEL = None
_CLIP_PROCESSOR = None

def _load_clip_model():
    global _CLIP_MODEL, _CLIP_PROCESSOR
    if not _VISUAL_AVAILABLE:
        return
    if _CLIP_MODEL is None:
        device = "cuda" if _gpu_alive() else "cpu"
        print(f"Loading CLIP model on {device}...")
        _CLIP_PROCESSOR = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
        _CLIP_MODEL = CLIPModel.from_pretrained("openai/clip-vit-base-patch32").to(device)

if _VISUAL_AVAILABLE:
    _load_clip_model()

def _process_visual_scenes(video_path: str, labels: list = None) -> list:
    if not _VISUAL_AVAILABLE or _CLIP_MODEL is None:
        return []
    
    if not labels:
        labels = [
            "person talking", "podcast studio", "street interview", 
            "gameplay", "screencast", "outdoor nature", "b-roll", "reaction face"
        ]
        
    print(f"[VISUAL] Detecting scenes in {video_path}...")
    scene_list = detect(video_path, ContentDetector(threshold=27.0))
    
    hero_frames = []
    scene_timestamps = []
    
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    
    for scene in scene_list:
        start_frame = scene[0].get_frames()
        end_frame = scene[1].get_frames()
        middle_frame = start_frame + ((end_frame - start_frame) // 2)
        
        cap.set(cv2.CAP_PROP_POS_FRAMES, middle_frame)
        ret, frame = cap.read()
        if ret:
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            hero_frames.append(Image.fromarray(frame_rgb))
            scene_timestamps.append({
                "start": round(start_frame / fps, 2),
                "end": round(end_frame / fps, 2)
            })
    cap.release()
    
    if not hero_frames:
        return []
        
    print(f"[VISUAL] Running batch CLIP inference on {len(hero_frames)} scenes...")
    device = "cuda" if _gpu_alive() else "cpu"
    inputs = _CLIP_PROCESSOR(text=labels, images=hero_frames, return_tensors="pt", padding=True).to(device)
    
    with torch.no_grad():
        outputs = _CLIP_MODEL(**inputs)
        probs = outputs.logits_per_image.softmax(dim=1)
        
    visual_scenes = []
    probs_cpu = probs.cpu().numpy()
    
    for i, ts in enumerate(scene_timestamps):
        best_idx = probs_cpu[i].argmax()
        visual_scenes.append({
            "start": ts["start"],
            "end": ts["end"],
            "visual_label": labels[best_idx],
            "visual_confidence": round(float(probs_cpu[i][best_idx]), 3)
        })
        
    return visual_scenes

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


def _process_transcription(audio_path: str) -> list:
    """
    Elite streaming transcription with smart buffering.
    Merges segments with < 1s gaps to massively speed up downstream NLP.
    """
    vad_params = dict(min_silence_duration_ms=400, threshold=0.5)
    segments_stream, _ = model.transcribe(
        audio_path,
        beam_size=1,
        vad_filter=True,
        vad_parameters=vad_params,
        word_timestamps=False,
        task="translate",
        condition_on_previous_text=False
    )

    out_segments = []
    buffer = []
    last_segment_end = 0.0

    for segment in segments_stream:
        text = segment.text.strip()
        if not text:
            continue
        # > 1s gap means a different thought, flush the buffer
        if buffer and (segment.start - last_segment_end) > 1.0:
            out_segments.append({
                "start": round(buffer[0].start, 2),
                "end": round(buffer[-1].end, 2),
                "text": " ".join(s.text.strip() for s in buffer)
            })
            buffer = []
        buffer.append(segment)
        last_segment_end = segment.end

    if buffer:
        out_segments.append({
            "start": round(buffer[0].start, 2),
            "end": round(buffer[-1].end, 2),
            "text": " ".join(s.text.strip() for s in buffer)
        })
    return out_segments


def handler(event):
    input_data = event.get("input", {})
    task = input_data.get("task")
    youtube_url = input_data.get("youtube_url") or input_data.get("url")
    transcript = input_data.get("transcript") or []

    cloud_provider = input_data.get("cloud_provider", {})
    if isinstance(cloud_provider, dict):
        if cloud_provider.get("cloud_name"):
            os.environ["CLOUDINARY_CLOUD_NAME"] = cloud_provider.get("cloud_name", "")
        if cloud_provider.get("api_key"):
            os.environ["CLOUDINARY_API_KEY"] = cloud_provider.get("api_key", "")
        if cloud_provider.get("api_secret"):
            os.environ["CLOUDINARY_API_SECRET"] = cloud_provider.get("api_secret", "")

    if not task:
        return {"error": "Invalid task: missing task"}
    if task == "healthcheck":
        return {"status": "ok", "gpu": _gpu_alive()}
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
                "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best",
                "merge_output_format": "mp4",
                "outtmpl": video_path,
                "quiet": True,
                "no_warnings": True,
                "geo_bypass": True,
                "nocheckcertificate": True,
                "socket_timeout": 15,
                "retries": 3,
                "concurrent_fragment_downloads": 10,
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
                    return {"error": "Upload failed (no cloud provider configured), cannot provide a public video_url."}
                return {"video_url": video_url}

            if task == "transcribe_youtube":
                subprocess.run(
                    ["ffmpeg", "-y", "-threads", "0", "-i", video_path, "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", audio_path],
                    check=True,
                    capture_output=True,
                )
                out_segments = _process_transcription(audio_path)
            
                result = {
                        "status": "ok",
                        "segments": out_segments,
                    }
                
                if input_data.get("include_visual") and _VISUAL_AVAILABLE:
                    result["visual_scenes"] = _process_visual_scenes(video_path, input_data.get("visual_labels"))
                    
                return result

            if task == "orchestrate":
                try:
                    from viral_finder.orchestrator import orchestrate
                except Exception as e:
                    return {"error": f"Failed to import orchestrator: {e}"}

                visual_data = []
                if input_data.get("include_visual") and _VISUAL_AVAILABLE:
                    visual_data = _process_visual_scenes(video_path, input_data.get("visual_labels"))

                clips = orchestrate(
                    video_path,
                    top_k=int(os.environ.get("HS_ORCH_TOP_K", "8")),
                    prefer_gpu=True,
                    use_cache=True,
                    allow_fallback=False,
                    pipeline_mode=os.environ.get("HS_ORCH_PIPELINE_MODE", None),
                )
                result = {"status": "ok", "clips": clips}
                if visual_data:
                    result["visual_scenes"] = visual_data
                return result

            subprocess.run(
                ["ffmpeg", "-y", "-threads", "0", "-i", video_path, "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", audio_path],
                check=True,
                capture_output=True,
            )
            out_segments = _process_transcription(audio_path)
            return {"segments": out_segments}
    except Exception as e:
        return {"error": str(e)}


if os.getenv("LOCAL_HTTP_WORKER") == "1":
    from flask import Flask, jsonify, request

    app = Flask(__name__)

    @app.route("/", methods=["GET"])
    def health():
        return jsonify({"status": "ok", "message": "Worker ready. POST to /run with task data."})

    @app.route("/run", methods=["POST"])
    def run_local():
        job = {"input": request.json}
        return jsonify(handler(job))

    print("Local HTTP worker running on http://localhost:5000/run")
    app.run(host="0.0.0.0", port=5000)
else:
    runpod.serverless.start({"handler": handler})
