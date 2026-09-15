import json
import sys
import os
import re

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import utils.payoff_engine as pe
import utils.payoff_resolver as pr

with open('mock_transcript.json', 'r') as f:
    transcript = json.load(f)

hook = transcript[4]
hook_start = hook["start"]

spans = [
    {
        "name": "Build-up",
        "text": "During final testing, we found something. An anomaly.",
        "idx": 14,
    },
    {
        "name": "Actual Payoff",
        "text": "The Quantum Core... it's... sentient.",
        "idx": 16,
    },
    {
        "name": "Closure",
        "text": "This changes everything. Everything.",
        "idx": 19,
    }
]

print("--- PAYOFF RESOLVER SCORES ---")
for s in spans:
    t1 = pr.tier1_structural_score(transcript, s["idx"], hook_start)
    t2 = pr.tier2_embedding_score(hook["text"], s["text"], t1)
    print(f"\n{s['name']}: {s['text']}")
    print(f"Tier 1: {t1:.3f}")
    print(f"Tier 2: {t2:.3f}")
