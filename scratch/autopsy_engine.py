import sys
sys.path.insert(0, "..")
from utils.payoff_engine import PayoffEngine, infer_narrative_promise_and_debt

# Mock a thread and segments
hook_text = "If you want to make real money, these are the four things you need."
promise, debt, promise_type = infer_narrative_promise_and_debt(hook_text)
print(f"Hook: {hook_text}")
print(f"Type: {promise_type}")
print(f"Promise: {promise}")
print(f"Debt: {debt}\n")

candidates = [
    {"start": 10.0, "end": 12.0, "text": "First, you need to track your time.", "idx": 1},
    {"start": 12.0, "end": 15.0, "text": "Second, remove distractions completely.", "idx": 2},
    {"start": 15.0, "end": 18.0, "text": "Third, focus on the single bottleneck.", "idx": 3},
    {"start": 18.0, "end": 22.0, "text": "Fourth, act like the person you want to be.", "idx": 4},
    {"start": 22.0, "end": 26.0, "text": "And that is how you actually build wealth. Period.", "idx": 5},
]

engine = PayoffEngine()
thread = {"hook_text": hook_text}
result = engine.resolve(thread, candidates, {"text": hook_text, "start": 0.0}, candidates)

print("STATE:", result["state"])
if result["winner"]:
    print("WINNER SCORE:", result["winner"]["final_score"])
    print("WINNER REASON:", result["winner"]["rationale"])
print("\nTop Candidates Rejected:")
for c in result.get("top_candidates", []):
    print(f"Text: {c['text']}")
    print(f"Debt Match: {c['debt_match']}")
    print(f"Rejected: {c.get('rejection_reason')}")
    print(f"Rationale: {c['rationale']}")
    print("---")
