import os
import random
import requests
import logging
from typing import List, Optional

log = logging.getLogger(__name__)

PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")

def fetch_b_roll_for_keywords(keywords: List[str], target_dir: str = "assets/professional_broll") -> Optional[str]:
    """
    Fetches a high-quality vertical/horizontal video from Pexels based on keywords.
    Returns the local path of the downloaded video, or None if failed.
    """
    if not PEXELS_API_KEY:
        log.warning("[BROLL_ENGINE] PEXELS_API_KEY is not set. Cannot fetch dynamic B-roll.")
        return None
        
    if not keywords:
        return None

    os.makedirs(target_dir, exist_ok=True)
    
    # Pick the most relevant keyword or combine them
    log.info(f"[BROLL_ENGINE] 🧠 A.I. Director Thinking: Received keywords {keywords} from LLM Cortex.")
    query = keywords[0] if len(keywords) == 1 else random.choice(keywords)
    log.info(f"[BROLL_ENGINE] 🎯 Selected target keyword: '{query}' for Pexels search.")
    
    headers = {
        "Authorization": PEXELS_API_KEY
    }
    
    params = {
        "query": query,
        "per_page": 10,
        "orientation": "portrait", # Good for Shorts/TikTok
        "size": "large"
    }
    
    log.info(f"[BROLL_ENGINE] 📡 Initiating Pexels API Call: GET https://api.pexels.com/videos/search?query={query}&orientation=portrait")
    try:
        response = requests.get("https://api.pexels.com/videos/search", headers=headers, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        videos = data.get("videos", [])
        if not videos:
            log.warning(f"[BROLL_ENGINE] No videos found for query: '{query}'")
            return None
            
        # Pick a random video from top results to avoid repetition
        video = random.choice(videos[:5])
        video_files = video.get("video_files", [])
        
        # Sort by quality (highest res that isn't too huge, usually HD is fine)
        # For shorts, a height >= 1080 is ideal
        best_file = None
        for vf in sorted(video_files, key=lambda x: x.get("height", 0), reverse=True):
            if vf.get("link"):
                best_file = vf
                break
                
        if not best_file:
            return None
            
        video_url = best_file["link"]
        video_id = video["id"]
        
        local_filename = f"pexels_{video_id}.mp4"
        local_path = os.path.join(target_dir, local_filename)
        
        # Avoid re-downloading
        if os.path.exists(local_path):
            log.info(f"[BROLL_ENGINE] Using cached B-roll: {local_path}")
            return local_path
            
        # Download the video
        log.info(f"[BROLL_ENGINE] Downloading B-roll {video_id} from Pexels...")
        r = requests.get(video_url, stream=True, timeout=30)
        r.raise_for_status()
        
        with open(local_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
                
        log.info(f"[BROLL_ENGINE] Downloaded B-roll successfully: {local_path}")
        return local_path

    except Exception as e:
        log.error(f"[BROLL_ENGINE] Failed to fetch B-roll: {e}")
        return None
