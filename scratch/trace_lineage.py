import os, sys, json
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ['HS_TRACE_MODE'] = 'true'

import viral_finder.orchestrator as orch

def dump_candidates(candidates_list, name, c482_id=None, c0_id=None):
    if not candidates_list:
        candidates_list = []
        
    c482 = None
    c0 = None
    for c in candidates_list:
        if isinstance(c, dict):
            start = round(float(c.get("start", 0)), 1)
            cid = c.get("cid")
            if (c482_id and cid == c482_id) or (not c482_id and start == 482.1):
                c482 = c
            if (c0_id and cid == c0_id) or (not c0_id and start == 0.0):
                c0 = c
                
    def get_score(cand):
        if not cand: return "REJECTED"
        s = cand.get("arc_score") or cand.get("viral_score") or cand.get("score") or cand.get("hook_strength") or 0.0
        return f"{s:.3f}"
        
    print(f"| {name.ljust(13)} | {get_score(c482).ljust(16)} | {get_score(c0).ljust(14)} |")
    return (c482.get("cid") if c482 else c482_id), (c0.get("cid") if c0 else c0_id)


# Monkeypatch the pipeline stages
orig_hook_hunter = orch._run_global_hook_hunter
orig_semantic = orch._run_semantic_scoring
orig_enrichment = orch._run_enrichment
orig_insight = orch._run_insight_detector
orig_validation = orch._run_validation
orig_arc_assembler = orch._run_arc_assembler_v2
orig_surgeon = orch._run_groq_surgeon
orig_ranking = orch._run_ranking
orig_editor = orch._run_editor_refiner

c482_id, c0_id = None, None

def wrap_hook_hunter(ctx):
    global c482_id, c0_id
    res = orig_hook_hunter(ctx)
    print("\n| Stage         | Candidate 482.1s | Candidate 0.0s |")
    print("| ------------- | ---------------- | -------------- |")
    c482_id, c0_id = dump_candidates(ctx.raw_candidates, "Hook Hunter", c482_id, c0_id)
    return res

def wrap_semantic(ctx):
    global c482_id, c0_id
    c482_id, c0_id = dump_candidates(ctx.raw_candidates, "Assign IDs", c482_id, c0_id)
    res = orig_semantic(ctx)
    dump_candidates(ctx.raw_candidates, "Semantic", c482_id, c0_id)
    return res

def wrap_enrichment(ctx):
    res = orig_enrichment(ctx)
    dump_candidates(ctx.enriched_candidates, "Enrichment", c482_id, c0_id)
    return res

def wrap_insight(ctx):
    res = orig_insight(ctx)
    dump_candidates(ctx.enriched_candidates, "Insight", c482_id, c0_id)
    return res

def wrap_validation(ctx):
    res = orig_validation(ctx)
    dump_candidates(ctx.validated_candidates, "Validation", c482_id, c0_id)
    return res

def wrap_arc(ctx):
    res = orig_arc_assembler(ctx)
    out = ctx.ranked_output or ctx.final_candidates or []
    dump_candidates(out, "ArcAssembler", c482_id, c0_id)
    return res

def wrap_surgeon(ctx):
    res = orig_surgeon(ctx)
    out = ctx.ranked_output or ctx.final_candidates or []
    dump_candidates(out, "GroqSurgeon", c482_id, c0_id)
    return res

def wrap_ranking(ctx):
    res = orig_ranking(ctx)
    out = ctx.ranked_output or ctx.final_candidates or []
    dump_candidates(out, "Ranking", c482_id, c0_id)
    return res

def wrap_editor(ctx):
    res = orig_editor(ctx)
    out = ctx.ranked_output or ctx.final_candidates or []
    dump_candidates(out, "Editor", c482_id, c0_id)
    return res

orch._run_global_hook_hunter = wrap_hook_hunter
orch._run_semantic_scoring = wrap_semantic
orch._run_enrichment = wrap_enrichment
orch._run_insight_detector = wrap_insight
orch._run_validation = wrap_validation
orch._run_arc_assembler_v2 = wrap_arc
orch._run_groq_surgeon = wrap_surgeon
orch._run_ranking = wrap_ranking
orch._run_editor_refiner = wrap_editor


if __name__ == "__main__":
    print("Running full pipeline via orchestrate...")
    orch.orchestrate("scratch/test_vid.mp4", top_k=8, allow_fallback=False)
