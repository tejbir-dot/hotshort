import os
import sys
import importlib


def _reload_idea_graph():
    sys.modules.pop("viral_finder.idea_graph", None)
    return importlib.import_module("viral_finder.idea_graph")


def test_lazy_brain_disabled():
    os.environ["HS_BRAIN_ENABLE_ENRICH"] = "0"
    os.environ["HS_BRAIN_EAGER_IMPORT"] = "0"
    sys.modules.pop("viral_finder.ultron_brain", None)
    ig = _reload_idea_graph()
    segs = [{"start": 0.0, "end": 1.0, "text": "simple test line"}]
    _ = ig.compute_segment_features(segs, aud=[], vis=[], brain=None)
    assert getattr(ig, "_brain_loader_reason", "") == "disabled_by_env"
    assert "viral_finder.ultron_brain" not in sys.modules


def test_dense_coalesce_does_not_collapse_everything():
    os.environ["HS_IDEA_COALESCE_TIME_TOL"] = "0.25"
    os.environ["HS_IDEA_COALESCE_SEM_THR"] = "0.50"
    ig = _reload_idea_graph()
    nodes = []
    for i in range(8):
        s = float(i * 3)
        e = s + 2.5
        txt = f"topic{i} unique signal {i}"
        nodes.append(
            ig.IdeaNode(
                start_idx=i,
                end_idx=i,
                start_time=s,
                end_time=e,
                segments=[{"start": s, "end": e, "text": txt}],
                text=txt,
                state=ig.DEVELOPMENT,
                curiosity_score=0.40,
                punch_confidence=0.20,
                semantic_quality=0.50,
                fingerprint=ig.fingerprint_text(txt),
                metrics={},
            )
        )
    out = ig.coalesce_nodes(nodes)
    assert len(out) >= 3, f"expected multiple nodes, got {len(out)}"


def test_selector_relaxed_pass_recovers_min_target():
    os.environ["HS_SELECTOR_RELAX_CURIO_DELTA"] = "0.08"
    os.environ["HS_SELECTOR_RELAX_PUNCH_DELTA"] = "0.08"
    os.environ["HS_SELECTOR_RELAX_SEM_FLOOR"] = "0.45"
    ig = _reload_idea_graph()
    nodes = []
    for i in range(3):
        s = float(i * 12)
        e = s + 8.0
        txt = f"angle {i} new perspective"
        nodes.append(
            ig.IdeaNode(
                start_idx=i,
                end_idx=i,
                start_time=s,
                end_time=e,
                segments=[{"start": s, "end": e, "text": txt}],
                text=txt,
                state=ig.DEVELOPMENT,
                curiosity_score=0.20,
                punch_confidence=0.20,
                semantic_quality=0.47,
                fingerprint=ig.fingerprint_text(txt),
                metrics={},
            )
        )
    out = ig.select_candidate_clips(
        nodes,
        top_k=6,
        transcript=[],
        ensure_sentence_complete=False,
        allow_multi_angle=True,
        min_target=3,
        diversity_mode="balanced",
        max_overlap_ratio=0.35,
    )
    assert len(out) >= 3, f"expected relaxed recovery to hit min target, got {len(out)}"


def test_memory_pressure_levels():
    orch = importlib.import_module("viral_finder.orchestrator")
    old = orch._rss_mb
    try:
        orch._rss_mb = lambda: 530.0
        assert orch._memory_pressure_level(550.0) == "over"
        orch._rss_mb = lambda: 480.0
        assert orch._memory_pressure_level(550.0) == "near"
        orch._rss_mb = lambda: 300.0
        assert orch._memory_pressure_level(550.0) == "safe"
    finally:
        orch._rss_mb = old


if __name__ == "__main__":
    test_lazy_brain_disabled()
    test_dense_coalesce_does_not_collapse_everything()
    test_selector_relaxed_pass_recovers_min_target()
    test_memory_pressure_levels()
    print("balanced scientist tests passed")
