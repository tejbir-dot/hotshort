import os
import asyncio
from pathlib import Path

# Fix Windows unicode issues for terminal output
import sys
import io
if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass
    os.environ["PYTHONIOENCODING"] = "utf-8"

from youtube_uploader import upload_video
from whop_submitter import submit_to_whop
from Manager import parse_smart_captions

FACTORY_DIR = Path(__file__).parent.resolve()
PENDING_DIR = FACTORY_DIR / "Pending_Videos"

async def test_yt_only():
    print("\n🚀 Starting LIVE YouTube + Whop Test...")
    
    video_path = FACTORY_DIR / "Failed_Videos" / "clip_1_182_243.mp4"
    caption_path = FACTORY_DIR / "Failed_Videos" / "clip_1_182_243_caption.txt"
    current_clip = video_path.name

    if not video_path.exists():
        print(f"❌ Video not found at: {video_path}")
        return
    
    full_caption_text = "Crazy facts! 🤯 #shorts #viral"
    if caption_path.exists():
        full_caption_text = caption_path.read_text(encoding="utf-8").strip()

    smart_caps = parse_smart_captions(full_caption_text)
    yt_cap = smart_caps['youtube']

    print(f"\n🎬 Target Video: {current_clip}")
    print("▶️ Firing YouTube Engine (Live mode)...\n")

    # Run YouTube Upload (in thread to mimic Manager)
    try:
        yt_video_url = await asyncio.get_event_loop().run_in_executor(
            None, upload_video, str(video_path), yt_cap
        )
        print(f"\n✅ YouTube SUCCESS! URL: {yt_video_url}")
    except Exception as e:
        print(f"\n❌ YouTube FAILED: {e}")
        return

    # Whop Submit
    if yt_video_url:
        print(f"\n💰 Submitting YouTube URL to Whop TJR campaign: {yt_video_url} ...")
        try:
            whop_ok = await asyncio.get_event_loop().run_in_executor(
                None, submit_to_whop, yt_video_url, current_clip, "YouTube"
            )
            if whop_ok:
                print("✅ Whop: YouTube link SUBMITTED!")
            else:
                print("⚠️ Whop: Skipped or Failed")
        except Exception as e:
            print(f"❌ Whop Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_yt_only())
