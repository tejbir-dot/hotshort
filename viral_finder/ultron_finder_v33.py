import numpy as np
import re
import os
# from viral_finder.transcript_engine import transcribe_file
from viral_finder.visual_audio_engine import analyze_audio, analyze_visual
from viral_finder.ultron_brain import load_ultron_brain, ultron_brain_score, ultron_learn
from viral_finder.visual_audio_engine import analyze_visual
from viral_finder.idea_graph import build_idea_graph, select_candidate_clips, sentence_complete_extend, analyze_curiosity_and_detect_punches
from viral_finder.gemini_transcript_engine import extract_transcript
# semantic intelligence helpers
from utils.narrative_intelligence import (
    detect_message_punch,
    detect_thought_completion,
    extend_until_sentence_complete,
    estimate_semantic_quality,
    narrative_fingerprint
)

def fuse(hook: float, audio: float, motion: float) -> float:
    """
    🌌 Ultron V33-X Cosmic Fusion
    - hook   → ignition (curiosity spark)
    - audio  → emotional pressure
    - motion → visual stimulation
    
    Intelligence upgrades:
    - non-linear hook damping (prevents premature endings)
    - rewards sustained energy, not spikes
    - creates space for narrative continuation
    """

    # Clamp inputs
    hook = max(0.0, min(hook, 1.0))
    audio = max(0.0, min(audio, 1.0))
    motion = max(0.0, min(motion, 1.0))

    # --- 1. Non-linear hook control ---
    # Strong hooks ignite, but should not dominate forever
    hook_energy = hook ** 0.75   # soften sharp spikes

    # --- 2. Sustained energy field ---
    # If audio & motion both present → narrative is alive
    sustain = (audio * motion) ** 0.5

    # --- 3. Emotional pressure ---
    # Audio carries more meaning than motion
    emotional_drive = (audio ** 0.6)

    # --- 4. Visual assist ---
    visual_drive = motion ** 0.85

    # --- 5. Cosmic fusion ---
    score = (
        (hook_energy * 0.42) +        # ignition
        (emotional_drive * 0.28) +    # feeling
        (visual_drive * 0.15) +       # stimulation
        (sustain * 0.15)              # continuity
    )

    return round(score, 4)

import numpy as np
import math
from typing import List, Tuple

# --------------------
# Helper utilities (local, safe)
# --------------------
def _token_set(text: str):
    toks = [t.strip(".,!?;:\"'()[]").lower() for t in text.split()]
    return set([t for t in toks if t])

def text_overlap(a: str, b: str) -> float:
    """
    Lightweight semantic similarity based on token / bigram overlap.
    Returns value in [0,1].
    Robust fallback if texts are short.
    """
    if not a or not b:
        return 0.0
    A = _token_set(a)
    B = _token_set(b)
    if not A or not B:
        return 0.0
    jacc = len(A & B) / len(A | B)
    # bigram boost to capture order similarity
    def bigrams(s):
        w = [t for t in s.split() if t]
        return set(zip(w, w[1:])) if len(w) > 1 else set()
    bigA = bigrams(a)
    bigB = bigrams(b)
    big_boost = (len(bigA & bigB) / (len(bigA | bigB) + 1e-9)) if (bigA or bigB) else 0.0
    # geometric blend favors both token and phrase similarity
    return float((0.6 * jacc) + (0.4 * big_boost))

def dedupe_by_time(candidates: List[dict], time_tol: float = 0.5) -> List[dict]:
    """
    Remove near-duplicate candidates based on start/end times.
    Keeps highest-score among collisions.
    """
    if not candidates:
        return []
    # bucket by rounded start/end
    buckets = {}
    for c in candidates:
        key = (round(c["start"] / time_tol), round(c["end"] / time_tol))
        if key not in buckets or c["score"] > buckets[key]["score"]:
            buckets[key] = c
    uniq = list(buckets.values())
    # sort by start
    uniq.sort(key=lambda x: x["start"])
    return uniq

def extend_to_closure(trs, start_idx, end_idx, max_extend_seconds=8.0):
    """
    Try to extend an arc to include a semantic closure phrase
    or finish the current spoken sentence.
    Returns new_end_idx (index into trs).
    """
    closure_phrases = [
        "that's why", "so", "therefore", "in conclusion", "the point is", "the lesson",
        "remember", "this means", "in the end", "to summarize", "so the", "what i learned"
    ]
    total_segs = len(trs)
    # current end time
    end_time = trs[end_idx].get("end", trs[end_idx].get("start", 0.0))
    # scan forward a few segments but don't go beyond max_extend_seconds
    i = end_idx + 1
    while i < total_segs:
        seg = trs[i]
        seg_text = seg.get("text", "").lower()
        seg_start = seg.get("start", 0.0)
        # stop if we've extended too far in wall-clock time
        if seg_start - end_time > max_extend_seconds:
            break
        # if segment contains a closure phrase, include it (and maybe next)
        if any(p in seg_text for p in closure_phrases):
            # try to include one more segment to give "aftertaste"
            return min(total_segs - 1, i + 1)
        i += 1
    return end_idx

def detect_idea_boundaries(segments: list) -> list:
    """
    Genius-builder detect_idea_boundaries (drop-in).
    - Returns list of (start_idx, end_idx) tuples (same as before).
    - Also populates global ARC_META mapping:
        ARC_META[(start_idx, end_idx)] = {
            "label": "Motivation Myth",
            "stage": "setup" | "development" | "punch",
            "confidence": 0.0..1.0,
            "text": "combined arc text"
        }
    Notes:
    - Uses pairwise text_overlap() for semantic similarity (must exist in your codebase).
    - Uses fast, local heuristics for labels and stage detection (no external models).
    - Tunable thresholds near the top.
    """
    try:
        # Early exit
        if not segments:
            globals()['ARC_META'] = {}
            return []

        # === Tunables (adjust for your content mix) ===
        MIN_ARC_SEGS_SHORT = 1
        MIN_ARC_SEGS_LONG = 2
        SIM_BASE_RELAX_FOR_LONG = 0.30
        DELTA_DROP_THRESHOLD = 0.30
        MIN_SIM_THRESHOLD = 0.22
        MAX_GAP_MULTIPLIER = 2.5
        SMALL_MERGE_TIME = 0.6
        HIGH_SEM_MERGE = 0.55
        # =================================================

        # Helpers
        def _log(*a, **k):
            lg = globals().get("log", None)
            if lg is not None:
                try:
                    lg.info(*a, **k)
                    return
                except Exception:
                    pass
            print("[detect_idea_boundaries]", *a)

        # Safe extraction
        N = len(segments)
        texts = [ (seg.get("text", "") or "").strip() for seg in segments ]
        starts = [float(seg.get("start", 0.0) or 0.0) for seg in segments]
        ends = [float(seg.get("end", seg.get("start", 0.0) or 0.0) or seg.get("start", 0.0) or 0.0) for seg in segments]

        seg_durations = [max(0.01, e - s) for s, e in zip(starts, ends)]
        avg_seg_dur = float(np.mean(seg_durations)) if seg_durations else 0.5
        total_dur = (ends[-1] - starts[0]) if N > 0 else 0.0

        # adaptive thresholds
        max_gap = min(2.2, max(0.9, avg_seg_dur * MAX_GAP_MULTIPLIER))
        base_sim_threshold = 0.30 if N > 25 else 0.36
        sim_threshold = max(MIN_SIM_THRESHOLD, base_sim_threshold - (min(20, N) / 200.0))
        delta_drop_threshold = DELTA_DROP_THRESHOLD
        min_arc_segs = MIN_ARC_SEGS_SHORT if N < 6 else MIN_ARC_SEGS_LONG

        # closure / punch markers
        closure_phrases = {"so", "therefore", "ultimately", "in conclusion", "to summarize", "remember", "that's why", "the point is", "and that's why"}
        question_indicators = {"?", "how", "why", "what", "when", "where", "which"}
        development_markers = {"because", "so that", "in order to", "for example", "for instance", "first", "second", "third", "then", "next", "after"}

        # === compute pairwise similarity (i-1 vs i) ===
        pair_sims = []
        for i in range(1, N):
            try:
                s = text_overlap(texts[i-1], texts[i])
            except Exception:
                s = 0.0
            pair_sims.append(float(s))

        # moving average smoothing
        def smooth(arr, k=3):
            if not arr:
                return []
            out = []
            half = k // 2
            L = len(arr)
            for i in range(L):
                lo = max(0, i - half)
                hi = min(L, i + half + 1)
                out.append(float(np.mean(arr[lo:hi])))
            return out

        smooth_sims = smooth(pair_sims, k=3)

        # compute deltas and normalize
        deltas = [0.0]
        for i in range(1, len(smooth_sims)):
            d = abs(smooth_sims[i] - smooth_sims[i-1])
            deltas.append(d)
        max_delta = max(deltas) if deltas else 1.0
        if max_delta <= 0:
            max_delta = 1.0
        deltas = [d / max_delta for d in deltas]

        # --- main arc assembly loop (semantic + time heuristics) ---
        arcs = []
        cur_s = 0
        cur_e = 0
        cur_text_window = texts[0] if texts else ""

        for i in range(1, N):
            gap = starts[i] - ends[i-1]
            sim = smooth_sims[i-1] if (i-1) < len(smooth_sims) else 0.0
            delta = deltas[i-1] if (i-1) < len(deltas) else 0.0

            prev_low = (texts[i-1] or "").lower()
            prev_end_marker = prev_low.rstrip().endswith((".", "!", "?"))
            closure_hit = any(phrase in prev_low for phrase in closure_phrases) and prev_end_marker

            sudden_topic_shift = (delta >= delta_drop_threshold and sim < (sim_threshold + 0.05))
            large_gap = (gap > max_gap and sim < (sim_threshold + 0.15))
            closure_boundary = closure_hit and sim < (sim_threshold + 0.10)

            # continuation if similarity is high and gap is OK OR small delta
            continue_arc = False
            if sim >= sim_threshold and gap <= max_gap:
                continue_arc = True
            elif (sim >= sim_threshold - 0.08) and delta < (delta_drop_threshold * 0.6) and gap <= max_gap:
                continue_arc = True

            # force boundary on extreme shift events
            if sudden_topic_shift or large_gap or closure_boundary:
                continue_arc = False

            if continue_arc:
                cur_e = i
                cur_text_window = (cur_text_window + " " + texts[i])[-2400:]
            else:
                # close arc
                if (cur_e - cur_s + 1) >= min_arc_segs:
                    arcs.append((cur_s, cur_e))
                else:
                    # try merging a very small arc into previous arc if semantically close
                    if arcs and (cur_e - cur_s + 1) < min_arc_segs:
                        prev_s, prev_e = arcs[-1]
                        prev_text = " ".join(texts[prev_s:prev_e+1])
                        cur_text = " ".join(texts[cur_s:cur_e+1])
                        try:
                            sim_to_prev = text_overlap(prev_text, cur_text)
                        except Exception:
                            sim_to_prev = 0.0
                        if sim_to_prev > 0.34:
                            arcs[-1] = (prev_s, cur_e)
                        else:
                            arcs.append((cur_s, cur_e))
                    else:
                        arcs.append((cur_s, cur_e))
                # start new arc
                cur_s = i
                cur_e = i
                cur_text_window = texts[i]

        # finalize last arc
        if (cur_e - cur_s + 1) >= min_arc_segs:
            arcs.append((cur_s, cur_e))
        else:
            if arcs:
                prev_s, prev_e = arcs[-1]
                arcs[-1] = (prev_s, cur_e)
            else:
                arcs.append((cur_s, cur_e))

        # remove duplicates & sort
        arcs = sorted(list(dict.fromkeys(arcs)), key=lambda x: x[0])

        # conservative sliding windows fallback ONLY when arcs too few
        if len(arcs) < 4 and N >= 6:
            windows = []
            for w in (4, 6, 8):
                step = max(1, w // 2)
                for s in range(0, max(1, N - w + 1), step):
                    e = min(N - 1, s + w - 1)
                    # avoid too-close existing arcs
                    too_close = any(abs(starts[s] - starts[a_s]) < max(0.8, avg_seg_dur) and abs(ends[e] - ends[a_e]) < max(0.8, avg_seg_dur) for a_s, a_e in arcs)
                    if not too_close:
                        windows.append((s, e))
            for w in windows:
                if w not in arcs:
                    arcs.append(w)
                if len(arcs) >= 8:
                    break

        # Final merge: coalesce arcs that are near in time OR very semantically similar
        merged = []
        for s, e in sorted(arcs, key=lambda x: (x[0], x[1])):
            if not merged:
                merged.append([s, e])
                continue
            prev_s, prev_e = merged[-1]
            time_gap_secs = starts[s] - ends[prev_e]
            prev_text = " ".join(texts[prev_s:prev_e+1])
            cur_text = " ".join(texts[s:e+1])
            try:
                sem_sim = text_overlap(prev_text, cur_text)
            except Exception:
                sem_sim = 0.0

            if s <= prev_e + 1 or time_gap_secs <= SMALL_MERGE_TIME or sem_sim > HIGH_SEM_MERGE:
                merged[-1][1] = max(prev_e, e)
            else:
                merged.append([s, e])
        arcs = [(int(a), int(b)) for a, b in merged]

        # === NEW: metadata extraction per arc (label + stage + confidence) ===
        ARC_META = {}
        stopwords = {
            "the", "is", "in", "and", "to", "a", "of", "it", "that", "this", "for", "on", "with",
            "as", "are", "was", "be", "by", "i", "you", "they", "we", "but", "or", "an", "so"
        }

        def extract_label(text, max_words=3):
            if not text:
                return "idea"
            # simple tokenization
            toks = [t.lower() for t in re.findall(r"[A-Za-z0-9']+", text)]
            # score tokens by frequency, ignoring stopwords and short tokens
            freq = {}
            for t in toks:
                if len(t) < 3 or t in stopwords:
                    continue
                freq[t] = freq.get(t, 0) + 1
            # prefer longer descriptive tokens if tie
            items = sorted(freq.items(), key=lambda x: (-x[1], -len(x[0])))
            if items:
                words = [it[0] for it in items[:max_words]]
                return " ".join(words).title()
            # fallback: short prefix
            s = " ".join(toks[:max_words]).strip()
            return (s[:40] + "...") if len(s) > 40 else (s or "idea")

        def detect_stage(arc_text):
            t = (arc_text or "").lower()
            score = 0.0
            # question heavy -> setup
            q_count = t.count("?") + sum(1 for q in question_indicators if (" " + q + " ") in (" " + t + " "))
            # development markers
            dev_count = sum(1 for w in development_markers if w in t)
            # closure / punch markers
            punch_count = sum(1 for w in closure_phrases if w in t) + (1 if t.rstrip().endswith(("!", ".")) else 0)
            # exclamation bias for punch
            exclaim = t.count("!")
            # determine
            if q_count > 0 and punch_count == 0:
                stage = "setup"
            elif punch_count > 0 or exclaim >= 1:
                stage = "punch"
            elif dev_count > 0:
                stage = "development"
            else:
                # fallback heuristics using length and presence of 'how to' / 'because'
                if "how to" in t or "how" in t and "to" in t:
                    stage = "development"
                elif len(t.split()) <= 8 and q_count > 0:
                    stage = "setup"
                else:
                    # if arc contains 'that's why' etc -> punch
                    if any(p in t for p in closure_phrases):
                        stage = "punch"
                    else:
                        stage = "development" if len(t.split()) > 12 else "setup"
            # compute a crude confidence from counts and length
            conf = min(0.98, 0.2 + min(1.0, (q_count + dev_count + punch_count + exclaim) * 0.18) + min(0.5, len(t.split()) / 60.0))
            return stage, round(conf, 2)

        # populate meta
        for s, e in arcs:
            arc_text = " ".join(texts[s:e+1]).strip()
            label = extract_label(arc_text, max_words=3)
            stage, conf = detect_stage(arc_text)
            ARC_META[(s, e)] = {
                "label": label,
                "stage": stage,
                "confidence": conf,
                "text": arc_text
            }

        # expose metadata globally for UI or downstream functions
        globals()['ARC_META'] = ARC_META

        # safety: ensure we always return at least one arc
        if not arcs:
            return [(0, max(0, N - 1))]

        return arcs

    except Exception as exc:
        # graceful degrade
        _lg = globals().get("log", None)
        if _lg:
            try:
                _lg.exception("detect_idea_boundaries failure: %s", exc)
            except Exception:
                pass
        else:
            print("[detect_idea_boundaries] exception:", exc)
        # fallback single arc
        globals()['ARC_META'] = { (0, max(0, len(segments) - 1)): {"label":"whole","stage":"development","confidence":0.5, "text": " ".join([(s.get('text','') or '') for s in segments]) } }
        return [(0, max(0, len(segments) - 1))]

def find_viral_moments(path, top_k=12, allow_fallback=False, payoff_conf_thresh=0.70, min_curiosity_peak=0.22):
    """
    Genius-layer find_viral_moments
    
    Layers:
     1) Transcribe + fast analyze curiosity/punch
     2) Build idea graph seeded by curiosity candidates
     3) For each idea-node: compute audio/visual/brain features, detect payoff, score
     4) Strict validation gates: curiosity rise, peak, payoff confidence, sensible end
     5) Dedupe / stitch / diversity selection
     6) Return top_k results (no meaningless clips). Debug info logged to help tuning.

    Parameters:
      path: str video/audio path
      top_k: number of clips requested
      allow_fallback: whether to fall back to evenly spaced windows (default False)
      payoff_conf_thresh: minimum payoff confidence to accept clip
      min_curiosity_peak: minimum curiosity peak to consider clip interesting
    """
    import os
    import hashlib
    import numpy as np
    from statistics import mean
    model_name = "small"
    use_gpu = True

    # defensive imports (your project helpers)
    try:
        from viral_finder.gemini_transcript_engine import transcribe_file, warmup
    except Exception:
        transcribe_and_analyze = None

    # core helpers - assume present, call defensively
    from viral_finder.ultron_brain import load_ultron_brain, ultron_learn, ultron_brain_score
    try:
        from viral_finder.idea_graph import build_idea_graph, select_candidate_clips
    except Exception:
        build_idea_graph = None
        select_candidate_clips = None

    try:
        from . import (
            text_overlap, fuse, dedupe_by_time
        )
    except Exception:
        # if missing, define safe fallbacks
        text_overlap = lambda a, b: 0.0
        fuse = lambda *args: float(mean([float(x or 0.0) for x in args])) if args else 0.0
        dedupe_by_time = lambda arr, time_tol=0.5: arr

    # other pipeline helpers
    try:
        from viral_finder.visual_audio_engine import analyze_audio, analyze_visual
    except Exception:
        analyze_audio = lambda p: []
        analyze_visual = lambda p: []

    # Attempt smart transcription + analysis (preferred)
    brain = load_ultron_brain()
    trs = []
    aud = []
    vis = []
    curiosity_curve = None
    curiosity_candidates = []

    try:
        if transcribe_and_analyze:
            trs, feats, curiosity_curve, curiosity_candidates = transcribe_and_analyze(
                path, model_name="small", device="cpu", aud=None, vis=None, brain=brain
            )
            # ensure aud/vis exist
            aud = analyze_audio(path) or []
            vis = analyze_visual(path) or []
        else:
            raise RuntimeError("transcribe_and_analyze not available")
    except Exception as exc:
        # defensive fallback to older pipeline pieces
        # ===============================
# TRANSCRIPT (SINGLE SOURCE OF TRUTH)
# ===============================
   
        from viral_finder.transcript_engine import extract_transcript

        trs = extract_transcript(
            path,
            model_name=model_name,
            prefer_gpu=use_gpu
        ) or []

    except Exception as e:
        print("[ULTRON] Transcript failed:", e)
        trs = []

    aud = analyze_audio(path) or []
    vis = analyze_visual(path) or []

    total_segs = len(trs)
    print("\n[ULTRON V33-X] Starting full self-evolving viral scan…")
    print(f"[ULTRON] Raw transcript segments: {total_segs}")

    if total_segs < 1:
        print("[ULTRON] Transcript empty, returning empty result.")
        return {"candidates": [], "rejected": [], "debug": {"total_arcs": 0, "curiosity_candidates": 0}}

    # If we don't have precomputed curiosity candidates, try to run analyzer
    try:
        if not curiosity_candidates:
            from viral_finder.idea_graph import analyze_curiosity_and_detect_punches
            feats, curiosity_curve, curiosity_candidates = analyze_curiosity_and_detect_punches(trs, aud=aud, vis=vis, brain=brain)
    except Exception:
        # keep empty
        curiosity_candidates = curiosity_candidates or []

    # Build idea graph seeded by curiosity candidates (preferred)
    nodes = []
    candidates = []
    try:
        phase1_unsuppress = str(os.environ.get("HS_ULTRON_PHASE1_UNSUPPRESS", "1")).strip().lower() in ("1", "true", "yes", "on")
        relaxed_curio_cutoff = float(os.environ.get("HS_ULTRON_CURIO_CUTOFF", "0.16") or 0.16)
        relaxed_punch_cutoff = float(os.environ.get("HS_ULTRON_PUNCH_CUTOFF", "0.16") or 0.16)
        nodes = build_idea_graph(
            trs,
            aud=aud,
            vis=vis,
            curiosity_candidates=curiosity_candidates,
            brain=brain,
            disable_coalesce=phase1_unsuppress,
            disable_node_cap=phase1_unsuppress,
        ) or []
        from viral_finder.idea_graph import select_candidate_clips

        candidates = select_candidate_clips(
            nodes,
            top_k=top_k,
            transcript=trs,
            ensure_sentence_complete=True,
            allow_multi_angle=True if phase1_unsuppress else False,
            diversity_mode="maximum" if phase1_unsuppress else "balanced",
            min_target=max(0, int(top_k)) if phase1_unsuppress else 0,
            curio_cutoff=relaxed_curio_cutoff if phase1_unsuppress else None,
            punch_cutoff=relaxed_punch_cutoff if phase1_unsuppress else None,
        )

    except Exception as exc:
        print("[ULTRON] build_idea_graph failed:", exc)
        # fallback: every N segments -> naive nodes
        if total_segs:
            approx = max(1, total_segs // 12)
            nodes = []
            for i in range(0, total_segs, approx):
                nodes.append(type("N", (), {"start_idx": i, "end_idx": min(total_segs - 1, i + approx - 1)}))

    # Convert nodes to (start_idx, end_idx) for fallback mapping.
    idea_boundaries = [(int(getattr(n, "start_idx", n[0])), int(getattr(n, "end_idx", n[1]))) for n in nodes]

    # Fix 1: score selected candidate arcs first (complete-thought spans), not raw node boundaries.
    def _time_to_seg_index(transcript, t):
        if not transcript:
            return 0
        for i, seg in enumerate(transcript):
            s = float(seg.get("start", 0.0) or 0.0)
            e = float(seg.get("end", s) or s)
            if s <= float(t) <= e:
                return i
        return min(
            range(len(transcript)),
            key=lambda i: abs(float(transcript[i].get("start", 0.0) or 0.0) - float(t)),
        )

    scoring_arcs = []
    if isinstance(candidates, list) and candidates:
        for i, arc in enumerate(candidates):
            try:
                if isinstance(arc, dict) and ("start_idx" in arc or "end_idx" in arc):
                    s_idx = int(arc.get("start_idx", 0) or 0)
                    e_idx = int(arc.get("end_idx", s_idx) or s_idx)
                elif isinstance(arc, dict):
                    s_t = float(arc.get("start", 0.0) or 0.0)
                    e_t = float(arc.get("end", s_t) or s_t)
                    s_idx = _time_to_seg_index(trs, s_t)
                    e_idx = _time_to_seg_index(trs, e_t)
                else:
                    continue
                s_idx = max(0, min(len(trs) - 1, int(s_idx)))
                e_idx = max(s_idx, min(len(trs) - 1, int(e_idx)))
                scoring_arcs.append((i, s_idx, e_idx, arc))
            except Exception:
                continue
    else:
        scoring_arcs = [(i, int(s), int(e), None) for i, (s, e) in enumerate(idea_boundaries)]

    print(
        f"[ULTRON] Generated {len(idea_boundaries)} node arcs and "
        f"{len(candidates) if isinstance(candidates, list) else 0} selected arcs"
    )

    # --- helpers inside function ---
    def _slice_mean(list_of_dicts, key, s, e):
        vals = [float(x.get(key, 0.0)) for x in list_of_dicts if s <= float(x.get("time", 0.0)) <= e]
        return float(np.mean(vals)) if vals else 0.0

    def _safe_text(seg):
        return (seg.get("text", "") or "").strip()

    def _fingerprint(text, start_t, end_t):
        normalized = " ".join(text.lower().split())[:240]
        key = f"{round(start_t,1)}-{round(end_t,1)}|{normalized}"
        return hashlib.md5(key.encode("utf-8")).hexdigest()

    # Validation gate - strict, transparent
    def validate_clip(curve, start_t, end_t, payoff_conf, min_peak=min_curiosity_peak):
        # payoff gate
        if payoff_conf is None or payoff_conf < payoff_conf_thresh:
            return False, "payoff_low"
        # curve existence
        if not curve or len(curve) < 3:
            return False, "no_curve"
        # extract values within window
        window = [v for (t, v) in curve if start_t <= t <= end_t]
        if not window or len(window) < 3:
            return False, "too_short_window"
        peak = max(window)
        if peak < min_peak:
            return False, "no_curiosity_peak"
        # peak must occur before end- small margin
        peak_idx = window.index(peak)
        if peak_idx >= len(window) - 1:
            # peak at very end; not a payoff
            return False, "peak_at_end"
        # ensure drop/flatten at end (last value below peak by delta or at least not rising)
        if window[-1] > window[-2] + 0.02:
            return False, "no_curiosity_drop"
        return True, "ok"

    # Collect candidates with debug info
    raw_candidates = []
    rejected = []
    for arc_idx, start_idx, end_idx, selected_arc in scoring_arcs:
        debug = {
            "arc_idx": arc_idx,
            "start_idx": start_idx,
            "end_idx": end_idx,
            "decision": None,
            "reason": None,
            "selected_arc_seeded": bool(selected_arc is not None),
        }

        # bounds safety
        start_idx = max(0, start_idx)
        end_idx = min(max(start_idx, end_idx), max(0, total_segs - 1))

        # semantic closure: try to extend to sentence boundary if function exists
        try:
            from viral_finder.ultron_finder_v33 import extend_to_closure
            new_end = extend_to_closure(trs, start_idx, end_idx, max_extend_seconds=8.0)
            if isinstance(new_end, int) and new_end >= end_idx:
                end_idx = min(len(trs) - 1, new_end)
        except Exception:
            pass

        combined_text = " ".join([_safe_text(seg) for seg in trs[start_idx:end_idx + 1]]).strip()
        idea_start = float(trs[start_idx].get("start", 0.0)) if start_idx < total_segs else 0.0
        idea_end = float(trs[end_idx].get("end", idea_start + 0.5)) if end_idx < total_segs else idea_start + 0.5

        if idea_end - idea_start < 1.2:
            debug["decision"] = "reject"
            debug["reason"] = "too_short"
            rejected.append(debug)
            continue

        # features
        a_avg = _slice_mean(aud, "energy", idea_start, idea_end)
        m_avg = _slice_mean(vis, "motion", idea_start, idea_end)
        try:
            impact, meaning, novelty, emotion, clarity = ultron_brain_score(combined_text or "", brain)
        except Exception:
            impact = meaning = novelty = emotion = clarity = 0.0

        hook = 0.1 * (1.0 if "?" in combined_text else 0.0) + 0.08 * (1.0 if "!" in combined_text else 0.0)
        continuity = text_overlap(trs[start_idx].get("text", ""), trs[end_idx].get("text", "")) if total_segs else 0.0
        arc_len = idea_end - idea_start
        continuity_bonus = min(0.45, continuity * (arc_len / max(1.0, min(arc_len, 60.0))))
        classic = fuse(hook + 0.05, a_avg, m_avg)
        provisional = (0.40 * impact) + (0.25 * classic) + (0.20 * meaning) + (0.15 * continuity_bonus)

        # punch detection
        try:
            from utils.narrative_intelligence import detect_message_punch
            punch_conf_raw = detect_message_punch(idea_start, idea_end, combined_text, trs, provisional)
            punch_conf = float(punch_conf_raw) if isinstance(punch_conf_raw, (int, float)) else (1.0 if punch_conf_raw else 0.0)
        except Exception:
            punch_conf = 0.0

        # semantic quality
        try:
            semantic_quality = estimate_semantic_quality(combined_text, provisional)
        except Exception:
            semantic_quality = provisional

        # payoff detection: prefer candidate meta from curiosity analyzer
        payoff_time = None
        payoff_conf = None
        # search matching curiosity_candidate that overlaps this node
        try:
            for cand in curiosity_candidates:
                c_s = cand.get("start_time") or cand.get("start") or 0.0
                c_e = cand.get("end_time") or cand.get("end") or 0.0
                if c_s <= idea_end and c_e >= idea_start:
                    payoff_time = cand.get("payoff_time") or cand.get("end_time") or cand.get("end")
                    payoff_conf = cand.get("payoff_confidence") or cand.get("payoff_conf") or cand.get("payoff_confidence", None)
                    break
        except Exception:
            pass

        # fallback: if no payoff found, attempt detect_payoff_end if available
        if payoff_time is None:
            try:
                from viral_finder.idea_graph import detect_payoff_end
                ptime, pconf = detect_payoff_end(trs, start_idx, end_idx, curiosity_curve=curiosity_curve)
                payoff_time = ptime
                payoff_conf = pconf
            except Exception:
                payoff_time = None
                payoff_conf = None

        # final decision to try to extend to sentence complete around payoff_time
        if payoff_time and payoff_time > idea_end:
            try:
                # extend to sentence end near payoff_time
                idea_end = extend_until_sentence_complete(idea_start, payoff_time, trs, max_extend=6.0) or idea_end
            except Exception:
                pass

        # final scoring
        final_classic = fuse(hook + 0.05, a_avg, m_avg)
        final_score = (0.40 * impact) + (0.22 * final_classic) + (0.20 * meaning) + (0.18 * continuity_bonus)
        final_score = float(round(final_score, 4))

        # attach candidate
        candidate = {
            "text": combined_text,
            "start": round(idea_start, 2),
            "end": round(idea_end, 2),
            "score": final_score,
            "hook": round(hook, 4),
            "audio": round(a_avg, 4),
            "motion": round(m_avg, 4),
            "impact": round(impact, 4),
            "meaning": round(meaning, 4),
            "continuity": round(continuity, 4),
            "arc_len": round(arc_len, 2),
            "punch_conf": round(punch_conf, 3),
            "semantic_quality": round(semantic_quality, 3),
            "fingerprint": _fingerprint(combined_text, idea_start, idea_end),
            "payoff_time": payoff_time,
            "payoff_confidence": float(payoff_conf) if payoff_conf is not None else None
        }

        # validate via curiosity curve + payoff
        if curiosity_curve is None:
            _curiosity = []
        elif hasattr(curiosity_curve, "tolist"):
            _curiosity = curiosity_curve.tolist()
        else:
            _curiosity = curiosity_curve

        ok, reason = validate_clip(
           _curiosity,
           candidate["start"],
           candidate["end"],
           candidate.get("payoff_confidence"),
           min_peak=min_curiosity_peak
        )

        if not ok:
            debug.update({
              "decision": "reject",
              "reason": reason,
              "meta": candidate
            })
            rejected.append(debug)
            continue
        
        # accept
        debug.update({"decision": "accept", "reason": "ok", "meta": candidate})
        raw_candidates.append(candidate)

        # learning hook
        try:
            ultron_learn(brain, candidate.get("impact", 0.0), candidate.get("score", 0.0))
        except Exception:
            pass

    # dedupe by time (strict)
    try:
        raw_candidates = dedupe_by_time(raw_candidates, time_tol=0.5)
    except Exception:
        pass

    # stitch adjacent if clearly same narrative (keep highest score)
    stitched = []
    for c in sorted(raw_candidates, key=lambda x: (x["start"], -x["score"])):
        if not stitched:
            stitched.append(dict(c))
            continue
        prev = stitched[-1]
        time_gap = c["start"] - prev["end"]
        sim = text_overlap(prev["text"], c["text"])
        score_diff = abs(prev["score"] - c["score"])
        if time_gap <= 3.0 and sim > 0.36 and score_diff < 0.3:
            prev["end"] = round(max(prev["end"], c["end"]), 2)
            prev["text"] = (prev["text"] + " " + c["text"]).strip()
            prev["score"] = round(max(prev["score"], c["score"]), 4)
            prev["arc_len"] = round(prev["end"] - prev["start"], 2)
            prev["continuity"] = round(text_overlap(prev["text"].split()[0] if prev["text"] else "", prev["text"].split()[-1] if prev["text"] else ""), 4)
        else:
            stitched.append(dict(c))

    candidates = stitched

    # uniqueness gate by fingerprint (keep highest)
    unique_map = {}
    for c in sorted(candidates, key=lambda x: (-x["score"], x["start"])):
        fp = c.get("fingerprint") or _fingerprint(c.get("text", ""), c["start"], c["end"])
        if fp not in unique_map or c["score"] > unique_map[fp]["score"]:
            unique_map[fp] = c
    candidates = list(unique_map.values())
    candidates.sort(key=lambda x: x["score"], reverse=True)

    # final diversity selection: avoid many that start nearby
    results = []
    used_starts = []
    for c in candidates:
        if len(results) >= top_k:
            break
        too_close = any(abs(c["start"] - s) < 3.0 for s in used_starts)
        if not too_close:
            results.append(c)
            used_starts.append(c["start"])

    # If empty and allow_fallback True, produce minimal, labeled fallback windows (low confidence)
    if not results and allow_fallback:
        # evenly spaced fallback but mark as fallback so UI can show hint
        total_dur = max(1.0, (trs[-1].get("end") if trs else 60.0) or 60.0)
        step = max(10, int(total_dur // max(1, top_k)))
        for i in range(top_k):
            s = i * step
            e = min(total_dur, s + min(15, step))
            results.append({
                "text": "",
                "start": round(float(s), 2),
                "end": round(float(e), 2),
                "score": 0.0,
                "hook": 0.0,
                "audio": 0.0,
                "motion": 0.0,
                "impact": 0.0,
                "meaning": 0.0,
                "continuity": 0.0,
                "arc_len": round(e - s, 2),
                "punch_conf": 0.0,
                "semantic_quality": 0.0,
                "fingerprint": _fingerprint("fallback", s, e),
                "payoff_time": None,
                "payoff_confidence": 0.0,
                "fallback": True
            })

    # Debug lens printing
    try:
        if os.environ.get("ULTRON_DEBUG_LENS") == "1":
            print("\n[DEBUG LENS] Top candidates (post-filter):")
            for i, r in enumerate(results[:top_k]):
                print(f"[{i+1}] {r['start']:.2f}-{r['end']:.2f}  score={r['score']:.3f} payoff={r.get('payoff_confidence')}")
                head = (r.get("text","").split("|")[0] if r.get("text") else "")[:120]
                tail = (r.get("text","").split("|")[-1] if r.get("text") else "")[:120]
                print("   head:", head)
                print("   tail:", tail)
            # print rejection reasons summary
            from collections import Counter
            reasons = [r["reason"] for r in rejected]
            print("Reject reasons:", Counter(reasons))
    except Exception:
        pass

    print(f"[ULTRON] Returning {len(results)} raw candidates")
    return {
    "candidates": results,
    "rejected": rejected,
    "debug": {
        "total_arcs": len(idea_boundaries),
        "curiosity_candidates": len(curiosity_candidates)
    }
}

