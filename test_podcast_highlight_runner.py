import os, sys
REPO = r"c:\Users\n\Documents\hotshort"
sys.path.insert(0, REPO)

from effects.world_class_editor import ClipEditor, ClipEditConfig
print("[OK] Import successful")

candidates = [
    os.path.join(REPO, "test_slice.mp4"),
    os.path.join(REPO, "test.mp4"),
    os.path.join(REPO, "test_nvenc.mp4"),
]
clip = next((c for c in candidates if os.path.exists(c) and os.path.getsize(c) > 100_000), None)
if not clip:
    print("[SKIP] No usable test clip found")
    sys.exit(0)

out = os.path.join(REPO, "test_out_podcast_highlight.mp4")
print(f"[TEST] clip={clip}")

editor = ClipEditor(work_dir=os.path.join(REPO, "_test_podcast_tmp"))
config = ClipEditConfig(
    target_ratio="9:16",
    add_captions=False,
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
    source_end=30.0,
    transcript=None,
    config=config,
    clip_title="Podcast Speaker Highlight Test",
)

print(f"[DONE] output={result.output_path}")
print(f"[META] engagement_score={result.engagement_score}")
fmt = result.metadata.get("format_detection", {})
print(f"[META] format_type={fmt.get('format_type','unknown')}")
print(f"[META] dual_pct={fmt.get('dual_speaker_pct','?')}")
