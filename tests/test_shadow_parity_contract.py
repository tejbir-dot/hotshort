from viral_finder import orchestrator
from viral_finder.dominance_selector import select_dominant_arcs
from viral_finder.global_fields import build_cognition_cache


def test_shadow_metrics_contract():
    gm = [
        {"start": 10.0, "end": 20.0, "score": 0.91, "arc_complete": True},
        {"start": 30.0, "end": 40.0, "score": 0.80, "arc_complete": False},
    ]
    lg = [
        {"start": 12.0, "end": 19.0, "score": 0.72, "arc_complete": False},
        {"start": 32.0, "end": 41.0, "score": 0.68, "arc_complete": False},
    ]
    m = orchestrator._shadow_metrics(gm, lg, top_k=3, target_min=3)
    assert set(m.keys()) == {
        "dominant_clip_jaccard",
        "arc_completeness_delta",
        "score_margin_delta",
        "underflow_rate",
    }


def test_godmode_output_schema_is_compatible():
    transcript = [
        {"start": 0.0, "end": 1.0, "text": "hook question?"},
        {"start": 1.0, "end": 2.0, "text": "build conflict now"},
        {"start": 2.0, "end": 3.0, "text": "peak surge!"},
        {"start": 3.0, "end": 4.0, "text": "so this is why it resolves."},
    ]
    cache = build_cognition_cache(transcript, aud=[], vis=[])
    out = select_dominant_arcs(cache, top_k=2, selection_mode="godmode_shadow")
    assert out, "expected candidates from godmode selector"
    for c in out:
        assert "start" in c and "end" in c and "score" in c and "text" in c
        assert "selection_mode" in c

