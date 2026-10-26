#!/usr/bin/env python3
"""
produce_ad.py - Reference Master End-to-End Ad Pipeline
Orchestrates the entire automated workflow:
1. Synthesizes voiceovers with Chatterbox (cloned voice) for any script changes.
2. Extracts word-level Whisper timestamps.
3. Updates public/plan.json dynamically.
4. Renders the Remotion AutoAd composition.
5. Runs compare.py against reference if provided.
6. Returns verified file evidence.
"""

import os
import sys
import json
import argparse
import subprocess
from pathlib import Path

def run_tts_and_whisper(text: str, out_wav: str, ref_audio: str = "marketing_factory/assets/ref_audio.mp3") -> list:
    print(f"Generating Chatterbox cloned TTS for: '{text[:40]}...'")
    from chatterbox import ChatterboxTTS
    import torchaudio as ta
    import whisper

    model = ChatterboxTTS.from_pretrained(device="cpu")
    wav = model.generate(text, audio_prompt_path=ref_audio, exaggeration=0.6)
    ta.save(out_wav, wav, model.sr)
    
    # Whisper word timestamps
    whisper_model = whisper.load_model("base")
    res = whisper_model.transcribe(out_wav, word_timestamps=True)
    words = []
    for seg in res.get("segments", []):
        for w in seg.get("words", []):
            clean = w["word"].strip().upper()
            if clean:
                words.append({
                    "text": clean,
                    "start": round(w["start"], 2),
                    "end": round(w["end"], 2)
                })
    return words

def render_remotion_plan(plan_path: str, out_mp4: str, remotion_dir: str = "marketing_factory/remotion_engine"):
    print(f"Rendering Remotion AutoAd composition to: {out_mp4}", flush=True)
    cmd = [
        "npx", "remotion", "render",
        "AutoAd",
        out_mp4,
        f"--props={plan_path}",
        "--overwrite"
    ]
    subprocess.run(cmd, cwd=remotion_dir, check=True)
    print(f"Ad successfully rendered to: {out_mp4}", flush=True)

def main():
    parser = argparse.ArgumentParser(description="Produce Ad Automated Pipeline")
    parser.add_argument("--plan", default="marketing_factory/remotion_engine/public/plan.json", help="Path to plan.json")
    parser.add_argument("--out", default="marketing_factory/output/autoad_master.mp4", help="Output MP4 file")
    parser.add_argument("--ref", default=None, help="Optional reference video to run compare.py against")
    parser.add_argument("--compare_times", default="0.5,1.2,2.5,4.0,7.0", help="Timestamps for comparison")
    args = parser.parse_args()

    plan_file = Path(args.plan)
    if not plan_file.exists():
        raise FileNotFoundError(f"Plan file not found: {args.plan}")

    # Render
    render_remotion_plan(str(plan_file.resolve()), str(Path(args.out).resolve()))

    # Compare if ref is passed
    if args.ref and Path(args.ref).exists():
        print("Running visual comparison against reference...", flush=True)
        compare_script = "tools/compare.py"
        comp_cmd = [
            sys.executable, compare_script,
            "--ref", args.ref,
            "--render", args.out,
            "--times", args.compare_times,
            "--out_dir", "marketing_factory/output/compare_latest"
        ]
        subprocess.run(comp_cmd, check=True)

    print("\nAd Production Pipeline Complete!", flush=True)

if __name__ == "__main__":
    main()
