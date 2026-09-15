import json
import sys
import os
import re

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import utils.payoff_engine as pe

# Patch the _has_any and _count_markers functions to use regex
def _has_any(text, markers):
    t = pe._normalize_text(text)
    return any(re.search(rf"\b{re.escape(m)}\b", t) for m in markers)

def _count_markers(text, markers):
    t = pe._normalize_text(text)
    return sum(1 for m in markers if re.search(rf"\b{re.escape(m)}\b", t))

pe._has_any = _has_any
pe._count_markers = _count_markers

with open('mock_transcript.json', 'r') as f:
    transcript = json.load(f)

hook = transcript[4]
thread = {
    "trace_id": "test",
    "hook_text": hook["text"],
    "start_s": hook["start"],
}

engine = pe.PayoffEngine()
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

print("--- AFTER WORD BOUNDARY FIX ---")
for s in spans:
    score = engine._score_span(s, thread, hook, promise_frame)
    print(f"\n{s['name']}: {s['text']}")
    print(f"final_score: {score.final_score:.3f}")
