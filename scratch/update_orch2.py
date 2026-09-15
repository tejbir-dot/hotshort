import sys

with open('c:/Users/n/Documents/hotshort/viral_finder/orchestrator.py', 'r', encoding='utf-8') as f:
    code = f.read()

# Replace the loop to include EDITOR_REFINER
old_arc = '''                if ctx and hasattr(ctx, "candidate_threads") and tid in ctx.candidate_threads:
                    st = ctx.candidate_threads[tid]
                    arc_props = st.proposals.get("ARC_ASSEMBLER", [])
                    for prop in arc_props:
                        if prop.get("type") == "boundary":
                            lineage.trace_change(
                                cid, 
                                "ARC_ASSEMBLER", 
                                {"start": prop["before"]["start"], "end": prop["before"]["end"], "text": "..."}, 
                                {"start": prop["after"]["start"], "end": prop["after"]["end"], "text": c.get("text", "")}, 
                                prop.get("reason", "arc_assemble")
                            )'''

new_arc = '''                if ctx and hasattr(ctx, "candidate_threads") and tid in ctx.candidate_threads:
                    st = ctx.candidate_threads[tid]
                    for stage_name in ["ARC_ASSEMBLER", "EDITOR_REFINER"]:
                        for prop in st.proposals.get(stage_name, []):
                            if prop.get("type") == "boundary":
                                lineage.trace_change(
                                    cid, 
                                    stage_name, 
                                    {"start": prop["before"]["start"], "end": prop["before"]["end"], "text": "..."}, 
                                    {"start": prop["after"]["start"], "end": prop["after"]["end"], "text": "..."}, 
                                    prop.get("reason", stage_name)
                                )'''

code = code.replace(old_arc, new_arc)

with open('c:/Users/n/Documents/hotshort/viral_finder/orchestrator.py', 'w', encoding='utf-8') as f:
    f.write(code)
print('Phase 3 updates applied.')
