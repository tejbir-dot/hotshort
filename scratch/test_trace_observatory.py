import os
import sys
import json
import logging

# Enable trace mode and other test configurations
os.environ['HS_ORCH_MAX_GLOBAL_HOOKS'] = '5'
os.environ['HS_HOOK_HUNTER_DEBUG'] = '1'
os.environ['HS_TRACE_MODE'] = 'true'
os.environ['HS_GROQ_CORTEX'] = '0' # Disabling groq api queries for unit test speed

sys.path.insert(0, ".")

logging.basicConfig(level=logging.INFO, format="%(message)s")

from viral_finder.orchestrator import orchestrate

print("=" * 60)
print("RUNNING END-TO-END PIPELINE WITH TRACE MODE")
print("=" * 60)

transcript_path = r"c:\Users\n\Documents\hotshort\.hotshort_transcripts_cache\17391602f63bf04260926df9bdf4e0330c24060b.json"

res = orchestrate(
    transcript_path,
    top_k=3,
    prefer_gpu=False,
    use_cache=True,
    allow_fallback=True
)
