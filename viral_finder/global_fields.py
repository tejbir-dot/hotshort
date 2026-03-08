from __future__ import annotations

import math
import re
from typing import Dict, List, Optional, Sequence, Tuple

from viral_finder.cognition_cache import CognitionCache, FrameFeatures, prefix_sum
from viral_finder.role_tagger import decode_roles

ROLE_NAMES = ("HOOK", "BUILD", "CONFLICT", "PEAK", "PAYOFF", "REFLECTION")
WORD_RE = re.compile(r"\w+", flags=re.UNICODE)


def _sigmoid(x: float) -> float:
    x = max(-60.0, min(60.0, float(x or 0.0)))
    return 1.0 / (1.0 + math.exp(-x))


def _relu(x: float) -> float:
    return x if x > 0.0 else 0.0


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(x or 0.0)))


def _mean(vals: Sequence[float]) -> float:
    if not vals:
        return 0.0
    return float(sum(float(v or 0.0) for v in vals)) / float(len(vals))


def _median(vals: Sequence[float]) -> float:
    if not vals:
        return 0.0
    arr = sorted(float(v or 0.0) for v in vals)
    n = len(arr)
    m = n // 2
    if n % 2 == 1:
        return arr[m]
    return 0.5 * (arr[m - 1] + arr[m])


def _percentile(vals: Sequence[float], q: float) -> float:
    if not vals:
        return 0.0
    arr = sorted(float(v or 0.0) for v in vals)
    if len(arr) == 1:
        return arr[0]
    q = _clip(q, 0.0, 100.0)
    pos = (len(arr) - 1) * (q / 100.0)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return arr[lo]
    w = pos - lo
    return arr[lo] + (arr[hi] - arr[lo]) * w


def _iqr(vals: Sequence[float]) -> float:
    return _percentile(vals, 75.0) - _percentile(vals, 25.0)


def _robust_norm(series: Sequence[float], eps: float = 1e-6) -> List[float]:
    vals = [float(v or 0.0) for v in series]
    if not vals:
        return []
    med = _median(vals)
    spread = _iqr(vals)
    if spread <= eps:
        mn = min(vals)
        mx = max(vals)
        span = max(eps, mx - mn)
        return [_sigmoid(_clip((v - mn) / span, -3.5, 3.5)) for v in vals]
    out = []
    for v in vals:
        z = _clip((v - med) / (spread + eps), -3.5, 3.5)
        out.append(_sigmoid(z))
    return out


def _moving_average(series: Sequence[float], k: int = 3) -> List[float]:
    vals = [float(v or 0.0) for v in series]
    if not vals:
        return []
    k = max(1, int(k))
    if k == 1:
        return vals
    half = k // 2
    out: List[float] = []
    n = len(vals)
    for i in range(n):
        s = max(0, i - half)
        e = min(n, i + half + 1)
        out.append(_mean(vals[s:e]))
    return out


def _delta(series: Sequence[float]) -> List[float]:
    vals = [float(v or 0.0) for v in series]
    if not vals:
        return []
    out = [0.0]
    for i in range(1, len(vals)):
        out.append(vals[i] - vals[i - 1])
    return out


def _extract_time_series(
    points: Optional[List[Dict]],
    key: str,
    frames: List[Tuple[float, float]],
    fallback_key: str = "time",
) -> List[float]:
    if not frames:
        return []
    if not points:
        return [0.0 for _ in frames]
    out: List[float] = []
    for s, e in frames:
        vals = []
        for p in points:
            try:
                t = float(p.get(fallback_key, p.get("start", 0.0)) or 0.0)
                if s <= t <= e:
                    vals.append(float(p.get(key, 0.0) or 0.0))
            except Exception:
                continue
        out.append(_mean(vals) if vals else 0.0)
    return out


def _tokenize(text: str) -> List[str]:
    return WORD_RE.findall((text or "").lower())


def _clause_count(text: str) -> int:
    if not text:
        return 0
    return max(1, len(re.split(r"[,:;.!?]\s*", text.strip())))


def _segment_frames(transcript: List[Dict]) -> List[Tuple[float, float, str]]:
    out: List[Tuple[float, float, str]] = []
    for seg in transcript or []:
        try:
            s = float(seg.get("start", 0.0) or 0.0)
            e = float(seg.get("end", s) or s)
        except Exception:
            continue
        if e <= s:
            e = s + 0.5
        out.append((s, e, str(seg.get("text", "") or "").strip()))
    return out


def _depth_channels(tokens: List[str], text: str, duration: float, prev_tokens: List[str]) -> Tuple[float, float, float, float, float]:
    word_count = max(1, len(tokens))
    lower = text.lower()
    abstract_hits = sum(
        1 for t in tokens if t.endswith(("tion", "ism", "ity", "ness", "ment")) or t in {"system", "model", "principle", "pattern", "framework"}
    )
    abstraction = _clip(float(abstract_hits) / float(word_count), 0.0, 1.0)

    clauses = _clause_count(text)
    idea_compression = _clip(float(clauses) / float(max(1.0, duration * 1.6)), 0.0, 1.0)

    metaphor_markers = sum(1 for t in ("like", "as if", "imagine", "is a", "becomes") if t in lower)
    metaphor_density = _clip(float(metaphor_markers) / 3.0, 0.0, 1.0)

    contradiction_markers = sum(1 for t in ("but", "however", "yet", "although", "despite", "instead") if t in lower)
    negations = sum(1 for t in tokens if t in {"not", "never", "no", "none", "nothing"})
    contradiction_complexity = _clip((0.65 * contradiction_markers + 0.35 * negations) / 3.0, 0.0, 1.0)

    prev = set(prev_tokens)
    cur = set(tokens)
    union = len(prev | cur)
    novelty_shift = 0.0 if union == 0 else (1.0 - (len(prev & cur) / float(union)))
    novelty_shift = _clip(novelty_shift, 0.0, 1.0)

    return abstraction, idea_compression, metaphor_density, contradiction_complexity, novelty_shift


def build_cognition_cache(
    transcript: List[Dict],
    aud: Optional[List[Dict]] = None,
    vis: Optional[List[Dict]] = None,
    semantic_enhancer: bool = False,
) -> CognitionCache:
    segs = _segment_frames(transcript)
    if not segs:
        return CognitionCache(
            frames=[],
            energy=[],
            escalation=[],
            resolution_pressure=[],
            conflict=[],
            curiosity_delta=[],
            cadence_drop=[],
            energy_decel=[],
            depth=[],
            roles=[],
            role_post={k: [] for k in ROLE_NAMES},
            prefix={},
            zone_indices={"peaks": [], "escalation": [], "conflict": []},
        )

    frame_windows = [(s, e) for s, e, _ in segs]
    audio_energy = _extract_time_series(aud, "energy", frame_windows)
    motion = _extract_time_series(vis, "motion", frame_windows)

    text_word_counts = [len(_tokenize(t)) for _, _, t in segs]
    durations = [max(0.35, (e - s)) for s, e, _ in segs]
    semantic_density_raw = [float(wc) / d for wc, d in zip(text_word_counts, durations)]

    punctuation_impulse_raw = []
    surprise_raw = []
    open_loops_raw = []
    deferred_claims_raw = []
    closure_evidence_raw = []
    stance_div_raw = []
    contradiction_signal_raw = []
    polarity_whiplash_raw = []
    novelty_raw = []
    question_tension_raw = []
    cadence_compression_raw = []
    depth_channels: List[Tuple[float, float, float, float, float]] = []
    prev_tokens: List[str] = []

    for i, (_, _, text) in enumerate(segs):
        tokens = _tokenize(text)
        lower = text.lower()
        punc = min(1.0, text.count("!") * 0.35 + text.count("?") * 0.45 + text.count("...") * 0.25)
        punctuation_impulse_raw.append(punc)

        novelty_local = 1.0
        if i > 0:
            prev = set(prev_tokens)
            cur = set(tokens)
            union = len(prev | cur)
            novelty_local = 0.0 if union == 0 else (1.0 - (len(prev & cur) / float(union)))
        novelty_raw.append(_clip(novelty_local, 0.0, 1.0))

        surprise_raw.append(_clip(0.45 * punc + 0.55 * novelty_local, 0.0, 1.0))
        question_tension_raw.append(_clip(0.7 if "?" in text else 0.0 + (0.2 if "why" in lower or "how" in lower else 0.0), 0.0, 1.0))

        open_loops = 0.0
        if "?" in text:
            open_loops += 0.5
        if any(m in lower for m in ("wait", "but", "however", "later", "soon", "next")):
            open_loops += 0.25
        open_loops_raw.append(_clip(open_loops, 0.0, 1.0))

        deferred = 0.0
        if any(m in lower for m in ("i will", "we will", "going to", "let me", "i'll")):
            deferred += 0.55
        if any(m in lower for m in ("first", "second", "third", "next")):
            deferred += 0.25
        deferred_claims_raw.append(_clip(deferred, 0.0, 1.0))

        closure = 0.0
        if any(m in lower for m in ("so", "therefore", "that means", "that's why", "in short", "bottom line")):
            closure += 0.7
        if text.strip().endswith((".", "!")):
            closure += 0.2
        closure_evidence_raw.append(_clip(closure, 0.0, 1.0))

        contrast_markers = sum(1 for m in ("but", "however", "yet", "although", "instead", "despite") if m in lower)
        neg_markers = sum(1 for t in tokens if t in {"not", "never", "no", "none"})
        stance_div_raw.append(_clip((contrast_markers * 0.35) + (neg_markers * 0.22), 0.0, 1.0))
        contradiction_signal_raw.append(_clip((contrast_markers * 0.45) + (neg_markers * 0.2), 0.0, 1.0))
        polarity_whiplash_raw.append(_clip((1.0 if contrast_markers > 0 and ("good" in lower or "bad" in lower) else 0.0), 0.0, 1.0))

        clauses = _clause_count(text)
        cadence_compression_raw.append(_clip(float(clauses) / float(max(1.0, durations[i] * 1.2)), 0.0, 1.0))

        depth_channels.append(_depth_channels(tokens, text, durations[i], prev_tokens))
        prev_tokens = tokens

    intensity_raw = [0.58 * a + 0.42 * m for a, m in zip(audio_energy, motion)]

    intensity_n = _robust_norm(intensity_raw)
    sem_density_n = _robust_norm(semantic_density_raw)
    cadence_n = _robust_norm(cadence_compression_raw)
    surprise_n = _robust_norm(surprise_raw)
    punch_n = _robust_norm(punctuation_impulse_raw)
    open_n = _robust_norm(open_loops_raw)
    deferred_n = _robust_norm(deferred_claims_raw)
    closure_n = _robust_norm(closure_evidence_raw)
    stance_n = _robust_norm(stance_div_raw)
    contradiction_n = _robust_norm(contradiction_signal_raw)
    whiplash_n = _robust_norm(polarity_whiplash_raw)
    novelty_n = _robust_norm(novelty_raw)
    question_n = _robust_norm(question_tension_raw)

    energy = [
        _sigmoid(
            0.30 * intensity_n[i]
            + 0.20 * sem_density_n[i]
            + 0.18 * cadence_n[i]
            + 0.16 * surprise_n[i]
            + 0.16 * punch_n[i]
        )
        for i in range(len(segs))
    ]
    energy = _moving_average(energy, 3)
    d_energy = _delta(energy)
    dd_energy = _delta(d_energy)
    d_sem = _delta(sem_density_n)
    escalation = [
        _relu(d_energy[i]) + 0.55 * _relu(dd_energy[i]) + 0.35 * _relu(d_sem[i]) for i in range(len(segs))
    ]
    escalation = _moving_average(escalation, 3)

    resolution_pressure = [
        _sigmoid(0.45 * open_n[i] + 0.30 * deferred_n[i] - 0.25 * closure_n[i]) for i in range(len(segs))
    ]
    resolution_pressure = _moving_average(resolution_pressure, 3)

    conflict = [
        _sigmoid(0.50 * stance_n[i] + 0.30 * contradiction_n[i] + 0.20 * whiplash_n[i]) for i in range(len(segs))
    ]
    conflict = _moving_average(conflict, 3)

    d_open = _delta(open_n)
    d_novelty = _delta(novelty_n)
    curiosity_delta = [_relu(d_open[i]) + 0.40 * _relu(d_novelty[i]) + 0.25 * question_n[i] for i in range(len(segs))]
    curiosity_delta = _moving_average(curiosity_delta, 3)

    cadence_drop = [max(0.0, (cadence_n[i - 1] - cadence_n[i]) if i > 0 else 0.0) for i in range(len(segs))]
    energy_decel = [max(0.0, (d_energy[i - 1] - d_energy[i]) if i > 0 else 0.0) for i in range(len(segs))]

    depth_raw = []
    for a, c, m, k, n in depth_channels:
        structural_depth = 0.24 * a + 0.22 * c + 0.16 * m + 0.20 * k + 0.18 * n
        if semantic_enhancer:
            structural_depth = _clip((0.92 * structural_depth) + (0.08 * (0.5 * n + 0.5 * k)), 0.0, 1.0)
        depth_raw.append(structural_depth)
    depth = _moving_average(depth_raw, 3)

    frames: List[FrameFeatures] = []
    for i, (s, e, text) in enumerate(segs):
        a, c, m, k, n = depth_channels[i]
        frames.append(
            FrameFeatures(
                idx=i,
                start=float(s),
                end=float(e),
                text=text,
                intensity=float(intensity_n[i]),
                semantic_density=float(sem_density_n[i]),
                cadence_compression=float(cadence_n[i]),
                surprise=float(surprise_n[i]),
                punch_impulse=float(punch_n[i]),
                open_loops=float(open_n[i]),
                deferred_claims=float(deferred_n[i]),
                closure_evidence=float(closure_n[i]),
                stance_divergence=float(stance_n[i]),
                contradiction_signal=float(contradiction_n[i]),
                polarity_whiplash=float(whiplash_n[i]),
                novelty=float(novelty_n[i]),
                question_tension=float(question_n[i]),
                abstraction_density=float(a),
                idea_compression=float(c),
                metaphor_density=float(m),
                contradiction_complexity=float(k),
                novelty_shift=float(n),
            )
        )

    roles, role_post = decode_roles(
        energy=energy,
        escalation=escalation,
        resolution_pressure=resolution_pressure,
        conflict=conflict,
        curiosity_delta=curiosity_delta,
        punch=punch_n,
        semantic_density=sem_density_n,
    )

    prefix: Dict[str, List[float]] = {
        "energy": prefix_sum(energy),
        "escalation": prefix_sum(escalation),
        "resolution_pressure": prefix_sum(resolution_pressure),
        "conflict": prefix_sum(conflict),
        "curiosity_delta": prefix_sum(curiosity_delta),
        "depth": prefix_sum(depth),
        "cadence_drop": prefix_sum(cadence_drop),
        "energy_decel": prefix_sum(energy_decel),
        "punch": prefix_sum(punch_n),
    }
    for role_name in ROLE_NAMES:
        prefix[f"role:{role_name}"] = prefix_sum(role_post.get(role_name, []))

    peaks = []
    esc_zones = []
    conf_zones = []
    for i in range(len(frames)):
        local_total = energy[i] + escalation[i] + punch_n[i]
        prev_total = local_total if i == 0 else (energy[i - 1] + escalation[i - 1] + punch_n[i - 1])
        next_total = local_total if i >= len(frames) - 1 else (energy[i + 1] + escalation[i + 1] + punch_n[i + 1])
        if local_total >= prev_total and local_total >= next_total and local_total > 0.60:
            peaks.append(i)
        if escalation[i] > 0.24:
            esc_zones.append(i)
        if conflict[i] > 0.58:
            conf_zones.append(i)

    return CognitionCache(
        frames=frames,
        energy=energy,
        escalation=escalation,
        resolution_pressure=resolution_pressure,
        conflict=conflict,
        curiosity_delta=curiosity_delta,
        cadence_drop=cadence_drop,
        energy_decel=energy_decel,
        depth=depth,
        roles=roles,
        role_post=role_post,
        prefix=prefix,
        zone_indices={"peaks": peaks, "escalation": esc_zones, "conflict": conf_zones},
    )

