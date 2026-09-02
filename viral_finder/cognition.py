from dataclasses import dataclass, field
from typing import Any, List, Optional

# ---------------------------------------------------------------------------
# INTELLIGENCE TRANSPORT CONTRACT
#
# Every Evidence packet produced by the pipeline MUST end in exactly one of:
#   CONSUMED         — it influenced a downstream decision (consumer was recorded)
#   EXPLICITLY_REJECTED — evaluated and intentionally discarded (reason recorded)
#   ORPHANED         — reached end of pipeline without any consumer (= bug)
#
# Use .consume(consumer_name) to mark CONSUMED.
# Use .reject(reason, consumer_name) to mark EXPLICITLY_REJECTED.
# An un-touched Evidence is automatically classified ORPHANED at audit time.
# ---------------------------------------------------------------------------

class Evidence:
    """
    An atomic unit of intelligence produced by any pipeline component.

    Fields:
        type       — what kind of signal this is (e.g. "stop_scroll", "curiosity_peak")
        value      — the signal value (numeric or bool)
        producer   — which component created it (e.g. "groq_trigger", "curiosity_engine")
        confidence — producer's self-reported confidence in this value [0.0–1.0]

    Transport state (mutable — not frozen):
        _consumed_by        — list of consumers that read this evidence
        _rejected_reason    — reason if explicitly rejected
        _rejected_by        — consumer that rejected it
    """

    __slots__ = ("type", "value", "producer", "confidence",
                 "_consumed_by", "_rejected_reason", "_rejected_by")

    def __init__(self, type: str, value: Any, producer: str, confidence: float = 1.0):
        self.type = type
        self.value = value
        self.producer = producer
        self.confidence = confidence
        # Transport tracking — mutable
        self._consumed_by: List[str] = []
        self._rejected_reason: Optional[str] = None
        self._rejected_by: Optional[str] = None

    def consume(self, consumer: str) -> "Evidence":
        """Mark this evidence as consumed by `consumer`. Returns self for chaining."""
        if consumer not in self._consumed_by:
            self._consumed_by.append(consumer)
        return self

    def reject(self, reason: str, consumer: str) -> "Evidence":
        """Mark this evidence as explicitly rejected (evaluated, not used, reason known)."""
        self._rejected_reason = reason
        self._rejected_by = consumer
        return self

    @property
    def transport_state(self) -> str:
        """Returns: 'CONSUMED', 'EXPLICITLY_REJECTED', or 'ORPHANED'."""
        if self._consumed_by:
            return "CONSUMED"
        if self._rejected_reason is not None:
            return "EXPLICITLY_REJECTED"
        return "ORPHANED"

    @property
    def consumed_by(self) -> List[str]:
        return list(self._consumed_by)

    # Make it usable as a dict key / in sets (hash by identity, not value)
    def __repr__(self) -> str:
        return (
            f"Evidence(type={self.type!r}, value={self.value!r}, "
            f"producer={self.producer!r}, confidence={self.confidence}, "
            f"state={self.transport_state})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Evidence):
            return NotImplemented
        return (self.type == other.type and self.value == other.value
                and self.producer == other.producer and self.confidence == other.confidence)

    def __hash__(self):
        return hash((self.type, self.producer, id(self)))


@dataclass
class IntelligenceArtifact:
    evidence_stream: List[Evidence] = field(default_factory=list)

    def get_evidence(self, ev_type: str) -> List[Evidence]:
        """Returns all evidence objects of a specific type."""
        return [e for e in self.evidence_stream if e.type == ev_type]

    def get_max_value(self, ev_type: str, default: float = 0.0, consumer: Optional[str] = None) -> float:
        """
        Helper to get the maximum numeric value for a specific evidence type.
        If `consumer` is provided, marks matched evidence as consumed.
        """
        matches = self.get_evidence(ev_type)
        if not matches:
            return default
        try:
            numeric_vals = []
            for m in matches:
                if isinstance(m.value, (int, float, str)) and str(m.value).replace('.', '', 1).isdigit():
                    numeric_vals.append((float(m.value), m))
            if not numeric_vals:
                return default
            best_val, best_ev = max(numeric_vals, key=lambda x: x[0])
            if consumer:
                for _, ev in numeric_vals:
                    ev.consume(consumer)
            return best_val
        except Exception:
            return default

    def get_bool(self, ev_type: str, default: bool = False, consumer: Optional[str] = None) -> bool:
        """
        Helper to check if any evidence of this type evaluates to True.
        If `consumer` is provided, marks matched evidence as consumed.
        """
        matches = self.get_evidence(ev_type)
        if not matches:
            return default
        result = any(bool(m.value) is True for m in matches)
        if consumer:
            for m in matches:
                m.consume(consumer)
        return result


@dataclass
class TriggerArtifact:
    trigger_type: str
    psychology: dict
    reason: str
    confidence: float
    trace_id: str


@dataclass
class NarrativeContract:
    """
    A complete psychological debt cycle: hook creates a promise, payoff resolves it.

    A clip is 'contract-complete' only when it contains BOTH sides.
    A clip with ONLY a hook is a fragment — viral potential wasted.
    A clip with ONLY a payoff has no reason to watch it through.

    contract_score = debt_score × resolution_score (0->1)
    """
    hook_trigger: dict          # The trigger that creates narrative debt
    payoff_trigger: dict        # The trigger that resolves the debt
    hook_start: float           # Where the debt begins
    payoff_end: float           # Where the debt resolves
    debt_score: float           # How strongly the hook creates curiosity/tension
    resolution_score: float     # How fully the payoff delivers
    contract_score: float       # debt × resolution — the combined virality score
    hook_type: str              # e.g. 'strong_claim', 'belief_reversal'
    payoff_type: str            # e.g. 'payoff', 'complete_thought'
    trace_id: str
