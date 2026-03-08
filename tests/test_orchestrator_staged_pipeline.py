from viral_finder import orchestrator


def test_staged_pipeline_reuses_cached_transcript(monkeypatch):
    transcript = [
        {"start": 0.0, "end": 1.2, "text": "Why this works?"},
        {"start": 1.2, "end": 2.5, "text": "Because payoff comes here."},
        {"start": 2.5, "end": 4.0, "text": "So that is the point."},
    ]

    def _fail_transcribe(_path):
        raise AssertionError("transcribe should not be called when cache exists")

    monkeypatch.setattr(orchestrator, "_load_cached_transcript", lambda _p: transcript)
    monkeypatch.setattr(orchestrator, "_save_cached_transcript", lambda _p, _s: None)
    monkeypatch.setattr(orchestrator, "gemini_transcribe", _fail_transcribe)
    monkeypatch.setattr(orchestrator, "extract_transcript", _fail_transcribe)
    monkeypatch.setattr(orchestrator, "legacy_transcribe", _fail_transcribe)
    monkeypatch.setattr(orchestrator, "analyze_audio", lambda _p: [{"time": 1.0, "energy": 0.5}])
    monkeypatch.setattr(orchestrator, "analyze_visual", lambda _p: [{"time": 1.0, "motion": 0.4}])
    monkeypatch.setattr(orchestrator, "_ensure_brain_runtime_loaded", lambda: None)
    monkeypatch.setattr(orchestrator, "_brain_import_ok", False)
    monkeypatch.setattr(
        orchestrator,
        "run_curiosity_stage",
        lambda transcript, aud, vis, brain: {
            "features": [],
            "curve": [(0.0, 0.1), (1.0, 0.35), (2.0, 0.2)],
            "candidates": [{"start_idx": 0, "end_idx": 2, "payoff_confidence": 0.9}],
        },
    )
    monkeypatch.setattr(orchestrator, "build_idea_graph", lambda *args, **kwargs: [object()])
    monkeypatch.setattr(
        orchestrator,
        "select_candidate_clips",
        lambda *args, **kwargs: [
            {
                "start": 0.0,
                "end": 2.0,
                "text": "Why this works? Because payoff comes here.",
                "score": 0.42,
                "label": "Insight / Punch",
                "reason": "curiosity | semantic",
                "curiosity": 0.31,
                "punch_confidence": 0.75,
                "payoff_confidence": 0.92,
            }
        ],
    )

    out = orchestrator.orchestrate("dummy.mp4", top_k=3, pipeline_mode="staged")
    assert out
    first = out[0]
    assert "signals" in first
    assert set(first["signals"].keys()) == {"psychology", "semantic", "narrative", "engagement"}
    assert first["validation"]["accepted"] is True


def test_staged_pipeline_validation_rejects_before_rank(monkeypatch):
    transcript = [
        {"start": 0.0, "end": 1.0, "text": "A"},
        {"start": 1.0, "end": 2.0, "text": "B"},
        {"start": 2.0, "end": 3.0, "text": "C"},
    ]

    monkeypatch.setattr(orchestrator, "_load_cached_transcript", lambda _p: transcript)
    monkeypatch.setattr(orchestrator, "analyze_audio", lambda _p: [{"time": 1.0, "energy": 0.3}])
    monkeypatch.setattr(orchestrator, "analyze_visual", lambda _p: [{"time": 1.0, "motion": 0.3}])
    monkeypatch.setattr(orchestrator, "_ensure_brain_runtime_loaded", lambda: None)
    monkeypatch.setattr(orchestrator, "_brain_import_ok", False)
    monkeypatch.setattr(
        orchestrator,
        "run_curiosity_stage",
        lambda transcript, aud, vis, brain: {
            "features": [],
            "curve": [(0.0, 0.1), (1.0, 0.2), (2.0, 0.25)],
            "candidates": [],
        },
    )
    monkeypatch.setattr(orchestrator, "build_idea_graph", lambda *args, **kwargs: [object(), object()])
    monkeypatch.setattr(
        orchestrator,
        "select_candidate_clips",
        lambda *args, **kwargs: [
            {"start": 0.0, "end": 1.5, "text": "clip1", "score": 0.4, "payoff_confidence": 0.1},
            {"start": 1.6, "end": 2.8, "text": "clip2", "score": 0.5, "payoff_confidence": 0.2},
        ],
    )

    out = orchestrator.orchestrate("dummy.mp4", top_k=2, pipeline_mode="staged", allow_fallback=False)
    assert out == []
