import os
import re
import json
import time
import torch
import threading
import nltk
from nltk.sentiment import SentimentIntensityAnalyzer
from faster_whisper import WhisperModel
from youtube_transcript_api import YouTubeTranscriptApi
import yt_dlp

# -----------------------------------------------------------
# Initialize Sentiment Engine
# -----------------------------------------------------------
nltk.download('vader_lexicon', quiet=True)
sia = SentimentIntensityAnalyzer()

# -----------------------------------------------------------
# GLOBAL Whisper Model (cached once for speed)
# -----------------------------------------------------------
_MODEL = None
_MODEL_LOCK = threading.Lock()
_MODEL_NAME = "tiny.en"          # fastest English model
_COMPUTE_TYPE = "float16"        # perfect for GTX 1630

def _get_or_load_model(device="cuda"):
    """Load Whisper model once, reuse it for all transcriptions."""
    global _MODEL
    if _MODEL is not None:
        return _MODEL

    with _MODEL_LOCK:
        if _MODEL is not None:
            return _MODEL

        print(f"⚡ Loading Faster-Whisper model ({_MODEL_NAME}) on {device.upper()} ...")
        try:
            torch.backends.cudnn.benchmark = True
        except Exception:
            pass

        _MODEL = WhisperModel(_MODEL_NAME, device=device, compute_type=_COMPUTE_TYPE)
        print("✅ Whisper model ready.")
        return _MODEL

# -----------------------------------------------------------
# Extract YouTube Video ID
# -----------------------------------------------------------
def extract_video_id(url: str):
    match = re.search(r"(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})", url)
    return match.group(1) if match else None

# -----------------------------------------------------------
# Download Audio using yt_dlp
# -----------------------------------------------------------
def download_audio(video_id: str):
    url = f"https://www.youtube.com/watch?v={video_id}"
    output_file = f"temp_audio_{video_id}.mp3"

    print(f"\n🎥 Fetching audio from: {url}")
    cookie_path = os.path.join(os.getcwd(), "cookies.txt")
    print(f"🧩 Using cookies: {os.path.exists(cookie_path)}")

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": f"temp_audio_{video_id}.%(ext)s",
        "quiet": True,
        "noplaylist": True,
        "nocheckcertificate": True,
        "socket_timeout": 30,
        "max_downloads": 1,
        "http_chunk_size": 10485760,  # 10MB chunks
        # Retries + backoff to reduce transient 429s on shared IPs.
        "retries": 5,
        "fragment_retries": 5,
        "sleep_interval": 5,
        "max_sleep_interval": 15,
        # Prefer Android client which is typically less aggressively rate-limited.
        "extractor_args": {
            "youtube": {
                "player_client": ["android"],
            }
        },
        # Anti-blocking measures for HTTP 403 errors
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-us,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        },
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
    }

    # Add cookie file only if it exists
    if os.path.exists(cookie_path):
        ydl_opts["cookiefile"] = cookie_path

    try:
        print("[TRANSCRIPT] Starting yt-dlp audio download…")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        print(f"✅ Audio downloaded successfully → {output_file}")
        return output_file
    except Exception as e:
        msg = str(e) or repr(e)
        if "HTTP Error 429" in msg or "Too Many Requests" in msg or "429:" in msg:
            print("❌ Audio download rate-limited by YouTube (HTTP 429). Please retry in 1–2 minutes.")
        else:
            print("❌ Audio download failed:", msg)
        return None

# -----------------------------------------------------------
# Super Fast Transcription (GPU + Cache)
# -----------------------------------------------------------
def get_transcript(video_id: str, max_duration=None, force_refresh=False):
    """Fast GPU Whisper transcription with caching and YouTube fallback."""
    cache_dir = "cache"
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, f"{video_id}.json")

    # Check cache
    if not force_refresh and os.path.exists(cache_path):
        print(f"📦 Cached transcript found → {cache_path}")
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)

    # Try YouTube captions
    try:
        print("🔎 Trying YouTube captions first...")
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        yt_transcript = transcript_list.find_transcript(['en']).fetch()
        print("✅ Found YouTube captions.")
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(yt_transcript, f, indent=2)
        return yt_transcript
    except Exception as e:
        print("⚠️ YouTube captions not found. Falling back to Whisper.")
        print("🪲 Debug:", e)

    # Download audio
    audio_file = download_audio(video_id)
    if not audio_file or not os.path.exists(audio_file):
        print("❌ Audio file missing after download.")
        return []

    start = time.time()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = _get_or_load_model(device=device)

    print(f"🎧 Transcribing with Faster-Whisper ({device.upper()}) ...")
    try:
        segments, info = model.transcribe(audio_file, beam_size=1)
        if max_duration:
            segments = [s for s in segments if s.start < max_duration]
            print(f"⏩ Preview Mode: Trimmed to {max_duration}s")

        transcript = [{"text": s.text, "start": s.start, "end": s.end} for s in segments]
        print(f"🎯 Transcription completed in {time.time()-start:.2f}s — {len(transcript)} segments")

        # Cache transcript
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(transcript, f, ensure_ascii=False, indent=2)
        print(f"💾 Transcript cached → {cache_path}")

        os.remove(audio_file)
        return transcript

    except Exception as e:
        print("❌ Faster-Whisper failed:", e)
        return []

# -----------------------------------------------------------
# Emotion + Keyword Scoring
# -----------------------------------------------------------
def analyze_emotion(text: str):
    sentiment = sia.polarity_scores(text)
    return abs(sentiment["compound"]) * (1 + sentiment["pos"] + sentiment["neg"])

VIRAL_KEYWORDS = [
    "crazy", "unbelievable", "insane", "moment", "wow", "shocking",
    "epic", "viral", "best", "funniest", "emotional", "amazing"
]

def keyword_boost(text: str):
    return 1 + (sum(text.lower().count(k) for k in VIRAL_KEYWORDS) * 0.4)

# -----------------------------------------------------------
# Viral Segment Finder
# -----------------------------------------------------------
def score_transcript(transcript):
    results = []
    for t in transcript:
        score = analyze_emotion(t["text"]) * keyword_boost(t["text"])
        results.append({**t, "score": round(score, 3)})
    return sorted(results, key=lambda x: x["score"], reverse=True)

def find_viral_moments(youtube_url, clip_length=15):
    video_id = extract_video_id(youtube_url)
    if not video_id:
        print("❌ Invalid YouTube URL.")
        return []

    transcript = get_transcript(video_id, max_duration=None)
    if not transcript:
        print("❌ No transcript found.")
        return []

    scored = score_transcript(transcript)
    moments = []
    for s in scored[:10]:
        start = max(0, s["start"] - clip_length / 2)
        end = s["end"] + clip_length / 2
        moments.append({
            "start": round(start, 2),
            "end": round(end, 2),
            "text": s["text"],
            "score": s["score"]
        })
    return moments

# -----------------------------------------------------------
# Main Entry Point
# -----------------------------------------------------------
if __name__ == "__main__":
    url = input("🎥 Paste a YouTube link: ")
    moments = find_viral_moments(url)
    for i, m in enumerate(moments, 1):
        print(f"\n{i}. [{m['start']}s - {m['end']}s] 🔥 Score: {m['score']}")
        print(f"   → {m['text']}")
