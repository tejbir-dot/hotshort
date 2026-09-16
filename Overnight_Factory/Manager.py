import os
import sys
import shutil
import asyncio
from datetime import datetime
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────
FACTORY_DIR  = Path(__file__).parent.resolve()
PENDING_DIR  = FACTORY_DIR / "Pending_Videos"
UPLOADED_DIR = FACTORY_DIR / "Uploaded_Videos"
FAILED_DIR   = FACTORY_DIR / "Failed_Videos"
WAIT_TIME    = 5 * 60 * 60   # 5 hours between uploads (stealth mode)

# Make sure directories exist
for _d in (PENDING_DIR, UPLOADED_DIR, FAILED_DIR):
    _d.mkdir(exist_ok=True)

# ── Import the real YouTube uploader ─────────────────────────────────────────
sys.path.insert(0, str(FACTORY_DIR))
try:
    from youtube_uploader import upload_video as yt_upload
    YT_AVAILABLE = True
except ImportError:
    print("⚠️  youtube_uploader.py not found — YouTube uploads will be skipped.")
    YT_AVAILABLE = False

# ─────────────────────────────────────────────────────────────────────────────

async def factory_manager():
    print("👑 THE GHOST FACTORY: OVERLORD ENGINE STARTED...")
    print(f"   📁 Pending  : {PENDING_DIR}")
    print(f"   📁 Uploaded : {UPLOADED_DIR}")
    print(f"   📁 Failed   : {FAILED_DIR}\n")

    while True:
        ts = datetime.now().strftime('%H:%M:%S')
        print(f"[{ts}] 🔍 Checking Pending_Videos...")

        # Pick all .mp4 files, sorted by oldest first
        videos = sorted(PENDING_DIR.glob("*.mp4"), key=lambda p: p.stat().st_mtime)

        if videos:
            video_path   = videos[0]
            current_video = video_path.name

            # Caption file (same name, .txt)
            caption_path = video_path.with_suffix(".txt")
            title_hashtags = "Banger video! #shorts #viral"   # default fallback
            if caption_path.exists():
                title_hashtags = caption_path.read_text(encoding="utf-8").strip()

            print(f"\n🎬 Picked Up  : {current_video}")
            print(f"📝 Caption    : {title_hashtags[:80]}{'...' if len(title_hashtags)>80 else ''}")

            upload_ok = False

            # ── YouTube Upload ────────────────────────────────────────────────
            if YT_AVAILABLE:
                print("\n⚙️  Firing YouTube Bot...")
                try:
                    await asyncio.get_event_loop().run_in_executor(
                        None, yt_upload, str(video_path), title_hashtags
                    )
                    print("✅ YouTube Upload: SUCCESS")
                    upload_ok = True
                except Exception as e:
                    print(f"❌ YouTube Upload FAILED: {e}")
            else:
                print("⏭️  YouTube skipped (uploader not available)")
                upload_ok = True   # don't block pipeline if uploader missing

            # ── Move to correct archive folder ───────────────────────────────
            dest_dir = UPLOADED_DIR if upload_ok else FAILED_DIR
            dest_label = "✅ Archived" if upload_ok else "❌ Failed"

            shutil.move(str(video_path), str(dest_dir / current_video))
            if caption_path.exists():
                shutil.move(str(caption_path), str(dest_dir / caption_path.name))

            print(f"\n{dest_label} → {dest_dir.name}/{current_video}")

            if upload_ok:
                print(f"\n🕒 Going Stealth. Sleeping {WAIT_TIME//3600}h before next upload...")
                await asyncio.sleep(WAIT_TIME)
            else:
                print("⏳ Upload failed — retrying next clip in 5 minutes...")
                await asyncio.sleep(5 * 60)

        else:
            print("😴 No clips found. Checking again in 10 minutes...")
            await asyncio.sleep(10 * 60)


# ── Entry Point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    asyncio.run(factory_manager())