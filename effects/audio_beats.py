# audio_beats.py
import numpy as np
import librosa

def analyze_beats(audio_path: str,
                  frame_ms: int = 120,
                  peak_ratio: float = 0.72,
                  top_k:int = 25):
    """
    Ultra-Fast Beat Scanner
    -----------------------
    - converts audio into energy envelopes (RMS)
    - picks high-energy peaks as beat markers
    - structure for jump-cut decisions

    Output keys:
      {
        "beats": [(timestamp, strength), ...],
        "curve": [... normalized rms ...],
        "fps": float
      }
    """

    # ---- Load short mono audio ----
    sig, sr = librosa.load(audio_path, sr=None, mono=True)
    if sig is None or len(sig) == 0:
        return {"beats": [], "curve": [], "fps": 0.0}

    # ---- Frame hop ----
    hop = int(sr * (frame_ms / 1000.0))
    if hop <= 0:
        hop = 512

    # ---- RMS Energy ----
    rms = librosa.feature.rms(y=sig, frame_length=hop, hop_length=hop).flatten()
    if len(rms) == 0:
        return {"beats": [], "curve": [], "fps": 0.0}

    # ---- Normalize ----
    rms_norm = (rms - rms.min()) / (rms.max() - rms.min() + 1e-9)

    # ---- Peak threshold ----
    thresh = np.quantile(rms_norm, peak_ratio)

    peaks = []
    for idx, val in enumerate(rms_norm):
        if val >= thresh:
            ts = (idx * hop) / sr
            peaks.append((round(ts, 2), round(float(val), 4)))

    # ---- Limit peaks for stability ----
    peaks = sorted(peaks, key=lambda x: x[1], reverse=True)[:top_k]
    peaks = sorted(peaks, key=lambda x: x[0])  # timeline order

    return {
        "beats": peaks,
        "curve": rms_norm.tolist(),
        "fps": len(rms_norm) / (len(sig) / sr)
    }
