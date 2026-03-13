import os
import yt_dlp
from faster_whisper import WhisperModel
import subprocess
import tempfile

model = WhisperModel("small", device="cuda")

def handler(event):
    """
    RunPod worker handler for YouTube transcription.
    Downloads video, extracts audio, runs Whisper transcription.
    """
    input_data = event.get("input", {})
    task = input_data.get("task")
    youtube_url = input_data.get("youtube_url")

    if task != "transcribe_youtube" or not youtube_url:
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