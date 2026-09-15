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

print("AFTER FIX WINNER:")
winner = result.get("winner")
if winner:
    print(f"Text: {winner['text']}")
    print(f"Score: {winner['final_score']}")
else:
    print("None")
