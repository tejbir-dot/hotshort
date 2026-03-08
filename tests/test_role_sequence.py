from viral_finder.global_fields import build_cognition_cache


def test_role_sequence_contains_peak_then_payoff():
    transcript = [
        {"start": 0.0, "end": 1.2, "text": "you think this is simple?"},
        {"start": 1.2, "end": 2.4, "text": "let me show why this builds tension"},
        {"start": 2.4, "end": 3.6, "text": "but here is the conflict that breaks expectations"},
        {"start": 3.6, "end": 4.8, "text": "this is the critical moment!"},
        {"start": 4.8, "end": 6.0, "text": "so that is why it works."},
    ]
    aud = [
        {"time": 0.6, "energy": 0.3},
        {"time": 1.8, "energy": 0.45},
        {"time": 3.0, "energy": 0.7},
        {"time": 4.2, "energy": 0.95},
        {"time": 5.4, "energy": 0.65},
    ]
    cache = build_cognition_cache(transcript, aud=aud, vis=[])
    peak_idx = [i for i, r in enumerate(cache.roles) if r == "PEAK"]
    payoff_idx = [i for i, r in enumerate(cache.roles) if r == "PAYOFF"]
    assert peak_idx, "expected at least one PEAK frame"
    assert payoff_idx, "expected at least one PAYOFF frame"
    assert min(payoff_idx) >= min(peak_idx), "expected payoff to occur after peak in sequence"

