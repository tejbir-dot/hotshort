import bolt
import time

with bolt.stage("Decode"):
    time.sleep(0.123)
    bolt.counter("video_open", 4)

with bolt.stage("Face Tracking"):
    time.sleep(0.045)
    bolt.counter("ffmpeg_encode", 2)

with bolt.stage("Encoding"):
    time.sleep(0.067)

bolt.save_report("scratch/bolt_report.json")
