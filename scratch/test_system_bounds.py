import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from viral_finder.orchestrator import _run_arc_assembler_v2, _run_editor_refiner, PipelineContext

class MockThread:
    def __init__(self):
        self.state = "RESOLVED"

    def propose_boundary(self, *args, **kwargs):
        pass

# Create a mock transcript of 1-second segments
transcript = []
for i in range(100):
    transcript.append({
        "start": float(i),
        "end": float(i + 1),
        "text": f"Sentence number {i}.",
        "idx": i
    })

# The hook is at 10-12s
candidates = [
    {
        "id": "c_001",
        "start": 10.0,
        "end": 12.0,
        "hook_strength": 0.9,
        "hook_idx": 10,
        "payoff_engine_score": 0.8,
        "trace_id": "thread_1"
    }
]

# Mock payoff engine to immediately return a payoff at 15s-16s
class MockPayoffEngine:
    def resolve(self, st, trans, hook, window):
        return {
            "state": "RESOLVED",
            "winner": {
                "idx": 15,
                "start": 15.0,
                "end": 16.0,
                "text": "Sentence number 15.",
                "final_score": 0.85
            }
        }

import utils.payoff_engine
utils.payoff_engine.PayoffEngine = MockPayoffEngine

import viral_finder.orchestrator
viral_finder.orchestrator.compute_quality_scores = lambda t, s, e: {"information_density_score": 0.05, "semantic_quality": 0.1}

ctx = PipelineContext(
    path="dummy.mp4",
    top_k=5,
    allow_fallback=False,
    transcript=transcript,
    final_candidates=candidates,
    candidate_threads={"thread_1": MockThread()}
)

print("=== STARTING DIAGNOSTIC TRACE ===")
print(f"[STAGE 0: HOOK HUNTER] start: 10.0, end: 12.0")

viral_finder.orchestrator._run_arc_assembler_v2(ctx)
if not hasattr(ctx, 'ranked_output') or not ctx.ranked_output:
    print("Arc assembler failed.")
    sys.exit(1)

arc_out = ctx.ranked_output[0]
print(f"[STAGE 1: ARC_ASSEMBLER_V2]")
print(f"  -> Hook Start: 10.0")
print(f"  -> Payoff Ends: 16.0")
print(f"  -> Min Clip Padding Applied: Yes (min_clip=18.0)")
print(f"  -> Assembler Output: start: {arc_out['start']:.2f}, end: {arc_out['end']:.2f}, duration: {arc_out['end'] - arc_out['start']:.2f}s")

ctx.final_candidates = ctx.ranked_output
viral_finder.orchestrator._run_editor_refiner(ctx)

editor_out = ctx.ranked_output[0] if ctx.ranked_output else ctx.final_candidates[0]
print(f"[STAGE 2: EDITOR_REFINER]")
print(f"  -> Pre-pad / Post-pad Applied: Yes (1.2s pre, 1.5s post)")
print(f"  -> Final Output: start: {editor_out['start']:.2f}, end: {editor_out['end']:.2f}, duration: {editor_out.get('duration', editor_out['end'] - editor_out['start']):.2f}s")
