import json
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import utils.payoff_engine as pe

with open('mock_transcript.json', 'r') as f:
    transcript = json.load(f)

hook = transcript[4]
thread = {
    "trace_id": "test",
    "hook_text": hook["text"],
    "start_s": hook["start"],
}

hook_end = hook["end"]
arc_end_cap = hook_end + 90.0
candidate_window = [
    s for s in transcript
    if (s.get("start", 0) >= hook_end + 5.0) and (s.get("end", 0) <= arc_end_cap)
]

engine = pe.PayoffEngine()
result = engine.resolve(thread, transcript, hook, candidate_window)

print("TOP CANDIDATES:")
for c in result.get("top_candidates", []):
    print(f"[{c['start']}-{c['end']}] Score: {c['final_score']:.3f} | Text: {c['text']}")
