"""
prepare_cards.py - Systematic Card Asset Pipeline for Remotion Engine
Extracts 2-second high-energy moments from branded clips, loops them into 4.0s replays,
and places them systematically into remotion_engine/public/cards/.
"""

import os
import subprocess
import sys

def process_card_clip(input_path: str, output_path: str, start_sec: float = 0.5, duration: float = 2.0):
    """
    Trims a clip, loops it twice (replay effect), scales to 540x960 30fps, and strips audio.
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{start_sec:.3f}",
        "-t", f"{duration:.3f}",
        "-i", input_path,
        "-filter_complex", "[0:v]scale=540:960,fps=30,split=2[v1][v2];[v1][v2]concat=n=2:v=1[v]",
        "-map", "[v]",
        "-c:v", "libx264",
        "-crf", "16",
        "-preset", "fast",
        "-pix_fmt", "yuv420p",
        "-an",
        output_path
    ]
    print(f"Processing: {os.path.basename(input_path)} -> {output_path}")
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"  ✓ Created {os.path.basename(output_path)}")

def prepare_all_cards(
    clip_left: str = "marketing_factory/output/b1d60a78_branded_0_50_118.mp4",
    clip_center: str = "marketing_factory/output/a3f63caa_branded_1_388_467.mp4",
    clip_right: str = "marketing_factory/output/b1d60a78_branded_1_1_68.mp4",
    cards_dir: str = "marketing_factory/remotion_engine/public/cards"
):
    print("=" * 60)
    print("HOTSHORT MARKETING FACTORY: SYSTEMATIC CARD ASSET PIPELINE")
    print("=" * 60)
    
    process_card_clip(clip_left, os.path.join(cards_dir, "card_left.mp4"), start_sec=0.5, duration=2.0)
    process_card_clip(clip_center, os.path.join(cards_dir, "card_center.mp4"), start_sec=1.0, duration=2.0)
    process_card_clip(clip_right, os.path.join(cards_dir, "card_right.mp4"), start_sec=0.5, duration=2.0)
    
    print("\n✓ All 3 cards ready for Remotion automation!")

if __name__ == "__main__":
    prepare_all_cards()
