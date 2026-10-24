"""
clean_clips.py
Removes the duplicate top yellow caption from the 7 user clips,
retains only the stylish word-by-word subtitle baked into the clip,
and generates clean high-res poster frames for zero-delay preloading.
"""

import os
import subprocess

CLIPS = [
    'b1d60a78_branded_0_50_118.mp4',
    'a3f63caa_branded_1_388_467.mp4',
    'b1d60a78_branded_1_1_68.mp4',
    '99cdb3e7_branded_3_102_189.mp4',
    'b1d60a78_branded_2_32_99.mp4',
    '99cdb3e7_edited_2_246_328.mp4',
    '99cdb3e7_branded_0_246_328.mp4'
]

INPUT_DIR = 'marketing_factory/output'
OUTPUT_DIR = 'static/clean_clips'
os.makedirs(OUTPUT_DIR, exist_ok=True)

print("=" * 60)
print("CLEANING 7 USER CLIPS: REMOVING TOP DUPLICATE CAPTION")
print("=" * 60)

for i, filename in enumerate(CLIPS):
    in_path = os.path.join(INPUT_DIR, filename)
    out_path = os.path.join(OUTPUT_DIR, filename)
    poster_path = os.path.join(OUTPUT_DIR, f'poster_{i}.jpg')
    
    print(f"[{i+1}/{len(CLIPS)}] Processing {filename}...")
    
    # 1. Strip top duplicate yellow caption seamlessly using background blur (NO black band)
    cmd = [
        "ffmpeg", "-y",
        "-i", in_path,
        "-vf", "split[main][blur];[blur]crop=iw:320:0:0,boxblur=28:5[blurred];[main][blurred]overlay=0:0",
        "-c:v", "libx264",
        "-crf", "16",
        "-preset", "fast",
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        out_path
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"  [OK] Cleaned video (no black band) saved to {out_path}")
    
    # 2. Extract crystal-clear poster at t=1.0s (or 1.5s) for instant preloading
    cmd_poster = [
        "ffmpeg", "-y",
        "-ss", "1.0",
        "-i", out_path,
        "-vframes", "1",
        "-q:v", "2",
        poster_path
    ]
    subprocess.run(cmd_poster, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"  [OK] Poster saved to {poster_path}")

print("\nAll 7 clips cleaned and prepped with zero duplicate captions!")
