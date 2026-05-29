import os
import logging
from dotenv import load_dotenv
load_dotenv()

# Set up logging to stdout
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# Ensure Groq is enabled and fail-open/log reasoning are set
os.environ["HS_GROQ_CORTEX_ENABLED"] = "1"
os.environ["HS_GROQ_LOG_REASONING"] = "1"
# Ensure we don't use PYTEST env var so it runs
if "PYTEST_CURRENT_TEST" in os.environ:
    del os.environ["PYTEST_CURRENT_TEST"]

from viral_finder.groq_cortex import review_candidates_with_groq

candidates = [
    {
        "id": "c0",
        "start": 10.0,
        "end": 45.0,
        "duration": 35.0,
        "text": "And that is why building a startup is so hard. You spend 3 months polishing a product that nobody wants because you didn't do customer development. Customer development is the single most important thing. If you don't talk to customers, you are building in a vacuum.",
        "viral_score": 0.85,
        "reason": "validation"
    },
    {
        "id": "c1",
        "start": 50.0,
        "end": 75.0,
        "duration": 25.0,
        "text": "Yeah, I mean, it's just some basic code. We wrote a React app and put a Node backend on it. Nothing special.",
        "viral_score": 0.35,
        "reason": "backfill"
    },
    {
        "id": "c2",
        "start": 80.0,
        "end": 115.0,
        "duration": 35.0,
        "text": "Here's the contrarian take: raising venture capital is actually a disadvantage for 90% of SaaS companies. When you raise VC, you are forced to go for a 10x exit or die. But if you bootstrap, you can build a highly profitable $5M/year business that you own 100% of.",
        "viral_score": 0.78,
        "reason": "validation"
    }
]

res = review_candidates_with_groq(candidates)
print("\n--- RESULTS ---")
print(f"Total returned: {len(res)}")
for i, r in enumerate(res):
    print(f"\nClip {i}:")
    print(f"  Title: {r.get('title')}")
    print(f"  Score: {r.get('viral_score')}")
    print(f"  Cortex Score: {r.get('cortex_score')}")
    print(f"  Archetype: {r.get('clip_archetype')}")
    print(f"  Start: {r.get('start')} (orig: {candidates[int(r['id'][1:])]['start']})")
    print(f"  End: {r.get('end')} (orig: {candidates[int(r['id'][1:])]['end']})")
