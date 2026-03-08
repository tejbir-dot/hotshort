from viral_finder import orchestrator
from viral_finder import ultron_brain
from viral_finder.validation_gates import apply_post_enrichment_validation


def test_ultron_brain_falls_back_to_heuristics_without_embeddings(monkeypatch):
    monkeypatch.setattr(ultron_brain, "embed_model", None)
    monkeypatch.setattr(ultron_brain, "util", None)
    monkeypatch.setattr(ultron_brain, "torch", None)

    brain = {
        "pattern_memory": [],
        "meaning_weight": 1.0,
        "novelty_weight": 1.0,
        "emotion_weight": 1.0,
        "clarity_weight": 1.0,
        "semantic_enabled": True,
    }

    impact, meaning, novelty, emotion, clarity = ultron_brain.ultron_brain_score(
        "This secret explains the core truth behind the system",
        brain,
    )

    assert brain["semantic_enabled"] is False
    assert impact > 0.0
    assert meaning > 0.0
    assert novelty > 0.0
    assert clarity > 0.0


def test_orchestrator_enrichment_keeps_semantic_scores_with_heuristic_runtime(monkeypatch):
    monkeypatch.setattr(orchestrator, "_runtime_ultron_brain_score", orchestrator._heuristic_semantic_scores)
    candidate = {
        "start": 0.0,
        "end": 2.0,
        "text": "A secret truth that explains the whole pattern",
        "score": 0.55,
        "hook": 0.2,
    }

    enriched = orchestrator.enrich_candidate(candidate, aud=[], vis=[], brain=None)

    assert enriched["impact"] > 0.0
    assert enriched["meaning"] > 0.0
    assert enriched["novelty"] > 0.0
    assert enriched["clarity"] > 0.0


def test_validation_rescues_strong_semantic_candidate_when_curve_is_missing():
    candidates = [
        {
            "start": 0.0,
            "end": 8.0,
            "text": "This is the insight that changes how you see the system.",
            "payoff_confidence": 0.2,
            "alignment_score": 0.12,
            "viral_density": 0.48,
            "signals": {
                "psychology": {"payoff_confidence": 0.2},
                "semantic": {
                    "impact": 0.68,
                    "meaning": 0.66,
                    "novelty": 0.61,
                    "clarity": 0.72,
                    "semantic_quality": 0.74,
                },
                "narrative": {
                    "completion_score": 0.63,
                    "trigger_score": 0.44,
                },
            },
        }
    ]

    accepted, rejected = apply_post_enrichment_validation(candidates, curve=[])

    assert len(accepted) == 1
    assert accepted[0]["validation"]["accepted"] is True
    assert rejected == []
