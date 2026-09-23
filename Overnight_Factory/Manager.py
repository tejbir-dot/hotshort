import os
import sys
import json
import shutil
import random
import asyncio
import re
from datetime import datetime
from pathlib import Path

# ── ⚙️ MASTER CONFIGURATION ───────────────────────────────────────────────────
FACTORY_DIR  = Path(__file__).parent.resolve()
PENDING_DIR  = FACTORY_DIR / "Pending_Videos"
UPLOADED_DIR = FACTORY_DIR / "Uploaded_Videos"
FAILED_DIR   = FACTORY_DIR / "Failed_Videos"
COOKIES_VAULT = FACTORY_DIR / "Cookies_Vault"  # 🔐 Multi-campaign cookie vault
WAIT_TIME_MIN = 6 * 60 * 60   # 6 hours minimum stealth sleep
WAIT_TIME_MAX = 6 * 60 * 60 + 30 * 60  # 6.5 hours maximum (random gap — bot-detection avoid)

# ── 📁 CAMPAIGN → COOKIE FOLDER MAPPING ─────────────────────────────────────
# Pending subfolder name → Cookies_Vault subfolder name
# Add new campaigns here when you create new Pending_Videos subfolders!
COOKIE_CAMPAIGN_MAP = {
    # Pending subfolder names (PRIMARY — folder name is source of truth)
    "TJR_pending":               "TJR_campaign",
    "Double_Coverage_pending":   "Double_Coverage",
    # Legacy campaign name keys (fallback for caption scanning)
    "TJR_trader":                "TJR_campaign",
    "TJR_trader_new":            "TJR_campaign",
    "Double_Coverage_Podcast":   "Double_Coverage",
    "Double_Coverage_podcast":   "Double_Coverage",
}
DEFAULT_COOKIE_FOLDER = "TJR_campaign"  # fallback agar campaign map mein nahi mila

for _d in (PENDING_DIR, UPLOADED_DIR, FAILED_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ── 🚀 ENGINE IGNITION (Dynamic Loaders) ──────────────────────────────────────
sys.path.insert(0, str(FACTORY_DIR))

def load_engine(module_name, func_name="upload_video"):
    try:
        mod = __import__(module_name)
        fn = getattr(mod, func_name)
        print(f"  🟢 {module_name.upper():<18} : ONLINE & ARMED")
        return fn
    except ImportError as e:
        print(f"  🔴 {module_name.upper():<18} : OFFLINE — ImportError: {e}")
        return None
    except Exception as e:
        print(f"  🔴 {module_name.upper():<18} : OFFLINE — Error: {e}")
        return None

def resolve_cookie_dir(campaign_name: str) -> Path:
    """
    Campaign name dekhke sahi Cookies_Vault subfolder return karta hai.
    Uploaders is path se apne cookie files uthate hain.
    """
    folder_name = COOKIE_CAMPAIGN_MAP.get(campaign_name, DEFAULT_COOKIE_FOLDER)
    cookie_dir  = COOKIES_VAULT / folder_name
    if not cookie_dir.exists():
        print(f"  ⚠️  Cookie folder '{folder_name}' not found! Falling back to default.")
        cookie_dir = COOKIES_VAULT / DEFAULT_COOKIE_FOLDER
    return cookie_dir

print("\n" + "="*50)
print(" 👑 THE GHOST FACTORY: OVERLORD v3.0 BOOTING...")
print("="*50)
yt_upload     = load_engine("youtube_uploader")
tiktok_upload = None  # ⏸️  DISABLED — re-enable when TT cookies refreshed
ig_upload     = None  # ⏸️  DISABLED — re-enable when IG cookies refreshed
whop_submit   = load_engine("whop_submitter", func_name="submit_to_whop")
print("  ⏸️  TIKTOK_UPLOADER    : DISABLED (manual override)")
print("  ⏸️  INSTA_UPLOADER     : DISABLED (manual override)")
print("="*50 + "\n")

# ── 🧠 SMART CAPTION PARSER ──────────────────────────────────────────────────
def parse_smart_captions(full_text):
    """
    Splits the caption file into per-platform captions.

    Strategy: Split on the dash-line separators FIRST, then identify which
    platform each chunk belongs to.  This prevents any regex cross-
    contamination where IG could accidentally capture TT/YT content
    (the old (?:-{10,}|$) approach failed when IG was the last section
    and earlier dash-lines were consumed by a previous match).
    """
    caps = {"youtube": full_text, "tiktok": full_text, "instagram": full_text}  # safe fallback
    try:
        # Split on lines that are entirely dashes (10+ dashes)
        sections = re.split(r'\n-{10,}\n?', full_text)
        for section in sections:
            section = section.strip()
            if not section:
                continue
            if "TIKTOK CAPTION:" in section:
                after = section.split("TIKTOK CAPTION:", 1)[1].strip()
                if after:
                    caps['tiktok'] = after
            elif "YOUTUBE SHORTS CAPTION:" in section:
                after = section.split("YOUTUBE SHORTS CAPTION:", 1)[1].strip()
                if after:
                    caps['youtube'] = after
            elif "INSTAGRAM REELS CAPTION:" in section:
                after = section.split("INSTAGRAM REELS CAPTION:", 1)[1].strip()
                if after:
                    caps['instagram'] = after
        print(f"  ✅ Caption parser: TT={len(caps['tiktok'])}c | YT={len(caps['youtube'])}c | IG={len(caps['instagram'])}c")
    except Exception as e:
        print(f"⚠️ Parser Warning: {e} — falling back to full text for all platforms")
    return caps

# ─────────────────────────────────────────────────────────────────────────────

async def factory_manager():
    print(f"👁️‍🗨️ RADAR ACTIVE ON: {PENDING_DIR.name}\n")

    while True:
        ts = datetime.now().strftime('%H:%M:%S')
        videos = sorted(
            [p for p in PENDING_DIR.rglob("*.mp4") if p.parent != PENDING_DIR],  # only in subfolders
            key=lambda p: p.stat().st_mtime
        )
        # Also pick up any stray clips in root Pending_Videos (legacy support)
        root_vids = sorted(PENDING_DIR.glob("*.mp4"), key=lambda p: p.stat().st_mtime)
        videos = videos + root_vids

        if not videos:
            print(f"[{ts}] 😴 No fresh ammo. Scanning again in 10 minutes...")
            await asyncio.sleep(10 * 60)
            continue

        # ── 👁️ QUEUE VISIBILITY ──
        print(f"\n[{ts}] 📋 UPCOMING QUEUE (Next 5 clips):")
        for i, v in enumerate(videos[:5]):
            print(f"   {i+1}. {v.name}")
        print("-" * 50)

        video_path   = videos[0]
        current_clip = video_path.name
        caption_path = video_path.with_name(f"{video_path.stem}_caption.txt")
        
        full_caption_text = "Crazy facts! 🤯 #shorts #viral #mindset" # Backup
        if caption_path.exists():
            full_caption_text = caption_path.read_text(encoding="utf-8").strip()

        # 🔐 COOKIE VAULT: 3-Layer Campaign Detection
        # Layer 1 (BEST): Parent subfolder name (e.g. TJR_pending, Double_Coverage_pending)
        # Layer 2 (OK):   .meta.json sidecar file stamped by auto_factory
        # Layer 3 (LAST): DEFAULT fallback (TJR_campaign)
        detected_campaign = None

        # Layer 1: Subfolder name — THE CLEANEST SIGNAL
        parent_folder = video_path.parent.name  # e.g. 'TJR_pending'
        if parent_folder in COOKIE_CAMPAIGN_MAP:
            detected_campaign = parent_folder
            print(f"  📁  Campaign from folder: '{parent_folder}' → vault: '{COOKIE_CAMPAIGN_MAP[parent_folder]}'")

        # Layer 2: .meta.json sidecar (if no subfolder match)
        if not detected_campaign:
            meta_path = video_path.with_suffix(".meta.json")
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    detected_campaign = meta.get("campaign")
                    print(f"  🏷️  Campaign from meta.json: '{detected_campaign}'")
                except Exception:
                    pass

        # Layer 3: Default fallback
        if not detected_campaign:
            detected_campaign = DEFAULT_COOKIE_FOLDER
            print(f"  ⚠️  Campaign not detected — defaulting to '{detected_campaign}'")

        active_cookie_dir = resolve_cookie_dir(detected_campaign)
        os.environ["HS_COOKIE_DIR"] = str(active_cookie_dir)
        print(f"  🔐 Cookie Vault: '{active_cookie_dir.name}' (campaign: {detected_campaign})")

        # 🔥 CTO MAGIC: Yahan tere captions alag-alag bat jayenge!
        smart_caps = parse_smart_captions(full_caption_text)

        print(f"\n[{ts}] 🎯 TARGET ACQUIRED: {current_clip}")
        print(f"  📝 Extracted YT Caption : {len(smart_caps['youtube'])} characters")
        print(f"  📝 Extracted TT Caption : {len(smart_caps['tiktok'])} characters")
        print(f"  📝 Extracted IG Caption : {len(smart_caps['instagram'])} characters\n")

        upload_success = True

        # ── 1. YOUTUBE STRIKE ──────────────────────────────────────────
        yt_video_url = None   # Will hold youtu.be link for Whop
        if yt_upload:
            print("  ▶️ [1/3] Firing YouTube Engine...")
            try:
                yt_video_url = await asyncio.get_event_loop().run_in_executor(
                    None, yt_upload, str(video_path), smart_caps['youtube']
                )
                print(f"    ✅ YouTube: SUCCESS | URL: {yt_video_url or 'not captured'}\n")
            except Exception as e:
                print(f"    ❌ YouTube: FAILED ({e})\n")
                upload_success = False

        # ── 1b. WHOP AUTO-SUBMIT ───────────────────────────────────────
        if yt_video_url and whop_submit:
            print("  💰 [1b] Submitting to Whop campaign...")
            try:
                whop_ok = await asyncio.get_event_loop().run_in_executor(
                    None, whop_submit, yt_video_url, current_clip
                )
                if whop_ok:
                    print("    ✅ Whop: SUBMITTED — $$ on the way!\n")
                else:
                    print("    ⚠️ Whop: Skipped (form URL not set or submission failed)\n")
            except Exception as e:
                print(f"    ⚠️ Whop: FAILED ({e}) — upload still counted as success\n")

        # ── 2. TIKTOK STRIKE ───────────────────────────────────────────
        if tiktok_upload:
            print("  ▶️ [2/3] Firing TikTok Engine...")
            try:
                tt_video_url = await asyncio.get_event_loop().run_in_executor(None, tiktok_upload, str(video_path), smart_caps['tiktok'])
                print(f"    ✅ TikTok: SUCCESS | URL: {tt_video_url or 'not captured'}\n")
                if tt_video_url and whop_submit:
                    print("  💰 [2b] Submitting TikTok to Whop campaign...")
                    try:
                        whop_ok = await asyncio.get_event_loop().run_in_executor(None, whop_submit, tt_video_url, current_clip, "TikTok")
                        if whop_ok: print("    ✅ Whop: TikTok SUBMITTED!\n")
                        else: print("    ⚠️ Whop: TikTok Skipped\n")
                    except Exception as e:
                        print(f"    ⚠️ Whop: TikTok FAILED ({e})\n")
            except Exception as e:
                print(f"    ❌ TikTok: FAILED ({e})\n")
                upload_success = False

        # ── 3. INSTAGRAM STRIKE ────────────────────────────────────────
        if ig_upload:
            print("  ▶️ [3/3] Firing Instagram Engine...")
            try:
                ig_video_url = await asyncio.get_event_loop().run_in_executor(None, ig_upload, str(video_path), smart_caps['instagram'])
                print(f"    ✅ Instagram: SUCCESS | URL: {ig_video_url or 'not captured'}\n")
                if ig_video_url and whop_submit:
                    print("  💰 [3b] Submitting Instagram to Whop campaign...")
                    try:
                        whop_ok = await asyncio.get_event_loop().run_in_executor(None, whop_submit, ig_video_url, current_clip, "Instagram")
                        if whop_ok: print("    ✅ Whop: Instagram SUBMITTED!\n")
                        else: print("    ⚠️ Whop: Instagram Skipped\n")
                    except Exception as e:
                        print(f"    ⚠️ Whop: Instagram FAILED ({e})\n")
            except Exception as e:
                print(f"    ❌ Instagram: FAILED ({e})\n")
                upload_success = False

        # If none of the uploaders loaded, fail immediately
        if not yt_upload and not tiktok_upload and not ig_upload:
            print("  💀 ALL ENGINES OFFLINE — skipping to Failed_Videos\n")
            upload_success = False

        # ── ARCHIVE & SLEEP ────────────────────────────────────────────
        dest_dir   = UPLOADED_DIR if upload_success else FAILED_DIR
        dest_label = "📦 ARCHIVED (Success)" if upload_success else "⚠️ MOVED TO FAILED"

        shutil.move(str(video_path), str(dest_dir / current_clip))
        if caption_path.exists():
            shutil.move(str(caption_path), str(dest_dir / caption_path.name))

        print(f"{dest_label} -> {dest_dir.name}/{current_clip}")

        if upload_success:
            wait_secs = random.randint(WAIT_TIME_MIN, WAIT_TIME_MAX)
            wait_hrs  = wait_secs / 3600
            print(f"\n🛡️ GHOST MODE ACTIVATED. Radar off for {wait_hrs:.1f} hours to avoid detection...")
            
            # Live countdown timer
            for remaining in range(wait_secs, 0, -1):
                hrs, rem = divmod(remaining, 3600)
                mins, secs = divmod(rem, 60)
                sys.stdout.write(f"\r⏳ Time until next strike: {hrs:02d}h {mins:02d}m {secs:02d}s ")
                sys.stdout.flush()
                await asyncio.sleep(1)
            print("\n")
        else:
            print("\n⚠️ System encountered errors. Retrying next file in 5 minutes...\n")
            await asyncio.sleep(5 * 60)

if __name__ == "__main__":
    asyncio.run(factory_manager())