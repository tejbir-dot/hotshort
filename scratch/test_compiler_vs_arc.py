import os
import sys
import logging
import time

# Ensure import paths
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from viral_finder.narrative_compiler import NarrativeContract, CompilerConfig, CompilationContext, compile_narrative
from utils.payoff_resolver import PayoffResolver

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Test")

def main():
    print("=" * 60)
    print("A/B TEST: NARRATIVE COMPILER vs ARC ASSEMBLER")
    print("=" * 60)
    
    # 1. Mock Transcript
    # 10 segments, each 1 second long
    transcript = []
    text_parts = [
        "So", "let", "me", "tell", "you",
        "why", "this", "is", "so", "important."
    ]
    for i, w in enumerate(text_parts):
        transcript.append({
            "idx": i,
            "start": float(i),
            "end": float(i + 1),
            "text": w
        })

    hook_idx = 2  # "me"
    surgeon_target_idx = 8  # "so" (Groq Surgeon says payoff is exactly here)
    
    # 2. Mock Groq Surgeon Contract
    print(f"\n[GROQ SURGEON DECISION]")
    print(f"Hook Index: {hook_idx} ('{text_parts[hook_idx]}')")
    print(f"Target Payoff Index: {surgeon_target_idx} ('{text_parts[surgeon_target_idx]}')")
    
    contract = NarrativeContract(
        hook_idx=hook_idx,
        payoff_idx=surgeon_target_idx,
        decision="KEEP",
        confidence=0.95,
        story_complete=True,
        expected_duration=6.0,
        reason="Surgeon determined the true ending is at 'so'."
    )
    
    print("\n" + "=" * 60)
    print("RUNNING PATH A: NARRATIVE COMPILER")
    print("=" * 60)
    
    comp_ctx = CompilationContext(
        transcript=transcript,
        config=CompilerConfig(),
        logger=logger,
        clock_start_time=time.perf_counter()
    )
    
    result = compile_narrative(contract, comp_ctx)
    if result.success:
        print(f"Compiler Result Payoff Index: {result.clip.payoff_idx}")
        print(f"Compiler Exact Payoff Text: {result.clip.payoff_text}")
        print(f"Compiler Final End Time: {result.clip.end}s")
        if result.clip.payoff_idx == surgeon_target_idx:
            print("[SUCCESS] Narrative Compiler strictly respected the Groq Surgeon's contract!")
    
    print("\n" + "=" * 60)
    print("RUNNING PATH B: LEGACY ARC ASSEMBLER (PayoffResolver fallback)")
    print("=" * 60)
    
    resolver = PayoffResolver()
    arc_candidate_window = transcript[hook_idx:]
    
    res_seg = resolver.find(
        hook_text=transcript[hook_idx]["text"],
        hook_start_s=transcript[hook_idx]["start"],
        candidate_window=arc_candidate_window,
        full_transcript=transcript,
        thread_id="test_thread",
        run_tier3=True
    )
    
    if res_seg:
        arc_payoff_idx = res_seg.get("idx")
        arc_text = res_seg.get("text")
        print(f"Arc Assembler Selected Payoff Index: {arc_payoff_idx}")
        print(f"Arc Assembler Exact Payoff Text: {arc_text}")
        print(f"Arc Assembler Final End Time: {res_seg.get('end')}s")
        
        if arc_payoff_idx != surgeon_target_idx:
            print("[MUTATION DETECTED] Arc Assembler ignored the Surgeon and guessed randomly based on embeddings/heuristics.")
    else:
        print("Arc Assembler failed to find a payoff in this mock.")
    
    print("\n" + "=" * 60)

if __name__ == "__main__":
    main()
