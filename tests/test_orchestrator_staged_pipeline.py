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


def test_enrichment_budget_prioritizes_strict_candidates(monkeypatch):
    monkeypatch.setenv("HS_SELECTOR_PRE_ENRICH_BUDGET", "3")
    monkeypatch.setenv("HS_ORCH_ENRICH_STRICT_FIRST", "1")
    monkeypatch.setattr(orchestrator, "compute_quality_scores", lambda *args, **kwargs: {"hook_score": 0.2, "payoff_resolution_score": 0.2, "information_density_score": 0.2})
    monkeypatch.setattr(
        orchestrator,
        "enrich_candidate",
        lambda candidate, aud, vis, brain, cache_bucket=None: {
            **candidate,
            "impact": 0.5,
            "meaning": 0.5,
            "novelty": 0.4,
            "emotion": 0.2,
            "clarity": 0.6,
            "classic": 0.5,
            "audio": 0.2,
            "motion": 0.2,
            "semantic_quality": float(candidate.get("semantic_quality", 0.4)),
        },
    )
    ctx = orchestrator.PipelineContext(path="dummy.mp4", top_k=2, allow_fallback=False)
    ctx.transcript = [{"start": 0.0, "end": 20.0, "text": "full transcript context"}]
    ctx.raw_candidates = [
        {"start": 0.0, "end": 5.0, "text": "strict one", "score": 0.72, "select_pass": "strict", "semantic_quality": 0.7, "curiosity": 0.5, "punch_confidence": 0.5},
        {"start": 6.0, "end": 11.0, "text": "strict two", "score": 0.68, "select_pass": "strict", "semantic_quality": 0.68, "curiosity": 0.44, "punch_confidence": 0.42},
        {"start": 12.0, "end": 17.0, "text": "relaxed one", "score": 0.45, "select_pass": "relaxed", "semantic_quality": 0.49, "curiosity": 0.22, "punch_confidence": 0.2, "relaxed_readiness": 0.48},
        {"start": 18.0, "end": 19.5, "text": "hook one", "score": 0.4, "hook_seed": True, "hook_strength": 0.5, "semantic_quality": 0.35},
    ]
    orchestrator._run_enrichment(ctx)
    stats = ctx.stage_stats["L7_SIGNAL_ENRICHMENT"]
    assert stats["selected_candidates"] == 3
    assert stats["selected_strict"] == 2
    assert stats["selected_relaxed"] <= 1


def test_narrative_scores_use_candidate_cache(monkeypatch):
    calls = {"count": 0}

    def _fake_quality_scores(*args, **kwargs):
        calls["count"] += 1
        return {"hook_score": 0.31, "ending_strength": 0.44}

    monkeypatch.setattr(orchestrator, "compute_quality_scores", _fake_quality_scores)
    cache_bucket = {}
    candidate = {"start": 0.0, "end": 5.0, "_feature_cache": cache_bucket}
    transcript = [{"start": 0.0, "end": 5.0, "text": "segment"}]
    first = orchestrator._extract_narrative_scores(transcript, candidate)
    second = orchestrator._extract_narrative_scores(transcript, candidate)
    assert first == second
    assert calls["count"] == 1


def test_validation_stage_records_reject_reasons(monkeypatch):
    ctx = orchestrator.PipelineContext(path="dummy.mp4", top_k=2, allow_fallback=False)
    monkeypatch.setattr(
        orchestrator,
        "apply_post_enrichment_validation",
        lambda candidates, curve, min_peak, payoff_conf_thresh: (
            [dict(candidates[0], validation={"accepted": True, "reasons": []})],
            [dict(candidates[1], validation={"accepted": False, "reasons": ["payoff_low"]})],
        ),
    )
    ctx.curiosity_curve = [(0.0, 0.1), (1.0, 0.15), (2.0, 0.12)]
    ctx.enriched_candidates = [
        {"start": 0.0, "end": 2.0, "text": "good clip", "payoff_confidence": 0.55, "signals": {"psychology": {"payoff_confidence": 0.55}}},
        {"start": 3.0, "end": 5.0, "text": "weak clip", "payoff_confidence": 0.05, "signals": {"psychology": {"payoff_confidence": 0.05}}},
    ]
    orchestrator._run_validation(ctx)
    stats = ctx.stage_stats["L8_VALIDATION_GATES"]
    assert stats["rejected"] == 1
    assert "payoff_low" in stats["reject_reasons"]


def test_staged_pipeline_backfills_longform_underflow(monkeypatch):
    transcript = []
    start = 0.0
    for idx in range(220):
        transcript.append({"start": start, "end": start + 4.0, "text": f"segment {idx}"})
        start += 4.0

    monkeypatch.setattr(orchestrator, "_load_cached_transcript", lambda _p: transcript)
    monkeypatch.setattr(orchestrator, "_save_cached_transcript", lambda _p, _s: None)
    monkeypatch.setattr(orchestrator, "analyze_audio", lambda _p: [{"time": 10.0, "energy": 0.15}])
    monkeypatch.setattr(orchestrator, "analyze_visual", lambda _p: [{"time": 10.0, "motion": 0.0}])
    monkeypatch.setattr(orchestrator, "_ensure_brain_runtime_loaded", lambda: None)
    monkeypatch.setattr(orchestrator, "_brain_import_ok", False)
    monkeypatch.setattr(
        orchestrator,
        "run_curiosity_stage",
        lambda transcript, aud, vis, brain: {
            "features": [],
            "curve": [(0.0, 0.1), (20.0, 0.3), (40.0, 0.12)],
            "candidates": [{"peak_time": 40.0}, {"peak_time": 240.0}, {"peak_time": 520.0}],
        },
    )
    monkeypatch.setattr(orchestrator, "build_idea_graph", lambda *args, **kwargs: [object()] * 4)
    monkeypatch.setattr(
        orchestrator,
        "select_candidate_clips",
        lambda *args, **kwargs: [
            {
                "start": 10.0,
                "end": 26.0,
                "text": "strict seed",
                "score": 0.52,
                "select_pass": "strict",
                "semantic_quality": 0.64,
                "curiosity": 0.42,
                "punch_confidence": 0.38,
                "payoff_confidence": 0.42,
            }
        ],
    )

    out = orchestrator.orchestrate("dummy.mp4", top_k=5, pipeline_mode="staged", allow_fallback=False)

    assert len(out) >= 3
    assert any(bool(c.get("backfill")) for c in out)


def test_staged_pipeline_uses_duration_based_target_min_for_candidate_selection(monkeypatch):
    transcript = []
    start = 0.0
    for idx in range(220):
        transcript.append({"start": start, "end": start + 4.0, "text": f"segment {idx}"})
        start += 4.0

    captured = {}

    def fake_select_candidate_clips(*args, **kwargs):
        captured['min_target'] = kwargs.get('min_target')
        return [
            {
                "start": 10.0,
                "end": 22.0,
                "text": "sample clip",
                "score": 0.52,
                "select_pass": "strict",
                "semantic_quality": 0.64,
                "curiosity": 0.42,
                "punch_confidence": 0.38,
                "payoff_confidence": 0.42,
            }
        ]

    monkeypatch.setattr(orchestrator, "_load_cached_transcript", lambda _p: transcript)
    monkeypatch.setattr(orchestrator, "_save_cached_transcript", lambda _p, _s: None)
    monkeypatch.setattr(orchestrator, "analyze_audio", lambda _p: [{"time": 10.0, "energy": 0.15}])
    monkeypatch.setattr(orchestrator, "analyze_visual", lambda _p: [{"time": 10.0, "motion": 0.0}])
    monkeypatch.setattr(orchestrator, "_ensure_brain_runtime_loaded", lambda: None)
    monkeypatch.setattr(orchestrator, "_brain_import_ok", False)
    monkeypatch.setattr(
        orchestrator,
        "run_curiosity_stage",
        lambda transcript, aud, vis, brain: {
            "features": [],
            "curve": [(0.0, 0.1), (20.0, 0.3), (40.0, 0.12)],
            "candidates": [{"peak_time": 40.0}],
        },
    )
    monkeypatch.setattr(orchestrator, "build_idea_graph", lambda *args, **kwargs: [object()])
    monkeypatch.setattr(orchestrator, "select_candidate_clips", fake_select_candidate_clips)

    orchestrator.orchestrate("dummy.mp4", top_k=7, pipeline_mode="staged", allow_fallback=False)

    assert captured.get('min_target') == 5


def test_editor_refiner_rejects_flat_incomplete_arc():
    ctx = orchestrator.PipelineContext(path="dummy.mp4", top_k=2, allow_fallback=False, target_min=1)
    ctx.transcript = [
        {"start": 0.0, "end": 5.0, "text": "plain setup"},
        {"start": 5.0, "end": 10.0, "text": "still context"},
        {"start": 10.0, "end": 15.0, "text": "nothing resolves"},
    ]
    ctx.ranked_output = [
        {
            "start": 0.0,
            "end": 15.0,
            "duration": 15.0,
            "text": "plain setup still context nothing resolves",
            "label": "Context Builder",
            "arc_complete": False,
            "arc_score": 0.16,
            "viral_score": 0.16,
            "signals": {
                "narrative": {"hook_score": 0.05, "open_loop_score": 0.0, "payoff_resolution_score": 0.08},
                "engagement": {"motion": 0.0, "energy": 0.04},
                "psychology": {"tension_gradient": 0.0},
                "semantic": {"impact": 0.44, "meaning": 0.52, "clarity": 0.49},
            },
            "motion": 0.0,
            "classic": 0.04,
            "hook_offset": 6.0,
            "hook_strength": 0.05,
            "story_patterns": [],
            "payoff_segment": {"start": 14.0, "end": 15.0, "text": "nothing resolves"},
            "hook_segment": {"start": 6.0, "end": 7.0, "text": "still context"},
        }
    ]

    orchestrator._run_editor_refiner(ctx)

    assert ctx.ranked_output == []
