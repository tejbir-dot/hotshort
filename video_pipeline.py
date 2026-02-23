import os
import random
import subprocess
import yt_dlp
import time

OUTPUT_DIR = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

def generate_clip_for_job(yt_url, job_id, progress=None):
    """
    Download the yt_url to a temp file named temp_{job_id}.mp4
    Cut a random 8-15s clip and save as output/hotshort_clip_{job_id}.mp4
    progress: callable(message) for status updates
    """
    def say(msg):
        print(f"[{job_id}] {msg}")
        if callable(progress):
            try:
                progress(msg)
            except Exception:
                pass

    temp_file = f"temp_{job_id}.mp4"
    output_file = os.path.join(OUTPUT_DIR, f"hotshort_clip_{job_id}.mp4")

    # Remove any previous artifacts for this job (rare)
    for p in [temp_file, output_file]:
        try:
            if os.path.exists(p):
                os.remove(p)
        except Exception:
            pass

    # 1) Download
    say("Downloading video…")
    ydl_opts = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4",
        "outtmpl": temp_file,
        "merge_output_format": "mp4",
        "quiet": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([yt_url])

    # 2) Duration
    say("Extracting duration…")
    cmd_duration = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        temp_file
    ]
    duration = float(subprocess.check_output(cmd_duration).strip())
    say(f"Duration: {duration:.1f}s")

    # 3) Choose clip segment
    clip_length = random.randint(8, 15)
    start_time = 0
    if duration > clip_length:
        start_time = random.randint(0, int(duration - clip_length))
    end_time = start_time + clip_length
    say(f"Cutting {clip_length}s segment from {start_time}s → {end_time}s")

    # 4) Fast ffmpeg cut (no re-encode)
    try:
        say("Cutting clip (fast mode)...")
        cmd_cut = [
            "ffmpeg", "-ss", str(start_time), "-to", str(end_time),
            "-i", temp_file,
            "-c", "copy", "-avoid_negative_ts", "1",
            output_file, "-y", "-loglevel", "error"
        ]
        subprocess.run(cmd_cut, check=True)
        say("Clip ready (fast).")
    except subprocess.CalledProcessError:
        # fallback: re-encode via ffmpeg for reliability
        say("Fast cut failed, falling back to re-encode...")
        cmd_fallback = [
            "ffmpeg", "-ss", str(start_time), "-to", str(end_time),
            "-i", temp_file,
            "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
            output_file, "-y", "-loglevel", "error"
        ]
        subprocess.run(cmd_fallback, check=True)
        say("Clip ready (fallback).")

    # small pause to allow OS flush
    time.sleep(0.5)
    return output_file
