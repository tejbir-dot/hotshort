from viral_finder.cognition_cache import FrameWindow
from viral_finder.escalation_memory import EscalationMemoryConfig, escalation_memory_extend
from viral_finder.global_fields import build_cognition_cache


def test_escalation_memory_extends_to_release():
    transcript = [
        {"start": 0.0, "end": 1.0, "text": "wait because this is building"},
        {"start": 1.0, "end": 2.0, "text": "there is one more thing and you will see"},
        {"start": 2.0, "end": 3.0, "text": "the tension keeps rising right now"},
        {"start": 3.0, "end": 4.0, "text": "so that is why the answer is simple."},
        {"start": 4.0, "end": 5.0, "text": "final reflection follows."},
    ]
    aud = [
        {"time": 0.5, "energy": 0.45},
        {"time": 1.5, "energy": 0.62},
        {"time": 2.5, "energy": 0.85},
        {"time": 3.5, "energy": 0.95},
        {"time": 4.5, "energy": 0.35},
    ]
    cache = build_cognition_cache(transcript, aud=aud, vis=[])
    w = FrameWindow(0, 2)
    out = escalation_memory_extend(
        w,
        cache,
        cfg=EscalationMemoryConfig(
            tension_threshold=0.02,
            resolution_threshold=0.90,
            release_threshold=0.20,
            lookahead_sec=4.0,
            max_extend_sec=4.0,
        ),
    )
    assert out.e > w.e, f"expected extension into release frames ({out.e} <= {w.e})"
