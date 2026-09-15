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
    {"name": "A", "text": "During testing we found an anomaly.", "start": 30.0, "end": 35.0, "idxs": [0]},
    {"name": "B", "text": "The Quantum Core is sentient.", "start": 40.0, "end": 45.0, "idxs": [1]},
    {"name": "C", "text": "This changes everything.", "start": 50.0, "end": 55.0, "idxs": [2]},
]

print("--- COMPONENT SCORES ---")
for s in spans:
    score = engine._score_span(s, thread, hook, promise_frame)
    print(f"\n{s['name']}: {s['text']}")
    print(f"promise_match: {score.promise_match:.3f}")
    print(f"debt_match: {score.debt_match:.3f}")
    print(f"development_alignment: {score.development_alignment:.3f}")
    print(f"specificity: {score.specificity:.3f}")
    print(f"closure: {score.closure:.3f}")
    print(f"finality: {score.finality:.3f}")
    print(f"emotional_release: {score.emotional_release:.3f}")
    print(f"boundary_crispness: {score.boundary_crispness:.3f}")
    print(f"final_score: {score.final_score:.3f}")
