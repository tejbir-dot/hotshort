import os
import sys
import json
import logging
from collections import defaultdict

os.environ['HS_TRACE_MODE'] = 'true'
sys.path.insert(0, r"c:\Users\n\Documents\hotshort")

from viral_finder import orchestrator
from viral_finder.pipeline_context import PipelineContext
from utils.narrative_intelligence import StoryThread, infer_narrative_promise_and_debt, build_contract
from utils.payoff_engine import PayoffEngine
from utils.payoff_resolver import PayoffResolver

logging.basicConfig(level=logging.ERROR)

def run_deep_audit():
    print("[1/4] Loading transcript...")
    TRANSCRIPT_PATH = r"c:\Users\n\Documents\hotshort\.hotshort_transcripts_cache\17391602f63bf04260926df9bdf4e0330c24060b.json"
    with open(TRANSCRIPT_PATH, "r", encoding="utf-8") as f:
        transcript = json.load(f)

    print("[2/4] Running global hook hunter...")
    ctx = PipelineContext(path="dummy.mp4", top_k=20, allow_fallback=False)
    ctx.transcript = transcript
    orchestrator._run_global_hook_hunter(ctx)

    threads = list(ctx.candidate_threads.values())
    print(f"      Found {len(threads)} hook threads.")

    engine = PayoffEngine()
    resolver = PayoffResolver()

    results_md = []
    results_md.append("# Deep Audit: Payoff Resolution Pipeline\n")
    results_md.append("This report traces the exact dual-path logic currently active in `orchestrator.py` across real hooks.\n\n")

    tier_stats = defaultdict(int)
    durations = []

    print("[3/4] Running exact orchestrator resolution logic...")
    for i, thread in enumerate(threads):
        sys.stdout.write(f"\r      Processing hook {i+1}/{len(threads)}...")
        sys.stdout.flush()
        
        # Ensure contract is built
        if not thread.promise:
            p, d, pt = infer_narrative_promise_and_debt(thread.hook_text)
            thread.promise = p
            thread.narrative_debt = d
            thread.promise_type = pt
            thread.contract = build_contract(pt, thread.hook_text)

        hook_idx = thread.start_idx
        arc_start = thread.start_s
        max_clip = 90.0

        # Build candidate window exactly like orchestrator
        candidate_window = []
        for tmp_j in range(hook_idx, len(transcript)):
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

        best_payoff = None
        source_tier = None
        engine_score = 0.0

        # --- PATH A: StoryThread-backed PayoffEngine ---
        try:
            result = engine.resolve(thread, transcript, transcript[hook_idx], candidate_window)
            if result.get("winner") and result.get("state") in ("RESOLVED", "CONTINUED"):
                best_payoff = result["winner"]
                source_tier = "Path A (PayoffEngine)"
                engine_score = best_payoff.get("final_score", 0.0)
        except Exception as e:
            pass

        # --- PATH B: Direct PayoffResolver (Fallback) ---
        if best_payoff is None:
            try:
                resolver_seg = resolver.find(
                    hook_text=thread.hook_text,
                    hook_start_s=thread.start_s,
                    candidate_window=candidate_window,
                    full_transcript=list(transcript),
                    thread_id=f"audit_{i}"
                )
                if resolver_seg:
                    best_payoff = resolver_seg
                    tier = resolver_seg.get("tier", "?")
                    source_tier = f"Path B (Tier {tier})"
            except Exception as e:
                pass

        # Write to report
        results_md.append(f"## Hook {i+1}: `{thread.hook_text}`\n")
        results_md.append(f"- **Start Time**: {arc_start:.1f}s\n")
        
        if best_payoff:
            duration = best_payoff['end'] - arc_start
            durations.append(duration)
            tier_stats[source_tier] += 1
            
            results_md.append(f"- **Resolution Source**: {source_tier}\n")
            if "Path A" in source_tier:
                results_md.append(f"- **Engine Score**: {engine_score:.2f}\n")
            results_md.append(f"- **Final Duration**: {duration:.1f}s\n")
            results_md.append(f"- **Payoff Segment**: `{best_payoff['text']}`\n\n")
        else:
            tier_stats["Failed / Unresolved"] += 1
            results_md.append(f"- **Resolution Source**: FAILED\n")
            results_md.append(f"- **Final Duration**: N/A\n\n")

    print("\n[4/4] Writing report...")
    
    # Prepend Summary
    avg_dur = sum(durations) / len(durations) if durations else 0
    summary = ["## Executive Summary\n"]
    summary.append(f"- **Total Hooks Evaluated**: {len(threads)}\n")
    summary.append(f"- **Average Resolved Duration**: {avg_dur:.1f} seconds\n")
    summary.append("- **Resolution Tier Distribution**:\n")
    for tier, count in sorted(tier_stats.items()):
        summary.append(f"  - {tier}: {count} ({count/len(threads)*100:.1f}%)\n")
    summary.append("\n---\n\n")
    
    final_md = "".join(summary) + "".join(results_md)
    
    out_path = r"c:\Users\n\.gemini\antigravity-ide\brain\6fad6c37-3b43-4e1f-8d4c-fea29cd28652\payoff_deep_audit.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(final_md)

    print("\n" + "="*50)
    print("AUDIT COMPLETE")
    print(f"Total Hooks Evaluated: {len(threads)}")
    print(f"Average Resolved Duration: {avg_dur:.1f} seconds")
    print("Resolution Tier Distribution:")
    for tier, count in sorted(tier_stats.items()):
        print(f"  - {tier}: {count} ({count/len(threads)*100:.1f}%)")
    print("="*50)

if __name__ == "__main__":
    run_deep_audit()
