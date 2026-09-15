import bolt
import cv2
import av
import sys
import os

path = sys.argv[1] if len(sys.argv) > 1 else ("scratch/dummy.mp4" if os.path.exists("scratch/dummy.mp4") else "test.mp4")
max_frames = int(sys.argv[2]) if len(sys.argv) > 2 else 500

print(f"[EXPERIMENT] Running OpenCV vs PyAV switch on {path} (max {max_frames} frames)...", flush=True)

# 1. OpenCV Read
bolt.reset()
with bolt.stage("OpenCV Read"):
    bolt.emit("video_open")
    cap = cv2.VideoCapture(path)
    count_cv = 0
    while count_cv < max_frames:
        ok, frame = cap.read()
        if not ok: break
        bolt.emit("frame_decode")
        count_cv += 1
    cap.release()

print("\n--- OpenCV Report ---", flush=True)
bolt.save_report("scratch/report_opencv.json")

# 2. PyAV Read
bolt.reset()
with bolt.stage("PyAV Read"):
    bolt.emit("video_open")
    container = av.open(path)
    stream = container.streams.video[0]
    stream.thread_type = "AUTO"
    count_av = 0
    for frame in container.decode(stream):
        img = frame.to_ndarray(format="bgr24")
        bolt.emit("frame_decode")
        count_av += 1
        if count_av >= max_frames: break
    container.close()

print("\n--- PyAV Report ---", flush=True)
bolt.save_report("scratch/report_pyav.json")
