import os
import shutil
import logging
import subprocess
import time
from pydub import AudioSegment
from pydub.silence import detect_nonsilent

import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

log = logging.getLogger(__name__)

def run_silence_killer(input_video_path: str, output_video_path: str) -> bool:
    t_start = time.perf_counter()
    if os.environ.get("HS_SILENCE_KILLER", "1").strip().lower() in ("0", "false", "no"):
        log.info("[SILENCE_KILLER] Disabled via HS_SILENCE_KILLER=0, bypassing.")
        shutil.copy2(input_video_path, output_video_path)
        return False

    print("[SILENCE_KILLER] Starting Silence Killer (Hardware Accelerated)...", flush=True)
    log.info(f"[SILENCE_KILLER] Processing: {input_video_path}")
    
    # 1. Probe video and audio duration via ffprobe
    try:
        probe = subprocess.run([
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration:stream=codec_type",
            "-of", "json",
            input_video_path
        ], capture_output=True, text=True, check=True, timeout=15)
        import json
        p_data = json.loads(probe.stdout)
        duration_sec = float(p_data.get("format", {}).get("duration", 0.0))
        streams = p_data.get("streams", [])
        has_audio = any(s.get("codec_type") == "audio" for s in streams)
    except Exception as e:
        log.warning(f"[SILENCE_KILLER] Probe failed ({e}), falling back to direct copy.")
        shutil.copy2(input_video_path, output_video_path)
        return False

    if not has_audio or duration_sec <= 0:
        print("❌ No audio found in video. Skipping silence killer.")
        shutil.copy2(input_video_path, output_video_path)
        return False

    # 2. Extract 16kHz mono audio via FFmpeg in < 1 second (no MoviePy overhead)
    temp_wav = input_video_path + "_temp_audio.wav"
    try:
        subprocess.run([
            "ffmpeg", "-y", "-nostdin",
            "-i", input_video_path,
            "-vn", "-ac", "1", "-ar", "16000",
            temp_wav
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=30)
    except Exception as e:
        log.warning(f"[SILENCE_KILLER] Audio extraction failed: {e}")
        if os.path.exists(temp_wav):
            try: os.remove(temp_wav)
            except Exception: pass
        shutil.copy2(input_video_path, output_video_path)
        return False

    # 3. Analyze audio using pydub
    try:
        pydub_audio = AudioSegment.from_wav(temp_wav)
    finally:
        if os.path.exists(temp_wav):
            try: os.remove(temp_wav)
            except Exception: pass

    # CONFIGURATION (The Magic Numbers)
    MIN_SILENCE_LEN = 500  # Only catch gaps >= 0.5s
    SILENCE_THRESH = -40   # -40 dBFS threshold
    PAD_MS = 150           # 150ms buffer to prevent clipping speech edges

    print("[SILENCE_KILLER] Analyzing audio for silent gaps...", flush=True)
    speaking_chunks = detect_nonsilent(
        pydub_audio, 
        min_silence_len=MIN_SILENCE_LEN, 
        silence_thresh=SILENCE_THRESH
    )

    if not speaking_chunks:
        print("[SILENCE_KILLER] No speaking found. Skipping.", flush=True)
        shutil.copy2(input_video_path, output_video_path)
        return False

    # 4. Apply padding and merge overlapping chunks
    video_duration_ms = duration_sec * 1000.0
    padded_chunks = []
    for start_ms, end_ms in speaking_chunks:
        s = max(0.0, float(start_ms - PAD_MS))
        e = min(video_duration_ms, float(end_ms + PAD_MS))
        if padded_chunks and s <= padded_chunks[-1][1]:
            # Merge overlapping windows
            padded_chunks[-1] = (padded_chunks[-1][0], max(padded_chunks[-1][1], e))
        else:
            padded_chunks.append((s, e))

    print(f"[SILENCE_KILLER] Cutting {len(padded_chunks)} speaking chunks and concatenating...", flush=True)
    log.info(f"[SILENCE_KILLER] Kept {len(padded_chunks)} chunks.")

    # If only 1 chunk covers essentially the whole video, skip re-render
    if len(padded_chunks) == 1 and (padded_chunks[0][1] - padded_chunks[0][0]) >= (video_duration_ms - 500.0):
        print("[SILENCE_KILLER] No significant silence found. Skipping re-render.", flush=True)
        log.info("[SILENCE_KILLER] No significant silence found, bypassing render.")
        shutil.copy2(input_video_path, output_video_path)
        return False

    # 5. Build FFmpeg filter_complex (trim + atrim + concat)
    filter_parts = []
    concat_inputs = []
    for idx, (s_ms, e_ms) in enumerate(padded_chunks):
        s_sec = s_ms / 1000.0
        e_sec = e_ms / 1000.0
        filter_parts.append(f"[0:v]trim=start={s_sec:.3f}:end={e_sec:.3f},setpts=PTS-STARTPTS[v{idx}]")
        filter_parts.append(f"[0:a]atrim=start={s_sec:.3f}:end={e_sec:.3f},asetpts=PTS-STARTPTS[a{idx}]")
        concat_inputs.append(f"[v{idx}][a{idx}]")

    filter_complex = ";".join(filter_parts) + f";{''.join(concat_inputs)}concat=n={len(padded_chunks)}:v=1:a=1[outv][outa]"

    # 6. Render with NVENC (Hardware GPU) with fallback to libx264 ultrafast
    use_nvenc = os.environ.get("HS_SILENCE_NVENC", "1").strip().lower() not in ("0", "false", "no")
    rendered_ok = False
    encoder_name = "nvenc"

    if use_nvenc:
        cmd_nvenc = [
            "ffmpeg", "-y", "-nostdin",
            "-i", input_video_path,
            "-filter_complex", filter_complex,
            "-map", "[outv]", "-map", "[outa]",
            "-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", "19", "-b:v", "0",
            "-c:a", "aac", "-b:a", "192k",
            output_video_path
        ]
        try:
            res_nvenc = subprocess.run(cmd_nvenc, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=120)
            if res_nvenc.returncode == 0 and os.path.exists(output_video_path) and os.path.getsize(output_video_path) > 1000:
                rendered_ok = True
                encoder_name = "h264_nvenc"
            else:
                log.warning(f"[SILENCE_KILLER] NVENC failed (code={res_nvenc.returncode}), trying libx264 fallback...")
        except Exception as e:
            log.warning(f"[SILENCE_KILLER] NVENC execution exception ({e}), trying libx264 fallback...")

    if not rendered_ok:
        encoder_name = "libx264_ultrafast"
        cmd_cpu = [
            "ffmpeg", "-y", "-nostdin",
            "-i", input_video_path,
            "-filter_complex", filter_complex,
            "-map", "[outv]", "-map", "[outa]",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "19",
            "-c:a", "aac", "-b:a", "192k",
            output_video_path
        ]
        try:
            res_cpu = subprocess.run(cmd_cpu, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=180)
            if res_cpu.returncode == 0 and os.path.exists(output_video_path) and os.path.getsize(output_video_path) > 1000:
                rendered_ok = True
            else:
                log.error(f"[SILENCE_KILLER] libx264 fallback also failed (code={res_cpu.returncode})")
        except Exception as e:
            log.error(f"[SILENCE_KILLER] libx264 fallback exception: {e}")

    if not rendered_ok:
        shutil.copy2(input_video_path, output_video_path)
        return False

    t_total = time.perf_counter() - t_start
    print(f"[SILENCE_KILLER] Viral Cut Ready! encoder={encoder_name} wall_s={t_total:.2f}s chunks={len(padded_chunks)}", flush=True)
    log.info(f"[SILENCE_KILLER] Completed via {encoder_name} in {t_total:.2f}s (chunks={len(padded_chunks)})")
    return True
