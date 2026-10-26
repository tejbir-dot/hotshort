#!/usr/bin/env python3
"""
compare.py - Reference Master Phase 4 Side-by-Side Visual Comparator
Extracts frames at given timestamps from reference and rendered videos,
stitches them side-by-side (Reference LEFT, Render RIGHT with timestamp stamp),
and creates an overview comparison contact sheet.
"""

import os
import sys
import argparse
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

def extract_frame(video_path: str, timestamp: float, out_path: str):
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(timestamp),
        "-i", video_path,
        "-frames:v", "1",
        "-q:v", "2",
        out_path
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

def stitch_comparison(ref_frame_path: str, render_frame_path: str, t: float, out_path: str, target_height: int = 1080):
    ref_img = Image.open(ref_frame_path).convert("RGB")
    ren_img = Image.open(render_frame_path).convert("RGB")
    
    # Scale both to target_height preserving aspect ratio
    ref_aspect = ref_img.width / ref_img.height
    ren_aspect = ren_img.width / ren_img.height
    
    ref_w = int(target_height * ref_aspect)
    ren_w = int(target_height * ren_aspect)
    
    ref_resized = ref_img.resize((ref_w, target_height), Image.Resampling.LANCZOS)
    ren_resized = ren_img.resize((ren_w, target_height), Image.Resampling.LANCZOS)
    
    # Stitch side by side with a divider line
    divider_w = 8
    total_w = ref_w + ren_w + divider_w
    combined = Image.new("RGB", (total_w, target_height), (20, 20, 25))
    
    combined.paste(ref_resized, (0, 0))
    # Divider bar
    divider = Image.new("RGB", (divider_w, target_height), (255, 215, 0)) # Gold line
    combined.paste(divider, (ref_w, 0))
    combined.paste(ren_resized, (ref_w + divider_w, 0))
    
    draw = ImageDraw.Draw(combined)
    
    # Add label banners
    # Try default font or load simple truetype
    try:
        font_large = ImageFont.truetype("arial.ttf", 36)
        font_small = ImageFont.truetype("arial.ttf", 28)
    except:
        font_large = font_small = ImageFont.load_default()
        
    # Badge: REFERENCE (LEFT)
    draw.rectangle([(20, 20), (280, 75)], fill=(0, 0, 0, 200), outline=(255, 255, 255))
    draw.text((30, 28), "REFERENCE", fill=(255, 255, 255), font=font_large)
    
    # Badge: OUR RENDER (RIGHT)
    draw.rectangle([(ref_w + divider_w + 20, 20), (ref_w + divider_w + 280, 75)], fill=(0, 0, 0, 200), outline=(74, 222, 128))
    draw.text((ref_w + divider_w + 30, 28), "HOTSHORT", fill=(74, 222, 128), font=font_large)
    
    # Timestamp stamp bottom center
    t_str = f"t = {t:0.2f}s"
    t_w = 200
    cx = total_w // 2
    draw.rectangle([(cx - 100, target_height - 65), (cx + 100, target_height - 15)], fill=(15, 15, 20), outline=(255, 215, 100))
    draw.text((cx - 70, target_height - 58), t_str, fill=(255, 215, 100), font=font_small)
    
    combined.save(out_path, quality=95)

def create_tiled_sheet(compare_images: list, out_sheet_path: str):
    if not compare_images:
        return
    imgs = [Image.open(p) for p in compare_images]
    n = len(imgs)
    
    # Max 2 columns
    cols = min(2, n)
    rows = (n + cols - 1) // cols
    
    thumb_h = 540
    thumb_w = int(imgs[0].width * (thumb_h / imgs[0].height))
    
    sheet = Image.new("RGB", (cols * thumb_w, rows * thumb_h), (10, 10, 12))
    
    for idx, img in enumerate(imgs):
        r = idx // cols
        c = idx % cols
        t_img = img.resize((thumb_w, thumb_h), Image.Resampling.LANCZOS)
        sheet.paste(t_img, (c * thumb_w, r * thumb_h))
        
    sheet.save(out_sheet_path, quality=90)
    print(f"Generated comparison sheet: {out_sheet_path}", flush=True)

def run_comparison(ref_path: str, render_path: str, timestamps: list, out_dir: str = "compare_out"):
    os.makedirs(out_dir, exist_ok=True)
    temp_dir = os.path.join(out_dir, "temp_stills")
    os.makedirs(temp_dir, exist_ok=True)
    
    compare_paths = []
    
    print(f"Comparing Reference vs Render across {len(timestamps)} timestamps: {timestamps}", flush=True)
    for t in timestamps:
        ref_still = os.path.join(temp_dir, f"ref_{t:0.2f}.jpg")
        ren_still = os.path.join(temp_dir, f"ren_{t:0.2f}.jpg")
        comp_out = os.path.join(out_dir, f"compare_{t:0.2f}s.jpg")
        
        extract_frame(ref_path, t, ref_still)
        extract_frame(render_path, t, ren_still)
        
        stitch_comparison(ref_still, ren_still, t, comp_out)
        compare_paths.append(comp_out)
        print(f"Stitched: {comp_out}", flush=True)
        
    sheet_path = os.path.join(out_dir, "sheet.jpg")
    create_tiled_sheet(compare_paths, sheet_path)
    print("\nComparison Complete! Evidence saved in:", out_dir)

def main():
    parser = argparse.ArgumentParser(description="Reference Master Visual Comparator")
    parser.add_argument("--ref", required=True, help="Path to reference video (ref.mp4)")
    parser.add_argument("--render", required=True, help="Path to rendered video (out_vN.mp4)")
    parser.add_argument("--times", default="0.5,1.2,2.5,4.0,7.5,12.0", help="Comma-separated timestamps in seconds")
    parser.add_argument("--out_dir", default="compare_out", help="Output directory")
    args = parser.parse_args()
    
    ts = [float(x.strip()) for x in args.times.split(",") if x.strip()]
    run_comparison(args.ref, args.render, ts, args.out_dir)

if __name__ == "__main__":
    main()
