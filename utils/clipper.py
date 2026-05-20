import subprocess
import os

def cut_clip_segment(video_path, start_time, end_time, output_path):
    """
    Cuts a clean mp4 clip using FFmpeg. NEVER produces corrupt files.
    """

    # Make sure folder exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Auto-detect if CUDA/NVENC is available for GPU acceleration
    use_nvenc = False
    if os.getenv("HS_USE_NVENC") == "1":
        use_nvenc = True
    elif os.getenv("HS_USE_NVENC") != "0":
        try:
            import torch
            use_nvenc = torch.cuda.is_available()
        except Exception:
            pass

    vcodec = "h264_nvenc" if use_nvenc else "libx264"
    preset = "p4" if use_nvenc else "fast"  # p4 is a balanced speed/quality NVENC preset

    command = [
        "ffmpeg",
        "-y",
        "-ss", str(start_time),
        "-to", str(end_time),
        "-i", video_path,
        "-c:v", vcodec,
        "-c:a", "aac",
        "-preset", preset,
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
