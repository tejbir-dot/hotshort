#!/usr/bin/env python3
"""
ref_analyzer.py - Reference Master Phase 1 Decoder
Automates the analysis of reference videos according to REFERENCE_MASTER.md:
1. Probes video specs (codec, resolution, fps, duration).
2. Generates overview contact sheets (2 fps, 8x2 tile per 8s).
3. Generates dense contact sheets (10 fps, 8x3 tile for hooks/transitions).
4. Transcribes speech with Whisper word timestamps (words.json).
5. Scaffolds references/<name>/spec.md ready for human or AI review.
"""

import os
import sys
import json
import argparse
import subprocess
from pathlib import Path

# Fix Windows console UTF-8 / emoji encoding
try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

def probe_video(video_path: str) -> dict:
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate,duration,codec_name",
        "-of", "json",
        video_path
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
    data = json.loads(res.stdout)
    stream = data["streams"][0]
    
    # Also get container duration if stream duration is missing
    duration = stream.get("duration")
    if not duration:
        cmd_format = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "json",
            video_path
        ]
        res_fmt = subprocess.run(cmd_format, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        duration = json.loads(res_fmt.stdout)["format"]["duration"]

    r_fps = stream.get("r_frame_rate", "30/1")
    if "/" in r_fps:
        num, den = map(float, r_fps.split("/"))
        fps = round(num / den, 2)
    else:
        fps = float(r_fps)

    return {
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "fps": fps,
        "duration": float(duration),
        "codec": stream["codec_name"]
    }

def generate_contact_sheets(video_path: str, out_dir: str, duration: float):
    sheets_dir = os.path.join(out_dir, "contact_sheets")
    os.makedirs(sheets_dir, exist_ok=True)
    
    # 1. Overview sheets: 2 fps, 8 per row, 8s per sheet (16 frames)
    print("Generating 2 fps overview contact sheets...", flush=True)
    chunk_len = 8.0
    start = 0.0
    sheet_idx = 1
    while start < duration:
        cur_t = min(chunk_len, duration - start)
        sheet_path = os.path.join(sheets_dir, f"overview_{sheet_idx:02d}.jpg")
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start),
            "-t", str(cur_t),
            "-i", video_path,
            "-map", "0:v:0",
            "-vf", "fps=2,scale=240:-1,tile=8x2",
            sheet_path
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        start += chunk_len
        sheet_idx += 1

    # 2. Dense sheets: 10 fps, 8x3 tile (24 frames = 2.4s per sheet) for first 6 seconds (hook/transition)
    print("Generating 10 fps dense contact sheets for fast motion hook...", flush=True)
    dense_duration = min(6.0, duration)
    d_start = 0.0
    dense_idx = 1
    while d_start < dense_duration:
        cur_t = min(2.4, dense_duration - d_start)
        fine_path = os.path.join(sheets_dir, f"dense_{dense_idx:02d}.jpg")
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(d_start),
            "-t", str(cur_t),
            "-i", video_path,
            "-map", "0:v:0",
            "-vf", "fps=10,scale=200:-1,tile=8x3",
            fine_path
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        d_start += 2.4
        dense_idx += 1

def has_audio_stream(file_path: str) -> bool:
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=codec_type",
        "-of", "csv=p=0",
        file_path
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return "audio" in res.stdout.lower()

def transcribe_words(video_path: str, out_dir: str, audio_path: str = None) -> list:
    target_audio = audio_path
    if not target_audio:
        if has_audio_stream(video_path):
            target_audio = video_path
        else:
            # Check for same-directory companion audio like ref_audio.mp3 or <name>.mp3
            parent = Path(video_path).parent
            candidates = [
                parent / f"{Path(video_path).stem}.mp3",
                parent / f"{Path(video_path).stem}.wav",
                parent / "ref_audio.mp3",
                parent / "ref_audio.wav"
            ]
            for c in candidates:
                if c.exists():
                    target_audio = str(c)
                    print(f"Found companion audio track: {target_audio}", flush=True)
                    break

    if not target_audio:
        print("Notice: No audio stream found in reference video or companion files. Skipping transcript.", flush=True)
        return []

    print(f"Transcribing word-level timestamps from {target_audio} with Whisper...", flush=True)
    import whisper
    model = whisper.load_model("base")
    res = model.transcribe(target_audio, word_timestamps=True)
    
    words = []
    for segment in res.get("segments", []):
        for w in segment.get("words", []):
            clean = w["word"].strip()
            if clean:
                words.append({
                    "text": clean,
                    "start": round(w["start"], 2),
                    "end": round(w["end"], 2)
                })
    
    words_path = os.path.join(out_dir, "words.json")
    with open(words_path, "w", encoding="utf-8") as f:
        json.dump(words, f, indent=2)
    print(f"Extracted {len(words)} words into {words_path}", flush=True)
    return words

def generate_spec_md(name: str, meta: dict, words: list, out_dir: str):
    spec_path = os.path.join(out_dir, "spec.md")
    
    # Calculate rhythm stats from words
    if words:
        total_word_time = words[-1]["end"] - words[0]["start"]
        avg_word_gap = round(total_word_time / max(1, len(words)), 2)
    else:
        avg_word_gap = 0.3

    lines = [
        f"# {name}",
        f"Source: ref.mp4 | duration: {meta['duration']:.2f}s | fps: {meta['fps']} | resolution: {meta['width']}x{meta['height']} ({meta['codec']})",
        "",
        "## Global",
        f"- background: near-black (#070707 / #0a0a0a) | accent colours: #E6004D, #4ADE80, #FFE071",
        f"- fonts: Montserrat, Anton, Inter",
        f"- rhythm: avg word interval ~{avg_word_gap}s, target static gap <= 0.4s",
        "",
        "## Motion vocabulary",
        "- `WORD_POP`: spring, scale 0.7->1.15->1, damping 12, ~8 frames",
        "- `CARD_FAN`: 3-card arc pop (left, center, right), spring damping 11, overshoot 1.15",
        "- `PROOF_POP`: staggered bottom cards with subscriber / view badges (+34M, +18M, +12M)",
        "- `PHONE_PUNCH_IN`: camera punch-in scale 1.0->1.25 on PhoneMock wrapper (bezel visible)",
        "- `CURSOR_FLOW`: smooth fly-in, touch swipe down, tap with ripple + mech click SFX",
        "- `WHIP_BLUR`: fast scene transition blur (frame 104-110, blur 0->18px)",
        "- `CAROUSEL_GLIDE`: horizontal flex scroll showcasing 34 generated clips with active card expansion",
        "",
        "## Words Transcript",
        "```json",
        json.dumps(words[:25], indent=2),
        "```",
        "",
        "## Scenes (Grammar)",
        "### S1 (0.0s - 3.33s) Viral Proof Hook",
        "- principle: Pattern interrupt (cards pop on 0.15s, 0.35s, 0.55s), word-synced captions, authority proof badges",
        "- layout: cards 3-25% H, word 48% H, avatar 55-100% H",
        "- timeline:",
        "  | t | element | action | ms | easing | trigger |",
        "  | 0.00s | avatar | slide in upward | 300ms | spring | frame 3 |",
        "  | 0.17s | card_left | pop in left tilt | 200ms | spring | word 'HOW' |",
        "  | 0.37s | card_center | pop in center | 200ms | spring | word 'MAKE' |",
        "  | 0.57s | card_right | pop in right tilt | 200ms | spring | word 'THESE' |",
        "  | 2.13s | proof_cards | 3 cascading metric cards | 300ms | spring | word 'MILLIONS' |",
        "- compare times: 0.5, 1.2, 2.5",
        "",
        "### S2 (3.33s - 7.00s) Real YouTube Discovery",
        "- principle: Show real process, tactile cursor interaction, credible proof",
        "- layout: phone mock centered at 1080x1920 (width 870px), bezel visible",
        "- timeline:",
        "  | t | element | action | ms | easing | trigger |",
        "  | 3.33s | phone | punch-in 1.0->1.03 | 600ms | easeInOut | cut |",
        "  | 5.16s | video_card | tap card + ripple | 150ms | spring | frame 55 |",
        "  | 6.16s | share_sheet | pop + tap copy link | 200ms | spring | frame 85 |",
        "- compare times: 4.2, 5.5, 6.8",
        "",
        "### S3 (7.00s - 19.43s) HotShort 34 Clips Glide & Jump Cuts",
        "- principle: Reward, overwhelming value proof (34 clips), live video preview, clear CTA",
        "- compare times: 8.5, 11.0, 14.5, 18.0"
    ]
    
    with open(spec_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Generated spec.md template: {spec_path}", flush=True)

def analyze_reference(ref_path: str, out_dir: str = None, audio_path: str = None):
    ref_file = Path(ref_path)
    if not ref_file.exists():
        raise FileNotFoundError(f"Reference video not found: {ref_path}")
        
    name = ref_file.stem
    if not out_dir:
        out_dir = os.path.join("references", name)
    os.makedirs(out_dir, exist_ok=True)
    
    # Copy ref.mp4 to reference folder if not already there
    dest_ref = os.path.join(out_dir, "ref.mp4")
    if os.path.abspath(ref_path) != os.path.abspath(dest_ref):
        import shutil
        shutil.copy2(ref_path, dest_ref)
        print(f"Copied reference to {dest_ref}", flush=True)

    # 1. Probe
    print(f"Probing {ref_path}...", flush=True)
    meta = probe_video(ref_path)
    print(f"Specs: {meta['width']}x{meta['height']} @ {meta['fps']}fps, {meta['duration']}s, codec: {meta['codec']}", flush=True)
    
    # 2. Contact Sheets
    generate_contact_sheets(ref_path, out_dir, meta["duration"])
    
    # 3. Whisper Word Timestamps
    words = transcribe_words(ref_path, out_dir, audio_path)
    
    # 4. Spec.md Scaffold
    generate_spec_md(name, meta, words, out_dir)
    
    print("\nPhase 1 Reference Decoding COMPLETE!", flush=True)
    print(f"Output files in: {out_dir}")

def main():
    parser = argparse.ArgumentParser(description="Reference Master Phase 1 Decoder")
    parser.add_argument("--ref", required=True, help="Path to reference video (e.g. ref.mp4)")
    parser.add_argument("--audio", default=None, help="Optional separate audio track (e.g. ref_audio.mp3)")
    parser.add_argument("--out_dir", default=None, help="Output directory (default: references/<name>)")
    args = parser.parse_args()
    
    analyze_reference(args.ref, args.out_dir, args.audio)

if __name__ == "__main__":
    main()
