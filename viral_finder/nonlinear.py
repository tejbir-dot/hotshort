"""Detect attention islands (non-linear spikes) from sequential segments.

Segments expected: list of dict-like or objects with keys/attrs:
  - audio_energy (0..1), emotion (0..1), motion (0..1)
  - semantic_distance(prev) -> float (0..1) or precomputed semantic field

This is lightweight and uses delta-based scoring.
"""
from typing import List, Dict, Any


def dominant_delta(delta: Dict[str, float]) -> str:
    # return key with largest relative contribution
    if not delta:
        return ""
    k = max(delta.items(), key=lambda kv: kv[1])[0]
    return k


def detect_attention_islands(segments: List[Any]) -> List[Dict[str, Any]]:
    islands = []
    if not segments or len(segments) < 2:
        return islands

    for i in range(1, len(segments)):
        prev = segments[i-1]
        curr = segments[i]

        # support both dicts and objects
        def get(o, k, default=0.0):
            try:
                if isinstance(o, dict):
                    return float(o.get(k, default) or default)
                return float(getattr(o, k, default) or default)
            except Exception:
                return float(default)

        delta = {
            "audio": abs(get(curr, "audio_energy") - get(prev, "audio_energy")),
            "emotion": abs(get(curr, "emotion") - get(prev, "emotion")),
            "semantic": 0.0,
            "motion": abs(get(curr, "motion") - get(prev, "motion")),
        }

        # semantic distance: allow segment to provide method .semantic_distance(prev)
        try:
            if hasattr(curr, "semantic_distance"):
                sd = curr.semantic_distance(prev)
                delta["semantic"] = abs(float(sd))
            else:
                # fallback: look for precomputed field
                delta["semantic"] = abs(get(curr, "semantic", 0.0) - get(prev, "semantic", 0.0))
        except Exception:
            delta["semantic"] = 0.0

        score = (
            0.35 * delta["semantic"] +
            0.25 * delta["emotion"] +
            0.25 * delta["audio"] +
            0.15 * delta["motion"]
        )

        if score > 0.55:
            islands.append({
                "index": i,
                "score": float(round(score, 3)),
                "reason": dominant_delta(delta),
                "delta": {k: float(round(v, 3)) for k, v in delta.items()}
            })

    return islands
