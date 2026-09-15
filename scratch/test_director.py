import sys
import logging
import os
from effects.world_class_editor import ClipEditor, ClipEditConfig

logging.basicConfig(level=logging.INFO, format="%(message)s")

def main():
    if len(sys.argv) > 1:
        clip_path = sys.argv[1]
    else:
        clip_path = r"c:\Users\n\Documents\hotshort\test_downloads\test123.mp4"
    
    out_path = clip_path.replace(".mp4", "_out.mp4")
    
    print(f"Running editor on: {clip_path}")
    
    config = ClipEditConfig(
        aspect_ratio="9:16",
        split_min_gap_ratio=0.38
    )
    
    editor = ClipEditor(work_dir=r"C:\Users\n\Documents\hotshort\scratch")
    try:
        editor.enhance_pretrimmed_clip(
            input_path=clip_path,
            output_path=out_path,
            source_start=0.0,
            source_end=15.0,
            config=config,
        )
    except Exception as e:
        print(f"Failed or completed: {e}")

if __name__ == "__main__":
    main()

