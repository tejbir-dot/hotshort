import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from viral_finder.orchestrator import _run_global_hook_hunter
from utils.narrative_intelligence import StoryThread

class DummyContext:
    def __init__(self):
        self.transcript = [
            {"start": 0.0, "end": 2.0, "text": "This is a random intro that nobody cares about."},
            {"start": 10.0, "end": 12.0, "text": "What if I told you that the secret to wealth is simple?", "semantic_quality": 0.9},
            {"start": 14.0, "end": 16.0, "text": "It's so simple that billionaires use this one hidden trick every single day to multiply their money.", "semantic_quality": 0.95},
            {"start": 20.0, "end": 22.0, "text": "And today I'm going to reveal exactly how they do it.", "semantic_quality": 0.8},
            {"start": 60.0, "end": 62.0, "text": "Another completely different topic is how to build muscle fast.", "semantic_quality": 0.8}
        ]
        self.raw_candidates = []
        self.hooks_suppressed = 0
        self.candidate_feature_cache = {}
        self.trace_logs = {}
        self.candidate_threads = {}
        self.curiosity_curve = []
    
    def trace_state(self, *args, **kwargs): pass
    def trace_event(self, *args, **kwargs): pass
    def trace_suppressed_child(self, *args, **kwargs): pass

def run_experiment():
    print("="*60)
    print("FORENSIC EXPERIMENT: HOOK HUNTER WITH VS WITHOUT STORY THREAD")
    print("="*60)
    
    # We will patch orchestrator's _StoryThread behavior.
    import viral_finder.orchestrator as orch
    
    # We also need to mock compute_quality_scores to return predictable scores
    def mock_scores(transcript, start, end):
        if start == 10.0: return {"hook_score": 0.50, "pattern_break_score": 0.50} # Decent hook
        if start == 14.0: return {"hook_score": 0.99, "pattern_break_score": 0.90} # AMAZING hook
        if start == 60.0: return {"hook_score": 0.70, "pattern_break_score": 0.60} # Good hook
        return {"hook_score": 0.1, "pattern_break_score": 0.1}
        
    orch.compute_quality_scores = mock_scores
    # Patch env variables
    os.environ["HS_TRACE_MODE"] = "false"
    
    # First: WITH StoryThread (The Buggy System)
    ctx_with = DummyContext()
    print("\n[RUNNING WITH STORY THREAD]")
    _run_global_hook_hunter(ctx_with)
    
    print("\nRESULTS WITH STORY THREAD:")
    for i, h in enumerate(ctx_with.raw_candidates):
        print(f"  Candidate {i+1}: Start={h['start']}s, Strength={h.get('hook_strength', 0):.2f}, Text='{h['text'][:40]}...'")
    print(f"  Hooks Suppressed: {ctx_with.hooks_suppressed}")
    
    # Second: WITHOUT StoryThread (The Revert)
    orch._StoryThread = None
    ctx_without = DummyContext()
    print("\n[RUNNING WITHOUT STORY THREAD]")
    _run_global_hook_hunter(ctx_without)
    
    print("\nRESULTS WITHOUT STORY THREAD:")
    for i, h in enumerate(ctx_without.raw_candidates):
        print(f"  Candidate {i+1}: Start={h['start']}s, Strength={h.get('hook_strength', 0):.2f}, Text='{h['text'][:40]}...'")
    print(f"  Hooks Suppressed: {ctx_without.hooks_suppressed}")

if __name__ == "__main__":
    run_experiment()
