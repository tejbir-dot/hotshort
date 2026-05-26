import subprocess
import os
import json

def get_video_duration(video_path: str) -> float:
    """
    Get video duration in seconds using ffprobe.
    """
    try:
        result = subprocess.run([
            'ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', video_path
        ], capture_output=True, text=True, timeout=15)
        data = json.loads(result.stdout)
        return float(data['format']['duration'])
    except Exception as e:
        print(f"[FFPROBE ERROR] Failed to read video duration: {e}")
        return 0.0

def format_viral_clips(raw_clips, min_duration=30.0, overlap_threshold=5.0, video_duration=None):
    """
    Deduplicate clips that start at nearly the same time, and pad short clips to min_duration.
    Supports both dictionary objects and objects with attributes.
    """
    if not raw_clips:
        return []

    print(f"[INFO] Formatting {len(raw_clips)} raw clips (Applying Deduplication & 30s Padding)...")
    
    # Copy clips to avoid in-place side effects
    clips_copy = []
    for c in raw_clips:
        if isinstance(c, dict):
            clips_copy.append(c.copy())
        else:
            import copy
            try:
                clips_copy.append(copy.copy(c))
            except Exception:
                clips_copy.append(c)

    def get_val(item, key, default=0.0):
        if isinstance(item, dict):
            return item.get(key, default)
        return getattr(item, key, default)

    def set_val(item, key, val):
        if isinstance(item, dict):
            item[key] = val
        else:
            setattr(item, key, val)

    # 1. Sort clips by start time, and if start same, descending duration
    clips_copy.sort(key=lambda x: (get_val(x, 'start', 0.0), -(get_val(x, 'end', 0.0) - get_val(x, 'start', 0.0))))

    deduplicated = []
    for clip in clips_copy:
        if not deduplicated:
            deduplicated.append(clip)
            continue

        prev_clip = deduplicated[-1]
        
        # RULE 1: Deduplication - Check if start times are too close (Clones)
        if abs(get_val(clip, 'start', 0.0) - get_val(prev_clip, 'start', 0.0)) <= overlap_threshold:
            prev_duration = get_val(prev_clip, 'end', 0.0) - get_val(prev_clip, 'start', 0.0)
            curr_duration = get_val(clip, 'end', 0.0) - get_val(clip, 'start', 0.0)
            
            # If current clip is longer, replace the previous one
            if curr_duration > prev_duration:
                deduplicated[-1] = clip 
        else:
            deduplicated.append(clip)

    # RULE 2: The 30-Second Minimum (Padding)
    final_clips = []
    for clip in deduplicated:
        start = get_val(clip, 'start', 0.0)
        end = get_val(clip, 'end', 0.0)
        duration = end - start
        
        if duration < min_duration:
            new_end = start + min_duration
            # Ensure we do not cut beyond the actual video length
            if video_duration and new_end > video_duration:
                new_end = video_duration
            
            print(f"[TRACE] Padded clip from {duration:.1f}s to {new_end - start:.1f}s")
            set_val(clip, 'end', new_end)
            if isinstance(clip, dict):
                clip['duration'] = round(new_end - start, 2)
            else:
                if hasattr(clip, 'duration'):
                    clip.duration = round(new_end - start, 2)
                
        final_clips.append(clip)

    print(f"[INFO] Formatting complete. {len(final_clips)} viral clips ready.")
    return final_clips

def cut_clip_segment(video_path, start_time, end_time, output_path, is_free=False):
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
    ]
    
    vf_parts = []
    visual_style = os.getenv("HS_VISUAL_STYLE", "").strip().lower()
    if visual_style == "pixel_enhance":
        vf_parts.append("scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,eq=contrast=1.18:saturation=1.12:brightness=-0.03,unsharp=5:5:0.8:3:3:0.4,noise=alls=6:allf=t")
        
    if os.getenv("HS_WATERMARK_ENABLED") == "1" and (os.getenv("HS_WATERMARK_FREE_ONLY", "1") != "1" or is_free):
        wm_path = os.path.abspath("static/branding/logo_icon.png").replace("\\", "/")
        command.extend(["-i", wm_path])
        vf_str = ",".join(vf_parts) if vf_parts else "null"
        # Combine the linear chain with the second input using filter_complex
        vf_complex = f"[0:v]{vf_str}[v_main];[1:v]scale=90:-1[wm];[v_main][wm]overlay=W-w-30:H-h-120,drawtext=text='MADE WITH HOTSHORT':fontcolor=white@0.85:fontsize=28:borderw=2:bordercolor=black@0.5:x=w-text_w-25:y=h-80[out_v]"
        command += ["-filter_complex", vf_complex, "-map", "[out_v]", "-map", "0:a?"]
        print("[WATERMARK] premium applied=true path=clipper (fast-input mode)")
    else:
        if vf_parts:
            command += ["-vf", ",".join(vf_parts)]
        
    command += [
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

