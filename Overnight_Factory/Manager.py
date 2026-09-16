import os
import sys
import shutil
import asyncio
import re
from datetime import datetime
from pathlib import Path

# ── ⚙️ MASTER CONFIGURATION ───────────────────────────────────────────────────
FACTORY_DIR  = Path(__file__).parent.resolve()
PENDING_DIR  = FACTORY_DIR / "Pending_Videos"
UPLOADED_DIR = FACTORY_DIR / "Uploaded_Videos"
FAILED_DIR   = FACTORY_DIR / "Failed_Videos"
WAIT_TIME    = 5 * 60 * 60   # 5 hours stealth sleep

for _d in (PENDING_DIR, UPLOADED_DIR, FAILED_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ── 🚀 ENGINE IGNITION (Dynamic Loaders) ──────────────────────────────────────
sys.path.insert(0, str(FACTORY_DIR))

def load_engine(module_name, func_name="upload_video"):
    try:
        mod = __import__(module_name)
        print(f"  🟢 {module_name.upper():<18} : ONLINE & ARMED")
        return getattr(mod, func_name)
    except ImportError:
        print(f"  🔴 {module_name.upper():<18} : OFFLINE (File not found)")
        return None

print("\n" + "="*50)
print(" 👑 THE GHOST FACTORY: OVERLORD v3.0 BOOTING...")
print("="*50)
yt_upload     = load_engine("youtube_uploader")
tiktok_upload = load_engine("tiktok_uploader")
ig_upload     = load_engine("insta_uploader")
print("="*50 + "\n")

# ── 🧠 SMART CAPTION PARSER ──────────────────────────────────────────────────
def parse_smart_captions(full_text):
    """Tere specific text format se har platform ka caption alag nikalta hai."""
    caps = {"youtube": full_text, "tiktok": full_text, "instagram": full_text} # Fallback
    try:
        # Regex jaadu: Header se leker dashes '----' tak ka text extract karta hai
        tt_match = re.search(r'TIKTOK CAPTION:(.*?)(?:-{10,}|$)', full_text, re.DOTALL)
        if tt_match: caps['tiktok'] = tt_match.group(1).strip()
        
        yt_match = re.search(r'YOUTUBE SHORTS CAPTION:(.*?)(?:-{10,}|$)', full_text, re.DOTALL)
        if yt_match: caps['youtube'] = yt_match.group(1).strip()
        
        ig_match = re.search(r'INSTAGRAM REELS CAPTION:(.*?)(?:-{10,}|$)', full_text, re.DOTALL)
        if ig_match: caps['instagram'] = ig_match.group(1).strip()
    except Exception as e:
        print(f"⚠️ Parser Warning: {e}")
    return caps

# ─────────────────────────────────────────────────────────────────────────────

async def factory_manager():
    print(f"👁️‍🗨️ RADAR ACTIVE ON: {PENDING_DIR.name}\n")

    while True:
        ts = datetime.now().strftime('%H:%M:%S')
        videos = sorted(PENDING_DIR.glob("*.mp4"), key=lambda p: p.stat().st_mtime)

        if not videos:
            print(f"[{ts}] 😴 No fresh ammo. Scanning again in 10 minutes...")
            await asyncio.sleep(10 * 60)
            continue

        video_path   = videos[0]
        current_clip = video_path.name
        caption_path = video_path.with_name(f"{video_path.stem}_caption.txt")
        
        full_caption_text = "Crazy facts! 🤯 #shorts #viral #mindset" # Backup
        if caption_path.exists():
            full_caption_text = caption_path.read_text(encoding="utf-8").strip()

        # 🔥 CTO MAGIC: Yahan tere captions alag-alag bat jayenge!
        smart_caps = parse_smart_captions(full_caption_text)

        print(f"\n[{ts}] 🎯 TARGET ACQUIRED: {current_clip}")
        print(f"  📝 Extracted YT Caption : {len(smart_caps['youtube'])} characters")
        print(f"  📝 Extracted TT Caption : {len(smart_caps['tiktok'])} characters")
        print(f"  📝 Extracted IG Caption : {len(smart_caps['instagram'])} characters\n")

        upload_success = True

        # ── 1. YOUTUBE STRIKE ──────────────────────────────────────────
        if yt_upload:
            print("  ▶️ [1/3] Firing YouTube Engine...")
            try:
                await asyncio.get_event_loop().run_in_executor(None, yt_upload, str(video_path), smart_caps['youtube'])
                print("    ✅ YouTube: SUCCESS\n")
            except Exception as e:
                print(f"    ❌ YouTube: FAILED ({e})\n")
                upload_success = False

        # ── 2. TIKTOK STRIKE ───────────────────────────────────────────
        if tiktok_upload:
            print("  ▶️ [2/3] Firing TikTok Engine...")
            try:
                await asyncio.get_event_loop().run_in_executor(None, tiktok_upload, str(video_path), smart_caps['tiktok'])
                print("    ✅ TikTok: SUCCESS\n")
            except Exception as e:
                print(f"    ❌ TikTok: FAILED ({e})\n")
                upload_success = False

        # ── 3. INSTAGRAM STRIKE ────────────────────────────────────────
        if ig_upload:
            print("  ▶️ [3/3] Firing Instagram Engine...")
            try:
                await asyncio.get_event_loop().run_in_executor(None, ig_upload, str(video_path), smart_caps['instagram'])
                print("    ✅ Instagram: SUCCESS\n")
            except Exception as e:
                print(f"    ❌ Instagram: FAILED ({e})\n")
                upload_success = False

        # ── ARCHIVE & SLEEP ────────────────────────────────────────────
        dest_dir   = UPLOADED_DIR if upload_success else FAILED_DIR
        dest_label = "📦 ARCHIVED (Success)" if upload_success else "⚠️ MOVED TO FAILED"

        shutil.move(str(video_path), str(dest_dir / current_clip))
        if caption_path.exists():
            shutil.move(str(caption_path), str(dest_dir / caption_path.name))

        print(f"{dest_label} -> {dest_dir.name}/{current_clip}")

        if upload_success:
            print(f"\n🛡️ GHOST MODE ACTIVATED. Radar off for {WAIT_TIME//3600} hours to avoid detection...\n")
            await asyncio.sleep(WAIT_TIME)
        else:
            print("\n⚠️ System encountered errors. Retrying next file in 5 minutes...\n")
            await asyncio.sleep(5 * 60)

if __name__ == "__main__":
    asyncio.run(factory_manager())