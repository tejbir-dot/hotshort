"""
Clip selector facade for centralized dedupe/diversity ranking.
"""

from typing import Any, Dict, List


def rank_and_diversify(
    candidates: List[Dict[str, Any]],
    top_k: int,
    min_start_gap: float = 3.0,
) -> List[Dict[str, Any]]:
    def _rank_key(candidate: Dict[str, Any]) -> tuple[float, float, float]:
        return (
            float(candidate.get("viral_score", candidate.get("score_enriched", candidate.get("score", 0.0))) or 0.0),
            float(candidate.get("score_enriched", candidate.get("score", 0.0)) or 0.0),
            float(candidate.get("score", 0.0) or 0.0),
        )

    ranked = sorted(
        candidates or [],
        key=_rank_key,
        reverse=True,
    )
    out: List[Dict[str, Any]] = []
    starts: List[float] = []
    for cand in ranked:
        s = float(cand.get("start", 0.0) or 0.0)
        if any(abs(s - ps) < min_start_gap for ps in starts):
            continue
        out.append(cand)
        starts.append(s)
        if len(out) >= int(max(1, top_k)):
            break
    return out
