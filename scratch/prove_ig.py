import json
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import utils.payoff_engine as pe

engine = pe.PayoffEngine()
hook = {"start": 0.0, "end": 5.0, "text": "But what if... what if we could break free?"}
thread = {"trace_id": "test", "hook_text": hook["text"], "start_s": hook["start"]}
promise_frame = engine._make_promise_frame(thread, hook)

spans = [
    {"name": "During testing we found an anomaly.", "text": "During testing we found an anomaly.", "start": 45.0, "end": 50.0, "idxs": [0]},
    {"name": "The Quantum Core is sentient.", "text": "The Quantum Core is sentient.", "start": 45.0, "end": 50.0, "idxs": [1]},
]

scored_candidates = []
for s in spans:
    score = engine._score_span(s, thread, hook, promise_frame)
    score.information_gain = pe._measure_information_gain(score.text, hook["text"])
    scored_candidates.append(score)

# Apply winner selection sort
scored_candidates.sort(key=lambda c: (round(c.final_score, 2), c.information_gain, c.boundary_crispness), reverse=True)

print("--- NEW RANKING (WITH INFORMATION GAIN) ---")
for i, c in enumerate(scored_candidates):
    print(f"{i+1}. {c.text}")
    print(f"   Information Gain: {c.information_gain:.3f}")
    print(f"   Structural Score (Rounded): {round(c.final_score, 2):.3f} (Exact: {c.final_score:.3f})")
    print(f"   Boundary Crispness: {c.boundary_crispness:.3f}")
