import os
import sys
import logging

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from effects.world_class_editor import ClipEditor

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def verify_broll_logic():
    # Setup mock data for the editor
    cfg = {
        "work_dir": os.path.abspath(os.path.join(os.path.dirname(__file__), "wce_work")),
        "font_file": "arial.ttf"
    }
    os.makedirs(cfg["work_dir"], exist_ok=True)
    
    editor = ClipEditor(cfg["work_dir"])
    
    # We pass an empty b_roll_keywords to force the fallback logic
    cortex_meta = {
        "content_genre": "podcast",
        "b_roll_keywords": ["money", "finance"]
    }
    
    # We pass a fake transcript
    transcript = [
        {"start": 0.0, "end": 1.0, "text": "This"},
        {"start": 1.0, "end": 2.0, "text": "conversation"},
        {"start": 2.0, "end": 3.0, "text": "about"},
        {"start": 3.0, "end": 4.0, "text": "nothing"},
        {"start": 4.0, "end": 5.0, "text": "nature"},
        {"start": 5.0, "end": 6.0, "text": "creation"},
        {"start": 6.0, "end": 7.0, "text": "is"},
        {"start": 7.0, "end": 8.0, "text": "insane"},
        {"start": 8.0, "end": 9.0, "text": "and"},
        {"start": 9.0, "end": 10.0, "text": "crazy"}
    ]
    
    # Fake video path
    dummy_vid = os.path.join(cfg["work_dir"], "dummy.mp4")
    if not os.path.exists(dummy_vid):
        os.system(f'ffmpeg -f lavfi -i color=c=black:s=1280x720:d=10 -f lavfi -i anullsrc=r=44100:cl=mono:d=10 -c:v libx264 -c:a aac "{dummy_vid}" -y')

    try:
        editor.enhance_pretrimmed_clip(
            input_path=dummy_vid,
            output_path=os.path.join(cfg["work_dir"], "dummy_out.mp4"),
            source_start=0.0,
            source_end=10.0,
            transcript=transcript,
            cortex_hints=cortex_meta,
            precomputed_narrative=None
        )
    except Exception as e:
        logging.info(f"Execution reached exception: {e}")

if __name__ == "__main__":
    os.environ["HS_BROLL_ENABLED"] = "1"
    verify_broll_logic()
