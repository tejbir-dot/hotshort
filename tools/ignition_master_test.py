"""
ignition_master_tests.py

MASTER-LEVEL TEST SUITE
Levels 1 → 5 for the Ignition–Punch System

Purpose:
- Stress-test cognitive alignment between HUMAN attention and AI ignition
- Not accuracy benchmarking — alignment + failure discovery

Covers:
L1: Human vs Machine Ground Truth
L2: Quiet-but-Deadly Hooks
L3: Clickbait Immunity
L4: Contrarian Truth Detection
L5: Multi-Ignition Mapping

Usage:
    python ignition_master_tests.py

Assumes:
- ignition_deep.py is in the same directory
- You will READ outputs, not blindly trust them

"""

from viral_finder.ignition_deep import analyze_segments_for_ignition

# -----------------------------
# Helper to build segments
# -----------------------------

def seg(start, dur, text, audio=0.0, pitch=0.0, motion=0.0):
    return {
        "start": start,
        "end": round(start + dur, 3),
        "text": text,
        "audio_energy": audio,
        "pitch": pitch,
        "motion": motion
    }


def run_test(name, segments, expected_hint=None, min_score=0.6, min_slope=0.12):
    print(f"\n==============================")
    print(f"TEST: {name}")
    print(f"==============================")

    spec, ignitions = analyze_segments_for_ignition(
        segments,
        min_score=min_score,
        min_slope=min_slope
    )

    from viral_finder.ignition_deep import select_clip_start

    best_start = select_clip_start(ignitions, goal="viral")

    print("\n🎯 BEST CLIP START:")
    print(best_start["time"], best_start["ignition_type"])

    if not ignitions:
        print("❌ NO IGNITIONS DETECTED")
    else:
        print("✅ IGNITIONS DETECTED:")
        for ig in ignitions:
            print(f" → time={ig['time']}s | score={ig['score']} | slope={ig['slope']}")
            if ig.get("bands"):
                print(f"   bands: {ig['bands']}")
            if ig.get("meta", {}).get("text"):
                print(f"   text: {ig['meta']['text']}")
        from collections import Counter

        punch_counts = Counter(i["ignition_type"] for i in ignitions)

        print("\n🧠 PUNCH PROFILE:")
        for k, v in punch_counts.items():
            print(f" - {k}: {v}")

    if expected_hint:
        print(f"HUMAN EXPECTATION: {expected_hint}")
        

# ==========================================================
# LEVEL 1 — HUMAN vs MACHINE (Ground Truth Calibration)
# ==========================================================

def level_1():
    segments = [
        seg(0.0, 1.0, "i want to share something personal", audio=0.05),
        seg(1.0, 1.0, "most people think success feels good", audio=0.04),
        seg(2.0, 1.0, "but they are lying to you", audio=0.6),
        seg(3.0, 1.0, "this belief ruined my life", audio=0.7)
    ]

    run_test(
        "LEVEL 1 — Ground Truth",
        segments,
        expected_hint="Human ignition around 2.0s when belief is violated"
    )


# ==========================================================
# LEVEL 2 — QUIET BUT DEADLY
# ==========================================================

def level_2():
    segments = [
        seg(0.0, 1.0, "listen carefully", audio=0.02),
        seg(1.0, 1.0, "this almost destroyed my career", audio=0.03),
        seg(2.0, 1.0, "and nobody warned me", audio=0.03)
    ]

    run_test(
        "LEVEL 2 — Quiet but Deadly",
        segments,
        expected_hint="Ignition should fire despite low audio energy",
        min_score=0.4,
        min_slope=0.05
    )


# ==========================================================
# LEVEL 3 — CLICKBAIT IMMUNITY
# ==========================================================

def level_3():
    segments = [
        seg(0.0, 1.0, "you wont believe this secret", audio=0.3),
        seg(1.0, 1.0, "so i went to the store", audio=0.2),
        seg(2.0, 1.0, "and bought some apples", audio=0.2)
    ]

    run_test(
        "LEVEL 3 — Clickbait Immunity",
        segments,
        expected_hint="System should reject or give very weak ignition"
    )


# ==========================================================
# LEVEL 4 — CONTRARIAN TRUTH
# ==========================================================

def level_4():
    segments = [
        seg(0.0, 1.0, "after years of experience", audio=0.05),
        seg(1.0, 1.0, "hard work does not make you rich", audio=0.05),
        seg(2.0, 1.0, "most advice you hear is wrong", audio=0.05)
    ]

    run_test(
        "LEVEL 4 — Contrarian Truth",
        segments,
        expected_hint="Ignition from semantic violation, not emotion",
        min_score=0.45,
        min_slope=0.08
    )


# ==========================================================
# LEVEL 5 — MULTI-IGNITION STORY ARC
# ==========================================================

def level_5():
    segments = [
        seg(0.0, 1.0, "wait this almost destroyed my career", audio=0.2),
        seg(1.0, 1.0, "but here is why most people fail", audio=0.15),
        seg(2.0, 1.0, "i spent ten years learning this", audio=0.25),
        seg(3.0, 1.0, "and the secret is attention", audio=0.5)
    ]

    run_test(
        "LEVEL 5 — Multi-Ignition Mapping",
        segments,
        expected_hint="Should detect 2–3 ignitions across story beats",
        min_score=0.5,
        min_slope=0.1
    )


# ==========================================================
# RUN ALL TESTS
# ==========================================================

if __name__ == "__main__":
    print("\n🔥 IGNITION MASTER TEST SUITE (LEVELS 1–5) 🔥\n")

    level_1()
    level_2()
    level_3()
    level_4()
    level_5()

    print("\n🧠 Tests complete.")
    print("Now compare AI ignition times with your HUMAN intuition.")
    print("Failures = insights. Insights = evolution.")
