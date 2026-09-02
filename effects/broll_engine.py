import os
import requests
import logging
from urllib.parse import quote

log = logging.getLogger("broll_engine")

def fetch_broll_asset(keyword: str, output_path: str, width: int = 1080, height: int = 1920) -> str:
    """
    Fetches a cinematic B-roll image from Pollinations.ai based on the keyword.
    Returns the path to the downloaded image, or None if failed.
    """
    if not keyword:
        keyword = "cinematic podcast background"
        
    prompt = f"beautiful cinematic {keyword} highly detailed realistic"
    encoded_prompt = quote(prompt)
    url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width={width}&height={height}&nologo=true"
    
    log.info(f"[BROLL] Fetching asset for keyword: '{keyword}' -> {url}")
    
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        
        with open(output_path, "wb") as f:
            f.write(response.content)
            
        log.info(f"[BROLL] Successfully saved B-Roll asset to {output_path}")
        return output_path
    except Exception as e:
        log.error(f"[BROLL] Failed to fetch B-Roll asset: {e}")
        return None

def get_ken_burns_filter(start_time: float, duration: float, width: int = 1080, height: int = 1920) -> str:
    """
    Returns the buttery-smooth FFmpeg Ken Burns filter string.
    Uses the scale-before-zoom trick to eliminate pixel-rounding jitter.
    """
    # scale to massive resolution to fix zoompan integer truncation jitter
    # d is duration in frames (assumed 30fps)
    frames = int(max(duration, 5.0) * 30)
    return f"scale=4320:7680,zoompan=z='min(zoom+0.0015,1.5)':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps=30"
