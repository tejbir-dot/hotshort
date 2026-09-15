import cv2
import av
import subprocess
import numpy as np
import sys
import os
from time import perf_counter

path = sys.argv[1] if len(sys.argv) > 1 else r"downloads\https___youtu_be_jMhhaAQK1NQ_si_bOl_mcppIsV47iEt.mp4"
max_frames = int(sys.argv[2]) if len(sys.argv) > 2 else 10000

print(f"[BENCHMARK] 3-Way Media Backend Isolation Test on: {path}", flush=True)
print(f"[BENCHMARK] Max consecutive frames to test: {max_frames}", flush=True)

cap = cv2.VideoCapture(path)
if not cap.isOpened():
    print(f"Error: Could not open {path}", flush=True)
    sys.exit(1)

w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
fps = cap.get(cv2.CAP_PROP_FPS)
total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
cap.release()

print(f"Video Meta: {total_frames} frames @ {fps:.2f} FPS ({w}x{h})\n", flush=True)
frame_size = w * h * 3

# ==========================================
# 1. OpenCV VideoCapture
# ==========================================
print("--- 1. Testing OpenCV VideoCapture ---", flush=True)
cap = cv2.VideoCapture(path)
count_cv = 0
t0 = perf_counter()
while count_cv < max_frames:
    ok, frame = cap.read()
    if not ok:
        break
    count_cv += 1
    if count_cv % 2000 == 0:
        print(f"  [OpenCV] read {count_cv} frames ({perf_counter() - t0:.2f}s, {count_cv / (perf_counter() - t0):.1f} FPS)", flush=True)
t_cv = perf_counter() - t0
cap.release()
fps_cv = count_cv / t_cv if t_cv > 0 else 0
print(f"  -> OpenCV Final: {count_cv} frames in {t_cv:.2f}s = {fps_cv:.2f} FPS\n", flush=True)

# ==========================================
# 2. PyAV
# ==========================================
print("--- 2. Testing PyAV (AUTO threads) ---", flush=True)
container = av.open(path)
stream = container.streams.video[0]
stream.thread_type = "AUTO"
count_av = 0
t0 = perf_counter()
for frame in container.decode(stream):
    img = frame.to_ndarray(format="bgr24")
    count_av += 1
    if count_av % 2000 == 0:
        print(f"  [PyAV] read {count_av} frames ({perf_counter() - t0:.2f}s, {count_av / (perf_counter() - t0):.1f} FPS)", flush=True)
    if count_av >= max_frames:
        break
t_av = perf_counter() - t0
container.close()
fps_av = count_av / t_av if t_av > 0 else 0
print(f"  -> PyAV Final: {count_av} frames in {t_av:.2f}s = {fps_av:.2f} FPS\n", flush=True)

# ==========================================
# 3. FFmpeg image2pipe (CPU software decode)
# ==========================================
print("--- 3. Testing FFmpeg image2pipe (CPU) ---", flush=True)
cmd_ff = [
    "ffmpeg", "-hide_banner", "-loglevel", "error",
    "-i", path,
    "-f", "image2pipe",
    "-pix_fmt", "bgr24",
    "-vcodec", "rawvideo",
    "-"
]
proc = subprocess.Popen(cmd_ff, stdout=subprocess.PIPE, bufsize=10**8)
count_ff = 0
t0 = perf_counter()
while count_ff < max_frames:
    raw_bytes = proc.stdout.read(frame_size)
    if len(raw_bytes) < frame_size:
        break
    img = np.frombuffer(raw_bytes, dtype=np.uint8).reshape((h, w, 3))
    count_ff += 1
    if count_ff % 2000 == 0:
        print(f"  [FFmpeg-CPU] read {count_ff} frames ({perf_counter() - t0:.2f}s, {count_ff / (perf_counter() - t0):.1f} FPS)", flush=True)
t_ff = perf_counter() - t0
proc.terminate()
proc.wait()
fps_ff = count_ff / t_ff if t_ff > 0 else 0
print(f"  -> FFmpeg-CPU Final: {count_ff} frames in {t_ff:.2f}s = {fps_ff:.2f} FPS\n", flush=True)

# ==========================================
# 4. FFmpeg image2pipe (-hwaccel auto)
# ==========================================
print("--- 4. Testing FFmpeg image2pipe (-hwaccel auto) ---", flush=True)
cmd_hw = [
    "ffmpeg", "-hide_banner", "-loglevel", "error",
    "-hwaccel", "auto",
    "-i", path,
    "-f", "image2pipe",
    "-pix_fmt", "bgr24",
    "-vcodec", "rawvideo",
    "-"
]
proc_hw = subprocess.Popen(cmd_hw, stdout=subprocess.PIPE, bufsize=10**8)
count_hw = 0
t0 = perf_counter()
while count_hw < max_frames:
    raw_bytes = proc_hw.stdout.read(frame_size)
    if len(raw_bytes) < frame_size:
        break
    img = np.frombuffer(raw_bytes, dtype=np.uint8).reshape((h, w, 3))
    count_hw += 1
    if count_hw % 2000 == 0:
        print(f"  [FFmpeg-HW] read {count_hw} frames ({perf_counter() - t0:.2f}s, {count_hw / (perf_counter() - t0):.1f} FPS)", flush=True)
t_hw = perf_counter() - t0
proc_hw.terminate()
proc_hw.wait()
fps_hw = count_hw / t_hw if t_hw > 0 else 0
print(f"  -> FFmpeg-HW Final: {count_hw} frames in {t_hw:.2f}s = {fps_hw:.2f} FPS\n", flush=True)

print("="*60, flush=True)
print("FINAL BACKEND COMPARISON (1080p Production Scale - 10,000 frames):", flush=True)
print(f"  1. OpenCV VideoCapture : {fps_cv:.2f} FPS ({t_cv:.2f}s)", flush=True)
print(f"  2. PyAV (AUTO threads) : {fps_av:.2f} FPS ({t_av:.2f}s)", flush=True)
print(f"  3. FFmpeg image2pipe   : {fps_ff:.2f} FPS ({t_ff:.2f}s)", flush=True)
print(f"  4. FFmpeg (-hwaccel)   : {fps_hw:.2f} FPS ({t_hw:.2f}s)", flush=True)
print("="*60, flush=True)
