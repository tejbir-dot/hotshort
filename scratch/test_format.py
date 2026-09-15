import sys
import logging
from effects.format_analyzer import analyze_video_format

logging.basicConfig(level=logging.INFO, format="%(message)s")

def main():
    if len(sys.argv) > 1:
        clip_path = sys.argv[1]
    else:
        clip_path = r"c:\Users\n\Documents\hotshort\test_downloads\test123.mp4"
    
    print(f"Running format analyzer on: {clip_path}")
    res = analyze_video_format(clip_path)
    print("Result:", res.format_type, "avg_faces:", res.face_count_avg)

if __name__ == "__main__":
    main()

