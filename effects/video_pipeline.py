import os
import random
import subprocess
import yt_dlp
import time

from effects.smart_cutting_engine import run_smart_cut_pipeline

OUTPUT_DIR = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

def generate_clip_for_job(yt_url, job_id, progress=None):
    """
    Download the yt_url to a temp file named temp_{job_id}.mp4
    Use the Smart Cutting Engine to create an energetic short clip.
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

    # 2) Run Semantic-First Editor
    say("Running Semantic-First Editor...")
    try:
        # Phase 12: Mock connection to the Hotshort brain
        mock_semantic_profile = {
            "preset": "hype", # Phase 10: Color Preset
            "triggers": [
                {"start": 2.0, "end": 5.0, "type": "surprise", "score": 0.95}, # Phase 7: Zoom Engine trigger
                {"start": 8.0, "end": 12.0, "type": "topic_shift", "score": 0.88} # Phase 8: Transition Engine trigger
            ]
        }
        
        run_smart_cut_pipeline(temp_file, output_file, target_duration=15.0, semantic_profile=mock_semantic_profile)
        say("Elite semantic short ready!")
    except Exception as e:
        say(f"Smart cut failed: {e}. Falling back to random cut...")
        
        # 3) Fallback: Random cut
        cmd_duration = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            temp_file
        ]
        duration = float(subprocess.check_output(cmd_duration).strip())
        
        clip_length = random.randint(8, 15)
        start_time = 0
        if duration > clip_length:
            start_time = random.randint(0, int(duration - clip_length))
        end_time = start_time + clip_length
        
        cmd_fallback = [
            "ffmpeg", "-ss", str(start_time), "-to", str(end_time),
            "-i", temp_file,
            "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-c:a", "aac",
            output_file, "-y", "-loglevel", "error"
        ]
        subprocess.run(cmd_fallback, check=True)
        say("Fallback clip ready.")

    # small pause to allow OS flush
    time.sleep(0.5)
    return output_file
