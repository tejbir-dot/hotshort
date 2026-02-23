# tools/test_monster_cognition_master.py

from viral_finder.idea_graph import analyze_curiosity_and_detect_punches

def run_test(name, segments, expected):
    print(f"\nTEST CASE: {name}")
    feats, curiosity, candidates = analyze_curiosity_and_detect_punches(
        segments,
        aud=None,
        vis=None,
        brain=None
    )

    if not candidates:
        print("❌ No candidates detected")
        decision = "REJECT"
    else:
        best = max(candidates, key=lambda x: x[2].get("curiosity_peak", 0))
        meta = best[2]
        decision = "PASS" if meta.get("payoff_confidence", 0) >= 0.6 else "REJECT"

        print("Ignition start:", meta["start_time"])
        print("Payoff time   :", meta["payoff_time"])
        print("Confidence    :", meta["payoff_confidence"])

    print("DECISION :", decision, "| EXPECTED:", expected)
    print("RESULT   :", "✅ CORRECT" if decision == expected else "❌ WRONG")

# --------------------------------------------------
# TEST CASES
# --------------------------------------------------

TESTS = [

    # 1. PERFECT VIRAL
    (
        "🔥 PERFECT VIRAL",
        [
            {"start":0,"end":1,"text":"Wait."},
            {"start":1,"end":3,"text":"This almost destroyed my entire career."},
            {"start":3,"end":6,"text":"Most people make this mistake without realizing it."},
            {"start":6,"end":9,"text":"Here’s how to avoid it forever."}
        ],
        "PASS"
    ),

    # 2. CLICKBAIT NO PAYOFF
    (
        "❌ CLICKBAIT NO PAYOFF",
        [
            {"start":0,"end":2,"text":"This will change your life."},
            {"start":2,"end":6,"text":"So yeah, consistency matters."}
        ],
        "REJECT"
    ),

    # 3. BORING INFORMATION
    (
        "😴 BORING INFORMATION",
        [
            {"start":0,"end":3,"text":"Today we will discuss market fundamentals."},
            {"start":3,"end":8,"text":"There are many factors involved."}
        ],
        "REJECT"
    ),

    # 4. LATE PUNCH (BAD HOOK)
    (
        "🧨 LATE PUNCH",
        [
            {"start":0,"end":6,"text":"Let me give you some background first."},
            {"start":6,"end":9,"text":"Actually, everything you know is wrong."}
        ],
        "REJECT"
    ),

    # 5. QUIET BUT DEADLY
    (
        "🤫 QUIET BUT DEADLY",
        [
            {"start":0,"end":2,"text":"I shouldn’t say this…"},
            {"start":2,"end":5,"text":"but most financial advice is lying to you."}
        ],
        "PASS"
    ),

    # 6. PLATEAU (NO DOPAMINE SHIFT)
    (
        "📉 PLATEAU",
        [
            {"start":0,"end":3,"text":"This is important."},
            {"start":3,"end":6,"text":"This is also important."}
        ],
        "REJECT"
    ),

    # 7. MULTIPLE IGNITIONS
    (
        "⚡ MULTIPLE IGNITIONS",
        [
            {"start":0,"end":2,"text":"Stop scrolling."},
            {"start":2,"end":4,"text":"This mistake costs people millions."},
            {"start":4,"end":7,"text":"But here’s the part nobody tells you."}
        ],
        "PASS"
    ),

    # 8. STRONG IGNITION, NO PAYOFF
    (
        "💣 IGNITION NO PAYOFF",
        [
            {"start":0,"end":3,"text":"This secret will shock you."},
            {"start":3,"end":8,"text":"Anyway, just be disciplined."}
        ],
        "REJECT"
    ),

    # 9. PAYOFF WITHOUT IGNITION
    (
        "🎯 PAYOFF WITHOUT IGNITION",
        [
            {"start":0,"end":5,"text":"Here is a complete step-by-step solution."}
        ],
        "REJECT"
    ),

    # 10. CONTRARIAN TRUTH
    (
        "🧠 CONTRARIAN TRUTH",
        [
            {"start":0,"end":2,"text":"Everyone tells you to work harder."},
            {"start":2,"end":5,"text":"That advice is exactly why you’re stuck."}
        ],
        "PASS"
    ),
]

# --------------------------------------------------
# RUN ALL
# --------------------------------------------------

print("\n========== MONSTER COGNITION MASTER TEST ==========")

for name, segs, expected in TESTS:
    run_test(name, segs, expected)

print("\n========== TEST COMPLETE ==========")
