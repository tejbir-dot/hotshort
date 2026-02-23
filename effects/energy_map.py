import cv2
import numpy as np
import subprocess
from typing import List

# -------------------------------
# FAST AUDIO RMS (NO LIBROSA)
# -------------------------------
def extract_audio_rms(
    video_path: str,
    samples: int
) -> np.ndarray:

    cmd = [
        "ffmpeg", "-i", video_path,
        "-vn", "-ac", "1",
        "-af", f"astats=metadata=1:reset=1,aresample={samples}",
        "-f", "null", "-"
    ]

    p = subprocess.run(cmd, stderr=subprocess.PIPE, text=True)
    rms = []

    for line in p.stderr.splitlines():
        if "RMS_level" in line:
            try:
                val = float(line.split(":")[-1])
                rms.append(abs(val))
            except:
                pass

    arr = np.array(rms)
    return arr / arr.max() if arr.size and arr.max() > 0 else arr


# -------------------------------
# FAST MOTION ENERGY
# -------------------------------
def extract_motion_energy(
    video_path: str,
    samples: int,
    resize=(96, 54)
) -> np.ndarray:

    cap = cv2.VideoCapture(video_path)
    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    step = max(1, frames // samples)

    last = None
    motion = []

    for i in range(0, frames, step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ok, fr = cap.read()
        if not ok:
            break

        gy = cv2.cvtColor(cv2.resize(fr, resize), cv2.COLOR_BGR2GRAY)

        if last is not None:
            motion.append(np.mean(cv2.absdiff(gy, last)))

        last = gy

    cap.release()
    arr = np.array(motion)
    return arr / arr.max() if arr.size and arr.max() > 0 else arr


# -------------------------------
# ENERGY MAP BUILDER (PURE BRAIN)
# -------------------------------
def build_energy_curve(
    video_path: str,
    samples: int = 64,
    audio_weight: float = 0.55
) -> List[float]:

    ae = extract_audio_rms(video_path, samples)
    ve = extract_motion_energy(video_path, samples)

    L = min(len(ae), len(ve))
    if L == 0:
        return []

    energy = (ae[:L] * audio_weight) + (ve[:L] * (1 - audio_weight))
    energy = energy / energy.max() if energy.max() > 0 else energy

    return energy.tolist()
def build_zoom_filter(
    energy_curve,
    max_zoom=1.08
):
    if not energy_curve:
        return ""

    avg = sum(energy_curve) / len(energy_curve)
    z = min(max_zoom, 1.0 + avg * 0.08)

    return f"zoompan=z='{z}':d=1"
