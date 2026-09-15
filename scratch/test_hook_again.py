import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from effects.world_class_editor import ClipEditor, VideoFormat

def main():
    clip_path = r"c:\Users\n\Documents\hotshort\scratch\hotshort_out\clip_0_1436_1508.mp4"
    if not os.path.exists(clip_path):
        print("Clip not found:", clip_path)
        return

    # Enable transitions
    os.environ["HS_TRANSITIONS_ENABLED"] = "1"
    os.environ["HS_BROLL_ENABLED"] = "1"
    os.environ["HS_DISABLE_BG_BLUR"] = "1"

    print("Running Hook Polish Test on:", clip_path)

    wce = ClipEditor(work_dir="scratch/test_wce_work")
    os.makedirs("scratch/test_wce_work", exist_ok=True)
    
    video_fmt = VideoFormat()
    video_fmt.format_type = "podcast"
    video_fmt.speaker_positions = [0.5]
    video_fmt.face_count_avg = 1.0
    video_fmt.face_switch_rate = 0.0

    cortex_data = {
        "content_genre": "podcast",
        "b_roll_keywords": ["money", "finance", "cinematic"]
    }

    try:
        res = wce.enhance_pretrimmed_clip(
            clip_path=clip_path,
            captions=[],  # No captions to avoid double subbing
            clip_title="TEST HOOK POLISH",
            transcript_window="Test window",
            video_fmt=video_fmt,
            cortex_data=cortex_data
        )
        print("Done! Output at:", res.output_path)
    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
