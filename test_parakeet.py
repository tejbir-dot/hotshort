import os
import time
import requests
import base64
import json
from dotenv import load_dotenv

load_dotenv()

OPEN_ROUTER_API = os.getenv("OPEN_ROUTER_API")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

audio_file = "test_punjabi.mp3"

def download_sample_audio():
    # We will use yt-dlp to download a small 1 minute punjabi podcast clip
    if not os.path.exists(audio_file):
        print("Downloading sample audio...")
        os.system('yt-dlp -x --audio-format mp3 --audio-quality 0 --postprocessor-args "-ac 1 -ar 16000" --download-sections "*00:01:00-00:02:00" -o "test_punjabi.%(ext)s" "https://www.youtube.com/watch?v=D-z_Nf50Pqk"')

def test_whisper_groq():
    print("Testing Whisper (Groq)...")
    
    start_time = time.time()
    with open(audio_file, "rb") as file:
        response = requests.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}"
            },
            files={
                "file": (audio_file, file, "audio/mpeg")
            },
            data={
                "model": "whisper-large-v3",
                "response_format": "verbose_json"
            }
        )
    end_time = time.time()
    
    print(f"Whisper Time: {end_time - start_time:.2f}s")
    
    try:
        out = response.json()
        with open("whisper_out.json", "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        return out
    except Exception as e:
        print("Error parsing whisper response", e)
        print(response.text)
        return None

def test_parakeet_openrouter():
    print("Testing Parakeet (OpenRouter)...")
    start_time = time.time()
    
    with open(audio_file, "rb") as f:
        audio_b64 = base64.b64encode(f.read()).decode()

    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPEN_ROUTER_API}",
            "Content-Type": "application/json"
        },
        json={
            "model": "nvidia/parakeet-tdt-0.6b-v3",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Transcribe this audio"
                        },
                        {
                            "type": "input_audio",
                            "audio_url": {
                                "url": f"data:audio/mp3;base64,{audio_b64}"
                            }
                        }
                    ]
                }
            ]
        }
    )
    
    end_time = time.time()
    print(f"Parakeet Time: {end_time - start_time:.2f}s")
    
    try:
        out = response.json()
        with open("parakeet_out.json", "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        return out
    except Exception as e:
        print("Error parsing parakeet response", e)
        print(response.text)
        return None

if __name__ == "__main__":
    download_sample_audio()
    if os.path.exists(audio_file):
        test_whisper_groq()
        test_parakeet_openrouter()
    else:
        print("Failed to download audio")
