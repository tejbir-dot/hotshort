import json
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.payoff_engine import PayoffEngine

with open('mock_transcript.json', 'r') as f:
    transcript = json.load(f)

# Hook: "But what if... what if we could break free?" (start 12.5)
hook = transcript[4]

# Create thread
thread = {
    "trace_id": "test_thread",
    "hook_text": hook["text"],
    "start_s": hook["start"],
}

hook_end = hook["end"]
arc_end_cap = hook_end + 90.0
candidate_window = [
    s for s in transcript
    if (s.get("start", 0) >= hook_end + 5.0) and (s.get("end", 0) <= arc_end_cap)
]

engine = PayoffEngine()
result = engine.resolve(thread, transcript, hook, candidate_window)

print("HOOK:", hook["text"])
print("CANDIDATE WINDOW START/END:", candidate_window[0]["start"], "to", candidate_window[-1]["end"])
print("CANDIDATE WINDOW TRANSCRIPT:")
for c in candidate_window:
    print(f"[{c['start']}-{c['end']}] {c['text']}")

print("\nACTUAL TRANSCRIPT AFTER CANDIDATE_WINDOW:")
after = [s for s in transcript if s.get("start", 0) >= candidate_window[-1]["end"]]
if not after:
    print("(None)")
else:
    for a in after:
         print(f"[{a['start']}-{a['end']}] {a['text']}")

print("\nRESULT STATE:", result.get("state"))
print("WINNER SCORE:", result.get("resolution_score"))
print("WINNER TEXT:", result.get("winner", {}).get("text") if result.get("winner") else "None")
