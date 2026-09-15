import sys

with open('c:/Users/n/Documents/hotshort/viral_finder/orchestrator.py', 'r', encoding='utf-8') as f:
    code = f.read()

# Fix 1: EXTEND_RIGHT loop
old_fc1 = '''                                        for fc in final_candidates:
                                            if fc.get("cid") == cid and cid != "?":
                                                fc["end"] = max(old_end, new_end)'''

new_fc1 = '''                                        for fc in final_candidates:
                                            if fc.get("cid", fc.get("id", "?")) == cid and cid != "?":
                                                fc["end"] = max(old_end, new_end)'''

code = code.replace(old_fc1, new_fc1)

# Fix 2: MOVE_HOOK loop
old_fc2 = '''                                        for fc in final_candidates:
                                            if fc.get("cid") == cid and cid != "?":
                                                fc["start"] = new_start'''

new_fc2 = '''                                        for fc in final_candidates:
                                            if fc.get("cid", fc.get("id", "?")) == cid and cid != "?":
                                                fc["start"] = new_start'''

code = code.replace(old_fc2, new_fc2)

with open('c:/Users/n/Documents/hotshort/viral_finder/orchestrator.py', 'w', encoding='utf-8') as f:
    f.write(code)
print('CID mapping fixed.')
