import sys
import re

with open('c:/Users/n/Documents/hotshort/viral_finder/orchestrator.py', 'r', encoding='utf-8') as f:
    code = f.read()

# Replace everything from "# GOVERNOR TELEMETRY BLOCK (PHASE 1)" down to "return final_candidates"
start_idx = code.find('    # -------------------------------------------------------------------------\n    # GOVERNOR TELEMETRY BLOCK (PHASE 1)')
end_idx = code.find('    return final_candidates')

if start_idx != -1 and end_idx != -1:
    new_end_block = '''    # -------------------------------------------------------------------------
    # FLIGHT RECORDER EXPORT
    # -------------------------------------------------------------------------
    trace_dir = lineage.export_traces(final_clips_count=len(final_candidates))
    
    print(f"\\nPIPELINE COMPLETE: job={lineage.job_id}\\n")
    print(f"clips_final={len(final_candidates)}")
    print(f"candidates_total={len(lineage.candidates)}")
    print(f"mutations={lineage.mutations_count}")
    print(f"ownership_transfers={lineage.ownership_transfers_count}")
    print(f"discarded_changes={lineage.discarded_changes_count}\\n")
    print(f"trace_report={trace_dir}/index.html\\n")
    
'''
    
    code = code[:start_idx] + new_end_block + code[end_idx:]

with open('c:/Users/n/Documents/hotshort/viral_finder/orchestrator.py', 'w', encoding='utf-8') as f:
    f.write(code)
print('Phase 4 updates applied.')
