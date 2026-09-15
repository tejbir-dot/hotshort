import cv2
import sys
import os
from time import perf_counter

path = sys.argv[1] if len(sys.argv) > 1 else ("scratch/test_vid.mp4" if os.path.exists("scratch/test_vid.mp4") else "test.mp4")
max_frames = int(sys.argv[2]) if len(sys.argv) > 2 else 3000

print(f"[EXPERIMENT] Testing pure cv2.VideoCapture.read() speed on: {path}", flush=True)
print(f"[EXPERIMENT] Max frames to test: {max_frames}", flush=True)

cap = cv2.VideoCapture(path)
if not cap.isOpened():
    print(f"Error: Could not open {path}", flush=True)
    sys.exit(1)

total_frames_reported = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
fps_reported = cap.get(cv2.CAP_PROP_FPS)
width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
print(f"Video Meta: {total_frames_reported} frames @ {fps_reported:.2f} FPS ({width}x{height})", flush=True)

frames = 0
t0 = perf_counter()

while frames < max_frames:
    ok, frame = cap.read()
    if not ok:
        break
    frames += 1
    if frames % 500 == 0:
        print(f"  ... read {frames} frames ({perf_counter() - t0:.2f}s, {frames / (perf_counter() - t0):.1f} FPS)", flush=True)

elapsed = perf_counter() - t0
cap.release()

print("\n" + "="*40, flush=True)
print("FINAL RESULTS (Pure cv2.VideoCapture.read()):", flush=True)
print(f"  Resolution        : {width}x{height}", flush=True)
print(f"  Total Frames Read : {frames}", flush=True)
print(f"  Total Time Elapsed: {elapsed:.2f} seconds", flush=True)
print(f"  Average FPS       : {frames / elapsed if elapsed > 0 else 0:.2f} FPS", flush=True)
print("="*40, flush=True)
