"""
payoff_engine.py

StoryThread-aware Narrative Resolver for HotShort.

Design goals:
- Payoff is not a sentence. It is a structural resolution of a promise/debt.
- Score candidate spans, not isolated lines.
- Keep the engine deterministic, explainable, and experiment-mode friendly.
- Work with a StoryThread object, but remain resilient if the object is a plain dict-like bundle.

This module is intentionally self-contained and uses only the standard library.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
import logging
import math
import re
import os

log = logging.getLogger("payoff_engine")

# Prefer the project's canonical promise/debt inference when available.
try:  # package import when used inside the repo
    from .narrative_intelligence import infer_narrative_promise_and_debt as _project_infer_narrative_promise_and_debt  # type: ignore
except Exception:  # pragma: no cover - fallback for standalone usage
    try:
        from narrative_intelligence import infer_narrative_promise_and_debt as _project_infer_narrative_promise_and_debt  # type: ignore
    except Exception:  # pragma: no cover
        _project_infer_narrative_promise_and_debt = None


# ---------------------------------------------------------------------------
# Promise types
# ---------------------------------------------------------------------------

class PromiseType:
    PROCESS_EXPLANATION = "PROCESS_EXPLANATION"
    CAUSE_REVELATION = "CAUSE_REVELATION"
    SINGULAR_LEVERAGE = "SINGULAR_LEVERAGE"
    RECOMMENDATION = "RECOMMENDATION"
    NARRATIVE_CLIMAX = "NARRATIVE_CLIMAX"
    GENERAL_INSIGHT = "GENERAL_INSIGHT"
    UNKNOWN = "UNKNOWN"


PROMISE_TYPE_HINTS: Dict[str, Dict[str, Any]] = {
    PromiseType.PROCESS_EXPLANATION: {
        "tokens": {
            "how", "process", "step", "steps", "mechanism", "mechanics",
            "first", "then", "next", "then", "way", "execute", "build",
            "map", "flow", "throughput", "system", "sequence",
        },
        "patterns": [
            r"\bfirst\b.*\bthen\b",
            r"\bhow\b.*\bworks?\b",
            r"\bway\b.*\bdo\b",
            r"\bstep\b",
            r"\bprocess\b",
        ],
        "must_be_multi_segment": True,
    },
    PromiseType.CAUSE_REVELATION: {
        "tokens": {
            "because", "reason", "cause", "caused", "due", "therefore",
            "that's why", "why", "root", "origin", "explain", "explanation",
        },
        "patterns": [
            r"\bbecause\b",
            r"\bthat's why\b",
            r"\bdue to\b",
            r"\bwhy\b.*\b\b",
        ],
        "must_be_multi_segment": False,
    },
    PromiseType.SINGULAR_LEVERAGE: {
        "tokens": {
            "one", "one thing", "single", "only", "highest leverage",
            "highest", "leverage", "bottleneck", "constraint", "priority",
            "the one", "95%", "5%", "focus", "singular",
        },
        "patterns": [
            r"\bone thing\b",
            r"\bthe one\b",
            r"\bonly\b",
            r"\bhighest leverage\b",
            r"\bbottleneck\b",
            r"\bconstraint\b",
        ],
        "must_be_multi_segment": False,
    },
    PromiseType.RECOMMENDATION: {
        "tokens": {
            "should", "need to", "must", "stop", "don't", "do this",
            "take", "prioritize", "recommend", "suggest", "need", "go do",
        },
        "patterns": [
            r"\byou should\b",
            r"\byou need to\b",
            r"\byou must\b",
            r"\bstop\b",
            r"\bdon't\b",
        ],
        "must_be_multi_segment": False,
    },
    PromiseType.NARRATIVE_CLIMAX: {
        "tokens": {
            "then", "finally", "at last", "realized", "landed", "happened",
            "the moment", "eventually", "end", "ending", "resolution",
            "climax", "reveal", "turned out",
        },
        "patterns": [
            r"\band then\b",
            r"\bfinally\b",
            r"\bwhat happened\b",
            r"\brealized\b",
            r"\bturned out\b",
        ],
        "must_be_multi_segment": True,
    },
    PromiseType.GENERAL_INSIGHT: {
        "tokens": {
            "insight", "lesson", "meaning", "so", "therefore", "insane",
            "interesting", "important", "real", "truth", "understand",
        },
        "patterns": [
            r"\bmeaning\b",
            r"\bso\b",
            r"\btherefore\b",
        ],
        "must_be_multi_segment": False,
    },
}


# ---------------------------------------------------------------------------
# Helper dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PromiseFrame:
    promise: str
    debt: str
    promise_type: str
    rationale: str = ""
    hints: List[str] = field(default_factory=list)


@dataclass
class CandidateScore:
    idxs: List[int]
    text: str
    start: float
    end: float
    promise_match: float
    debt_match: float
    development_alignment: float
    specificity: float
    closure: float
    emotional_release: float
    finality: float
    boundary_crispness: float
    final_score: float
    information_gain: float = 0.0
    rejection_reason: Optional[str] = None
    rationale: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "idxs": self.idxs,
            "text": self.text,
            "start": self.start,
            "end": self.end,
            "promise_match": round(self.promise_match, 3),
            "debt_match": round(self.debt_match, 3),
            "development_alignment": round(self.development_alignment, 3),
            "specificity": round(self.specificity, 3),
            "closure": round(self.closure, 3),
            "emotional_release": self.emotional_release,
            "finality": self.finality,
            "boundary_crispness": self.boundary_crispness,
            "final_score": self.final_score,
            "information_gain": self.information_gain,
            "rejection_reason": self.rejection_reason,
            "rationale": self.rationale,
        }


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"[a-z0-9%']+")
_SENTENCE_BREAK_RE = re.compile(r"[.!?]+")
_MULTISPACE_RE = re.compile(r"\s+")
_NUM_RE = re.compile(r"\b\d+(\.\d+)?%?\b")

STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "to", "of", "in", "on", "for",
    "at", "by", "is", "it", "i", "you", "we", "he", "she", "they", "this",
    "that", "with", "are", "was", "be", "as", "if", "then", "than", "from",
    "into", "your", "our", "their", "my", "me", "us", "them", "so", "do",
    "does", "did", "have", "has", "had", "will", "would", "can", "could",
    "should", "just", "not", "no", "yes", "all", "any", "one", "thing",
}

CONTRAST_MARKERS = {
    "but", "however", "although", "though", "yet", "instead", "rather",
    "actually", "really", "in reality", "the truth is", "what matters",
    "what's really", "what you need", "the point is",
}

CLOSURE_MARKERS = {
    "that's why", "so", "therefore", "meaning", "in conclusion", "ultimately",
    "finally", "the point", "bottom line", "to be clear", "what this means",
    "which means", "in other words",
}

EMOTIONAL_RELEASE_MARKERS = {
    "wow", "crazy", "insane", "amazing", "unbelievable", "mind-blowing",
    "shocking", "wild", "powerful", "beautiful", "huge", "massive",
}

FINALITY_MARKERS = {
    "period", "full stop", "that's all", "nothing else", "end of story",
    "no more", "mic drop", "done", "final", "game changer", "locked in",
}

RECOMMENDATION_MARKERS = {
    "you should", "you need to", "you must", "stop", "don't", "do this",
    "take", "focus on", "prioritize", "consider", "avoid", "make sure",
}

PROCESS_MARKERS = {
    "first", "then", "next", "step", "steps", "process", "mechanism",
    "flow", "sequence", "how", "way", "build", "map", "throughput",
}

CAUSE_MARKERS = {
    "because", "reason", "due to", "that's why", "cause", "caused", "why",
    "root", "therefore", "so that",
}

SINGULAR_MARKERS = {
    "one thing", "the one", "only", "single", "highest leverage", "bottleneck",
    "constraint", "priority", "focus", "5%", "95%", "the key", "the answer",
    "one answer", "singular answer",
}


def _normalize_text(text: str) -> str:
    text = (text or "").strip().lower()
    text = _MULTISPACE_RE.sub(" ", text)
    return text


def _tokens(text: str) -> List[str]:
    return _WORD_RE.findall(_normalize_text(text))


def _content_tokens(text: str) -> List[str]:
    return [t for t in _tokens(text) if t not in STOPWORDS and len(t) > 2]


def _dedupe_preserve_order(values: Iterable[str]) -> List[str]:
    seen = set()
    out = []
    for v in values:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _safe_get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _segment_text(seg: Dict[str, Any]) -> str:
    return str(seg.get("text") or seg.get("segment_text") or seg.get("content") or "").strip()


def _segment_idx(seg: Dict[str, Any], fallback: int) -> int:
    for key in ("idx", "index", "segment_idx", "seg_idx", "i"):
        if key in seg and isinstance(seg[key], int):
            return seg[key]
    return fallback


def _segment_start(seg: Dict[str, Any]) -> float:
    for key in ("start", "start_s", "begin", "t0"):
        val = seg.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                pass
    return 0.0


def _segment_end(seg: Dict[str, Any]) -> float:
    for key in ("end", "end_s", "finish", "t1"):
        val = seg.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                pass
    # fallback: start + duration if present
    start = _segment_start(seg)
    for key in ("dur", "duration", "seconds"):
        val = seg.get(key)
        if val is not None:
            try:
                return start + float(val)
            except (TypeError, ValueError):
                pass
    return start


def _measure_narrative_resolution(text: str, hook_text: str) -> float:
    """
    Experimental Semantic Tie-breaker:
    Measures true narrative resolution by looking for causal completion,
    outcome statements, and epiphany verbs that indicate a question opened 
    by the hook is being answered.
    """
    text_n = _normalize_text(text)
    text_lower = text_n.lower()
    score = 0.0
    
    # 1. Epiphany / Discovery verbs
    epiphanies = {"realized", "learned", "understood", "discovered", "decided", "figured out", "found out", "turned out"}
    if _has_any(text_lower, epiphanies):
        score += 1.0
        
    # 2. Consequence / Shift markers
    shifts = {"was wrong", "was right", "stopped", "started", "became", "changed", "never", "always", "actually", "the truth is", "in reality"}
    if _has_any(text_lower, shifts):
        score += 0.8
        
    # 3. Absolutes / Final states
    absolutes = {"wrong", "right", "dead", "alive", "broken", "fixed", "over", "done", "impossible", "possible", "sentient", "ruined", "saved"}
    words = set(_content_tokens(text_lower))
    if any(a in words for a in absolutes):
        score += 0.5
        
    # 4. Entity Novelty (minor signal)
    raw_words = text.split()
    if len(raw_words) > 1:
        hook_lower = hook_text.lower()
        entities = sum(1 for w in raw_words[1:] if w[0].isupper() and w.lower() not in hook_lower)
        score += min(0.5, entities * 0.2)
        
    return score


def _span_seconds(start: float, end: float) -> float:
    return max(0.0, float(end) - float(start))


def _lexical_overlap(a: str, b: str) -> float:
    ta = set(_content_tokens(a))
    tb = set(_content_tokens(b))
    if not ta or not tb:
        return 0.0
    inter = ta & tb
    union = ta | tb
    return len(inter) / max(1, len(union))


def _count_markers(text: str, markers: Iterable[str]) -> int:
    t = _normalize_text(text)
    return sum(1 for m in markers if m in t)


def _has_any(text: str, markers: Iterable[str]) -> bool:
    t = _normalize_text(text)
    return any(m in t for m in markers)


def _question_signature(text: str) -> bool:
    return "?" in text


def _sentence_count(text: str) -> int:
    parts = [p for p in _SENTENCE_BREAK_RE.split(text) if p.strip()]
    return max(1, len(parts))


# ---------------------------------------------------------------------------
# Promise inference (fallback; prefer importing the project version)
# ---------------------------------------------------------------------------

def _fallback_infer_narrative_promise_and_debt(hook_text: str) -> tuple[str, str, str]:
    """
    Fallback promise inference used when the project version is unavailable.
    Prefer the project-level implementation in utils/narrative_intelligence.py.
    """
    text = _normalize_text(hook_text)

    if "one thing" in text or "highest leverage" in text or "singular" in text or "single" in text:
        return (
            "I will reveal the highest leverage thing.",
            "Need singular highest-leverage answer",
            PromiseType.SINGULAR_LEVERAGE,
        )
    if text.startswith("how ") or " how " in f" {text} " or _has_any(text, PROCESS_MARKERS):
        return (
            "I will explain the mechanism or process.",
            "Need process/mechanism explanation",
            PromiseType.PROCESS_EXPLANATION,
        )
    if text.startswith("why ") or " why " in f" {text} " or _has_any(text, CAUSE_MARKERS):
        return (
            "I will reveal the underlying reason.",
            "Need cause/explanation",
            PromiseType.CAUSE_REVELATION,
        )
    if _has_any(text, {"mistake", "wrong", "fail", "failure", "stop"}):
        return (
            "I will explain what people do wrong.",
            "Need failure cause and correction",
            PromiseType.RECOMMENDATION,
        )
    if _has_any(text, {"story", "happened", "remember", "when i", "when he", "when they"}):
        return (
            "I will tell you an interesting story.",
            "Need story resolution/climax",
            PromiseType.NARRATIVE_CLIMAX,
        )
    if text.startswith("what ") or " what " in f" {text} " or _has_any(text, {"secret", "the thing", "the key"}):
        return (
            "I will reveal the specific thing or secret.",
            "Need singular answer/revelation",
            PromiseType.SINGULAR_LEVERAGE,
        )
    return (
        "I will share an interesting insight.",
        "Need satisfying conclusion/insight",
        PromiseType.GENERAL_INSIGHT,
    )


def infer_narrative_promise_and_debt(hook_text: str) -> tuple[str, str, str]:
    """
    Canonical promise/debt inference entrypoint.

    If the repo's narrative_intelligence module provides the function, use it.
    Otherwise fall back to the local heuristic implementation.
    """
    if _project_infer_narrative_promise_and_debt is not None:
        try:
            return _project_infer_narrative_promise_and_debt(hook_text)
        except Exception:
            log.exception("Project promise inference failed; using fallback heuristics.")
    return _fallback_infer_narrative_promise_and_debt(hook_text)



# ---------------------------------------------------------------------------
# Payoff Engine
# ---------------------------------------------------------------------------

class PayoffEngine:
    """
    Narrative Resolver:
    - scores candidate spans against a StoryThread's promise/debt
    - preserves explanations for every score
    - keeps top-5 hypotheses
    - is intentionally deterministic and inspectable

    The engine is designed to be strong on structure:
    hook -> promise -> debt -> development -> payoff -> resolution
    """

    # Weighting is intentionally debt-dominant.
    DEFAULT_WEIGHTS = {
        "debt_match": 0.65,
        "specificity": 0.15,
        "closure": 0.10,
        "emotional_release": 0.05,
        "finality": 0.05,
    }

    def __init__(self, top_k: int = 5, min_debt_match: float = 0.4):
        self.top_k = max(1, int(top_k))
        self.min_debt_match = float(min_debt_match)

    # ----- story thread compatibility -------------------------------------------------

    @staticmethod
    def _get_thread_value(thread: Any, key: str, default: Any = None) -> Any:
        if thread is None:
            return default
        if isinstance(thread, dict):
            return thread.get(key, default)
        return getattr(thread, key, default)

    @staticmethod
    def _thread_add_candidate(thread: Any, candidate: Dict[str, Any]) -> None:
        if thread is None:
            return
        try:
            if hasattr(thread, "add_payoff_candidate"):
                thread.add_payoff_candidate(candidate)
            elif isinstance(thread, dict):
                thread.setdefault("payoff_candidates", []).append(candidate)
        except Exception:
            log.exception("Failed to add payoff candidate to thread")

    @staticmethod
    def _thread_add_history(thread: Any, stage: str, action: str, reason: str, confidence: float) -> None:
        if thread is None:
            return
        try:
            if hasattr(thread, "add_history"):
                thread.add_history(stage, action, reason, confidence)
            elif isinstance(thread, dict):
                thread.setdefault("history", []).append({
                    "stage": stage,
                    "action": action,
                    "reason": reason,
                    "confidence": confidence,
                })
        except Exception:
            log.exception("Failed to add history to thread")

    @staticmethod
    def _thread_set_resolution(thread: Any, resolution_score: float, confidence_score: float, state: str) -> None:
        if thread is None:
            return
        try:
            if hasattr(thread, "set_resolution"):
                thread.set_resolution(resolution_score, confidence_score, state)
            else:
                if isinstance(thread, dict):
                    thread["resolution_score"] = resolution_score
                    thread["confidence_score"] = confidence_score
                    thread["state"] = state
        except Exception:
            log.exception("Failed to set resolution on thread")

    # ----- promise frame ---------------------------------------------------------------

    def _make_promise_frame(self, thread: Any, hook_segment: Dict[str, Any]) -> PromiseFrame:
        hook_text = str(_safe_get(thread, "hook_text", "") or _segment_text(hook_segment))
        promise = str(self._get_thread_value(thread, "promise", "") or "").strip()
        debt = str(self._get_thread_value(thread, "narrative_debt", "") or "").strip()
        promise_type = str(self._get_thread_value(thread, "promise_type", "UNKNOWN") or "UNKNOWN").strip()

        if not promise or not debt or promise_type == "UNKNOWN":
            promise, debt, promise_type = infer_narrative_promise_and_debt(hook_text)

        rationale = f"hook='{hook_text[:60]}' promise_type={promise_type}"
        hints = self._promise_hints(promise_type)
        return PromiseFrame(promise=promise, debt=debt, promise_type=promise_type, rationale=rationale, hints=hints)

    def _promise_hints(self, promise_type: str) -> List[str]:
        hint_map = {
            PromiseType.PROCESS_EXPLANATION: [
                "process", "mechanism", "steps", "how it works", "sequence"
            ],
            PromiseType.CAUSE_REVELATION: [
                "because", "reason", "cause", "why it happens"
            ],
            PromiseType.SINGULAR_LEVERAGE: [
                "the one thing", "single answer", "highest leverage", "bottleneck"
            ],
            PromiseType.RECOMMENDATION: [
                "what to do", "what to stop", "action", "correction"
            ],
            PromiseType.NARRATIVE_CLIMAX: [
                "story climax", "turning point", "what happened", "landing"
            ],
            PromiseType.GENERAL_INSIGHT: [
                "insight", "lesson", "meaning", "takeaway"
            ],
        }
        return hint_map.get(promise_type, ["general resolution"])

    # ----- candidate span generation ---------------------------------------------------

    def _build_span_candidates(
        self,
        candidate_window: Sequence[Dict[str, Any]],
        max_span_segments: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Build 1..N segment spans from the candidate window.
        This lets the engine resolve multi-segment payoffs instead of only single lines.
        """
        cleaned = [c for c in candidate_window if _segment_text(c)]
        spans: List[Dict[str, Any]] = []

        for i in range(len(cleaned)):
            for span_len in range(1, max_span_segments + 1):
                j = i + span_len
                if j > len(cleaned):
                    break
                parts = cleaned[i:j]
                text = " ".join(_segment_text(p) for p in parts).strip()
                if not text:
                    continue
                start = _segment_start(parts[0])
                end = _segment_end(parts[-1])
                idxs = [_segment_idx(p, fallback=k) for k, p in enumerate(parts, start=i)]
                spans.append({
                    "idxs": idxs,
                    "text": text,
                    "start": start,
                    "end": end,
                    "parts": parts,
                })

        # Deduplicate by exact text/start/end
        deduped = []
        seen = set()
        for s in spans:
            key = (s["text"], round(s["start"], 3), round(s["end"], 3))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(s)
        return deduped

    # ----- scoring primitives ----------------------------------------------------------

    def _score_promise_match(self, text: str, promise_frame: PromiseFrame) -> Tuple[float, List[str]]:
        """
        A structural score for whether the candidate fulfills the promise type.
        This is a *gate*, not a vibe score.
        """
        text_n = _normalize_text(text)
        promise_type = promise_frame.promise_type
        rationale = []
        score = 0.20  # conservative base

        # Generic structural clues shared across most strong payoffs
        if _has_any(text_n, CLOSURE_MARKERS):
            score += 0.08
            rationale.append("closure marker")
        if _has_any(text_n, FINALITY_MARKERS):
            score += 0.10
            rationale.append("finality marker")
        if _question_signature(text_n):
            # Questions can be payoffs in some narratives, but generally not a payoff unless
            # the hook itself was a question that gets answered. Keep this small.
            score += 0.02
            rationale.append("question form")

        # Type-specific structural logic
        if promise_type == PromiseType.PROCESS_EXPLANATION:
            hits = sum(
                1 for t in PROCESS_MARKERS
                if t in text_n
            )
            if hits:
                score += min(0.60, 0.18 + 0.10 * hits)
                rationale.append(f"process hits={hits}")
            if re.search(r"\b(first|then|next|after that|finally)\b", text_n):
                score += 0.12
                rationale.append("ordered sequence")
            if re.search(r"\b(how|way it works|mechanism|flow)\b", text_n):
                score += 0.10
                rationale.append("mechanism language")

        elif promise_type == PromiseType.CAUSE_REVELATION:
            hits = sum(1 for t in CAUSE_MARKERS if t in text_n)
            if hits:
                score += min(0.60, 0.20 + 0.10 * hits)
                rationale.append(f"cause hits={hits}")
            if re.search(r"\b(that's why|because|due to|reason)\b", text_n):
                score += 0.15
                rationale.append("explicit cause phrase")
            if re.search(r"\bso\b", text_n) and len(_tokens(text_n)) > 8:
                score += 0.05
                rationale.append("causal closure")

        elif promise_type == PromiseType.SINGULAR_LEVERAGE:
            hits = sum(1 for t in SINGULAR_MARKERS if t in text_n)
            if hits:
                score += min(0.60, 0.22 + 0.10 * hits)
                rationale.append(f"singular hits={hits}")
            if re.search(r"\b(one thing|the one|only|single|highest leverage)\b", text_n):
                score += 0.18
                rationale.append("singular leverage phrasing")
            if re.search(r"\b(bottleneck|constraint|priority|focus)\b", text_n):
                score += 0.12
                rationale.append("priority framing")
            if re.search(r"\b(5%|95%)\b", text_n):
                score += 0.08
                rationale.append("leverage ratio")

        elif promise_type == PromiseType.RECOMMENDATION:
            hits = sum(1 for t in RECOMMENDATION_MARKERS if t in text_n)
            if hits:
                score += min(0.60, 0.20 + 0.10 * hits)
                rationale.append(f"recommendation hits={hits}")
            if re.search(r"\b(you should|you need to|you must|stop|don't|do this)\b", text_n):
                score += 0.15
                rationale.append("directive language")

        elif promise_type == PromiseType.NARRATIVE_CLIMAX:
            hits = sum(1 for t in {"then", "finally", "happened", "realized", "turned out"} if t in text_n)
            if hits:
                score += min(0.60, 0.16 + 0.10 * hits)
                rationale.append(f"climax hits={hits}")
            if _sentence_count(text_n) >= 2 or len(_tokens(text_n)) > 12:
                score += 0.05
                rationale.append("story-like span")

        else:  # GENERAL_INSIGHT / UNKNOWN
            hits = sum(1 for t in {"meaning", "so", "therefore", "that's why"} if t in text_n)
            if hits:
                score += min(0.35, 0.10 * hits)
                rationale.append(f"insight hits={hits}")
            if len(_tokens(text_n)) > 9:
                score += 0.05
                rationale.append("insight length")

        return min(1.0, score), rationale

    def _score_specificity(self, text: str) -> float:
        """
        Specificity prefers concrete, non-generic resolution language.
        """
        text_n = _normalize_text(text)
        tokens = _tokens(text_n)
        content = _content_tokens(text_n)

        score = 0.35

        if len(tokens) >= 8:
            score += 0.12
        if len(tokens) >= 14:
            score += 0.08

        if _NUM_RE.search(text_n):
            score += 0.12

        concrete_markers = {
            "money", "time", "calendar", "customers", "bottleneck", "support",
            "assistant", "flow", "throughput", "volume", "work", "business",
            "results", "priority", "focus", "steps", "process", "constraint",
            "deliver", "execute", "input", "output",
        }
        concrete_hits = sum(1 for t in content if t in concrete_markers)
        score += min(0.18, 0.03 * concrete_hits)

        # Penalize overly generic filler
        generic_phrases = {
            "interesting insight", "what matters", "you know", "kind of", "stuff",
            "things", "something like", "sort of", "i guess", "maybe", "right?",
        }
        if any(p in text_n for p in generic_phrases):
            score -= 0.10

        # Prefer sentences that contain a clear noun chunk feel
        if len(content) >= 6:
            score += 0.05

        return max(0.0, min(1.0, score))

    def _score_closure(self, text: str) -> float:
        text_n = _normalize_text(text)
        score = 0.30

        if _has_any(text_n, CLOSURE_MARKERS):
            score += 0.35
        if text_n.startswith(("so ", "therefore ", "meaning ", "that's why ")):
            score += 0.10
        if _question_signature(text_n):
            # question endings are usually weaker closure than declarative endings
            score -= 0.05
        if _sentence_count(text_n) >= 2:
            score += 0.05

        # if the sentence sounds like a wrap-up, boost it a bit
        if re.search(r"\b(this means|what this means|bottom line|the point is)\b", text_n):
            score += 0.15

        return max(0.0, min(1.0, score))

    def _score_emotional_release(self, text: str) -> float:
        text_n = _normalize_text(text)
        score = 0.20

        if _has_any(text_n, EMOTIONAL_RELEASE_MARKERS):
            score += 0.35
        if re.search(r"\b(wow|crazy|insane|wild|amazing|huge|powerful)\b", text_n):
            score += 0.10
        if re.search(r"\b(honestly|really|actually)\b", text_n):
            score += 0.05

        return max(0.0, min(1.0, score))

    def _score_finality(self, text: str) -> float:
        text_n = _normalize_text(text)
        score = 0.25

        if _has_any(text_n, FINALITY_MARKERS):
            score += 0.45
        if re.search(r"\b(period|full stop|that's all|nothing else|end of story)\b", text_n):
            score += 0.20
        if re.search(r"\b(locked|done|final|complete|resolved)\b", text_n):
            score += 0.10
        if text_n.endswith((".", "!", "?")):
            score += 0.03

        return max(0.0, min(1.0, score))

    def _score_development_alignment(
        self,
        text: str,
        thread: Any,
        promise_frame: PromiseFrame,
    ) -> float:
        """
        How much this candidate feels like the continuation of the same story,
        not just a topical neighbor.
        """
        candidate_tokens = set(_content_tokens(text))
        if not candidate_tokens:
            return 0.0

        hook_text = str(self._get_thread_value(thread, "hook_text", "") or "")
        thread_development_points = self._get_thread_value(thread, "development_points", []) or []
        suppressed_children = self._get_thread_value(thread, "suppressed_children", []) or []

        contexts: List[str] = [hook_text]
        for dp in thread_development_points:
            if isinstance(dp, dict):
                contexts.append(str(dp.get("text", "")))
            else:
                contexts.append(str(dp))
        for sc in suppressed_children:
            if isinstance(sc, dict):
                contexts.append(str(sc.get("text", "")))
            else:
                contexts.append(str(sc))

        # Use maximum overlap against any thread context
        overlaps = [_lexical_overlap(text, ctx) for ctx in contexts if ctx]
        overlap = max(overlaps) if overlaps else 0.0

        # More alignment when candidate repeats the thematic vocabulary established by the thread
        debt_tokens = set(_content_tokens(promise_frame.debt))
        promise_tokens = set(_content_tokens(promise_frame.promise))
        thematic_overlap = 0.0
        if debt_tokens:
            thematic_overlap += len(candidate_tokens & debt_tokens) / max(1, len(candidate_tokens | debt_tokens))
        if promise_tokens:
            thematic_overlap += len(candidate_tokens & promise_tokens) / max(1, len(candidate_tokens | promise_tokens))

        thematic_overlap = min(1.0, thematic_overlap)

        # boost when the candidate resonates with suppressed child language
        child_overlap = 0.0
        if suppressed_children:
            child_overlap = max(_lexical_overlap(text, c if isinstance(c, str) else str(c)) for c in suppressed_children)

        # keep it conservative; this should help, not dominate
        score = 0.45 * overlap + 0.35 * thematic_overlap + 0.20 * child_overlap
        return max(0.0, min(1.0, score))

    def _score_boundary_crispness(self, text: str) -> float:
        """
        Boundary crispness asks: does the candidate feel like a clean stopping point?
        """
        text_n = _normalize_text(text)
        score = 0.30

        # A sentence that sounds like a conclusion and is not too long tends to be crisp.
        token_len = len(_tokens(text_n))
        if 6 <= token_len <= 24:
            score += 0.20
        if token_len > 24:
            score -= 0.10
        if _has_any(text_n, FINALITY_MARKERS):
            score += 0.20
        if _has_any(text_n, CLOSURE_MARKERS):
            score += 0.10
        if re.search(r"\b(and then|then|so|therefore|meaning)\b", text_n):
            score += 0.05

        return max(0.0, min(1.0, score))

    def _score_span(
        self,
        span: Dict[str, Any],
        thread: Any,
        hook_segment: Dict[str, Any],
        promise_frame: PromiseFrame,
    ) -> CandidateScore:
        text = str(span["text"])
        promise_match, promise_rationale = self._score_promise_match(text, promise_frame)
        debt_match = promise_match  # alias for external compatibility
        specificity = self._score_specificity(text)
        closure = self._score_closure(text)
        emotional_release = self._score_emotional_release(text)
        finality = self._score_finality(text)
        development_alignment = self._score_development_alignment(text, thread, promise_frame)
        boundary_crispness = self._score_boundary_crispness(text)

        # [FEATURE] Apply Payoff Prediction
        predicted_payoff = str(self._get_thread_value(thread, "predicted_payoff_description", "") or "")
        expected_keywords = self._get_thread_value(thread, "expected_keywords", []) or []
        predicted_match = 0.0
        if predicted_payoff:
            predicted_match += 0.3 * _lexical_overlap(text, predicted_payoff)
            kw_hits = sum(1 for kw in expected_keywords if kw.lower() in text.lower())
            if expected_keywords:
                predicted_match += 0.7 * min(1.0, kw_hits / max(1, len(expected_keywords)))
        
        predicted_match = min(1.0, predicted_match)
        
        # Boost structural scores if semantic prediction hits
        if predicted_match > 0.2:
            debt_match = min(1.0, debt_match + (predicted_match * 0.4))
            promise_match = min(1.0, promise_match + (predicted_match * 0.4))

        # Slight time-based shaping:
        # - too early after hook: unlikely to be full payoff
        # - too late within an excessive window: risk of drift
        hook_start = float(self._get_thread_value(thread, "start_s", _segment_start(hook_segment)) or _segment_start(hook_segment))
        span_start = float(span["start"])
        span_end = float(span["end"])
        delta = max(0.0, span_start - hook_start)

        timing_score = 0.55
        if 15 <= delta <= 40:
            timing_score += 0.05
        elif 40 < delta <= 90:
            timing_score += 0.25  # sweet spot for full narrative build-up
        else:
            timing_score -= 0.05

        # A direct payoff should often sit near the tail of the candidate window.
        if span_end >= hook_start and span_end - span_start <= 60:
            timing_score += 0.03

        # final score emphasizes the promise fulfillment and development relationship
        final_score = (
            promise_match * 0.40 +
            debt_match * 0.25 +
            development_alignment * 0.15 +
            specificity * 0.08 +
            closure * 0.05 +
            finality * 0.04 +
            emotional_release * 0.02 +
            boundary_crispness * 0.01
        )

        # Apply timing shaping gently
        final_score = final_score * (0.85 + 0.15 * timing_score)

        # Graduated penalty for short clips to force ArcAssembler to find a later payoff
        if delta < 35:
            penalty = 0.60 * (1.0 - (delta / 35.0))
            final_score -= penalty

        rationale = []
        rationale.extend(promise_rationale)
        if predicted_match > 0.2:
            rationale.append(f"predictive match={predicted_match:.2f}")
        if development_alignment > 0.15:
            rationale.append("development alignment")
        if boundary_crispness > 0.55:
            rationale.append("crisp boundary")
        if specificity > 0.65:
            rationale.append("specific")
        if closure > 0.60:
            rationale.append("closure")
        if finality > 0.60:
            rationale.append("finality")
        if emotional_release > 0.60:
            rationale.append("emotional release")

        rejection_reason = None
        if debt_match < self.min_debt_match:
            rejection_reason = f"debt_match<{self.min_debt_match:.2f}"
        elif promise_frame.promise_type == PromiseType.SINGULAR_LEVERAGE and debt_match < 0.55:
            rejection_reason = "insufficient singular leverage resolution"
        elif promise_frame.promise_type == PromiseType.PROCESS_EXPLANATION and debt_match < 0.50:
            rejection_reason = "insufficient process explanation"
        elif promise_frame.promise_type == PromiseType.CAUSE_REVELATION and debt_match < 0.50:
            rejection_reason = "insufficient causal revelation"

        return CandidateScore(
            idxs=list(span["idxs"]),
            text=text,
            start=float(span["start"]),
            end=float(span["end"]),
            promise_match=promise_match,
            debt_match=debt_match,
            development_alignment=development_alignment,
            specificity=specificity,
            closure=closure,
            emotional_release=emotional_release,
            finality=finality,
            boundary_crispness=boundary_crispness,
            final_score=max(0.0, min(1.0, final_score)),
            rejection_reason=rejection_reason,
            rationale=_dedupe_preserve_order(rationale),
        )

    # ----- public API -----------------------------------------------------------------

    def resolve(
        self,
        thread: Any,  # StoryThread or compatible dict/object
        transcript_segments: List[Dict[str, Any]],
        hook_segment: Dict[str, Any],
        candidate_window: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Evaluate a candidate window and return the strongest payoff hypotheses.

        Returns a structured resolution result:
        {
            "top_candidates": [...],
            "winner": {...} or None,
            "state": "RESOLVED|OPEN|CONTINUED|SEARCH_FAILED",
            "promise": "...",
            "debt": "...",
            "promise_type": "...",
            "resolution_score": float,
            "confidence_score": float,
        }
        """
        # Build or recover promise frame from thread
        promise_frame = self._make_promise_frame(thread, hook_segment)

        # Keep the thread in sync for downstream observability
        if not self._get_thread_value(thread, "promise", None):
            self._set_thread_field(thread, "promise", promise_frame.promise)
        if not self._get_thread_value(thread, "narrative_debt", None):
            self._set_thread_field(thread, "narrative_debt", promise_frame.debt)
        if not self._get_thread_value(thread, "promise_type", None) or self._get_thread_value(thread, "promise_type", "UNKNOWN") == "UNKNOWN":
            self._set_thread_field(thread, "promise_type", promise_frame.promise_type)

        spans = self._build_span_candidates(candidate_window, max_span_segments=3)
        scored: List[CandidateScore] = []

        for span in spans:
            scored_candidate = self._score_span(span, thread, hook_segment, promise_frame)

            rejection_reason = None
            # Removed over-aggressive debt_match hard rejects so clips are ranked by holistic score.
            # if scored_candidate.debt_match < self.min_debt_match:
            #     rejection_reason = f"debt_match_below_min ({scored_candidate.debt_match:.2f} < {self.min_debt_match})"
            
            # Allow telemetry but don't drop the candidate
            if scored_candidate.debt_match < self.min_debt_match:
                # Telemetry for what WOULD have been rejected
                human_accept = (scored_candidate.finality > 0.6 or scored_candidate.closure > 0.6 or scored_candidate.boundary_crispness > 0.6)
                if human_accept:
                    # log.info("\n=========================================================")
                    # log.info("WEAK DEBT MATCH (KEPT)\n")
                    pass

            scored.append(scored_candidate)

        # Experimental Semantic Tie-breaker
        hook_t = str(hook_segment.get("text", ""))
        use_experimental = os.getenv("HS_EXPERIMENTAL_SEMANTIC_TIEBREAKER", "0").strip() == "1"
        
        for c in scored:
            if use_experimental:
                c.information_gain = _measure_narrative_resolution(c.text, hook_t)
            else:
                c.information_gain = 0.0

        if use_experimental:
            # Sort primarily by final_score (rounded to bucket similar structural scores),
            # then narrative resolution (semantic), then crispness (boundary).
            scored.sort(key=lambda c: (round(c.final_score, 2), c.information_gain, c.boundary_crispness), reverse=True)
        else:
            # Default structural sort
            scored.sort(key=lambda c: (c.final_score, c.debt_match, c.boundary_crispness), reverse=True)
            
        top_candidates = scored[: self.top_k]

        # Write candidates into thread for observability.
        for cand in top_candidates:
            self._thread_add_candidate(thread, cand.as_dict())

        winner: Optional[CandidateScore] = top_candidates[0] if top_candidates else None

        # ------------------------------------------------------------------
        # THREE-TIER RESOLVER FALLBACK
        # If the keyword gate rejected every candidate, run the structural /
        # embedding resolver (Tier 1 & 2) before giving up.
        # Tier 3 (Groq) is queued here and fired in bulk by the orchestrator.
        # ------------------------------------------------------------------
        resolver_seg: Optional[Dict[str, Any]] = None
        if (winner is None or winner.final_score < 0.55) and candidate_window:
            try:
                from utils.payoff_resolver import PayoffResolver
                _resolver = PayoffResolver()
                hook_text_val = str(self._get_thread_value(thread, "hook_text", _segment_text(hook_segment)) or "")
                hook_start_val = float(_segment_start(hook_segment))
                thread_id_val = str(
                    self._get_thread_value(thread, "thread_id",
                        self._get_thread_value(thread, "trace_id", "unknown")) or "unknown"
                )
                resolver_seg = _resolver.find(
                    hook_text=hook_text_val,
                    hook_start_s=hook_start_val,
                    candidate_window=candidate_window,
                    full_transcript=list(transcript_segments),
                    thread_id=thread_id_val,
                )
            except Exception as _exc:
                log.warning("[PAYOFF_ENGINE] PayoffResolver failed: %s", _exc)

        # If Tier1/Tier2 found a winner, synthesize it as a lightweight winner dict
        resolver_winner: Optional[Dict[str, Any]] = None
        if resolver_seg is not None:
            tier = resolver_seg.get("tier", "?")
            tier_score = resolver_seg.get(
                f"tier{tier}_score",
                resolver_seg.get("tier1_score", resolver_seg.get("tier2_score", 0.5)),
            )
            resolver_winner = {
                "idxs": [resolver_seg.get("idx", -1)],
                "text": str(resolver_seg.get("text", "")),
                "start": float(resolver_seg.get("start", 0.0)),
                "end": float(resolver_seg.get("end", 0.0)),
                "promise_match": float(tier_score),
                "debt_match": float(tier_score),
                "development_alignment": 0.0,
                "specificity": 0.5,
                "closure": float(tier_score),
                "emotional_release": 0.0,
                "finality": float(tier_score),
                "boundary_crispness": float(tier_score),
                "final_score": float(tier_score),
                "rejection_reason": None,
                "rationale": [f"tier{tier}_resolver"],
            }
            log.info(
                "\n[PAYOFF_ENGINE] RESOLVER_FALLBACK tier=%s score=%.2f text='%s'",
                tier, tier_score, resolver_winner["text"][:60],
            )

        # Compare winner and resolver_winner to find the true strongest payoff
        best_candidate = None
        is_resolver = False

        if winner and resolver_winner:
            if float(resolver_winner["final_score"]) > float(winner.final_score):
                best_candidate = resolver_winner
                is_resolver = True
            else:
                best_candidate = winner
                is_resolver = False
        elif resolver_winner:
            best_candidate = resolver_winner
            is_resolver = True
        elif winner:
            best_candidate = winner
            is_resolver = False

        # Resolution logic using the best candidate
        if best_candidate and not is_resolver:
            winner_c = best_candidate  # type CandidateScore
            resolution_score = float(winner_c.final_score)
            confidence_score = float(min(1.0, max(winner_c.debt_match, winner_c.development_alignment, winner_c.boundary_crispness)))

            # Conservative state machine
            if resolution_score >= 0.80 and winner_c.debt_match >= 0.60:
                state = "RESOLVED"
            elif resolution_score >= 0.55:
                state = "CONTINUED"
            else:
                state = "SEARCH_FAILED"

            self._thread_set_resolution(thread, resolution_score, confidence_score, state)
            self._set_thread_field(thread, "winning_payoff", winner_c.text)
            self._set_thread_field(thread, "payoff_candidate", winner_c.text)
            self._set_thread_field(thread, "payoff_candidate_score", winner_c.final_score)
            self._thread_add_history(
                thread,
                stage="PAYOFF_ENGINE",
                action="RESOLVE",
                reason=f"winner_final_score={winner_c.final_score:.3f} debt_match={winner_c.debt_match:.3f}",
                confidence=confidence_score,
            )
        elif best_candidate and is_resolver:
            res_winner = best_candidate  # type Dict
            resolution_score = float(res_winner["final_score"])
            confidence_score = float(res_winner["closure"])
            
            if resolution_score >= 0.85:
                state = "RESOLVED"
            else:
                state = "CONTINUED"

            self._thread_set_resolution(thread, resolution_score, confidence_score, state)
            self._set_thread_field(thread, "winning_payoff", res_winner["text"])
            self._set_thread_field(thread, "payoff_candidate", res_winner["text"])
            self._set_thread_field(thread, "payoff_candidate_score", resolution_score)
            self._thread_add_history(
                thread,
                stage="PAYOFF_ENGINE",
                action="RESOLVER_FALLBACK",
                reason=f"tier{res_winner['rationale'][0]} structural resolver score={resolution_score:.2f}",
                confidence=confidence_score,
            )
        else:
            resolution_score = 0.0
            confidence_score = 0.0
            state = "SEARCH_FAILED"
            self._thread_set_resolution(thread, resolution_score, confidence_score, state)
            self._thread_add_history(
                thread,
                stage="PAYOFF_ENGINE",
                action="SEARCH_FAILED",
                reason="no candidate passed keyword gates or structural resolver",
                confidence=0.0,
            )

        # Merge resolver_winner into top_candidates list for telemetry
        final_winner_dict = None
        if resolver_winner and winner:
            if resolver_winner["final_score"] > winner.final_score:
                final_winner_dict = resolver_winner
            else:
                final_winner_dict = winner.as_dict()
        elif resolver_winner:
            final_winner_dict = resolver_winner
        elif winner:
            final_winner_dict = winner.as_dict()

        all_top = [c.as_dict() for c in top_candidates]
        if resolver_winner and (not final_winner_dict or final_winner_dict == resolver_winner):
            # Insert at the top if it won or if winner was None
            all_top.insert(0, resolver_winner)

        # Certificate-style output for downstream telemetry
        result = {
            "thread_id": self._get_thread_value(thread, "thread_id", self._get_thread_value(thread, "trace_id", "unknown")),
            "hook_text": self._get_thread_value(thread, "hook_text", _segment_text(hook_segment)),
            "promise": self._get_thread_value(thread, "promise", promise_frame.promise),
            "debt": self._get_thread_value(thread, "narrative_debt", promise_frame.debt),
            "promise_type": self._get_thread_value(thread, "promise_type", promise_frame.promise_type),
            "contract": self._get_thread_value(thread, "contract", {}),
            "top_candidates": all_top,
            "winner": final_winner_dict,
            "resolution_score": round(resolution_score, 3),
            "confidence_score": round(confidence_score, 3),
            "state": state,
            "should_stop": state == "RESOLVED",
            "certificate": {
                "why_won": winner.rationale if winner else (resolver_winner["rationale"] if resolver_winner else []),
                "rejected_count": max(0, len(scored) - len(top_candidates)),
                "resolver_tier": resolver_seg.get("tier") if resolver_seg else None,
            },
        }

        # Lightweight log for observability.
        self._log_resolution(result)
        return result

    # ----- misc helpers ---------------------------------------------------------------

    def _set_thread_field(self, thread: Any, key: str, value: Any) -> None:
        if thread is None:
            return
        try:
            if isinstance(thread, dict):
                thread[key] = value
            else:
                setattr(thread, key, value)
        except Exception:
            log.exception("Failed to set thread field %s", key)

    def _log_resolution(self, result: Dict[str, Any]) -> None:
        # Emit PAYOFF_SOURCE entry for observability
        try:
            source = result.get("certificate", {}).get("resolver_tier")
            if source:
                cid = result.get("winner", {}).get("idxs", ["unknown"])[0]
                log_line = (
                    f"[PAYOFF_SOURCE]\n"
                    f"cid={cid}\n"
                    f"source=TIER{source}\n"
                )
                with open(os.path.join(self._project_root, "payoff_source.log"), "a") as f:
                    f.write(log_line + "\n")
        except Exception:
            pass

        try:
            log.info("\n=========================================================")
            log.info("GOVERNOR NARRATIVE REPORT")
            log.info("=========================================================\n")
            
            contract_info = result.get("contract", {}) or {}
            promise_type = result.get("promise_type", "UNKNOWN")
            
            log.info("HOOK:\n\"%s\"\n", result.get("hook_text"))
            log.info("CONTRACT:\n%s\n", promise_type.lower())
            
            winner = result.get("winner")
            if winner:
                log.info("FRAME:\n%s\n", winner.get("idxs", []))
                log.info("RESOLUTION:\n\"%s\"\n", winner.get("text", "").strip())
                
                pm = winner.get("promise_match", winner.get("debt_match", 0.0))
                da = winner.get("development_alignment", 0.0)
                cl = winner.get("closure", 0.0)
                
                log.info("SCORES:\ncontract_match=%.2f\ndevelopment=%.2f\nresolution=%.2f\n", pm, da, cl)
                log.info("FINAL=%.2f\n", winner.get("final_score", 0.0))
            else:
                log.info("FRAME:\n[]\n")
                log.info("RESOLUTION:\nNONE\n")
                log.info("SCORES:\ncontract_match=0.00\ndevelopment=0.00\nresolution=0.00\n")
                log.info("FINAL=0.00\n")
                
            log.info("THREAD STATE: %s", result.get("state"))
            log.info("=========================================================\n")
        except Exception:
            # Logging should never crash the pipeline.
            log.exception("Failed to log payoff resolution")


__all__ = [
    "PayoffEngine",
    "PromiseType",
    "PromiseFrame",
    "CandidateScore",
    "infer_narrative_promise_and_debt",
]
