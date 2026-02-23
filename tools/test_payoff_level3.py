"""
Level-3 Payoff Adversarial Test Harness
Focus: cognitive realism, false-positive rejection, and gate integrity
"""

from pprint import pprint

# Import your function
from viral_finder.idea_graph import detect_payoff_end


# -------------------------------------------------------------------
# Helper: build synthetic feature sequences
# -------------------------------------------------------------------
def make_feats(
    curiosity,
    sem_density,
    texts=None,
    seg_dur=2.0,
    start_time=0.0
):
    feats = []
    t = start_time
    for i, c in enumerate(curiosity):
        feats.append({
            "start": round(t, 2),
            "end": round(t + seg_dur, 2),
            "curiosity": float(c),
            "sem_density": float(sem_density[i]),
            "text": texts[i] if texts else ""
        })
        t += seg_dur
    return feats, curiosity


# -------------------------------------------------------------------
# Test runner
# -------------------------------------------------------------------
def run_test(name, feats, curv, start_idx, expect_payoff: bool):
    print("\n" + "=" * 60)
    print(f"TEST: {name}")

    payoff_time, conf, meta = detect_payoff_end(
        feats,
        curv,
        start_idx=start_idx,
        return_meta=True,
        debug=False
    )

    print(f"payoff_time: {payoff_time}")
    print(f"confidence: {conf}")
    print(f"reason: {meta.get('reason')}")

    passed = (payoff_time is not None) if expect_payoff else (payoff_time is None)

    if passed:
        print("✅ PASS")
    else:
        print("❌ FAIL")
        print("— Debug (last 3 rows) —")
        pprint(meta.get("debug_rows", [])[-3:])

    return passed


# -------------------------------------------------------------------
# LEVEL-3 TEST CASES
# -------------------------------------------------------------------
def run_all():
    passed = 0
    failed = 0

    # 1️⃣ Nested Peak (valid payoff)
    feats, curv = make_feats(
        curiosity=[0.2, 0.6, 0.9, 0.8, 0.6, 0.4],
        sem_density=[0.3, 0.4, 0.5, 0.55, 0.56, 0.56],
        texts=["", "", "", "", "So the point is.", ""]
    )
    passed += run_test("NestedPeak", feats, curv, 0, True)
    failed += 0 if passed else 1

    # 2️⃣ Semantic Momentum (meaning still rising → reject)
    feats, curv = make_feats(
        curiosity=[0.9, 0.7, 0.5, 0.4, 0.3],
        sem_density=[0.3, 0.55, 0.75, 0.9, 1.05],
        texts=["", "", "", "", ""]
    )
    passed += run_test("SemanticMomentum", feats, curv, 0, False)
    failed += 0 if passed else 1

    # 3️⃣ Plateau (no closure, no fall)
    feats, curv = make_feats(
        curiosity=[0.5, 0.5, 0.5, 0.5],
        sem_density=[0.4, 0.42, 0.44, 0.45],
        texts=["", "", "", ""]
    )
    passed += run_test("Plateau", feats, curv, 0, False)
    failed += 0 if passed else 1

    # 4️⃣ False Closure (punch words but obligation open)
    feats, curv = make_feats(
        curiosity=[0.6, 0.55, 0.5],
        sem_density=[0.4, 0.55, 0.7],
        texts=["", "But wait!", "However this continues"]
    )
    passed += run_test("FalseClosure", feats, curv, 0, False)
    failed += 0 if passed else 1

    # 5️⃣ Aftertaste Bounce (curiosity rises again)
    feats, curv = make_feats(
        curiosity=[0.9, 0.6, 0.4, 0.6],
        sem_density=[0.3, 0.4, 0.45, 0.46],
        texts=["", "", "", ""]
    )
    passed += run_test("AftertasteBounce", feats, curv, 0, False)
    failed += 0 if passed else 1

    # ----------------------------------------------------------------
    print("\n" + "=" * 60)
    print(f"SUMMARY: passed={passed} failed={failed}")
    print("=" * 60)


if __name__ == "__main__":
    run_all()
