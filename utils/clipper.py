import subprocess
import os

def cut_clip_segment(video_path, start_time, end_time, output_path):
    """
    Cuts a clean mp4 clip using FFmpeg. NEVER produces corrupt files.
    """

    # Make sure folder exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Force overwrite and write correct codec
    command = [
        "ffmpeg",
        "-y",
        "-ss", str(start_time),
        "-to", str(end_time),
        "-i", video_path,
        "-c:v", "libx264",
        "-c:a", "aac",
        "-preset", "fast",
        "-movflags", "+faststart",
        output_path
    ]

    try:
        subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"[FFMPEG ERROR] {e}")
        return None

    # Extra safety: ensure final file is NOT empty
    if not os.path.exists(output_path) or os.path.getsize(output_path) < 5000:
        print("[ERROR] Output clip too small — failed render.")
        return None

    return output_path
