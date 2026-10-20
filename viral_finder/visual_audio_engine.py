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
    # [PERF] Collect PCM chunks into a list, then stack once — avoids O(n²) concatenation
    raw_chunks = []
    read_size = 524288  # 512 KB per read — fewer syscalls on large audio files

    try:
        while True:
            chunk = p.stdout.read(read_size)
            if not chunk:
                break
            raw_chunks.append(np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0)

        p.wait(timeout=10)
    except Exception:
        try:
            p.kill()
        except Exception:
            pass
        return []

    if not raw_chunks:
        return []

    # Single stack — O(n) instead of O(n²)
    buf = np.concatenate(raw_chunks)
    frame_idx = 0
    pos = 0
    while pos + frame_length <= buf.size:
        frame = buf[pos:pos + frame_length]
        rms = float(np.sqrt(np.mean(frame * frame) + 1e-12))
        energies.append(rms)
        times.append(float(frame_idx * hop_length) / float(sr))
        frame_idx += 1
        pos += hop_length

    out = [{"time": t, "energy": e} for t, e in zip(times, energies)]
    dt = time.time() - t0
    print(f"[AUDIO] frames={len(out)} sr={sr} hop={hop_length} took={dt:.2f}s")
    return out

from concurrent.futures import ThreadPoolExecutor

# --- INTELLIGENCE UPGRADES ---
  # (1) Face Detection for Close-up Score (Migrated to external InsightFace)



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


def analyze_visual(
    video_path: str,
    max_seconds: float = None,
    target_samples: int = 50,
    down=(128, 72),
    skip=False
):
    """
    ULTRON V35 — SPARSE UNIFORM SAMPLING VISUAL ENGINE
    --------------------------------------------------
    - Samples target_samples uniformly across the entire video.
    - Extremely fast, uses downscaled grayscale frames.
    - Avoids scanning only the first 1.0 second of video.
    """
    if skip:
        return [{"time": 0.0, "motion": 0.5}]

    if not video_path or not os.path.exists(video_path):
        raise RuntimeError(f"[ANALYZE_VISUAL] Video file not ready or missing: {video_path}")

    import cv2
    import numpy as np

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"[ANALYZE_VISUAL] cv2.VideoCapture failed to open: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

    if total_frames <= 0:
        cap.release()
        raise RuntimeError(f"[ANALYZE_VISUAL] Video has invalid frame count ({total_frames}): {video_path}")

    # Determine frame step to sample target_samples across the entire video duration
    step = max(1, total_frames // target_samples)

    last = None
    results = []

    for idx in range(0, total_frames, step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        if not ok:
            break

        gray = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), down)

        if last is not None:
            # NumPy vector operation for absolute difference
            motion = float(np.mean(cv2.absdiff(gray, last)))
            ts = round(idx / fps, 2)
            results.append({"time": ts, "motion": motion})

        last = gray

    cap.release()

    if not results:
        raise RuntimeError(f"[ANALYZE_VISUAL] No valid frames extracted from {video_path}")

    return results
