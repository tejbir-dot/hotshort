
import os, shutil
from effects.world_class_editor import ClipEditor, CaptionSegment

work_dir = "./scratch/wce_test_run"
editor = ClipEditor(work_dir=work_dir)

# Create a dummy video file or just call the _write_ass method directly since it writes files
dummy_path = os.path.join(work_dir, "test_subs.ass")

captions = [
    CaptionSegment(start=0.5, end=2.0, text="This is a test of the styling system."),
    CaptionSegment(start=2.2, end=4.5, text="We are verifying neon, beast, and minimal looks.")
]

# Test classic style
editor._write_ass(
    path=dummy_path,
    width=1080,
    height=1920,
    duration=5.0,
    captions=captions,
    hook_line="Classic Hook Test",
    cta_line="Follow for more",
    hashtags_line="#test #classic",
    subtitle_style="classic"
)
with open(dummy_path, "r", encoding="utf-8") as f:
    classic_content = f.read()
print("CLASSIC OUTLINE:", [l.strip() for l in classic_content.splitlines() if "Style: Caption" in l])

# Test neon style
editor._write_ass(
    path=dummy_path,
    width=1080,
    height=1920,
    duration=5.0,
    captions=captions,
    hook_line="Neon Hook Test",
    cta_line="Follow for more",
    hashtags_line="#test #neon",
    subtitle_style="neon"
)
with open(dummy_path, "r", encoding="utf-8") as f:
    neon_content = f.read()
print("NEON OUTLINE:", [l.strip() for l in neon_content.splitlines() if "Style: Caption" in l])

# Test beast style
editor._write_ass(
    path=dummy_path,
    width=1080,
    height=1920,
    duration=5.0,
    captions=captions,
    hook_line="Beast Hook Test",
    cta_line="Follow for more",
    hashtags_line="#test #beast",
    subtitle_style="beast"
)
with open(dummy_path, "r", encoding="utf-8") as f:
    beast_content = f.read()
print("BEAST OUTLINE:", [l.strip() for l in beast_content.splitlines() if "Style: Caption" in l])

# Test minimal style
editor._write_ass(
    path=dummy_path,
    width=1080,
    height=1920,
    duration=5.0,
    captions=captions,
    hook_line="Minimal Hook Test",
    cta_line="Follow for more",
    hashtags_line="#test #minimal",
    subtitle_style="minimal"
)
with open(dummy_path, "r", encoding="utf-8") as f:
    minimal_content = f.read()
print("MINIMAL OUTLINE:", [l.strip() for l in minimal_content.splitlines() if "Style: Caption" in l])

shutil.rmtree(work_dir, ignore_errors=True)
