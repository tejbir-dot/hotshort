from viral_finder.dominance_selector import SelectorConfig, select_dominant_arcs
from viral_finder.global_fields import build_cognition_cache


def test_override_protocol_applies_on_high_punch():
    transcript = [
        {"start": 0.0, "end": 1.2, "text": "setup line"},
        {"start": 1.2, "end": 2.4, "text": "more setup"},
        {"start": 2.4, "end": 3.6, "text": "this is explosive! this is explosive!"},
        {"start": 3.6, "end": 4.8, "text": "that is why this matters!"},
        {"start": 4.8, "end": 6.0, "text": "reflection"},
    ]
    aud = [
        {"time": 0.6, "energy": 0.2},
        {"time": 1.8, "energy": 0.3},
        {"time": 3.0, "energy": 0.98},
        {"time": 4.2, "energy": 0.95},
        {"time": 5.4, "energy": 0.25},
    ]
    cache = build_cognition_cache(transcript, aud=aud, vis=[])
    out = select_dominant_arcs(
        cache,
        top_k=3,
        cfg=SelectorConfig(top_k=3, override_thr=0.40, lookahead_sec=6.0),
        selection_mode="godmode",
    )
    assert out, "expected at least one candidate"
    assert any(bool(c.get("override_applied")) for c in out), "expected at least one override_applied candidate"

