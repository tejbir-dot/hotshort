import sys
import os
import io
import json
import time
import traceback
from datetime import datetime

# Force UTF-8 on Windows — prevents emoji crash in face scanner threads
if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass
    os.environ["PYTHONIOENCODING"] = "utf-8"

# Root folder ko Python path mein add karna taaki local_worker import ho sake
PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PARENT_DIR)

# Ab tera actual engine import ho jayega
import local_worker
local_worker._LOCAL_MODE = True
from local_worker import _process_job  # Engine entry function

# --- FACTORY CONFIGURATION ---
FACTORY_DIR = os.path.dirname(os.path.abspath(__file__))
QUEUE_FILE = os.path.join(FACTORY_DIR, "queue.txt")
FACTORY_OUTPUT_DIR = os.path.join(FACTORY_DIR, "Output")
PENDING_DIR = os.path.join(FACTORY_DIR, "Pending_Videos")

# Campaign name → which Pending_Videos subfolder to drop clips into
CAMPAIGN_PENDING_MAP = {
    "TJR_trader":              "TJR_pending",
    "TJR_trader_new":          "TJR_pending",
    "Double_Coverage_Podcast": "Double_Coverage_pending",
    "Double_Coverage_podcast": "Double_Coverage_pending",
    # Default for unknown campaigns:
    "default":                 "TJR_pending",
}

# ── 🎨 PER-CAMPAIGN BRANDING CONFIG ───────────────────────────────────────────
# handle       = @tag that gets injected in caption (replaces generic @TJR etc.)
# replace_tags = old @handles to find-and-replace in generated captions
# hashtags     = campaign-specific hashtags (appended / replace generic ones)
CAMPAIGN_BRANDING = {
    "TJR_trader": {
        "handle":       "@TJR",
        "replace_tags": [],
        "hashtags":     "#clipculture #thegeniusclipper #tjradmiral #daytrading #tradingmindset",
    },
    "TJR_trader_new": {
        "handle":       "@TJR",
        "replace_tags": [],
        "hashtags":     "#clipculture #thegeniusclipper #tjradmiral #daytrading #tradingmindset",
    },
    "Double_Coverage_Podcast": {
        "handle":       "@DoubleCoveragePodcast",
        "replace_tags": ["@TJR", "@tjr"],   # remove TJR branding
        "hashtags":     "#doublecoverage #doublecoveragepodcast #nfl #sports #podcast #football #sportspodcast",
    },
    "Double_Coverage_podcast": {
        "handle":       "@DoubleCoveragePodcast",
        "replace_tags": ["@TJR", "@tjr"],
        "hashtags":     "#doublecoverage #doublecoveragepodcast #nfl #sports #podcast #football #sportspodcast",
    },
}

def patch_captions(campaign_dir: str, campaign: str):
    """
    Post-process all _caption.txt files in campaign_dir:
    - Replace wrong @handles with correct campaign handle
    - Replace generic hashtag blocks with campaign-specific ones
    """
    branding = CAMPAIGN_BRANDING.get(campaign)
    if not branding:
        return  # No branding config — skip

    handle      = branding["handle"]
    replace_tags = branding["replace_tags"]
    hashtags    = branding["hashtags"]

    import re as _re
    caption_files = [
        os.path.join(root, f)
        for root, _, files in os.walk(campaign_dir)
        for f in files if f.endswith("_caption.txt")
    ]

    for cap_path in caption_files:
        text = open(cap_path, encoding="utf-8").read()
        original = text

        # 1. Replace wrong handles
        for wrong_tag in replace_tags:
            text = text.replace(wrong_tag, handle)

        # 2. Replace the entire "Hashtags: ..." line with campaign hashtags
        text = _re.sub(
            r'Hashtags:.*',
            f'Hashtags: {hashtags}',
            text
        )

        # 3. Make sure handle appears (add if not present)
        if handle not in text:
            text = text.replace("@TJR", handle)

        if text != original:
            open(cap_path, "w", encoding="utf-8").write(text)
            print(f"    [BRAND] Patched: {os.path.basename(cap_path)}")


def setup_factory():
    """Output + Pending subfolders banayega agar nahi hain"""
    if not os.path.exists(FACTORY_OUTPUT_DIR):
        os.makedirs(FACTORY_OUTPUT_DIR)
        print(f"[FACTORY INIT] Created master output directory: {FACTORY_OUTPUT_DIR}")
    # Auto-create all pending subfolders
    for subfolder in set(CAMPAIGN_PENDING_MAP.values()):
        path = os.path.join(PENDING_DIR, subfolder)
        if not os.path.exists(path):
            os.makedirs(path)
            print(f"[FACTORY INIT] Created pending subfolder: {subfolder}/")

def read_queue():
    """queue.txt se links aur campaign names padhega"""
    if not os.path.exists(QUEUE_FILE):
        print(f"[ERROR] {QUEUE_FILE} not found! Factory band hai.")
        return []
    
    tasks = []
    with open(QUEUE_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            # Ignore empty lines or comments
            if not line or line.startswith("#"):
                continue

            # Format: video_path | campaign_name | creator_intent (optional)
            if "|" in line:
                parts = [x.strip() for x in line.split("|")]
                video_path    = parts[0]
                campaign_name = parts[1] if len(parts) > 1 else "default"
                creator_intent = parts[2] if len(parts) > 2 else ""
                tasks.append({
                    "path": video_path,
                    "campaign": campaign_name,
                    "creator_intent": creator_intent,
                })
            else:
                print(f"[WARNING] Skipping invalid line in queue: {line} (Use 'path | campaign | intent')")
    return tasks

FORMATS = {
    "1": "center_crop",
    "2": "9_16_blur",
    "3": "square",
    "4": "original",
}

def _ask_format(n_videos: int) -> str:
    """Ek baar poochh lo — phir saare videos pe yahi format lagega."""
    print("\n" + "═" * 50)
    print("  📐 VIDEO FORMAT SELECT KARO  (sirf ek baar)")
    print("═" * 50)
    print("  1 → center_crop   (9:16 face-centered)  [DEFAULT]")
    print("  2 → 9_16_blur     (9:16 blurred sides)")
    print("  3 → square        (1:1)")
    print("  4 → original      (no crop)")
    print("═" * 50)
    try:
        choice = input("  Choice [1/2/3/4] (Enter = 1): ").strip()
    except (EOFError, KeyboardInterrupt):
        choice = "1"
    fmt = FORMATS.get(choice, "center_crop")
    print(f"  ✅ Format locked: {fmt}  (saare {n_videos} videos pe yahi lagega)")
    print("═" * 50 + "\n")
    return fmt

def run_factory():
    print(f"\n🚀 [OVERNIGHT FACTORY STARTED] Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    setup_factory()
    tasks = read_queue()

    if not tasks:
        print("[FACTORY STATUS] Queue is empty. Going to sleep! 😴")
        return

    # ── Ek baar format poochh lo ──────────────────────────────────────
    chosen_format = _ask_format(len(tasks))
    print(f"[FACTORY STATUS] Found {len(tasks)} videos in queue. Format: {chosen_format}. Starting mass production...\n")

    for index, task in enumerate(tasks, 1):
        video_path     = task['path']
        campaign       = task['campaign']
        creator_intent = task.get('creator_intent', '') or ''

        # Extract Video ID for folder naming
        import re as _re
        vid_match = _re.search(r'(?:v=|youtu\.be/|shorts/)([a-zA-Z0-9_-]{11})', video_path)
        vid_id = vid_match.group(1) if vid_match else f"vid_{int(time.time())}"

        # Campaign and Video specific folder banana
        campaign_dir = os.path.join(FACTORY_OUTPUT_DIR, campaign, vid_id)
        if not os.path.exists(campaign_dir):
            os.makedirs(campaign_dir)

        print(f"{'='*60}")
        print(f"🎬 [PROCESSING {index}/{len(tasks)}] Campaign: {campaign}")
        print(f"🔗 Source: {video_path}")
        print(f"📁 Target Folder: {campaign_dir}")
        if creator_intent:
            print(f"🎯 Creator Intent: {creator_intent}")
        else:
            print(f"🎯 Creator Intent: (none — generic viral mode)")
        print(f"{'='*60}")

        # THE BULLETPROOF TRY-CATCH (Zero Crash Guarantee)
        try:
            start_time = time.time()

            # ---------------------------------------------------------
            # ⚙️ TERA HOTSHORT ENGINE YAHAN FIRE HOGA
            # creator_intent local_worker → orchestrator → groq_cortex tak
            # already wired hai (local_worker.py line 1777)
            job_dict = {
                "job_id": f"factory_{int(time.time())}_{index}",
                "youtube_url": video_path,
                "video_format": chosen_format,
                "creator_intent": creator_intent if creator_intent else None,
            }
            # Temporarily override OS env to output in campaign dir
            os.environ["HS_CLIPS_DIR"] = os.path.abspath(campaign_dir)

            _process_job(job_dict, cloudinary_ok=False)

            # 🏷️ STAMP META FILES: Har clip ke sath .meta.json sidecar file banao
            # Manager.py yahi file padhke campaign identify karega — no guessing!
            for clip_file in Path(campaign_dir).rglob("*.mp4"):
                meta_path = clip_file.with_suffix(".meta.json")
                if not meta_path.exists():  # already stamped? skip
                    meta_data = {
                        "campaign": campaign,
                        "source_url": video_path,
                        "generated_at": datetime.now().isoformat(),
                    }
                    meta_path.write_text(json.dumps(meta_data, indent=2), encoding="utf-8")
                    print(f"    🏷️ Meta stamped: {clip_file.name}.meta.json")

            # 🎨 PATCH CAPTIONS: Wrong @handle aur hashtags swap karo
            print(f"\n    [BRAND] Patching captions for campaign: {campaign}...")
            patch_captions(campaign_dir, campaign)

            # 🔥 NEW: AUTOMATIC WATERMARK FOR DOUBLE COVERAGE
            if campaign.lower() == "double_coverage_podcast":
                import watermark
                image_wp = r"C:\Users\n\Documents\hotshort\assets\broll_assets\money_assets\double_coverage_campaign watermark.webp"
                print(f"\n💧 Triggering Double Coverage Watermark for {campaign_dir}...")
                watermark.apply_watermarks(campaign_dir, image_path=image_wp)

            # 📦 AUTO-ROUTE CLIPS TO CORRECT PENDING SUBFOLDER
            # Manager.py reads the subfolder name to identify campaign + pick cookie vault!
            pending_subfolder = CAMPAIGN_PENDING_MAP.get(campaign, CAMPAIGN_PENDING_MAP["default"])
            pending_dest = os.path.join(PENDING_DIR, pending_subfolder)
            os.makedirs(pending_dest, exist_ok=True)
            moved_count = 0
            for clip_file in Path(campaign_dir).rglob("*.mp4"):
                caption_file = clip_file.with_name(f"{clip_file.stem}_caption.txt")
                shutil.copy2(str(clip_file), os.path.join(pending_dest, clip_file.name))
                if caption_file.exists():
                    shutil.copy2(str(caption_file), os.path.join(pending_dest, caption_file.name))
                moved_count += 1
            print(f"\n  📦 AUTO-ROUTED {moved_count} clip(s) → Pending_Videos/{pending_subfolder}/")
            # ---------------------------------------------------------

            elapsed = round(time.time() - start_time, 2)
            print(f"✅ [SUCCESS] Video {index} complete in {elapsed}s. Saved to {campaign}/")


        except Exception as e:
            print(f"❌ [CRITICAL FAILURE] Video {index} crashed!")
            print(f"⚠️ Error: {str(e)}")
            # Error log save karega taaki subah tu padh sake kyu fail hua
            with open("factory_errors.log", "a") as err_log:
                err_log.write(f"\n[{datetime.now()}] Failed: {video_path}\n{traceback.format_exc()}\n")
            print("[FACTORY RECOVERY] Skipping to the next video...\n")
            
    print(f"\n🏁 [OVERNIGHT FACTORY FINISHED] Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"💼 CEO Sahab, aapki clips '{FACTORY_OUTPUT_DIR}' folder mein ready hain!")

if __name__ == "__main__":
    run_factory()
