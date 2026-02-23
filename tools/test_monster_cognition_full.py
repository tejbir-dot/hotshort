
"""
GRAND MASTER MONSTER COGNITION TEST
Tests ignition + punch + payoff from ALL human cognitive angles.
No ML. No GPU. Fully deterministic.
"""

from viral_finder.idea_graph import (
    analyze_curiosity_and_detect_punches
)

# -----------------------------
# Helper to build fake transcript
# -----------------------------
def seg(t, s, e):
    return {"text": t, "start": s, "end": e}

# -----------------------------
# TEST CASES (Human Psychology)
# -----------------------------
TEST_CASES = [
    {
        "name": "🔥 PERFECT VIRAL",
        "expected": "PASS",
        "segments": [
            seg("Why most people fail at building wealth?", 0, 2),
            seg("Because they focus on income, not leverage.", 2, 5),
            seg("Let me show you the exact framework.", 5, 8),
            seg("This is how I built my first million.", 8, 12),
        ]
    },
    {
        "name": "❌ CLICKBAIT NO PAYOFF",
        "expected": "REJECT",
        "segments": [
            seg("You won't believe this secret!", 0, 2),
            seg("People are shocked by this.", 2, 4),
            seg("This changes everything.", 4, 7),
            seg("Anyway let's move on.", 7, 10),
        ]
    },
    {
        "name": "😴 BORING INFORMATION",
        "expected": "REJECT",
        "segments": [
            seg("Today I will explain the history of banking.", 0, 3),
            seg("Banks were created in the 15th century.", 3, 7),
            seg("They evolved slowly over time.", 7, 11),
        ]
    },
    {
        "name": "🧨 LATE PUNCH (BAD HOOK)",
        "expected": "REJECT",
        "segments": [
            seg("So today we are talking about mindset.", 0, 3),
            seg("Mindset is important in life.", 3, 7),
            seg("Most people never realize this.", 7, 11),
            seg("Here is the shocking truth about money.", 11, 15),
        ]
    },
    {
        "name": "⚠️ FALSE REPETITION",
        "expected": "REJECT",
        "segments": [
            seg("You need discipline to succeed.", 0, 3),
            seg("You need discipline to succeed.", 3, 6),
            seg("You need discipline to succeed.", 6, 9),
        ]
    },
    {
        "name": "⚡ FAST SHOCK VALUE",
        "expected": "PASS",
        "segments": [
            seg("I lost everything at 19.", 0, 2),
            seg("Then I discovered one brutal truth.", 2, 4),
            seg("Money follows leverage, not effort.", 4, 7),
        ]
    },
]

# -----------------------------
# RUN TESTS
# -----------------------------
print("\n========== MONSTER COGNITION FULL TEST ==========\n")

passed = 0

for tc in TEST_CASES:
    print(f"TEST CASE: {tc['name']}")
    feats, curiosity, candidates = analyze_curiosity_and_detect_punches(
        tc["segments"],
        brain=None,   # force fallback path
        window=3
    )

    decision = "PASS" if candidates else "REJECT"
    correct = decision == tc["expected"]

    if correct:
        passed += 1

    print(f"  DETECTED       : {decision}")
    print(f"  EXPECTED       : {tc['expected']}")
    print(f"  RESULT         : {'✅ CORRECT' if correct else '❌ WRONG'}")

    if candidates:
        top = candidates[0][2]
        print(f"  PAYOFF TIME    : {round(top.get('payoff_time', -1), 2)}")
        print(f"  CONFIDENCE     : {round(top.get('payoff_confidence', 0.0), 3)}")

    print("-" * 60)

print(f"\nSUMMARY: {passed}/{len(TEST_CASES)} PASSED")
print("\n========== TEST COMPLETE ==========\n")
