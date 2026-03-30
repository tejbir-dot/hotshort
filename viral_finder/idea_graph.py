# viral_finder/idea_graph.py
import re
import hashlib
import math
import statistics
import os
from collections import namedtuple, deque, Counter
from typing import List, Tuple, Dict, Any, Optional, Union
import logging
import subprocess
log = logging.getLogger("idea_graph")

# If you already have numpy in your project, it's fine to use; otherwise we avoid heavy deps here.
try:
    import numpy as np
except Exception:
    np = None

# --- numpy-safe helpers (fallbacks when numpy not available) ---------------------------------
def _has_np():
    return np is not None
import re
# ---------------- Example glue (how you might call these inside idea_graph) ----------------
import math
import numpy as np
from statistics import mean
from collections import deque

# Tunables (feel free to expose as config)
HOOK_LOOKBACK_SECS = 6.0           # how far back (seconds) to search for punch/hook
HOOK_MIN_SCORE = 0.20              # minimal hook score to move start earlier
RETENTION_DROP_THRESHOLD = 0.35    # min retention (0..1) to keep candidate
FINAL_SCORE_MIN = 0.28             # global cutoff for output (tunable)
RETENTION_SIM_STEP = 1             # simulate per-segment
MAX_CANDIDATES_PER_IGNITION = 2    # allow a second fallback per ignition (short)
IdeaNode = namedtuple("IdeaNode", [
    "start_idx", "end_idx", "start_time", "end_time",
    "segments", "text", "state",
    "curiosity_score", "punch_confidence",
    "semantic_quality", "fingerprint", "metrics"
])
from viral_finder.sarcasm import detect_sarcasm

SETUP = "setup"
TENSION = "tension"
DEVELOPMENT = "development"
RESOLUTION = "resolution"
OPEN = "open"
def _normalize_ign_idx(ign):
    # accept int, tuple, dict
    if isinstance(ign, int):
        return ign
    if isinstance(ign, (list, tuple)):
        return int(ign[0])
    if isinstance(ign, dict):
        return int(ign.get("idx", ign.get("start_idx", 0)))
    return 0
def _safe_get(f, k, default=0.0):
    try:
        return float(f.get(k, default))
    except Exception:
        return default

def _np_max_slice(arr, s, e):
    try:
        a = np.asarray(arr)
        return float(np.max(a[s:e+1]))
    except Exception:
        # fallback for lists
        return max(arr[s:e+1]) if e >= s and arr[s:e+1] else (arr[s] if s < len(arr) else 0.0)
def time_to_seg_index(transcript, t):
    for i, s in enumerate(transcript):
        if float(s.get("start", 0.0)) <= t <= float(s.get("end", s.get("start", 0.0))):
            return i
    # fallback to nearest
    return min(range(len(transcript)), key=lambda i: abs(float(transcript[i].get("start",0.0)) - t))
def get_video_duration(video_path: str) -> float:
    """
    Returns video duration in seconds using ffprobe.
    """
    result = subprocess.run(
        [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    return float(result.stdout.strip())

# ----------------------------
# Hook / punch start detector
# ----------------------------
def find_punch_start(feats, curiosity, ignition_idx, max_lookback_secs=HOOK_LOOKBACK_SECS):
    """
    Scan backwards from ignition_idx to find a better 'hook' start.
    Returns a candidate start index and a hook_score (0..1).
    Heuristics used:
     - presence of hard question / short punchy sentence
     - contrast word
     - short sentence length
     - audio energy spike (if available in feats)
     - novelty / semantic jump
    """
    n = len(feats)
    if ignition_idx < 0 or ignition_idx >= n:
        return ignition_idx, 0.0

    # time bounds
    ign_start_time = _safe_get(feats[ignition_idx], "start", 0.0)
    lookback_limit_time = max(0.0, ign_start_time - max_lookback_secs)

    best_idx = ignition_idx
    best_score = 0.0

    # iterate backwards until time < lookback_limit_time
    for i in range(ignition_idx, -1, -1):
        seg = feats[i]
        seg_start = _safe_get(seg, "start", 0.0)
        if seg_start < lookback_limit_time:
            break

        txt = (seg.get("text", "") or "").strip().lower()
        wc = len(txt.split())
        # cue heuristics
        score = 0.0
        # hard question / question mark
        if "?" in txt:
            score += 0.34
        # curiosity markers and short punchy sentence
        if any(cm in txt for cm in ("did you know", "what if", "have you ever", "guess what", "you won't believe", "here's the thing", "most people")):
            score += 0.28
        # contrast words
        if any(w in txt for w in ("but ", "however", "instead", "actually", "on the other hand", "yet ")):
            score += 0.16
        # short punch bonus
        if 2 <= wc <= 10:
            score += 0.12
        # audio energy boost if present
        energy = _safe_get(seg, "energy", 0.0)
        if energy > 0.08:
            # normalize small energy to small boost
            score += min(0.2, energy * 0.8)
        # novelty / sem density jump
        sem = _safe_get(seg, "sem_density", 0.0)
        # compare to ignition seg sem
        ign_sem = _safe_get(feats[ignition_idx], "sem_density", 0.0)
        if abs(sem - ign_sem) > 0.08:
            score += 0.08

        # small penalty for being too early (prefer near ignition)
        time_distance = ign_start_time - seg_start
        score *= max(0.6, 1.0 - (time_distance / max_lookback_secs))

        if score > best_score:
            best_score = score
            best_idx = i

    # only accept if above HOOK_MIN_SCORE; else keep original ignition
    if best_score >= HOOK_MIN_SCORE and best_idx < ignition_idx:
        return best_idx, round(min(1.0, best_score), 3)
    return ignition_idx, 0.0

# ----------------------------
# Retention simulator (very small state machine)
# ----------------------------
def simulate_retention(feats, start_idx, end_idx, init_state=None):
    """
    Simulate viewer attention across segments [start_idx .. end_idx].
    Returns retention_score (0..1) approximating fraction of viewer remaining.
    Model is lightweight and deterministic: gating layers affect 'energy' and 'curiosity tension'.
    """
    # initial state
    state = {
        "energy": 0.6,            # baseline attention
        "curiosity": 0.0,         # tension
        "load": 0.25,             # cognitive load
        "momentum": 0.4,
        "trust": 0.5
    }
    if init_state:
        state.update(init_state)

    min_energy = 0.05
    decay = 0.06  # baseline decay per seg

    def clamp(x): return max(0.0, min(1.0, x))

    for i in range(start_idx, min(end_idx + 1, len(feats))):
        seg = feats[i]
        txt = (seg.get("text", "") or "").strip().lower()
        wc = len(txt.split())
        energy_delta = 0.0
        curiosity_delta = 0.0
        load_delta = 0.0
        momentum_delta = 0.0

        # Gate 0: Punch/hook sustain
        if "?" in txt or any(cm in txt for cm in ("did you know", "what if", "guess what")):
            energy_delta += 0.18
            curiosity_delta += 0.14

        # Gate 1: Context anchor -> reduce load if named entity / anchor present
        if len(txt) <= 60 and (any(w in txt for w in ("i'm", "we're", "the project", "the company", "when i"))):
            load_delta -= 0.06

        # Gate 2: Expectation set (promises / enumerations)
        if any(p in txt for p in ("first,", "second,", "third,", "step", "today i'll", "how to", "i'm going to show")):
            curiosity_delta += 0.09
            energy_delta += 0.06

        # Gate 3: Open-loop (creates tension)
        if txt.endswith("...") or txt.startswith("but") or any(q in txt for q in ("stay tuned", "more on this later")):
            curiosity_delta += 0.12
            momentum_delta -= 0.04

        # Gate 4: Cognitive ease
        if wc > 35:
            load_delta += 0.08
            energy_delta -= 0.08
        else:
            load_delta -= 0.02

        # Gate 5: Micro reward
        if any(k in txt for k in ("so", "therefore", "in short", "that means", "the point is")) and wc < 30:
            energy_delta += 0.14
            curiosity_delta -= 0.18
            momentum_delta += 0.06

        # Gate 6: Momentum (semantic progress via sem_density)
        sem = _safe_get(seg, "sem_density", 0.0)
        if sem > 0.5:
            momentum_delta += 0.04
            energy_delta += 0.02

        # Gate 7: Intent finality / betrayal check - if seg introduces a new obligation (question to audience)
        if any(w in txt for w in ("subscribe", "check out", "visit", "sign up")):
            # call-to-action too early -> slight trust hit (if before payoff)
            state["trust"] -= 0.08
            energy_delta -= 0.06

        # update state with decay and clamp
        state["energy"] = clamp(state["energy"] + energy_delta - decay * (1.0 + state["load"]))
        state["curiosity"] = clamp(state["curiosity"] + curiosity_delta - 0.02)
        state["load"] = clamp(state["load"] + load_delta)
        state["momentum"] = clamp(state["momentum"] + momentum_delta)
        state["trust"] = clamp(state["trust"])

        # if energy drains below min -> early drop
        if state["energy"] < min_energy or state["trust"] < 0.12:
            return 0.0  # near-certain drop

    # final retention score derived from energy, curiosity, momentum, trust
    final = 0.55*state["energy"] + 0.18*state["curiosity"] + 0.12*state["momentum"] + 0.15*state["trust"]
    return float(max(0.0, min(1.0, final)))

# ----------------------------
# Candidate scoring and selection
# ----------------------------
def _score_candidate(feats, curiosity, s_idx, e_idx, hook_score, retention_score, brain=None):
    # base signals
    peak = 0.0
    try:
        peak = float(np.max(np.asarray(curiosity[s_idx:e_idx+1])))
    except Exception:
        try:
            peak = max(curiosity[s_idx:e_idx+1])
        except Exception:
            peak = float(curiosity[s_idx]) if s_idx < len(curiosity) else 0.0

    # semantic quality rough average
    sems = [_safe_get(seg, "sem_density", 0.0) for seg in feats[s_idx:e_idx+1]]
    sem_avg = mean(sems) if sems else 0.0

    # audio/motion cues
    energies = [_safe_get(seg, "energy", 0.0) for seg in feats[s_idx:e_idx+1]]
    motions = [_safe_get(seg, "motion", 0.0) for seg in feats[s_idx:e_idx+1]]
    a_avg = mean(energies) if energies else 0.0
    m_avg = mean(motions) if motions else 0.0

    # punch proxy: hook + local punch density
    punch_local = hook_score + 0.4 * min(1.0, a_avg + m_avg)

    # combine into final interpretable score
    final = (0.45 * peak) + (0.22 * punch_local) + (0.18 * retention_score) + (0.15 * sem_avg)
    final = float(max(0.0, min(1.0, final)))
    return final, {"peak": peak, "hook": hook_score, "punch_local": punch_local, "sem_avg": sem_avg,
                   "energy": a_avg, "motion": m_avg, "retention": retention_score}

# ----------------------------
# MAIN entry (layered)
# ----------------------------
def analyze_curiosity_and_detect_punches(segments, aud=None, vis=None, brain=None,
                                        window=3,
                                        ignition_min_slope=0.08,
                                        ignition_min_curiosity=0.14,
                                        drop_ratio=0.45):
    """
    Layered analyzer (replacement).
    Returns feats, curiosity, candidates [(s_idx,e_idx,meta), ...].
    """
    # 1) compute features & curve (use your existing functions)
    feats = compute_segment_features(segments, aud=aud, vis=vis, brain=brain)
    curiosity = compute_curiosity_curve(feats, window=window)

    # 2) detect ignitions (candidate ignition indices)
    # ignitions = detect_ignition_points(feats, curiosity, min_slope=ignition_min_slope, min_curiosity=ignition_min_curiosity)
    # from viral_finder.ignition_deep import detect_ignitions_deep
    # ignitions, ign_summary = detect_ignitions_deep(segments, use_audio_motion=True)
    from viral_finder.ignition_deep import (
        detect_ignitions,
        analyze_segments_for_ignition,
        build_semantic_spectrogram,
    )

    # segments == transcript list, feats optional
    # spect_and_ign = detect_ignitions(segments, feats=feats, lexicon=None, window_sec=1.5, step_sec=0.25, top_k=6)
    # ignitions = spect_and_ign["ignitions"]
    # each ignition: {time, pre_time, score, slope}
      # Convert ignition pre_time -> nearest segment index to seed curiosity measurement
    spec, ignitions = analyze_segments_for_ignition(segments, run_ser_if_available=False)
    import subprocess

    # Non-linear content detection: attention islands
    try:
        from viral_finder.nonlinear import detect_attention_islands
        # classify content style: mean semantic jump + silence proportion
        def classify_content_style(feats):
            if not feats:
                return "linear"
            # semantic jump approximated by 1 - sim_prev
            jumps = [max(0.0, 1.0 - f.get("sim_prev", 0.0)) for f in feats]
            avg_jump = float(sum(jumps) / len(jumps)) if jumps else 0.0
            # silence ratio: proportion of low-energy segments
            low_energy = sum(1 for f in feats if f.get("energy", 0.0) < 0.02)
            silence_ratio = low_energy / len(feats)
            if avg_jump > 0.45 or silence_ratio > 0.22:
                return "non_linear"
            return "linear"

        style = classify_content_style(feats)
        if style == "non_linear":
            islands = detect_attention_islands(feats)
            # convert islands to lightweight candidates (start/end from neighbouring segments)
            for isl in islands:
                idx = isl.get("index", 1)
                s_idx = max(0, idx-1)
                start = feats[s_idx].get("start", 0.0)
                end = feats[idx].get("end", start + 3.0)
                candidates.append({
                    "start": start,
                    "end": end,
                    "score": isl.get("score", 0.0),
                    "label": "Attention Island",
                    "reason": f"delta:{isl.get('reason','')}",
                    "curiosity": float(curiosity[idx] if hasattr(curiosity,'__len__') and idx < len(curiosity) else 0.0),
                    "punch_confidence": 0.0,
                    "semantic_quality": feats[idx].get("impact", 0.0),
                    "fingerprint": fingerprint_text(feats[idx].get("text","")[:150]),
                    "metrics": feats[idx]
                })
            # If non-linear, we may still continue to adapt ignitions
    except Exception:
        pass

    # # seconds
    # punch_clips = generate_punch_clips(
    #               ignitions,
    #             video_duration=video_duration
    # )

    candidates = []

    # defensive guards
    if not ignitions:
        return feats, curiosity, []




    for ign in ignitions:
        ign_idx = _normalize_ign_idx(ign)

        ign_idx = max(0, min(len(feats) - 1, ign_idx))

        try:
            e_idx = detect_punch_end(
            feats,
            curiosity,
            ign_idx,
            drop_ratio=drop_ratio
        )
            if e_idx is None:
               e_idx = min(len(feats) - 1, ign_idx + int(window * 3))
        except Exception:
            e_idx = min(len(feats) - 1, ign_idx + int(window * 3))

        # 3) find a better punch start (hook) by scanning backwards
        hook_idx, hook_score = find_punch_start(feats, curiosity, ign_idx)
        # ensure hook_idx <= ign_idx
        hook_idx = max(0, min(hook_idx, ign_idx))

        # also attempt a slightly earlier fallback (one more segment back) if hook_score borderline
        fallback_starts = [hook_idx]
        if hook_score < 0.28 and hook_idx > 0:
            fallback_starts.append(max(0, hook_idx - 1))

        # for each start candidate, simulate retention & score
        local_candidates = []
        for s_idx in fallback_starts[:MAX_CANDIDATES_PER_IGNITION]:
            # ensure valid bounds
            s_idx = int(s_idx)
            e_idx_local = int(e_idx)
            # clamp
            s_idx = max(0, min(s_idx, len(feats)-1))
            e_idx_local = max(s_idx, min(e_idx_local, len(feats)-1))

            # payoff detection (best-effort) - use existing detector if available
            payoff_time, payoff_conf = None, 0.0
            try:
                if "detect_payoff_end" in globals():
                    payoff_time, payoff_conf = detect_payoff_end(feats, curiosity, s_idx, end_idx=e_idx_local)
                else:
                    payoff_time, payoff_conf = None, 0.0
            except Exception:
                payoff_time, payoff_conf = None, 0.0

            # if payoff_time within bounds, clamp e_idx_local to payoff segment index
            if payoff_time is not None:
                # find nearest segment index whose end >= payoff_time
                for idx in range(s_idx, e_idx_local + 1):
                    if _safe_get(feats[idx], "end", 1e9) >= payoff_time:
                        e_idx_local = idx
                        break

            # simulate retention
            retention_score = simulate_retention(feats, s_idx, e_idx_local)

            # score candidate
            final_score, breakdown = _score_candidate(feats, curiosity, s_idx, e_idx_local, hook_score, retention_score, brain=brain)

            # build metadata
            s_time, e_time = indices_to_time(feats, s_idx, e_idx_local)
            meta = {
                "start_idx": int(s_idx),
                "end_idx": int(e_idx_local),
                "start_time": float(s_time),
                "end_time": float(e_time),
                "curiosity_peak": float(breakdown["peak"]),
                "curiosity_at_start": float(curiosity[s_idx]) if hasattr(curiosity, "__len__") else float(curiosity),
                "hook_idx": int(hook_idx),
                "hook_score": float(hook_score),
                "retention_score": float(retention_score),
                "score": float(final_score),
                "breakdown": breakdown,
                "payoff_time": float(payoff_time) if payoff_time is not None else None,
                "payoff_confidence": float(payoff_conf) if payoff_conf else 0.0
            }
            local_candidates.append((s_idx, e_idx_local, meta))

        # sort local candidates by score desc and push top (but avoid near duplicates)
        local_candidates.sort(key=lambda x: -x[2]["score"])
        for cand in local_candidates[:1]:
            # accept only if retention & score meet thresholds
            if cand[2]["retention_score"] >= RETENTION_DROP_THRESHOLD and cand[2]["score"] >= FINAL_SCORE_MIN:
                candidates.append(cand)
            else:
                # allow some lower-scoring ones if payoff detected strongly
                if cand[2].get("payoff_confidence", 0.0) >= 0.70 and cand[2]["score"] > 0.18:
                    candidates.append(cand)

    # dedupe by time (simple)
    def _time_key(c): return (round(c[2]["start_time"], 2), round(c[2]["end_time"], 2))
    seen = set()
    final = []
    for s,e,m in sorted(candidates, key=lambda x: -x[2]["score"]):
        key = _time_key((s,e,m))
        if key in seen:
            continue
        seen.add(key)
        final.append((s,e,m))

    return feats, curiosity, final
_PROMISE_PATTERNS=[
    r"\bnext\b", r"\bcoming up\b", r"\bi will explain\b",
    r"\blet me show\b", r"\bwe'll see\b", r"\bbut first\b"
]

RESOLUTION_PATTERNS = [
    r"\bso\b", r"\btherefore\b", r"\bthis means\b",
    r"\bthat's why\b", r"\bin short\b", r"\bthe point is\b"
]
_WORDS_RE = re.compile(r"\w+", flags=re.UNICODE)

def normalize_text(s: str) -> str:
    if not s:
        return ""
    s = s.replace("\u2019", "'").strip()
    s = re.sub(r"\s+", " ", s)
    return s.strip()

def tokens(s: str) -> List[str]:
    return _WORDS_RE.findall(s.lower())
def jaccard_sim(a: str, b: str) -> float:
    A = set(tokens(a))
    B = set(tokens(b))
    if not A and not B:
        return 1.0
    if not A or not B:
        return 0.0
    return len(A & B) / len(A | B)

def bigram_sim(a: str, b: str) -> float:
    ta = tokens(a)
    tb = tokens(b)
    if len(ta) < 2 or len(tb) < 2:
        return 0.0

    def bigrams(t):
        return set([f"{t[i]} {t[i+1]}" for i in range(len(t)-1)])

    A = bigrams(ta)
    B = bigrams(tb)
    if not A or not B:
        return 0.0
    return len(A & B) / len(A | B)

def text_overlap(a: str, b: str) -> float:
    a = normalize_text(a)
    b = normalize_text(b)
    return 0.6 * jaccard_sim(a, b) + 0.4 * bigram_sim(a, b)
def fingerprint_text(s: str) -> str:
    s = normalize_text(s)
    h = hashlib.sha1(s.encode("utf-8")).hexdigest()
    return h
from viral_finder.language import detect_language
from viral_finder.curiosity_maps import get_map as get_curiosity_map


# fallback markers (used if language maps missing)
CURIOSITY_MARKERS = [
    "did you know", "what if", "imagine", "have you ever",
    "guess what", "here's the thing", "you won't believe",
    "ever wondered", "how to", "why", "did you", "secret"
]


def detect_curiosity_score(text: str) -> float:
    t = (text or "").lower()
    score = 0.0

    # language-specific lexicon
    lang = detect_language(text or "")
    markers = []
    try:
        markers = get_curiosity_map(lang)
    except Exception:
        markers = CURIOSITY_MARKERS

    # merge maps (language-specific first, then fallback markers)
    combined = list(dict.fromkeys((markers or []) + CURIOSITY_MARKERS))

    for m in combined:
        if m in t:
            score += 0.18

    if "?" in t:
        score += 0.15

    wc = len(tokens(text))
    if 2 <= wc <= 8:
        score += 0.06

    return min(1.0, score)
# def detect_instant_ignition(text: str) -> bool:
#     """
#     Fires immediately on human attention triggers.
#     This mimics subconscious snap-attention.
#     """
#     if not text:
#         return False

#     t = text.lower()

#     # hard question
#     if "?" in t and any(q in t for q in ["why", "how", "what", "who", "did you"]):
#         return True

#     # bold / authority claim
#     bold_phrases = [
#         "this will change",
#         "nobody tells you",
#         "most people are wrong",
#         "the truth about",
#         "you are doing it wrong",
#         "this is why",
#         "here’s the secret",
#         "stop doing this"
#     ]
#     if any(p in t for p in bold_phrases):
#         return True

#     # shock / extremity
#     shock_words = ["never", "always", "insane", "crazy", "exposed", "destroyed"]
#     if any(w in t for w in shock_words):
#         return True

#     return False

CONTRAST_MARKERS = [
    "but", "however", "instead", "actually",
    "in reality", "on the other hand", "yet", "rather"
]

def detect_contrast_strength(text: str) -> float:
    t = text.lower()
    score = 0.0

    for m in CONTRAST_MARKERS:
        if m in t:
            score += 0.25

    if "used to" in t:
        score += 0.4
    if "now i" in t or "now we" in t:
        score += 0.25

    return min(1.0, score)
CONCLUSION_MARKERS = [
    "so remember", "don't forget", "final thought",
    "bottom line", "to summarize", "in conclusion",
    "that's why", "therefore", "that means"
]

def detect_conclusion_marker(text: str) -> bool:
    t = text.lower()
    if any(m in t for m in CONCLUSION_MARKERS):
        return True

    if t.rstrip().endswith((".", "!")) and len(tokens(t)) <= 20:
        if "so" in t or "therefore" in t or "that's" in t:
            return True

    return False
def _env_float(name: str, default: float) -> float:
    try:
        raw = os.getenv(name)
        if raw is None or str(raw).strip() == "":
            return float(default)
        return float(raw)
    except Exception:
        return float(default)


SIM_THRESHOLD_SHORT = 0.38
COALESCE_TIME_TOL_DEFAULT = max(0.0, _env_float("HS_IDEA_COALESCE_TIME_TOL", 0.25))
SEM_SIM_THRESHOLD_DEFAULT = min(0.99, max(0.0, _env_float("HS_IDEA_COALESCE_SEM_THR", 0.50)))
IDEA_MAX_NODE_SECONDS = max(3.0, _env_float("HS_IDEA_MAX_NODE_SECONDS", 15.0))
SIM_THRESHOLD_LONG = 0.33
# Break an arc when semantic overlap between consecutive segments drops below this
SEM_DRIFT_BREAK = 0.30

def same_thought(current_text_window: str,
                 new_segment_text: str,
                 gap_seconds: float,
                 avg_seg_dur: float,
                 n_segments: int) -> bool:

    cur = normalize_text(current_text_window)
    new = normalize_text(new_segment_text)

    sim = text_overlap(cur[-1200:], new) if cur and new else 0.0
    sim_threshold = SIM_THRESHOLD_SHORT if n_segments < 25 else SIM_THRESHOLD_LONG
    max_gap = min(2.0, max(0.8, avg_seg_dur * 2.0))

    prev_low = cur[-200:].lower() if cur else ""
    closure_hit = any(w in prev_low for w in CONCLUSION_MARKERS)
    contrast = any(w in new.lower() for w in CONTRAST_MARKERS)

    if closure_hit:
        return False
    if gap_seconds > max_gap and sim < (sim_threshold + 0.12):
        return False
    if contrast and sim < (sim_threshold + 0.15):
        return False
    if sim >= sim_threshold:
        return True
    if sim >= (sim_threshold - 0.08) and gap_seconds <= max_gap:
        return True

    return False
# ----------------------------------------
# Selection & Suppression Thresholds
# ----------------------------------------

# Minimum curiosity score to consider a clip
CURIO_SELECT_CUTOFF = min(0.95, max(0.0, _env_float("HS_SELECTOR_CURIO_CUTOFF", 0.28)))

# Minimum punch confidence to consider a clip
PUNCH_SELECT_CUTOFF = min(0.95, max(0.0, _env_float("HS_SELECTOR_PUNCH_CUTOFF", 0.28)))

# Diversity-selector defaults
SELECT_RELAX_CURIO_DELTA_DEFAULT = min(0.30, max(0.0, _env_float("HS_SELECTOR_RELAX_CURIO_DELTA", 0.08)))
SELECT_RELAX_PUNCH_DELTA_DEFAULT = min(0.30, max(0.0, _env_float("HS_SELECTOR_RELAX_PUNCH_DELTA", 0.08)))
SELECT_RELAX_SEM_FLOOR_DEFAULT = min(0.80, max(0.20, _env_float("HS_SELECTOR_RELAX_SEM_FLOOR", 0.45)))
SELECT_BASE_SEM_FLOOR = 0.52
SELECT_STRICT_PASS_WEIGHT = min(1.50, max(0.30, _env_float("HS_DIVERSITY_STRICT_PASS_WEIGHT", 1.00)))
SELECT_RELAX_PASS_WEIGHT = min(1.00, max(0.20, _env_float("HS_DIVERSITY_RELAX_PASS_WEIGHT", 0.85)))
SELECT_STRICT_MIN_TARGET_DEFAULT = max(0, int(_env_float("HS_SELECTOR_STRICT_MIN_TARGET", 0)))
SELECT_RELAX_MAX_CANDIDATES_DEFAULT = max(1, int(_env_float("HS_SELECTOR_RELAX_MAX_CANDIDATES", 8)))
SELECT_RELAX_DYNAMIC_ENABLE_DEFAULT = str(os.getenv("HS_SELECTOR_RELAX_DYNAMIC_ENABLE", "1")).strip().lower() in ("1", "true", "yes", "on")

# If a node is a strong resolution, suppress it (avoid boring endings)
RESOLUTION_SUPPRESS_CUTOFF = 0.15

def sentence_complete_extend(start_t: float,
                             end_t: float,
                             transcript: List[Dict],
                             max_extend: float = 6.0) -> float:
    """
    Extend clip end to complete the current sentence if end_t cuts mid-sentence.
    Human-like polish layer.
    """
    if not transcript:
        return end_t

    for seg in transcript:
        ts = float(seg.get("start", 0.0))
        te = float(seg.get("end", ts))

        if ts < end_t < te:
            extra = min(te - end_t, max_extend)
            return round(end_t + extra, 2)

    return end_t

def opens_new_obligation(text: str) -> bool:
    if not text:
        return False
    t = text.lower()
    return any(re.search(p, t) for p in _PROMISE_PATTERNS)

def semantic_commitment_closing(semd, idx, lookahead=2, eps=0.02):
    """
    Meaning should NOT keep rising after payoff.
    """
    cur = semd[idx]
    for j in range(idx + 1, min(len(semd), idx + 1 + lookahead)):
        if semd[j] > cur + eps:
            return False
    return True

def _arr(x):
    if _has_np():
        return np.array(x, dtype=float)
    return [float(v) for v in x]

def _nanpercentile(x, q):
    # q in [0,100]
    if _has_np():
        return float(np.nanpercentile(x, q))
    vals = sorted([v for v in x if v == v])
    if not vals:
        return 0.0
    # linear interpolation
    k = (len(vals) - 1) * (q / 100.0)
    lo = int(math.floor(k))
    hi = int(math.ceil(k))
    if lo == hi:
        return float(vals[lo])
    frac = k - lo
    return float(vals[lo] + frac * (vals[hi] - vals[lo]))

def _moving_avg_same(raw, k):
    # kernel assumed uniform of length k
    if _has_np():
        kernel = np.ones(k) / float(k)
        return np.convolve(raw, kernel, mode='same')
    N = len(raw)
    out = [0.0] * N
    half = k // 2
    for i in range(N):
        s = max(0, i - half)
        e = min(N, i + half + 1)
        window = raw[s:e]
        out[i] = float(sum(window) / max(1, len(window)))
    return out

def _clip_list(x, lo, hi):
    if _has_np():
        return np.clip(x, lo, hi)
    return [min(max(v, lo), hi) for v in x]

def _slice_max(arr, s, e):
    if _has_np():
        return float(np.max(arr[s:e+1]))
    return float(max(arr[s:e+1]))

# -----------------------------------------------------------------------------------------------

log = logging.getLogger(__name__)

# Lightweight text overlap utility.
# Avoid importing ultron_finder_v33 here because that import path can transitively
# load heavy semantic models at module import time.
def text_overlap(a: str, b: str) -> float:
    """Simple overlap: Jaccard on words (fast fallback)."""
    if not a or not b:
        return 0.0
    wa = set(re.findall(r"\w+", a.lower()))
    wb = set(re.findall(r"\w+", b.lower()))
    if not wa or not wb:
        return 0.0
    inter = wa & wb
    uni = wa | wb
    return float(len(inter)) / (len(uni) + 1e-9)

_brain_loader_attempted = False
_brain_loader_ok = False
_brain_loader_reason = "not_attempted"


def _default_brain_score(text, brain=None):
    """
    Fallback brain scorer:
    returns (impact, meaning, novelty, emotion, clarity) in [0,1]
    naive heuristics: punctuation, question, length
    """
    if not text:
        return 0.0, 0.0, 0.0, 0.0, 0.0
    t = text.lower()
    impact = 0.6 if "!" in text else 0.2
    meaning = min(1.0, len(text.split()) / 30.0)
    novelty = 0.25 if "new" in t or "novel" in t or "secret" in t else 0.05
    emotion = 0.3 if any(w in t for w in ("amazing", "insane", "crazy", "shocking")) else 0.05
    clarity = 0.5
    return impact, meaning, novelty, emotion, clarity


_runtime_ultron_brain_score = _default_brain_score


def _brain_enabled() -> bool:
    raw_new = os.getenv("HS_BRAIN_ENABLE_ENRICH", "")
    if raw_new.strip() != "":
        return str(raw_new).strip().lower() in ("1", "true", "yes", "on")
    raw_old = os.getenv("HS_ORCH_BRAIN_ENABLED", "")
    if raw_old.strip() != "":
        return str(raw_old).strip().lower() in ("1", "true", "yes", "on")
    is_render = (
        str(os.environ.get("RENDER", "")).strip().lower() in ("1", "true", "yes", "on")
        or bool(os.environ.get("RENDER_SERVICE_ID"))
    )
    return not is_render


def _ensure_brain_score_runtime() -> None:
    global _brain_loader_attempted, _brain_loader_ok, _brain_loader_reason, _runtime_ultron_brain_score
    if _brain_loader_attempted:
        return
    _brain_loader_attempted = True
    if not _brain_enabled():
        _brain_loader_ok = False
        _brain_loader_reason = "disabled_by_env"
        _runtime_ultron_brain_score = _default_brain_score
        log.info("[BRAIN] idea_graph lazy=1 enabled=0 reason=%s", _brain_loader_reason)
        return
    try:
        from viral_finder.ultron_brain import ultron_brain_score as _real_ultron_brain_score

        _runtime_ultron_brain_score = _real_ultron_brain_score
        _brain_loader_ok = True
        _brain_loader_reason = "loaded"
        log.info("[BRAIN] idea_graph lazy=1 enabled=1 reason=loaded")
    except Exception as exc:
        _brain_loader_ok = False
        _brain_loader_reason = str(exc)
        _runtime_ultron_brain_score = _default_brain_score
        log.warning("[BRAIN] idea_graph lazy=1 enabled=1 fallback=%s", _brain_loader_reason)


if str(os.getenv("HS_BRAIN_EAGER_IMPORT", "0")).strip().lower() in ("1", "true", "yes", "on"):
    _ensure_brain_score_runtime()

# ---------------- Core: features -> curiosity/tension -> punch detection ----------------

def compute_segment_features(segments, aud=None, vis=None, brain=None):
    """
    For each transcript segment produce feature dict:
    {
      "start","end","text",
      "energy","motion",
      "punct_score","is_question",
      "sem_density","impact","meaning","novelty","emotion","clarity",
      "sim_prev" (semantic similarity to previous)
    }
    aud, vis: lists of dicts with keys "time","energy" / "motion" (optional)
    """
    N = len(segments)
    feats = []
    _ensure_brain_score_runtime()
    # build quick time->value maps for audio/visual (per-second average)
    def mean_in_range(list_of_dicts, key, s, e):
        if not list_of_dicts:
            return 0.0
        vals = [x.get(key, 0.0) for x in list_of_dicts if x.get("time", 0.0) >= s and x.get("time", 0.0) <= e]
        if not vals:
            return 0.0
        if _has_np():
            return float(np.mean(vals))
        return float(statistics.mean(vals))

    for i, seg in enumerate(segments):
        s = float(seg.get("start", 0.0))
        e = float(seg.get("end", s + 0.01))
        text = (seg.get("text") or "").strip()
        energy = mean_in_range(aud, "energy", s, e) if aud is not None else 0.0
        motion = mean_in_range(vis, "motion", s, e) if vis is not None else 0.0

        # punctuation / question heuristics
        punct_score = (1.0 if "!" in text else 0.0) + (0.6 if "..." in text else 0.0)
        is_question = 1.0 if "?" in text or text.lower().startswith(("what","why","how","when","where","who")) else 0.0
        punct_score = min(1.0, punct_score + is_question*0.6)

        # semantic density ~ words per second
        word_count = len(re.findall(r"\w+", text))
        duration = max(0.01, e - s)
        sem_density = min(1.0, (word_count / duration) / 6.0)  # tuned: 6 words/sec -> density 1

        # brain vector provides richer signals if available
        impact, meaning, novelty, emotion, clarity = _runtime_ultron_brain_score(text, brain)

        sim_prev = 0.0
        if i > 0:
            try:
                sim_prev = text_overlap(segments[i-1].get("text",""), text)
            except Exception:
                sim_prev = 0.0

        feats.append({
            "idx": i,
            "start": s, "end": e, "text": text,
            "energy": float(energy),
            "motion": float(motion),
            "punct": float(punct_score),
            "is_question": bool(is_question),
            "sem_density": float(sem_density),
            "impact": float(impact),
            "meaning": float(meaning),
            "novelty": float(novelty),
            "emotion": float(emotion),
            "clarity": float(clarity),
            "sim_prev": float(sim_prev),
            "word_count": word_count,
        })
    return feats


def compute_curiosity_curve(feats, window=3, weights=None):
    """
    Compute curiosity score per segment (0..1).
    weights: dict of contribution weights (novelty, meaning, energy, punct, sem_density)
    returns np.array(curiosity)
    """
    if weights is None:
        weights = {
            "novelty": 0.34,
            "meaning": 0.22,
            "energy": 0.16,
            "punct": 0.12,
            "sem_density": 0.16
        }

    N = len(feats)
    if N == 0:
        return (np.array([]) if _has_np() else [])

    if _has_np():
        novelty = np.array([f["novelty"] for f in feats], dtype=float)
        meaning = np.array([f["meaning"] for f in feats], dtype=float)
        energy = np.array([f["energy"] for f in feats], dtype=float)
        punct = np.array([f["punct"] for f in feats], dtype=float)
        semd = np.array([f["sem_density"] for f in feats], dtype=float)
    else:
        novelty = [float(f["novelty"]) for f in feats]
        meaning = [float(f["meaning"]) for f in feats]
        energy = [float(f["energy"]) for f in feats]
        punct = [float(f["punct"]) for f in feats]
        semd = [float(f["sem_density"]) for f in feats]

    # normalize each signal robustly (min-max)
    def robust_norm(x):
        if len(x) == 0:
            return x
        # compute low/high percentiles robustly
        lo = _nanpercentile(x, 8)
        hi = _nanpercentile(x, 92)
        if hi - lo < 1e-6:
            # fallback to min/max
            mn = min(x)
            mx = max(x)
            if mx - mn < 1e-9:
                return [0.0 for _ in x] if not _has_np() else np.zeros_like(x)
            if _has_np():
                return np.clip((x - mn) / (mx - mn + 1e-9), 0, 1)
            return [min(max((v - mn) / (mx - mn + 1e-9), 0.0), 1.0) for v in x]
        if _has_np():
            return np.clip((x - lo) / (hi - lo + 1e-9), 0.0, 1.0)
        return [min(max((v - lo) / (hi - lo + 1e-9), 0.0), 1.0) for v in x]

    nov_n = robust_norm(novelty)
    mean_n = robust_norm(meaning)
    eng_n = robust_norm(energy)
    p_n = robust_norm(punct)
    s_n = robust_norm(semd)

    # raw curiosity (per-segment)
    if _has_np():
        raw = (weights["novelty"] * nov_n +
               weights["meaning"] * mean_n +
               weights["energy"] * eng_n +
               weights["punct"] * p_n +
               weights["sem_density"] * s_n)
    else:
        raw = [
            weights["novelty"] * nov_n[i] +
            weights["meaning"] * mean_n[i] +
            weights["energy"] * eng_n[i] +
            weights["punct"] * p_n[i] +
            weights["sem_density"] * s_n[i]
            for i in range(N)
        ]

    # smooth to build expectation curve (moving average)
    k = max(1, int(window))
    # moving average smoothing (same-mode)
    if _has_np():
        kernel = np.ones(k) / k
        curiosity = np.convolve(raw, kernel, mode="same")
        curiosity = np.clip(curiosity, 0.0, 1.0)
        return curiosity
    else:
        curiosity = _moving_avg_same(raw, k)
        curiosity = _clip_list(curiosity, 0.0, 1.0)
        return curiosity


import math
import re
from typing import List, Tuple, Dict, Optional

# you probably already have these; re-declare if not
CURIOSITY_MARKERS = [
    "did you know", "what if", "imagine", "have you ever", "guess what", "here's the thing",
    "what people", "most people", "you won't believe", "surprising", "low-key", "curious",
    "ever wondered", "how to", "why", "did you", "let me tell you", "secret"
]

BOLD_MARKERS = [
    "this will change", "nobody tells you", "most people are wrong", "the truth about",
    "you are doing it wrong", "this is why", "here’s the secret", "stop doing this", "you must",
    "you need to", "never", "always", "i was the", "youngest", "billionaire", "exposed"
]

EMOTION_WORDS = ["love","hate","amazing","insane","truth","secret","exposed","crazy","fear","power"]

_WORDS_RE = re.compile(r"\w+", flags=re.UNICODE)
def tokens(s: str) -> List[str]:
    return _WORDS_RE.findall((s or "").lower())

def _safe_get(feat: dict, key: str, default=0.0):
    try:
        return feat.get(key, default)
    except Exception:
        return default

def detect_instant_score(text: str, feat: dict = None, prev_text: str = "", next_text: str = "") -> Tuple[float, Dict]:
    """
    Returns (score 0..1, reasons dict). Text-only + small context-based instant attention scoring.
    Designed to be conservative (no false positives).
    """
    reasons = {}
    if not text:
        return 0.0, reasons

    t = text.lower()
    score = 0.0

    # 1) question / hard question spike
    if "?" in t:
        score += 0.30
        reasons["question"] = True
        # stronger if wh-words present
        if any(w in t for w in ("why", "how", "what", "who", "did you", "did we")):
            score += 0.12
            reasons["hard_question"] = True

    # 2) curiosity phrase markers
    for m in CURIOSITY_MARKERS:
        if m in t:
            score += 0.14
            reasons.setdefault("curio_markers", 0)
            reasons["curio_markers"] += 1

    # 3) bold claim / authority / superlative
    for b in BOLD_MARKERS:
        if b in t:
            score += 0.22
            reasons.setdefault("bold", 0)
            reasons["bold"] += 1

    # 4) short punchiness bonus
    wc = len(tokens(text))
    if 2 <= wc <= 9:
        score += 0.06
        reasons["short_sentence"] = True

    # 5) emotional / shocking words
    emotion_hits = sum(1 for w in EMOTION_WORDS if w in t)
    if emotion_hits:
        score += min(0.18, 0.06 * emotion_hits)
        reasons["emotion_hits"] = emotion_hits

    # 6) context contrast (if next or prev strongly different) -> small boost
    if prev_text and text and prev_text.strip():
        # cheap overlap check
        prev_tokens = set(tokens(prev_text))
        cur_tokens = set(tokens(text))
        overlap = len(prev_tokens & cur_tokens) / max(1, len(prev_tokens | cur_tokens))
        if overlap < 0.25:
            score += 0.04
            reasons["low_overlap_prev"] = True

    # 7) audio/visual signals in feat (if present)
    if feat:
        vol = float(_safe_get(feat, "volume", 0.0) or 0.0)
        motion = float(_safe_get(feat, "motion", 0.0) or 0.0)
        pitch = float(_safe_get(feat, "pitch", 0.0) or 0.0)
        # normalize assumptions: volume/pitch/motion usually between 0..1 in your features
        # give small boosts if signal is strong
        if vol > 0.7:
            score += 0.06
            reasons["loud"] = vol
        if motion > 0.5:
            score += 0.05
            reasons["motion"] = motion
        if pitch > 0.7:
            score += 0.03
            reasons["pitch"] = pitch

    # clamp
    return float(min(1.0, score)), reasons


def detect_ignition_points(
    feats: List[dict],
    curiosity,
    min_slope: float = 0.08,
    min_curiosity: float = 0.14,
    instant_threshold: float = 0.45,
    slope_window: int = 2,
    semantic_window: int = 3,
    min_separation_sec: float = 1.2,
    return_meta: bool = True,
):
    """
    Robust ignition detector: fuses instant language/audio cues with slope-based curiosity growth.
    - feats: list of segment dicts (must contain "start","end","text" and optionally audio/vis keys)
    - curiosity: sequence-like with same length as feats
    Returns list of ignition indices. If return_meta=True returns (ignitions, debug_rows)
    """
    N = len(feats)
    debug_rows = []
    ignitions = []

    # helper functions
    def get_cur(i):
        try:
            val = curiosity[i]
            return float(val) if not hasattr(val, "__iter__") else float(val)
        except Exception:
            return 0.0

    def mean_prev_cur(i, w):
        start = max(0, i - w)
        vals = [get_cur(j) for j in range(start, i)]
        return sum(vals) / max(1, len(vals))

    def mean_sem(i, w):
        # semantic density feature if present
        vals = []
        for j in range(max(0, i-w), min(N, i+1)):
            vals.append(float(_safe_get(feats[j], "sem_density", 0.0) or 0.0))
        return sum(vals) / max(1, len(vals))

    # precompute last ignition time (seconds) to avoid too-close ignitions
    last_ign_time = -9999.0

    for i in range(N):
        feat = feats[i]
        text = (feat.get("text","") if isinstance(feat, dict) else str(feat)) or ""
        prev_text = feats[i-1].get("text","") if i-1 >= 0 else ""
        next_text = feats[i+1].get("text","") if i+1 < N else ""

        instant_score, inst_reasons = detect_instant_score(text, feat, prev_text, next_text)

        # semantic jump: big meaning increase -> attention
        sem_here = float(_safe_get(feat, "sem_density", 0.0) or 0.0)
        sem_prev = mean_sem(max(0, i-1), semantic_window)
        sem_delta = sem_here - sem_prev

        # novelty/curiosity jump (relative)
        cur_here = get_cur(i)
        prev_mean = mean_prev_cur(i, slope_window)
        cur_delta = cur_here - prev_mean

        # speaker change bonus
        speaker_change = False
        try:
            sp = feat.get("speaker", None)
            sp_prev = feats[i-1].get("speaker", None) if i-1 >= 0 else None
            if sp and sp_prev and sp != sp_prev:
                speaker_change = True
        except Exception:
            speaker_change = False

        # repetition penalty: if this exact text fingerprint seen recently -> lower instant
        text_fp = (text or "").strip().lower()[:200]
        repeat_penalty = 0.0
        # scan last few segments for same tokens
        for j in range(max(0, i-8), i):
            try:
                if text_fp and text_fp in (feats[j].get("text","").strip().lower()[:200]):
                    repeat_penalty = 0.25
                    break
            except Exception:
                pass

        # score fusion: weights (tuneable)
        # instant_score is strong if > instant_threshold
        w_instant = 0.55
        w_sem = 0.18
        w_cur_delta = 0.20
        w_speaker = 0.07

        fused = (w_instant * instant_score) + (w_sem * max(0.0, sem_delta)) + (w_cur_delta * max(0.0, cur_delta)) + (w_speaker * (1.0 if speaker_change else 0.0))
        fused = fused * (1.0 - repeat_penalty)
        # clamp
        fused = max(0.0, min(1.0, fused))

        # slope detection (fallback)
        slope = cur_delta  # simple delta; optionally use multi-step slope

        # decide ignition: either strong fused instant OR slope + curiosity absolute
        slope_condition = (slope >= min_slope and cur_here >= min_curiosity)
        instant_condition = (fused >= instant_threshold)

        # time spacing guard (optional): avoid two ignitions < min_separation_sec apart
        ign_time = float(_safe_get(feat, "start", 0.0) or 0.0)
        too_close = (ign_time - last_ign_time) < min_separation_sec

        accept = False
        reason_tags = {}
        if instant_condition and not too_close:
            accept = True
            reason_tags["instant_accept"] = True
        elif slope_condition and not too_close:
            accept = True
            reason_tags["slope_accept"] = True

        # small bonus: if sem_delta is very high (>0.15) allow acceptance even if below thresholds
        if not accept and sem_delta > 0.18 and not too_close:
            accept = True
            reason_tags["sem_boosted"] = True

        if accept:
            ignitions.append(i)
            last_ign_time = ign_time

        # collect debug row for tuning
        debug_rows.append({
            "idx": i,
            "start": float(_safe_get(feat, "start", 0.0)),
            "text_snip": (text[:140].replace("\n"," ") if text else ""),
            "instant_score": round(instant_score, 3),
            "fused": round(fused, 3),
            "sem_delta": round(sem_delta, 3),
            "cur_here": round(cur_here, 3),
            "cur_delta": round(cur_delta, 3),
            "slope_condition": slope_condition,
            "instant_condition": instant_condition,
            "speaker_change": speaker_change,
            "repeat_penalty": repeat_penalty,
            "accepted": accept,
            "reasons": inst_reasons if isinstance(inst_reasons, dict) else {}
        })

    # dedupe & sort
    ignitions = sorted(set(ignitions))

    if return_meta:
        return ignitions, debug_rows
    return ignitions

def detect_punch_end(feats, curiosity, start_idx, max_lookahead=10, drop_ratio=0.45, closure_extra=0.5):
    """
    Given a start index (ignition), scan forward and return the best end index (inclusive).
    Heuristics:
      - if curiosity drops below (peak * drop_ratio) => exhaustion
      - if closure/conclusion markers present in text => end
      - if long repeat (low semantic novelty for many segments) => end
    Returns end_idx (int)
    """
    N = len(feats)
    if start_idx >= N:
        return start_idx

    peak = curiosity[start_idx]
    # allow later curiosity to go higher (recompute local peak)
    local_max = peak
    end_idx = start_idx
    for j in range(start_idx, min(N, start_idx + max_lookahead)):
        local_max = max(local_max, curiosity[j])
    peak = local_max

    # scan forward to find end
    for i in range(start_idx + 1, min(N, start_idx + max_lookahead + 1)):
        f = feats[i]
        # closure words check
        txt = (f["text"] or "").lower()
        if txt.endswith((".", "!", "?")):
            # look for conclusion / CTA / summarizing tokens
            if any(w in txt for w in ("so remember", "in conclusion", "to summarize", "bottom line", "and that's", "the point is", "which is why", "this is why")):
                return i
        # exhaustion: curiosity drop relative to peak
        if curiosity[i] <= peak * drop_ratio:
            # allow a tiny extra segment to finish sentence
            return max(start_idx, i - 1)
        # long tail of low novelty
        if f["novelty"] < 0.05 and f["sem_density"] < 0.15 and (i - start_idx) >= 3:
            return max(start_idx, i - 1)
        end_idx = i

    # fallback: if nothing triggered, return a short extension (3 segments or until end)
    return min(N - 1, start_idx + min( max_lookahead, max(2, int((end_idx - start_idx) + 2))))

import re
from typing import List, Dict, Optional

_PROMISE_PATTERNS = [
    r"\bone thing\b", r"\bone mistake\b", r"\bthe reason\b", r"\bthis is why\b",
    r"\bthe key\b", r"\bthe problem\b", r"\bwhat happens when\b", r"\bthe truth\b",
    r"\bthe secret\b", r"\bi'll (show|tell)\b", r"\b(i want to tell|let me tell)\b",
    r"\bhere's why\b", r"\bthere's a (big )?reason\b", r"\bif you\b.*\bthen\b"
]

_RESOLUTION_PATTERNS = [
    r"\bis that\b", r"\bmeans\b", r"\bbecause\b", r"\bwhich is why\b",
    r"\bso the reason\b", r"\bthat's why\b", r"\bin other words\b",
    r"\bto fix that\b", r"\bthe answer is\b", r"\bhere's how\b", r"\btherefore\b",
    r"\bas a result\b", r"\bso remember\b", r"\band (that's|that is)\b"
]

_ENUM_MARKERS = [
    r"\bfirst\b", r"\bsecond\b", r"\bthird\b", r"\bnext\b", r"\banother\b",
    r"\bfinally\b", r"\bto begin\b", r"\bto start\b"
]

def _text_join(feat: dict) -> str:
    return (feat.get("text", "") if isinstance(feat, dict) else str(feat)) or ""

def detect_obligation_open_and_resolution(
    feats: List[dict],
    peak_idx: int,
    candidate_idx: int,
    lookback: int = 2,
    lookahead: int = 2
) -> Dict[str, Optional[object]]:
    """
    Layer-7: detect whether a promise/obligation is opened near the peak and whether
    it's closed/resolved at or before the candidate_idx.

    Returns meta:
      {
        "obligation_open": bool,
        "obligation_span": (start_idx, end_idx) or None,
        "obligation_phrase": str or None,
        "obligation_type": "enumeration"|"promise"|"question" or None,
        "obligation_confidence": 0..1,
        "obligation_closed": bool,
        "closure_phrase": str or None,
        "closure_confidence": 0..1
      }
    """
    N = len(feats)
    peak_idx = max(0, min(peak_idx, N-1))
    candidate_idx = max(0, min(candidate_idx, N-1))

    # examine window around peak for promise patterns
    lb = max(0, peak_idx - lookback)
    ub = min(N-1, peak_idx + lookahead)
    peak_texts = " ".join(_text_join(f) for f in feats[lb:ub+1]).lower()

    # heuristic scoring for obligation opening
    obligation_open = False
    obligation_type = None
    obligation_phrase = None
    score = 0.0

    # enumerate cues (explicit enumerations often imply promised items)
    for p in _ENUM_MARKERS:
        if re.search(p, peak_texts):
            obligation_open = True
            obligation_type = "enumeration"
            obligation_phrase = re.search(p, peak_texts).group(0)
            score = max(score, 0.55)

    # explicit promise / teaser patterns
    for p in _PROMISE_PATTERNS:
        m = re.search(p, peak_texts)
        if m:
            obligation_open = True
            obligation_type = obligation_type or "promise"
            obligation_phrase = obligation_phrase or m.group(0)
            score = max(score, 0.7)

    # rhetorical question / call-to-action that expects resolution
    if re.search(r"\b(have you ever|did you know|what if|how do you)\b", peak_texts):
        obligation_open = True
        obligation_type = obligation_type or "question"
        score = max(score, 0.5)

    # if nothing found -> not an obligation
    if not obligation_open:
        return {
            "obligation_open": False,
            "obligation_span": None,
            "obligation_phrase": None,
            "obligation_type": None,
            "obligation_confidence": 0.0,
            "obligation_closed": False,
            "closure_phrase": None,
            "closure_confidence": 0.0
        }

    # now check whether the candidate end (and small lookahead) contains resolution cues
    la = min(N-1, candidate_idx + lookahead)
    end_texts = " ".join(_text_join(f) for f in feats[max(0, candidate_idx - lookback):la+1]).lower()

    closure_found = None
    closure_conf = 0.0
    for p in _RESOLUTION_PATTERNS:
        m = re.search(p, end_texts)
        if m:
            closure_found = m.group(0)
            closure_conf = max(closure_conf, 0.7)

    # also treat short conclusive sentence as closure (e.g., "Do this." "It works.")
    last_seg = _text_join(feats[candidate_idx]).strip()
    if last_seg and len(last_seg.split()) <= 12 and last_seg.endswith((".", "!", "?")):
        # small boost if sentence starts with "so", "therefore", "in short"
        if re.match(r"^\s*(so|therefore|in short|remember|so remember)\b", last_seg.lower()):
            closure_found = closure_found or last_seg
            closure_conf = max(closure_conf, 0.75)
        else:
            closure_conf = max(closure_conf, 0.35)
            closure_found = closure_found or last_seg

    # If closure not found but end contains demonstrative pronouns referencing earlier noun (weak)
    if closure_conf < 0.4:
        # look for words: "this", "that", "these" nearby plus "means"/"is"
        if re.search(r"\b(this|that|these|those)\b", end_texts) and re.search(r"\b(is|means|means that|equals)\b", end_texts):
            closure_conf = max(closure_conf, 0.45)
            closure_found = closure_found or "demonstrative_resolution"

    return {
        "obligation_open": True,
        "obligation_span": (lb, ub),
        "obligation_phrase": obligation_phrase,
        "obligation_type": obligation_type,
        "obligation_confidence": round(float(score), 3),
        "obligation_closed": bool(closure_found),
        "closure_phrase": closure_found,
        "closure_confidence": round(float(closure_conf), 3)
    }
from typing import List, Dict, Optional

_TOPIC_SHIFT_MARKERS = [
    r"\banyway\b", r"\bmoving on\b", r"\bnow let's\b", r"\bnext\b", r"\bback to\b",
    r"\bchanging topic\b", r"\breturn to\b", r"\blet's talk about\b", r"\bonto\b"
]

def detect_topic_shift_override(
    feats: List[dict],
    peak_idx: int,
    candidate_idx: int,
    speaker_key: str = "speaker",
    lookback: int = 1,
    lookahead: int = 2
) -> Dict[str, Optional[object]]:
    """
    Layer-8: detect deliberate topic / speaker transition that *allows* closing even if
    an obligation looked open.

    Returns:
      {
        "override_allowed": bool,
        "reason": str or None,
        "speaker_changed": bool,
        "transition_phrase": str or None,
        "confidence": 0..1
      }

    Heuristics:
      - Strong override when speaker changed around the candidate AND candidate contains explicit
        transition markers ("anyway", "moving on", "next").
      - Mild override when candidate end contains "by the way", "btw", "also" with speaker change.
      - No override if obligation_open is strong and candidate contains no transition markers.
    """
    N = len(feats)
    peak_idx = max(0, min(peak_idx, N-1))
    candidate_idx = max(0, min(candidate_idx, N-1))

    # speaker change detection (if metadata exists)
    speaker_changed = False
    s_peak = feats[peak_idx].get(speaker_key) if isinstance(feats[peak_idx], dict) else None
    s_cand = feats[candidate_idx].get(speaker_key) if isinstance(feats[candidate_idx], dict) else None
    if s_peak is not None and s_cand is not None and s_peak != s_cand:
        speaker_changed = True

    # find transition tokens in small window around candidate end
    la = min(N-1, candidate_idx + lookahead)
    window_text = " ".join((feats[i].get("text","") if isinstance(feats[i], dict) else "") for i in range(max(0, candidate_idx - lookback), la+1)).lower()

    transition_phrase = None
    trans_conf = 0.0
    for p in _TOPIC_SHIFT_MARKERS:
        m = re.search(p, window_text)
        if m:
            transition_phrase = m.group(0)
            trans_conf = max(trans_conf, 0.75)

    # milder cues that suggest speaker is wrapping or segueing
    if trans_conf < 0.6:
        if re.search(r"\b(by the way|btw|also|oh and)\b", window_text):
            transition_phrase = transition_phrase or "by_the_way"
            trans_conf = max(trans_conf, 0.45)

    # override rule:
    # - if speaker changed AND there is a transition marker => strong override
    # - if speaker changed & mild cue => medium override (allow with lower confidence)
    # - if no speaker change but strong transition phrase => allow mild override
    override_allowed = False
    reason = None
    conf = 0.0
    if speaker_changed and trans_conf >= 0.45:
        override_allowed = True
        reason = "speaker_change_with_transition"
        conf = trans_conf + 0.15
    elif trans_conf >= 0.75:
        override_allowed = True
        reason = "explicit_transition_marker"
        conf = trans_conf
    elif speaker_changed and trans_conf >= 0.3:
        override_allowed = True
        reason = "speaker_change_mild"
        conf = 0.35

    return {
        "override_allowed": bool(override_allowed),
        "reason": reason,
        "speaker_changed": bool(speaker_changed),
        "transition_phrase": transition_phrase,
        "confidence": round(min(1.0, float(conf)), 3)
    }

import math
from typing import List, Tuple, Optional, Dict

def detect_payoff_end(
    feats: List[dict],
    curiosity,
    start_idx: int,
    end_idx: Optional[int] = None,
    window: int = 2,
    slope_thresh: float = -0.015,
    sem_delta_thresh: float = 0.08,
    punch_delta_eps: float = 0.02,
    aftertaste: float = 0.5,
    min_clip_len: float = 1.0,
    min_confidence: float = 0.25,
    return_meta: bool = True,
    debug: bool = False
) -> Tuple[Optional[float], float, dict]:
    """
    Robust payoff detector with multi-layer gating.
    Returns (payoff_time or None, confidence, meta_dict) when return_meta=True.
    Otherwise returns (payoff_time or None, confidence).
    """

    # quick guards
    meta = {"reason": None}
    if not feats or start_idx is None:
        meta["reason"] = "no_feats_or_start"
        return (None, 0.0, meta) if return_meta else (None, 0.0)

    N = len(feats)
    if end_idx is None:
        end_idx = N - 1
    start_idx = max(0, min(int(start_idx), N - 1))
    end_idx = max(0, min(int(end_idx), N - 1))
    if start_idx >= end_idx:
        meta["reason"] = "invalid_range"
        return (None, 0.0, meta) if return_meta else (None, 0.0)

    # --- handle curiosity robustly (numpy or list) ---
    try:
        import numpy as _np
        cur = _np.asarray(curiosity, dtype=_np.float32)
        use_numpy = True
    except Exception:
        cur = [float(c) for c in (curiosity or [f.get("curiosity", 0.0) for f in feats])]
        use_numpy = False

    def cur_slice(a, b):
        if use_numpy:
            return cur[a:b+1]
        return cur[a:b+1]

    # clip the search slice
    try:
        seg_slice = cur_slice(start_idx, end_idx)
        if len(seg_slice) == 0:
            meta["reason"] = "empty_curiosity_slice"
            return (None, 0.0, meta) if return_meta else (None, 0.0)
    except Exception:
        cur = [float(f.get("curiosity", 0.0)) for f in feats]
        use_numpy = False
        seg_slice = cur[start_idx:end_idx+1]
        if not seg_slice:
            meta["reason"] = "empty_curiosity_slice"
            return (None, 0.0, meta) if return_meta else (None, 0.0)

    # locate peak (first occurrence of max after start)
    try:
        if use_numpy and hasattr(seg_slice, "argmax"):
            rel_peak = int(seg_slice.argmax())
        else:
            rel_peak = int(max(range(len(seg_slice)), key=lambda i: seg_slice[i]))
    except Exception:
        rel_peak = int(max(range(len(seg_slice)), key=lambda i: seg_slice[i]))
    peak_idx = start_idx + rel_peak

    if peak_idx >= end_idx:
        meta["reason"] = "peak_at_or_after_end"
        meta["peak_idx"] = peak_idx
        return (None, 0.0, meta) if return_meta else (None, 0.0)
    
    # helper: robust feature arrays
    def _get_feat_array(key, default=0.0):
        arr = []
        for f in feats:
            try:
                arr.append(float(f.get(key, default)))
            except Exception:
                arr.append(default)
        return arr

    semd = _get_feat_array("sem_density", 0.0)
    
    def opens_new_obligation(text):
        if not text:
           return False
        t = text.lower()
        triggers = (
        "next",
        "but then",
        "now let's",
        "what happens next",
        "so the next thing",
        "which brings us to",
        "let me explain",
        "this is where",
    )
        return any(k in t for k in triggers)


    # punch proxy
    def _punch_proxy_text(txt: str) -> float:
        if not txt:
            return 0.0
        t = txt.lower()
        score = 0.0
        if "in short" in t or "to sum up" in t or "in summary" in t or "the point is" in t:
            score += 0.7
        if t.strip().endswith((".", "!", "?")) and len(t.split()) <= 12 and (t.split()[0] in ("so", "and")):
            score += 0.25
        for w in ("but", "however", "on the other hand", "instead"):
            if w in t:
                score += 0.12
        if "?" in t:
            score += 0.10
        return float(min(1.0, score))

    punch = [_punch_proxy_text(f.get("text", "") if isinstance(f, dict) else "") for f in feats]

    # mean window that supports numpy or list
    def mean_window(arr, a, b):
        if a < 0:
            a = 0
        if b >= len(arr):
            b = len(arr) - 1
        cnt = b - a + 1
        if cnt <= 0:
            return 0.0
        try:
            if use_numpy and hasattr(arr, "astype"):
                sl = arr[a:b+1]
                return float(sl.mean()) if len(sl) else 0.0
        except Exception:
            pass
        s = 0.0
        for i in range(a, b + 1):
            s += float(arr[i])
        return s / max(1.0, cnt)

    best_score = 0.0
    best_idx = None
    best_gates = {}
    debug_rows = []

    # sliding scan from peak forward
    for t in range(peak_idx + 1, end_idx + 1):
        prev_s = max(start_idx, t - window)
        prev_e = t - 1
        cur_s = t
        cur_e = min(end_idx, t + window - 1)
        if prev_s > prev_e or cur_s > cur_e:
            continue

        prev_cur_mean = mean_window(cur, prev_s, prev_e)
        cur_cur_mean = mean_window(cur, cur_s, cur_e)
        slope = (cur_cur_mean - prev_cur_mean) / max(1.0, (cur_e - cur_s + 1))

        prev_sem = mean_window(semd, prev_s, prev_e)
        cur_sem = mean_window(semd, cur_s, cur_e)
        sem_delta = cur_sem - prev_sem

        prev_p = mean_window(punch, prev_s, prev_e)
        cur_p = mean_window(punch, cur_s, cur_e)
        punch_delta = cur_p - prev_p

        # plateau detection (hard reject)
        plateau_flag = (abs(slope) < 0.005 and abs(sem_delta) < sem_delta_thresh)
        if plateau_flag:
            # skip plateau candidates: not a payoff
            debug_rows.append({
                "t_idx": t, "reason": "plateau_reject",
                "slope": slope, "sem_delta": sem_delta,
                "prev_cur": prev_cur_mean, "cur_cur": cur_cur_mean
            })
            continue

        # semantic momentum veto (meaning is still growing strongly) -> skip
        if sem_delta > (sem_delta_thresh * 1.2):
            debug_rows.append({
                "t_idx": t, "reason": "sem_momentum_veto",
                "slope": slope, "sem_delta": sem_delta,
                "prev_cur": prev_cur_mean, "cur_cur": cur_cur_mean
            })
            continue
        
        # compute graded strengths
        A_strength = 0.0
        if slope <= slope_thresh:
            A_strength = min(1.0, abs(slope) / max(1e-6, abs(slope_thresh)))
        B_strength = max(0.0, 1.0 - min(1.0, abs(sem_delta) / max(1e-6, sem_delta_thresh * 3.0)))
        C_strength = max(0.0, 1.0 - min(1.0, abs(punch_delta) / max(1e-6, punch_delta_eps * 3.0)))

        base_score = (0.45 * A_strength) + (0.30 * B_strength) + (0.25 * C_strength)
        # =========================
        # LAYER 7: INTENT FINALITY
        # =========================
        intent_final = True
        if cur_e + 1 < len(feats):
           next_txt = feats[cur_e + 1].get("text", "")
        if opens_new_obligation(next_txt):
           intent_final = False

        gates["intent_final"] = intent_final
        if not intent_final:
           base_score *= 0.1   # strong penalty

        # =========================
        # LAYER 8: SEMANTIC COMMITMENT
        # =========================
        semantic_commit = semantic_commitment_closing(semd, cur_e)
        gates["semantic_commitment"] = semantic_commit
        if not semantic_commit:
           base_score *= 0.15  # heavy penalty

        # closure detection
        seg_txt = ""
        try:
            seg_txt = (feats[cur_e].get("text", "") if isinstance(feats[cur_e], dict) else "")
        except Exception:
            seg_txt = ""
        lowtxt = seg_txt.lower()
        closure_here = any(k in lowtxt for k in ("in short", "to sum up", "the point is", "remember that", "so here's", "so remember"))
        if closure_here:
            base_score = max(base_score, 0.75)

        # punch without closure should be softened (fake-closure)
        if punch_delta > 0.2 and not closure_here:
            base_score *= 0.5

        # sentence-complete small boost
        if seg_txt.strip().endswith((".", "!", "?")) and len(seg_txt.split()) < 40:
            base_score += 0.05

        # aftertaste check: future curiosity must NOT rise above current window mean
        future_s = cur_e + 1
        future_e = min(end_idx, cur_e + window)
        future_mean = mean_window(cur, future_s, future_e) if future_s <= future_e else cur_cur_mean
        aftertaste_ok = (future_mean <= cur_cur_mean)

        # clip length / obligation closed
        clip_start_time = float(feats[start_idx].get("start", 0.0))
        seg_end_time = float(feats[cur_e].get("end", feats[cur_e].get("start", clip_start_time)))
        clip_len = seg_end_time - clip_start_time
        min_len_ok = (clip_len >= min_clip_len)
        obligation_closed = not (sem_delta > (sem_delta_thresh * 1.2))

        # if clip too short, reject
        if not min_len_ok:
            base_score = 0.0

        # record debug row + gates
        gates = {
            "curiosity_fall": (slope <= slope_thresh),
            "semantic_flat": (abs(sem_delta) <= sem_delta_thresh),
            "punch_stable": (abs(punch_delta) <= punch_delta_eps),
            "closure_authentic": closure_here,
            "obligation_closed": obligation_closed,
            "aftertaste_stable": aftertaste_ok,
            "min_len": min_len_ok,
            "plateau": plateau_flag
        }

        debug_rows.append({
            "t_idx": t,
            "prev_cur": prev_cur_mean,
            "cur_cur": cur_cur_mean,
            "slope": slope,
            "prev_sem": prev_sem,
            "cur_sem": cur_sem,
            "sem_delta": sem_delta,
            "prev_p": prev_p,
            "cur_p": cur_p,
            "punch_delta": punch_delta,
            "closure_here": closure_here,
            "aftertaste_ok": aftertaste_ok,
            "base_score": base_score,
            "seg_end_time": seg_end_time,
            "clip_len": clip_len,
            "gates": gates
        })

        # pick candidate if score is best so far
        if base_score > best_score:
            best_score = base_score
            best_idx = cur_e
            best_gates = dict(gates)
            # store last chosen meta so we can return detailed info
            peak_time = float(feats[peak_idx].get("end", feats[peak_idx].get("start", 0.0)))
            chosen_time_tmp = min(float(feats[end_idx].get("end", seg_end_time)), seg_end_time + aftertaste)
            best_meta_snapshot = {
                "peak_idx": peak_idx,
                "peak_time": peak_time,
                "chosen_idx": best_idx,
                "chosen_time": round(chosen_time_tmp, 3),
                "score_raw": round(best_score, 3),
                "debug_rows": list(debug_rows)
            }

        # early accept on clear closure and min_len
        if closure_here and min_len_ok:
            chosen_time = min(float(feats[end_idx].get("end", seg_end_time)), seg_end_time + aftertaste)
            meta = {
                "reason": "closure_marker",
                "peak_idx": peak_idx,
                "peak_time": float(feats[peak_idx].get("end", feats[peak_idx].get("start", 0.0))),
                "chosen_idx": cur_e,
                "chosen_time": round(chosen_time, 3),
                "score_raw": max(0.0, min(1.0, base_score)),
                "debug_rows": debug_rows,
                "gates": gates
            }
            if debug:
                print("[detect_payoff_end] closure_accept:", meta)
            return (round(chosen_time, 3), round(max(0.0, min(1.0, base_score)), 3), meta) if return_meta else (round(chosen_time, 3), round(max(0.0, min(1.0, base_score)), 3))


    # Post-scan: final decision
    if best_idx is None:
        meta = {"reason": "no_candidate_found", "debug_rows": debug_rows}
        return (None, 0.0, meta) if return_meta else (None, 0.0)
    required = (
    best_gates.get("intent_final") and
    best_gates.get("semantic_commitment") and
    best_gates.get("aftertaste_stable") and
    best_gates.get("min_len")
)

    if not required:
        meta = {
        "reason": "gated_reject",
        "gates": best_gates,
        "debug_rows": debug_rows
    }
        return (None, 0.0, meta) if return_meta else (None, 0.0)

    # enforce HARD gating before accepting scored candidate
    # require: (curiosity_fall OR closure_authentic) AND (semantic_flat OR closure_authentic) AND aftertaste AND obligation_closed AND min_len
    gates_ok = (
        (best_gates.get("curiosity_fall", False) or best_gates.get("closure_authentic", False))
        and (best_gates.get("semantic_flat", False) or best_gates.get("closure_authentic", False))
        and best_gates.get("aftertaste_stable", False)
        and best_gates.get("obligation_closed", False)
        and best_gates.get("min_len", False)
    )

    if not gates_ok:
        meta = {
            "reason": "gated_reject",
            "best_score": round(best_score, 3),
            "best_idx": best_idx,
            "best_gates": best_gates,
            "debug_rows": debug_rows
        }
        if debug:
            print("[detect_payoff_end] gated_reject:", meta)
        return (None, 0.0, meta) if return_meta else (None, 0.0)

    # gates passed -> accept
    seg_end_time = float(feats[best_idx].get("end", feats[best_idx].get("start", 0.0)))
    chosen_time = min(float(feats[end_idx].get("end", seg_end_time)), seg_end_time + aftertaste)
    meta = {
        "reason": "gated_accept",
        "peak_idx": peak_idx,
        "peak_time": float(feats[peak_idx].get("start", 0.0)),
        "chosen_idx": best_idx,
        "chosen_time": round(chosen_time, 3),
        "score_raw": round(best_score, 3),
        "gates": best_gates,
        "debug_rows": debug_rows
    }
    if debug:
        print("[detect_payoff_end] gated_accept:", meta)

    return (round(chosen_time, 3), round(best_score, 3), meta) if return_meta else (round(chosen_time, 3), round(best_score, 3))

def indices_to_time(feats, start_idx, end_idx, pad_before=0.4, pad_after=0.6):
    """Convert segment indices to clip time with small padding (seconds)."""
    if not feats:
        return 0.0, 0.5
    s = max(0.0, feats[start_idx]["start"] - pad_before)
    e = min(feats[-1]["end"], feats[end_idx]["end"] + pad_after)
    return round(float(s), 2), round(float(e), 2)


# ----------------------------------------
# Core: build idea graph
# ----------------------------------------
def build_idea_graph(
    transcript: List[Dict],
    aud: Optional[List[Dict]] = None,
    vis: Optional[List[Dict]] = None,
    curiosity_candidates: Optional[List[Any]] = None,
    narrative_triggers: Optional[List[Dict[str, Any]]] = None,
    brain: Optional[Any] = None,
    disable_coalesce: bool = False,
    disable_node_cap: bool = False,
) -> List[IdeaNode]:
    """
    Build idea nodes from transcript segments.

    transcript: list of {"start": float, "end": float, "text": str}
    aud: optional list of {"time": float, "energy": float}
    vis: optional list of {"time": float, "motion": float}

    Returns: list of IdeaNode objects (state may be OPEN until analyzed)
    """
    if not transcript:
        return []

    # prepare arrays
    N = len(transcript)
    texts = [normalize_text(seg.get("text", "")) for seg in transcript]
    starts = [float(seg.get("start", 0.0)) for seg in transcript]
    ends = [float(seg.get("end", seg.get("start", 0.0) + 0.01)) for seg in transcript]
    durations = [max(0.01, e - s) for s, e in zip(starts, ends)]
    avg_seg_dur = float(statistics.mean(durations)) if durations else 0.5
    log.info(
        "[COALESCE-CONFIG] time_tol=%.2f sem_thr=%.2f max_node_secs=%.2f",
        float(COALESCE_TIME_TOL_DEFAULT),
        float(SEM_SIM_THRESHOLD_DEFAULT),
        float(IDEA_MAX_NODE_SECONDS),
    )

    arcs = []
    cur_s = 0
    cur_e = 0
    cur_text_window = texts[0]

    for i in range(1, N):
        gap = starts[i] - ends[i - 1]
        sem_drift = text_overlap(cur_text_window[-1200:], texts[i])
        # Rollback: don't treat "semantic drift" as a boundary unless there's actual silence/pause.
        # Dense transcripts often have low overlap between micro-segments while still staying on one idea.
        max_gap = min(2.0, max(0.8, avg_seg_dur * 2.0))
        if sem_drift < SEM_DRIFT_BREAK and gap > max_gap:
            # semantic drift -> close arc
            log.debug("[IDEA] drift break at seg=%d overlap=%.2f gap=%.2f", i, sem_drift, gap)
            segs = transcript[cur_s:cur_e + 1]
            txt = " ".join(s.get("text", "") for s in segs).strip()
            start_t = float(transcript[cur_s].get("start", 0.0))
            end_t = float(transcript[cur_e].get("end", start_t + 0.01))
            arcs.append((cur_s, cur_e, start_t, end_t, txt, segs))
            cur_s = i
            cur_e = i
            cur_text_window = texts[i]
            continue

        if same_thought(cur_text_window, texts[i], gap, avg_seg_dur, N):
            cur_e = i
            cur_text_window = (cur_text_window + " " + texts[i])[-2400:]
        else:
            # close current arc
            segs = transcript[cur_s:cur_e + 1]
            txt = " ".join(s.get("text", "") for s in segs).strip()
            start_t = float(transcript[cur_s].get("start", 0.0))
            end_t = float(transcript[cur_e].get("end", start_t + 0.01))
            arcs.append((cur_s, cur_e, start_t, end_t, txt, segs))
            # new arc
            cur_s = i
            cur_e = i
            cur_text_window = texts[i]

    # finalize last
    segs = transcript[cur_s:cur_e + 1]
    txt = " ".join(s.get("text", "") for s in segs).strip()
    start_t = float(transcript[cur_s].get("start", 0.0))
    end_t = float(transcript[cur_e].get("end", start_t + 0.01))
    arcs.append((cur_s, cur_e, start_t, end_t, txt, segs))

    # transform arcs into IdeaNodes with analysis
    nodes = []
    for (s_idx, e_idx, s_time, e_time, txt, segs) in arcs:
        curiosity = detect_curiosity_score(txt)
        contrast = detect_contrast_strength(txt)
        conclusion = detect_conclusion_marker(txt)
        # rough semantic quality: length + curiosity + contrast
        wc = len(tokens(txt))
        semantic_quality = min(1.0, 0.25 + (min(1.0, wc/40.0) * 0.4) + curiosity*0.25 + contrast*0.1)

        # punch confidence: high if conclusion markers or strong contrast
        punch = 0.0
        if conclusion:
            punch += 0.65
        punch += contrast * 0.25
        if "?" in txt:
            punch += 0.12
        punch = min(1.0, punch)

        # metrics: optionally incorporate audio/visual averages
        metrics = {}
        if aud:
            a_vals = [x.get("energy",0.0) for x in aud if s_time <= x.get("time",0.0) <= e_time]
            metrics["audio_mean"] = float(statistics.mean(a_vals)) if a_vals else 0.0
        else:
            metrics["audio_mean"] = 0.0

        if vis:
            m_vals = [x.get("motion",0.0) for x in vis if s_time <= x.get("time",0.0) <= e_time]
            metrics["motion_mean"] = float(statistics.mean(m_vals)) if m_vals else 0.0
        else:
            metrics["motion_mean"] = 0.0

        # state heuristics
        state = OPEN
        if conclusion or punch >= 0.6:
            state = RESOLUTION
        elif "?" in txt or detect_curiosity_score(txt) > 0.18:
            state = TENSION
        else:
            state = DEVELOPMENT

        node_text = normalize_text(txt)
        fp = fingerprint_text(node_text[:2000])

        node = IdeaNode(
            start_idx = int(s_idx),
            end_idx = int(e_idx),
            start_time = float(s_time),
            end_time = float(e_time),
            segments = segs,
            text = node_text,
            state = state,
            curiosity_score = round(curiosity, 3),
            punch_confidence = round(punch, 3),
            semantic_quality = round(semantic_quality, 3),
            fingerprint = fp,
            metrics = metrics
        )
        nodes.append(node)

    # dedupe / coalesce nodes that are extremely similar or overlapping heavily
    if not disable_coalesce:
        cap = 0.0 if disable_node_cap else float(IDEA_MAX_NODE_SECONDS)
        nodes = coalesce_nodes(nodes, max_node_secs=cap)

    # If external curiosity candidates are provided, use them to seed or refine nodes.
    if curiosity_candidates:
        for cand in curiosity_candidates:
            try:
                if isinstance(cand, dict):
                    s_idx = int(cand.get("start_idx", cand.get("start", 0)))
                    e_idx = int(cand.get("end_idx", cand.get("end", s_idx)))
                    meta = cand.get("meta", cand)
                else:
                    s_idx, e_idx, meta = cand

                s_idx = max(0, min(len(transcript)-1, int(s_idx)))
                e_idx = max(s_idx, min(len(transcript)-1, int(e_idx)))

                s_time = float(transcript[s_idx].get("start", 0.0))
                e_time = float(transcript[e_idx].get("end", transcript[s_idx].get("start", 0.0)+0.01))

                overlap_found = False
                for i, n in enumerate(nodes):
                    if not (e_time <= n.start_time or s_time >= n.end_time):
                        overlap_found = True
                        peak = float(meta.get("curiosity_peak", meta.get("curiosity", 0.0))) if meta else 0.0
                        start_c = float(meta.get("curiosity_at_start", 0.0)) if meta else 0.0
                        metrics = dict(n.metrics or {})
                        metrics["curiosity_peak"] = max(metrics.get("curiosity_peak", 0.0), peak)
                        metrics["curiosity_at_start"] = max(metrics.get("curiosity_at_start", 0.0), start_c)
                        # propagate payoff metadata when present
                        if meta:
                            if meta.get("payoff_time") is not None:
                                metrics["payoff_time"] = max(metrics.get("payoff_time", 0.0), float(meta.get("payoff_time", 0.0)))
                            if meta.get("payoff_confidence") is not None:
                                metrics["payoff_confidence"] = max(metrics.get("payoff_confidence", 0.0), float(meta.get("payoff_confidence", 0.0)))
                        new_curio = max(n.curiosity_score, round(peak, 3))
                        new_punch = max(n.punch_confidence, float(meta.get("punch_confidence", n.punch_confidence)) if meta else n.punch_confidence)
                        nodes[i] = n._replace(curiosity_score=round(new_curio,3), punch_confidence=round(new_punch,3), metrics=metrics)
                        break

                if not overlap_found:
                    segs = transcript[s_idx:e_idx+1]
                    txt = " ".join(s.get("text","") for s in segs).strip()
                    wc = len(tokens(txt))
                    semantic_quality = min(1.0, 0.25 + (min(1.0, wc/40.0) * 0.4) + detect_curiosity_score(txt)*0.25 + detect_contrast_strength(txt)*0.1)
                    punch = float(meta.get("punch_confidence", 0.0)) if meta else 0.0
                    curiosity_val = float(meta.get("curiosity_peak", meta.get("curiosity_at_start", detect_curiosity_score(txt)))) if meta else detect_curiosity_score(txt)
                    metrics = {"curiosity_peak": float(meta.get("curiosity_peak", 0.0)) if meta else 0.0, "curiosity_at_start": float(meta.get("curiosity_at_start", 0.0)) if meta else 0.0}
                    # include payoff metadata when available
                    if meta:
                        if meta.get("payoff_time") is not None:
                            metrics["payoff_time"] = float(meta.get("payoff_time", 0.0))
                        if meta.get("payoff_confidence") is not None:
                            metrics["payoff_confidence"] = float(meta.get("payoff_confidence", 0.0))
                    fp = fingerprint_text(txt[:2000])
                    new_node = IdeaNode(
                        start_idx=int(s_idx), end_idx=int(e_idx), start_time=float(s_time), end_time=float(e_time),
                        segments=segs, text=normalize_text(txt), state=OPEN,
                        curiosity_score=round(float(curiosity_val),3), punch_confidence=round(float(punch),3),
                        semantic_quality=round(float(semantic_quality),3), fingerprint=fp, metrics=metrics
                    )
                    nodes.append(new_node)
            except Exception:
                continue

        # re-coalesce after injecting candidates
        if not disable_coalesce:
            cap = 0.0 if disable_node_cap else float(IDEA_MAX_NODE_SECONDS)
            nodes = coalesce_nodes(nodes, max_node_secs=cap)

    # Narrative trigger boost (non-ML O(n*m), bounded by node count, small in practice)
    if narrative_triggers:
        def _ovr(a_s, a_e, b_s, b_e):
            inter = max(0.0, min(a_e, b_e) - max(a_s, b_s))
            if inter <= 0.0:
                return 0.0
            shorter = max(1e-6, min(a_e - a_s, b_e - b_s))
            return float(inter / shorter)

        boosted_nodes = []
        for n in nodes:
            metrics = dict(n.metrics or {})
            trigger_hits = []
            trigger_weight = 0.0
            trigger_type = None
            for tr in narrative_triggers:
                ts = float(tr.get("start", 0.0) or 0.0)
                te = float(tr.get("end", ts) or ts)
                if _ovr(float(n.start_time), float(n.end_time), ts, te) <= 0.0:
                    continue
                conf = float(tr.get("confidence", 0.0) or 0.0)
                trigger_weight = max(trigger_weight, conf)
                if trigger_type is None:
                    trigger_type = tr.get("type")
                trigger_hits.append(tr)
            if trigger_hits:
                metrics["narrative_trigger_weight"] = round(float(trigger_weight), 4)
                metrics["narrative_trigger_type"] = trigger_type
                metrics["narrative_trigger_count"] = int(len(trigger_hits))
                boosted_sem = min(1.0, float(n.semantic_quality) + (0.10 * float(trigger_weight)))
                boosted_nodes.append(n._replace(semantic_quality=round(boosted_sem, 3), metrics=metrics))
            else:
                boosted_nodes.append(n)
        nodes = boosted_nodes

    # DEBUG: log grouping summary and pairwise semantic similarity
    try:
        log.info("[IDEA] segments=%d arcs=%d nodes=%d avg_seg_dur=%.2fs", N, len(arcs), len(nodes), avg_seg_dur)
        if 1 < len(nodes) <= 10:
            sims = []
            for i in range(len(nodes)):
                for j in range(i + 1, len(nodes)):
                    sims.append(f"{i}-{j}:{text_overlap(nodes[i].text, nodes[j].text):.2f}")
            log.info("[IDEA] node_pair_semantic_overlap: %s", "; ".join(sims))

        # Logging-only invariants for regression detection (no behavior change)
        if N > 40 and len(nodes) < 3:
            log.warning("[INVARIANT] transcript_segments=%d idea_nodes=%d arcs=%d", N, len(nodes), len(arcs))
        if len(nodes) == 1:
            n0 = nodes[0]
            try:
                dur = float(n0.end_time) - float(n0.start_time)
            except Exception:
                dur = 0.0
            log.warning(
                "[INVARIANT] idea_nodes=1 node_words=%d node_chars=%d dur=%.2fs start=%.2f end=%.2f",
                len(tokens(n0.text or "")),
                len(n0.text or ""),
                dur,
                float(n0.start_time),
                float(n0.end_time),
            )
    except Exception:
        pass

    return nodes

# ----------------------------------------
# Coalescing / dedupe
# ----------------------------------------
def _split_node_if_too_long(node: IdeaNode, max_node_secs: float) -> List[IdeaNode]:
    """Split an oversized idea node into contiguous chunks by segment boundaries."""
    try:
        duration = float(node.end_time) - float(node.start_time)
    except Exception:
        duration = 0.0

    if max_node_secs <= 0 or duration <= max_node_secs:
        return [node]

    segs = list(node.segments or [])
    if len(segs) <= 1:
        return [node]

    split_nodes = []
    chunk = []
    chunk_start_idx = int(node.start_idx)
    seg_idx_cursor = int(node.start_idx)

    def _build_chunk(chunk_segs: List[Dict[str, Any]], start_idx: int) -> Optional[IdeaNode]:
        if not chunk_segs:
            return None
        try:
            start_t = float(chunk_segs[0].get("start", node.start_time))
        except Exception:
            start_t = float(node.start_time)
        try:
            end_t = float(chunk_segs[-1].get("end", start_t))
        except Exception:
            end_t = float(start_t)
        if end_t <= start_t:
            end_t = start_t + 0.01

        txt = " ".join((s.get("text", "") or "").strip() for s in chunk_segs).strip()
        txt = normalize_text(txt)
        wc = len(tokens(txt))
        curio = detect_curiosity_score(txt)
        punch = 0.0
        if detect_conclusion_marker(txt):
            punch += 0.65
        punch += detect_contrast_strength(txt) * 0.25
        if "?" in txt:
            punch += 0.12
        punch = min(1.0, punch)
        sem = min(
            1.0,
            0.25
            + (min(1.0, wc / 40.0) * 0.4)
            + (curio * 0.25)
            + (detect_contrast_strength(txt) * 0.1),
        )
        end_idx = int(start_idx + max(0, len(chunk_segs) - 1))
        return IdeaNode(
            start_idx=int(start_idx),
            end_idx=end_idx,
            start_time=float(start_t),
            end_time=float(end_t),
            segments=chunk_segs,
            text=txt,
            state=node.state,
            curiosity_score=round(float(curio), 3),
            punch_confidence=round(float(punch), 3),
            semantic_quality=round(float(max(sem, 0.0)), 3),
            fingerprint=fingerprint_text((txt or "")[:2000]),
            metrics=dict(node.metrics or {}),
        )

    for seg in segs:
        seg_start = float(seg.get("start", chunk[0].get("start", seg.get("start", 0.0)) if chunk else seg.get("start", 0.0)))
        seg_end = float(seg.get("end", seg_start))
        if chunk:
            chunk_window = float(seg_end) - float(chunk[0].get("start", seg_start))
            if chunk_window > max_node_secs:
                built = _build_chunk(chunk, chunk_start_idx)
                if built is not None:
                    split_nodes.append(built)
                chunk = [seg]
                chunk_start_idx = seg_idx_cursor
            else:
                chunk.append(seg)
        else:
            chunk = [seg]
            chunk_start_idx = seg_idx_cursor
        seg_idx_cursor += 1

    built_last = _build_chunk(chunk, chunk_start_idx)
    if built_last is not None:
        split_nodes.append(built_last)

    if len(split_nodes) > 1:
        log.info(
            "[COALESCE] force_split node %.2f-%.2f dur=%.2fs chunks=%d max_node_secs=%.2f",
            float(node.start_time),
            float(node.end_time),
            float(duration),
            len(split_nodes),
            float(max_node_secs),
        )

    return split_nodes or [node]


def _force_split_overlong_nodes(nodes: List[IdeaNode], max_node_secs: float) -> List[IdeaNode]:
    if not nodes or max_node_secs <= 0:
        return nodes or []
    out = []
    for n in nodes:
        out.extend(_split_node_if_too_long(n, max_node_secs=max_node_secs))
    return out


def coalesce_nodes(
    nodes: List[IdeaNode],
    time_tol: float = COALESCE_TIME_TOL_DEFAULT,
    sem_sim_threshold: float = SEM_SIM_THRESHOLD_DEFAULT,
    max_node_secs: float = IDEA_MAX_NODE_SECONDS,
) -> List[IdeaNode]:
    if not nodes:
        return []
    raw_cap = float(max_node_secs if max_node_secs is not None else IDEA_MAX_NODE_SECONDS)
    cap_enabled = raw_cap > 0.0
    max_node_secs = max(3.0, raw_cap) if cap_enabled else 1e9
    ordered_nodes = sorted(nodes, key=lambda x: (x.start_time, -x.semantic_quality))

    dense_ratio = 0.0
    adaptive_time_tol = float(time_tol)
    if len(ordered_nodes) > 1:
        gaps0 = []
        for idx in range(1, len(ordered_nodes)):
            g = float(ordered_nodes[idx].start_time - ordered_nodes[idx - 1].end_time)
            gaps0.append(g)
        nonneg_gaps = [max(0.0, g) for g in gaps0]
        if nonneg_gaps:
            dense_hits = sum(1 for g in nonneg_gaps if g <= 0.08)
            dense_ratio = float(dense_hits) / float(len(nonneg_gaps))
            if dense_ratio >= 0.75:
                adaptive_time_tol = min(adaptive_time_tol, 0.18)
            elif dense_ratio >= 0.60:
                adaptive_time_tol = min(adaptive_time_tol, 0.22)
    log.info(
        "[COALESCE-CONFIG] base_time_tol=%.2f adaptive_time_tol=%.2f sem_thr=%.2f dense_ratio=%.2f max_node_secs=%.2f",
        float(time_tol),
        float(adaptive_time_tol),
        float(sem_sim_threshold),
        float(dense_ratio),
        float(max_node_secs),
    )

    merge_stats = {"total": 0, "overlap": 0, "close": 0, "sem": 0, "close_and_sem": 0, "exhaust": 0}
    gap_samples = []
    sem_samples = []

    merged = []
    for n in ordered_nodes:
        if not merged:
            merged.append(n)
            continue
        prev = merged[-1]
        # temporal gap
        gap = n.start_time - prev.end_time
        sem_sim = text_overlap(prev.text, n.text)
        try:
            gap_samples.append(float(gap))
            sem_samples.append(float(sem_sim))
        except Exception:
            pass

        # --- IDEA EXHAUSTION detector ---
        def idea_exhaustion(prev: IdeaNode, curr: IdeaNode,
                            punch_eps: float = 0.08,
                            sem_eps: float = 0.06,
                            curiosity_drop_thresh: float = 0.18) -> Optional[float]:
            """
            If exhaustion is detected between prev and curr, return a suggested end_time
            (float) for prev that trims it near the punch delivery; otherwise return None.
            Criteria:
              - same state
              - small punch diff
              - small semantic_quality diff
              - prev.curiosity - curr.curiosity >= curiosity_drop_thresh
            """
            try:
                if prev.state != curr.state:
                    return None
                if abs(prev.punch_confidence - curr.punch_confidence) > punch_eps:
                    return None
                if abs(prev.semantic_quality - curr.semantic_quality) > sem_eps:
                    return None
                if (prev.curiosity_score - curr.curiosity_score) < curiosity_drop_thresh:
                    return None

                # locate best punch moment inside prev's segments
                best_score = 0.0
                best_t = None
                for seg in prev.segments:
                    txt = (seg.get("text", "") or "")
                    p = 0.0
                    if detect_conclusion_marker(txt):
                        p += 0.65
                    p += detect_contrast_strength(txt) * 0.25
                    if "?" in txt:
                        p += 0.12
                    if p > best_score:
                        best_score = p
                        best_t = float(seg.get("end", seg.get("start", 0.0)))

                if best_score >= 0.45 and best_t is not None:
                    return best_t
                # fallback: trim to prev.end_time (no strong punch localization)
                return prev.end_time
            except Exception:
                return None

        exhaustion_end = idea_exhaustion(prev, n)

        # Merge policy (rollback): merge dense micro-nodes into bounded windows.
        # This avoids collapsing everything into one node while keeping nodes large enough to qualify.
        prev_dur = max(0.01, float(prev.end_time - prev.start_time))
        curr_dur = max(0.01, float(n.end_time - n.start_time))
        local_time_tol = float(adaptive_time_tol)
        if gap >= 0.0:
            local_time_tol = min(local_time_tol, max(0.08, min(0.25, 0.45 * min(prev_dur, curr_dur))))
        local_sem_thr = float(sem_sim_threshold) + (0.07 if gap <= 0.08 else 0.0)
        local_sem_thr = min(0.95, local_sem_thr)
        overlap_hit = (gap < 0.0)
        close_hit = (gap <= local_time_tol)
        sem_hit = (sem_sim >= local_sem_thr)
        exhaust_hit = (exhaustion_end is not None)
        merged_len = float(max(prev.end_time, n.end_time) - min(prev.start_time, n.start_time))
        within_cap = (not cap_enabled) or (merged_len <= max_node_secs)
        merge_hit = overlap_hit or exhaust_hit or (close_hit and sem_hit and within_cap)
        if merge_hit:
            merge_stats["total"] += 1
            if overlap_hit:
                merge_stats["overlap"] += 1
            if close_hit:
                merge_stats["close"] += 1
            if sem_hit:
                merge_stats["sem"] += 1
            if close_hit and sem_hit:
                merge_stats["close_and_sem"] += 1
            if exhaust_hit:
                merge_stats["exhaust"] += 1
            # merge by creating new IdeaNode (or trim prev if exhausted)
            start_idx = min(prev.start_idx, n.start_idx)
            end_idx = max(prev.end_idx, n.end_idx)
            start_time = min(prev.start_time, n.start_time)
            end_time = max(prev.end_time, n.end_time)
            combined_text = (prev.text + " " + n.text).strip()
            # choose higher semantic_quality/punch
            semantic_quality = max(prev.semantic_quality, n.semantic_quality)
            punch = max(prev.punch_confidence, n.punch_confidence)
            curiosity = max(prev.curiosity_score, n.curiosity_score)
            # metrics: average where possible
            metrics = {}
            for k in set(prev.metrics.keys()) | set(n.metrics.keys()):
                a = prev.metrics.get(k, 0.0)
                b = n.metrics.get(k, 0.0)
                metrics[k] = round((a + b) / 2.0, 4)
            # choose state: RESOLUTION > TENSION > DEVELOPMENT > OPEN
            state_priority = {RESOLUTION: 3, TENSION: 2, DEVELOPMENT: 1, OPEN: 0}
            state = prev.state if state_priority.get(prev.state,0) >= state_priority.get(n.state,0) else n.state

            if exhaustion_end is not None:
                # Trim prev to exhaustion_end and discard tail node n as a separate node
                # keep at least one segment
                new_segs = [s for s in prev.segments if float(s.get("start", 0.0)) < exhaustion_end]
                if not new_segs:
                    new_segs = prev.segments
                new_txt = " ".join(s.get("text","") for s in new_segs).strip()
                # recompute some metrics conservatively
                wc = len(tokens(new_txt))
                new_sem = min(1.0, 0.25 + (min(1.0, wc/40.0) * 0.4) + detect_curiosity_score(new_txt)*0.25 + detect_contrast_strength(new_txt)*0.1)
                new_punch = 0.0
                if detect_conclusion_marker(new_txt):
                    new_punch += 0.65
                new_punch += detect_contrast_strength(new_txt) * 0.25
                if "?" in new_txt:
                    new_punch += 0.12
                new_punch = min(1.0, new_punch)
                new_curio = detect_curiosity_score(new_txt)
                # derive new end_idx relative to prev.start_idx
                new_end_idx = prev.start_idx + max(0, len(new_segs) - 1)
                merged[-1] = IdeaNode(
                    start_idx=prev.start_idx, end_idx=new_end_idx, start_time=prev.start_time, end_time=float(min(exhaustion_end, prev.end_time)),
                    segments=new_segs, text=normalize_text(new_txt), state=state,
                    curiosity_score=round(new_curio,3), punch_confidence=round(new_punch,3),
                    semantic_quality=round(new_sem,3), fingerprint=fingerprint_text(new_txt[:2000]), metrics=metrics
                )
            else:
                merged[-1] = IdeaNode(
                    start_idx=start_idx, end_idx=end_idx, start_time=start_time, end_time=end_time,
                    segments=prev.segments + n.segments, text=normalize_text(combined_text),
                    state=state, curiosity_score=round(curiosity,3), punch_confidence=round(punch,3),
                    semantic_quality=round(semantic_quality,3), fingerprint=fingerprint_text(combined_text[:2000]),
                    metrics=metrics
                )
        else:
            # suppression: avoid chained resolution nodes that add no curiosity
            if merged and merged[-1].state == RESOLUTION and n.state == RESOLUTION and n.curiosity_score < RESOLUTION_SUPPRESS_CUTOFF:
                # skip adding this low-value resolution node
                continue
            merged.append(n)

    # When everything collapses, report which merge triggers dominated.
    try:
        if len(nodes) > 1 and len(merged) == 1:
            gap_min = min(gap_samples) if gap_samples else 0.0
            gap_max = max(gap_samples) if gap_samples else 0.0
            sem_min = min(sem_samples) if sem_samples else 0.0
            sem_max = max(sem_samples) if sem_samples else 0.0
            log.warning(
                "[COALESCE] collapse in=%d out=%d merges=%d overlap_hit=%d close_hit=%d sem_hit=%d close_and_sem=%d exhaust_hit=%d time_tol=%.2f sem_thr=%.2f gap_min=%.3f gap_max=%.3f sem_min=%.3f sem_max=%.3f",
                len(nodes),
                len(merged),
                merge_stats["total"],
                merge_stats["overlap"],
                merge_stats["close"],
                merge_stats["sem"],
                merge_stats["close_and_sem"],
                merge_stats["exhaust"],
                float(adaptive_time_tol),
                float(sem_sim_threshold),
                float(gap_min),
                float(gap_max),
                float(sem_min),
                float(sem_max),
            )
    except Exception:
        pass

    if not cap_enabled:
        return merged
    return _force_split_overlong_nodes(merged, max_node_secs=max_node_secs)

# ----------------------------------------
# Candidate selector: pick clip-worthy nodes
# ----------------------------------------
def _select_candidate_clips_v2(
    nodes: List[IdeaNode],
    top_k: int = 12,
    transcript: Optional[List[Dict]] = None,
    ensure_sentence_complete: bool = False,
    allow_multi_angle: bool = False,
    min_target: int = 0,
    diversity_mode: str = "balanced",
    max_overlap_ratio: float = 0.35,
    curio_cutoff: Optional[float] = None,
    punch_cutoff: Optional[float] = None,
) -> List[Dict[str, Any]]:
    if not nodes:
        return []

    diversity_mode = str(diversity_mode or "balanced").strip().lower()
    min_target = max(0, int(min_target or 0))
    max_overlap_ratio = min(0.95, max(0.05, float(max_overlap_ratio or 0.35)))

    relax_curio_delta = float(SELECT_RELAX_CURIO_DELTA_DEFAULT)
    relax_punch_delta = float(SELECT_RELAX_PUNCH_DELTA_DEFAULT)
    relax_sem_floor = float(SELECT_RELAX_SEM_FLOOR_DEFAULT)
    relax_dynamic_enable = bool(SELECT_RELAX_DYNAMIC_ENABLE_DEFAULT)
    relax_max_candidates = max(1, int(SELECT_RELAX_MAX_CANDIDATES_DEFAULT or 1))
    selected_curio_cutoff = float(CURIO_SELECT_CUTOFF if curio_cutoff is None else max(0.0, min(1.0, curio_cutoff)))
    selected_punch_cutoff = float(PUNCH_SELECT_CUTOFF if punch_cutoff is None else max(0.0, min(1.0, punch_cutoff)))
    strict_min_target = max(min_target, int(SELECT_STRICT_MIN_TARGET_DEFAULT or 0))
    transcript_items = list(transcript or [])
    transcript_duration = 0.0
    if transcript_items:
        try:
            transcript_duration = max(0.0, float(transcript_items[-1].get("end", transcript_items[-1].get("start", 0.0)) or 0.0) - float(transcript_items[0].get("start", 0.0) or 0.0))
        except Exception:
            transcript_duration = 0.0
    total_words = 0
    for item in transcript_items:
        try:
            total_words += len(str(item.get("text", "") or "").split())
        except Exception:
            pass
    words_per_second = (float(total_words) / transcript_duration) if transcript_duration > 0.5 else 0.0
    transcript_density = min(2.0, max(0.0, words_per_second / 2.8))
    node_density = min(2.0, float(len(nodes)) / float(max(1, top_k * 2)))
    avg_motion = 0.0
    avg_audio = 0.0
    avg_semantic = 0.0
    if nodes:
        avg_motion = sum(float((dict(n.metrics or {}) if isinstance(n.metrics, dict) else {}).get("motion_mean", 0.0) or 0.0) for n in nodes) / float(len(nodes))
        avg_audio = sum(float((dict(n.metrics or {}) if isinstance(n.metrics, dict) else {}).get("audio_mean", 0.0) or 0.0) for n in nodes) / float(len(nodes))
        avg_semantic = sum(float(getattr(n, "semantic_quality", 0.0) or 0.0) for n in nodes) / float(len(nodes))
    content_hint = "balanced"
    if transcript_density < 0.45 and avg_motion > 0.18 and avg_semantic < 0.55:
        content_hint = "visual_sparse"
    elif transcript_density > 1.15 and node_density > 1.0:
        content_hint = "dense_talk"

    if relax_dynamic_enable:
        dynamic_relax = min(0.08, 0.03 * max(0.0, node_density - 1.0)) + min(0.06, 0.04 * max(0.0, 0.80 - transcript_density))
        if content_hint == "dense_talk":
            dynamic_relax += 0.02
        relax_curio_delta = min(0.30, max(relax_curio_delta, relax_curio_delta + dynamic_relax))
        relax_punch_delta = min(0.30, max(relax_punch_delta, relax_punch_delta + (dynamic_relax * 0.85)))
        if content_hint == "visual_sparse":
            relax_sem_floor = min(0.80, max(relax_sem_floor, SELECT_BASE_SEM_FLOOR + 0.02))
        elif content_hint == "dense_talk":
            relax_sem_floor = max(0.20, relax_sem_floor - 0.03)

    log.info(
        "[DIVERSITY-CONFIG] selector mode=%s min_target=%d strict_floor=%d allow_multi_angle=%s max_overlap=%.2f relax(curio=%.2f,punch=%.2f,sem_floor=%.2f) pass_w(strict=%.2f,relaxed=%.2f) density=%.2f nodes=%.2f hint=%s",
        diversity_mode,
        min_target,
        strict_min_target,
        allow_multi_angle,
        max_overlap_ratio,
        relax_curio_delta,
        relax_punch_delta,
        relax_sem_floor,
        float(SELECT_STRICT_PASS_WEIGHT),
        float(SELECT_RELAX_PASS_WEIGHT),
        transcript_density,
        node_density,
        content_hint,
    )

    def _build_candidates(curio_cutoff: float, punch_cutoff: float, sem_floor: float, pass_name: str) -> List[Dict[str, Any]]:
        pass_candidates = []
        seen_fp_local = set()
        for n in nodes:
            qualifies = False
            if n.state == RESOLUTION and n.curiosity_score < RESOLUTION_SUPPRESS_CUTOFF:
                continue
            if n.state == RESOLUTION and n.semantic_quality >= 0.30:
                qualifies = True
            elif (n.curiosity_score >= curio_cutoff and n.punch_confidence >= punch_cutoff) or n.semantic_quality >= sem_floor:
                qualifies = True

            if not qualifies:
                log.debug(
                    "[SELECT] skipped node %.1f-%.1f state=%s curio=%.2f punch=%.2f sem=%.2f pass=%s",
                    n.start_time,
                    n.end_time,
                    n.state,
                    n.curiosity_score,
                    n.punch_confidence,
                    n.semantic_quality,
                    pass_name,
                )
                continue

            if not allow_multi_angle and n.fingerprint in seen_fp_local:
                log.debug("[SELECT] skipped node %.1f-%.1f duplicate fingerprint", n.start_time, n.end_time)
                continue
            seen_fp_local.add(n.fingerprint)

            metrics = dict(n.metrics or {}) if isinstance(n.metrics, dict) else {}
            audio = float(metrics.get("audio_mean", 0.0) or 0.0)
            motion = float(metrics.get("motion_mean", 0.0) or 0.0)
            energy = math.sqrt(max(0.0, audio * motion)) if (audio and motion) else (audio or motion)
            curiosity_peak = float(metrics.get("curiosity_peak", 0.0) or 0.0)
            curiosity_start = float(metrics.get("curiosity_at_start", 0.0) or 0.0)
            narrative_trigger_weight = float(metrics.get("narrative_trigger_weight", 0.0) or 0.0)

            score = (0.40 * n.semantic_quality) + (0.26 * n.punch_confidence) + (0.16 * n.curiosity_score) + (0.08 * energy)
            score += (0.12 * curiosity_peak) + (0.06 * curiosity_start)
            score += (0.10 * narrative_trigger_weight)
            pass_weight = SELECT_STRICT_PASS_WEIGHT if pass_name == "strict" else SELECT_RELAX_PASS_WEIGHT
            score *= float(pass_weight)
            score = round(min(1.0, score), 4)

            if n.state == RESOLUTION and n.curiosity_score >= curio_cutoff:
                label = "Revealing Truth"
            elif n.punch_confidence >= 0.6:
                label = "Insight / Punch"
            elif n.curiosity_score >= (curio_cutoff + 0.12):
                label = "Curiosity Hook"
            elif n.semantic_quality >= 0.6:
                label = "Story / Explanation"
            else:
                label = "Context Builder"

            reason_pieces = []
            if n.curiosity_score > (curio_cutoff - 0.05):
                reason_pieces.append("curiosity")
            if n.punch_confidence > (punch_cutoff - 0.10):
                reason_pieces.append("punch")
            if n.semantic_quality > 0.4:
                reason_pieces.append("semantic")

            sentiment_score = 0.0
            try:
                sentiment_score = metrics.get("sentiment", metrics.get("sentiment_compound", metrics.get("emotion", 0.0)))
            except Exception:
                sentiment_score = 0.0
            audio_flatness = 0.0
            try:
                audio_flatness = metrics.get("audio_flatness", metrics.get("spectral_flatness", 0.0))
            except Exception:
                audio_flatness = 0.0

            try:
                is_sarcastic, sarcasm_score = detect_sarcasm(n.text or "", sentiment_score, audio_flatness)
            except Exception:
                is_sarcastic, sarcasm_score = (False, 0.0)

            if ("yeah right" in (n.text or "").lower()) or ("as if" in (n.text or "").lower()):
                is_sarcastic = True
                sarcasm_score = max(float(sarcasm_score or 0.0), 0.72)

            if is_sarcastic:
                sarcasm_penalty = 0.45 if pass_name == "relaxed" else 0.55
                score = round(score * sarcasm_penalty, 4)
                reason_pieces.append("sarcasm")
                try:
                    metrics["sarcasm"] = sarcasm_score
                except Exception:
                    pass

            content_shape_penalty = 0.0
            transcript_conf = float(metrics.get("transcript_confidence", metrics.get("confidence", 1.0)) or 1.0)
            if content_hint == "visual_sparse" and transcript_conf < 0.55 and n.semantic_quality < 0.62:
                content_shape_penalty = 0.10
            elif transcript_density < 0.35 and n.curiosity_score < 0.30 and n.punch_confidence < 0.32:
                content_shape_penalty = 0.06
            if content_shape_penalty > 0.0:
                score = round(max(0.0, score - content_shape_penalty), 4)
                reason_pieces.append("content_shape")

            payoff_hint = max(
                float(metrics.get("payoff_confidence", 0.0) or 0.0),
                float(metrics.get("completion_score", 0.0) or 0.0),
                float(metrics.get("ending_strength", 0.0) or 0.0),
            )
            relaxed_readiness = round(
                min(
                    1.0,
                    (0.34 * float(n.semantic_quality))
                    + (0.22 * float(n.punch_confidence))
                    + (0.14 * float(n.curiosity_score))
                    + (0.10 * float(curiosity_peak))
                    + (0.12 * float(payoff_hint))
                    + (0.08 * (1.0 - min(1.0, float(sarcasm_score or 0.0)))),
                ),
                4,
            )
            reason = " | ".join(reason_pieces) or "balanced"
            cand = {
                "text": n.text,
                "start": n.start_time,
                "end": n.end_time,
                "score": score,
                "label": label,
                "reason": reason,
                "curiosity": n.curiosity_score,
                "punch_confidence": n.punch_confidence,
                "semantic_quality": n.semantic_quality,
                "fingerprint": n.fingerprint,
                "metrics": metrics,
                "select_pass": pass_name,
                "sarcasm_score": round(float(sarcasm_score or 0.0), 4),
                "content_hint": content_hint,
                "content_shape_penalty": round(float(content_shape_penalty), 4),
                "relaxed_readiness": relaxed_readiness,
                "payoff_hint": round(float(payoff_hint), 4),
            }

            pass_candidates.append(cand)
        return pass_candidates

    strict_candidates = _build_candidates(
        curio_cutoff=selected_curio_cutoff,
        punch_cutoff=selected_punch_cutoff,
        sem_floor=float(SELECT_BASE_SEM_FLOOR),
        pass_name="strict",
    )

    relaxed_candidates = []
    second_pass_target = max(min_target, strict_min_target)
    if second_pass_target > 0 and len(strict_candidates) < second_pass_target and diversity_mode in ("balanced", "maximum", "max", "diverse"):
        relaxed_candidates = _build_candidates(
            curio_cutoff=max(0.0, selected_curio_cutoff - relax_curio_delta),
            punch_cutoff=max(0.0, selected_punch_cutoff - relax_punch_delta),
            sem_floor=max(float(relax_sem_floor), float(SELECT_BASE_SEM_FLOOR) - 0.07),
            pass_name="relaxed",
        )
        relaxed_floor = max(0.22, min(0.72, (selected_curio_cutoff + selected_punch_cutoff) * 0.35))
        clustered_relaxed: List[Dict[str, Any]] = []
        relaxed_by_cluster: Dict[int, int] = {}
        for cand in sorted(relaxed_candidates, key=lambda x: (float(x.get("relaxed_readiness", x.get("score", 0.0)) or 0.0), float(x.get("score", 0.0) or 0.0)), reverse=True):
            if float(cand.get("relaxed_readiness", cand.get("score", 0.0)) or 0.0) < relaxed_floor:
                continue
            cluster_key = int(float(cand.get("start", 0.0) or 0.0) // 12.0)
            if relaxed_by_cluster.get(cluster_key, 0) >= 1:
                continue
            clustered_relaxed.append(cand)
            relaxed_by_cluster[cluster_key] = relaxed_by_cluster.get(cluster_key, 0) + 1
            if len(clustered_relaxed) >= relax_max_candidates:
                break
        relaxed_candidates = clustered_relaxed
        log.info(
            "[DIVERSITY] selector second_pass strict=%d relaxed=%d min_target=%d floor=%.2f cap=%d",
            len(strict_candidates),
            len(relaxed_candidates),
            second_pass_target,
            relaxed_floor,
            relax_max_candidates,
        )

    candidates_by_fp = {}
    pass_priority = {"strict": 2, "relaxed": 1}
    for c in strict_candidates + relaxed_candidates:
        fp = c.get("fingerprint") or fingerprint_text((c.get("text", "") or "")[:2000])
        prev = candidates_by_fp.get(fp)
        if prev is None:
            candidates_by_fp[fp] = c
            continue
        prev_rank = pass_priority.get(prev.get("select_pass", ""), 0)
        cur_rank = pass_priority.get(c.get("select_pass", ""), 0)
        if (c.get("score", 0.0), cur_rank) > (prev.get("score", 0.0), prev_rank):
            candidates_by_fp[fp] = c

    candidates = list(candidates_by_fp.values())
    log.info(
        "[SELECT] raw_candidates=%d strict=%d relaxed=%d (from %d nodes)",
        len(candidates),
        len(strict_candidates),
        len(relaxed_candidates),
        len(nodes),
    )
    if len(candidates) < 2:
        log.warning("[INVARIANT] raw_candidates=%d (from %d nodes) < 2", len(candidates), len(nodes))

    def _overlap_ratio(a_s: float, a_e: float, b_s: float, b_e: float) -> float:
        inter = max(0.0, min(a_e, b_e) - max(a_s, b_s))
        if inter <= 0.0:
            return 0.0
        shorter = max(1e-6, min((a_e - a_s), (b_e - b_s)))
        return float(inter / shorter)

    candidates.sort(key=lambda x: x["score"], reverse=True)
    final = []
    used_ranges = []
    for c in candidates:
        s = float(c["start"])
        e = float(c["end"])
        drop = False
        for (us, ue, existing_label) in used_ranges:
            ranges_overlap = not (e <= us or s >= ue)
            if not ranges_overlap:
                continue

            ratio = _overlap_ratio(s, e, us, ue)
            if not allow_multi_angle:
                drop = True
                break

            same_label = (c.get("label") == existing_label)
            if same_label and ratio > max_overlap_ratio:
                log.info(
                    "[DIVERSITY] overlap_drop %.1f-%.1f with %.1f-%.1f ratio=%.2f label=%s",
                    s, e, us, ue, ratio, c.get("label"),
                )
                drop = True
                break
            if (not same_label) and ratio > max_overlap_ratio:
                log.info(
                    "[DIVERSITY] overlap_drop %.1f-%.1f with %.1f-%.1f ratio=%.2f labels=%s/%s",
                    s, e, us, ue, ratio, c.get("label"), existing_label,
                )
                drop = True
                break
            if (not same_label) and ratio <= max_overlap_ratio:
                log.debug(
                    "[DIVERSITY] overlap_keep %.1f-%.1f with %.1f-%.1f ratio=%.2f labels=%s/%s",
                    s, e, us, ue, ratio, c.get("label"), existing_label,
                )

        if drop:
            continue

        final.append(c)
        used_ranges.append((s, e, c.get("label")))
        if len(final) >= top_k:
            break

    if ensure_sentence_complete and transcript_items:
        for cand in final:
            try:
                cand["end"] = float(sentence_complete_extend(cand["start"], cand["end"], transcript_items))
            except Exception:
                pass

    log.info("[SELECT] final_candidates=%d (top_k=%d)", len(final), top_k)
    if len(nodes) >= 3 and len(final) < 2:
        log.warning(
            "[INVARIANT] idea_nodes=%d raw_candidates=%d final=%d allow_multi_angle=%s curio_cutoff=%.2f punch_cutoff=%.2f",
            len(nodes),
            len(candidates),
            len(final),
            allow_multi_angle,
            selected_curio_cutoff,
            selected_punch_cutoff,
        )

    return final


def select_candidate_clips(
    nodes: List[IdeaNode],
    top_k: int = 12,
    transcript: Optional[List[Dict]] = None,
    ensure_sentence_complete: bool = False,
    allow_multi_angle: bool = False,
    min_target: int = 0,
    diversity_mode: str = "balanced",
    max_overlap_ratio: float = 0.35,
    curio_cutoff: Optional[float] = None,
    punch_cutoff: Optional[float] = None,
) -> List[Dict[str,Any]]:

    """
    Convert IdeaNodes into candidate clip dicts with scoring and pick top_k.
    Each candidate dict contains start,end,text,score,labels,reason...
    """
    return _select_candidate_clips_v2(
        nodes=nodes,
        top_k=top_k,
        transcript=transcript,
        ensure_sentence_complete=ensure_sentence_complete,
        allow_multi_angle=allow_multi_angle,
        min_target=min_target,
        diversity_mode=diversity_mode,
        max_overlap_ratio=max_overlap_ratio,
        curio_cutoff=curio_cutoff,
        punch_cutoff=punch_cutoff,
    )

    """
    candidates = []
    seen_fp = set()

    for n in nodes:
        # filter: require resolution OR high curiosity+punch OR high semantic quality
        qualifies = False
        # Suppress weak resolution nodes early (policy)
        if n.state == RESOLUTION and n.curiosity_score < RESOLUTION_SUPPRESS_CUTOFF:
            continue
        if n.state == RESOLUTION and n.semantic_quality >= 0.30:
            qualifies = True
        elif (n.curiosity_score >= CURIO_SELECT_CUTOFF and n.punch_confidence >= PUNCH_SELECT_CUTOFF) or n.semantic_quality >= 0.52:
            qualifies = True

        if not qualifies:
            log.debug("[SELECT] skipped node %.1f-%.1f state=%s curio=%.2f punch=%.2f sem=%.2f (failed qualifies)", n.start_time, n.end_time, n.state, n.curiosity_score, n.punch_confidence, n.semantic_quality)
            continue

        # uniqueness guard
        if not allow_multi_angle:
           if n.fingerprint in seen_fp:
             log.debug("[SELECT] skipped node %.1f-%.1f duplicate fingerprint", n.start_time, n.end_time)
             continue
        seen_fp.add(n.fingerprint)

        # scoring: combine semantic_quality, punch, curiosity, audio/motion
        audio = n.metrics.get("audio_mean", 0.0)
        motion = n.metrics.get("motion_mean", 0.0)
        energy = math.sqrt(max(0.0, audio * motion)) if (audio and motion) else (audio or motion)
        # include optional curiosity meta if present (from analyze_curiosity_and_detect_punches)
        curiosity_peak = float(n.metrics.get("curiosity_peak", 0.0))
        curiosity_start = float(n.metrics.get("curiosity_at_start", 0.0))

        score = (0.40 * n.semantic_quality) + (0.26 * n.punch_confidence) + (0.16 * n.curiosity_score) + (0.08 * energy)
        # extra boost from explicit curiosity meta
        score += (0.12 * curiosity_peak) + (0.06 * curiosity_start)
        score = round(min(1.0, score), 4)

        # label: simple mapping
        if n.state == RESOLUTION and n.curiosity_score >= CURIO_SELECT_CUTOFF:
            label = "Revealing Truth"
        elif n.punch_confidence >= 0.6:
            label = "Insight / Punch"
        elif n.curiosity_score >= (CURIO_SELECT_CUTOFF + 0.12):
            label = "Curiosity Hook"
        elif n.semantic_quality >= 0.6:
            label = "Story / Explanation"
        else:
            label = "Context Builder"

        reason_pieces = []
        if n.curiosity_score > (CURIO_SELECT_CUTOFF - 0.05):
            reason_pieces.append("curiosity")
        if n.punch_confidence > (PUNCH_SELECT_CUTOFF - 0.10):
            reason_pieces.append("punch")
        if n.semantic_quality > 0.4:
            reason_pieces.append("semantic")
        reason = " · ".join(reason_pieces) or "balanced"
        # --- sarcasm detection: lexical + negation + prosody ---
        try:
            sentiment_score = n.metrics.get("sentiment", n.metrics.get("sentiment_compound", n.metrics.get("emotion", 0.0))) if isinstance(n.metrics, dict) else 0.0
        except Exception:
            sentiment_score = 0.0
        audio_flatness = 0.0
        try:
            audio_flatness = n.metrics.get("audio_flatness", n.metrics.get("spectral_flatness", 0.0)) if isinstance(n.metrics, dict) else 0.0
        except Exception:
            audio_flatness = 0.0

        try:
            is_sarcastic, sarcasm_score = detect_sarcasm(n.text or "", sentiment_score, audio_flatness)
        except Exception:
            is_sarcastic, sarcasm_score = (False, 0.0)

        if is_sarcastic:
            score = round(score * 0.55, 4)
            reason_pieces.append("Sarcastic contradiction detected")
            # persist small sarcasm score in metrics for downstream explainability
            try:
                if isinstance(n.metrics, dict):
                    n.metrics["sarcasm"] = sarcasm_score
            except Exception:
                pass

        reason = " · ".join(reason_pieces) or "balanced"

        cand = {
            "text": n.text,
            "start": n.start_time,
            "end": n.end_time,
            "score": score,
            "label": label,
            "reason": reason,
            "curiosity": n.curiosity_score,
            "punch_confidence": n.punch_confidence,
            "semantic_quality": n.semantic_quality,
            "fingerprint": n.fingerprint,
            "metrics": n.metrics
        }

        # optionally extend to sentence-complete endings when requested
        if ensure_sentence_complete and transcript:
            try:
                new_end = sentence_complete_extend(cand["start"], cand["end"], transcript)
                cand["end"] = float(new_end)
            except Exception:
                pass

        candidates.append(cand)

    log.info("[SELECT] raw_candidates=%d (from %d nodes)", len(candidates), len(nodes))
    if len(candidates) < 2:
        log.warning("[INVARIANT] raw_candidates=%d (from %d nodes) < 2", len(candidates), len(nodes))
    for c in candidates:
        log.debug("[SELECT] raw window %.1f-%.1f score=%.3f label=%s curio=%.2f punch=%.2f sem=%.2f", c["start"], c["end"], c["score"], c["label"], c["curiosity"], c["punch_confidence"], c["semantic_quality"])

    # sort and return top_k, also strict dedupe by time range
    candidates.sort(key=lambda x: x["score"], reverse=True)
    final = []
    used_ranges = []
    for c in candidates:
        s = c["start"]; e = c["end"]
        overlap = False
        for (us, ue, existing_label) in used_ranges:
            ranges_overlap = not (e <= us or s >= ue)
            if ranges_overlap and (not allow_multi_angle) and (c["label"] == existing_label):
                overlap = True
                log.debug("[SELECT] drop %.1f-%.1f score=%.3f due to overlap with %.1f-%.1f label=%s", s, e, c["score"], us, ue, existing_label)
                break
        if overlap:
            continue
        final.append(c)
        used_ranges.append((s,e,c["label"]))
        if len(final) >= top_k:
            break

    log.info("[SELECT] final_candidates=%d (top_k=%d)", len(final), top_k)
    if len(nodes) >= 3 and len(final) < 2:
        log.warning("[INVARIANT] idea_nodes=%d raw_candidates=%d final=%d allow_multi_angle=%s curio_cutoff=%.2f punch_cutoff=%.2f", len(nodes), len(candidates), len(final), allow_multi_angle, CURIO_SELECT_CUTOFF, PUNCH_SELECT_CUTOFF)

    return final
    """


def debug_print_lens(candidates: List[Dict[str, Any]], transcript: Optional[List[Dict]] = None, top_n: int = 12):
    """
    Print a compact debug lens for top candidates.
    For each candidate: start, end, curiosity_peak, first 1-2 transcript lines, last 1-2 transcript lines, label.
    """
    if not candidates:
        print("[DEBUG LENS] No candidates to show")
        return

    def get_label(cand_text: str, cand: Dict[str, Any]) -> str:
        # prefer existing label/stage fields
        if cand.get("label"):
            return cand.get("label")
        if cand.get("stage"):
            return cand.get("stage")
        # heuristics
        if detect_conclusion_marker(cand_text):
            return "Resolution/Punch"
        if "?" in (cand_text or "") or detect_curiosity_score(cand_text) > 0.18:
            return "Setup/Tension"
        return "Development"

    print("[DEBUG LENS] Top {} candidates:".format(min(top_n, len(candidates))))
    for i, c in enumerate(sorted(candidates, key=lambda x: x.get("score", 0.0), reverse=True)[:top_n]):
        s = float(c.get("start", 0.0))
        e = float(c.get("end", 0.0))
        # curiosity peak: try metrics then fallback
        curiosity_peak = None
        if isinstance(c.get("metrics"), dict):
            curiosity_peak = c["metrics"].get("curiosity_peak") if c["metrics"].get("curiosity_peak") is not None else None
        if curiosity_peak is None:
            curiosity_peak = c.get("curiosity") or c.get("hook") or c.get("score")

        # get transcript snippets overlapping
        first_lines = []
        last_lines = []
        if transcript:
            segs = [seg for seg in transcript if seg.get("end", 0.0) > s and seg.get("start", 0.0) < e]
            if segs:
                first_lines = [ (seg.get("text","") or "").strip() for seg in segs[:2] ]
                last_lines = [ (seg.get("text","") or "").strip() for seg in segs[-2:] ]

        label = get_label(c.get("text", ""), c)

        print(f"[{i+1}] {s:.2f}-{e:.2f}  curiosity_peak={float(curiosity_peak or 0.0):.3f}  label={label}  score={c.get('score',0.0):.3f}")
        if first_lines:
            print("    first:", " | ".join(first_lines))
        if last_lines:
            print("    last:", " | ".join(last_lines))
        # small separator
        print("    ---")


def plot_curiosity_curve(curiosity, feats=None, out_path=None):
    """
    Plot curiosity vs time if matplotlib is available; otherwise write CSV to out_path.
    curiosity: array-like per-segment
    feats: optional list of per-seg dicts (for time mapping)
    out_path: optional path to save (PNG or CSV)
    """
    try:
        import matplotlib.pyplot as plt
    except Exception:
        plt = None

    times = None
    if feats:
        times = [f.get("start", 0.0) for f in feats]
    else:
        times = list(range(len(curiosity)))

    if plt:
        plt.figure(figsize=(8, 3))
        plt.plot(times, curiosity, '-o')
        plt.xlabel('time (s)')
        plt.ylabel('curiosity')
        plt.ylim(0, 1.0)
        plt.grid(alpha=0.3)
        if out_path and out_path.lower().endswith('.png'):
            plt.title('Curiosity Curve')
            plt.tight_layout()
            plt.savefig(out_path)
            print(f"[plot_curiosity_curve] saved to {out_path}")
        else:
            plt.show()
        plt.close()
    else:
        # fallback: write CSV
        if out_path:
            try:
                import csv
                with open(out_path, 'w', newline='', encoding='utf-8') as fh:
                    w = csv.writer(fh)
                    w.writerow(['time','curiosity'])
                    for t, c in zip(times, curiosity):
                        w.writerow([t, c])
                print(f"[plot_curiosity_curve] wrote CSV to {out_path}")
            except Exception as e:
                print("[plot_curiosity_curve] failed to write CSV:", e)
        else:
            # print to stdout
            print("time,curiosity")
            for t, c in zip(times, curiosity):
                print(f"{t},{c}")

# ----------------------------------------
# Example usage (quick test)
# ----------------------------------------
if __name__ == "__main__":
    # quick fake transcript
    segs = [
        {"start":0,"end":6,"text":"Most people think saving money is hard. But actually there's a simple trick."},
        {"start":6,"end":12,"text":"Here's the thing: automate a small transfer each week."},
        {"start":12,"end":18,"text":"I used to waste my paycheck but now I have a habit."},
        {"start":18,"end":26,"text":"So remember: small automatic rules beat big willpower."},
        {"start":26,"end":32,"text":"By the way, did you know compound interest doubles?"},
        {"start":32,"end":38,"text":"How to start: open two accounts and schedule transfers."},
    ]

    nodes = build_idea_graph(segs)
    print("IDEA NODES:")
    for n in nodes:
        print(f" [{n.start_time:.1f}-{n.end_time:.1f}] state={n.state} curiosity={n.curiosity_score} punch={n.punch_confidence} quality={n.semantic_quality}")
        print("  text:", n.text[:120])
    candidates = select_candidate_clips(nodes, top_k=6)
    print("\nCANDIDATES:")
    for c in candidates:
        print(f"  {c['label']} {c['score']} {c['start']:.1f}-{c['end']:.1f} reason={c['reason']}")
