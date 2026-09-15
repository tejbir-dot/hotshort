import os, sys, json
sys.path.insert(0, r"c:\Users\n\Documents\hotshort")
os.environ["HS_TRACE_MODE"] = "true"
os.environ["HS_HOOK_HUNTER_DEBUG"] = "1"
os.environ["HS_EXPERIMENT_MODE"] = "1"

from viral_finder import orchestrator
from viral_finder.pipeline_context import PipelineContext

TRANSCRIPT_PATH = r"c:\Users\n\Documents\hotshort\.hotshort_transcripts_cache\17391602f63bf04260926df9bdf4e0330c24060b.json"
with open(TRANSCRIPT_PATH, "r", encoding="utf-8") as f:
    transcript = json.load(f)

ctx = PipelineContext(path="dummy.mp4", top_k=5, allow_fallback=True)
ctx.transcript = transcript

# Mock functions
orchestrator._load_cached_transcript = lambda _p: transcript
orchestrator._save_cached_transcript = lambda _p, _s: None
orchestrator.analyze_audio = lambda _p: [{"time": float(i*4), "energy": 0.5} for i in range(len(transcript))]
orchestrator.analyze_visual = lambda _p: [{"time": float(i*4), "motion": 0.4} for i in range(len(transcript))]

# Run Pipeline
try:
    orchestrator._run_global_hook_hunter(ctx)
    ctx.ranked_output = list(ctx.raw_candidates or [])
    orchestrator._run_arc_assembler_v2(ctx)
    
    # We must call the _pool setup from orchestrator to run Groq Surgeon
    final_candidates = ctx.ranked_output or []
    from viral_finder.groq_cortex import review_candidates_with_groq
    
    if final_candidates:
        _pool = list(final_candidates)
        groq_result = review_candidates_with_groq(_pool, transcript, ctx.candidate_threads)
    
    orchestrator._run_editor_refiner(ctx)
except Exception as e:
    import traceback
    traceback.print_exc()

print("="*60)
print("STORY THREAD AUTOPSY")
print("="*60)

with open(r"c:\Users\n\Documents\hotshort\scratch\governor_autopsy.txt", "w", encoding="utf-8") as f:
    f.write("STORY THREAD GOVERNOR AUTOPSY\n")
    f.write("="*60 + "\n")
    for tid, st in ctx.candidate_threads.items():
        # Only log interesting threads (those that Arc Assembler at least touched)
        if len(st.history) <= 1:
            continue
            
        report = f"""
THREAD: {tid}
HOOK: {st.hook_text}
DEVELOPMENT: {len(st.suppressed_children) if hasattr(st, "suppressed_children") else 0} points
PAYOFF_CANDIDATE: {st.payoff_candidate or 'None'}
RESOLUTION_SCORE: {st.resolution_score}
STATE_HISTORY: {[h.get('action') for h in st.history]}
FINAL_STATE: {st.state}
------------------------------------------------------------
"""
        print(report)
        f.write(report)
