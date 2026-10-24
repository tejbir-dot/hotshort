import os, sys
REPO = r"c:\Users\n\Documents\hotshort"
sys.path.insert(0, REPO)

from effects.world_class_editor import ClipEditor, ClipEditConfig
print("[OK] Import successful")

clip = os.path.join(REPO, "test_dc_720p_chunk.mp4")
out  = os.path.join(REPO, "test_dc_speaker_out.mp4")
print(f"[TEST] clip={clip}")

editor = ClipEditor(work_dir=os.path.join(REPO, "_test_chunk_tmp"))
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
    source_end=15.0,
    transcript=None,
    config=config,
    clip_title="DC Speaker Highlight Test",
)

print(f"[DONE] output={result.output_path}")
print(f"[META] engagement_score={result.engagement_score}")
print(f"[META] video_format={result.metadata.get('video_format','?')}")
print(f"[META] speaker_positions={result.metadata.get('speaker_positions','?')}")
