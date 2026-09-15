import os
import sys
import logging

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("test_transitions")

from effects.world_class_editor import ClipEditor, ClipEditConfig

def test_integration():
    editor = ClipEditor(work_dir="scratch/test_wce_work")
    cfg = ClipEditConfig()
    cfg.target_ratio = "9:16"
    cfg.export_fps = 30
    
    # Enable transitions (defaulted to 1 anyway, but let's be explicit)
    os.environ["HS_TRANSITIONS_ENABLED"] = "1"
    
    input_path = "test.mp4"
    output_path = "scratch/test_output_with_transition.mp4"
    
    if not os.path.exists(input_path):
        log.error(f"Input file {input_path} not found!")
        sys.exit(1)
        
    log.info("Running enhance_pretrimmed_clip on test.mp4...")
    
    # We mock a small clip window (0.0 to 3.0 seconds)
    # This is long enough to trigger transition (needs >= 2.0s)
    res = editor.enhance_pretrimmed_clip(
        input_path=input_path,
        output_path=output_path,
        source_start=0.0,
        source_end=3.0,
        config=cfg,
        clip_title="Test Clip"
    )
    
    log.info(f"Edit result: {res}")
    if os.path.exists(output_path):
        log.info(f"SUCCESS! Output created at: {output_path} (size: {os.path.getsize(output_path)} bytes)")
    else:
        log.error("FAIL! Output file was not created.")
        sys.exit(1)

if __name__ == "__main__":
    test_integration()
