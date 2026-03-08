from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class FrameFeatures:
    idx: int
    start: float
    end: float
    text: str
    intensity: float
    semantic_density: float
    cadence_compression: float
    surprise: float
    punch_impulse: float
    open_loops: float
    deferred_claims: float
    closure_evidence: float
    stance_divergence: float
    contradiction_signal: float
    polarity_whiplash: float
    novelty: float
    question_tension: float
    abstraction_density: float
    idea_compression: float
    metaphor_density: float
    contradiction_complexity: float
    novelty_shift: float


@dataclass(frozen=True)
class FrameWindow:
    s: int
    e: int

    def valid(self, n: int) -> bool:
        return 0 <= self.s < n and 0 <= self.e < n and self.s <= self.e

    def length(self) -> int:
        return max(0, self.e - self.s + 1)


@dataclass
class CognitionCache:
    frames: List[FrameFeatures]
    energy: List[float]
    escalation: List[float]
    resolution_pressure: List[float]
    conflict: List[float]
    curiosity_delta: List[float]
    cadence_drop: List[float]
    energy_decel: List[float]
    depth: List[float]
    roles: List[str]
    role_post: Dict[str, List[float]]
    prefix: Dict[str, List[float]]
    zone_indices: Dict[str, List[int]]

    @property
    def n(self) -> int:
        return len(self.frames)

    @property
    def last_idx(self) -> int:
        return max(0, self.n - 1)

    def slice_mean(self, series_name: str, s: int, e: int) -> float:
        if self.n == 0:
            return 0.0
        s = max(0, min(s, self.last_idx))
        e = max(s, min(e, self.last_idx))
        pref = self.prefix.get(series_name)
        if not pref:
            return 0.0
        total = pref[e + 1] - pref[s]
        return float(total) / float(max(1, e - s + 1))

    def slice_sum(self, series_name: str, s: int, e: int) -> float:
        if self.n == 0:
            return 0.0
        s = max(0, min(s, self.last_idx))
        e = max(s, min(e, self.last_idx))
        pref = self.prefix.get(series_name)
        if not pref:
            return 0.0
        return float(pref[e + 1] - pref[s])


def prefix_sum(series: List[float]) -> List[float]:
    out = [0.0]
    run = 0.0
    for v in series:
        run += float(v or 0.0)
        out.append(run)
    return out

