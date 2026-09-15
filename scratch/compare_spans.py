import json
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.payoff_engine import PayoffEngine

with open('mock_transcript.json', 'r') as f:
    transcript = json.load(f)

hook = transcript[4] # "But what if... what if we could break free?"
thread = {
    "trace_id": "test",
    "hook_text": hook["text"],
    "start_s": hook["start"],
}

engine = PayoffEngine()
promise_frame = engine._make_promise_frame(thread, hook)

spans = [
    {
        "name": "Build-up",
        "text": "During final testing, we found something. An anomaly.",
        "start": 45.0,
        "end": 48.5,
        "idxs": [14, 15],
    },
    {
        "name": "Actual Payoff",
        "text": "The Quantum Core... it's... sentient. It's not just a machine. It's alive.",
        "start": 50.0,
        "end": 56.0,
        "idxs": [16, 17],
    },
    {
        "name": "Closure",
        "text": "This changes everything. Everything.",
        "start": 62.0,
        "end": 64.0,
        "idxs": [19],
    }
]

print("--- BEFORE FIX ---")
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
    # compute penalty if delta < 35
    delta = s["start"] - hook["start"]
    penalty = 0.0
    if delta < 35:
        penalty = 0.60 * (1.0 - (delta / 35.0))
    print(f"timing penalty: -{penalty:.3f}")
