from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from viral_finder.cognition_cache import CognitionCache, FrameWindow


@dataclass(frozen=True)
class EscalationMemoryConfig:
    tension_threshold: float = 0.58
    resolution_threshold: float = 0.52
    release_threshold: float = 0.62
    lookahead_sec: float = 14.0
    max_extend_sec: float = 14.0


def _mean(vals) -> float:
    vals = list(vals or [])
    if not vals:
        return 0.0
    return float(sum(float(v or 0.0) for v in vals)) / float(len(vals))


def seconds_to_frames(cache: CognitionCache, sec: float) -> int:
    if cache.n <= 1:
        return 1
    avg = _mean([(f.end - f.start) for f in cache.frames])
    avg = max(0.25, avg)
    return max(1, int(round(float(sec) / avg)))


def resolution_completeness(window: FrameWindow, cache: CognitionCache) -> float:
    if cache.n == 0 or not window.valid(cache.n):
        return 0.0
    payoff_mean = cache.slice_mean("role:PAYOFF", window.s, window.e)
    rp_start = cache.resolution_pressure[window.s]
    rp_end = cache.resolution_pressure[window.e]
    rp_drop = max(0.0, rp_start - rp_end)
    return max(0.0, min(1.0, (0.62 * payoff_mean) + (0.38 * rp_drop)))


def future_window_scan(cache: CognitionCache, end_idx: int, lookahead_sec: float) -> Tuple[int, float]:
    if cache.n == 0:
        return 0, 0.0
    end_idx = max(0, min(end_idx, cache.last_idx))
    max_idx = min(cache.last_idx, end_idx + seconds_to_frames(cache, lookahead_sec))
    best_idx = end_idx
    best = 0.0
    for j in range(end_idx + 1, max_idx + 1):
        d_rp = cache.resolution_pressure[j] - cache.resolution_pressure[j - 1]
        closure = cache.frames[j].closure_evidence if 0 <= j < cache.n else 0.0
        rel = (
            0.35 * cache.role_post.get("PAYOFF", [0.0] * cache.n)[j]
            + 0.30 * max(0.0, -d_rp)
            + 0.20 * cache.cadence_drop[j]
            + 0.15 * cache.energy_decel[j]
            + 0.15 * closure
        )
        if rel > best:
            best = rel
            best_idx = j
    return best_idx, float(best)


def escalation_memory_extend(
    window: FrameWindow,
    cache: CognitionCache,
    cfg: EscalationMemoryConfig = EscalationMemoryConfig(),
) -> FrameWindow:
    if cache.n == 0 or not window.valid(cache.n):
        return window
    tension = cache.slice_mean("resolution_pressure", window.s, window.e) * cache.slice_mean("escalation", window.s, window.e)
    rc = resolution_completeness(window, cache)
    if tension < cfg.tension_threshold or rc >= cfg.resolution_threshold:
        return window

    j, release = future_window_scan(cache, window.e, cfg.lookahead_sec)
    max_extra = seconds_to_frames(cache, cfg.max_extend_sec)
    if release >= cfg.release_threshold and (j - window.e) <= max_extra:
        return FrameWindow(window.s, j)
    return window
