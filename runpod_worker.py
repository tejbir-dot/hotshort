import os
import yt_dlp
from faster_whisper import WhisperModel
import subprocess
import tempfile

# Optional helper: upload output to S3 (for public URL delivery)
try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except ImportError:
    boto3 = None

# Optional helper: upload output to Cloudinary (for public URL delivery)
try:
    import cloudinary
    import cloudinary.uploader
    _CLOUDINARY_AVAILABLE = True
except ImportError:
    cloudinary = None
    _CLOUDINARY_AVAILABLE = False


def _configure_cloudinary() -> bool:
    """Configure cloudinary from environment variables.

    Returns True if Cloudinary is configured and ready to upload.

    Expected env vars:
      - CLOUDINARY_CLOUD_NAME
      - CLOUDINARY_API_KEY
      - CLOUDINARY_API_SECRET
    """

    if not _CLOUDINARY_AVAILABLE:
        return False

    cloud_name = os.environ.get("CLOUDINARY_CLOUD_NAME")
    api_key = os.environ.get("CLOUDINARY_API_KEY")
    api_secret = os.environ.get("CLOUDINARY_API_SECRET")

    if not (cloud_name and api_key and api_secret):
        return False

    cloudinary.config(
        cloud_name=cloud_name,
        api_key=api_key,
        api_secret=api_secret,
    )
    return True


def _upload_to_cloudinary(local_path: str) -> str | None:
    """Upload a local file to Cloudinary and return a public URL."""

    if not _configure_cloudinary():
        return None

    try:
        result = cloudinary.uploader.upload(local_path, resource_type="video")
        return result.get("secure_url")
    except Exception as e:
        print("Cloudinary upload failed:", e)
        return None

model = WhisperModel("small", device="cuda")


def _upload_to_s3(local_path: str) -> str | None:
    """Upload a local file to S3 and return a public URL.

    Environment variables (optional):
      - AWS_S3_BUCKET or S3_BUCKET
      - AWS_REGION (default: us-east-1)
      - AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY

    If the env vars are not set or boto3 is unavailable, this returns None.
    """
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
    """RunPod worker handler.

    Supports:
      - task="download": download YouTube -> return {"file_url": "https://..."}
      - task="transcribe_youtube": download + whisper transcription.
    """

    input_data = event.get("input", {})
    task = input_data.get("task")
    youtube_url = input_data.get("youtube_url")

    if not task or not youtube_url:
        return {"error": "Invalid task or missing youtube_url"}

    try:
        # Create temp directory
        with tempfile.TemporaryDirectory() as temp_dir:
            video_path = os.path.join(temp_dir, "video.mp4")
            audio_path = os.path.join(temp_dir, "audio.wav")

            # Download video with yt-dlp
            ydl_opts = {
                "format": "best",
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
                }
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([youtube_url])

            # If RunPod is used as a download proxy, return a public URL for the file.
            if task == "download":
                # Prefer Cloudinary when it is configured (CLOUDINARY_* env vars).
                video_url = _upload_to_cloudinary(video_path) or _upload_to_s3(video_path)
                if not video_url:
                    # Fail early: Render cannot download file:// URLs.
                    return {
                        "error": "Upload failed (no cloud provider configured), cannot provide a public video_url."
                    }

                print("DOWNLOAD DONE:", video_path, "->", video_url)

                # Return a stable public URL that can be used by web clients.
                return {"video_url": video_url}

            # Extract audio with ffmpeg
            subprocess.run([
                "ffmpeg", "-y", "-i", video_path, "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", audio_path
            ], check=True, capture_output=True)

            # Transcribe with Whisper
            segments, _ = model.transcribe(audio_path)

            # Format segments
            transcript = []
            for s in segments:
                transcript.append({
                    "start": s.start,
                    "end": s.end,
                    "text": s.text
                })

            return {"segments": transcript}

    except Exception as e:
        return {"error": str(e)}