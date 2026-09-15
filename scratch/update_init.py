import sys

with open('c:/Users/n/Documents/hotshort/viral_finder/orchestrator.py', 'r', encoding='utf-8') as f:
    code = f.read()

old_init_block = '''            # --- FLIGHT RECORDER INITIALIZATION ---
            for c in final_candidates:
                cid = c.get("cid", c.get("id", "?"))
                lineage.init_candidate(cid, {"start": c.get("start"), "end": c.get("end"), "text": c.get("text", "")}, "CANDIDATE_GENERATION")
                
                # Trace ARC Assembler
                tid = c.get("trace_id", c.get("id"))
                if ctx and hasattr(ctx, "candidate_threads") and tid in ctx.candidate_threads:
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

new_init_block = '''            # --- FLIGHT RECORDER INITIALIZATION ---
            for c in final_candidates:
                cid = c.get("cid", c.get("id", "?"))
                tid = c.get("trace_id", c.get("id"))
                
                orig_start = c.get("start")
                orig_end = c.get("end")
                orig_text = "..."
                
                # Find the true original boundaries before Arc Assembler
                if ctx and hasattr(ctx, "candidate_threads") and tid in ctx.candidate_threads:
                    st = ctx.candidate_threads[tid]
                    arc_props = st.proposals.get("ARC_ASSEMBLER", [])
                    if arc_props:
                        first_prop = arc_props[0]
                        if first_prop.get("type") == "boundary":
                            orig_start = first_prop["before"]["start"]
                            orig_end = first_prop["before"]["end"]
                            orig_text = "(raw hook fragment)"
                            
                lineage.init_candidate(cid, {"start": orig_start, "end": orig_end, "text": orig_text}, "CANDIDATE_GENERATION")
                
                # Trace ARC Assembler & Editor Refiner
                if ctx and hasattr(ctx, "candidate_threads") and tid in ctx.candidate_threads:
                    st = ctx.candidate_threads[tid]
                    for stage_name in ["ARC_ASSEMBLER", "EDITOR_REFINER"]:
                        for prop in st.proposals.get(stage_name, []):
                            if prop.get("type") == "boundary":
                                lineage.trace_change(
                                    cid, 
                                    stage_name, 
                                    {"start": prop["before"]["start"], "end": prop["before"]["end"], "text": "..."}, 
                                    {"start": prop["after"]["start"], "end": prop["after"]["end"], "text": c.get("text", "") if stage_name == "EDITOR_REFINER" else "(assembled arc text)"}, 
                                    prop.get("reason", stage_name)
                                )'''

code = code.replace(old_init_block, new_init_block)

with open('c:/Users/n/Documents/hotshort/viral_finder/orchestrator.py', 'w', encoding='utf-8') as f:
    f.write(code)
print('Orchestrator true-initialization fixed.')
