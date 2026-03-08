from __future__ import annotations

from typing import Dict, List, Tuple

ROLES = ("HOOK", "BUILD", "CONFLICT", "PEAK", "PAYOFF", "REFLECTION")
ROLE_TO_IDX = {r: i for i, r in enumerate(ROLES)}


def _clamp01(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return float(x)


def _local_max(series: List[float], i: int) -> bool:
    cur = float(series[i] or 0.0)
    prev = cur if i <= 0 else float(series[i - 1] or 0.0)
    nxt = cur if i >= len(series) - 1 else float(series[i + 1] or 0.0)
    return cur >= prev and cur >= nxt


def _emission(
    i: int,
    n: int,
    energy: List[float],
    escalation: List[float],
    resolution_pressure: List[float],
    conflict: List[float],
    curiosity_delta: List[float],
    punch: List[float],
    semantic_density: List[float],
) -> Dict[str, float]:
    e = float(energy[i] or 0.0)
    esc = float(escalation[i] or 0.0)
    res = float(resolution_pressure[i] or 0.0)
    conf = float(conflict[i] or 0.0)
    cur = float(curiosity_delta[i] or 0.0)
    pu = float(punch[i] or 0.0)
    sem = float(semantic_density[i] or 0.0)
    dres = 0.0 if i == 0 else (float(resolution_pressure[i - 1] or 0.0) - res)
    early = 1.0 if i <= max(1, int(0.30 * n)) else 0.0
    late = 1.0 if i >= int(0.60 * n) else 0.0

    out = {
        "HOOK": _clamp01(0.35 * cur + 0.30 * esc + 0.20 * pu + 0.15 * early),
        "BUILD": _clamp01(0.45 * esc + 0.30 * res + 0.15 * sem + 0.10 * cur),
        "CONFLICT": _clamp01(0.55 * conf + 0.20 * esc + 0.15 * res + 0.10 * pu),
        "PEAK": _clamp01(0.35 * e + 0.35 * esc + 0.20 * pu + (0.10 if _local_max(energy, i) else 0.0)),
        "PAYOFF": _clamp01(0.40 * pu + 0.25 * dres + 0.20 * e + 0.15 * late),
        "REFLECTION": _clamp01(0.35 * sem + 0.30 * (1.0 - conf) + 0.20 * (1.0 - esc) + 0.15 * late),
    }
    return out


def decode_roles(
    energy: List[float],
    escalation: List[float],
    resolution_pressure: List[float],
    conflict: List[float],
    curiosity_delta: List[float],
    punch: List[float],
    semantic_density: List[float],
) -> Tuple[List[str], Dict[str, List[float]]]:
    n = len(energy)
    if n == 0:
        return [], {r: [] for r in ROLES}

    emissions: List[Dict[str, float]] = [
        _emission(
            i=i,
            n=n,
            energy=energy,
            escalation=escalation,
            resolution_pressure=resolution_pressure,
            conflict=conflict,
            curiosity_delta=curiosity_delta,
            punch=punch,
            semantic_density=semantic_density,
        )
        for i in range(n)
    ]

    # Stage-constrained decoding to avoid degenerate flat labeling.
    peak_idx = max(range(n), key=lambda i: (energy[i] + escalation[i] + punch[i]))
    payoff_idx = -1
    best_payoff = -1.0
    for i in range(peak_idx, n):
        dres = 0.0 if i == 0 else max(0.0, resolution_pressure[i - 1] - resolution_pressure[i])
        s = emissions[i]["PAYOFF"] + (0.35 * dres)
        if s > best_payoff:
            best_payoff = s
            payoff_idx = i
    if payoff_idx < peak_idx:
        payoff_idx = peak_idx

    hook_end = max(0, min(peak_idx, int(0.30 * n)))
    roles: List[str] = ["BUILD" for _ in range(n)]
    for i in range(n):
        if i == peak_idx:
            roles[i] = "PEAK"
            continue
        if i == payoff_idx and i >= peak_idx:
            roles[i] = "PAYOFF"
            continue
        if i < hook_end:
            roles[i] = "HOOK" if emissions[i]["HOOK"] >= emissions[i]["BUILD"] else "BUILD"
            continue
        if i < peak_idx:
            roles[i] = "CONFLICT" if emissions[i]["CONFLICT"] >= emissions[i]["BUILD"] else "BUILD"
            continue
        if i > payoff_idx:
            roles[i] = "REFLECTION"
            continue
        roles[i] = "CONFLICT" if emissions[i]["CONFLICT"] >= emissions[i]["BUILD"] else "BUILD"

    # Ensure explicit payoff exists after peak for arc completeness logic.
    if not any(r == "PAYOFF" for r in roles[peak_idx:]):
        roles[min(n - 1, peak_idx + 1)] = "PAYOFF"

    role_post = {r: [0.0 for _ in range(n)] for r in ROLES}
    for i in range(n):
        total = 0.0
        vals = []
        for r in ROLES:
            v = max(1e-6, emissions[i][r])
            vals.append(v)
            total += v
        for ridx, r in enumerate(ROLES):
            role_post[r][i] = vals[ridx] / total
    return roles, role_post
