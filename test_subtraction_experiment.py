import os
import time
from unittest.mock import patch

os.environ["HS_GROQ_NARRATIVE_ROLES"] = "1"
os.environ["HS_GROQ_TRANSCRIPT_FIRST"] = "0"
os.environ["HS_GROQ_CORTEX_ENABLED"] = "0"
os.environ["HS_EXPERIMENT_MODE"] = "0"

import viral_finder.orchestrator as orch

DUMMY_TRANSCRIPT = [
    {"start": i*5.0, "end": (i+1)*5.0, "text": f"This is segment {i} of the podcast.", "words": []} 
    for i in range(60)
]

def mock_transcription(ctx):
    ctx.transcript = DUMMY_TRANSCRIPT
    ctx.transcript_source = "mock"

def mock_av_features(ctx):
    ctx.audio_features = [0.0] * len(DUMMY_TRANSCRIPT)
    ctx.visual_features = [0.0] * len(DUMMY_TRANSCRIPT)

def mock_curiosity(ctx):
    ctx.curiosity_curve = [0.5] * len(DUMMY_TRANSCRIPT)
    ctx.curiosity_candidates = [
        {"start": 10.0, "end": 20.0, "score": 0.8},
        {"start": 30.0, "end": 45.0, "score": 0.9}
    ]
    ctx.curiosity = {"curve": ctx.curiosity_curve, "candidates": ctx.curiosity_candidates}

# Mock out Groq latency to prove it costs time
def mock_analyze_narrative_roles(transcript):
    time.sleep(2.0)
    return {i: "HOOK" if i % 5 == 0 else ("PAYOFF" if i % 5 == 4 else "BUILD") for i in range(len(transcript))}

def run_experiment():
    print("=======================================")
    print(" EXPERIMENT A: GROQ NARRATIVE ROLES")
    print("=======================================")

    with patch('viral_finder.orchestrator._run_transcription', side_effect=mock_transcription), \
         patch('viral_finder.orchestrator._run_av_features', side_effect=mock_av_features), \
         patch('viral_finder.orchestrator._run_curiosity', side_effect=mock_curiosity), \
         patch('viral_finder.groq_cortex.analyze_narrative_roles', side_effect=mock_analyze_narrative_roles):
        
        # RUN 1: Baseline (Subtraction OFF)
        os.environ["HS_SUBTRACTION_MODE"] = "0"
        t0 = time.time()
        res_before = orch.orchestrate("fake_path.mp4", use_cache=False)
        time_before = time.time() - t0
        clips_before = res_before
        
        print(f"\n[BASELINE]")
        print(f"Runtime: {time_before:.2f}s")
        print(f"Clips Generated: {len(clips_before)}")
        
        # RUN 2: Subtraction ON
        os.environ["HS_SUBTRACTION_MODE"] = "1"
        t0 = time.time()
        res_after = orch.orchestrate("fake_path.mp4", use_cache=False)
        time_after = time.time() - t0
        clips_after = res_after
        
        print(f"\n[SUBTRACTION MODE]")
        print(f"Runtime: {time_after:.2f}s")
        print(f"Clips Generated: {len(clips_after)}")
        
        print("\n=======================================")
        print(" CONCLUSION")
        print("=======================================")
        clips_match = len(clips_before) == len(clips_after)
        for i in range(min(len(clips_before), len(clips_after))):
            c1 = clips_before[i]
            c2 = clips_after[i]
            if c1.get("start") != c2.get("start") or c1.get("end") != c2.get("end"):
                clips_match = False
                break

        if clips_match and time_after < time_before:
            print("[SUCCESS] EXACT SAME CLIPS")
            print(f"[SUCCESS] FASTER RUNTIME (Saved {time_before - time_after:.2f}s)")
            print("\nVERDICT: DELETE IT")
        else:
            print("[FAIL] DIFFERENCE DETECTED. DO NOT DELETE.")
            print(f"Clips Match: {clips_match}")

if __name__ == '__main__':
    run_experiment()
