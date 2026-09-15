import sys

with open('c:/Users/n/Documents/hotshort/viral_finder/orchestrator.py', 'r', encoding='utf-8') as f:
    code = f.read()

# EXTEND RIGHT
old_ext = '''                                                from viral_finder.system_observer import get_observer
                                                try:
                                                    get_observer().modify_candidate(cid, "surgeon_cortex", {"end": max(old_end, new_end), "text": fc["text"]})
                                                except Exception:
                                                    pass
                                                break'''

new_ext = '''                                                from viral_finder.system_observer import get_observer
                                                try:
                                                    get_observer().modify_candidate(cid, "surgeon_cortex", {"end": max(old_end, new_end), "text": fc["text"]})
                                                except Exception:
                                                    pass
                                                lineage.trace_change(cid, "GROQ_SURGEON", {"end": old_end, "text": old_text}, {"end": max(old_end, new_end), "text": fc["text"]}, "EXTEND_RIGHT")
                                                break'''

code = code.replace(old_ext, new_ext)

# MOVE HOOK
old_move = '''                                                from viral_finder.system_observer import get_observer
                                                try:
                                                    get_observer().modify_candidate(cid, "surgeon_cortex", {"start": new_start, "text": fc["text"]})
                                                except Exception:
                                                    pass
                                                break'''

new_move = '''                                                from viral_finder.system_observer import get_observer
                                                try:
                                                    get_observer().modify_candidate(cid, "surgeon_cortex", {"start": new_start, "text": fc["text"]})
                                                except Exception:
                                                    pass
                                                lineage.trace_change(cid, "GROQ_SURGEON", {"start": old_start, "text": old_text}, {"start": new_start, "text": fc["text"]}, "MOVE_HOOK")
                                                break'''

code = code.replace(old_move, new_move)

# Attempt repair
old_repair = '''                repaired["groq_surgeon"]["repair_applied"] = True
                kept_candidates.append(repaired)
                repaired_count += 1
                log.info(f"[SURGEON_REPAIR] SUCCESS: Replaced cid={c.get('id')} with repaired candidate.")'''

new_repair = '''                repaired["groq_surgeon"]["repair_applied"] = True
                kept_candidates.append(repaired)
                repaired_count += 1
                log.info(f"[SURGEON_REPAIR] SUCCESS: Replaced cid={c.get('id')} with repaired candidate.")
                lineage.trace_change(c.get("cid", c.get("id")), "GROQ_SURGEON_REPAIR", {"start": c.get("start"), "end": c.get("end"), "text": c.get("text")}, {"start": repaired.get("start"), "end": repaired.get("end"), "text": repaired.get("text")}, f"attempt_repair({rej_type})")'''

code = code.replace(old_repair, new_repair)

with open('c:/Users/n/Documents/hotshort/viral_finder/orchestrator.py', 'w', encoding='utf-8') as f:
    f.write(code)
print('Phase 2 updates applied.')
