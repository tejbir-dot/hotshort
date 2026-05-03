import os
import subprocess
import tempfile
import wave
import contextlib
# Lazy loaded dependencies: webrtcvad, scenedetect, librosa, numpy
# ---------------------------------------------------------
# SMART CUTTING ENGINE (PHASES 1-12)
# THE SEMANTIC-FIRST EDITOR
# ---------------------------------------------------------

def detect_scenes(video_path: str) -> list[tuple[float, float]]:
    try:
        from scenedetect import detect, ContentDetector
        scene_list = detect(video_path, ContentDetector())
        segments = [(s[0].get_seconds(), s[1].get_seconds()) for s in scene_list]
    except ImportError:
        segments = []
        
    if not segments:
        cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", video_path]
        try:
            dur = float(subprocess.check_output(cmd).strip())
            segments.append((0.0, dur))
        except Exception:
            pass
    return segments

def extract_pcm(video_path: str, wav_path: str):
    cmd = ["ffmpeg", "-y", "-i", video_path, "-vn", "-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le", wav_path]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

def detect_silence(video_path: str, aggressiveness: int = 3) -> list[tuple[float, float]]:
    import webrtcvad
    fd, tmp_wav = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        extract_pcm(video_path, tmp_wav)
        vad = webrtcvad.Vad(aggressiveness)
        with contextlib.closing(wave.open(tmp_wav, 'rb')) as wf:
            sample_rate = wf.getframerate()
            pcm_data = wf.readframes(wf.getnframes())
        
        frame_duration_ms = 30
        frame_size = int(sample_rate * (frame_duration_ms / 1000.0) * 2)
        
        silences = []
        in_silence = False
        silence_start = 0.0
        offset = 0
        while offset + frame_size < len(pcm_data):
            frame = pcm_data[offset:offset+frame_size]
            is_speech = vad.is_speech(frame, sample_rate)
            timestamp = (offset / 2) / sample_rate
            if not is_speech and not in_silence:
                in_silence = True
                silence_start = timestamp
            elif is_speech and in_silence:
                in_silence = False
                silences.append((silence_start, timestamp))
            offset += frame_size
        if in_silence:
            timestamp = (offset / 2) / sample_rate
            silences.append((silence_start, timestamp))
        return silences
    finally:
        if os.path.exists(tmp_wav):
            os.remove(tmp_wav)

def detect_beats(video_path: str) -> list[float]:
    fd, tmp_wav = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        extract_pcm(video_path, tmp_wav)
        y, sr = librosa.load(tmp_wav, sr=16000)
        tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
        beat_times = librosa.frames_to_time(beat_frames, sr=sr)
        return list(beat_times)
    except Exception as e:
        print(f"[BEAT-DETECT] Failed: {e}")
        return []
    finally:
        if os.path.exists(tmp_wav):
            os.remove(tmp_wav)

def merge_segments(scenes: list[tuple[float, float]], silences: list[tuple[float, float]], min_len: float = 1.0) -> list[tuple[float, float]]:
    valid_segments = []
    for s_start, s_end in scenes:
        cur_start = s_start
        for sil_start, sil_end in silences:
            if sil_end <= cur_start or sil_start >= s_end:
                continue
            if sil_start > cur_start:
                if (sil_start - cur_start) >= min_len:
                    valid_segments.append((cur_start, sil_start))
            cur_start = max(cur_start, sil_end)
        if (s_end - cur_start) >= min_len:
            valid_segments.append((cur_start, s_end))
    return valid_segments

def snap_cut_to_nearest_beat(timestamp: float, beats: list[float], max_shift: float = 0.3) -> float:
    if not beats: return timestamp
    nearest_beat = min(beats, key=lambda b: abs(b - timestamp))
    if abs(nearest_beat - timestamp) <= max_shift:
        return nearest_beat
    return timestamp

def score_energy(video_path: str, segments: list[tuple[float, float]], scenes: list[tuple[float, float]], silences: list[tuple[float, float]], semantic_profile: dict) -> list[dict]:
    energy_curve = build_energy_curve(video_path, samples=128)
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", video_path]
    try:
        total_dur = float(subprocess.check_output(cmd).strip())
    except Exception:
        total_dur = segments[-1][1] if segments else 1.0
        
    num_samples = len(energy_curve) if energy_curve else 1
    ranked = []
    
    triggers = semantic_profile.get("triggers", []) if semantic_profile else []
    
    for start, end in segments:
        duration = end - start
        if duration <= 0: continue
            
        if energy_curve:
            s_idx = max(0, min(int((start / total_dur) * num_samples), num_samples - 1))
            e_idx = max(0, min(int((end / total_dur) * num_samples), num_samples))
            if e_idx > s_idx:
                chunk_energy = energy_curve[s_idx:e_idx]
                motion_score = sum(chunk_energy) / len(chunk_energy)
            else:
                motion_score = energy_curve[s_idx] if s_idx < num_samples else 0.0
        else:
            motion_score = 0.5
            
        silence_in_seg = sum(max(0, min(end, sil_end) - max(start, sil_start)) for sil_start, sil_end in silences if max(start, sil_start) < min(end, sil_end))
        speech_density = max(0.0, min(1.0, 1.0 - (silence_in_seg / duration)))
        
        # Connect to Brain (Phase 12)
        semantic_strength = 0.5
        zoom_trigger = False
        transition_type = "smash"
        
        for trig in triggers:
            t_start, t_end = trig.get("start", 0), trig.get("end", 0)
            if max(start, t_start) < min(end, t_end):
                semantic_strength = max(semantic_strength, trig.get("score", 0.8))
                if trig.get("type") in ["surprise", "question", "belief_reversal", "number", "command"]:
                    zoom_trigger = True
                if trig.get("type") == "topic_shift":
                    transition_type = "whip"
        
        scenes_in_seg = sum(1 for sc in scenes if start <= sc[0] < end)
        scene_change_rate = min(1.0, scenes_in_seg / (duration / 3.0)) if duration > 0 else 0.0
        
        energy_score = (0.4 * motion_score) + (0.3 * speech_density) + (0.2 * semantic_strength) + (0.1 * scene_change_rate)
        
        if energy_score >= 0.3:
            ranked.append({
                "start": start,
                "end": end,
                "score": energy_score,
                "duration": duration,
                "zoom": zoom_trigger,
                "transition": transition_type
            })
        
    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked

def choose_best_segments(ranked_segments: list[dict], target_duration: float = 15.0) -> list[dict]:
    selected = []
    current_duration = 0.0
    for seg in ranked_segments:
        if current_duration + seg["duration"] <= target_duration + 2.0:
            selected.append(seg)
            current_duration += seg["duration"]
        if current_duration >= target_duration:
            break
    selected.sort(key=lambda x: x["start"])
    return selected

def create_mock_ass(segments: list[dict], ass_path: str):
    """Phase 9: Cheap CPU Caption Engine Burn-in (Mock Whisper)"""
    header = [
        "[Script Info]", "ScriptType: v4.00+", "PlayResX: 1080", "PlayResY: 1920",
        "[V4+ Styles]",
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding",
        "Style: Default,Arial,60,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,2,0,2,10,10,150,1",
        "[Events]",
        "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text"
    ]
    def _ass_time(sec):
        h, m, s = int(sec//3600), int((sec%3600)//60), sec%60
        return f"{h}:{m:02d}:{s:05.2f}"
        
    events = []
    rel_start = 0.0
    for i, seg in enumerate(segments):
        duration = seg["end"] - seg["start"]
        events.append(f"Dialogue: 0,{_ass_time(rel_start)},{_ass_time(rel_start+duration)},Default,,0,0,0,,{{\\b1}}Clip {i+1} {int(duration)}s{{\\b0}}")
        rel_start += duration
        
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write("\n".join(header + events))

def build_color_preset(preset: str) -> str:
    """Phase 10: Color Preset Engine"""
    if preset == "hype":
        return "eq=contrast=1.3:saturation=1.2:brightness=0.05"
    elif preset == "cinematic":
        return "eq=contrast=1.1:saturation=0.9:gamma=0.95"
    elif preset == "vlog":
        return "eq=contrast=1.05:saturation=1.1"
    return ""

def export_elite_short(video_path: str, segments: list[dict], output_path: str, preset: str = "hype"):
    if not segments: raise ValueError("No segments")
    
    fd, list_file = tempfile.mkstemp(suffix=".txt")
    os.close(fd)
    
    fd2, ass_file = tempfile.mkstemp(suffix=".ass")
    os.close(fd2)
    
    chunk_files = []
    try:
        create_mock_ass(segments, ass_file)
        color_filter = build_color_preset(preset)
        
        # Phase 7 & 8: Process chunks with zoompan & basic transitions
        for i, seg in enumerate(segments):
            chunk_out = f"{output_path}_chunk_{i}.mp4"
            chunk_files.append(chunk_out)
            
            vf_parts = []
            if seg.get("zoom"): # Phase 7 Zoom Engine
                vf_parts.append("zoompan=z='min(zoom+0.0015,1.5)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'")
            
            if color_filter: # Phase 10 Color
                vf_parts.append(color_filter)
                
            # Phase 8: Cheap transition - fast fade in for topic shifts
            if seg.get("transition") == "whip":
                vf_parts.append("fade=t=in:st=0:d=0.2")
                
            vf_string = ",".join(vf_parts) if vf_parts else "null"
            
            cmd = [
                "ffmpeg", "-y", "-ss", str(seg["start"]), "-to", str(seg["end"]),
                "-i", video_path, "-vf", vf_string,
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
                "-c:a", "aac", "-b:a", "128k", "-avoid_negative_ts", "1",
                chunk_out
            ]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            
        with open(list_file, "w") as f:
            for chunk in chunk_files:
                f.write(f"file '{os.path.abspath(chunk)}'\n")
                
        # Concat and Phase 9 Captions Burn-in
        concat_out = f"{output_path}_concat.mp4"
        ass_file_escaped = ass_file.replace('\\\\', '/').replace(':', '\\\\:')
        ass_filter = f"subtitles='{ass_file_escaped}'"
        
        concat_cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file,
            "-vf", ass_filter, "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
            "-c:a", "aac", "-b:a", "128k", concat_out
        ]
        subprocess.run(concat_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        
        # Phase 11: Audio Ducking (Mock - assume we had a bg_music.mp3)
        # If we had bg music, we would do:
        # ffmpeg -i concat_out -i bg_music -filter_complex "[1:a][0:a]sidechaincompress=threshold=-15dB:ratio=4[bg];[0:a][bg]amix=inputs=2[aout]" -map 0:v -map "[aout]" final.mp4
        # For now, we just move concat to output
        os.replace(concat_out, output_path)
        
    finally:
        if os.path.exists(list_file): os.remove(list_file)
        if os.path.exists(ass_file): os.remove(ass_file)
        for chunk in chunk_files:
            if os.path.exists(chunk): os.remove(chunk)

def run_smart_cut_pipeline(video_path: str, output_path: str, target_duration: float = 15.0, semantic_profile: dict = None) -> str:
    print("[SEMANTIC-EDITOR] Detecting scenes...")
    scenes = detect_scenes(video_path)
    
    print("[SEMANTIC-EDITOR] Detecting silence...")
    silences = detect_silence(video_path)
    
    print("[SEMANTIC-EDITOR] Detecting beats...")
    beats = detect_beats(video_path)
    
    print("[SEMANTIC-EDITOR] Merging boundaries...")
    segments = merge_segments(scenes, silences)
    
    print("[SEMANTIC-EDITOR] Scoring segments by energy & brain signals...")
    ranked = score_energy(video_path, segments, scenes, silences, semantic_profile)
    
    print("[SEMANTIC-EDITOR] Selecting best moments...")
    selected = choose_best_segments(ranked, target_duration)
    
    print("[SEMANTIC-EDITOR] Snapping cuts to beats...")
    for seg in selected:
        seg["start"] = snap_cut_to_nearest_beat(seg["start"], beats, max_shift=0.25)
        seg["end"] = snap_cut_to_nearest_beat(seg["end"], beats, max_shift=0.35)
    
    print(f"[SEMANTIC-EDITOR] Exporting {len(selected)} segments with Polish...")
    preset = semantic_profile.get("preset", "hype") if semantic_profile else "hype"
    export_elite_short(video_path, selected, output_path, preset=preset)
    
    return output_path

def render_platform_clip(input_path: str, output_path: str, format_type: str, is_pro: bool = False):
    """
    Phase 13: Export Platform Format logic.
    Applies resolution, fps, crf, trimming, and watermarks based on platform.
    """
    if format_type == "tiktok":
        max_duration = 60
        vf = "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,fps=30"
        crf = "22"
        b_a = "128k"
    elif format_type == "instagram":
        max_duration = 90
        vf = "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,fps=30"
        crf = "20"  # Higher quality for IG compression
        b_a = "128k"
    elif format_type == "shorts":
        max_duration = 60
        vf = "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,fps=60"
        crf = "18"
        b_a = "192k" # Better audio
    else:
        max_duration = 60
        vf = "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,fps=30"
        crf = "22"
        b_a = "128k"
        
    # Phase 13: Watermark Engine (Monetization Hook)
    if not is_pro:
        # Draw a semi-transparent watermark in the top left
        vf += ",drawtext=text='HOTSHORT':fontcolor=white@0.5:fontsize=48:x=50:y=50:box=1:boxcolor=black@0.3:boxborderw=10"
        
    # Check duration and trim if necessary
    cmd_dur = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", input_path]
    try:
        dur = float(subprocess.check_output(cmd_dur).strip())
    except Exception:
        dur = max_duration
        
    cmd = [
        "ffmpeg", "-y", "-i", input_path
    ]
    
    if dur > max_duration:
        cmd.extend(["-t", str(max_duration)])
        
    # Phase 13: Tiered Quality Engine (Smart Founder Move)
    # Free users get "Fast Export" (ultrafast) for stability.
    # Pro users get "HD Export" (fast) for better compression/quality.
    preset = "fast" if is_pro else "ultrafast"
    
    cmd.extend([
        "-vf", vf,
        "-c:v", "libx264", "-preset", preset, "-crf", crf,
        "-c:a", "aac", "-b:a", b_a,
        output_path
    ])
    
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    return output_path
