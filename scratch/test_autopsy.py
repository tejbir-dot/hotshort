import os
import sys
import json
import logging

os.environ['HS_ORCH_MAX_GLOBAL_HOOKS'] = '100'
os.environ['HS_HOOK_HUNTER_DEBUG'] = '1'
os.environ['HS_TRACE_MODE'] = 'true'

sys.path.insert(0, ".")

logging.basicConfig(level=logging.INFO, format="%(message)s")

from viral_finder.orchestrator import _run_global_hook_hunter, PipelineContext

print("=" * 60)
print("REAL TRANSCRIPT AUTOPSY")
print("=" * 60)

transcript_path = r"c:\Users\n\Documents\hotshort\.hotshort_transcripts_cache\17391602f63bf04260926df9bdf4e0330c24060b.json"

with open(transcript_path, "r", encoding="utf-8") as f:
    transcript = json.load(f)

ctx = PipelineContext(
    path="mock.mp4",
    top_k=5,
    allow_fallback=False,
    transcript=transcript,
    raw_candidates=[]
)

# Run the updated Hook Hunter
_run_global_hook_hunter(ctx)

print("\n" + "=" * 60)
print(f"Total Candidates Generated: {len(ctx.raw_candidates)}")
print("Candidates Details:")
for idx, c in enumerate(ctx.raw_candidates):
    print(f"\n[C_{idx}] Start: {c['start']:.1f}s | Score: {c['score']}")
    print(f"Hook: {c['text']}")

print("\n" + "=" * 60)
print("Candidates between 520s and 560s:")
for idx, c in enumerate(ctx.raw_candidates):
    if 520 <= c['start'] <= 560:
        print(f"Start: {c['start']:.1f}s | Score: {c['score']} | Hook: {c['text']}")

