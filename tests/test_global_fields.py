from viral_finder.global_fields import build_cognition_cache


def test_escalation_prefers_acceleration_over_flat_energy():
    transcript = [
        {"start": 0.0, "end": 1.5, "text": "steady line one"},
        {"start": 1.5, "end": 3.0, "text": "steady line two"},
        {"start": 3.0, "end": 4.5, "text": "steady line three"},
        {"start": 4.5, "end": 6.0, "text": "why does this suddenly matter?!"},
        {"start": 6.0, "end": 7.5, "text": "this changes everything right now!"},
    ]
    aud = [
        {"time": 0.5, "energy": 0.35},
        {"time": 2.0, "energy": 0.35},
        {"time": 3.5, "energy": 0.35},
        {"time": 5.0, "energy": 0.95},
        {"time": 6.5, "energy": 0.96},
    ]
    cache = build_cognition_cache(transcript, aud=aud, vis=[])
    early = max(cache.escalation[:3])
    late = max(cache.escalation[3:])
    assert late > early, f"expected late escalation burst > early flat zone ({late} <= {early})"

