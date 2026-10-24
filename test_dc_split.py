import os, sys
REPO = r"c:\Users\n\Documents\hotshort"
sys.path.insert(0, REPO)

from effects.world_class_editor import ClipEditor, ClipEditConfig
print("[OK] Import successful")

# Use a real Double Coverage pre-trimmed clip (already trimmed by pipeline)
# These are the raw trimmed clips BEFORE editing
RAW_CLIPS_DIR = os.path.join(REPO, r"Overnight_Factory\Output\Double_Coverage_podcast\JdtyQDvriso")

# Pick a raw source — we need the ORIGINAL downloaded video, not the already-edited clip
# Check what the source yt video was
import glob
clips = sorted(glob.glob(os.path.join(RAW_CLIPS_DIR, "*.mp4")))
if not clips:
    print("[SKIP] No clips found")
    sys.exit(0)

clip = clips[0]
sz = os.path.getsize(clip)
print(f"[TEST] Using pre-trimmed clip: {clip} ({sz//1024}KB)")

out = os.path.join(REPO, "test_dc_speaker_highlight.mp4")
print(f"[TEST] Output: {out}")

editor = ClipEditor(work_dir=os.path.join(REPO, "_test_dc_tmp"))
config = ClipEditConfig(
    target_ratio="9:16",
    add_captions=False,          # skip captions - visual test only
    enhance_visuals=True,
    enhance_audio=False,
    enable_active_speaker=True,
    enable_format_detection=True,
    enable_hook_speed_ramp=False,
)

result = editor.enhance_pretrimmed_clip(
    input_path=clip,
    output_path=out,
    source_start=0.0,
    source_end=90.0,
    transcript=None,
    config=config,
    clip_title="DC Speaker Highlight Test",
)

print(f"\n[DONE] output={result.output_path}")
print(f"[META] engagement_score={result.engagement_score}")
fmt = result.metadata.get("format_detection", {})
print(f"[META] format_type={fmt.get('format_type','unknown')}")
print(f"[META] dual_pct={fmt.get('dual_speaker_pct','?')}")
print(f"[META] full_fmt={fmt}")
