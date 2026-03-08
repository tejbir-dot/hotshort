"""
Curiosity/Psychology facade for staged orchestration.
"""

from typing import Any, Dict, List

from viral_finder.idea_graph import analyze_curiosity_and_detect_punches


def run_curiosity(
    transcript: List[Dict[str, Any]],
    aud: List[Dict[str, Any]] | None = None,
    vis: List[Dict[str, Any]] | None = None,
    brain: Any = None,
) -> Dict[str, Any]:
    feats, curve, candidates = analyze_curiosity_and_detect_punches(
        transcript,
        aud=aud,
        vis=vis,
        brain=brain,
    )
    if hasattr(curve, "tolist"):
        curve = curve.tolist()
    return {
        "features": feats or [],
        "curve": curve or [],
        "candidates": candidates or [],
    }
