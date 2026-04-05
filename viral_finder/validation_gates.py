"""
Validation gate facade for post-enrichment policy.
"""

from typing import Any, Dict, Iterable, List, Tuple


def _clamp01(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value or 0.0)))
    except Exception:
        return 0.0


def _semantic_validation_rescue(candidate: Dict[str, Any], failure_reason: str) -> bool:
    signals = (candidate.get("signals", {}) or {})
    semantic = (signals.get("semantic", {}) or {})
    narrative = (signals.get("narrative", {}) or {})
    psychology = (signals.get("psychology", {}) or {})

    semantic_quality = _clamp01(semantic.get("semantic_quality", candidate.get("semantic_quality", 0.0)))
    impact = _clamp01(semantic.get("impact", candidate.get("impact", 0.0)))
    meaning = _clamp01(semantic.get("meaning", candidate.get("meaning", 0.0)))
    clarity = _clamp01(semantic.get("clarity", candidate.get("clarity", 0.0)))
    completion = _clamp01(narrative.get("completion_score", 0.0))
    trigger_score = _clamp01(narrative.get("trigger_score", 0.0))
    viral_density = _clamp01(candidate.get("viral_density", 0.0))
    alignment = _clamp01(candidate.get("alignment_score", 0.0))
    payoff_conf = _clamp01(psychology.get("payoff_confidence", candidate.get("payoff_confidence", 0.0)))
    sarcasm_score = _clamp01(candidate.get("sarcasm_score", candidate.get("metrics", {}).get("sarcasm", 0.0) if isinstance(candidate.get("metrics", {}), dict) else 0.0))
    content_penalty = _clamp01(candidate.get("content_shape_penalty", 0.0))

    semantic_strength = max(semantic_quality, (0.5 * impact) + (0.3 * meaning) + (0.2 * clarity))
    narrative_strength = max(completion, trigger_score, viral_density)
    explanation_strength = max(
        semantic_strength,
        (0.45 * meaning) + (0.35 * clarity) + (0.20 * impact),
    )
    if sarcasm_score >= 0.65 and failure_reason != "no_curve":
        return False
    if content_penalty >= 0.10 and semantic_strength < 0.72:
        return False

    if failure_reason == "no_curiosity_drop":
        return semantic_strength >= 0.56 and narrative_strength >= 0.40
    if failure_reason in {"payoff_low", "no_curve", "too_short_window", "no_curiosity_peak"}:
        return (
            explanation_strength >= 0.60
            and narrative_strength >= 0.42
            and (
                alignment >= 0.08
                or payoff_conf >= 0.35
                or impact >= 0.35
                or (meaning >= 0.72 and clarity >= 0.68)
            )
        )
    return False


def validate_candidate_by_curiosity(
    curve: Iterable[Any],
    start_t: float,
    end_t: float,
    payoff_conf: float | None,
    candidate: Dict[str, Any] | None = None,
    min_peak: float = 0.22,
    payoff_conf_thresh: float = 0.5,
) -> Tuple[bool, str]:
    if payoff_conf is None or payoff_conf < payoff_conf_thresh:
        reason = "payoff_low"
        if candidate and _semantic_validation_rescue(candidate, reason):
            return True, "semantic_rescue"
        return False, reason
    seq = list(curve or [])
    if len(seq) < 3:
        reason = "no_curve"
        if candidate and _semantic_validation_rescue(candidate, reason):
            return True, "semantic_rescue"
        return False, reason
    window = [v for (t, v) in seq if start_t <= t <= end_t]
    if len(window) < 3:
        reason = "too_short_window"
        if candidate and _semantic_validation_rescue(candidate, reason):
            return True, "semantic_rescue"
        return False, reason
    peak = max(window)
    if peak < min_peak:
        reason = "no_curiosity_peak"
        if candidate and _semantic_validation_rescue(candidate, reason):
            return True, "semantic_rescue"
        return False, reason
    if window[-1] > window[-2] + 0.02:
        reason = "no_curiosity_drop"
        if candidate and _semantic_validation_rescue(candidate, reason):
            return True, "semantic_rescue"
        return False, reason
    return True, "ok"


def apply_post_enrichment_validation(
    candidates: List[Dict[str, Any]],
    curve: Iterable[Any],
    min_peak: float = 0.22,
    payoff_conf_thresh: float = 0.5,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    accepted: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for cand in candidates or []:
        payoff_conf = cand.get("payoff_confidence")
        ok, reason = validate_candidate_by_curiosity(
            curve=curve,
            start_t=float(cand.get("start", 0.0) or 0.0),
            end_t=float(cand.get("end", 0.0) or 0.0),
            payoff_conf=payoff_conf,
            candidate=cand,
            min_peak=min_peak,
            payoff_conf_thresh=payoff_conf_thresh,
        )
        payload = dict(cand)
        payload["validation"] = {"accepted": bool(ok), "reasons": [] if ok else [reason]}
        if ok:
            accepted.append(payload)
        else:
            rejected.append(payload)
    return accepted, rejected
