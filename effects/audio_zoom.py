import subprocess
import numpy as np
import tempfile
import os

def extract_wav(video_path: str) -> str:
    """
    Extract small WAV for fast RMS reading.
    Always returns a valid wav file or ''.
    """
    try:
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vn",
            "-ac", "1",
            "-ar", "16000",
            "-acodec", "pcm_s16le",
            tmp
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return tmp
    except:
        return ""


def compute_audio_zoom(video_path: str, boost: float = 0.12) -> float:
    """
    Ultra-fast audio RMS → zoom factor.
    boost: scaling factor for how strong zoom reacts.
    Output:
        1.00 (base zoom)
        up to ~1.15 (peaks)
    """

    # Extract minimal audio
    wav = extract_wav(video_path)
    if not wav or not os.path.exists(wav):
        return 1.0

    try:
        # read wav raw
        with open(wav, "rb") as f:
            raw = np.frombuffer(f.read(), dtype=np.int16)

        if len(raw) == 0:
            os.remove(wav)
            return 1.0

        # Normalize
        rms = float(np.sqrt(np.mean(raw.astype(float) ** 2)))

        # Convert to zoom
        zoom = 1.0 + (rms / 8000.0) * boost
        zoom = max(1.0, min(zoom, 1.18))  # clamp

        os.remove(wav)
        return round(zoom, 3)
    except:
        return 1.0
