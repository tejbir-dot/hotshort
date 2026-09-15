import re
import copy

with open("viral_finder/orchestrator.py", "r", encoding="utf-8") as f:
    code = f.read()

# 1. Uncage V2 (we will just regex replace inside V2)
v2_idx = code.find("def _run_arc_assembler_v2")
v2_code = code[v2_idx:]
legacy_code = code[:v2_idx]

# Uncage min_clip
v2_code = v2_code.replace("min_clip = 15.0", "min_clip = 5.0")

# Remove 50s cap
v2_code = re.sub(
    r'if payoff_resolution > 0\.6:\s*if max_clip != 50\.0:\s*import logging\s*logging\.getLogger\("orchestrator"\)\.info\([^)]+\)\s*max_clip = 50\.0',
    '',
    v2_code,
    flags=re.MULTILINE
)

# Remove 6s build gate
v2_code = re.sub(
    r'if build_duration < 6\.0:\s*if \(ending_strength > 0\.3\) or \(payoff_resolution > 0\.35\) or punch:\s*import logging\s*logging\.getLogger\("orchestrator"\)\.info\([^)]+\)\s*j \+= 1\s*continue',
    '',
    v2_code,
    flags=re.MULTILINE
)

code = legacy_code + v2_code

# 2. Add experiment mode logic in orchestrator
# In ultron_engine, find: _run_arc_assembler(ctx)
engine_idx = code.find("def ultron_engine")
if engine_idx != -1:
    old_call = "    _run_arc_assembler(ctx)"
    new_call = """
    if os.environ.get("HS_EXPERIMENT_MODE") == "1":
        import copy
        ctx_legacy = copy.deepcopy(ctx)
        ctx_v2 = copy.deepcopy(ctx)
        
        _run_arc_assembler(ctx_legacy)
        _run_arc_assembler_v2(ctx_v2)
        
        # EXPERIMENT_COMPARE Telemetry
        legacy_arcs = {c.get("cid", c.get("id", "")): c for c in ctx_legacy.final_candidates or []}
        v2_arcs = {c.get("cid", c.get("id", "")): c for c in ctx_v2.final_candidates or []}
        
        all_cids = set(list(legacy_arcs.keys()) + list(v2_arcs.keys()))
        for cid in all_cids:
            old_c = legacy_arcs.get(cid)
            new_c = v2_arcs.get(cid)
            if old_c and new_c:
                old_text = str(old_c.get("text", "")).replace("\\n", " ")
                new_text = str(new_c.get("text", "")).replace("\\n", " ")
                
                old_dur = float(old_c.get("end", 0.0)) - float(old_c.get("start", 0.0))
                new_dur = float(new_c.get("end", 0.0)) - float(new_c.get("start", 0.0))
                
                old_score = float(old_c.get("arc_score", 0.0))
                new_score = float(new_c.get("arc_score", 0.0))
                
                log.info(f"\\n[EXPERIMENT_COMPARE] candidate_id={cid}")
                log.info(f"OLD_PAYOFF: \\"{old_text[:60]}...\\"")
                log.info(f"NEW_PAYOFF: \\"{new_text[:60]}...\\"")
                log.info(f"OLD_DURATION: {old_dur:.1f}s")
                log.info(f"NEW_DURATION: {new_dur:.1f}s")
                log.info(f"OLD_SCORE: {old_score:.3f}")
                log.info(f"NEW_SCORE: {new_score:.3f}\\n")
                
        ctx.final_candidates = ctx_legacy.final_candidates
        ctx.ranked_output = ctx_legacy.ranked_output
    else:
        _run_arc_assembler(ctx)
"""
    code = code.replace(old_call, new_call)

with open("viral_finder/orchestrator.py", "w", encoding="utf-8") as f:
    f.write(code)
