import os
from pydub import AudioSegment
from pydub.silence import detect_nonsilent
from moviepy.editor import VideoFileClip, concatenate_videoclips
import shutil
import logging

log = logging.getLogger(__name__)

def run_silence_killer(input_video_path: str, output_video_path: str) -> bool:
    print("🔥 Starting Silence Killer...")
    log.info(f"[SILENCE_KILLER] Processing: {input_video_path}")
    
    # 1. Load video and extract audio
    video = VideoFileClip(input_video_path)
    if video.audio is None:
        print("❌ No audio found in video. Skipping silence killer.")
        video.close()
        shutil.copy2(input_video_path, output_video_path)
        return False
        
    temp_wav = input_video_path + "_temp_audio.wav"
    video.audio.write_audiofile(temp_wav, logger=None)
    
    # 2. Analyze audio using pydub
    pydub_audio = AudioSegment.from_wav(temp_wav)
    
    # CONFIGURATION (The Magic Numbers)
    MIN_SILENCE_LEN = 500  # Sirf us silence ko pakdo jo 0.5 sec se badi ho
    SILENCE_THRESH = -40   # -40 dBFS (Iske neeche sab silence hai)
    PAD_MS = 150           # The Secret Sauce (150ms ka buffer)
    
    print("🔍 Analyzing audio for silent gaps...")
    # detect_nonsilent returns a list of [start_ms, end_ms] of SPEAKING parts
    speaking_chunks = detect_nonsilent(
        pydub_audio, 
        min_silence_len=MIN_SILENCE_LEN, 
        silence_thresh=SILENCE_THRESH
    )
    
    # Clean up temp wav
    if os.path.exists(temp_wav):
        os.remove(temp_wav)
        
    if not speaking_chunks:
        print("❌ No speaking found. Skipping.")
        video.close()
        shutil.copy2(input_video_path, output_video_path)
        return False

    # 3. Apply Padding and Cut Video
    keep_clips = []
    video_duration_ms = video.duration * 1000
    
    for i, chunk in enumerate(speaking_chunks):
        start_ms, end_ms = chunk
        
        # Add Padding (but don't go out of bounds)
        start_ms = max(0, start_ms - PAD_MS)
        end_ms = min(video_duration_ms, end_ms + PAD_MS)
        
        # Convert ms to seconds for moviepy
        start_sec = start_ms / 1000.0
        end_sec = end_ms / 1000.0
        
        # Extract the speaking subclip
        keep_clips.append(video.subclip(start_sec, end_sec))
    
    print(f"✂️ Cutting {len(speaking_chunks)} speaking chunks and concatenating...")
    log.info(f"[SILENCE_KILLER] Kept {len(speaking_chunks)} chunks.")
    
    if len(keep_clips) == 1 and keep_clips[0].duration >= video.duration - 0.5:
        # If the only chunk spans almost the entire video, no need to re-render
        print("ℹ️ No significant silence found. Skipping re-render.")
        log.info("[SILENCE_KILLER] No significant silence found, bypassing render.")
        video.close()
        shutil.copy2(input_video_path, output_video_path)
        return False
    
    # 4. Merge all speaking clips back together safely
    # method="compose" prevents audio glitching/drifting
    final_video = concatenate_videoclips(keep_clips, method="compose")
    
    temp_m4a = input_video_path + "_temp_audio.m4a"
    final_video.write_videofile(
        output_video_path, 
        codec="libx264", 
        audio_codec="aac", 
        temp_audiofile=temp_m4a, 
        remove_temp=True,
        fps=video.fps,
        logger=None # Suppress moviepy logs
    )
    
    # Close resources
    final_video.close()
    video.close()
    for c in keep_clips:
        c.close()
        
    print("✅ Viral Cut Ready!")
    return True
