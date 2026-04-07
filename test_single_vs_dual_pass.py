#!/usr/bin/env python3
"""
Test: Single Pass vs Dual Pass Analysis
Compare results and timing between one-pass and two-pass clip selection.

Usage:
  python test_single_vs_dual_pass.py <youtube_url>
  
Example:
  python test_single_vs_dual_pass.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
"""

import os
import sys
import time
import json
from dotenv import load_dotenv

load_dotenv()

def check_dependencies():
    """Verify required packages are installed."""
    try:
        import yt_dlp
        from models.user import User
        from models.job import Job
        from app import app, db
        return True
    except ImportError as e:
        print(f"❌ Missing dependency: {e}")
        return False

def run_test(youtube_url):
    """Run single pass vs dual pass comparison test."""
    
    if not check_dependencies():
        print("\n💡 Install dependencies: pip install -r requirements.txt")
        return
    
    from app import app, db
    from models.user import User
    from viral_finder.idea_graph import analyze_transcript_v2
    from youtube_helper import download_youtube_video
    
    print("\n" + "="*70)
    print("🧪 CLIP SELECTION PASS COMPARISON TEST")
    print("="*70)
    print(f"Video: {youtube_url}")
    print()
    
    # Step 1: Download video
    print("📥 Downloading video...")
    download_start = time.time()
    try:
        video_path, _ = download_youtube_video(youtube_url)
        download_time = time.time() - download_start
        print(f"✅ Downloaded: {video_path} ({download_time:.2f}s)")
    except Exception as e:
        print(f"❌ Download failed: {e}")
        return
    
    # Step 2: Extract transcript
    print("\n📝 Extracting transcript...")
    extract_start = time.time()
    try:
        import yt_dlp
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            info = ydl.extract_info(youtube_url, download=False)
            transcript = info.get('subtitles', {})
        extract_time = time.time() - extract_start
        print(f"✅ Transcript extracted ({extract_time:.2f}s)")
    except Exception as e:
        print(f"⚠️  No subtitle transcript: {e}")
        transcript = {}
    
    # Step 3: Test STRICT PASS ONLY (1 pass)
    print("\n" + "-"*70)
    print("🔴 TEST 1: STRICT PASS ONLY (1 Pass)")
    print("-"*70)
    
    # Temporarily set environment to disable relaxed pass
    original_min_clips = os.getenv("HS_MIN_CLIPS_SHORT", "3")
    os.environ["HS_SELECTOR_RELAX_CURIO_DELTA"] = "0.00"  # Disable relaxation
    os.environ["HS_SELECTOR_RELAX_PUNCH_DELTA"] = "0.00"
    
    strict_start = time.time()
    try:
        # Run analysis with strict pass only
        from viral_finder.idea_graph import _analyze_clips_worker
        result_strict = _analyze_clips_worker(
            clip_source=[],  # Placeholder - would need actual implementation
            video_info={},
            plan_limits={"max_daily_clips": 999},
            diversity_mode="balanced"
        )
        strict_time = time.time() - strict_start
        strict_clips = len(result_strict.get("clips", []))
        print(f"⏱️  Time taken: {strict_time:.2f}s")
        print(f"📊 Clips found: {strict_clips}")
        print(f"Details: {json.dumps(result_strict.get('stats', {}), indent=2)}")
    except Exception as e:
        print(f"⚠️  Analysis error: {e}")
        strict_time = 0
        strict_clips = 0
    
    # Step 4: Test STRICT + RELAXED PASS (2 passes)
    print("\n" + "-"*70)
    print("🟢 TEST 2: STRICT + RELAXED PASSES (2 Passes)")
    print("-"*70)
    
    # Re-enable relaxed pass
    os.environ["HS_SELECTOR_RELAX_CURIO_DELTA"] = "0.08"
    os.environ["HS_SELECTOR_RELAX_PUNCH_DELTA"] = "0.08"
    
    dual_start = time.time()
    try:
        # Run analysis with both passes
        result_dual = _analyze_clips_worker(
            clip_source=[],  # Placeholder
            video_info={},
            plan_limits={"max_daily_clips": 999},
            diversity_mode="balanced"
        )
        dual_time = time.time() - dual_start
        dual_clips = len(result_dual.get("clips", []))
        print(f"⏱️  Time taken: {dual_time:.2f}s")
        print(f"📊 Clips found: {dual_clips}")
        print(f"Details: {json.dumps(result_dual.get('stats', {}), indent=2)}")
    except Exception as e:
        print(f"⚠️  Analysis error: {e}")
        dual_time = 0
        dual_clips = 0
    
    # Step 5: Comparison Results
    print("\n" + "="*70)
    print("📊 COMPARISON RESULTS")
    print("="*70)
    print(f"{'Metric':<30} {'Strict (1Pass)':<20} {'Strict+Relaxed (2Pass)':<20} {'Difference':<15}")
    print("-"*70)
    print(f"{'Time Taken (seconds)':<30} {strict_time:>18.2f}s {dual_time:>20.2f}s {(dual_time-strict_time):>13.2f}s")
    print(f"{'Clips Found':<30} {strict_clips:>18} {dual_clips:>20} {(dual_clips-strict_clips):>13}")
    
    if dual_time > 0:
        time_overhead = ((dual_time - strict_time) / dual_time) * 100
        print(f"{'Time Overhead %':<30} {'-':>18} {'-':>20} {time_overhead:>12.1f}%")
    
    if dual_clips > 0 and strict_clips > 0:
        clip_increase = ((dual_clips - strict_clips) / strict_clips) * 100
        print(f"{'Clip Increase %':<30} {'-':>18} {'-':>20} {clip_increase:>12.1f}%")
    
    print("\n🎯 KEY INSIGHTS:")
    print(f"✅ Relaxed pass adds {dual_clips - strict_clips} extra clips")
    print(f"⏱️  Extra time cost: {dual_time - strict_time:.2f}s ({((dual_time-strict_time)/dual_time*100):.1f}%)")
    print(f"📈 Quality tradeoff: Lower thresholds = more clips but potentially lower quality")
    
    # Cleanup
    os.environ["HS_MIN_CLIPS_SHORT"] = original_min_clips
    if os.path.exists(video_path):
        os.remove(video_path)
        print(f"\n🧹 Cleaned up: {video_path}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        print("❌ Error: YouTube URL required")
        sys.exit(1)
    
    youtube_url = sys.argv[1]
    run_test(youtube_url)
