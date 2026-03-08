from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from viral_finder.cognition_cache import CognitionCache, FrameWindow
from viral_finder.escalation_memory import EscalationMemoryConfig, escalation_memory_extend, resolution_completeness


@dataclass(frozen=True)
class OverrideState:
    applied: bool
    score: float = 0.0
    coalesce_relax: float = 0.0
    overlap_penalty_scale: float = 1.0


@dataclass
class Candidate:
    window: FrameWindow
    impact_score: float
    arc_complete: bool
    override: OverrideState
    cluster_id: int = -1


@dataclass(frozen=True)
class SelectorConfig:
    top_k: int = 8
    min_window_sec: float = 10.0
    max_window_sec: float = 46.0
    override_thr: float = 0.82
    lookahead_sec: float = 14.0
    dominance_over_count: bool = True


def _clamp01(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return float(x)


def _mean(vals: List[float]) -> float:
    if not vals:
        return 0.0
    return float(sum(float(v or 0.0) for v in vals)) / float(len(vals))


def _trimmed_mean(vals: List[float], trim: float = 0.1) -> float:
    if not vals:
        return 0.0
    arr = sorted(float(v or 0.0) for v in vals)
    n = len(arr)
    k = int(n * trim)
    if k * 2 >= n:
        return _mean(arr)
    core = arr[k : n - k]
    return _mean(core)


def _percentile(vals: List[float], q: float) -> float:
    if not vals:
        return 0.0
    arr = sorted(float(v or 0.0) for v in vals)
    if len(arr) == 1:
        return arr[0]
    q = max(0.0, min(100.0, q))
    pos = (len(arr) - 1) * (q / 100.0)
    lo = int(pos)
    hi = min(len(arr) - 1, lo + 1)
    w = pos - lo
    return arr[lo] + (arr[hi] - arr[lo]) * w


def _frames_to_seconds(cache: CognitionCache, frames: int) -> float:
    if cache.n == 0:
        return 0.0
    avg = _mean([(f.end - f.start) for f in cache.frames])
    return float(frames) * max(0.25, avg)


def _seconds_to_frames(cache: CognitionCache, sec: float) -> int:
    if cache.n == 0:
        return 1
    avg = _mean([(f.end - f.start) for f in cache.frames])
    avg = max(0.25, avg)
    return max(1, int(round(float(sec) / avg)))


def _window_text(cache: CognitionCache, w: FrameWindow) -> str:
    parts = []
    for i in range(w.s, w.e + 1):
        t = cache.frames[i].text.strip()
        if t:
            parts.append(t)
    return " ".join(parts).strip()


def _token_set(txt: str) -> set:
    return set((txt or "").lower().split())


def _text_overlap(a: str, b: str) -> float:
    sa = _token_set(a)
    sb = _token_set(b)
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    uni = len(sa | sb)
    return float(inter) / float(max(1, uni))


def _arc_complete(cache: CognitionCache, w: FrameWindow) -> bool:
    n = max(1, w.e - w.s + 1)
    cutoff = w.s + int(0.35 * n)
    late_cutoff = w.s + int(0.70 * n)
    hook_or_build = False
    peak_idx = -1
    payoff_after_peak = False
    local_rp_peak = 0.0
    for i in range(w.s, w.e + 1):
        r = cache.roles[i]
        if i <= cutoff and r in ("HOOK", "BUILD"):
            hook_or_build = True
        if r == "PEAK" and i < late_cutoff and peak_idx < 0:
            peak_idx = i
        if peak_idx >= 0 and i > peak_idx and r == "PAYOFF":
            payoff_after_peak = True
        local_rp_peak = max(local_rp_peak, cache.resolution_pressure[i])
    rp_drop = local_rp_peak - cache.resolution_pressure[w.e]
    return bool(hook_or_build and peak_idx >= 0 and payoff_after_peak and rp_drop >= 0.18)


def _agg_escalation(cache: CognitionCache, w: FrameWindow) -> float:
    vals = cache.escalation[w.s : w.e + 1]
    burst = max(vals) if vals else 0.0
    return _clamp01(0.75 * _trimmed_mean(vals, trim=0.1) + 0.25 * burst)


def _agg_punch(cache: CognitionCache, w: FrameWindow) -> float:
    punch_vals = [cache.frames[i].punch_impulse for i in range(w.s, w.e + 1)]
    cadence = [cache.frames[i].cadence_compression for i in range(w.s, w.e + 1)]
    return _clamp01(0.62 * max(punch_vals or [0.0]) + 0.38 * _trimmed_mean(cadence, trim=0.1))


def _agg_depth(cache: CognitionCache, w: FrameWindow) -> float:
    return _clamp01(_trimmed_mean(cache.depth[w.s : w.e + 1], trim=0.1))


def _agg_curiosity(cache: CognitionCache, w: FrameWindow) -> float:
    return _clamp01(_trimmed_mean(cache.curiosity_delta[w.s : w.e + 1], trim=0.1))


def _agg_conflict(cache: CognitionCache, w: FrameWindow) -> float:
    return _clamp01(_trimmed_mean(cache.conflict[w.s : w.e + 1], trim=0.1))


def _impact_score(cache: CognitionCache, w: FrameWindow) -> float:
    esc_delta = _agg_escalation(cache, w)
    punch = _agg_punch(cache, w)
    depth = _agg_depth(cache, w)
    cur = _agg_curiosity(cache, w)
    conf = _agg_conflict(cache, w)
    rc = resolution_completeness(w, cache)

    score = (0.27 * esc_delta) + (0.22 * punch) + (0.16 * depth) + (0.12 * cur) + (0.11 * conf) + (0.12 * rc)
    if _arc_complete(cache, w):
        score *= 1.10
    elif rc < 0.45:
        score *= 0.82
    return _clamp01(score)


def _peak_prominence(cache: CognitionCache, w: FrameWindow) -> float:
    vals = [cache.energy[i] + cache.escalation[i] + cache.frames[i].punch_impulse for i in range(w.s, w.e + 1)]
    if not vals:
        return 0.0
    return _clamp01(max(vals) - _mean(vals))


def _escalation_burst(cache: CognitionCache, w: FrameWindow) -> float:
    vals = cache.escalation[w.s : w.e + 1]
    if not vals:
        return 0.0
    top = sorted(vals, reverse=True)[: max(1, len(vals) // 5)]
    return _clamp01(_mean(top))


def _conflict_spike(cache: CognitionCache, w: FrameWindow) -> float:
    vals = cache.conflict[w.s : w.e + 1]
    return _clamp01(max(vals or [0.0]))


def _override_score(cache: CognitionCache, w: FrameWindow) -> float:
    punch = _agg_punch(cache, w)
    burst = _escalation_burst(cache, w)
    prominence = _peak_prominence(cache, w)
    conflict_spike = _conflict_spike(cache, w)
    return _clamp01((0.50 * punch) + (0.25 * burst) + (0.15 * prominence) + (0.10 * conflict_spike))


def _apply_override(cache: CognitionCache, w: FrameWindow, cfg: SelectorConfig) -> Tuple[FrameWindow, OverrideState]:
    punch_vals = [cache.frames[i].punch_impulse for i in range(w.s, w.e + 1)]
    punch_p97 = _percentile([f.punch_impulse for f in cache.frames], 97.0)
    punch_peak = max(punch_vals or [0.0])
    ovs = _override_score(cache, w)
    trigger = (punch_peak >= punch_p97) or (ovs >= cfg.override_thr)
    if not trigger:
        return w, OverrideState(False, score=ovs)

    expand_frames = max(1, int((w.e - w.s + 1) * 0.60))
    nw = FrameWindow(w.s, min(cache.last_idx, w.e + expand_frames))

    # cross-boundary merge behavior: pull start left if continuity around boundary is high.
    if nw.s > 0:
        gap_energy = abs(cache.energy[nw.s] - cache.energy[nw.s - 1])
        esc_cont = 1.0 - min(1.0, gap_energy)
        if esc_cont >= 0.60:
            nw = FrameWindow(max(0, nw.s - min(3, nw.s)), nw.e)

    if _arc_complete(cache, nw):
        # trim to first strong payoff after peak
        peak = None
        payoff = None
        for i in range(nw.s, nw.e + 1):
            if peak is None and cache.roles[i] == "PEAK":
                peak = i
            if peak is not None and i > peak and cache.roles[i] == "PAYOFF":
                payoff = i
                break
        if payoff is not None:
            tail = min(cache.last_idx, payoff + 2)
            nw = FrameWindow(nw.s, max(nw.s, tail))
    return nw, OverrideState(True, score=ovs, coalesce_relax=-0.18, overlap_penalty_scale=0.35)


def _seed_windows(cache: CognitionCache, cfg: SelectorConfig) -> List[FrameWindow]:
    if cache.n == 0:
        return []
    min_f = _seconds_to_frames(cache, cfg.min_window_sec)
    max_f = _seconds_to_frames(cache, cfg.max_window_sec)
    seeds = set(cache.zone_indices.get("peaks", []))
    seeds.update(cache.zone_indices.get("escalation", []))
    seeds.update(cache.zone_indices.get("conflict", []))
    if not seeds:
        seeds = {max(0, cache.n // 3), max(0, (2 * cache.n) // 3)}
    windows: List[FrameWindow] = []
    for idx in sorted(seeds):
        local_esc = cache.escalation[idx]
        pad_left = max(1, int(min_f * (0.45 + (0.4 * min(1.0, local_esc)))))
        pad_right = max(1, int(min_f * (0.55 + (0.4 * min(1.0, local_esc)))))
        s = max(0, idx - pad_left)
        e = min(cache.last_idx, idx + pad_right)
        if (e - s + 1) < min_f:
            e = min(cache.last_idx, s + min_f - 1)
        if (e - s + 1) > max_f:
            e = s + max_f - 1
        windows.append(FrameWindow(s, e))
    # coarse dedupe by center distance
    windows = sorted(windows, key=lambda w: (w.s, w.e))
    out: List[FrameWindow] = []
    centers: List[int] = []
    min_gap = max(1, min_f // 2)
    for w in windows:
        c = (w.s + w.e) // 2
        if any(abs(c - x) < min_gap for x in centers):
            continue
        out.append(w)
        centers.append(c)
    return out


def _cluster_candidates(cache: CognitionCache, candidates: List[Candidate]) -> List[List[Candidate]]:
    if not candidates:
        return []
    sorted_c = sorted(candidates, key=lambda c: c.window.s)
    clusters: List[List[Candidate]] = []
    for c in sorted_c:
        attached = False
        txt_c = _window_text(cache, c.window)
        for cl in clusters:
            last = cl[-1]
            temporal_gap = max(0, c.window.s - last.window.e)
            txt_last = _window_text(cache, last.window)
            sem = _text_overlap(txt_c, txt_last)
            esc1 = cache.slice_mean("escalation", c.window.s, c.window.e)
            esc2 = cache.slice_mean("escalation", last.window.s, last.window.e)
            esc_cont = 1.0 - min(1.0, abs(esc1 - esc2))
            if temporal_gap <= 6 and (sem >= 0.22 or esc_cont >= 0.65):
                cl.append(c)
                attached = True
                break
        if not attached:
            clusters.append([c])
    return clusters


def _cluster_score(cache: CognitionCache, cluster: List[Candidate]) -> float:
    if not cluster:
        return 0.0
    impacts = sorted([c.impact_score for c in cluster], reverse=True)
    top3 = impacts[:3]
    max_imp = impacts[0]
    mean_top3 = _mean(top3)
    arc_complete_rate = _mean([1.0 if c.arc_complete else 0.0 for c in cluster])
    esc_cont = 0.0
    if len(cluster) > 1:
        esc_vals = [cache.slice_mean("escalation", c.window.s, c.window.e) for c in cluster]
        esc_cont = 1.0 - min(1.0, (max(esc_vals) - min(esc_vals)))
    payoff_yield = _mean([resolution_completeness(c.window, cache) for c in cluster])
    return _clamp01((0.45 * max_imp) + (0.25 * mean_top3) + (0.15 * arc_complete_rate) + (0.10 * esc_cont) + (0.05 * payoff_yield))


def _best_complete_arc(cluster: List[Candidate]) -> Optional[Candidate]:
    if not cluster:
        return None
    complete = [c for c in cluster if c.arc_complete]
    if complete:
        return sorted(complete, key=lambda c: c.impact_score, reverse=True)[0]
    return sorted(cluster, key=lambda c: c.impact_score, reverse=True)[0]


def _window_to_candidate_dict(cache: CognitionCache, c: Candidate, mode: str) -> Dict:
    w = c.window
    start = cache.frames[w.s].start
    end = cache.frames[w.e].end
    text = _window_text(cache, w)
    role_path = cache.roles[w.s : w.e + 1]
    rc = resolution_completeness(w, cache)
    out = {
        "text": text,
        "start": round(float(start), 2),
        "end": round(float(end), 2),
        "score": round(float(c.impact_score), 4),
        "impact_score": round(float(c.impact_score), 4),
        "arc_complete": bool(c.arc_complete),
        "role_path": role_path,
        "override_applied": bool(c.override.applied),
        "override_score": round(float(c.override.score), 4),
        "resolution_completeness": round(float(rc), 4),
        "cluster_id": int(c.cluster_id),
        "selection_mode": mode,
        "label": "Dominant Arc" if c.arc_complete else "Escalation Arc",
        "reason": "godmode_dominance",
        "why": ["Acceleration preserved", "Peak-to-payoff continuity", "Dominance-first selection"],
        "fingerprint": f"gm:{w.s}:{w.e}:{int(c.arc_complete)}",
    }
    return out


def _dedupe_candidates(items: List[Candidate]) -> List[Candidate]:
    out: List[Candidate] = []
    for c in sorted(items, key=lambda x: x.impact_score, reverse=True):
        drop = False
        for ex in out:
            inter = max(0, min(c.window.e, ex.window.e) - max(c.window.s, ex.window.s) + 1)
            if inter <= 0:
                continue
            short = max(1, min(c.window.length(), ex.window.length()))
            if (inter / float(short)) > 0.72:
                drop = True
                break
        if not drop:
            out.append(c)
    return out


def select_dominant_arcs(
    cache: CognitionCache,
    top_k: int = 8,
    cfg: Optional[SelectorConfig] = None,
    selection_mode: str = "godmode",
) -> List[Dict]:
    if cfg is None:
        cfg = SelectorConfig(top_k=max(1, int(top_k or 1)))
    else:
        cfg = SelectorConfig(
            top_k=max(1, int(top_k or cfg.top_k)),
            min_window_sec=cfg.min_window_sec,
            max_window_sec=cfg.max_window_sec,
            override_thr=cfg.override_thr,
            lookahead_sec=cfg.lookahead_sec,
            dominance_over_count=cfg.dominance_over_count,
        )

    seeds = _seed_windows(cache, cfg)
    if not seeds:
        return []
    mem_cfg = EscalationMemoryConfig(lookahead_sec=cfg.lookahead_sec, max_extend_sec=cfg.lookahead_sec)
    built: List[Candidate] = []
    for w in seeds:
        w1 = escalation_memory_extend(w, cache, cfg=mem_cfg)
        w2, ovs = _apply_override(cache, w1, cfg)
        score = _impact_score(cache, w2)
        built.append(Candidate(window=w2, impact_score=score, arc_complete=_arc_complete(cache, w2), override=ovs))

    built = _dedupe_candidates(built)
    clusters = _cluster_candidates(cache, built)
    if not clusters:
        return []
    scored_clusters = sorted(
        [(idx, cl, _cluster_score(cache, cl)) for idx, cl in enumerate(clusters)],
        key=lambda x: x[2],
        reverse=True,
    )
    dom_idx, dom_cluster, _ = scored_clusters[0]
    locked: List[Candidate] = []
    best = _best_complete_arc(dom_cluster)
    if best is not None:
        best.cluster_id = dom_idx
        locked.append(best)

    if cfg.top_k <= 1:
        return [_window_to_candidate_dict(cache, c, selection_mode) for c in locked]

    # Diversity after dominance: pick top non-overlapping candidates from other clusters.
    rest_pool: List[Candidate] = []
    for idx, cl, _score in scored_clusters:
        for c in cl:
            c.cluster_id = idx
            if idx == dom_idx and c is best:
                continue
            rest_pool.append(c)
    rest_pool = sorted(rest_pool, key=lambda c: c.impact_score, reverse=True)

    picked = list(locked)
    for c in rest_pool:
        if len(picked) >= cfg.top_k:
            break
        overlap = False
        for ex in picked:
            inter = max(0, min(c.window.e, ex.window.e) - max(c.window.s, ex.window.s) + 1)
            if inter <= 0:
                continue
            short = max(1, min(c.window.length(), ex.window.length()))
            if (inter / float(short)) > (0.35 if c.override.applied else 0.60):
                overlap = True
                break
        if not overlap:
            picked.append(c)

    if cfg.dominance_over_count:
        # policy: never force-fill weak windows.
        pass
    else:
        # optional fill mode if caller wants it.
        for c in rest_pool:
            if len(picked) >= cfg.top_k:
                break
            if c not in picked:
                picked.append(c)

    return [_window_to_candidate_dict(cache, c, selection_mode) for c in picked]

