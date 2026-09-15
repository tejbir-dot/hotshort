import os, sys, json
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ['HS_TRACE_MODE'] = 'true'

TRANSCRIPT_PATH = r"c:\Users\n\Documents\hotshort\.hotshort_transcripts_cache\17391602f63bf04260926df9bdf4e0330c24060b.json"
with open(TRANSCRIPT_PATH, "r", encoding="utf-8") as f:
    TRANSCRIPT = json.load(f)

from viral_finder import orchestrator

# Suppress annoying logging during the run
logging.getLogger().setLevel(logging.ERROR)

class DummyContext:
    def __init__(self):
        self.transcript = TRANSCRIPT
        self.raw_candidates = []
        self.hooks_suppressed = 0
        self.candidate_feature_cache = {}
        self.trace_logs = {}
        self.candidate_threads = {}
        self.curiosity_curve = []
        self.stage_stats = {}
        self.hooks_discovered = 0
        
        self.suppressed_hooks = []

    def trace_state(self, *args, **kwargs): pass
    def trace_event(self, *args, **kwargs): pass
    def trace_suppressed_child(self, trace_id, start, text, score, reason):
        self.suppressed_hooks.append({
            "trace_id": trace_id,
            "start": start,
            "text": text,
            "score": score,
            "reason": reason
        })

def run_trace():
    print("=============================================================")
    print("   PRODUCTION FORENSIC TRACE: tpDE0RJ7yoM (dummy.mp4)        ")
    print("=============================================================")
    
    ctx = DummyContext()
    
    # We must patch get_feature_cache because it might call heavy ML models
    def mock_get_feature_cache(*args, **kwargs):
        pass
    
    # Wait, we want REAL scores. orchestrator.compute_quality_scores uses cache if we just let it run.
    # It might take a moment to compute if not cached. 
    # run_pipeline_test.py took only 1-2 seconds, meaning the transcript cache has semantic scores, 
    # and the basic scores are fast to compute. We don't need to mock it!
    
    orchestrator._run_global_hook_hunter(ctx)
    
    # Now we have ctx.raw_candidates (Injected) and ctx.suppressed_hooks (Suppressed)
    
    print("\n--- INJECTED CANDIDATES (SURVIVED) ---")
    injected_by_strength = sorted(ctx.raw_candidates, key=lambda x: x.get("hook_strength", 0), reverse=True)
    for c in injected_by_strength:
        print(f"Timestamp: {c['start']:>6.1f}s | Strength: {c.get('hook_strength', 0):.2f} | Final injected? Yes")
        
    print("\n--- SUPPRESSED CANDIDATES (KILLED BY STORYTHREAD) ---")
    suppressed_by_strength = sorted(ctx.suppressed_hooks, key=lambda x: x["score"], reverse=True)
    for c in suppressed_by_strength:
        print(f"Timestamp: {c['start']:>6.1f}s | Strength: {c['score']:.2f} | StoryThread ID: {c['trace_id'][:8]}... | Suppressed? Yes | Reason: {c['reason']}")
    
    highest_injected = injected_by_strength[0] if injected_by_strength else None
    highest_suppressed = suppressed_by_strength[0] if suppressed_by_strength else None
    
    print("\n=============================================================")
    print("                    FORENSIC VERDICT                         ")
    print("=============================================================")
    print(f"Was the highest hook_strength candidate suppressed?")
    
    if highest_suppressed and highest_injected and highest_suppressed["score"] > highest_injected.get("hook_strength", 0):
        print("YES.")
        print(f"- Highest surviving hook:  Strength {highest_injected.get('hook_strength', 0):.2f} at {highest_injected['start']}s")
        print(f"- Highest suppressed hook: Strength {highest_suppressed['score']:.2f} at {highest_suppressed['start']}s")
        diff = highest_suppressed["score"] - highest_injected.get("hook_strength", 0)
        print(f"- Difference in strength:  +{diff:.2f}")
        print(f"- Which StoryThread suppressed it: Thread {highest_suppressed['trace_id']}")
        print(f"- Which line of code made the decision: orchestrator.py, line 2312 (the 'continue' after logging suppression)")
    else:
        print("NO.")
        if highest_injected:
            print(f"Highest surviving hook was {highest_injected.get('hook_strength', 0):.2f}")
        if highest_suppressed:
            print(f"Highest suppressed hook was {highest_suppressed['score']:.2f}")

if __name__ == "__main__":
    run_trace()
