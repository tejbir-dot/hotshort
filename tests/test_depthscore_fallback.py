from viral_finder.global_fields import build_cognition_cache


def test_depthscore_nonzero_without_semantic_enhancer():
    transcript = [
        {"start": 0.0, "end": 1.5, "text": "this principle becomes a bridge to a better system"},
        {"start": 1.5, "end": 3.0, "text": "however that contradiction reveals the core pattern"},
        {"start": 3.0, "end": 4.5, "text": "in other words the model explains the shift"},
    ]
    cache = build_cognition_cache(transcript, aud=[], vis=[], semantic_enhancer=False)
    assert cache.depth, "depth channel should exist"
    assert max(cache.depth) > 0.0, "depth should remain non-zero in structural-only mode"

