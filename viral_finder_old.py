
import os
import re
import nltk
import yt_dlp
from faster_whisper import WhisperModel
from nltk.sentiment import SentimentIntensityAnalyzer
from concurrent.futures import ThreadPoolExecutor
import torch
torch.backends.cudnn.benchmark = True

# -----------------------------------------------------------
# SETUP
# -----------------------------------------------------------
nltk.download('vader_lexicon', quiet=True)
sia = SentimentIntensityAnalyzer()

# -----------------------------------------------------------
# 1. Extract YouTube Video ID
# -----------------------------------------------------------
def extract_video_id(url: str):
    match = re.search(r"(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})", url)
    return match.group(1) if match else None


# -----------------------------------------------------------
# 2. Download and/or Transcribe Video
# -----------------------------------------------------------
def download_audio(video_id: str):
    url = f"https://www.youtube.com/watch?v={video_id}"
    output_file = f"temp_audio_{video_id}"
    final_path = f"{output_file}.mp3"
    cookie_path = os.path.join(os.getcwd(), "cookies.txt")

    print("\n🎥 Fetching audio from:", url)
    print("🧩 Checking cookies at:", cookie_path)
    print("   Exists:", os.path.exists(cookie_path))

    # ✅ Always remove old files before downloading
    for ext in [".mp3", ".webm", ".m4a", ".part"]:
        f = f"{output_file}{ext}"
        if os.path.exists(f):
            os.remove(f)
            print(f"🧹 Removed old temp file: {f}")

    # ✅ yt-dlp options
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': output_file,
        'quiet': False,
        'cookiefile': cookie_path,
        'nocheckcertificate': True,
        'noplaylist': True,
        'no_warnings': True,
        'allow_unplayable_formats': True,
        'continuedl': False,    # 🚫 disable resume
        'overwrites': True,     # 🚫 overwrite old files
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        print(f"✅ Audio downloaded successfully → {final_path}")
        return final_path
    except Exception as e:
        print(f"❌ Audio download failed: {e}")
        return None


from faster_whisper import WhisperModel
import os
import os
import json
from faster_whisper import WhisperModel
import torch

def get_transcript(video_id: str):
    """Try YouTube captions; if none, fall back to Faster-Whisper GPU with caching."""
    cache_dir = "cache"
    os.makedirs(cache_dir, exist_ok=True)
    cache_file = os.path.join(cache_dir, f"{video_id}.json")

    # 1️⃣ Check cache
    if os.path.exists(cache_file):
        print(f"📦 Using cached transcript for {video_id}")
        with open(cache_file, "r", encoding="utf-8") as f:
            return json.load(f)

    print("⚙️ No cache found — generating transcript...")

    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        transcript = transcript_list.find_transcript(['en']).fetch()
        print("✅ Found YouTube transcript.")
    except Exception as e:
        print("⚠️ YouTube transcript not found. Using Faster-Whisper fallback...")
        audio_file = download_audio(video_id)
        if not audio_file:
            print("❌ Unable to download audio for Whisper.")
            return []

        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"🎧 Using Faster-Whisper on: {device.upper()}")
        torch.backends.cudnn.benchmark = True  

        model = WhisperModel("tiny.en", device=device, compute_type="float16")

        segments, info = model.transcribe(audio_file, beam_size=1)

        transcript = [
            {"text": seg.text, "start": seg.start, "end": seg.end}
            for seg in segments
        ]
        os.remove(audio_file)
        print(f"🎯 Transcription completed ({info.duration:.2f}s audio)")

    # 2️⃣ Save to cache
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(transcript, f, ensure_ascii=False, indent=2)
        print(f"💾 Transcript cached at: {cache_file}")

    return transcript



# -----------------------------------------------------------
# 3. Viral Analysis Logic
# -----------------------------------------------------------
def analyze_emotion(text: str):
    sentiment = sia.polarity_scores(text)
    emotion_score = abs(sentiment["compound"]) * (1 + (sentiment["pos"] + sentiment["neg"]))
    return emotion_score


VIRAL_KEYWORDS = [
    "crazy", "unbelievable", "insane", "moment", "wow", "shocking", "laugh",
    "epic", "must see", "viral", "unexpected", "best", "amazing", "funniest",
    "emotional", "insane"
]


def keyword_boost(text: str):
    boost = sum(text.lower().count(k) for k in VIRAL_KEYWORDS)
    return 1 + (boost * 0.4)

def score_transcript(transcript):
    scored_segments = []

    def score_segment(entry):
        text = entry["text"]
        start = entry["start"]
        end = entry.get("end", start + 5)
        emotion = analyze_emotion(text)
        boost = keyword_boost(text)
        total_score = emotion * boost
        return {
            "text": text,
            "start": start,
            "end": end,
            "score": total_score
        }

    with ThreadPoolExecutor(max_workers=8) as executor:
        scored_segments = list(executor.map(score_segment, transcript))

    return scored_segments



    

# -----------------------------------------------------------
# 4. Main Viral Finder
# -----------------------------------------------------------
def find_viral_moments(youtube_url, clip_length=15):
    video_id = extract_video_id(youtube_url)
    if not video_id:
        print("❌ Invalid YouTube link.")
        return []

    transcript = get_transcript(video_id)
    if not transcript:
        print("❌ Transcript not found.")
        return []

    scored_segments = score_transcript(transcript)
    scored_segments.sort(key=lambda x: x["score"], reverse=True)

    viral_moments = []
    for seg in scored_segments[:10]:
        start = max(0, seg["start"] - clip_length / 2)
        end = seg["end"] + clip_length / 2
        viral_moments.append({
            "start": round(start, 2),
            "end": round(end, 2),
            "text": seg["text"],
            "score": round(seg["score"], 3)
        })

    return viral_moments


# -----------------------------------------------------------
# 5. Test Run
# -----------------------------------------------------------
if __name__ == "__main__":
    url = input("Paste a YouTube link: ")
    moments = find_viral_moments(url)
    if not moments:
        print("❌ No viral moments found.")
    else:
        for i, m in enumerate(moments, 1):
            print(f"\n{i}. [{m['start']}s - {m['end']}s] Score: {m['score']}")
            print(f"   “{m['text']}”")
