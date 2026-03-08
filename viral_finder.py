# HOTSHORT GOD MODE
# REVIVED AND REBUILT
#
# This system is architected for pure, unsuppressed cognitive analysis.
# It operates on principles of semantic arc construction, not simple sentiment.
#
# LAYER 0: COGNITION ENGINE (The Brain)
# LAYER 1: ACQUISITION (The Senses)

import os
import re
import json
import time
import threading
import hashlib
import numpy as np
import yt_dlp
import torch
from sentence_transformers import SentenceTransformer, util
from faster_whisper import WhisperModel
from yt_dlp.networking.impersonate import ImpersonateTarget

# ======================================================================================
# MODEL MANAGEMENT
# Centralized loading for AI models to ensure they are loaded only once.
# ======================================================================================

_MODELS = {}
_MODEL_LOCK = threading.Lock()

def load_models(device="cuda"):
    """Loads all required AI models once and returns them."""
    with _MODEL_LOCK:
        if "sentence_transformer" in _MODELS and "whisper" in _MODELS:
            return _MODELS

        print(f"[INFO] Loading AI models on {device.upper()} ...")
        try:
            torch.backends.cudnn.benchmark = True
        except Exception:
            pass
            
        st_model = SentenceTransformer('all-MiniLM-L6-v2', device=device)
        _MODELS["sentence_transformer"] = st_model
        print("[SUCCESS] SentenceTransformer model ready.")
        
        whisper_model = WhisperModel("base.en", device=device, compute_type="float16")
        _MODELS["whisper"] = whisper_model
        print("[SUCCESS] Whisper model ready.")
        
        return _MODELS

# ======================================================================================
# LAYER 1: ACQUISITION
# Fetches media and transcripts. Provides data and quality signals to the Cognition Engine.
# ======================================================================================

class AcquisitionLayer:
    """
    Handles the retrieval of video transcripts, acting as the sensory input for the Cognition Engine.
    """
    def __init__(self, whisper_model, cache_dir="cache"):
        self.whisper_model = whisper_model
        self.cache_dir = cache_dir
        os.makedirs(self.cache_dir, exist_ok=True)

    def _get_url_details(self, url: str):
        """Identifies URL type and creates a unique, safe identifier for it."""
        yt_match = re.search(r"(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})", url)
        if yt_match:
            video_id = yt_match.group(1)
            return video_id, 'youtube'
        
        url_hash = hashlib.sha1(url.encode('utf-8')).hexdigest()
        return url_hash, 'other'

    def _download_audio(self, url: str, identifier: str):
        """Downloads audio using yt-dlp with robust settings."""
        output_file = os.path.join(self.cache_dir, f"temp_audio_{identifier}.mp3")

        print(f"\n[INFO] Fetching audio from: {url}")
        cookie_path = os.path.join(os.getcwd(), "cookies.txt")

        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": output_file.replace('.mp3', '.%(ext)s'),
            "quiet": True,
            "noplaylist": True,
            "nocheckcertificate": True,
            "socket_timeout": 30,
            "retries": 5,
            "fragment_retries": 5,
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}],
            "impersonate": ImpersonateTarget.from_str("chrome"),
        }
        if os.path.exists(cookie_path):
            ydl_opts["cookiefile"] = cookie_path

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            return output_file
        except Exception as e:
            print(f"[ERROR] Audio download failed: {e}")
            return None

    def get_transcript(self, url: str, force_refresh: bool = False):
        """
        Gets a full transcript.
        
        !!! DEVELOPMENT OVERRIDE !!!
        This function is currently hardcoded to read from `mock_transcript.json`
        to bypass network issues with yt-dlp. This allows for development
        of the Cognition Engine. To re-enable network functionality, remove this override.
        """
        mock_path = "mock_transcript.json"
        if os.path.exists(mock_path):
            print(f"[WARNING] DEV OVERRIDE: Loading from {mock_path}")
            with open(mock_path, "r", encoding="utf-8") as f:
                return json.load(f), "mock"
        else:
            print(f"[ERROR] Mock transcript not found at {mock_path}")
            return [], "mock_failed"

        # --- ORIGINAL NETWORK LOGIC ---
        # The following code is disabled during the dev override.
        
        # identifier, url_type = self._get_url_details(url)
        # cache_path = os.path.join(self.cache_dir, f"{identifier}.json")

        # if not force_refresh and os.path.exists(cache_path):
        #     print(f"[INFO] Cached transcript found -> {cache_path}")
        #     with open(cache_path, "r", encoding="utf-8") as f:
        #         return json.load(f), "cached"

        # if url_type == 'youtube':
        #     try:
        #         from youtube_transcript_api import YouTubeTranscriptApi
        #         transcript_list = YouTubeTranscriptApi.list_transcripts(identifier)
        #         yt_transcript = transcript_list.find_transcript(['en']).fetch()
        #         if not yt_transcript:
        #             raise ValueError("Empty transcript from API")
                
        #         print("[SUCCESS] Found official YouTube transcript.")
        #         with open(cache_path, "w", encoding="utf-8") as f:
        #             json.dump(yt_transcript, f, indent=2)
        #         return yt_transcript, "youtube_api"
        #     except Exception:
        #         print("[WARNING] YouTube captions not found. Falling back to Whisper transcription.")

        # audio_file = self._download_audio(url, identifier)
        # if not audio_file or not os.path.exists(audio_file):
        #     return [], "download_failed"
            
        # print(f"[INFO] Transcribing with Faster-Whisper...")
        # start_time = time.time()
        # try:
        #     segments, _ = self.whisper_model.transcribe(
        #         audio_file, beam_size=1, vad_filter=True, vad_parameters=dict(min_silence_duration_ms=250)
        #     )
        #     transcript = [{"text": s.text.strip(), "start": s.start, "end": s.end} for s in segments if s.text.strip()]
            
        #     if not transcript:
        #          return [], "transcription_failed_empty"

        #     print(f"[SUCCESS] Transcription complete in {time.time() - start_time:.2f}s")
        #     with open(cache_path, "w", encoding="utf-8") as f:
        #         json.dump(transcript, f, ensure_ascii=False, indent=2)
            
        #     return transcript, "whisper"
        # except Exception as e:
        #     print(f"[ERROR] Whisper transcription failed: {e}")
        #     return [], "transcription_failed_exception"
        # finally:
        #     if os.path.exists(audio_file):
        #         os.remove(audio_file)

# ======================================================================================
# LAYER 0: COGNITION ENGINE
# This is the "God Mode" brain. It only thinks.
# ======================================================================================

class CognitionEngine:
    """
    The core intelligence. It constructs a cognitive map of the content.
    """
    def __init__(self, sentence_transformer_model, device="cuda"):
        self.device = device
        self.model = sentence_transformer_model

    def _embed_transcript(self, transcript):
        """Computes semantic embeddings for each transcript segment."""
        if not transcript:
            return None, None
        sentences = [segment['text'] for segment in transcript]
        embeddings = self.model.encode(sentences, convert_to_tensor=True, device=self.device)
        return sentences, embeddings

    def _cluster_semantically(self, transcript, embeddings, threshold=0.5):
        """
        Groups transcript segments into semantic clusters (arcs) using cosine similarity.
        """
        if embeddings is None or len(embeddings) == 0:
            return []
        
        print(f"[COGNITION] Performing semantic clustering with threshold {threshold}...")
        
        cos_sim = util.pytorch_cos_sim(embeddings, embeddings)
        
        clusters = []
        visited = [False] * len(transcript)
        
        for i in range(len(transcript)):
            if visited[i]:
                continue
            
            current_cluster = {'segments': [], 'arc_id': len(clusters) + 1}
            queue = [i]
            visited[i] = True
            
            while queue:
                current_idx = queue.pop(0)
                current_cluster['segments'].append({
                    **transcript[current_idx],
                    'segment_id': current_idx
                })
                
                for j in range(len(transcript)):
                    if not visited[j] and cos_sim[current_idx][j] >= threshold:
                        visited[j] = True
                        queue.append(j)
            
            current_cluster['segments'].sort(key=lambda x: x['start'])
            clusters.append(current_cluster)
            
        print(f"[SUCCESS] Found {len(clusters)} semantic arcs.")
        return clusters

    # ... (placeholders for other cognition methods) ...
    def _detect_emotional_surges(self, transcript):
        print("[COGNITION] Detecting emotional surges...")
        return []
    def _identify_narrative_punches(self, clusters, emotions):
        print("[COGNITION] Identifying narrative punches...")
        return []
    def _calculate_depth_and_escalation(self, arcs):
        print("[COGNITION] Calculating depth and escalation...")
        return []
    def _merge_and_define_clips(self, arcs):
        print("[COGNITION] Defining final clips...")
        return []

    def find_viral_moments(self, transcript, acquisition_quality):
        """
        The main cognitive orchestration function.
        """
        if not transcript:
            print("CognitionEngine: Aborting, transcript is empty.")
            return []

        print(f"\n--- Starting God Mode Cognition (Quality: {acquisition_quality}) ---")
        sentences, embeddings = self._embed_transcript(transcript)
        clusters = self._cluster_semantically(transcript, embeddings, threshold=0.45)
        print("--- God Mode Cognition Complete ---")
        return clusters

# ======================================================================================
# Main Orchestrator
# ======================================================================================

def run_viral_finder(url: str, models):
    """
    High-level orchestrator.
    """
    acquisition = AcquisitionLayer(whisper_model=models["whisper"])
    cognition = CognitionEngine(sentence_transformer_model=models["sentence_transformer"])
    
    transcript, quality_signal = acquisition.get_transcript(url)

    if not transcript:
        print("[ERROR] Could not acquire a transcript. Aborting.")
        return []

    viral_moments = cognition.find_viral_moments(transcript, acquisition_quality=quality_signal)
    return viral_moments

if __name__ == "__main__":
    if len(os.sys.argv) > 1:
        url = os.sys.argv[1]
    else:
        url = input("[INFO] Paste a video link: ")
    
    # Load models once at the start
    loaded_models = load_models()
    
    clusters = run_viral_finder(url, loaded_models)
    
    if not clusters:
        print("\n[ERROR] No semantic arcs constructed.")
    else:
        print("\n*** Semantic Arcs Constructed ***")
        for cluster in clusters:
            sorted_segments = sorted(cluster['segments'], key=lambda s: s['start'])
            print(f"\n[SUCCESS] ARC {cluster['arc_id']} ({len(sorted_segments)} segments)")
            for segment in sorted_segments:
                print(f"   [{segment['start']:.2f}s] \"{segment['text']}\"")
