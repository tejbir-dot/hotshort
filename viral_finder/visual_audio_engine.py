import os
import shutil
import subprocess
import time

import cv2
import numpy as np

def analyze_audio(path: str, sr: int = 16000, frame_length: int = 2048, hop_length: int = 512):
    """
    Fast audio energy extractor (RMS).

    - Avoids `librosa.load()` (slow + loads entire file into RAM)
    - Streams PCM via FFmpeg and computes RMS per hop (similar to librosa.feature.rms defaults)

    Returns: [{"time": seconds, "energy": rms}, ...]
    """
    t0 = time.time()
    if not path or not os.path.exists(path):
        return []

    if shutil.which("ffmpeg") is None:
        # Fallback (keeps behavior if FFmpeg missing)
        try:
            import librosa  # type: ignore

            y, _sr = librosa.load(path, sr=sr)
            rms = librosa.feature.rms(y=y, frame_length=frame_length, hop_length=hop_length)[0]
            times = librosa.frames_to_time(range(len(rms)), sr=sr, hop_length=hop_length)
            return [{"time": float(t), "energy": float(r)} for t, r in zip(times, rms)]
        except Exception:
            return []

    cmd = [
        "ffmpeg",
        "-nostdin",
        "-v",
        "error",
        "-i",
        path,
        "-f",
        "s16le",
        "-ac",
        "1",
        "-ar",
        str(sr),
        "-",
    ]

    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except Exception:
        return []

    assert p.stdout is not None

    energies = []
    times = []
    buf = np.zeros((0,), dtype=np.float32)
    frame_idx = 0

    read_size = 65536  # bytes
    try:
        while True:
            chunk = p.stdout.read(read_size)
            if not chunk:
                break
            x = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
            if x.size == 0:
                continue
            buf = np.concatenate([buf, x])

            while buf.size >= frame_length:
                frame = buf[:frame_length]
                rms = float(np.sqrt(np.mean(frame * frame) + 1e-12))
                energies.append(rms)
                times.append(float(frame_idx * hop_length) / float(sr))
                frame_idx += 1
                buf = buf[hop_length:]

        p.wait(timeout=10)
    except Exception:
        try:
            p.kill()
        except Exception:
            pass
        return []

    out = [{"time": t, "energy": e} for t, e in zip(times, energies)]
    dt = time.time() - t0
    print(f"[AUDIO] frames={len(out)} sr={sr} hop={hop_length} took={dt:.2f}s")
    return out

from concurrent.futures import ThreadPoolExecutor

# --- INTELLIGENCE UPGRADES ---
# (1) Face Detection for Close-up Score
face_cascade = cv2.CascadeClassifier(
    cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
)


class AsyncVideoReader:
    """Asynchronous video reader for faster frame processing."""
    def __init__(self, video_path):
        self.stream = cv2.VideoCapture(video_path)
        self.stopped = False
        self.frame = None
    
    def start(self):
        """Start the reader."""
        return self
    
    def read(self):
        """Read the next frame."""
        ret, frame = self.stream.read()
        self.frame = frame if ret else None
        if not ret:
            self.stopped = True
        return self.frame
    
    def stop(self):
        """Stop the reader."""
        self.stopped = True


# def analyze_visual(
#     video_path: str,
#     max_samples: int = 60,
#     resize=(160, 90),
#     skip_visual=False
# ):
#     """
#     ULTRON Ultra-Fast Visual Heuristic
#     ---------------------------------
#     - Hard capped samples
#     - Early exit
#     - Safe fallback
#     - O(1) runtime feel
#     """

#     # 🔥 MASTER SWITCH
#     if skip_visual:
#         return [{"time": 0.0, "motion": 0.5}]

#     import cv2
#     import numpy as np

#     cap = cv2.VideoCapture(video_path)
#     if not cap.isOpened():
#         return [{"time": 0.0, "motion": 0.5}]

#     fps = cap.get(cv2.CAP_PROP_FPS) or 25
#     total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

#     if total == 0:
#         cap.release()
#         return [{"time": 0.0, "motion": 0.5}]

#     # sample evenly across timeline
#     step = max(1, total // max_samples)

#     last = None
#     out = []
#     collected = 0

#     for i in range(0, total, step):
#         cap.set(cv2.CAP_PROP_POS_FRAMES, i)
#         ok, frame = cap.read()
#         if not ok:
#             break

#         small = cv2.resize(frame, resize)
#         gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

#         if last is not None:
#             diff = cv2.absdiff(gray, last)
#             motion = float(diff.mean())
#             out.append({
#                 "time": round(i / fps, 2),
#                 "motion": motion
#             })
#             collected += 1

#         last = gray

#         # 🚀 HARD STOP
#         if collected >= max_samples:
#             break

#     cap.release()

#     # fallback safety
#     if not out:
#         return [{"time": 0.0, "motion": 0.5}]

#     return out
def analyze_visual(
    video_path: str,
    max_seconds: float = 1.0,
    target_samples: int = 50,
    down=(128, 72),
    skip=False
):
    """
    ULTRON V34 — LIGHTNING VISUAL ENGINE
    ------------------------------------
    - Scans only the first N seconds (default 1 sec)
    - ~50 samples max
    - Sequential read (FAST)
    - Downscaled grayscale
    - Motion = frame delta mean
    """

    if skip:
        return [{"time": 0.0, "motion": 0.5}]

    import cv2
    import time
    import numpy as np

    t0 = time.time()
    cap = cv2.VideoCapture(video_path)

    if not cap.isOpened():
        return [{"time": 0.0, "motion": 0.5}]

    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0

    # process only first N seconds
    max_frames = min(total_frames, int(fps * max_seconds))

    step = max(1, max_frames // target_samples)

    last = None
    results = []
    count = 0

    for idx in range(0, max_frames, step):

        # break hard by time
        if (time.time() - t0) > max_seconds:
            break

        ok, frame = cap.read()
        if not ok:
            break

        gray = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), down)

        if last is not None:
            # NumPy vector op
            motion = float(np.mean(cv2.absdiff(gray, last)))
            ts = round(idx / fps, 2)
            results.append({"time": ts, "motion": motion})
            count += 1

        last = gray
        if count >= target_samples:
            break

    cap.release()

    if not results:
        return [{"time": 0.0, "motion": 0.5}]

    return results
