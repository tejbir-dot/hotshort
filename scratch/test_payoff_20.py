import os, sys, json, logging
os.environ['HS_TRACE_MODE'] = 'true'
sys.path.insert(0, ".")

from viral_finder import orchestrator
from viral_finder.pipeline_context import PipelineContext
from utils.narrative_intelligence import StoryThread, infer_narrative_promise_and_debt
from utils.payoff_engine import PayoffEngine

logging.basicConfig(level=logging.ERROR)

TRANSCRIPT_PATH = r"c:\Users\n\Documents\hotshort\.hotshort_transcripts_cache\17391602f63bf04260926df9bdf4e0330c24060b.json"

with open(TRANSCRIPT_PATH, "r", encoding="utf-8") as f:
    transcript = json.load(f)

# Find top hooks using the global hook hunter
ctx = PipelineContext(path="dummy.mp4", top_k=8, allow_fallback=False)
ctx.transcript = transcript
orchestrator._run_global_hook_hunter(ctx)

# Get the threads created
threads = list(ctx.candidate_threads.values())
print(f"Found {len(threads)} hook threads.")

engine = PayoffEngine()
results_md = []

results_md.append("# 20 Hooks Payoff Engine Experiment\n")
results_md.append("This report contains the raw Governor Narrative Reports for the top 20 hooks in the transcript. We are inspecting whether the engine is finding **real resolutions** or just **topically related sentences**.\n\n")

for i, thread in enumerate(threads[:20]):
    # Re-infer just to be sure
    from utils.narrative_intelligence import build_contract
    promise, debt, promise_type = infer_narrative_promise_and_debt(thread.hook_text)
    thread.promise = promise
    thread.narrative_debt = debt
    thread.promise_type = promise_type
    thread.contract = build_contract(promise_type, thread.hook_text)
    
    hook_idx = thread.start_idx
    arc_start = thread.start_s
    max_clip = 120.0
    
    candidate_window = []
    for tmp_j in range(hook_idx + 1, len(transcript)):
        tmp_seg_s = transcript[tmp_j].get("start", 0.0)
        tmp_seg_e = transcript[tmp_j].get("end", 0.0)
        if (tmp_seg_e - arc_start) > max_clip:
            break
        candidate_window.append({
            "idx": tmp_j,
            "start": tmp_seg_s,
            "end": tmp_seg_e,
            "text": str(transcript[tmp_j].get("text", ""))
        })
        
    result = engine.resolve(thread, transcript, transcript[hook_idx], candidate_window)
    
    results_md.append(f"## Hook {i+1}\n")
    results_md.append(f"**Hook**: `{thread.hook_text}`\n")
    results_md.append(f"**Promise Type**: {thread.promise_type}\n")
    results_md.append(f"**Promise**: {thread.promise}\n")
    results_md.append(f"**Debt**: {thread.narrative_debt}\n\n")
    
    results_md.append("### Top 5 Candidates\n")
    for p in result.get("top_candidates", []):
        results_md.append(f"- **[{p['final_score']:.2f}]** {p['text']}  \n")
        results_md.append(f"  *(debt: {p['debt_match']:.2f}, spec: {p['specificity']:.2f}, clos: {p['closure']:.2f})*\n")
        
    winner = result.get("winner")
    if winner:
        results_md.append(f"\n**WINNING PAYOFF**: `{winner['text']}`\n")
    else:
        results_md.append(f"\n**WINNING PAYOFF**: NONE\n")
        
    results_md.append("---\n")

with open(r"c:\Users\n\.gemini\antigravity\brain\06f8ddcc-84b1-4d3f-9876-3ffc37904e15\experiment_results.md", "w", encoding="utf-8") as f:
    f.write("".join(results_md))
print("Done writing experiment_results.md")
