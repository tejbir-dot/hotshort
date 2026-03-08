"""
Clip selector facade for centralized dedupe/diversity ranking.
"""

from typing import Any, Dict, List


def rank_and_diversify(
    candidates: List[Dict[str, Any]],
    top_k: int,
    min_start_gap: float = 3.0,
) -> List[Dict[str, Any]]:
    ranked = sorted(
        candidates or [],
        key=lambda x: float(x.get("score_enriched", x.get("score", 0.0)) or 0.0),
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
