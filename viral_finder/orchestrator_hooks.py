"""
orchestrator_hooks.py

Support utilities to produce 1..N independent, high-quality clip variations
around each detected ignition/punch. Drop into viral_finder/ and import from
orchestrator.py (orchestrator will call these to expand ignitions -> unique clips).

What this file provides:
  - select_clip_start(ignitions, goal)
  - generate_punch_clips(ignitions, video_duration, ...)
  - simple text_overlap and dedupe helpers (safe, dependency-free fallbacks)

Design goals:
  - produce multiple *independent* clips per ignition (up to `max_per_ignition`)
  - diversity by using different "angles" (main-punch, curiosity-lead, authority-anchor,
    micro-snap) so clips feel unique and human-curated
  - robust dedupe by time range and semantic overlap
  - safe fallbacks so it runs even without large ML deps

Usage:
  from viral_finder.orchestrator_hooks import generate_punch_clips
  clips = generate_punch_clips(ignitions, video_duration, pre_roll=5, post_roll=15)

"""
from typing import List, Dict, Optional, Tuple
import math
import hashlib
import random

# Tunables
MIN_CLIP_DURATION = 2.0
MIN_INDEPENDENT_SPACING = 3.0  # seconds between independent clips starts
DEFAULT_PRE_ROLL = 5.0
DEFAULT_POST_ROLL = 15.0

# --- light-weight helpers ---

def _text_tokens(text: str):
    return [t.strip(".,!?;:\"'()[]").lower() for t in (text or "").split() if t.strip()]


def text_overlap(a: str, b: str) -> float:
    """Simple, fast token/bigram overlap fallback. Returns 0..1."""
    if not a or not b:
        return 0.0
    A = set(_text_tokens(a))
    B = set(_text_tokens(b))
    if not A or not B:
        return 0.0
    j = len(A & B) / len(A | B)
    def bigrams(s):
        w = [t for t in s.split() if t]
        return set(zip(w, w[1:])) if len(w) > 1 else set()
    bigA = bigrams(a)
    bigB = bigrams(b)
    big_boost = (len(bigA & bigB) / (len(bigA | bigB) + 1e-9)) if (bigA or bigB) else 0.0
    return float((0.6 * j) + (0.4 * big_boost))


def _fingerprint(text: str, start: float, end: float) -> str:
    key = f"{round(start,1)}-{round(end,1)}|{(' '.join(_text_tokens(text)))[:200]}"
    return hashlib.md5(key.encode("utf-8")).hexdigest()


def dedupe_by_time(clips: List[dict], time_tol: float = 0.5) -> List[dict]:
    if not clips:
        return []
    buckets = {}
    for c in clips:
        key = (round(c["start"] / time_tol), round(c["end"] / time_tol))
        if key not in buckets or c["score"] > buckets[key]["score"]:
            buckets[key] = c
    outs = list(buckets.values())
    outs.sort(key=lambda x: x["start"])
    return outs


# --- learning weights placeholder ---

def get_punch_weights() -> Dict[str, float]:
    # Ideally hooked to a persisted learner (ultron_brain). Safe defaults here.
    return {
        "belief_flip": 1.2,
        "quiet_danger": 1.1,
        "curiosity_cliff": 1.15,
        "emotional_spike": 1.05,
        "authority_anchor": 1.05,
        "contrarian_truth": 1.0,
    }


# --- select_clip_start (user-supplied, polished) ---

def select_clip_start(ignitions: List[dict], goal: str = "viral") -> Optional[dict]:
    """Pick a single ignition candidate to consider as a primary clip start.
    Returns the chosen ignition dict (unchanged reference) or None.
    """
    if not ignitions:
        return None

    punch_priority = {
        "viral": [
            "belief_flip",
            "quiet_danger",
            "curiosity_cliff",
            "emotional_spike",
            "authority_anchor",
        ],
        "trust": [
            "authority_anchor",
            "quiet_danger",
            "belief_flip",
        ],
        "education": [
            "contrarian_truth",
            "belief_flip",
            "authority_anchor",
        ]
    }

    learned_weights = get_punch_weights()
    order = punch_priority.get(goal, [])

    scored = []
    for ig in ignitions:
        base = float(ig.get("score", 0.0))
        weight = float(learned_weights.get(ig.get("ignition_type", ""), 1.0))
        priority_boost = 1.2 if ig.get("ignition_type") in order else 1.0
        final_score = base * weight * priority_boost
        scored.append((final_score, ig))

    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]


# --- generate_punch_clips: create multiple independent clips per ignition ---

def generate_punch_clips(
    ignitions: List[dict],
    video_duration: float,
    pre_roll: float = DEFAULT_PRE_ROLL,
    post_roll: float = DEFAULT_POST_ROLL,
    max_per_ignition: int = 3,
    min_spacing: float = MIN_INDEPENDENT_SPACING,
    goal: str = "viral",
) -> List[dict]:
    """Produce up to `max_per_ignition` *diverse* clips per ignition.

    Each ignition can spawn different "angles":
      - main_punch: centered on ignition time
      - curiosity_lead: start earlier to show setup
      - authority_anchor: start later to emphasize payoff/resolution
      - micro_snap: short clip highlighting a single phrase

    The function enforces time-based uniqueness and semantic diversity.
    Returns list of clip dicts: {start,end,duration,ignition_type,score,meta}
    """
    if not ignitions:
        return []

    clips: List[dict] = []
    seen_fp = set()

    for ig in ignitions:
        t = float(ig.get("time", ig.get("start", 0.0)))
        ig_type = ig.get("ignition_type", "unknown")
        base_score = float(ig.get("score", 0.0))
        text = (ig.get("text") or "")

        # candidate variants
        variants: List[Tuple[str, float, float, float]] = []  # (name, start, end, score_mod)

        # 1) main punch (safe)
        s_main = max(0.0, t - pre_roll)
        e_main = min(video_duration, t + post_roll)
        variants.append(("main_punch", s_main, e_main, 1.0))

        # 2) curiosity lead (start earlier to include hook/setup) — longer pre-roll
        s_curi = max(0.0, t - (pre_roll + min(8.0, pre_roll * 1.5)))
        e_curi = min(video_duration, t + min(post_roll, 6.0))
        variants.append(("curiosity_lead", s_curi, e_curi, 0.95))

        # 3) authority anchor (start a little later to capture payoff/result)
        s_auth = max(0.0, t - max(0.6, pre_roll * 0.5))
        e_auth = min(video_duration, t + post_roll + 4.0)
        variants.append(("authority_anchor", s_auth, e_auth, 0.9))

        # 4) micro snap (very short, rapid social format)
        short_s = max(0.0, t - 0.6)
        short_e = min(video_duration, t + 1.6)
        variants.append(("micro_snap", short_s, short_e, 0.8))

        # sort variants by descending intent-weight, try to pick up to max_per_ignition
        variants = sorted(variants, key=lambda x: x[3], reverse=True)

        chosen = []
        for name, s, e, mod in variants:
            dur = max(MIN_CLIP_DURATION, float(e - s))
            if dur < MIN_CLIP_DURATION:
                continue

            # enforce independence: do not allow start too close to already chosen clips
            too_close = False
            for c in clips + chosen:
                if abs(c["start"] - s) < min_spacing:
                    too_close = True
                    break
            if too_close:
                continue

            clip_text = text or ig.get("meta_text") or ig.get("summary") or ""
            score = round(min(1.0, base_score * mod + 0.05 * random.random()), 4)
            fp = _fingerprint(clip_text, s, e)
            if fp in seen_fp:
                continue

            chosen.append({
                "start": round(s, 2),
                "end": round(e, 2),
                "duration": round(e - s, 2),
                "ignition_type": ig_type,
                "angle": name,
                "score": score,
                "text": clip_text,
                "fingerprint": fp,
                "meta": {"orig_ignition": ig}
            })
            seen_fp.add(fp)

            if len(chosen) >= max_per_ignition:
                break

        # Optional semantic diversification: if chosen variants are semantically similar,
        # attempt to replace the lowest with an alternative that has lower overlap.
        if len(chosen) > 1:
            # compute pairwise overlaps and try to minimize
            for i in range(len(chosen)):
                for j in range(i + 1, len(chosen)):
                    a = chosen[i]
                    b = chosen[j]
                    ov = text_overlap(a.get("text", ""), b.get("text", ""))
                    if ov > 0.65:
                        # if overlap high, try to shrink the micro_snap or swap with other variant
                        if b["angle"] == "micro_snap" and b["duration"] > 1.5:
                            b["start"] = round(min(video_duration, b["start"] + 0.6), 2)
                        elif a["angle"] == "micro_snap":
                            a["start"] = round(min(video_duration, a["start"] + 0.6), 2)

        # append chosen to global clips
        clips.extend(chosen)

    # final dedupe & scoring sort
    try:
        clips = dedupe_by_time(clips, time_tol=0.5)
    except Exception:
        pass

    # strict uniqueness by start spacing: if too dense, keep highest score per window
    final = []
    for c in sorted(clips, key=lambda x: (-x["score"], x["start"])):
        if any(abs(c["start"] - f["start"]) < min_spacing for f in final):
            continue
        final.append(c)

    # limit total clips if caller wants to cap externally
    final.sort(key=lambda x: (-x["score"], x["start"]))

    return final


# ------------------
# Small integration helper for orchestrator.py
# ------------------

def expand_ignitions_to_clips(ignitions: List[dict], video_duration: float, per_ignition: int = 3) -> List[dict]:
    """Default pipeline used by orchestrator: choose primary ignition, then expand to multi-angle clips.
    This function is intentionally small so orchestrator can optionally replace it.
    """
    # choose top ignition per scoring but allow multiple ignitions
    if not ignitions:
        return []

    # sort ignitions by score desc
    sorted_ig = sorted(ignitions, key=lambda x: float(x.get("score", 0.0)), reverse=True)

    # optionally keep top N ignitions to expand (avoid expanding hundreds)
    top_to_expand = sorted_ig[:min(6, len(sorted_ig))]

    clips = generate_punch_clips(top_to_expand, video_duration, max_per_ignition=per_ignition)
    # final defensive sort
    clips.sort(key=lambda x: (-x.get("score", 0.0), x.get("start", 0.0)))
    return clips
