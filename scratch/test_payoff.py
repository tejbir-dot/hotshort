import os, sys, json, logging
os.environ['HS_TRACE_MODE'] = 'true'
sys.path.insert(0, ".")

from viral_finder import orchestrator
from viral_finder.pipeline_context import PipelineContext
import logging

logging.basicConfig(level=logging.INFO)

TRANSCRIPT_PATH = r"c:\Users\n\Documents\hotshort\.hotshort_transcripts_cache\17391602f63bf04260926df9bdf4e0330c24060b.json"

with open(TRANSCRIPT_PATH, "r", encoding="utf-8") as f:
    transcript = json.load(f)

print(f"Loaded transcript with {len(transcript)} segments.")

# Find the hook segment
hook_text_ref = "one thing that actually matters"
hook_idx = None
for i, seg in enumerate(transcript):
    if "one thing" in seg.get("text", "").lower() and "matters" in seg.get("text", "").lower():
        print(f"Found hook at {seg['start']}s: {seg['text']}")
        hook_idx = i
        break

if hook_idx is None:
    print("Could not find the specific hook.")
    sys.exit(1)

# We will manually create the StoryThread and run the PayoffEngine directly to isolate the test
from utils.narrative_intelligence import StoryThread, infer_narrative_promise_and_debt

seg = transcript[hook_idx]
hook_text = seg.get("text", "")
start_s = seg.get("start", 0.0)

thread = StoryThread(hook_text, start_s, hook_idx, trace_id="test_thread")
promise, debt = infer_narrative_promise_and_debt(hook_text)
thread.promise = promise
thread.narrative_debt = debt

# Candidate window
candidate_window = []
arc_start = start_s
max_clip = 120.0 # Let's give it a generous window

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

print(f"Running PayoffEngine over {len(candidate_window)} candidate segments...")

from utils.payoff_engine import PayoffEngine
engine = PayoffEngine()

result = engine.resolve(thread, transcript, transcript[hook_idx], candidate_window)

print("\n=================================================")
print("GOVERNOR NARRATIVE REPORT")
print("=========================")
print(f"HOOK: {thread.hook_text}")
print(f"PROMISE: {thread.promise}")
print(f"DEBT: {thread.narrative_debt}")
print("TOP 5 PAYOFFS:")
for p in result.get("top_candidates", []):
    print(f" - [{p['final_score']:.2f}] {p['text']} (debt: {p['debt_match']:.2f}, spec: {p['specificity']:.2f}, clos: {p['closure']:.2f}, emo: {p['emotional_release']:.2f}, fin: {p['finality']:.2f})")

winner = result.get("winner")
if winner:
    print(f"WINNING PAYOFF: [{winner['start']}s] {winner['text']}")
    print(f"WHY IT WON: Highest resolution score ({winner['final_score']:.2f})")
else:
    print("WINNING PAYOFF: NONE")
    
print("=================================================\n")
