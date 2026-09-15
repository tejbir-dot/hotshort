import bolt
from video_context import VideoContext
import os

path = "scratch/dummy.mp4" if os.path.exists("scratch/dummy.mp4") else "test.mp4"

print(f"[TEST] Simulating duplicate opens without vs with VideoContext on {path}...", flush=True)

# 1. Without VideoContext (Legacy behavior: 2 open calls)
bolt.reset()
with bolt.stage("Legacy (2x Open)"):
    # First module (e.g. format analyzer)
    bolt.emit("video_open")
    # Second module (e.g. crop expression)
    bolt.emit("video_open")

print("\n--- Legacy BOLT Report ---", flush=True)
bolt.save_report("scratch/report_legacy_open.json")

# 2. With VideoContext (New behavior: single cached handle)
bolt.reset()
with bolt.stage("VideoContext (Cached Open)"):
    # First module calls VideoContext.get() -> opens video once
    vc1 = VideoContext.get(path)
    # Reads 5 frames
    for _ in range(5):
        vc1.read()
    
    # Second module calls VideoContext.get() -> gets cached handle, ZERO new opens!
    vc2 = VideoContext.get(path)
    vc2.seek(0)
    for _ in range(5):
        vc2.read()

    VideoContext.close_all()

print("\n--- VideoContext BOLT Report ---", flush=True)
bolt.save_report("scratch/report_videocontext.json")
