"""
orchestrator.py

Master orchestrator that wires together Hotshort's intelligence stack:
 - transcription (gemini_transcript_engine or transcript_engine)
 - curiosity & punch analyzer (idea_graph / ignition_deep / parallel_mind)
 - audio & visual feature extraction (visual_audio_engine)
 - semantic/brain scoring (ultron_brain)
 - candidate selection & final clip generation

Usage:
    from viral_finder.orchestrator import orchestrate, cli_main
    orchestrate(path_to_file, top_k=8)

Drop this file into viral_finder/ as orchestrator.py and import from your existing pipeline.
"""

import os
import sys
import time
import math
import hashlib
import logging
import inspect
import re
from collections import Counter
from viral_finder.cognition import Evidence, IntelligenceArtifact
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed # Keep for other uses if any
from typing import List, Dict, Any, Optional
try:
    import psutil
except Exception:
    psutil = None

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
log = logging.getLogger("orchestrator")

# Defensive imports for project modules (graceful fallbacks)
try:
    from viral_finder.gemini_transcript_engine import transcribe_file as gemini_transcribe, transcribe_and_analyze
except Exception as e:
    log.warning(f"[ORCH] Import fallback triggered for viral_finder.gemini_transcript_engine: {e}")
    gemini_transcribe = None
    transcribe_and_analyze = None

try:
    from viral_finder.transcript_engine import transcribe_file as legacy_transcribe, extract_transcript
except Exception as e:
    log.warning(f"[ORCH] Import fallback triggered for viral_finder.transcript_engine: {e}")
    legacy_transcribe = None
    extract_transcript = None

try:
    from viral_finder.visual_audio_engine import analyze_audio, analyze_visual
except Exception as e:
    log.warning(f"[ORCH] Import fallback triggered for viral_finder.visual_audio_engine: {e}")
    analyze_audio = lambda path: []
    analyze_visual = lambda path: []

try:
    from viral_finder.idea_graph import (
        analyze_curiosity_and_detect_punches,
        build_idea_graph,
        select_candidate_clips,
        sentence_complete_extend,
        detect_payoff_end
    )
except Exception as e:
    log.warning(f"[ORCH] Import fallback triggered for unknown: {e}")
    analyze_curiosity_and_detect_punches = None
    build_idea_graph = None
    select_candidate_clips = None
    sentence_complete_extend = None
    detect_payoff_end = None

try:
    from viral_finder.curiosity_engine import run_curiosity as run_curiosity_stage
except Exception as e:
    log.warning(f"[ORCH] Import fallback triggered for viral_finder.curiosity_engine: {e}")
    run_curiosity_stage = None

try:
    from viral_finder.transcription_router import (
        choose_transcription_engine,
        get_transcription_config,
        log_routing_decision,
        apply_transcription_routing,
    )
    TRANSCRIPTION_ROUTER_AVAILABLE = True
except Exception as e:
    log.warning(f"[ORCH] Import fallback triggered for unknown: {e}")
    TRANSCRIPTION_ROUTER_AVAILABLE = False
    log.warning("[ROUTER] Transcription router not available, using legacy mode")

try:
    from viral_finder.validation_gates import apply_post_enrichment_validation
except Exception as e:
    log.warning(f"[ORCH] Import fallback triggered for viral_finder.validation_gates: {e}")
    apply_post_enrichment_validation = None

try:
    from viral_finder.clip_selector import rank_and_diversify
except Exception as e:
    log.warning(f"[ORCH] Import fallback triggered for viral_finder.clip_selector: {e}")
    rank_and_diversify = None

try:
    from viral_finder.narrative_trigger_engine import detect_narrative_triggers
except Exception as e:
    log.warning(f"[ORCH] Import fallback triggered for viral_finder.narrative_trigger_engine: {e}")
    detect_narrative_triggers = None

try:
    from utils.narrative_intelligence import compute_quality_scores
    from utils.narrative_intelligence import cqs_cache_reset, cqs_cache_stats
except Exception as e:
    log.warning(f"[ORCH] Import fallback triggered for utils.narrative_intelligence: {e}")
    compute_quality_scores = None
    cqs_cache_reset = lambda: {}
    cqs_cache_stats = lambda: {}
# Story memory feature fallback
compute_hook_resolution_bonus = None
try:
    from utils.narrative_intelligence import detect_message_punch as _detect_message_punch
except Exception as e:
    log.warning(f"[ORCH] Import fallback triggered for utils.narrative_intelligence: {e}")
    _detect_message_punch = None
try:
    from utils.story_patterns import detect_story_pattern
except Exception as e:
    log.warning(f"[ORCH] Import fallback triggered for utils.story_patterns: {e}")
    detect_story_pattern = None

try:
    from viral_finder.pipeline_trace import PipelineTrace
except Exception as e:
    log.warning(f"[ORCH] Import fallback triggered for viral_finder.pipeline_trace: {e}")
    PipelineTrace = None

try:
    from .global_fields import build_cognition_cache
    from .dominance_selector import select_dominant_arcs, SelectorConfig
except ImportError as e:
    log.warning(f"[ORCH] Import fallback triggered for .dominance_selector: {e}")
    build_cognition_cache = None
    select_dominant_arcs = None
    SelectorConfig = None

from viral_finder.pipeline_context import PipelineContext
try:
    from .ultron_finder_v33 import find_viral_moments as ultron_engine
except ImportError as e:
    log.warning(f"[ORCH] Import fallback triggered for .ultron_finder_v33: {e}")
    ultron_engine = None

# Avoid importing ultron_brain eagerly because it loads SentenceTransformer
# at module import time and can spike RAM on small instances.
_brain_import_attempted = False
_brain_import_ok = False
_brain_import_error = None
_runtime_load_ultron_brain = lambda: None
_runtime_ultron_brain_score = lambda text, brain=None: (0.0, 0.0, 0.0, 0.0, 0.0)
_runtime_ultron_learn = lambda brain, impact, score: None

# Lightweight utility helpers kept local to avoid heavy transitive imports.
def fuse(hook, audio, motion):
    return float((float(hook or 0.0) + float(audio or 0.0) + float(motion or 0.0)) / 3.0)


def _heuristic_semantic_scores(text: str, brain=None):
    text = str(text or "").strip()
    if not text:
        return 0.0, 0.0, 0.0, 0.0, 0.0
    wc = len(text.split())
    t_low = text.lower()
    meaning = min(1.0, wc / 18.0)
    # novelty=0.5: neutral, not 1.0 which is noise (we have no actual semantic distance signal here)
    novelty = 0.5
    emotion_words = {
        "love", "hate", "amazing", "insane", "truth",
        "secret", "exposed", "crazy", "fear", "power",
    }
    emotion = min(1.0, sum(w in t_low for w in emotion_words) / 4.0)
    clarity = max(0.2, 1.0 - min(1.0, wc / 35.0))
    impact = (meaning + novelty + emotion + clarity) / 4.0
    return (
        round(float(impact), 4),
        round(float(meaning), 4),
        round(float(novelty), 4),
        round(float(emotion), 4),
        round(float(clarity), 4),
    )


def text_overlap(a, b):
    if not a or not b:
        return 0.0
    aw = set(str(a).lower().split())
    bw = set(str(b).lower().split())
    if not aw or not bw:
        return 0.0
    inter = len(aw & bw)
    uni = len(aw | bw)
    return float(inter) / float(max(1, uni))


def dedupe_by_time(arr, time_tol=0.5):
    if not arr:
        return []
    out = []
    for c in sorted(arr, key=lambda x: (-float(x.get("score", 0.0) or 0.0), float(x.get("start", 0.0) or 0.0))):
        s = float(c.get("start", 0.0) or 0.0)
        e = float(c.get("end", s) or s)
        keep = True
        for ex in out:
            es = float(ex.get("start", 0.0) or 0.0)
            ee = float(ex.get("end", es) or es)
            if abs(s - es) <= float(time_tol) and abs(e - ee) <= float(time_tol):
                keep = False
                break
        if keep:
            out.append(c)
    return sorted(out, key=lambda x: float(x.get("start", 0.0) or 0.0))


def overlap_ratio(a_start, a_end, b_start, b_end):
    """
    Compute Intersection over Union (IoU) of two time windows.
    Returns 0-1 where 1 = perfect overlap, 0 = no overlap.
    """
    try:
        a_start = float(a_start or 0.0)
        a_end = float(a_end or a_start)
        b_start = float(b_start or 0.0)
        b_end = float(b_end or b_start)
        
        # Compute intersection
        inter_start = max(a_start, b_start)
        inter_end = min(a_end, b_end)
        inter = max(0.0, inter_end - inter_start)
        
        # Compute union
        union_start = min(a_start, b_start)
        union_end = max(a_end, b_end)
        union = max(0.001, union_end - union_start)  # Avoid div by zero
        
        return inter / union
    except Exception:
        return 0.0


def dedupe_by_overlap(clips, overlap_threshold=0.40):
    """
    🚀 Smart deduplication based on clip overlap ratio (IoU).
    Removes clips that overlap > threshold with higher-scored clips.
    
    Example: If clips 15.8-40.5 and 16.2-40.2 overlap > 40%, keep only the best-scored one.
    """
    if not clips:
        return []
    
    result = []
    # Sort by score (descending) to keep best clips when deduping
    sorted_clips = sorted(clips, key=lambda x: float(x.get("arc_score", x.get("viral_score", x.get("final_score", 0.0))) or 0.0), reverse=True)
    
    for clip in sorted_clips:
        clip_start = float(clip.get("start", 0.0) or 0.0)
        clip_end = float(clip.get("end", clip_start) or clip_start)
        
        # Check if this clip overlaps too much with any already-kept clip
        is_duplicate = False
        for existing in result:
            ex_start = float(existing.get("start", 0.0) or 0.0)
            ex_end = float(existing.get("end", ex_start) or ex_start)
            
            ratio = overlap_ratio(clip_start, clip_end, ex_start, ex_end)
            if ratio > overlap_threshold:
                is_duplicate = True
                
                cid_clip = clip.get('cid', clip.get('id', '?'))
                cid_existing = existing.get('cid', existing.get('id', '?'))
                score_clip = float(clip.get("arc_score", clip.get("viral_score", 0.0)) or 0.0)
                score_existing = float(existing.get("arc_score", existing.get("viral_score", 0.0)) or 0.0)
                
                import logging
                l_log = logging.getLogger("orchestrator")
                l_log.info("\n[DEDUP_TRACE]")
                l_log.info(f"candidate_id={cid_clip}")
                l_log.info(f"overlapped_with={cid_existing}")
                l_log.info(f"score_comparison={score_clip} vs {score_existing}")
                l_log.info(f"drop_reason=Overlap ratio {ratio:.2f} > threshold {overlap_threshold}\n")
                
                break
        
        if not is_duplicate:
            result.append(clip)
    
    # Return in chronological order
    return sorted(result, key=lambda x: float(x.get("start", 0.0) or 0.0))


def extend_until_sentence_complete(s, p, trs, max_extend=6.0):
    if not trs:
        return p
    end_t = float(p or s)
    for seg in trs:
        ts = float(seg.get("start", 0.0) or 0.0)
        te = float(seg.get("end", ts) or ts)
        if ts < end_t < te:
            return min(te, end_t + float(max_extend or 6.0))
    return end_t


def _clip_contains_time(candidate: Dict[str, Any], ts: Any, pad: float = 0.05) -> bool:
    try:
        t = float(ts)
        s = float(candidate.get("start", 0.0) or 0.0) - float(pad)
        e = float(candidate.get("end", s) or s) + float(pad)
        return s <= t <= e
    except Exception:
        return False


def _psychological_loop_state(
    *,
    hook_found: bool,
    payoff_idx: Optional[int],
    hook_idx: int,
    payoff_resolution: float,
    tension_gradient: float,
    info_density: float,
    rewatch: float,
) -> tuple[str, float]:
    expectation_opened = 1.0 if hook_found else 0.0
    expectation_maintained = _clamp01((0.60 * tension_gradient) + (0.40 * rewatch))
    evidence_added = _clamp01(info_density)
    payoff_delivered = _clamp01(payoff_resolution) if payoff_idx is not None else 0.0
    cognitive_closure = _clamp01((0.70 * payoff_delivered) + (0.30 * evidence_added))
    loop_health = _clamp01(
        (0.20 * expectation_opened)
        + (0.15 * expectation_maintained)
        + (0.20 * evidence_added)
        + (0.30 * payoff_delivered)
        + (0.15 * cognitive_closure)
    )
    if not hook_found:
        return "NO_HOOK", loop_health
    if payoff_idx is None or payoff_delivered <= 0.05:
        return "NO_PAYOFF", loop_health
    if payoff_idx == hook_idx and payoff_delivered >= 0.55:
        return "SELF_CONTAINED", loop_health
    if payoff_delivered >= 0.55 and cognitive_closure >= 0.50:
        return "RESOLVED", loop_health
    return "PARTIAL_PAYOFF", loop_health


def _loop_score_cap(loop_state: str, loop_health: float) -> float:
    state = str(loop_state or "UNKNOWN")
    if state in ("RESOLVED", "SELF_CONTAINED"):
        return 1.0
    if state == "PARTIAL_PAYOFF":
        return min(0.55, max(0.25, _clamp01(loop_health)))
    if state == "NO_PAYOFF":
        return 0.25
    if state == "NO_HOOK":
        return 0.20
    return 0.45


def _meaning_invariant_reject_reasons(candidate: Dict[str, Any]) -> List[str]:
    reasons: List[str] = []
    hook_seg = candidate.get("hook_segment") if isinstance(candidate.get("hook_segment"), dict) else {}
    payoff_seg = candidate.get("payoff_segment") if isinstance(candidate.get("payoff_segment"), dict) else {}
    if hook_seg and not _clip_contains_time(candidate, hook_seg.get("start")):
        reasons.append("hook_outside_clip")
    if payoff_seg and not _clip_contains_time(candidate, payoff_seg.get("end")):
        reasons.append("payoff_outside_clip")
    locked_payoff_time = candidate.get("locked_payoff_time")
    if locked_payoff_time is not None and not _clip_contains_time(candidate, locked_payoff_time):
        reasons.append("locked_payoff_outside_clip")
    return reasons


def _bridge_intelligence_to_signals(candidates: List[Dict[str, Any]], consumer: str) -> int:
    bridged = 0
    ev_map = {
        "stop_scroll": "stop_scroll",
        "memorability": "memorability",
        "shareability": "shareability",
        "usefulness": "usefulness",
        "completeness": "completeness",
        "emotional_charge": "emotional_charge",
        "curiosity": "curiosity",
        "curiosity_peak": "curiosity_peak",
    }
    for cand in candidates or []:
        if not isinstance(cand, dict):
            continue
        artifact = cand.get("intelligence")
        if not isinstance(artifact, IntelligenceArtifact):
            continue
        signals = cand.setdefault("signals", {})
        psych = signals.setdefault("psychology", {})
        for ev in artifact.evidence_stream:
            dest_key = ev_map.get(ev.type)
            if not dest_key:
                ev.reject(f"unsupported_evidence_type:{ev.type}", consumer)
                continue
            try:
                ev_val = float(ev.value) * float(ev.confidence)
            except (ValueError, TypeError):
                ev.reject("non_numeric_value", consumer)
                continue
            if ev_val > float(psych.get(dest_key, 0.0) or 0.0):
                psych[dest_key] = ev_val
                bridged += 1
            ev.consume(consumer)
    return bridged


def _reject_unsettled_intelligence(candidates: List[Dict[str, Any]], consumer: str, reason: str) -> int:
    rejected = 0
    for cand in candidates or []:
        if not isinstance(cand, dict):
            continue
        artifact = cand.get("intelligence")
        if not isinstance(artifact, IntelligenceArtifact):
            continue
        for ev in artifact.evidence_stream:
            if ev.transport_state == "ORPHANED":
                ev.reject(reason, consumer)
                rejected += 1
    return rejected

# core config
CACHE_DIR = ".hotshort_transcripts_cache"
DEFAULT_TOP_K = 8
MAX_ENRICH_WORKERS = max(1, min(4, max(1, (os.cpu_count() or 2) - 1)))


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return bool(default)
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    try:
        raw = os.getenv(name)
        if raw is None or str(raw).strip() == "":
            return int(default)
        return int(raw)
    except Exception:
        return int(default)


def _env_float(name: str, default: float) -> float:
    try:
        raw = os.getenv(name)
        if raw is None or str(raw).strip() == "":
            return float(default)
        return float(raw)
    except Exception:
        return float(default)


def _candidate_cache_tolerance_s() -> float:
    return max(0.1, _env_float("HS_ORCH_NARRATIVE_CACHE_TOLERANCE_S", 0.5))


def _stable_text_fingerprint(text: str) -> str:
    payload = str(text or "").strip().lower().encode("utf-8", "ignore")
    return hashlib.md5(payload).hexdigest()[:12]


def _normalized_candidate_cache_key(candidate: Dict[str, Any], transcript_len: int, tolerance_s: Optional[float] = None) -> str:
    tol = max(0.1, float(tolerance_s or _candidate_cache_tolerance_s()))
    start = float(candidate.get("start", 0.0) or 0.0)
    end = float(candidate.get("end", start) or start)
    start_q = round(start / tol) * tol
    end_q = round(end / tol) * tol
    fingerprint = candidate.get("fingerprint") or _stable_text_fingerprint(candidate.get("text", ""))
    return f"{transcript_len}:{round(start_q, 2)}:{round(end_q, 2)}:{fingerprint}"


IS_RENDER_RUNTIME = (
    str(os.environ.get("RENDER", "")).strip().lower() in ("1", "true", "yes", "on")
    or bool(os.environ.get("RENDER_SERVICE_ID"))
)


def _pipeline_profile() -> str:
    raw = os.getenv("HS_PIPELINE_PROFILE", "balanced_scientist")
    return str(raw or "balanced_scientist").strip().lower()


def _is_balanced_scientist() -> bool:
    return _pipeline_profile() == "balanced_scientist"


def _brain_enabled() -> bool:
    # Keep legacy key support but prefer the new profile-aware brain flag.
    if os.getenv("HS_BRAIN_ENABLE_ENRICH", "").strip() != "":
        raw = os.getenv("HS_BRAIN_ENABLE_ENRICH", "0")
        return str(raw).strip().lower() in ("1", "true", "yes", "on")
    # Render free tier default: disabled unless explicitly enabled.
    if os.getenv("HS_ORCH_BRAIN_ENABLED", "").strip() != "":
        raw = os.getenv("HS_ORCH_BRAIN_ENABLED", "0")
        return str(raw).strip().lower() in ("1", "true", "yes", "on")
    default = "0" if IS_RENDER_RUNTIME else "1"
    if _is_balanced_scientist() and IS_RENDER_RUNTIME:
        default = "0"
    raw = os.getenv("HS_ORCH_BRAIN_ENABLED", default)
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _rss_mb() -> float:
    if psutil is None:
        return 0.0
    try:
        p = psutil.Process(os.getpid())
        return float(getattr(p.memory_info(), "rss", 0) or 0) / (1024.0 * 1024.0)
    except Exception:
        return 0.0


def _res_checkpoint(stage: str, budget_mb: Optional[float] = None) -> float:
    rss = _rss_mb()
    budget = float(budget_mb or 0.0)
    if budget > 0.0:
        pct = (rss / budget) * 100.0
        log.info("[RES] stage=%s rss=%.1fMB budget=%.1fMB pct=%.1f", stage, rss, budget, pct)
    else:
        log.info("[RES] stage=%s rss=%.1fMB", stage, rss)
    return rss


def _memory_pressure_level(budget_mb: float) -> str:
    budget = max(1.0, float(budget_mb or 0.0))
    rss = _rss_mb()
    ratio = rss / budget
    if ratio >= 0.95:
        return "over"
    if ratio >= 0.85:
        return "near"
    return "safe"


def _ensure_brain_runtime_loaded() -> None:
    global _brain_import_attempted, _brain_import_ok, _brain_import_error
    global _runtime_load_ultron_brain, _runtime_ultron_brain_score, _runtime_ultron_learn

    if _brain_import_attempted:
        return
    _brain_import_attempted = True

    if not _brain_enabled():
        _brain_import_ok = False
        _brain_import_error = "disabled_by_env"
        return

    try:
        from viral_finder.ultron_brain import load_ultron_brain, ultron_brain_score, ultron_learn
        _runtime_load_ultron_brain = load_ultron_brain
        _runtime_ultron_brain_score = ultron_brain_score
        _runtime_ultron_learn = ultron_learn
        _brain_import_ok = True
    except Exception as exc:
        _brain_import_ok = False
        _brain_import_error = str(exc)
        _runtime_load_ultron_brain = lambda: None
        _runtime_ultron_brain_score = _heuristic_semantic_scores
        _runtime_ultron_learn = lambda brain, impact, score: None


if _env_bool("HS_BRAIN_EAGER_IMPORT", False):
    _ensure_brain_runtime_loaded()


def _resolve_min_target(total_dur: float, top_k: int) -> int:
    short_n = max(1, _env_int("HS_MIN_CLIPS_SHORT", 3))
    medium_n = max(1, _env_int("HS_MIN_CLIPS_MEDIUM", 4))
    long_n = max(1, _env_int("HS_MIN_CLIPS_LONG", 5))
    xlong_n = max(1, _env_int("HS_MIN_CLIPS_XLONG", 6))

    if total_dur < 90.0:
        target = short_n
    elif total_dur < 300.0:
        target = medium_n
    elif total_dur < 900.0:
        target = long_n
    else:
        target = xlong_n
    return max(1, min(int(target), int(max(1, top_k))))


def _extract_time_hint(item: Any) -> Optional[float]:
    try:
        if isinstance(item, dict):
            for k in ("peak_time", "time", "start", "t"):
                if k in item:
                    return float(item.get(k))
            for k in ("idx", "segment_idx"):
                if k in item:
                    return None
        elif isinstance(item, (list, tuple)):
            for v in item:
                try:
                    fv = float(v)
                except Exception:
                    continue
                if 0.0 <= fv < 1e6:
                    return fv
    except Exception:
        return None
    return None


def _collect_text_window(trs: List[Dict], s: float, e: float) -> str:
    if not trs:
        return ""
    parts = []
    for seg in trs:
        try:
            ss = float(seg.get("start", 0.0))
            ee = float(seg.get("end", ss))
        except Exception:
            continue
        if ee > s and ss < e:
            t = str(seg.get("text", "") or "").strip()
            if t:
                parts.append(t)
    return " ".join(parts).strip()


def _smart_backfill_candidates(
    trs: List[Dict],
    existing: List[Dict],
    target_min: int,
    top_k: int,
    curiosity_candidates: Optional[List[Any]] = None,
) -> List[Dict]:
    if not trs or target_min <= 0:
        return []

    total_dur = float(trs[-1].get("end", trs[-1].get("start", 0.0) + 60.0))
    clip_len = min(18.0, max(8.0, total_dur / max(4.0, float(target_min + 1))))
    bins = max(int(top_k), int(target_min * 2))
    step = max(6.0, total_dur / max(1.0, float(bins)))

    seen_fp = set()
    seen_ranges = []
    for c in (existing or []):
        try:
            s = float(c.get("start", 0.0))
            e = float(c.get("end", s))
            seen_ranges.append((s, e))
            fp = c.get("fingerprint") or _fingerprint(c.get("text", ""), s, e)
            seen_fp.add(fp)
        except Exception:
            pass

    seed_times = []
    for cc in (curiosity_candidates or []):
        t = _extract_time_hint(cc)
        if t is not None:
            seed_times.append(float(t))

    candidate_times = []
    candidate_times.extend(seed_times)
    t = 0.0
    while t < total_dur:
        candidate_times.append(float(t))
        t += step

    out = []
    for idx, ct in enumerate(candidate_times):
        s = max(0.0, min(float(ct), max(0.0, total_dur - clip_len)))
        e = min(total_dur, s + clip_len)
        if e <= s:
            continue

        # reject near-duplicate ranges
        too_close = False
        for rs, re in seen_ranges:
            inter = max(0.0, min(e, re) - max(s, rs))
            shorter = max(1e-6, min((e - s), (re - rs)))
            if (inter / shorter) > 0.65:
                too_close = True
                break
        if too_close:
            continue

        txt = _collect_text_window(trs, s, e)
        fp = _fingerprint(txt, s, e)
        if fp in seen_fp:
            continue

        seed_prox = 0.0
        if seed_times:
            nearest = min(abs(float(ct) - st) for st in seed_times)
            seed_prox = max(0.0, 1.0 - (nearest / max(1.0, clip_len * 2.0)))
        base_score = min(0.42, 0.16 + (0.20 * seed_prox) + (0.02 * (idx % 3)))

        out.append(
            {
                "text": txt,
                "start": round(float(s), 2),
                "end": round(float(e), 2),
                "score": round(float(base_score), 4),
                "fingerprint": fp,
                "label": "Alternate Angle",
                "reason": "diversity_backfill",
                "backfill": True,
                "backfill_source": "smart_bins",
            }
        )
        seen_fp.add(fp)
        seen_ranges.append((s, e))
        if len(out) >= max(0, target_min - len(existing or [])):
            break
    return out

# -------------------------
# Helpers
# -------------------------
def build_why_for_clip(c):
    why = []

    # Curiosity
    peak = c.get("curiosity_peak", 0)
    if peak > 0.3:
        why.append("Curiosity spike detected")

    # Belief flip / contradiction
    if c.get("ignition_type") in ("belief_flip", "contrarian_truth"):
        why.append("Belief flip / contradiction")

    # Authority / emotion
    if c.get("authority", 0) > 0.4:
        why.append("Authority-driven insight")
    elif c.get("emotion", 0) > 0.4:
        why.append("Emotional payoff")

    # Fallback (never empty)
    if not why:
        why.append("Narrative tension holds attention")

    return why

def _ensure_cache_dir():
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
    except Exception:
        pass


def _cache_key_for_path(path: str) -> str:
    """Key by file CONTENT (first 4 MB), not path string.
    Falls back to path-hash if file is unreadable (URL, missing, etc.).
    This ensures the same video always hits cache even when delivered via
    different temp paths or after a rename.
    """
    try:
        with open(path, 'rb') as _f:
            sample = _f.read(4 * 1024 * 1024)  # first 4 MB is enough to be unique
        return hashlib.sha1(sample).hexdigest()
    except Exception:
        # Remote URL or unreadable path — fall back to hashing the path string
        return hashlib.sha1(path.encode('utf-8')).hexdigest()


def _load_cached_transcript(path: str) -> Optional[List[Dict]]:
    _ensure_cache_dir()
    key = _cache_key_for_path(path)
    p = os.path.join(CACHE_DIR, f"{key}.json")
    if os.path.exists(p):
        try:
            import json
            with open(p, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return None
    return None


def _save_cached_transcript(path: str, segs: List[Dict]):
    _ensure_cache_dir()
    key = _cache_key_for_path(path)
    p = os.path.join(CACHE_DIR, f"{key}.json")
    try:
        import json
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(segs, f, ensure_ascii=False)
    except Exception:
        pass


def _slice_mean(list_of_dicts: List[Dict], key: str, s: float, e: float) -> float:
    vals = [float(x.get(key, 0.0)) for x in list_of_dicts if s <= float(x.get('time', x.get('start', 0.0) or 0.0)) <= e]
    if not vals:
        return 0.0
    return float(sum(vals) / len(vals))


def _fingerprint(text: str, s: float, e: float) -> str:
    k = f"{round(s,2)}-{round(e,2)}:{(' '.join(text.lower().split()))[:256]}"
    return hashlib.md5(k.encode('utf-8')).hexdigest()





def _interval_overlap_ratio(a_s: float, a_e: float, b_s: float, b_e: float) -> float:
    inter = max(0.0, min(a_e, b_e) - max(a_s, b_s))
    if inter <= 0.0:
        return 0.0
    shorter = max(1e-6, min(a_e - a_s, b_e - b_s))
    return float(inter / shorter)


def _shadow_metrics(godmode: List[Dict], legacy: List[Dict], top_k: int, target_min: int) -> Dict[str, float]:
    if not legacy:
        return {
            "dominant_clip_jaccard": 0.0,
            "arc_completeness_delta": 0.0,
            "score_margin_delta": 0.0,
            "underflow_rate": 1.0,
        }

    gm_top = godmode[0] if godmode else {}
    lg_top = legacy[0]
    jacc = _interval_overlap_ratio(
        float(gm_top.get("start", 0.0) or 0.0),
        float(gm_top.get("end", 0.0) or 0.0),
        float(lg_top.get("start", 0.0) or 0.0),
        float(lg_top.get("end", 0.0) or 0.0),
    )

    gm_arc = float(gm_top.get("arc_complete", 0.0) or 0.0)
    lg_arc = float(lg_top.get("arc_complete", 0.0) or 0.0)
    arc_delta = gm_arc - lg_arc

    gm_margin = 0.0
    if len(godmode) >= 2:
        gm_margin = float(godmode[0].get("score", 0.0) or 0.0) - float(godmode[1].get("score", 0.0) or 0.0)
    lg_margin = 0.0
    if len(legacy) >= 2:
        lg_margin = float(legacy[0].get("score", 0.0) or 0.0) - float(legacy[1].get("score", 0.0) or 0.0)
    score_margin_delta = gm_margin - lg_margin

    denom = float(max(1, max(top_k, target_min)))
    underflow = max(0.0, denom - float(len(godmode or []))) / denom
    return {
        "dominant_clip_jaccard": round(float(jacc), 4),
        "arc_completeness_delta": round(float(arc_delta), 4),
        "score_margin_delta": round(float(score_margin_delta), 4),
        "underflow_rate": round(float(underflow), 4),
    }

# -------------------------
# Enrichment (parallel-friendly)
# -------------------------

def _cheap_candidate_score(candidate: Dict[str, Any]) -> float:
    metrics = candidate.get("metrics", {}) or {}
    curiosity = _clamp01(candidate.get("curiosity", 0.0))
    punch = _clamp01(candidate.get("punch_confidence", 0.0))
    semantic = _clamp01(candidate.get("semantic_quality", candidate.get("score", 0.0)))
    payoff_hint = _clamp01(candidate.get("payoff_hint", metrics.get("payoff_confidence", 0.0)))
    curiosity_peak = _clamp01(metrics.get("curiosity_peak", candidate.get("curiosity", 0.0)))
    hook_strength = _clamp01(candidate.get("hook_strength", candidate.get("score", 0.0)))
    sarcasm_penalty = 1.0 - min(0.65, _clamp01(candidate.get("sarcasm_score", metrics.get("sarcasm", 0.0))) * 0.75)
    score = (
        (0.28 * semantic)
        + (0.22 * punch)
        + (0.18 * curiosity)
        + (0.14 * curiosity_peak)
        + (0.10 * payoff_hint)
        + (0.08 * hook_strength)
    )
    return round(float(_clamp01(score) * sarcasm_penalty), 4)


def _prepare_candidates_for_enrichment(ctx: "PipelineContext") -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    candidates = dedupe_by_time(list(ctx.raw_candidates or []), time_tol=_candidate_cache_tolerance_s())
    top_k = max(1, int(ctx.top_k or 1))
    budget_default = max(top_k * 3, top_k + 4)
    budget = max(top_k, _env_int("HS_SELECTOR_PRE_ENRICH_BUDGET", budget_default))
    strict_first = _env_bool("HS_ORCH_ENRICH_STRICT_FIRST", True)
    relaxed_cap = max(1, _env_int("HS_SELECTOR_RELAX_MAX_CANDIDATES", max(2, top_k)))
    reserved_relaxed = min(relaxed_cap, max(1, budget // 3))
    reserved_hooks = min(max(1, top_k // 2), max(1, budget // 4))

    strict_candidates: List[Dict[str, Any]] = []
    relaxed_candidates: List[Dict[str, Any]] = []
    hook_candidates: List[Dict[str, Any]] = []
    for cand in candidates:
        enriched = dict(cand)
        enriched["pre_enrich_score"] = _cheap_candidate_score(enriched)
        if bool(enriched.get("hook_seed")):
            hook_candidates.append(enriched)
        elif str(enriched.get("select_pass", "strict") or "strict") == "relaxed":
            relaxed_candidates.append(enriched)
        else:
            strict_candidates.append(enriched)

    strict_candidates.sort(key=lambda x: float(x.get("pre_enrich_score", x.get("score", 0.0)) or 0.0), reverse=True)
    relaxed_candidates.sort(
        key=lambda x: (
            float(x.get("pre_enrich_score", x.get("score", 0.0)) or 0.0),
            float(x.get("relaxed_readiness", x.get("score", 0.0)) or 0.0),
        ),
        reverse=True,
    )
    hook_candidates.sort(key=lambda x: float(x.get("pre_enrich_score", x.get("score", 0.0)) or 0.0), reverse=True)

    selected: List[Dict[str, Any]] = []
    if strict_first:
        strict_budget = min(len(strict_candidates), budget)
        selected.extend(strict_candidates[:strict_budget])
        remaining = max(0, budget - len(selected))
        if remaining > 0:
            selected.extend(relaxed_candidates[: min(reserved_relaxed, remaining)])
            remaining = max(0, budget - len(selected))
        if remaining > 0:
            selected.extend(hook_candidates[: min(reserved_hooks, remaining)])
    else:
        merged = sorted(
            strict_candidates + relaxed_candidates + hook_candidates,
            key=lambda x: float(x.get("pre_enrich_score", x.get("score", 0.0)) or 0.0),
            reverse=True,
        )
        selected = merged[:budget]

    if len(selected) < min(len(candidates), budget):
        existing_keys = {
            _normalized_candidate_cache_key(item, len(ctx.transcript or []))
            for item in selected
        }
        fallback_pool = strict_candidates + relaxed_candidates + hook_candidates
        for cand in fallback_pool:
            cache_key = _normalized_candidate_cache_key(cand, len(ctx.transcript or []))
            if cache_key in existing_keys:
                continue
            selected.append(cand)
            existing_keys.add(cache_key)
            if len(selected) >= min(len(candidates), budget):
                break

    pass_counts = Counter(str(c.get("select_pass", "strict") or "strict") for c in selected if not c.get("hook_seed"))
    return selected, {
        "budget": budget,
        "strict_first": 1 if strict_first else 0,
        "input_candidates": len(candidates),
        "strict_candidates": len(strict_candidates),
        "relaxed_candidates": len(relaxed_candidates),
        "hook_candidates": len(hook_candidates),
        "selected_candidates": len(selected),
        "selected_strict": int(pass_counts.get("strict", 0)),
        "selected_relaxed": int(pass_counts.get("relaxed", 0)),
        "selected_hooks": sum(1 for c in selected if c.get("hook_seed")),
        "filtered_out": max(0, len(candidates) - len(selected)),
    }


def enrich_candidate(candidate: Dict, aud: List[Dict], vis: List[Dict], brain, cache_bucket: Optional[Dict[str, Any]] = None) -> Dict:
    """Add audio/motion/brain/semantic fields to a candidate dict.
    Runs fast local fallbacks when heavy models are missing.
    """
    try:
        a_avg = _slice_mean(aud, 'energy', candidate['start'], candidate['end'])
        m_avg = _slice_mean(vis, 'motion', candidate['start'], candidate['end'])
    except Exception:
        a_avg = 0.0; m_avg = 0.0

    semantic_cache = cache_bucket if isinstance(cache_bucket, dict) else {}
    semantic_tuple = semantic_cache.get("semantic")
    if not semantic_tuple:
        try:
            semantic_tuple = _runtime_ultron_brain_score(candidate.get('text','') or '', brain)
        except Exception:
            semantic_tuple = (0.0, 0.0, 0.0, 0.0, 0.0)
        semantic_cache["semantic"] = semantic_tuple
    impact, meaning, novelty, emotion, clarity = semantic_tuple

    # fuse -> classic energy
    classic = fuse(0.05 + candidate.get('hook', 0.0), a_avg, m_avg)

    before_keys = {k: candidate.get(k) for k in ("audio", "motion", "impact", "meaning", "novelty", "emotion", "clarity", "classic")}
    candidate.update({
        'audio': round(a_avg, 4),
        'motion': round(m_avg, 4),
        'impact': round(impact, 4),
        'meaning': round(meaning, 4),
        'novelty': round(novelty, 4),
        'emotion': round(emotion, 4),
        'clarity': round(clarity, 4),
        'classic': round(classic, 4)
    })
    for _k, _before in before_keys.items():
        _after = candidate.get(_k)
        if _before != _after:
            _audit_field_mutation(candidate, _k, _before, _after, "enrich_candidate()", inspect.currentframe().f_lineno)

    # recalc a simple semantic_quality if not present
    if 'semantic_quality' not in candidate or candidate.get('semantic_quality') is None:
        try:
            from utils.narrative_intelligence import estimate_semantic_quality
            candidate['semantic_quality'] = round(float(estimate_semantic_quality(candidate.get('text',''), candidate.get('score',0.0))), 3)
        except Exception:
            candidate['semantic_quality'] = round(candidate.get('score', 0.0), 3)
        _audit_field_mutation(candidate, "semantic_quality", None, candidate.get("semantic_quality"), "enrich_candidate()", inspect.currentframe().f_lineno)

    return candidate

# -------------------------
# Validation gate (reusable)
# -------------------------
def _semantic_validation_rescue(candidate: Dict[str, Any], failure_reason: str) -> bool:
    signals = (candidate.get("signals", {}) or {})
    semantic = (signals.get("semantic", {}) or {})
    narrative = (signals.get("narrative", {}) or {})
    psychology = (signals.get("psychology", {}) or {})

    semantic_quality = max(0.0, min(1.0, float(semantic.get("semantic_quality", candidate.get("semantic_quality", 0.0)) or 0.0)))
    impact = max(0.0, min(1.0, float(semantic.get("impact", candidate.get("impact", 0.0)) or 0.0)))
    meaning = max(0.0, min(1.0, float(semantic.get("meaning", candidate.get("meaning", 0.0)) or 0.0)))
    clarity = max(0.0, min(1.0, float(semantic.get("clarity", candidate.get("clarity", 0.0)) or 0.0)))
    completion = max(0.0, min(1.0, float(narrative.get("completion_score", 0.0) or 0.0)))
    trigger_score = max(0.0, min(1.0, float(narrative.get("trigger_score", 0.0) or 0.0)))
    viral_density = max(0.0, min(1.0, float(candidate.get("viral_density", 0.0) or 0.0)))
    alignment = max(0.0, min(1.0, float(candidate.get("alignment_score", 0.0) or 0.0)))
    payoff_conf = max(0.0, min(1.0, float(psychology.get("payoff_confidence", candidate.get("payoff_confidence", 0.0)) or 0.0)))

    sarcasm_score = float(candidate.get("sarcasm_score", 0.0) or 0.0)
    content_penalty = float(candidate.get("content_shape_penalty", 0.0) or 0.0)

    semantic_strength = max(semantic_quality, (0.5 * impact) + (0.3 * meaning) + (0.2 * clarity))
    narrative_strength = max(completion, trigger_score, viral_density)
    explanation_strength = max(
        semantic_strength,
        (0.45 * meaning) + (0.35 * clarity) + (0.20 * impact),
    )

    if sarcasm_score >= 0.65 and failure_reason != "no_curve":
        return False
    if content_penalty >= 0.10 and semantic_strength < 0.72:
        return False

    if failure_reason == "no_curiosity_drop":
        return semantic_strength >= 0.56 and narrative_strength >= 0.40
    if failure_reason in {"payoff_low", "no_curve", "too_short_window", "no_curiosity_peak"}:
        return (
            explanation_strength >= 0.60
            and narrative_strength >= 0.42
            and (
                alignment >= 0.08
                or payoff_conf >= 0.35
                or impact >= 0.35
                or (meaning >= 0.72 and clarity >= 0.68)
            )
        )
    return False


def validate_candidate_by_curiosity(curve, start_t, end_t, payoff_conf, candidate=None, min_peak=0.22, payoff_conf_thresh=0.5) -> tuple[bool, str]:
    if payoff_conf is None or payoff_conf < payoff_conf_thresh:
        reason = 'payoff_low'
        if candidate and _semantic_validation_rescue(candidate, reason):
            return True, 'semantic_rescue'
        return False, reason
    if not curve or len(curve) < 3:
        reason = 'no_curve'
        if candidate and _semantic_validation_rescue(candidate, reason):
            return True, 'semantic_rescue'
        return False, reason
    window = [v for (t, v) in curve if start_t <= t <= end_t]
    if not window or len(window) < 3:
        reason = 'too_short_window'
        if candidate and _semantic_validation_rescue(candidate, reason):
            return True, 'semantic_rescue'
        return False, reason
    peak = max(window)
    if peak < min_peak:
        reason = 'no_curiosity_peak'
        if candidate and _semantic_validation_rescue(candidate, reason):
            return True, 'semantic_rescue'
        return False, reason
    if window[-1] > window[-2] + 0.02:
        reason = 'no_curiosity_drop'
        if candidate and _semantic_validation_rescue(candidate, reason):
            return True, 'semantic_rescue'
        return False, reason
    return True, 'ok'



def _record_stage(ctx: PipelineContext, stage: str, **stats: Any) -> None:
    ctx.stage_stats[stage] = stats
    compact = " ".join([f"{k}={v}" for k, v in stats.items()])
    log.info("[ORCH][%s] %s", stage, compact)


def _rank_score(candidate: Dict[str, Any], *keys: str) -> float:
    for key in keys:
        try:
            value = candidate.get(key, None)
        except Exception:
            value = None
        if value is not None:
            try:
                return float(value or 0.0)
            except Exception:
                continue
    return 0.0


def _candidate_origin(candidate: Dict[str, Any]) -> str:
    if bool(candidate.get("backfill")):
        return "backfill"
    if bool(candidate.get("hook_seed")):
        return "hook"
    return str(candidate.get("select_pass", "strict") or "strict")


def _semantic_explanation_strength(candidate: Dict[str, Any]) -> float:
    semantic = (candidate.get("signals", {}) or {}).get("semantic", {}) or {}
    impact = _clamp01(semantic.get("impact", candidate.get("impact", 0.0)))
    meaning = _clamp01(semantic.get("meaning", candidate.get("meaning", 0.0)))
    clarity = _clamp01(semantic.get("clarity", candidate.get("clarity", 0.0)))
    semantic_quality = _clamp01(semantic.get("semantic_quality", candidate.get("semantic_quality", 0.0)))
    return _clamp01(
        max(
            semantic_quality,
            (0.35 * impact) + (0.40 * meaning) + (0.25 * clarity),
        )
    )


def _should_backfill_candidates(ctx: "PipelineContext") -> bool:
    return _env_bool("HS_SMART_BACKFILL_ENABLED", True)


def _maybe_backfill_raw_candidates(ctx: "PipelineContext") -> None:
    t0 = time.time()
    if not _should_backfill_candidates(ctx):
        from viral_finder.system_observer import get_observer
        get_observer().log_stage("BACKFILL", 0, 0, 0.0)
        return
    target_min = max(0, int(ctx.target_min or 0))
    current = list(ctx.raw_candidates or [])
    if target_min <= 0 or len(current) >= target_min:
        from viral_finder.system_observer import get_observer
        get_observer().log_stage("BACKFILL", len(current), len(current), 0.0)
        return
    added = _smart_backfill_candidates(
        ctx.transcript or [],
        current,
        target_min=target_min,
        top_k=max(1, int(ctx.top_k or 1)),
        curiosity_candidates=ctx.curiosity_candidates or [],
    )
    if not added:
        from viral_finder.system_observer import get_observer
        get_observer().log_stage("BACKFILL", len(current), len(current), time.time() - t0)
        return
    ctx.raw_candidates = current + list(added)
    
    from viral_finder.system_observer import get_observer
    get_observer().log_stage(
        "BACKFILL",
        input_count=len(current),
        output_count=len(ctx.raw_candidates),
        wall_time=time.time() - t0,
        reject_reasons={"created": len(added)}
    )

    log.warning(
        "[ORCH-UNDERFLOW] raw_candidates=%d target_min=%d added_backfill=%d origins=%s",
        len(current),
        target_min,
        len(added),
        dict(sorted(Counter(_candidate_origin(c) for c in added).items())),
    )
    _record_stage(
        ctx,
        "L6C_SMART_BACKFILL",
        target_min=target_min,
        before=len(current),
        added=len(added),
        after=len(ctx.raw_candidates),
        origins=dict(sorted(Counter(_candidate_origin(c) for c in ctx.raw_candidates).items())),
    )


def _final_quality_rescue(candidate: Dict[str, Any]) -> bool:
    hard_reasons = set(_meaning_invariant_reject_reasons(candidate))
    loop_state = str(candidate.get("loop_state", "") or "")
    if hard_reasons or loop_state in ("NO_HOOK", "NO_PAYOFF"):
        return False
    semantic_strength = _semantic_explanation_strength(candidate)
    hook_metric = _clamp01(candidate.get("hook_score", candidate.get("hook_strength", 0.0)))
    payoff_metric = _clamp01(candidate.get("payoff_score", candidate.get("payoff_confidence", 0.0)))
    open_loop_metric = _clamp01(candidate.get("open_loop_score", 0.0))
    if hook_metric <= 0.02 and open_loop_metric <= 0.02:
        return False
    if payoff_metric <= 0.08 and loop_state not in ("RESOLVED", "CONTINUED"):
        return False
    if candidate.get("groq_moment") or candidate.get("cortex_enabled"):
        return True
    return semantic_strength >= 0.68 and (hook_metric >= 0.16 or open_loop_metric >= 0.14 or payoff_metric >= 0.22)


def _final_quality_reject_reasons(candidate: Dict[str, Any]) -> List[str]:
    reasons: List[str] = []
    reasons.extend(_meaning_invariant_reject_reasons(candidate))
    
    # Cortex-enabled candidates (LLM triggers/contracts) bypass all structural NLP rules.
    if candidate.get("groq_moment") or candidate.get("cortex_enabled"):
        return reasons
        
    loop_state = str(candidate.get("loop_state", "") or "")
    if loop_state == "NO_HOOK":
        reasons.append("loop_no_hook")
    elif loop_state == "NO_PAYOFF":
        reasons.append("loop_no_payoff")
    motion = _clamp01(candidate.get("motion", (candidate.get("signals", {}) or {}).get("engagement", {}).get("motion", 0.0)))
    hook_strength = _clamp01(candidate.get("hook_strength", candidate.get("hook_score", 0.0)))
    payoff_score = _clamp01(candidate.get("payoff_score", candidate.get("payoff_confidence", 0.0)))
    story_patterns = list(candidate.get("story_patterns") or [])
    arc_complete = bool(candidate.get("arc_complete", False))
    label = str(candidate.get("label", "") or "").lower()
    duration = float(candidate.get("duration", 0.0) or 0.0)
    hook_offset = float(candidate.get("hook_offset", 0.0) or 0.0)
    if hook_strength <= 0.02 and _clamp01(candidate.get("open_loop_score", 0.0)) <= 0.02:
        reasons.append("zero_hook_signal")
    if payoff_score < 0.32 and loop_state not in ("RESOLVED", "CONTINUED"):
        reasons.append("weak_unresolved_payoff")
    if (not arc_complete) and hook_strength < 0.20 and motion <= 0.02 and payoff_score < 0.15 and not story_patterns:
        reasons.append("flat_incomplete_arc")
    if "context" in label and payoff_score < 0.18 and hook_strength < 0.18 and not story_patterns:
        reasons.append("context_only_window")
    if duration >= 18.0 and payoff_score < 0.12 and hook_strength < 0.16 and hook_offset > 4.0:
        reasons.append("late_flat_hook")
    return reasons


def _resolve_contract_from_payoff(
    ctx: "PipelineContext",
    candidate: Dict[str, Any],
    *,
    hook_start: float,
    hook_trigger: Dict[str, Any],
    payoff_idx: Optional[int],
    payoff_seg: Dict[str, Any],
    resolution_score: float,
    payoff_source: str,
) -> Optional[Any]:
    """Reconcile late PayoffResolver truth back into the shared NCE contract list."""
    contracts = list(getattr(ctx, "narrative_contracts", []) or [])
    if not contracts or not payoff_seg:
        return None

    best = None
    best_dist = 999999.0
    for contract in contracts:
        c_hook_start = float(getattr(contract, "hook_start", 0.0) or 0.0)
        c_res = float(getattr(contract, "resolution_score", 0.0) or 0.0)
        if c_res > 0.0:
            continue
        dist = abs(c_hook_start - float(hook_start))
        if dist < best_dist:
            best = contract
            best_dist = dist

    if best is None or best_dist > 8.0:
        return None

    payoff_start = float(payoff_seg.get("start", 0.0) or 0.0)
    payoff_end = float(payoff_seg.get("end", payoff_start) or payoff_start)
    payoff_text = str(payoff_seg.get("text", "") or "")
    score = _clamp01(resolution_score)

    setattr(best, "payoff_trigger", {
        "type": "payoff",
        "start": payoff_start,
        "end": payoff_end,
        "text": payoff_text,
        "confidence": score,
        "source": payoff_source,
        "idx": payoff_idx,
    })
    setattr(best, "payoff_end", payoff_end)
    setattr(best, "resolution_score", round(float(score), 4))
    setattr(best, "contract_score", round(float(getattr(best, "debt_score", 0.0) or 0.0) * score, 4))
    setattr(best, "payoff_type", str(payoff_source or "payoff"))

    candidate["contract_seed"] = True
    candidate["_contract_trace_id"] = getattr(best, "trace_id", "")
    candidate["_contract_score"] = getattr(best, "contract_score", 0.0)
    candidate["completeness_signal"] = "RESOLVED"
    candidate["payoff_confidence"] = max(_clamp01(candidate.get("payoff_confidence", 0.0)), score)

    log.info(
        "[CONTRACT_RECONCILE] cid=%s hook_start=%.2f payoff_idx=%s source=%s resolution=%.3f contract_score=%.3f",
        candidate.get("cid", candidate.get("id", "?")),
        float(hook_start),
        payoff_idx,
        payoff_source,
        score,
        float(getattr(best, "contract_score", 0.0) or 0.0),
    )
    return best


def _pipeline_mode(explicit_mode: Optional[str]) -> str:
    mode = explicit_mode
    if mode is None:
        mode = os.getenv("HS_ORCH_PIPELINE_MODE", "staged")
    mode = str(mode or "staged").strip().lower()
    if mode not in ("staged", "legacy"):
        mode = "staged"
    return mode


def _run_transcription(ctx: PipelineContext) -> None:
    t0 = time.time()
    transcript = []
    source = "none"
    transcription_engine = "unknown"
    
    if ctx.use_cache:
        transcript = _load_cached_transcript(ctx.path) or []
        if transcript:
            source = "cache"
    
    if not transcript:
        # Apply intelligent routing (if available)
        if TRANSCRIPTION_ROUTER_AVAILABLE:
            try:
                apply_transcription_routing(ctx)
                transcription_engine = getattr(ctx, "transcription_engine", "unknown")
                log.info("[TRANSCRIPTION] Routing decision: engine=%s", transcription_engine)
            except Exception as e:
                log.warning("[TRANSCRIPTION] Router failed, using legacy mode: %s", e)

        force_runpod = os.getenv("HS_TRANSCRIPTION_FORCE_RUNPOD", "0").strip().lower() in ("1", "true", "yes", "on")
        local_gpu_available = False
        try:
            import torch  # type: ignore
            local_gpu_available = bool(torch.cuda.is_available())
        except Exception:
            local_gpu_available = False

        # If the router chose LOCAL_GPU (we're on the RunPod worker), skip the remote call.
        # Also skip if GPU is detected locally — no point calling RunPod from RunPod.
        engine_chosen = getattr(ctx, "transcription_engine", "unknown")
        runpod_required = force_runpod and not local_gpu_available and engine_chosen != "local_gpu"

        if runpod_required:
            try:
                from viral_finder.runpod_transcription import transcribe_local_media_path

                transcript = transcribe_local_media_path(ctx.path) or []
                source = "runpod"
                log.info("[TRANSCRIPTION] Completed via RunPod (segments=%d)", len(transcript))
            except Exception as e:
                if ctx.allow_fallback:
                    log.warning("[TRANSCRIPTION] RunPod failed: %s, trying local fallback", e)
                else:
                    raise
        
        allow_local_transcription = (not runpod_required) or bool(ctx.allow_fallback)
        if allow_local_transcription:
            # Execute transcription with fallback chain
            if not transcript and gemini_transcribe:
                try:
                    transcript = gemini_transcribe(ctx.path) or []
                    source = "gemini"
                    log.info("[TRANSCRIPTION] Completed via gemini (segments=%d)", len(transcript))
                except Exception as e:
                    log.warning("[TRANSCRIPTION] Gemini failed: %s, trying fallback", e)

            if not transcript and extract_transcript:
                try:
                    transcript = extract_transcript(ctx.path, prefer_gpu=ctx.prefer_gpu) or []
                    source = "legacy_extract"
                    log.info("[TRANSCRIPTION] Completed via extract_transcript (segments=%d)", len(transcript))
                except Exception as e:
                    log.warning("[TRANSCRIPTION] extract_transcript failed: %s, trying fallback", e)

            if not transcript and legacy_transcribe:
                try:
                    _model_name = os.getenv("WHISPER_MODEL", "small")
                    transcript = legacy_transcribe(ctx.path, _model_name, True) or []
                    source = "legacy_transcribe"
                    log.info("[TRANSCRIPTION] Completed via legacy_transcribe (segments=%d)", len(transcript))
                except Exception as e:
                    log.error("[TRANSCRIPTION] All engines failed: %s", e)

    
    if transcript and ctx.use_cache:
        _save_cached_transcript(ctx.path, transcript)
    
    ctx.transcript = transcript or []
    ctx.transcript_source = source
    
    _record_stage(
        ctx,
        "L1_TRANSCRIPTION",
        transcript_segments=len(ctx.transcript),
        source=source,
        engine=transcription_engine,
        reuse_cache=1 if source == "cache" else 0,
        wall_s=round(time.time() - t0, 3),
    )


def _run_av_features(ctx: PipelineContext) -> None:
    t0 = time.time()
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        future_audio = executor.submit(analyze_audio, ctx.path)
        future_visual = executor.submit(analyze_visual, ctx.path)
        
        try:
            ctx.audio_features = future_audio.result() or []
        except Exception:
            ctx.audio_features = []
            
        try:
            ctx.visual_features = future_visual.result() or []
        except Exception:
            ctx.visual_features = []

    ctx.av_features = {
        "audio": list(ctx.audio_features or []),
        "visual": list(ctx.visual_features or []),
    }
    _record_stage(
        ctx,
        "L2_AUDIO_VISUAL_FEATURES",
        audio_points=len(ctx.audio_features),
        visual_points=len(ctx.visual_features),
        wall_s=round(time.time() - t0, 3),
    )


def _run_semantic_scoring(ctx: PipelineContext) -> None:
    t0 = time.time()
    enable_semantic = _env_bool("HS_ENABLE_SEMANTIC_SCORING", True)
    if not enable_semantic:
        ctx.brain = None
        _record_stage(ctx, "L6_SEMANTIC_SCORING", brain_loaded=0, skipped="disabled", wall_s=round(time.time() - t0, 3))
        return
    if not (ctx.raw_candidates or []):
        ctx.brain = None
        _record_stage(ctx, "L6_SEMANTIC_SCORING", brain_loaded=0, skipped="no_candidates", wall_s=round(time.time() - t0, 3))
        return
    _ensure_brain_runtime_loaded()
    brain = None
    if _brain_import_ok:
        try:
            brain = _runtime_load_ultron_brain()
        except Exception as exc:
            log.warning("[ORCH] brain load failed: %s", exc)
            brain = None
    ctx.brain = brain
    # Stage-level semantic visibility (requested): explicit Ultron brain status in main orchestrator log.
    if brain is not None:
        log.info("[ORCH][ULTRON] semantic_runtime=ready model=ultron_brain")
    else:
        reason = _brain_import_error or "no_brain_runtime"
        log.info("[ORCH][ULTRON] semantic_runtime=degraded reason=%s fallback=heuristic", reason)
    _record_stage(
        ctx,
        "L6_SEMANTIC_SCORING",
        brain_loaded=1 if brain is not None else 0,
        wall_s=round(time.time() - t0, 3),
    )


def _run_curiosity(ctx: PipelineContext) -> None:
    t0 = time.time()
    if not analyze_curiosity_and_detect_punches and not run_curiosity_stage:
        ctx.curiosity_curve = []
        ctx.curiosity_candidates = []
        ctx.curiosity = {"curve": [], "candidates": []}
        _record_stage(ctx, "L3_CURIOSITY_ENGINE", candidates=0, wall_s=round(time.time() - t0, 3))
        return
    try:
        if run_curiosity_stage:
            payload = run_curiosity_stage(
                transcript=ctx.transcript,
                aud=ctx.audio_features,
                vis=ctx.visual_features,
                brain=ctx.brain,
            )
            ctx.curiosity_curve = payload.get("curve", []) or []
            ctx.curiosity_candidates = payload.get("candidates", []) or []
        else:
            _, curve, cands = analyze_curiosity_and_detect_punches(
                ctx.transcript,
                aud=ctx.audio_features,
                vis=ctx.visual_features,
                brain=ctx.brain,
            )
            if hasattr(curve, "tolist"):
                curve = curve.tolist()
            ctx.curiosity_curve = curve or []
            ctx.curiosity_candidates = cands or []
    except Exception as exc:
        log.warning("[ORCH] curiosity stage degraded: %s", exc)
        ctx.curiosity_curve = []
        ctx.curiosity_candidates = []
    ctx.curiosity = {
        "curve": list(ctx.curiosity_curve or []),
        "candidates": list(ctx.curiosity_candidates or []),
    }
    _record_stage(
        ctx,
        "L3_CURIOSITY_ENGINE",
        candidates=len(ctx.curiosity_candidates),
        curve_points=len(ctx.curiosity_curve),
        wall_s=round(time.time() - t0, 3),
    )


def _run_narrative_intelligence(ctx: PipelineContext) -> None:
    t0 = time.time()
    role_tags: List[str] = []
    role_paths: List[str] = []
    payoff_strength = 0.0
    narrative_samples: List[Dict[str, float]] = []

    if ctx.transcript:
        # ── Hindi / Hinglish keyword banks ──────────────────────────────────
        _HOOK_HI = (
            "kya aap jante hain", "kya aapko pata hai", "socho", "imagine karo",
            "kabhi socha", "aisa kyun", "ye kyun hota hai",
            "क्या आप जानते हैं", "क्या आपको पता है", "सोचो", "क्यों",
        )
        _PAYOFF_HI = (
            "isliye", "to baat ye hai", "yahi wajah hai", "yahi karan hai",
            "matlab ye hai", "seedhi baat", "sach ye hai", "asal mein",
            "yaad rakho", "akhir mein", "to samjho", "sach baat",
            "इसलिए", "तो बात ये है", "यही वजह है", "यही कारण है",
            "मतलब ये है", "सीधी बात", "सच ये है", "असल में",
            "याद रखो", "आखिरकार", "तो समझो",
        )
        _BUILD_HI = (
            "kyunki", "to", "phir", "uske baad", "aur phir", "jaise ki",
            "क्योंकि", "तो", "फिर", "उसके बाद", "और फिर", "जैसे कि",
        )
        # ────────────────────────────────────────────────────────────────────
        for seg in ctx.transcript:
            txt = str(seg.get("text", "") or "").lower()
            if (
                "?" in txt
                or any(k in txt for k in ("did you know", "what if", "ever wondered"))
                or any(k in txt for k in _HOOK_HI)
            ):
                role = "HOOK"
            elif (
                any(k in txt for k in ("that's why", "the point is", "in conclusion", "bottom line", "therefore"))
                or any(k in txt for k in _PAYOFF_HI)
            ):
                role = "PAYOFF"
            elif (
                any(k in txt for k in ("because", "so", "for example", "then", "next"))
                or any(k in txt for k in _BUILD_HI)
            ):
                role = "BUILD"
            else:
                role = "BUILD"
            role_tags.append(role)

        for r in role_tags:
            if not role_paths or role_paths[-1] != r:
                role_paths.append(r)

    groq_roles_map = {}
    if os.environ.get("HS_GROQ_NARRATIVE_ROLES", "0") == "1":
        try:
            from viral_finder.groq_cortex import analyze_narrative_roles
            groq_roles_map = analyze_narrative_roles(ctx.transcript or [])
        except Exception as e:
            log.warning(f"[ORCH][NARRATIVE] Failed to run Groq Narrative Roles: {e}")

    agreement_count = 0
    total_compared = 0
    groq_role_tags = []
    
    if ctx.transcript:
        for idx, seg in enumerate(ctx.transcript):
            legacy_role = role_tags[idx] if idx < len(role_tags) else "BUILD"
            groq_role = groq_roles_map.get(idx, legacy_role)  # fallback to legacy if groq missed it
            
            # Map simplified legacy tags to groq taxonomy for fair comparison
            normalized_legacy = "HOOK" if legacy_role == "HOOK" else ("PAYOFF" if legacy_role == "PAYOFF" else "BUILD")
            normalized_groq = "HOOK" if groq_role == "HOOK" else ("PAYOFF" if groq_role == "PAYOFF" else "BUILD")
            
            seg["legacy_role"] = legacy_role
            seg["groq_role"] = groq_role
            groq_role_tags.append(groq_role)
            
            if groq_roles_map and idx in groq_roles_map:
                total_compared += 1
                if normalized_legacy == normalized_groq:
                    agreement_count += 1
                else:
                    log.info(f"[NARRATIVE_COMPARE] Seg {idx} | Text: '{str(seg.get('text',''))[:40]}...' | Legacy: {legacy_role} vs Groq: {groq_role}")
    
    import random
    
    if ctx.transcript:
        log.info("[NARRATIVE_FORENSIC] --- Sampling 10 segments to verify Groq execution ---")
        sample_indices = random.sample(range(len(ctx.transcript)), min(10, len(ctx.transcript)))
        for i in sorted(sample_indices):
            seg = ctx.transcript[i]
            log.info(f"[NARRATIVE_FORENSIC] Seg {i:03d} | Legacy: {seg.get('legacy_role', 'N/A'):<6} | Groq: {seg.get('groq_role', 'N/A'):<8} | Text: {str(seg.get('text', ''))[:40]}...")
        log.info("[NARRATIVE_FORENSIC] ---------------------------------------------------")

    agreement_rate = (agreement_count / total_compared) if total_compared > 0 else 1.0
    if total_compared > 0:
        log.info(f"[NARRATIVE_COMPARE] Agreement Rate: {agreement_rate:.2%} ({agreement_count}/{total_compared})")
    else:
        log.warning("[NARRATIVE_COMPARE] Groq roles map was empty. Fallback to legacy occurred for 100% of segments.")

    # Performance-safe narrative summary: avoid expensive per-window quality scoring here.
    payoff_hints = []
    for cand in (ctx.curiosity_candidates or []):
        if isinstance(cand, dict):
            payoff_hints.append(float(cand.get("payoff_confidence", cand.get("payoff_conf", 0.0)) or 0.0))
            
    if payoff_hints:
        payoff_strength = sum(payoff_hints) / float(len(payoff_hints))
        groq_payoff_strength = payoff_strength
    else:
        payoff_strength = float(sum(1 for r in role_tags if r == "PAYOFF")) / float(max(1, len(role_tags)))
        groq_payoff_strength = float(sum(1 for r in groq_role_tags if r == "PAYOFF")) / float(max(1, len(groq_role_tags)))

    # Keep tiny sample for observability without heavy compute.
    narrative_samples = [
        {"role": role_tags[i], "groq_role": groq_role_tags[i] if i < len(groq_role_tags) else role_tags[i], "idx": float(i)}
        for i in range(0, min(len(role_tags), 12), max(1, len(role_tags) // 6 if len(role_tags) > 6 else 1))
    ]

    ctx.narrative = {
        "role_tags": role_tags,
        "groq_role_tags": groq_role_tags,
        "role_paths": role_paths,
        "payoff_strength": round(float(payoff_strength), 4),
        "groq_payoff_strength": round(float(groq_payoff_strength), 4),
        "samples": narrative_samples,
    }
    _record_stage(
        ctx,
        "L4_NARRATIVE_INTELLIGENCE",
        role_tags=len(role_tags),
        role_paths=len(role_paths),
        payoff_strength=round(float(payoff_strength), 4),
        groq_payoff_strength=round(float(groq_payoff_strength), 4),
        agreement_rate=round(agreement_rate, 4),
        wall_s=round(time.time() - t0, 3),
    )


def _run_narrative_trigger_stage(ctx: PipelineContext) -> None:
    t0 = time.time()
    triggers: List[Dict[str, Any]] = []
    if detect_narrative_triggers:
        try:
            triggers = detect_narrative_triggers(ctx.transcript or [])
        except Exception as exc:
            log.warning("[ORCH] narrative trigger stage degraded: %s", exc)
            triggers = []
    ctx.narrative_triggers = triggers
    dist: Dict[str, int] = {}
    for tr in triggers:
        k = str(tr.get("type", "unknown"))
        dist[k] = int(dist.get(k, 0)) + 1

    # ── Narrative Contract Engine ─────────────────────────────────────────────
    # Pair hooks with payoffs to detect complete psychological debt cycles.
    # Clips spanning a full contract get a contract_score boost in UVS.
    try:
        from viral_finder.narrative_trigger_engine import build_narrative_contracts
        ctx.narrative_contracts = build_narrative_contracts(triggers)
    except Exception as exc:
        log.warning("[NCE] Contract engine degraded: %s", exc)
        ctx.narrative_contracts = []
    # ─────────────────────────────────────────────────────────────────────────

    resolved = sum(1 for c in ctx.narrative_contracts if getattr(c, "resolution_score", 0) > 0)
    _record_stage(
        ctx,
        "L4_NARRATIVE_TRIGGER_ENGINE",
        triggers=len(triggers),
        belief_reversal=dist.get("belief_reversal", 0),
        secret_revelation=dist.get("secret_revelation", 0),
        mistake_explanation=dist.get("mistake_explanation", 0),
        strong_claim=dist.get("strong_claim", 0),
        contracts_resolved=resolved,
        contracts_total=len(ctx.narrative_contracts),
        wall_s=round(time.time() - t0, 3),
    )


def _overlap_ratio(a_s: float, a_e: float, b_s: float, b_e: float) -> float:
    inter = max(0.0, min(a_e, b_e) - max(a_s, b_s))
    if inter <= 0.0:
        return 0.0
    shorter = max(1e-6, min(a_e - a_s, b_e - b_s))
    return float(inter / shorter)


def _run_idea_graph(ctx: PipelineContext) -> None:
    t0 = time.time()
    nodes = []
    if build_idea_graph and ctx.transcript:
        try:
            nodes = build_idea_graph(
                ctx.transcript,
                aud=ctx.audio_features,
                vis=ctx.visual_features,
                curiosity_candidates=ctx.curiosity_candidates,
                narrative_triggers=ctx.narrative_triggers,
                brain=ctx.brain,
            ) or []
        except Exception as exc:
            log.warning("[ORCH] idea graph degraded: %s", exc)
            nodes = []
    ctx.idea_nodes = nodes
    _record_stage(ctx, "L5_IDEA_GRAPH", nodes=len(nodes), wall_s=round(time.time() - t0, 3))


def _run_candidate_generation(ctx: PipelineContext) -> None:
    t0 = time.time()
    candidates = []
    print("DEBUG select_candidate_clips =", select_candidate_clips)
    if select_candidate_clips and ctx.idea_nodes:
        try:
            candidates = select_candidate_clips(
                ctx.idea_nodes,
                top_k=ctx.top_k,
                transcript=ctx.transcript,
                ensure_sentence_complete=True,
                allow_multi_angle=True,
                min_target=max(1, int(ctx.target_min or ctx.top_k or 1)),
                diversity_mode="balanced",
            ) or []
        except Exception as exc:
            log.warning("[ORCH] candidate generation degraded: %s", exc)
            candidates = []
    ctx.raw_candidates = candidates
    pass_counts = Counter(str(c.get("select_pass", "strict") or "strict") for c in candidates if not c.get("hook_seed"))
    
    from viral_finder.system_observer import get_observer
    get_observer().log_stage(
        "CANDIDATE_GENERATION",
        input_count=len(ctx.idea_nodes or []),
        output_count=len(candidates),
        wall_time=time.time() - t0
    )

    _record_stage(
        ctx,
        "L5_CANDIDATE_GENERATION",
        produced=len(candidates),
        strict=int(pass_counts.get("strict", 0)),
        relaxed=int(pass_counts.get("relaxed", 0)),
        origins=dict(sorted(Counter(_candidate_origin(c) for c in candidates).items())),
        wall_s=round(time.time() - t0, 3),
    )


def _curiosity_peak_from_curve(curve: List, s: float, e: float) -> float:
    """Read peak curiosity value within [s, e] from the curiosity curve.
    Curve items can be (timestamp, value) tuples or bare float values (index = time).
    """
    window = []
    for i, item in enumerate(curve):
        if isinstance(item, (list, tuple)) and len(item) == 2:
            t, v = item
        else:
            t = float(i)
            v = item
        if float(s) <= float(t) <= float(e):
            window.append(float(v or 0.0))
    if not window:
        return 0.0
    return _clamp01(max(window))


def _inject_unmatched_trigger_candidates(ctx: "PipelineContext") -> None:
    """
    Guarantee every LLM trigger that has NO overlapping candidate becomes a clip.
    
    Algorithm:
    1. For each trigger, check if ANY existing candidate overlaps it.
    2. If not → it is "unmatched". Collect all unmatched triggers.
    3. Cluster nearby unmatched triggers (within 30s of each other).
    4. Per cluster: find sentence-aware START and END from transcript.
    5. Create a candidate with hook_seed=True and carry the trigger's psychology.
    """
    triggers = list(ctx.narrative_triggers or [])
    candidates = list(ctx.raw_candidates or [])
    transcript = list(ctx.transcript or [])
    if not triggers:
        return
    
    # Step 1: find unmatched triggers
    unmatched = []
    for tr in triggers:
        ts = float(tr.get("start", 0.0) or 0.0)
        te = float(tr.get("end", ts) or ts)
        matched = False
        for cand in candidates:
            cs = float(cand.get("start", 0.0) or 0.0)
            ce = float(cand.get("end", cs) or cs)
            if _overlap_ratio(ts, te, cs, ce) > 0.0:
                matched = True
                break
        if not matched:
            unmatched.append(tr)
    
    if not unmatched:
        log.info("[TRIGGER_INJECT] All triggers already covered by existing candidates.")
        return
    
    log.info(f"[TRIGGER_INJECT] {len(unmatched)} unmatched triggers → generating candidates")
    
    # Step 2: cluster by proximity (within 30s = likely same narrative passage)
    unmatched.sort(key=lambda t: float(t.get("start", 0.0)))
    clusters = []
    current_cluster = [unmatched[0]]
    for tr in unmatched[1:]:
        last_end = max(float(t.get("end", 0.0)) for t in current_cluster)
        if float(tr.get("start", 0.0)) - last_end <= 30.0:
            current_cluster.append(tr)
        else:
            clusters.append(current_cluster)
            current_cluster = [tr]
    clusters.append(current_cluster)
    
    new_candidates = []
    media_end = float(transcript[-1].get("end", 0.0)) if transcript else 9999.0
    
    for cluster in clusters:
        earliest_start = min(float(t.get("start", 0.0)) for t in cluster)
        latest_end = max(float(t.get("end", 0.0)) for t in cluster)
        
        # Sentence-aware START: walk backward to find prior sentence boundary
        best_start = earliest_start
        for seg in reversed(transcript):
            seg_end = float(seg.get("end", 0.0) or 0.0)
            seg_start = float(seg.get("start", 0.0) or 0.0)
            if seg_end > earliest_start:
                continue
            seg_text = str(seg.get("text", "") or "").strip()
            if seg_text.endswith(('.', '!', '?', '...')) or (earliest_start - seg_end) > 8.0:
                best_start = seg_start
                break
        
        # Sentence-aware END: walk forward to find payoff sentence boundary
        best_end = latest_end
        for seg in transcript:
            seg_start = float(seg.get("start", 0.0) or 0.0)
            seg_end = float(seg.get("end", 0.0) or 0.0)
            if seg_start < latest_end:
                continue
            seg_text = str(seg.get("text", "") or "").strip()
            best_end = seg_end
            if seg_text.endswith(('.', '!', '?', '...')) or (seg_end - latest_end) > 12.0:
                break
        
        clip_start = max(0.0, best_start)
        clip_end = min(media_end, best_end)
        
        # Pick best trigger in cluster (highest confidence) as representative
        best_trigger = max(cluster, key=lambda t: float(t.get("confidence", 0.0)))
        
        # Collect text in the clip window
        clip_text = " ".join(
            str(s.get("text", "")).strip()
            for s in transcript
            if float(s.get("start", 0.0)) >= clip_start and float(s.get("end", 0.0)) <= clip_end + 1.0
        ).strip()
        
        cand = {
            "start": round(clip_start, 2),
            "end": round(clip_end, 2),
            "text": clip_text,
            "score": float(best_trigger.get("confidence", 0.8)),
            "hook_seed": True,
            "hook_strength": float(best_trigger.get("confidence", 0.8)),
            "select_pass": "hook",
            "label": f"LLM Trigger: {best_trigger.get('type', 'strong_claim')}",
            "reason": best_trigger.get("reason", ""),
            "trigger_type": best_trigger.get("type", "strong_claim"),
            "_injected_from_trigger": True,
            "_trigger_cluster_size": len(cluster),
            "psychology": dict(best_trigger.get("psychology", {}) or {}),
            "_trigger_psychology": best_trigger.get("psychology", {}),
            "fingerprint": _fingerprint(clip_text, clip_start, clip_end),
            "cortex_enabled": True,  # Protect from structural rejection
        }
        
        # Preserve LLM intelligence for verifier and downstream
        psy = best_trigger.get("psychology", {})
        if psy:
            from viral_finder.cognition import IntelligenceArtifact, Evidence
            art = IntelligenceArtifact()
            for k, v in psy.items():
                if v:
                    art.evidence_stream.append(
                        Evidence(type=k, value=float(v), producer="trigger_forensic", confidence=float(best_trigger.get("confidence", 0.8)))
                    )
            cand["intelligence"] = art
        new_candidates.append(cand)
        log.info(f"[TRIGGER_INJECT] Created candidate {clip_start:.2f}-{clip_end:.2f} from {len(cluster)} trigger(s) [{best_trigger.get('type')}]")
    
    ctx.raw_candidates = list(ctx.raw_candidates or []) + new_candidates
    log.info(f"[TRIGGER_INJECT] Injected {len(new_candidates)} new trigger-sourced candidates. Total pool: {len(ctx.raw_candidates)}")

    # ── CONTRACT-BASED INJECTION: guarantee every resolved contract gets a clip ──
    # A resolved contract (hook → payoff pair) represents the most complete
    # psychological experience we know about. Inject it if not already covered.
    contract_candidates = []
    all_cands_now = list(ctx.raw_candidates or [])
    for contract in (ctx.narrative_contracts or []):
        res = getattr(contract, "resolution_score", 0.0)
        if res <= 0.0:
            continue  # unresolved hooks don't get injected here
        c_hook_start = getattr(contract, "hook_start", 0.0)
        c_payoff_end = getattr(contract, "payoff_end", 0.0)
        contract_window = c_payoff_end - c_hook_start
        if contract_window < 3.0:
            continue
        # Check if any existing candidate covers ≥60% of this contract window
        covered = False
        for cand in all_cands_now:
            cs = float(cand.get("start", 0.0) or 0.0)
            ce = float(cand.get("end", cs) or cs)
            overlap = max(0.0, min(ce, c_payoff_end) - max(cs, c_hook_start))
            if (overlap / contract_window) >= 0.60:
                covered = True
                break
        if covered:
            continue
        # Not covered — inject a contract-complete candidate
        # Sentence-aware boundaries
        c_start = c_hook_start
        for seg in reversed(transcript):
            seg_end = float(seg.get("end", 0.0) or 0.0)
            seg_text = str(seg.get("text", "") or "").strip()
            if seg_end > c_hook_start:
                continue
            if seg_text.endswith(('.', '!', '?', '...')) or (c_hook_start - seg_end) > 8.0:
                c_start = float(seg.get("start", 0.0))
                break
        c_end = c_payoff_end
        for seg in transcript:
            seg_start = float(seg.get("start", 0.0) or 0.0)
            seg_end = float(seg.get("end", 0.0) or 0.0)
            if seg_start < c_payoff_end:
                continue
            seg_text = str(seg.get("text", "") or "").strip()
            c_end = seg_end
            if seg_text.endswith(('.', '!', '?', '...')) or (seg_end - c_payoff_end) > 10.0:
                break
        c_start = max(0.0, c_start)
        c_end   = min(media_end, c_end)
        clip_text = " ".join(
            str(s.get("text", "")).strip()
            for s in transcript
            if float(s.get("start", 0.0)) >= c_start and float(s.get("end", 0.0)) <= c_end + 1.0
        ).strip()
        hook_psy = getattr(contract, "hook_trigger", {}).get("psychology", {}) or {}
        payoff_psy = getattr(contract, "payoff_trigger", {}).get("psychology", {}) or {}
        # Merge psychology: take max of hook + payoff for each dimension
        merged_psy = {k: max(float(hook_psy.get(k, 0.0)), float(payoff_psy.get(k, 0.0)))
                      for k in set(list(hook_psy.keys()) + list(payoff_psy.keys()))}
        cand = {
            "start": round(c_start, 2),
            "end": round(c_end, 2),
            "text": clip_text,
            "score": round(getattr(contract, "contract_score", 0.5), 4),
            "hook_seed": True,
            "contract_seed": True,   # ← marks this as a contract-complete injection
            "hook_strength": round(getattr(contract, "debt_score", 0.5), 4),
            "select_pass": "contract",
            "label": f"Contract: {getattr(contract, 'hook_type', '?')}→{getattr(contract, 'payoff_type', '?')}",
            "trigger_type": getattr(contract, "hook_type", "strong_claim"),
            "_injected_from_contract": True,
            "_contract_score": getattr(contract, "contract_score", 0.0),
            "_contract_trace_id": getattr(contract, "trace_id", ""),
            "psychology": dict(merged_psy),
            "_trigger_psychology": merged_psy,
            "fingerprint": _fingerprint(clip_text, c_start, c_end),
            "cortex_enabled": True,  # Protect from structural rejection
        }
        
        # Preserve LLM intelligence for verifier and downstream
        if merged_psy:
            from viral_finder.cognition import IntelligenceArtifact, Evidence
            art = IntelligenceArtifact()
            for k, v in merged_psy.items():
                if v:
                    art.evidence_stream.append(
                        Evidence(type=k, value=float(v), producer="trigger_forensic", confidence=1.0)
                    )
            cand["intelligence"] = art
        contract_candidates.append(cand)
        all_cands_now.append(cand)
        log.info(f"[NCE_INJECT] Contract candidate {c_start:.2f}-{c_end:.2f} "
                 f"[{getattr(contract, 'hook_type', '?')}→{getattr(contract, 'payoff_type', '?')}] "
                 f"contract_score={getattr(contract, 'contract_score', 0):.3f}")

    if contract_candidates:
        ctx.raw_candidates = list(ctx.raw_candidates or []) + contract_candidates
        log.info(f"[NCE_INJECT] Injected {len(contract_candidates)} contract-complete candidates. Total pool: {len(ctx.raw_candidates)}")
    # ─────────────────────────────────────────────────────────────────────────


def _run_global_hook_hunter(ctx: PipelineContext) -> None:
    t0 = time.time()

    # Kill switch: HS_HOOK_HUNTER=0 disables the entire stage
    if os.environ.get("HS_HOOK_HUNTER", "1").strip() == "0":
        log.info("[HOOK_HUNTER] disabled via HS_HOOK_HUNTER=0 — skipping")
        _record_stage(ctx, "L6B_GLOBAL_HOOK_HUNTER", scanned=0, strong_hooks=0, injected=0, wall_s=0.0)
        return

    transcript = list(ctx.transcript or [])
    existing = list(ctx.raw_candidates or [])
    if not transcript:
        _record_stage(ctx, "L6B_GLOBAL_HOOK_HUNTER", scanned=0, strong_hooks=0, injected=0, wall_s=round(time.time() - t0, 3))
        return


    debug_enabled = _env_bool("HS_HOOK_HUNTER_DEBUG", False)
    max_global_hooks = max(1, _env_int("HS_ORCH_MAX_GLOBAL_HOOKS", 20))
    hook_threshold = _env_float("HS_ORCH_GLOBAL_HOOK_THRESHOLD", 0.45)
    dedupe_tol = _env_float("HS_ORCH_GLOBAL_HOOK_DEDUPE_S", 2.0)
    hooks: List[Dict[str, Any]] = []
    # Deferred story-duplicate suppression: maps a discovered hook's trace_id to
    # the (thread, continuity, start, text, strength) it continues. Suppression is
    # applied later in the dedup/ranking stage — never at discovery time — so a
    # continuation decision can never prevent creation of a hook candidate.
    _susp_thread_by_trace: Dict[str, Any] = {}
    # STORY THREADS: the first stateful narrative primitive in HotShort.
    # Each StoryThread holds one open narrative contract (hook → payoff).
    # Before emitting a new candidate, we ask every active thread:
    #   "Does this segment continue you?"
    # If yes → suppress new candidate (same story, let existing arc grow).
    # If no  → create new thread (genuinely new story).
    # Threads expire when resolved OR when > horizon_s seconds old.
    _arc_horizon_s = _env_float("HS_HOOK_MEMORY_HORIZON_S", 120.0)
    _story_continuity_threshold = _env_float("HS_HOOK_STORY_CONTINUITY_THR", 0.30)
    _StoryThread = None
    try:
        from utils.narrative_intelligence import StoryThread as _StoryThread
    except Exception:
        pass
    active_story_threads: List[Any] = []   # List[StoryThread]

    def _curiosity_peak_for_window(s: float, e: float) -> float:
        curve = ctx.curiosity_curve or []
        window = []
        for i, item in enumerate(curve):
            # format: (timestamp, value)
            if isinstance(item, (list, tuple)) and len(item) == 2:
                t, v = item
            # format: value only
            else:
                t = float(i)
                v = item
            if float(s) <= float(t) <= float(e):
                window.append(float(v or 0.0))
        if not window:
            return 0.0
        return _clamp01(max(window))

    def _is_duplicate_seed(seed: Dict[str, Any], arr: List[Dict[str, Any]]) -> bool:
        s = float(seed.get("start", 0.0) or 0.0)
        e = float(seed.get("end", s) or s)
        for cand in arr:
            cs = float(cand.get("start", 0.0) or 0.0)
            ce = float(cand.get("end", cs) or cs)
            if abs(s - cs) <= dedupe_tol and abs(e - ce) <= dedupe_tol:
                return True
        return False

    for idx, seg in enumerate(transcript):
        seg_start = float(seg.get("start", 0.0) or 0.0)
        seg_end = float(seg.get("end", seg_start) or seg_start)
        if seg_end <= seg_start:
            continue
        seg_text = str(seg.get("text", "") or "").strip()
        cache_key = _normalized_candidate_cache_key({"start": seg_start, "end": seg_end, "text": seg_text}, len(transcript))
        cache_bucket = ctx.candidate_feature_cache.setdefault(cache_key, {})
        seg_scores = cache_bucket.get("narrative")
        if seg_scores is None:
            seg_scores = compute_quality_scores(transcript, seg_start, seg_end) if compute_quality_scores else {}
            cache_bucket["narrative"] = dict(seg_scores or {})
        hook_score = _clamp01(seg_scores.get("hook_score", 0.0))
        pattern_break_score = _clamp01(seg_scores.get("pattern_break_score", 0.0))
        open_loop_score = _clamp01(seg_scores.get("open_loop_score", 0.0))
        rewatch_score = _clamp01(seg_scores.get("rewatch_score", 0.0))
        semantic_quality = _clamp01(seg.get("semantic_quality", 0.0))
        curiosity_peak = _curiosity_peak_for_window(seg_start, seg_end)
        hook_strength = _clamp01(
            (0.35 * hook_score)
            + (0.25 * pattern_break_score)
            + (0.20 * open_loop_score)
            + (0.10 * curiosity_peak)
            + (0.10 * rewatch_score)
        )
        
        # --- Strict Hook Quality Gate ---
        _words = seg_text.lower().split()
        _is_garbage = False
        
        if len(_words) < 6:
            _is_garbage = True
            
        _first_word = _words[0].strip(".,!?\"'") if _words else ""
        _reject_starts = {"and", "but", "so", "because", "well", "sure", "oh", "like", "yeah", "yes", "no"}
        if _first_word in _reject_starts:
            # Only allow if it's a strong question like "But what if...?"
            if not ("what" in _words or "how" in _words or "?" in seg_text):
                _is_garbage = True
                
        if _is_garbage:
            # Drop unless the neural engine is absolutely certain it's a pattern break
            if hook_strength < 0.65 and pattern_break_score < 0.70:
                continue

        if hook_strength > hook_threshold or pattern_break_score > 0.40 or curiosity_peak > 0.45:

            # ── STORY MEMORY CLASSIFICATION (no suppression) ────────────────────
            # Ask every active StoryThread: "does this segment continue you?"
            # This is CLASSIFICATION ONLY. It records the hook→thread relationship
            # and grows the arc (add_development_point), but it MUST NOT prevent
            # creation of the hook candidate below. Story-duplicate suppression is
            # deferred to the dedup/ranking stage so that no valid hook hypothesis
            # is ever silently discarded at discovery time.
            # A thread only claims a segment if:
            #   1. It is not expired (resolved or > horizon_s old)
            #   2. compute_hook_resolution_bonus >= threshold
            _continuing_existing_arc = False
            _continuity_thread = None
            _continuity_score = 0.0
            if active_story_threads and compute_hook_resolution_bonus:
                # Prune expired threads first (resolved or timed out)
                _active_next = []
                for t in active_story_threads:
                    if t.is_expired(seg_start, _arc_horizon_s):
                        log.info("[STORY_THREAD_EXPIRED] %r", t)
                    else:
                        _active_next.append(t)
                active_story_threads = _active_next

                for _thread in active_story_threads:
                    _continuity = _thread.does_segment_continue(
                        seg_text, compute_hook_resolution_bonus, _story_continuity_threshold
                    )
                    if _continuity >= _story_continuity_threshold:
                        _continuing_existing_arc = True
                        _continuity_thread = _thread
                        _continuity_score = _continuity
                        log.info("[STORY_THREAD_CONTINUED] seg=%d '%.50s' continues %r", idx, seg_text, _thread)
                        # Grow the existing arc, but STILL create the independent
                        # hook candidate below. Suppression happens later.
                        _thread.add_development_point(seg_text, seg_start, _continuity)
                        break
            # ────────────────────────────────────────────────────────────────────

            # ── HOOK DISCOVERY (unconditional) ──────────────────────────────────
            # Every segment that clears the strength gate produces a hook
            # hypothesis, regardless of story-thread continuation. Continuation is
            # recorded as metadata (`story_duplicate`) for the dedup/ranking stage.
            if True:
                import uuid
                trace_id = str(uuid.uuid4())
                payload = {
                    "start": round(seg_start, 2),
                    "end": round(seg_end, 2),
                    "text": seg_text,
                    "score": round(float(hook_strength), 4),
                    "hook_seed": True,
                    "hook_strength": round(float(hook_strength), 4),
                    "semantic_quality": round(float(semantic_quality), 4),
                    "provenance": "L6B_GLOBAL_HOOK_HUNTER",
                    "trace_id": trace_id,
                    # Story-thread classification metadata (consumed by dedup stage).
                    "continues_thread": (_continuity_thread.trace_id if _continuity_thread else None),
                    "continuity_score": round(float(_continuity_score), 4),
                    "story_duplicate": bool(_continuing_existing_arc),
                }
                hooks.append(payload)
                if _continuing_existing_arc and _continuity_thread is not None:
                    # Defer the suppression bookkeeping/tracing to the dedup stage.
                    _susp_thread_by_trace[trace_id] = (
                        _continuity_thread, _continuity_score, seg_start, seg_text, hook_strength
                    )
                if os.environ.get("HS_TRACE_MODE", "false").strip().lower() == "true":
                    if trace_id not in ctx.trace_logs:
                        ctx.trace_logs[trace_id] = {
                            "identity": {},
                            "state_history": [],
                            "suppressed_children": [],
                            "events": []
                        }
                    ctx.trace_logs[trace_id]["identity"] = {
                        "hook": seg_text,
                        "start": round(seg_start, 2),
                        "birth_reason": {
                            "hook_score": round(hook_score, 4),
                            "pattern_break": round(pattern_break_score, 4),
                            "open_loop": round(open_loop_score, 4),
                            "curiosity_peak": round(curiosity_peak, 4),
                            "hook_strength": round(hook_strength, 4)
                        },
                        "state": "OPEN"
                    }
                    ctx.trace_state(trace_id, "OPEN")
                    ctx.trace_event(
                        trace_id=trace_id,
                        stage="HOOK_HUNTER",
                        event="CREATED",
                        changed=True,
                        impact="HIGH",
                        after={
                            "hook": seg_text,
                            "start": round(seg_start, 2)
                        }
                    )
                # Open a new StoryThread only for a genuinely-new hook. A
                # continuation already grew its parent thread above; the candidate
                # itself is still created and carried into the dedup stage.
                if _StoryThread and not _continuing_existing_arc:
                    _new_thread = _StoryThread(
                        hook_text=seg_text, start_s=seg_start, start_idx=idx, trace_id=trace_id
                    )
                    
                    # Infer Promise and Narrative Debt
                    from utils.narrative_intelligence import infer_narrative_promise_and_debt, build_contract
                    promise, debt, promise_type = infer_narrative_promise_and_debt(seg_text)
                    _new_thread.promise = promise
                    _new_thread.narrative_debt = debt
                    _new_thread.promise_type = promise_type
                    _new_thread.contract = build_contract(promise_type, seg_text)
                    
                    active_story_threads.append(_new_thread)
                    ctx.candidate_threads[trace_id] = _new_thread
                    log.info("[STORY_THREAD_CREATED] %r", _new_thread)
                    log.info("[NEW_HOOK_ALLOWED] seg=%d text='%.50s'", idx, seg_text)
                if debug_enabled and (len(hooks) <= 8 or hook_strength >= 0.65):
                    log.info('[HOOK] idx=%d strength=%.2f text="%s"', idx, hook_strength, seg_text[:120])

    # ── DEDUP / RANKING STAGE ───────────────────────────────────────────────
    # Discovery is complete: every hook hypothesis that cleared the strength gate
    # now exists in `hooks`, including story-continuations. Suppression happens
    # HERE, never at discovery, so a continuation decision can never prevent a
    # candidate from being created. Two independent dedup gates:
    #   1. story_duplicate    → same narrative arc (semantic continuation)
    #   2. _is_duplicate_seed → same time window as an existing candidate
    # The max_global_hooks cap is applied to INJECTED independent hooks (not to the
    # pre-dedup list) so a suppressed duplicate can never consume a slot and thereby
    # silently discard a real, independent hook.
    hooks = sorted(hooks, key=lambda x: float(x.get("hook_strength", x.get("score", 0.0)) or 0.0), reverse=True)
    injected: List[Dict[str, Any]] = []
    seen = list(existing)
    for hook in hooks:
        if hook.get("story_duplicate"):
            # Deferred story-duplicate suppression (moved here from discovery).
            ctx.hooks_suppressed += 1
            _susp = _susp_thread_by_trace.get(hook.get("trace_id"))
            if _susp:
                _thread, _cscore, _sstart, _stext, _sstrength = _susp
                log.info(
                    "[HOOK_SUPPRESSED_BY_MEMORY]\n"
                    "segment_text: %s\n"
                    "continuity_score: %.2f\n"
                    "thread_id: %s\n"
                    "thread_start: %.1f",
                    _stext, _cscore, id(_thread), _thread.start_s
                )
                if _thread.trace_id:
                    ctx.trace_suppressed_child(
                        trace_id=_thread.trace_id,
                        start=_sstart,
                        text=_stext,
                        score=_sstrength,
                        reason=f"continuity={_cscore:.2f}"
                    )
                    ctx.trace_event(
                        trace_id=_thread.trace_id,
                        stage="STORY_MEMORY",
                        event="SUPPRESSED_CHILD",
                        changed=True,
                        impact="CRITICAL",
                        before={"suppressed_children_count": len(ctx.trace_logs.get(_thread.trace_id, {}).get("suppressed_children", [])) - 1},
                        after={"suppressed_children_count": len(ctx.trace_logs.get(_thread.trace_id, {}).get("suppressed_children", [])), "suppressed_text": _stext}
                    )
                    ctx.trace_state(_thread.trace_id, "CONTINUED")
            continue
        if len(injected) >= max_global_hooks:
            # Ranking cap reached for independent hooks; keep scanning only so
            # remaining story-duplicates are still counted/traced above.
            continue
        if _is_duplicate_seed(hook, seen):
            continue
        # Strip the internal-only classification flag before the candidate enters
        # the downstream pipeline.
        hook.pop("story_duplicate", None)
        injected.append(hook)
        seen.append(hook)

    if injected:
        ctx.raw_candidates = list(existing) + injected
    log.info(
        "[HOOK-HUNTER] scanned=%d discovered=%d injected=%d suppressed_story_dupes=%d",
        len(transcript), len(hooks), len(injected), ctx.hooks_suppressed
    )

    from viral_finder.system_observer import get_observer
    get_observer().log_stage(
        "HOOK_HUNTER",
        input_count=len(existing),
        output_count=len(ctx.raw_candidates or []),
        wall_time=time.time() - t0
    )

    _record_stage(
        ctx,
        "L6B_GLOBAL_HOOK_HUNTER",
        scanned=len(transcript),
        strong_hooks=len(hooks),
        injected=len(injected),
        wall_s=round(time.time() - t0, 3),
    )


def _clamp01(x: Any) -> float:
    try:
        v = float(x or 0.0)
    except Exception:
        v = 0.0
    return max(0.0, min(1.0, v))


def _estimate_insight_count(text: str) -> int:
    t = str(text or "").strip()
    if not t:
        return 0
    sentence_like = [p for p in re.split(r"[.!?]+", t) if p.strip()]
    if sentence_like:
        return max(1, len(sentence_like))
    clauses = [p for p in re.split(r",|;| but | because | so | therefore | and ", t.lower()) if p.strip()]
    return max(1, len(clauses) // 2)


def _extract_narrative_scores(transcript: List[Dict[str, Any]], cand: Dict[str, Any]) -> Dict[str, float]:
    cache_obj = cand.get("_feature_cache")
    cache = cache_obj if isinstance(cache_obj, dict) else None
    if not compute_quality_scores:
        return {}
    try:
        s = float(cand.get("start", 0.0) or 0.0)
        e = float(cand.get("end", s) or s)
        if not transcript or e <= s:
            return {}
        if cache is not None and "narrative" in cache:
            return dict(cache["narrative"])
        payload = compute_quality_scores(transcript, s, e) or {}
        norm = {k: _clamp01(v) for k, v in payload.items() if isinstance(v, (int, float))}
        if cache is not None:
            cache["narrative"] = dict(norm)
        return norm
    except Exception:
        return {}


def _narrative_completion_score(cand: Dict[str, Any], narrative_scores: Optional[Dict[str, float]] = None) -> float:
    text = str(cand.get("text", "") or "").strip()
    narrative_scores = narrative_scores or {}
    payoff = _clamp01(cand.get("payoff_confidence", 0.0) or narrative_scores.get("payoff_resolution_score", 0.0))
    sentence_complete = 1.0 if text.endswith((".", "!", "?")) else 0.45
    label = str(cand.get("label", "") or "").lower()
    has_payoff_role = 1.0 if any(k in label for k in ("payoff", "revealing", "punch", "insight", "resolution")) else 0.35
    ending_strength = _clamp01(narrative_scores.get("ending_strength", 0.0))
    return _clamp01((0.25 * sentence_complete) + (0.35 * payoff) + (0.20 * has_payoff_role) + (0.20 * ending_strength))


def _run_enrichment(ctx: PipelineContext) -> None:
    t0 = time.time()
    out = []
    enable_alignment = _env_bool("HS_ENABLE_ALIGNMENT_SCORING", True)
    enable_tension_gradient = _env_bool("HS_ENABLE_TENSION_GRADIENT", True)
    enable_viral_density = _env_bool("HS_ENABLE_VIRAL_DENSITY", True)
    selected_candidates, budget_stats = _prepare_candidates_for_enrichment(ctx)
    narrative_cache_hits = 0
    semantic_cache_hits = 0
    for c in selected_candidates:
        cand = dict(c)
        cache_key = _normalized_candidate_cache_key(cand, len(ctx.transcript or []))
        cache_bucket = ctx.candidate_feature_cache.setdefault(cache_key, {})
        if "narrative" in cache_bucket:
            narrative_cache_hits += 1
        if "semantic" in cache_bucket:
            semantic_cache_hits += 1
        cand["_feature_cache"] = cache_bucket
        cand_start = float(cand.get("start", 0.0) or 0.0)
        cand_end = float(cand.get("end", cand_start) or cand_start)
        overlapping_triggers = []
        for tr in (ctx.narrative_triggers or []):
            ts = float(tr.get("start", 0.0) or 0.0)
            te = float(tr.get("end", ts) or ts)
            if _overlap_ratio(cand_start, cand_end, ts, te) > 0.0:
                overlapping_triggers.append(tr)
        if overlapping_triggers:
            media_end = float(ctx.transcript[-1].get("end", cand_end) or cand_end) if ctx.transcript else cand_end
            transcript = ctx.transcript or []
            
            # ── Sentence-aware START: walk BACKWARD to find sentence boundary ──────
            earliest_trigger_start = min(float(t.get("start", cand_start)) for t in overlapping_triggers)
            best_start = earliest_trigger_start
            for seg in reversed(transcript):
                seg_end = float(seg.get("end", 0.0) or 0.0)
                seg_start = float(seg.get("start", 0.0) or 0.0)
                if seg_end > earliest_trigger_start:
                    continue
                # Found a segment that ends just before the trigger
                seg_text = str(seg.get("text", "") or "").strip()
                # Accept as start if it ends a sentence (good boundary) OR if we are within 8s
                if seg_text.endswith(('.', '!', '?', '...')) or (earliest_trigger_start - seg_end) > 8.0:
                    best_start = seg_start
                    break
            cand_start = max(0.0, best_start)
            
            # ── Sentence-aware END: walk FORWARD to find payoff/sentence resolution ─
            latest_trigger_end = max(float(t.get("end", cand_end)) for t in overlapping_triggers)
            best_end = latest_trigger_end
            for seg in transcript:
                seg_start = float(seg.get("start", 0.0) or 0.0)
                seg_end = float(seg.get("end", 0.0) or 0.0)
                if seg_start < latest_trigger_end:
                    continue
                # Walk forward: stop at the first proper sentence boundary after trigger end
                seg_text = str(seg.get("text", "") or "").strip()
                best_end = seg_end
                if seg_text.endswith(('.', '!', '?', '...')) or (seg_end - latest_trigger_end) > 12.0:
                    break
            cand_end = min(media_end, best_end)
            
            log.info(f"[CLIP_BOUNDARY] Trigger-aware: {cand_start:.2f}-{cand_end:.2f} (trigger_span={earliest_trigger_start:.2f}-{latest_trigger_end:.2f})")
            
            cand["start"] = round(cand_start, 2)
            cand["end"] = round(max(cand_start + 0.01, cand_end), 2)
            cache_key = _normalized_candidate_cache_key(cand, len(ctx.transcript or []))
            cache_bucket = ctx.candidate_feature_cache.setdefault(cache_key, cache_bucket)

        cand.setdefault("score_base", float(cand.get("score", 0.0) or 0.0))
        cand = enrich_candidate(cand, ctx.audio_features, ctx.visual_features, ctx.brain, cache_bucket=cache_bucket)
        semantic_quality = float(cand.get("semantic_quality", cand.get("score_base", 0.0)) or 0.0)
        score_enriched = (
            0.40 * float(cand.get("impact", 0.0) or 0.0) +
            0.22 * float(cand.get("classic", 0.0) or 0.0) +
            0.20 * float(cand.get("meaning", 0.0) or 0.0) +
            0.18 * semantic_quality
        )
        cand["score_enriched"] = round(float(score_enriched), 4)
        
        # FIX3: DECISION TIMELINE — initialize and record first score
        _timeline = cand.setdefault("decision_timeline", [])
        _timeline.append({
            "stage": "ENRICHMENT",
            "event": "Base Score Enriched",
            "reason": "Combined impact, classic, meaning, and semantic_quality",
            "score": round(float(score_enriched), 4)
        })
        curiosity_at_start = _clamp01((cand.get("metrics", {}) or {}).get("curiosity_at_start", cand.get("curiosity", 0.0)))
        curiosity_peak = _clamp01((cand.get("metrics", {}) or {}).get("curiosity_peak", cand.get("curiosity", 0.0)))

        # ── FIX: Curiosity curve fallback for hook/inject candidates ─────────────
        # Hook Hunter and injected trigger candidates come in AFTER the curiosity
        # pass, so their cand["metrics"]["curiosity_peak"] is always 0.0.
        # Fall back to reading the actual curiosity curve for their time window.
        if curiosity_peak == 0.0 and ctx.curiosity_curve:
            curve_peak = _curiosity_peak_from_curve(ctx.curiosity_curve, cand_start, cand_end)
            if curve_peak > 0.0:
                curiosity_peak = curve_peak
                curiosity_at_start = _curiosity_peak_from_curve(
                    ctx.curiosity_curve, cand_start, min(cand_start + 2.0, cand_end)
                )
                log.info(f"[CURIOSITY_FALLBACK] {cand.get('cid','?')} {cand_start:.2f}-{cand_end:.2f}: curve_peak={curiosity_peak:.3f}")
        # ─────────────────────────────────────────────────────────────────────────

        tension_gradient = _clamp01(max(0.0, curiosity_peak - curiosity_at_start)) if enable_tension_gradient else 0.0
        payoff_conf = _clamp01(cand.get("payoff_confidence", 0.0))
        impact = _clamp01(cand.get("impact", 0.0))
        engagement_energy = _clamp01(cand.get("classic", 0.0))
        narrative_scores = _extract_narrative_scores(ctx.transcript, cand)
        alignment_score = (
            _clamp01(curiosity_peak * payoff_conf * impact * engagement_energy)
            if enable_alignment
            else 0.0
        )
        narrative_completion = _narrative_completion_score(cand, narrative_scores=narrative_scores)
        duration_s = max(0.01, float(cand.get("end", 0.0) or 0.0) - float(cand.get("start", 0.0) or 0.0))
        insight_count = _estimate_insight_count(str(cand.get("text", "") or ""))
        trigger_conf = max([float(t.get("confidence", 0.0) or 0.0) for t in overlapping_triggers], default=0.0)
        trigger_types = [str(t.get("type", "")) for t in overlapping_triggers if t.get("type")]

        # ── FIX: Completeness from transcript sentence boundaries ─────────────────
        # ending_strength / completion_score previously came from narrative payoff
        # engine which returns ~0.006 for most transcripts. Compute a real heuristic:
        # does the clip's last transcript segment end a sentence?
        transcript_segs = ctx.transcript or []
        clip_end_time = float(cand.get("end", cand_end))
        last_seg_in_clip = None
        for _seg in transcript_segs:
            _seg_start = float(_seg.get("start", 0.0) or 0.0)
            _seg_end = float(_seg.get("end", 0.0) or 0.0)
            if _seg_start <= clip_end_time and _seg_end <= clip_end_time + 1.5:
                last_seg_in_clip = _seg
        if last_seg_in_clip:
            _last_text = str(last_seg_in_clip.get("text", "") or "").strip()
            ends_sentence = _last_text.endswith(('.', '!', '?', '...', '."', '!"', '?"'))
            completion_heuristic = 0.82 if ends_sentence else 0.45
        else:
            completion_heuristic = 0.50
        # Merge with any existing narrative signals (take max)
        if narrative_scores:
            narrative_scores["completion_score"] = max(
                float(narrative_scores.get("completion_score", 0.0)),
                completion_heuristic
            )
            narrative_scores["ending_strength"] = max(
                float(narrative_scores.get("ending_strength", 0.0)),
                completion_heuristic * 0.8
            )
        else:
            narrative_scores = {
                "completion_score": completion_heuristic,
                "ending_strength": completion_heuristic * 0.8,
            }
        # ─────────────────────────────────────────────────────────────────────────

        weighted_triggers = 0.0
        trigger_bonus = 0.0
        for t_type in trigger_types:
            if t_type == "complete_thought":
                weighted_triggers += 2.0
                trigger_bonus = max(trigger_bonus, 0.4)
            elif t_type == "payoff":
                weighted_triggers += 1.8
                trigger_bonus = max(trigger_bonus, 0.3)
            elif t_type == "belief_reversal":
                weighted_triggers += 1.0
                trigger_bonus = max(trigger_bonus, 0.2)
            else:
                weighted_triggers += 1.0

        psy = dict(cand.get("psychology_scores", cand.get("psychology", {})))
        trigger_psy = cand.get("_trigger_psychology", {})
        if isinstance(trigger_psy, dict):
            for key, raw_val in trigger_psy.items():
                try:
                    val = float(raw_val)
                    if val > float(psy.get(key, 0.0) or 0.0):
                        psy[key] = val
                except (ValueError, TypeError):
                    continue
        psy.update({
            "curiosity": float(cand.get("curiosity", 0.0) or 0.0),
            "curiosity_peak": curiosity_peak,
            "curiosity_start": curiosity_at_start,
            "punch_confidence": float(cand.get("punch_confidence", 0.0) or 0.0),
            "payoff_confidence": payoff_conf,
            "tension_gradient": tension_gradient,
        })

        # ── INTELLIGENCE TRANSPORT BRIDGE ────────────────────────────────────────
        # Read Evidence from IntelligenceArtifact and merge into psy scoring dict.
        # Marking each Evidence as CONSUMED so the transport verifier can track it.
        # Without this bridge, evidence_stream packets produced by groq_cortex are
        # orphaned — generated but never influencing any decision.
        if isinstance(cand.get("intelligence"), IntelligenceArtifact):
            signals_ref = cand.setdefault("signals", {})
            signals_ref["psychology"] = psy
            _bridge_intelligence_to_signals([cand], "signal_enrichment")
            psy = signals_ref.get("psychology", psy)
        # ─────────────────────────────────────────────────────────────────────────
        
        # Attach TriggerArtifacts to Candidate
        import dataclasses
        artifacts_list = []
        for t in overlapping_triggers:
            if "artifact" in t:
                art = t["artifact"]
                # Convert dataclass to dict to avoid "Object of type TriggerArtifact is not JSON serializable"
                if dataclasses.is_dataclass(art):
                    artifacts_list.append(dataclasses.asdict(art))
                elif hasattr(art, "__dict__"):
                    artifacts_list.append(vars(art))
                else:
                    artifacts_list.append(art)
                    
                conf = max(0.0, float(getattr(art, "confidence", 0.0)))
                
                # Confidence-weighted aggregation
                psy_dict = getattr(art, "psychology", {})
                t_type = getattr(art, "trigger_type", "unknown")
                for key, raw_val in psy_dict.items():
                    try:
                        val = float(raw_val) * conf
                        if val > psy.get(key, 0.0):
                            log.info(f"[TRACE] Trigger({t_type}) -> {key}={raw_val} (conf={conf}) -> Candidate({cand.get('cid','?')}) -> Enrichment(effective={val:.3f}) -> Ranking")
                            psy[key] = val
                    except (ValueError, TypeError):
                        pass
                        
        if "artifacts" not in cand:
            cand["artifacts"] = {}
        cand["artifacts"]["triggers"] = artifacts_list
        
        trigger_density = float(weighted_triggers) / max(1.0, duration_s / 6.0)
        trigger_density = _clamp01(trigger_density)
        narrative_density = _clamp01(narrative_scores.get("information_density_score", 0.0))
        viral_density = _clamp01(
            min(1.0, (float(insight_count) / max(1.0, duration_s)) * 0.65 + (narrative_density * 0.35))
        ) if enable_viral_density else 0.0
        surprise_factor = _clamp01(max(cand.get("novelty", 0.0), narrative_scores.get("pattern_break_score", 0.0)))
        cand["signals"] = {
            "psychology": psy,
            "semantic": {
                "impact": float(cand.get("impact", 0.0) or 0.0),
                "meaning": float(cand.get("meaning", 0.0) or 0.0),
                "novelty": float(cand.get("novelty", 0.0) or 0.0),
                "clarity": float(cand.get("clarity", 0.0) or 0.0),
                "semantic_quality": semantic_quality,
                "surprise_factor": surprise_factor,
                "insight_count": insight_count,
            },
            "narrative": {
                "label": cand.get("label"),
                "reason": cand.get("reason"),
                "completion_score": narrative_completion,
                "trigger_type": trigger_types[0] if trigger_types else None,
                "trigger_score": _clamp01(trigger_conf + trigger_bonus),
                "trigger_density": trigger_density,
                "hook_score": float(narrative_scores.get("hook_score", 0.0) or 0.0),
                "open_loop_score": float(narrative_scores.get("open_loop_score", 0.0) or 0.0),
                "ending_strength": float(narrative_scores.get("ending_strength", 0.0) or 0.0),
                "payoff_resolution_score": float(narrative_scores.get("payoff_resolution_score", 0.0) or 0.0),
                "rewatch_score": float(narrative_scores.get("rewatch_score", 0.0) or 0.0),
                "virality_confidence": float(narrative_scores.get("virality_confidence", 0.0) or 0.0),
                "final_score": float(narrative_scores.get("final_score", 0.0) or 0.0),
            },
            "engagement": {
                "audio": float(cand.get("audio", 0.0) or 0.0),
                "motion": float(cand.get("motion", 0.0) or 0.0),
                "classic": engagement_energy,
                "energy": engagement_energy,
            },
        }
        cand["alignment_score"] = alignment_score
        cand["viral_density"] = viral_density
        cand["duration_s"] = duration_s
        cand.pop("_feature_cache", None)
        cand["provenance"] = {"stage": "L7_SIGNAL_ENRICHMENT"}
        out.append(cand)
    # Aggregated Ultron semantic output summary into orchestrator logs.
    if out:
        sem_impacts = [float((x.get("signals", {}).get("semantic", {}) or {}).get("impact", 0.0) or 0.0) for x in out]
        sem_meanings = [float((x.get("signals", {}).get("semantic", {}) or {}).get("meaning", 0.0) or 0.0) for x in out]
        sem_novelties = [float((x.get("signals", {}).get("semantic", {}) or {}).get("novelty", 0.0) or 0.0) for x in out]
        sem_clarities = [float((x.get("signals", {}).get("semantic", {}) or {}).get("clarity", 0.0) or 0.0) for x in out]
        n = float(max(1, len(out)))
        log.info(
            "[ORCH][ULTRON] semantic_batch candidates=%d avg(impact=%.3f meaning=%.3f novelty=%.3f clarity=%.3f)",
            len(out),
            sum(sem_impacts) / n,
            sum(sem_meanings) / n,
            sum(sem_novelties) / n,
            sum(sem_clarities) / n,
        )
    ctx.enriched_candidates = out
    _record_stage(
        ctx,
        "L7_SIGNAL_ENRICHMENT",
        produced=len(out),
        input_candidates=int(budget_stats.get("input_candidates", len(ctx.raw_candidates or []))),
        selected_candidates=int(budget_stats.get("selected_candidates", len(selected_candidates))),
        selected_strict=int(budget_stats.get("selected_strict", 0)),
        selected_relaxed=int(budget_stats.get("selected_relaxed", 0)),
        selected_hooks=int(budget_stats.get("selected_hooks", 0)),
        filtered_out=int(budget_stats.get("filtered_out", 0)),
        narrative_cache_hits=narrative_cache_hits,
        semantic_cache_hits=semantic_cache_hits,
        avg_alignment=round(sum(float(c.get("alignment_score", 0.0) or 0.0) for c in out) / float(max(1, len(out))), 4),
        signal_completeness_ratio=round(
            sum(1 for c in out if all(k in c.get("signals", {}) for k in ("psychology", "semantic", "narrative", "engagement")))
            / float(max(1, len(out))),
            3,
        ),
        wall_s=round(time.time() - t0, 3),
    )


def _run_insight_detector(ctx: PipelineContext) -> None:
    t0 = time.time()
    debug_enabled = _env_bool("HS_INSIGHT_DEBUG", False)
    found = 0
    out = []
    for idx, cand in enumerate(ctx.enriched_candidates or []):
        c = dict(cand or {})
        sig = c.get("signals", {}) or {}
        sem = sig.get("semantic", {}) or {}
        nar = sig.get("narrative", {}) or {}
        semantic_quality = _clamp01(sem.get("semantic_quality", 0.0))
        information_density = _clamp01(nar.get("information_density_score", 0.0))
        clarity = _clamp01(sem.get("clarity", 0.0))
        novelty = _clamp01(sem.get("novelty", 0.0))
        rewatch_score = _clamp01(nar.get("rewatch_score", 0.0))
        insight_strength = _clamp01(
            (0.40 * semantic_quality)
            + (0.20 * information_density)
            + (0.20 * clarity)
            + (0.10 * novelty)
            + (0.10 * rewatch_score)
        )
        is_insight = (
            (semantic_quality > 0.60 and information_density > 0.25)
            or (insight_strength > 0.55)
        )
        c["insight_candidate"] = bool(is_insight)
        c["insight_strength"] = round(float(insight_strength), 4)
        if is_insight:
            found += 1
            if debug_enabled and (found <= 12 or insight_strength >= 0.70):
                log.info("[INSIGHT] idx=%d strength=%.2f", idx, insight_strength)
        out.append(c)
    ctx.enriched_candidates = out
    log.info("[INSIGHT-DETECTOR] found=%d", found)
    _record_stage(
        ctx,
        "L8B_INSIGHT_DETECTOR",
        found=found,
        scanned=len(out),
        wall_s=round(time.time() - t0, 3),
    )


def _run_validation(ctx: PipelineContext) -> None:
    t0 = time.time()
    min_peak_raw = os.getenv("HS_ORCH_VALIDATION_MIN_SCORE", os.getenv("HS_ORCH_MIN_CURIOSITY_PEAK", "0.08"))
    min_peak = float(min_peak_raw or 0.08)
    payoff_conf_thresh = float(os.getenv("HS_ORCH_PAYOFF_CONF", "0.15") or 0.15)
    enriched_before_validation = list(ctx.enriched_candidates or [])
    _audit_stage_snapshot("VALIDATION_IN", enriched_before_validation)
    if apply_post_enrichment_validation:
        accepted, rejected = apply_post_enrichment_validation(
            ctx.enriched_candidates or [],
            curve=ctx.curiosity_curve,
            min_peak=min_peak,
            payoff_conf_thresh=payoff_conf_thresh,
        )
    else:
        accepted = []
        rejected = []
        for cand in (ctx.enriched_candidates or []):
            print("VALIDATION DEBUG:", cand.get("start"), cand.get("end"), cand.get("validation"))
            payoff_conf = cand.get("payoff_confidence")
            if payoff_conf is None:
                payoff_conf = cand.get("signals", {}).get("psychology", {}).get("payoff_confidence", 0.0)
            ok, reason = validate_candidate_by_curiosity(
                ctx.curiosity_curve,
                float(cand.get("start", 0.0) or 0.0),
                float(cand.get("end", 0.0) or 0.0),
                payoff_conf,
                candidate=cand,
                min_peak=min_peak,
                payoff_conf_thresh=payoff_conf_thresh,
            )
            before_validation = cand.get("validation")
            cand["validation"] = {"accepted": bool(ok), "reasons": [] if ok else [reason]}
            _audit_field_mutation(cand, "validation", before_validation, cand["validation"], "_run_validation()", inspect.currentframe().f_lineno)
            if ok:
                accepted.append(cand)
            else:
                rejected.append(cand)

    # Smart fallback: if validation removed everything, reuse already-computed candidates if fallback is allowed.
    if not accepted and ctx.allow_fallback:
        fallback_source = enriched_before_validation or list(ctx.raw_candidates or [])
        if fallback_source:
            log.warning("[ORCH-FALLBACK] validation removed all candidates, using enriched candidates")
            accepted = sorted(
                fallback_source,
                key=lambda x: float((x or {}).get("score_enriched", (x or {}).get("score", 0.0)) or 0.0),
                reverse=True,
            )[: max(1, int(ctx.top_k or 1))]
            for c in accepted:
                c.setdefault("validation", {}).setdefault("reasons", []).append("validation_fallback_rescue")
            rejected = []

    ctx.enriched_candidates = accepted
    ctx.validated_candidates = list(accepted or [])
    ctx.rejected_candidates = rejected
    _audit_stage_snapshot("VALIDATION_OUT", ctx.validated_candidates)
    reject_counter = Counter()
    for cand in rejected:
        for reason in ((cand.get("validation", {}) or {}).get("reasons", []) or []):
            reject_counter[str(reason)] += 1

    from viral_finder.system_observer import get_observer
    obs = get_observer()
    obs.log_stage(
        "VALIDATION",
        input_count=len(enriched_before_validation),
        output_count=len(accepted),
        wall_time=time.time() - t0,
        reject_reasons=dict(reject_counter),
    )

    # Trace candidate status in validation
    for cand in accepted:
        cid = cand.get("cid")
        if cid:
            reasons = (cand.get("validation", {}) or {}).get("reasons", [])
            if reasons and any("rescue" in r or "fallback" in r or "soft_gate" in r for r in reasons):
                obs.rescue_candidate(cid, "validation", ", ".join(reasons))
            else:
                obs.finalize_candidate(cid, "passed_validation")

    for cand in rejected:
        psych = cand.get("signals", {}).get("psychology", {})
        sem = cand.get("signals", {}).get("semantic", {})
        nar = cand.get("signals", {}).get("narrative", {})
        eng = cand.get("signals", {}).get("engagement", {})
        
        # ── STREAM A: LLM Deep Psychology (Groq Trigger Artifacts) ─────────────
        llm_stop_scroll  = _clamp01(psych.get("stop_scroll",  0.0))
        llm_curiosity    = _clamp01(psych.get("curiosity",    psych.get("curiosity_peak", 0.0)))
        llm_memorability = _clamp01(psych.get("memorability", 0.0))
        llm_shareability = _clamp01(psych.get("shareability", 0.0))
        llm_emotional    = _clamp01(psych.get("emotional_charge", 0.0))
        has_llm = llm_stop_scroll > 0.0 or llm_memorability > 0.0
        llm_score = _clamp01(
            0.35 * llm_stop_scroll +
            0.25 * llm_curiosity +
            0.20 * llm_memorability +
            0.12 * llm_shareability +
            0.08 * llm_emotional
        )

        # ── STREAM B: Curiosity Engine (Medium-High Trust) ──────────────────────
        curiosity_peak    = _clamp01(psych.get("curiosity_peak", psych.get("curiosity", 0.0)))
        payoff_confidence = _clamp01(psych.get("payoff_confidence", cand.get("payoff_confidence", 0.0)))
        curiosity_score   = _clamp01((0.65 * curiosity_peak) + (0.35 * payoff_confidence))

        # ── STREAM C: Semantic (Ultron Brain) ───────────────────────────────────
        semantic_impact = _clamp01(sem.get("impact", 0.0))
        semantic_score  = _clamp01(
            (0.50 * semantic_impact) +
            (0.30 * _clamp01(sem.get("meaning", 0.0))) +
            (0.20 * _clamp01(sem.get("clarity", 0.0)))
        )

        # ── STREAM D: Audio/Visual Energy ───────────────────────────────────────
        engagement_energy = _clamp01(eng.get("energy", eng.get("classic", 0.0)))
        av_score = _clamp01(
            (0.60 * engagement_energy) +
            (0.25 * _clamp01(eng.get("audio", 0.0))) +
            (0.15 * _clamp01(eng.get("motion", 0.0)))
        )

        # ── STREAM E: Narrative Structure ───────────────────────────────────────
        trigger_density = _clamp01(nar.get("trigger_density", 0.0))
        trigger_score   = _clamp01(nar.get("trigger_score", 0.0))
        trigger_type    = str(nar.get("trigger_type", "") or "")
        _t_bonus = 0.15 if trigger_type in ("complete_thought", "payoff") else (0.10 if trigger_type == "belief_reversal" else 0.0)
        narrative_score = _clamp01((0.55 * trigger_score) + (0.45 * trigger_density) + _t_bonus)

        # ── COMPLETENESS: soft multiplier based on ending quality ───────────────
        # No hard gate. Rewards complete clips. Never zeros out a clip.
        ending_strength = _clamp01(nar.get("ending_strength", 0.0))
        payoff_resolution = _clamp01(nar.get("payoff_resolution_score", 0.0))
        completion_score = _clamp01(nar.get("completion_score", 0.0))
        raw_completeness = _clamp01(
            (0.45 * completion_score) +
            (0.30 * ending_strength) +
            (0.25 * payoff_resolution)
        )
        resolved_floor = 0.35 if (
            str(cand.get("completeness_signal", "") or "").upper() == "RESOLVED"
            or bool(cand.get("contract_seed"))
            or (completion_score >= 0.45 and payoff_resolution >= 0.35)
        ) else 0.0
        completeness = max(resolved_floor, raw_completeness)

        # ── UNIFIED VIRAL SCORE ─────────────────────────────────────────────────
        if has_llm:
            # LLM signals present: trust them most, they evaluated actual psychology
            raw_uvs = (
                0.40 * llm_score +
                0.25 * curiosity_score +
                0.20 * semantic_score +
                0.10 * narrative_score +
                0.05 * av_score
            )
            log.info(f"[UVS] LLM-path: llm={llm_score:.3f} curiosity={curiosity_score:.3f} semantic={semantic_score:.3f} narrative={narrative_score:.3f} av={av_score:.3f} completeness={completeness:.3f}")
        else:
            # No LLM signal: pure heuristic blend
            raw_uvs = (
                0.40 * curiosity_score +
                0.30 * semantic_score +
                0.20 * av_score +
                0.10 * narrative_score
            )
            log.info(f"[UVS] heuristic-path: curiosity={curiosity_score:.3f} semantic={semantic_score:.3f} av={av_score:.3f} narrative={narrative_score:.3f} completeness={completeness:.3f}")

        # Apply completeness as soft multiplier (never fully zeros out)
        viral_score = _clamp01(raw_uvs * completeness)

        if bool(cand.get("insight_candidate", False)):
            viral_score = _clamp01(viral_score * 1.08)

        cand["base_viral_score"] = round(float(raw_uvs), 4)
        cand["viral_score"] = round(float(viral_score), 4)
        cand["ranking_payoff_gate"] = round(float(completeness), 4)  # kept for log compat
        cand["low_motion_talk"] = bool(
            _semantic_explanation_strength(cand) >= 0.62
            and _clamp01(eng.get("motion", 0.0)) <= 0.08
            and _clamp01(sem.get("meaning", 0.0)) >= 0.58
        )
        cid = cand.get("cid")
        if cid:
            reasons = (cand.get("validation", {}) or {}).get("reasons", [])
            obs.reject_candidate(cid, "validation", ", ".join(reasons) or "failed_validation_rules")

    _record_stage(
        ctx,
        "L8_VALIDATION_GATES",
        accepted=len(accepted),
        rejected=len(rejected),
        reject_reasons=dict(sorted(reject_counter.items())),
        accepted_origins=dict(sorted(Counter(_candidate_origin(c) for c in accepted).items())),
        wall_s=round(time.time() - t0, 3),
    )


def _run_ranking(ctx: PipelineContext) -> None:
    t0 = time.time()
    use_viral_score = _env_bool("HS_ENABLE_ALIGNMENT_SCORING", True)
    for cand in (ctx.ranked_output or []):
        psych = cand.get("signals", {}).get("psychology", {})
        sem = cand.get("signals", {}).get("semantic", {})
        nar = cand.get("signals", {}).get("narrative", {})
        eng = cand.get("signals", {}).get("engagement", {})

        # ── STREAM A: LLM Deep Psychology ────────────────────────────────────────
        # FIX4: usefulness and completeness now read from psy (populated by
        # INTELLIGENCE TRANSPORT BRIDGE in signal enrichment). Previously
        # these Evidence packets were produced by groq_cortex but never
        # consumed by the scoring formula — guaranteed orphans.
        llm_stop_scroll  = _clamp01(psych.get("stop_scroll",  0.0))
        llm_curiosity    = _clamp01(psych.get("curiosity",    psych.get("curiosity_peak", 0.0)))
        llm_memorability = _clamp01(psych.get("memorability", 0.0))
        llm_shareability = _clamp01(psych.get("shareability", 0.0))
        llm_emotional    = _clamp01(psych.get("emotional_charge", 0.0))
        llm_usefulness   = _clamp01(psych.get("usefulness",   0.0))  # FIX4: was always 0.0 before
        llm_completeness = _clamp01(psych.get("completeness", 0.0))  # FIX4: was always 0.0 before
        has_llm = llm_stop_scroll > 0.0 or llm_memorability > 0.0
        llm_score = _clamp01(
            0.30 * llm_stop_scroll +
            0.22 * llm_curiosity +
            0.18 * llm_memorability +
            0.15 * llm_usefulness +    # FIX4: usefulness now contributes (was silently zero)
            0.10 * llm_shareability +
            0.05 * llm_emotional
        )  # weights sum to 1.0

        # ── STREAM B: Curiosity Engine ───────────────────────────────────────────
        curiosity_peak    = _clamp01(psych.get("curiosity_peak", psych.get("curiosity", 0.0)))
        payoff_confidence = _clamp01(psych.get("payoff_confidence", cand.get("payoff_confidence", 0.0)))
        curiosity_score   = _clamp01((0.65 * curiosity_peak) + (0.35 * payoff_confidence))

        # ── STREAM C: Semantic (Ultron Brain) ────────────────────────────────────
        semantic_score = _clamp01(
            (0.50 * _clamp01(sem.get("impact", 0.0))) +
            (0.30 * _clamp01(sem.get("meaning", 0.0))) +
            (0.20 * _clamp01(sem.get("clarity", 0.0)))
        )

        # ── STREAM D: Audio/Visual Energy ────────────────────────────────────────
        engagement_energy = _clamp01(eng.get("energy", eng.get("classic", 0.0)))
        av_score = _clamp01(
            (0.60 * engagement_energy) +
            (0.25 * _clamp01(eng.get("audio", 0.0))) +
            (0.15 * _clamp01(eng.get("motion", 0.0)))
        )

        # ── STREAM E: Narrative Structure ─────────────────────────────────────────
        trigger_density = _clamp01(nar.get("trigger_density", 0.0))
        trigger_score   = _clamp01(nar.get("trigger_score", 0.0))
        trigger_type    = str(nar.get("trigger_type", "") or "")
        _t_bonus = 0.15 if trigger_type in ("complete_thought", "payoff") else (0.10 if trigger_type == "belief_reversal" else 0.0)
        narrative_score = _clamp01((0.55 * trigger_score) + (0.45 * trigger_density) + _t_bonus)

        # ── STREAM F: Narrative Contract Score ───────────────────────────────────
        # Does this clip span a complete hook→payoff debt cycle?
        # A fully resolved contract boosts UVS. An unresolved hook gets a mild penalty.
        cand_s = float(cand.get("start", 0.0) or 0.0)
        cand_e = float(cand.get("end", cand_s) or cand_s)
        contract_score = 0.0
        contract_matched = False
        for contract in (ctx.narrative_contracts or []):
            c_hook_start = getattr(contract, "hook_start", 0.0)
            c_payoff_end = getattr(contract, "payoff_end", 0.0)
            c_res        = getattr(contract, "resolution_score", 0.0)
            c_score      = getattr(contract, "contract_score", 0.0)
            if c_payoff_end > c_hook_start:
                contract_window = c_payoff_end - c_hook_start
                overlap = max(0.0, min(cand_e, c_payoff_end) - max(cand_s, c_hook_start))
                coverage = overlap / contract_window if contract_window > 0 else 0.0
                if coverage >= 0.60:
                    contract_score = max(contract_score, c_score * coverage)
                    contract_matched = c_res > 0.0
        if contract_matched:
            log.info(f"[NCE_MATCH] {cand.get('cid','?')} {cand_s:.1f}-{cand_e:.1f}: "
                     f"contract_score={contract_score:.3f} (RESOLVED)")
        elif contract_score > 0:
            log.info(f"[NCE_MATCH] {cand.get('cid','?')} {cand_s:.1f}-{cand_e:.1f}: "
                     f"contract_score={contract_score:.3f} (FRAGMENT — hook only)")

        # ── COMPLETENESS: soft multiplier (never zeros out a clip) ───────────────
        ending_strength   = _clamp01(nar.get("ending_strength", 0.0))
        payoff_resolution = _clamp01(nar.get("payoff_resolution_score", 0.0))
        completion_score  = _clamp01(nar.get("completion_score", 0.0))
        # FIX4: llm_completeness from groq now included in multiplier
        # (previously produced as Evidence but orphaned — never reached this formula)
        if contract_matched:
            completion_score = max(completion_score, 0.75)
            payoff_resolution = max(payoff_resolution, getattr(
                next((c for c in (ctx.narrative_contracts or [])
                      if getattr(c, "resolution_score", 0) > 0), None),
                "resolution_score", payoff_resolution
            ))
        raw_completeness = _clamp01(
            (0.40 * completion_score) +
            (0.25 * ending_strength) +
            (0.20 * payoff_resolution) +
            (0.15 * llm_completeness)    # FIX4: Groq completeness signal finally consumed
        )
        resolved_floor = 0.35 if (
            contract_matched
            or str(cand.get("completeness_signal", "") or "").upper() == "RESOLVED"
            or bool(cand.get("contract_seed"))
            or (completion_score >= 0.45 and payoff_resolution >= 0.35)
        ) else 0.0
        completeness = max(resolved_floor, raw_completeness)

        # ── UNIFIED VIRAL SCORE ───────────────────────────────────────────────────
        if has_llm:
            raw_uvs = _clamp01(
                0.35 * llm_score +
                0.22 * curiosity_score +
                0.18 * semantic_score +
                0.15 * contract_score +
                0.07 * narrative_score +
                0.03 * av_score
            )
            _uvs_path = "llm"
            _uvs_weights = {"llm": 0.35, "curiosity": 0.22, "semantic": 0.18,
                            "contract": 0.15, "narrative": 0.07, "av": 0.03}
        else:
            raw_uvs = _clamp01(
                0.35 * curiosity_score +
                0.28 * semantic_score +
                0.20 * contract_score +
                0.12 * av_score +
                0.05 * narrative_score
            )
            _uvs_path = "heuristic"
            _uvs_weights = {"curiosity": 0.35, "semantic": 0.28, "contract": 0.20,
                            "av": 0.12, "narrative": 0.05}

        viral_score = _clamp01(raw_uvs * completeness)
        _insight_boost = 1.08 if bool(cand.get("insight_candidate", False)) else 1.0
        if _insight_boost > 1.0:
            viral_score = _clamp01(viral_score * _insight_boost)
        loop_info = cand.get("psychological_loop", {}) if isinstance(cand.get("psychological_loop"), dict) else {}
        loop_state = str(cand.get("loop_state", loop_info.get("state", "UNKNOWN")) or "UNKNOWN")
        loop_health = _clamp01(cand.get("loop_health", loop_info.get("health", completeness)))
        loop_cap = _loop_score_cap(loop_state, loop_health)
        if viral_score > loop_cap:
            log.info(
                "[LOOP_GATE] cid=%s state=%s health=%.3f cap=%.3f score %.3f -> %.3f",
                cand.get("cid", "?"),
                loop_state,
                loop_health,
                loop_cap,
                viral_score,
                loop_cap,
            )
            viral_score = loop_cap

        cand["base_viral_score"]   = round(float(raw_uvs), 4)
        cand["viral_score"]        = round(float(viral_score), 4)
        cand["ranking_payoff_gate"]= round(float(completeness), 4)
        cand["loop_gate"]          = round(float(loop_cap), 4)
        cand["low_motion_talk"]    = bool(
            _semantic_explanation_strength(cand) >= 0.62
            and _clamp01(eng.get("motion", 0.0)) <= 0.08
            and _clamp01(sem.get("meaning", 0.0)) >= 0.58
        )

        # ── FIX2: NAMED SCORE BREAKDOWN ──────────────────────────────────────────
        # Every component that contributed to viral_score is named explicitly.
        # No hidden scalar math. This dict travels with the candidate to the API.
        cand["score_breakdown"] = {
            "path":        _uvs_path,
            "weights":     _uvs_weights,
            # Stream inputs
            "llm_score":        round(llm_score,       4) if has_llm else None,
            "curiosity_score":  round(curiosity_score,  4),
            "semantic_score":   round(semantic_score,   4),
            "narrative_score":  round(narrative_score,  4),
            "av_score":         round(av_score,         4),
            "contract_score":   round(contract_score,   4),
            "loop_state":       loop_state,
            "loop_health":      round(loop_health,       4),
            "loop_gate":        round(loop_cap,          4),
            # LLM sub-signals (named, not buried in llm_score)
            "llm_stop_scroll":   round(llm_stop_scroll,  4) if has_llm else None,
            "llm_memorability":  round(llm_memorability, 4) if has_llm else None,
            "llm_usefulness":    round(llm_usefulness,   4) if has_llm else None,
            "llm_completeness":  round(llm_completeness, 4) if has_llm else None,
            # Multipliers
            "completeness_multiplier": round(completeness,    4),
            "insight_boost":           round(_insight_boost,  3),
            # Results
            "raw_uvs":    round(raw_uvs,    4),
            "viral_score": round(viral_score, 4),
        }
        log.info(
            "[SCORE_BREAKDOWN] cid=%s %.1f-%.1f path=%s "
            "llm=%.3f curiosity=%.3f semantic=%.3f contract=%.3f narrative=%.3f av=%.3f "
            "completeness=%.3f insight_boost=%.2f raw_uvs=%.4f viral_score=%.4f",
            cand.get("cid", "?"),
            cand_s, cand_e,
            _uvs_path,
            llm_score if has_llm else 0.0,
            curiosity_score, semantic_score, contract_score, narrative_score, av_score,
            completeness, _insight_boost, raw_uvs, viral_score,
        )

        # ── FIX3: DECISION TIMELINE ───────────────────────────────────────────────
        # Append ranking entry to the candidate's per-stage score change history.
        _timeline = cand.setdefault("decision_timeline", [])
        _timeline.append({
            "stage":  "RANKING",
            "event":  "Judged",
            "reason": f"UVS: {_uvs_path}-path. completeness={completeness:.3f}"
                      + f" loop={loop_state}:{loop_health:.3f}"
                      + (f" insight_boost={_insight_boost:.2f}" if _insight_boost > 1.0 else ""),
            "score":  round(viral_score, 4)
        })

    # ── Hook-origin floor boost ──────────────────────────────────────────────
    # Hook Hunter clips are injected AFTER semantic scoring, so they carry
    # semantic=0 / engagement=0 / curiosity=0 → base_viral_score ≈ 0.
    # Without a floor they always rank last and get cut before arc assembly.
    # Grant them a minimum viral_score equal to their raw hook_score so they
    # compete fairly with strict candidates.
    for cand in (ctx.ranked_output or []):
        if _candidate_origin(cand) == "hook":
            raw_hook = float(cand.get("score", 0.0) or 0.0)
            # Floor = 40% of raw hook score (keeps them below strong strict candidates)
            loop_info = cand.get("psychological_loop", {}) if isinstance(cand.get("psychological_loop"), dict) else {}
            loop_state = str(cand.get("loop_state", loop_info.get("state", "UNKNOWN")) or "UNKNOWN")
            loop_health = _clamp01(cand.get("loop_health", loop_info.get("health", 0.0)))
            hook_floor = min(raw_hook * 0.40, _loop_score_cap(loop_state, loop_health))
            if cand.get("viral_score", 0.0) < hook_floor:
                cand["viral_score"] = round(hook_floor, 4)
                log.debug("[HOOK-FLOOR] cid=%s viral_score boosted to %.4f (hook_score=%.3f)",
                          cand.get("cid", "?"), hook_floor, raw_hook)
    # ────────────────────────────────────────────────────────────────────────

    ranked = sorted(
        (ctx.ranked_output or []),
        key=lambda x: (
            _rank_score(
                x,
                "viral_score" if use_viral_score else "score_enriched",
                "score_enriched",
                "score",
            ),
            _rank_score(x, "score_enriched", "score"),
            _rank_score(x, "score"),
        ),
        reverse=True,
    )

    ranked = dedupe_by_overlap(ranked, overlap_threshold=0.40)
    min_gap = float(os.getenv("HS_ORCH_DIVERSITY_MIN_START_GAP", "3.0") or 3.0)
    if rank_and_diversify:
        final = rank_and_diversify(ranked, top_k=int(ctx.top_k), min_start_gap=min_gap)
    else:
        final = []
        used = []
        for c in ranked:
            s = float(c.get("start", 0.0) or 0.0)
            if any(abs(s - ps) < min_gap for ps in used):
                continue
            final.append(c)
            used.append(s)
            if len(final) >= int(ctx.top_k):
                break

    if ctx.target_min and len(final) < int(ctx.target_min):
        recovered = list(final)
        existing_ids = set(id(c) for c in recovered)
        for c in ranked:
            if id(c) in existing_ids:
                continue
            recovered.append(c)
            existing_ids.add(id(c))
            if len(recovered) >= int(ctx.target_min):
                break
        if len(recovered) > len(final):
            log.warning(
                "[ORCH-UNDERFLOW-RECOVERY] initial=%d target_min=%d recovered=%d",
                len(final),
                int(ctx.target_min),
                len(recovered),
            )
            final = recovered

    for rank_idx, c in enumerate(final):
        c["decision_owner"] = "RANKING"
        c["ranking_rank"] = int(rank_idx + 1)
        c["ranking_decision_score"] = round(float(c.get("viral_score", c.get("score_enriched", c.get("score", 0.0))) or 0.0), 4)
        s = float(c.get("start", 0.0) or 0.0)
        e = float(c.get("end", 0.0) or 0.0)
        psych = c.get("signals", {}).get("psychology", {})
        nar = c.get("signals", {}).get("narrative", {})
        sem = c.get("signals", {}).get("semantic", {})
        eng = c.get("signals", {}).get("engagement", {})
        log.info(
            "[CLIP] %.2f-%.2f psychology=%.3f narrative=%.3f semantic=%.3f engagement=%.3f alignment=%.3f viral_score=%.3f",
            s,
            e,
            float(psych.get("curiosity_peak", psych.get("curiosity", 0.0)) or 0.0),
            float(nar.get("completion_score", 0.0) or 0.0),
            float(sem.get("impact", 0.0) or 0.0),
            float(eng.get("energy", eng.get("classic", 0.0)) or 0.0),
            float(c.get("alignment_score", 0.0) or 0.0),
            float(c.get("viral_score", c.get("score_enriched", 0.0)) or 0.0),
        )
        
        log.info(f"[CLIP_CHOOSER_REASONING] --- Clip {s:.2f}-{e:.2f} Selection ---")
        artifacts = c.get("artifacts", {}).get("triggers", [])
        if artifacts:
            log.info(f"  -> Triggers Evaluated: {len(artifacts)}")
            for art in artifacts:
                # art is a dict (converted from TriggerArtifact dataclass during enrichment)
                psy_dict = art.get("psychology", {}) if isinstance(art, dict) else getattr(art, "psychology", {})
                t_type = art.get("trigger_type", "unknown") if isinstance(art, dict) else getattr(art, "trigger_type", "unknown")
                conf = art.get("confidence", 0.0) if isinstance(art, dict) else getattr(art, "confidence", 0.0)
                psy_metrics = " ".join([f"{k}={v}" for k, v in psy_dict.items()])
                log.info(f"     * [{t_type}] conf={float(conf):.2f} | Deep Metrics: {psy_metrics}")
            log.info(f"     => Extracted Effective Deep Metrics into Candidate's Core Signals.")
        else:
            log.info("  -> Triggers Evaluated: None (Selected via native heuristic signals)")
            
        log.info(f"  -> Final Decision Math: base_viral_score={c.get('base_viral_score', 0.0)} * payoff_gate={c.get('ranking_payoff_gate', 0.0)} = viral_score={c.get('viral_score', 0.0)}")
        log.info("--------------------------------------------------")
        # Per-candidate Ultron semantic print through orchestrator (explicitly visible in main logs).
        log.info(
            "[ORCH][ULTRON][CAND] %.2f-%.2f impact=%.3f meaning=%.3f novelty=%.3f clarity=%.3f semantic_quality=%.3f",
            s,
            e,
            float(sem.get("impact", 0.0) or 0.0),
            float(sem.get("meaning", 0.0) or 0.0),
            float(sem.get("novelty", 0.0) or 0.0),
            float(sem.get("clarity", 0.0) or 0.0),
            float(sem.get("semantic_quality", 0.0) or 0.0),
        )
    ctx.final_candidates = final
    ctx.ranked_output = list(final or [])
    _record_stage(
        ctx,
        "L9_CLIP_SELECTOR_RANKING",
        ranked=len(ranked),
        returned=len(final),
        final_pass_provenance=dict(sorted(Counter(str(c.get("select_pass", "strict") or "strict") for c in final if not c.get("hook_seed")).items())),
        final_origins=dict(sorted(Counter(_candidate_origin(c) for c in final).items())),
        avg_viral_score=round(sum(float(c.get("viral_score", 0.0) or 0.0) for c in final) / float(max(1, len(final))), 4),
        wall_s=round(time.time() - t0, 3),
    )


def _run_arc_assembler(ctx: PipelineContext) -> None:
    t0 = time.time()
    transcript = list(ctx.transcript or [])
    # FIX1: Assembler runs before Ranking, so it must read from validated_candidates.
    ranked = list(ctx.validated_candidates or [])
    if (not transcript) or (not ranked):
        _record_stage(ctx, "L10_ARC_ASSEMBLER", input=len(ranked), arcs=0, complete=0, wall_s=round(time.time() - t0, 3))
        return

    min_clip = 25.0
    base_max_clip = 40.0
    lookback_s = 7.0
    out: List[Dict[str, Any]] = []
    complete_count = 0

    def _seg_bounds(seg: Dict[str, Any]) -> tuple[float, float]:
        ss = float(seg.get("start", 0.0) or 0.0)
        ee = float(seg.get("end", ss) or ss)
        return ss, max(ss, ee)

    def _find_seg_index(ts: float) -> int:
        target = float(ts or 0.0)
        for i, seg in enumerate(transcript):
            s, e = _seg_bounds(seg)
            if s <= target <= e:
                return i
        return max(0, min(len(transcript) - 1, 0 if not transcript else int(min(range(len(transcript)), key=lambda j: abs(_seg_bounds(transcript[j])[0] - target)))))

    for cand in ranked:
        c = dict(cand or {})
        s0 = float(c.get("start", 0.0) or 0.0)
        e0 = float(c.get("end", s0) or s0)
        if e0 <= s0:
            out.append(c)
            continue

        nar = (c.get("signals", {}) or {}).get("narrative", {}) or {}
        psych = (c.get("signals", {}) or {}).get("psychology", {}) or {}
        sem = (c.get("signals", {}) or {}).get("semantic", {}) or {}
        candidate_curiosity_peak = _clamp01(psych.get("curiosity_peak", psych.get("curiosity", 0.0)))
        candidate_semantic_quality = _clamp01(sem.get("semantic_quality", c.get("confidence", 0.0)))

        start_idx = _find_seg_index(s0)
        hook_idx = start_idx
        hook_found = False

        # HOOK: scan around candidate onset.
        hook_scan_end = min(len(transcript), start_idx + 8)
        why_selected = "fallback to candidate onset (default)"
        final_hook_score = 0.0
        best_segment_idx = start_idx
        best_score = -1.0
        best_reason = why_selected
        
        for j in range(max(0, start_idx - 2), hook_scan_end):
            seg_s, seg_e = _seg_bounds(transcript[j])
            seg_scores = compute_quality_scores(transcript, seg_s, seg_e) if compute_quality_scores else {}
            hook_score = _clamp01(seg_scores.get("hook_score", nar.get("hook_score", 0.0)))
            pattern_break = _clamp01(seg_scores.get("pattern_break_score", nar.get("pattern_break_score", 0.0)))
            
            # Compute candidate strength
            score = max(hook_score, pattern_break)
            
            if score > best_score:
                best_score = score
                best_segment_idx = j
                if hook_score >= pattern_break:
                    best_reason = f"strongest hook_score in window ({hook_score:.3f})"
                else:
                    best_reason = f"strongest pattern_break in window ({pattern_break:.3f})"
                    
        if best_score > 0.0:
            hook_idx = best_segment_idx
            hook_found = True
            final_hook_score = best_score
            why_selected = best_reason

        hook_seg = transcript[hook_idx]
        hook_start, hook_end = _seg_bounds(hook_seg)
        arc_start = hook_start
        # Backward expansion removed to start exactly at hook
        # for seg in reversed(transcript[:hook_idx]):
        #     prev_s, prev_e = _seg_bounds(seg)
        #     if prev_e < hook_start and (hook_start - prev_e) < lookback_s:
        #         arc_start = min(arc_start, prev_s)
        #         break
        
        # FIX: Do not start arc_end at e0 (candidate generation bound).
        # This was preventing the ArcAssembler from shrinking bloated clips!
        arc_end = hook_end
        payoff_idx = None
        max_clip = base_max_clip

        # BUILD + PAYOFF: forward O(n) pass with bounded horizon.
        j = hook_idx
        while j < len(transcript):
            seg = transcript[j]
            seg_s, seg_e = _seg_bounds(seg)
            if seg_s < arc_start:
                j += 1
                continue
            if (seg_e - arc_start) > max_clip:
                break

            seg_scores = compute_quality_scores(transcript, arc_start, seg_e) if compute_quality_scores else {}
            open_loop = _clamp01(seg_scores.get("open_loop_score", nar.get("open_loop_score", 0.0)))
            info_density = _clamp01(seg_scores.get("information_density_score", nar.get("information_density_score", 0.0)))
            semantic_quality = _clamp01(seg_scores.get("semantic_quality", 0.0))
            build_ok = (open_loop > 0.0) or (info_density > 0.1) or (semantic_quality > 0.4)

            if build_ok:
                arc_end = max(arc_end, seg_e)

            seg_text = str(seg.get("text", "") or "")
            punch = False
            if _detect_message_punch:
                try:
                    punch = bool(_detect_message_punch(seg_s, seg_e, seg_text, transcript, float(c.get("viral_score", c.get("score_enriched", 0.0)) or 0.0)))
                except Exception:
                    punch = False
            ending_strength = _clamp01(seg_scores.get("ending_strength", nar.get("ending_strength", 0.0)))
            payoff_resolution = _clamp01(seg_scores.get("payoff_resolution_score", nar.get("payoff_resolution_score", 0.0)))
            if payoff_resolution > 0.6:
                max_clip = 50.0
            build_duration = seg_e - hook_end
            if build_duration < 6.0:
                j += 1
                continue
            if (j - hook_idx >= 2) and (
                (ending_strength > 0.3) or
                (payoff_resolution > 0.35) or
                punch
            ):
                payoff_idx = j
                arc_end = max(arc_end, seg_e)
                break
            j += 1

        if payoff_idx == hook_idx:
            payoff_idx = None

        # ---- INSIGHT TAIL EXTENSION (safe) ----
        tail_limit = min((payoff_idx + 3) if payoff_idx is not None else (hook_idx + 3), len(transcript))
        for k in range((payoff_idx + 1) if payoff_idx is not None else (hook_idx + 1), tail_limit):
            seg_s, seg_e = _seg_bounds(transcript[k])
            seg_text = str(transcript[k].get("text", "") or "")
            seg_scores = compute_quality_scores(transcript, arc_start, seg_e) if compute_quality_scores else {}
            info_density = _clamp01(seg_scores.get("information_density_score", 0.0))
            semantic_quality = _clamp01(seg_scores.get("semantic_quality", 0.0))
            # Extend only if explanation/insight continues.
            if info_density > 0.12 or semantic_quality > 0.55:
                arc_end = max(arc_end, seg_e)
            else:
                break

        # Enforce min duration by extending forward.
        if (arc_end - arc_start) < min_clip:
            for k in range((payoff_idx + 1) if payoff_idx is not None else (hook_idx + 1), len(transcript)):
                _, seg_e = _seg_bounds(transcript[k])
                arc_end = max(arc_end, seg_e)
                if (arc_end - arc_start) >= min_clip:
                    break

        # Clamp and complete trailing sentence.
        # Start exactly at the hook.
        # arc_start = max(0.0, arc_start - 1.5)
        arc_end = min(arc_end, arc_start + max_clip)
        arc_end = max(arc_end, arc_start + min_clip)
        if (arc_end - arc_start) < 18.0:
            arc_end = min(arc_start + 22.0, arc_start + max_clip)
        arc_end = extend_until_sentence_complete(arc_start, arc_end, transcript, max_extend=4.0)
        arc_end = min(arc_end, arc_start + max_clip)

        arc_scores = compute_quality_scores(transcript, arc_start, arc_end) if compute_quality_scores else {}
        open_loop_tail = _clamp01(arc_scores.get("open_loop_score", 0.0))
        if open_loop_tail > 0.5:
            arc_end = min(arc_end + 6.0, arc_start + max_clip)
            arc_scores = compute_quality_scores(transcript, arc_start, arc_end) if compute_quality_scores else {}
        hook_score = _clamp01(arc_scores.get("hook_score", nar.get("hook_score", 0.0)))
        payoff_resolution = _clamp01(arc_scores.get("payoff_resolution_score", nar.get("payoff_resolution_score", 0.0)))
        tension_gradient = _clamp01(psych.get("tension_gradient", 0.0))
        info_density = _clamp01(arc_scores.get("information_density_score", nar.get("information_density_score", 0.0)))
        rewatch = _clamp01(arc_scores.get("rewatch_score", nar.get("rewatch_score", 0.0)))
        arc_score = _clamp01(
            (0.30 * hook_score)
            + (0.30 * payoff_resolution)
            + (0.20 * tension_gradient)
            + (0.10 * info_density)
            + (0.10 * rewatch)
        )
        base_arc_score = arc_score
        trigger_type = str(nar.get("trigger_type", "") or "")
        trigger_bonus_applied = trigger_type in ("belief_reversal", "complete_thought", "payoff")
        if trigger_bonus_applied:
            arc_score = _clamp01(arc_score * 1.2)
        payoff_source = str(c.get("payoff_source", ""))
        payoff_score_val = c.get("payoff_engine_score", 0.0)
        is_strong_payoff = (payoff_score_val >= 0.55) or (payoff_source in ["TIER1"])
        arc_complete = bool(hook_found and (payoff_idx is not None) and is_strong_payoff)
        if arc_complete:
            complete_count += 1
            arc_score = _clamp01(arc_score * 1.35)
        
        # DURATION SWEET SPOT BONUS - Strongly prefer 12-25s (TikTok range)
        duration = arc_end - arc_start
        ideal_duration = 18.0
        if 12.0 <= duration <= 25.0:
            duration_bonus = max(0.0, 1.0 - (abs(duration - ideal_duration) / ideal_duration))
            arc_score = _clamp01(arc_score + (duration_bonus * 0.10))

        payoff_seg = transcript[payoff_idx] if payoff_idx is not None else transcript[min(len(transcript) - 1, hook_idx)]
        p_s, p_e = _seg_bounds(payoff_seg)
        print(f"[ARC] hook_idx={hook_idx} payoff_idx={payoff_idx} duration={arc_end - arc_start:.1f}s")
        c["start"] = round(float(arc_start), 2)
        c["end"] = round(float(max(arc_start + 0.01, arc_end)), 2)
        c["duration"] = round(float(c["end"] - c["start"]), 2)
        c["hook_segment"] = {
            "idx": int(hook_idx),
            "start": round(float(hook_start), 2),
            "end": round(float(hook_end), 2),
            "text": str(hook_seg.get("text", "") or ""),
        }
        c["payoff_segment"] = {
            "idx": int(payoff_idx if payoff_idx is not None else hook_idx),
            "start": round(float(p_s), 2),
            "end": round(float(p_e), 2),
            "text": str(payoff_seg.get("text", "") or ""),
        }
        c["arc_complete"] = arc_complete
        c["arc_score"] = round(float(arc_score), 4)
        # FIX1: Do NOT overwrite viral_score here.
        # viral_score will be set by _run_ranking on the assembled clip.
        # c["viral_score"] = round(float(arc_score), 4)  <- REMOVED
        c["provenance"] = {"stage": "L10_ARC_ASSEMBLER"}
        c["hook_selection_trace"] = {
            "text": str(hook_seg.get("text", "") or ""),
            "score": round(float(final_hook_score), 4),
            "reason": why_selected
        }

        # FIX3: DECISION TIMELINE
        _boundary_changed = (round(float(arc_start), 2) != round(s0, 2)
                             or round(float(arc_end), 2) != round(e0, 2))
        _timeline = c.setdefault("decision_timeline", [])
        _timeline.append({
            "stage":  "ASSEMBLY",
            "event":  "Boundary Changed" if _boundary_changed else "Assembled",
            "reason": "payoff_found" if payoff_idx is not None else ("horizon_expansion" if _boundary_changed else "no_change"),
            "old_bounds": f"{round(s0, 2)}-{round(e0, 2)}",
            "new_bounds": f"{round(float(arc_start), 2)}-{round(float(arc_end), 2)}",
            "score":  round(arc_score, 4)
        })
        log.info(
            "[DECISION_TIMELINE] cid=%s ASSEMBLY: %.2fs-%.2fs -> %.2fs-%.2fs "
            "arc_score=%.4f arc_complete=%s boundary_changed=%s",
            c.get("cid", "?"), s0, e0, float(arc_start), float(arc_end),
            arc_score, arc_complete, _boundary_changed,
        )
        out.append(c)

        if os.environ.get("HS_TRACE_MODE", "false").strip().lower() == "true":
            tid = c.get("trace_id", c.get("id"))
            if tid:
                ctx.trace_state(tid, "EXPANDED")
                ctx.trace_event(
                    trace_id=tid,
                    stage="ARC_ASSEMBLER",
                    event="EXPANDED",
                    changed=(round(float(arc_end), 2) != round(e0, 2) or round(float(arc_start), 2) != round(s0, 2)),
                    impact="HIGH" if (round(float(arc_end), 2) != round(e0, 2)) else "LOW",
                    before={"start": round(s0, 2), "end": round(e0, 2)},
                    after={"start": round(float(arc_start), 2), "end": round(float(arc_end), 2)}
                )
                if payoff_idx is not None:
                    ctx.trace_state(tid, "PAYOFF_FOUND")
                    ctx.trace_event(
                        trace_id=tid,
                        stage="PAYOFF_SELECTION",
                        event="PAYOFF_SELECTED",
                        changed=True,
                        impact="HIGH",
                        after={"payoff_idx": payoff_idx, "payoff_text": str(payoff_seg.get("text", "") or "")}
                    )
                
                # [GOVERNOR TELEMETRY PHASE 1]
                if tid and hasattr(ctx, "candidate_threads") and tid in ctx.candidate_threads:
                    st = ctx.candidate_threads[tid]
                    st.propose_boundary(
                        stage="ARC_ASSEMBLER",
                        before_start=round(s0, 2),
                        before_end=round(e0, 2),
                        after_start=round(float(arc_start), 2),
                        after_end=round(float(arc_end), 2),
                        reason="payoff_found" if payoff_idx is not None else "horizon_expansion",
                        confidence=0.85
                    )
                    if payoff_idx is not None:
                        st.propose_state(
                            stage="ARC_ASSEMBLER",
                            state="PAYOFF_CANDIDATE",
                            reason="payoff_found",
                            confidence=0.85
                        )
    # FIX1: Assembler now only Transforms. Sort by arc_score for determinism,
    # dedup overlaps, then write ALL assembled clips to ranked_output.
    # _run_ranking (which runs after assembly) will apply top-k and final sort.
    #
    # GIANT-CLIP DEDUP PROTECTION:
    # An incomplete arc (no confirmed payoff) that happens to be long dominates
    # dedup (IoU > 0.40 against any normal 25-45s clip), killing all other candidates.
    # Penalize ONLY incomplete long arcs before dedup ordering.
    # arc_complete=True clips (genuine payoff at 83s, etc.) are EXEMPT — their
    # duration is earned and their score should not be reduced.
    DEDUP_MAX_CLIP_SAFE = base_max_clip  # 40s
    for _c in out:
        _dur = float(_c.get("end", 0.0) or 0.0) - float(_c.get("start", 0.0) or 0.0)
        _is_complete = bool(_c.get("arc_complete"))
        if _dur > DEDUP_MAX_CLIP_SAFE and not _is_complete:
            # Incomplete arc is bloated without a real payoff — penalize for dedup ordering
            _penalty = min(0.50, (_dur - DEDUP_MAX_CLIP_SAFE) / DEDUP_MAX_CLIP_SAFE * 0.5)
            _orig = float(_c.get("arc_score", 0.0) or 0.0)
            _c["arc_score"] = round(max(0.0, _orig - _penalty), 4)
            log.info(
                "[ARC_DEDUP_PENALTY] cid=%s dur=%.1fs arc_complete=False arc_score %.4f -> %.4f (incomplete giant-clip)",
                _c.get("cid", "?"), _dur, _orig, _c["arc_score"]
            )
        elif _dur > DEDUP_MAX_CLIP_SAFE and _is_complete:
            log.info(
                "[ARC_DEDUP_EXEMPT] cid=%s dur=%.1fs arc_complete=True score_protected=%.4f (payoff earned the length)",
                _c.get("cid", "?"), _dur, float(_c.get("arc_score", 0.0) or 0.0)
            )

    out = sorted(
        out,
        key=lambda x: float(x.get("arc_score", x.get("viral_score", 0.0)) or 0.0),
        reverse=True,
    )
    out = dedupe_by_overlap(out, overlap_threshold=0.40)

    # SAFETY NET: if dedup wiped everything, use top-3 by arc_score without dedup.
    # A 0-clip output causes the staged pipeline to fail and wastes another ~160s
    # running Ultron V33 as a fallback with no benefit.
    if not out and ranked:
        log.warning(
            "[ARC_ASSEMBLER] dedup wiped all %d assembled clips -- using top-3 fallback (no dedup).",
            len(ranked)
        )
        _fallback = sorted(
            ranked,
            key=lambda x: float(x.get("arc_score", x.get("viral_score", x.get("score_enriched", 0.0))) or 0.0),
            reverse=True
        )[:3]
        out = sorted(_fallback, key=lambda x: float(x.get("start", 0.0) or 0.0))

    ctx.ranked_output    = list(out)   # ranking reads from this
    ctx.final_candidates = list(out)   # will be replaced by ranking's output
    log.info("[ORCH-ARC] assembled=%d complete=%d input=%d", len(ctx.ranked_output), complete_count, len(ranked))

    from viral_finder.system_observer import get_observer
    obs = get_observer()
    obs.log_stage(
        "ARC_ASSEMBLER",
        input_count=len(ranked),
        output_count=len(ctx.ranked_output),
        wall_time=time.time() - t0
    )
    # Trace candidates
    output_dict = {c.get("cid"): c for c in ctx.ranked_output if c.get("cid")}
    for c in ranked:
        cid = c.get("cid")
        if cid:
            if cid in output_dict:
                out_cand = output_dict[cid]
                obs.modify_candidate(
                    cid,
                    "arc_assembler",
                    {
                        "start": out_cand.get("start"),
                        "end": out_cand.get("end"),
                        "scores": {"arc_score": out_cand.get("arc_score")}
                    }
                )
            else:
                obs.reject_candidate(cid, "arc_assembler", "dropped_during_overlap_deduplication_or_top_k_limit")

    _record_stage(
        ctx,
        "L10_ARC_ASSEMBLER",
        input=len(ranked),
        arcs=len(ctx.ranked_output),
        complete=complete_count,
        origins=dict(sorted(Counter(_candidate_origin(c) for c in ctx.ranked_output).items())),
        avg_arc_duration=round(sum(float(c.get("duration", 0.0) or 0.0) for c in ctx.ranked_output) / float(max(1, len(ctx.ranked_output))), 3),
        wall_s=round(time.time() - t0, 3),
    )




def _audit_candidate_state(
    ctx: PipelineContext,
    stage: str,
    candidate: Dict[str, Any],
    *,
    hook_idx: Any = None,
    payoff_idx: Any = None,
    contract_state: Any = None,
    loop_state: Any = None,
    resolution_score: Any = None,
    arc_complete: Any = None,
    drop_reason: str = "",
) -> None:
    if not isinstance(candidate, dict):
        return

    cid = candidate.get("cid", candidate.get("id", candidate.get("trace_id", "?")))

    if hook_idx is None:
        if isinstance(candidate.get("hook_segment"), dict):
            hook_idx = candidate["hook_segment"].get("idx")
        else:
            hook_idx = candidate.get("hook_idx")

    if payoff_idx is None:
        payoff_idx = candidate.get("locked_payoff_idx")
        if payoff_idx is None and isinstance(candidate.get("payoff_segment"), dict):
            payoff_idx = candidate["payoff_segment"].get("idx")

    tid = candidate.get("trace_id", candidate.get("id"))
    st = None
    if tid and hasattr(ctx, "candidate_threads"):
        st = ctx.candidate_threads.get(tid)

    if contract_state is None:
        contract_state = getattr(st, "state", None) if st is not None else candidate.get("contract_state")
    if loop_state is None:
        loop_state = candidate.get("loop_state")
    if resolution_score is None:
        resolution_score = (
            getattr(st, "resolution_score", None)
            if st is not None
            else candidate.get("resolution_score", candidate.get("payoff_engine_score"))
        )
    if arc_complete is None:
        arc_complete = candidate.get("arc_complete")

    log.info(
        "[CANDIDATE_AUDIT] stage=%s cid=%s hook_idx=%s payoff_idx=%s contract_state=%s "
        "loop_state=%s resolution_score=%s arc_complete=%s drop_reason=%s",
        stage,
        cid,
        hook_idx,
        payoff_idx,
        contract_state,
        loop_state,
        resolution_score,
        arc_complete,
        drop_reason or "",
    )


def _audit_stage_snapshot(stage: str, candidates: List[Dict[str, Any]], label: str = "") -> None:
    ids = [str(c.get("cid", c.get("id", c.get("trace_id", "?")))) for c in candidates if isinstance(c, dict)]
    log.info("[STAGE AUDIT] stage=%s %sinput=%d output=%d ids=%s", stage, f"{label} " if label else "", len(candidates), len(candidates), ids)


def _audit_field_mutation(candidate: Dict[str, Any], field: str, before: Any, after: Any, owner: str, exact_line: Optional[int] = None) -> None:
    cid = candidate.get("cid", candidate.get("id", candidate.get("trace_id", "?"))) if isinstance(candidate, dict) else "?"
    log.info(
        "[FIELD MUTATION] cid=%s field=%s before=%s after=%s owner=%s exact_line=%s",
        cid,
        field,
        before,
        after,
        owner,
        exact_line if exact_line is not None else "?",
    )


def _run_story_completion(ctx: PipelineContext) -> None:
    t0 = time.time()
    transcript = list(ctx.transcript or [])
    candidates = list(ctx.validated_candidates or [])
    _audit_stage_snapshot("STORY_COMPLETION_IN", candidates)
    if (not transcript) or (not candidates):
        _record_stage(ctx, "L10A_STORY_COMPLETION", input=len(candidates), completed=0, wall_s=round(time.time() - t0, 3))
        return

    def _seg_bounds(seg: Dict[str, Any]) -> tuple[float, float]:
        ss = float(seg.get("start", 0.0) or 0.0)
        ee = float(seg.get("end", ss) or ss)
        return ss, max(ss, ee)

    def _find_seg_index(ts: float) -> int:
        target = float(ts or 0.0)
        for i, seg in enumerate(transcript):
            s, e = _seg_bounds(seg)
            if s <= target <= e:
                return i
        return max(0, min(len(transcript) - 1, 0 if not transcript else int(min(range(len(transcript)), key=lambda j: abs(_seg_bounds(transcript[j])[0] - target)))))

    base_max_clip = 60.0
    completed = 0
    failed = 0

    for c in candidates:
        if not isinstance(c, dict):
            continue
        s0 = float(c.get("start", 0.0) or 0.0)
        e0 = float(c.get("end", s0) or s0)
        if e0 <= s0:
            continue

        if c.get("locked_payoff_time") is not None and c.get("locked_payoff_idx") is not None:
            completed += 1
            _audit_candidate_state(ctx, "StoryCompletion", c)
            continue

        if c.get("hook_segment"):
            hook_idx = int(c["hook_segment"].get("idx", _find_seg_index(s0)))
        elif c.get("hook_idx") is not None:
            hook_idx = int(c["hook_idx"])
        else:
            hook_idx = _find_seg_index(s0)
        hook_idx = max(0, min(len(transcript) - 1, hook_idx))
        hook_seg = transcript[hook_idx]
        hook_start, _ = _seg_bounds(hook_seg)

        candidate_window = []
        for tmp_j in range(hook_idx, len(transcript)):
            tmp_seg_s, tmp_seg_e = _seg_bounds(transcript[tmp_j])
            if (tmp_seg_e - hook_start) > base_max_clip:
                break
            candidate_window.append({
                "idx": tmp_j,
                "start": tmp_seg_s,
                "end": tmp_seg_e,
                "text": str(transcript[tmp_j].get("text", "") or "")
            })

        best_payoff = None
        payoff_idx = None
        tid = c.get("trace_id", c.get("id", "unknown"))
        st = ctx.candidate_threads.get(tid) if tid and hasattr(ctx, "candidate_threads") else None

        if (c.get("completeness_signal") == "RESOLVED" or c.get("contract_seed")) and c.get("end"):
            llm_end = float(c["end"])
            c["payoff_source"] = "CONTRACT_ENGINE" if c.get("contract_seed") else "LLM_DIRECTOR"
            c["payoff_engine_score"] = max(float(c.get("payoff_engine_score", 0.0) or 0.0), 1.0)
            for i, seg in enumerate(transcript):
                seg_end = float(seg.get("end", 0) or 0)
                if abs(seg_end - llm_end) <= 1.5:
                    payoff_idx = i
                    before_locked_idx = c.get("locked_payoff_idx")
                    c["locked_payoff_idx"] = payoff_idx
                    c["locked_payoff_time"] = llm_end
                    c["locked_payoff_text"] = seg.get("text", "")
                    _audit_field_mutation(c, "locked_payoff_idx", before_locked_idx, payoff_idx, "_run_story_completion()", inspect.currentframe().f_lineno)
                    completed += 1
                    break
            _audit_candidate_state(ctx, "StoryCompletion", c, hook_idx=hook_idx, payoff_idx=payoff_idx)
            continue

        if candidate_window:
            if st:
                try:
                    from utils.payoff_engine import PayoffEngine
                    engine = PayoffEngine()
                    
                    # =================================================
                    # THE INPUT CONTRACT (FORENSIC LOG)
                    # =================================================
                    print("\n=================================================")
                    print("HOOK")
                    _promise = st.ident.get("hook", "N/A") if hasattr(st, "ident") else "N/A"
                    _debt = "N/A"
                    _promise_type = "N/A"
                    if hasattr(st, "ident") and "birth_reason" in st.ident:
                        _br = st.ident["birth_reason"]
                        _debt = _br.get("debt", "N/A")
                        _promise_type = _br.get("promise_type", "N/A")
                    
                    _w_start = candidate_window[0]['start'] if candidate_window else "N/A"
                    _w_end = candidate_window[-1]['end'] if candidate_window else "N/A"
                    _num_segs = len(candidate_window)
                    
                    print(f"Promise\n{_promise}\n")
                    print(f"Debt\n{_debt}\n")
                    print(f"Promise Type\n{_promise_type}\n")
                    print(f"Window Start\n{_w_start}\n")
                    print(f"Window End\n{_w_end}\n")
                    print(f"Segments Given To Engine\n{_num_segs}")
                    
                    print("Transcript passed into PayoffEngine:")
                    for idx, _s in enumerate(candidate_window):
                        print(f"  Seg {_s.get('idx', '?')}: '{_s.get('text', '')}'")
                        
                    print(f"\nExpected Payoff Region\n[To be manually verified by Engineer]")
                    print("=================================================")

                    result = engine.resolve(st, transcript, transcript[hook_idx], candidate_window)

                    _state = result.get("state", "SEARCH_FAILED") if result else "SEARCH_FAILED"
                    print("Then immediately after")
                    print("Payoff Engine")
                    print("received")
                    print(f"{_num_segs} segments")
                    print("returned")
                    print(f"{_state}\n")
                    # =================================================
                    if result.get("winner") and result.get("state") in ("RESOLVED", "CONTINUED"):
                        best_payoff = result["winner"]
                        payoff_idx = best_payoff.get("idxs", [best_payoff.get("idx")])[-1]
                        c["locked_payoff_idx"] = payoff_idx
                        c["locked_payoff_time"] = best_payoff["end"]
                        c["locked_payoff_text"] = best_payoff["text"]
                        c["payoff_source"] = "PAYOFF_ENGINE"
                        c["payoff_engine_score"] = best_payoff.get("final_score", 0.0)
                        if "tier3_title" in best_payoff:
                            c["clip_title"] = best_payoff["tier3_title"]
                        _resolve_contract_from_payoff(
                            ctx,
                            c,
                            hook_start=float(hook_start),
                            hook_trigger=dict(transcript[hook_idx] or {}),
                            payoff_idx=int(payoff_idx) if payoff_idx is not None else None,
                            payoff_seg={
                                "start": best_payoff.get("start"),
                                "end": best_payoff.get("end"),
                                "text": best_payoff.get("text", ""),
                            },
                            resolution_score=float(best_payoff.get("final_score", 0.0) or 0.0),
                            payoff_source="PAYOFF_ENGINE",
                        )
                        completed += 1
                except Exception as _pe_exc:
                    log.warning("[STORY_COMPLETION] PayoffEngine failed cid=%s: %s", c.get("cid", c.get("id", "?")), _pe_exc)

            if best_payoff is None:
                try:
                    from utils.payoff_resolver import PayoffResolver
                    _resolver = PayoffResolver()
                    hook_text_val = str(transcript[hook_idx].get("text", "") or "")
                    hook_start_val = float(transcript[hook_idx].get("start", 0) or 0)
                    resolver_seg = _resolver.find(
                        hook_text=hook_text_val,
                        hook_start_s=hook_start_val,
                        candidate_window=candidate_window,
                        full_transcript=list(transcript),
                        thread_id=str(c.get("cid", c.get("id", "unknown"))),
                        run_tier3=True,
                    )
                    if resolver_seg:
                        tier = resolver_seg.get("tier", "?")
                        tier_score = resolver_seg.get(
                            f"tier{tier}_score",
                            resolver_seg.get("tier1_score", resolver_seg.get("tier2_score", 0.5)),
                        )
                        payoff_idx = resolver_seg.get("idx")
                        before_locked_idx = c.get("locked_payoff_idx")
                        c["locked_payoff_idx"] = payoff_idx
                        c["locked_payoff_time"] = resolver_seg.get("end")
                        c["locked_payoff_text"] = resolver_seg.get("text", "")
                        _audit_field_mutation(c, "locked_payoff_idx", before_locked_idx, payoff_idx, "_run_story_completion()", inspect.currentframe().f_lineno)
                        c["payoff_source"] = f"TIER{tier}"
                        c["payoff_engine_score"] = tier_score
                        if "tier3_title" in resolver_seg:
                            c["clip_title"] = resolver_seg["tier3_title"]
                        _resolve_contract_from_payoff(
                            ctx,
                            c,
                            hook_start=float(hook_start),
                            hook_trigger=dict(transcript[hook_idx] or {}),
                            payoff_idx=int(payoff_idx) if payoff_idx is not None else None,
                            payoff_seg={
                                "start": resolver_seg.get("start"),
                                "end": resolver_seg.get("end"),
                                "text": resolver_seg.get("text", ""),
                            },
                            resolution_score=float(tier_score or 0.0),
                            payoff_source=f"TIER{tier}",
                        )
                        completed += 1
                    else:
                        failed += 1
                except Exception as _res_exc:
                    failed += 1
                    log.warning("[STORY_COMPLETION] PayoffResolver failed cid=%s: %s", c.get("cid", c.get("id", "?")), _res_exc)

        _audit_candidate_state(ctx, "StoryCompletion", c, hook_idx=hook_idx, payoff_idx=payoff_idx)

    _record_stage(
        ctx,
        "L10A_STORY_COMPLETION",
        input=len(candidates),
        completed=completed,
        failed=failed,
        wall_s=round(time.time() - t0, 3),
    )
    log.info("[STORY_COMPLETION] input=%d completed=%d failed=%d", len(candidates), completed, failed)


def _run_arc_assembler_v2(ctx: PipelineContext) -> None:
    t0 = time.time()
    transcript = list(ctx.transcript or [])
    # FIX1: Assembler runs before Ranking, so it must read from validated_candidates.
    ranked = list(ctx.validated_candidates or [])
    _audit_stage_snapshot("ARC_ASSEMBLER_IN", ranked)
    if (not transcript) or (not ranked):
        _record_stage(ctx, "L10_ARC_ASSEMBLER", input=len(ranked), arcs=0, complete=0, wall_s=round(time.time() - t0, 3))
        return

    min_clip = 25.0  # Increased from 5.0 to 25.0 to prevent 20-second mechanical clips
    base_max_clip = 60.0  # Reduced back from 90s to 60s (P2 Fix for messy clips)
    lookback_s = 7.0
    out: List[Dict[str, Any]] = []
    complete_count = 0

    def _seg_bounds(seg: Dict[str, Any]) -> tuple[float, float]:
        ss = float(seg.get("start", 0.0) or 0.0)
        ee = float(seg.get("end", ss) or ss)
        return ss, max(ss, ee)

    def _find_seg_index(ts: float) -> int:
        target = float(ts or 0.0)
        for i, seg in enumerate(transcript):
            s, e = _seg_bounds(seg)
            if s <= target <= e:
                return i
        return max(0, min(len(transcript) - 1, 0 if not transcript else int(min(range(len(transcript)), key=lambda j: abs(_seg_bounds(transcript[j])[0] - target)))))

    import concurrent.futures as _cf

    def _assemble_one(cand):
        c = dict(cand or {})
        if isinstance(cand, dict):
            _audit_field_mutation(cand, "dict(candidate)", cand.get("cid", cand.get("id", cand.get("trace_id"))), c.get("cid", c.get("id", c.get("trace_id"))), "_assemble_one()", inspect.currentframe().f_lineno)
        s0 = float(c.get("start", 0.0) or 0.0)
        e0 = float(c.get("end", s0) or s0)
        if e0 <= s0:
            return c

        nar = (c.get("signals", {}) or {}).get("narrative", {}) or {}
        psych = (c.get("signals", {}) or {}).get("psychology", {}) or {}
        sem = (c.get("signals", {}) or {}).get("semantic", {}) or {}
        candidate_curiosity_peak = _clamp01(psych.get("curiosity_peak", psych.get("curiosity", 0.0)))
        candidate_semantic_quality = _clamp01(sem.get("semantic_quality", c.get("confidence", 0.0)))

        # Candidate metadata identifies the onset, but its Hook Hunter confidence
        # is provenance only.  The canonical score is measured below from the
        # assembled arc and must be the value exposed in selection telemetry.
        hook_hunter_confidence = 0.0
        if c.get("hook_segment"):
            hook_idx = int(c["hook_segment"].get("idx", _find_seg_index(s0)))
            hook_seg = transcript[hook_idx]
            hook_hunter_confidence = _clamp01(c["hook_segment"].get("score", c.get("hook_strength", 0.0)))
        elif c.get("hook_idx") is not None:
            hook_idx = int(c["hook_idx"])
            hook_seg = transcript[hook_idx]
            hook_hunter_confidence = _clamp01(c.get("hook_strength", 0.0))
        else:
            hook_idx = _find_seg_index(s0)
            hook_seg = transcript[hook_idx]
            hook_hunter_confidence = _clamp01(c.get("hook_strength", 0.0))
            
        hook_found = True
        why_selected = "candidate onset (Hook Hunter); score measured by Arc Assembler"

        hook_seg = transcript[hook_idx]
        hook_start, hook_end = _seg_bounds(hook_seg)
        
        protect_bounds = bool(c.get("cortex_enabled") or c.get("contract_seed") or c.get("_injected_from_trigger"))
        
        if protect_bounds:
            # LLM-injected candidates already have perfect, sentence-aware boundaries.
            # Bypassing the blind ArcAssembler geometry.
            arc_start = s0
            arc_end = e0
            max_clip = 300.0  # Allow up to 5 mins for LLM arcs
        else:
            arc_start = hook_start
            # Backward expansion removed to start exactly at hook
            arc_end = hook_end
            max_clip = base_max_clip
            
        payoff_idx = None

        # BUILD + PAYOFF: Payoff Engine V1 (Narrative Resolver)
        candidate_window = []
        for tmp_j in range(hook_idx, len(transcript)):
            tmp_seg_s, tmp_seg_e = _seg_bounds(transcript[tmp_j])
            if (tmp_seg_e - arc_start) > max_clip:
                break
            candidate_window.append({
                "idx": tmp_j,
                "start": tmp_seg_s,
                "end": tmp_seg_e,
                "text": str(transcript[tmp_j].get("text", "") or "")
            })

        payoff_idx = None
        best_payoff = None

        tid = c.get("trace_id", c.get("id", "unknown"))
        st = None
        if tid and hasattr(ctx, "candidate_threads") and tid in ctx.candidate_threads:
            st = ctx.candidate_threads[tid]

        # Arc is geometry only: consume payoff/completion selected upstream.
        locked_payoff_idx = c.get("locked_payoff_idx")
        locked_payoff_time = c.get("locked_payoff_time")
        if locked_payoff_idx is not None:
            try:
                payoff_idx = max(0, min(len(transcript) - 1, int(locked_payoff_idx)))
            except Exception:
                payoff_idx = None
        if locked_payoff_time is not None:
            try:
                arc_end = max(arc_end, float(locked_payoff_time))
            except Exception:
                pass
        elif (c.get("completeness_signal") == "RESOLVED" or c.get("contract_seed")) and c.get("end"):
            arc_end = max(arc_end, float(c.get("end", arc_end) or arc_end))


        # Preserving payoff_idx even if it equals hook_idx.
        # A 1-sentence hook that delivers its own punchline is a valid zero-duration arc.
        if payoff_idx is not None and payoff_idx < hook_idx:
            # Only clear if it hallucinates backwards
            payoff_idx = None

        if not protect_bounds:
            # ---- INSIGHT TAIL EXTENSION (safe) ----
            tail_limit = min((payoff_idx + 3) if payoff_idx is not None else (hook_idx + 3), len(transcript))
            for k in range((payoff_idx + 1) if payoff_idx is not None else (hook_idx + 1), tail_limit):
                seg_s, seg_e = _seg_bounds(transcript[k])
                seg_text = str(transcript[k].get("text", "") or "")
                seg_scores = compute_quality_scores(transcript, arc_start, seg_e) if compute_quality_scores else {}
                info_density = _clamp01(seg_scores.get("information_density_score", 0.0))
                semantic_quality = _clamp01(seg_scores.get("semantic_quality", 0.0))
                # Extend only if explanation/insight continues.
                if info_density > 0.12 or semantic_quality > 0.55:
                    arc_end = max(arc_end, seg_e)
                else:
                    break
    
            # Enforce min duration by extending forward.
            if (arc_end - arc_start) < min_clip:
                import logging
                logging.getLogger("orchestrator").info(f"\n[CONSTRAINT_HIT] constraint=min_clip_15 candidate={c.get('cid', '?')} natural_duration={arc_end - arc_start:.1f} forced_extension=yes\n")
                for k in range((payoff_idx + 1) if payoff_idx is not None else (hook_idx + 1), len(transcript)):
                    _, seg_e = _seg_bounds(transcript[k])
                    arc_end = max(arc_end, seg_e)
                    if (arc_end - arc_start) >= min_clip:
                        break
    
            # Clamp and complete trailing sentence.
            # Start exactly at the hook.
            # arc_start = max(0.0, arc_start - 1.5)
            arc_end = min(arc_end, arc_start + max_clip)
            arc_end = max(arc_end, arc_start + min_clip)
            # Removed legacy 18s->22s fallback padding to respect narrative bounds

        hook_seg = transcript[hook_idx]
        hook_start, hook_end = _seg_bounds(hook_seg)
        
        protect_bounds = bool(c.get("cortex_enabled") or c.get("contract_seed") or c.get("_injected_from_trigger"))
        
        if protect_bounds:
            # LLM-injected candidates already have perfect, sentence-aware boundaries.
            # Bypassing the blind ArcAssembler geometry.
            arc_start = s0
            arc_end = e0
            max_clip = 300.0  # Allow up to 5 mins for LLM arcs
        else:
            arc_start = hook_start
            # Backward expansion removed to start exactly at hook
            arc_end = hook_end
            max_clip = base_max_clip
            
        payoff_idx = None

        # BUILD + PAYOFF: Payoff Engine V1 (Narrative Resolver)
        candidate_window = []
        for tmp_j in range(hook_idx, len(transcript)):
            tmp_seg_s, tmp_seg_e = _seg_bounds(transcript[tmp_j])
            if (tmp_seg_e - arc_start) > max_clip:
                break
            candidate_window.append({
                "idx": tmp_j,
                "start": tmp_seg_s,
                "end": tmp_seg_e,
                "text": str(transcript[tmp_j].get("text", "") or "")
            })

        payoff_idx = None
        best_payoff = None

        tid = c.get("trace_id", c.get("id", "unknown"))
        st = None
        if tid and hasattr(ctx, "candidate_threads") and tid in ctx.candidate_threads:
            st = ctx.candidate_threads[tid]

        # Arc is geometry only: consume payoff/completion selected upstream.
        locked_payoff_idx = c.get("locked_payoff_idx")
        locked_payoff_time = c.get("locked_payoff_time")
        if locked_payoff_idx is not None:
            try:
                payoff_idx = max(0, min(len(transcript) - 1, int(locked_payoff_idx)))
            except Exception:
                payoff_idx = None
        if locked_payoff_time is not None:
            try:
                arc_end = max(arc_end, float(locked_payoff_time))
            except Exception:
                pass
        elif (c.get("completeness_signal") == "RESOLVED" or c.get("contract_seed")) and c.get("end"):
            arc_end = max(arc_end, float(c.get("end", arc_end) or arc_end))


        # Preserving payoff_idx even if it equals hook_idx.
        # A 1-sentence hook that delivers its own punchline is a valid zero-duration arc.
        if payoff_idx is not None and payoff_idx < hook_idx:
            # Only clear if it hallucinates backwards
            payoff_idx = None

        if not protect_bounds:
            # ---- INSIGHT TAIL EXTENSION (safe) ----
            tail_limit = min((payoff_idx + 3) if payoff_idx is not None else (hook_idx + 3), len(transcript))
            for k in range((payoff_idx + 1) if payoff_idx is not None else (hook_idx + 1), tail_limit):
                seg_s, seg_e = _seg_bounds(transcript[k])
                seg_text = str(transcript[k].get("text", "") or "")
                seg_scores = compute_quality_scores(transcript, arc_start, seg_e) if compute_quality_scores else {}
                info_density = _clamp01(seg_scores.get("information_density_score", 0.0))
                semantic_quality = _clamp01(seg_scores.get("semantic_quality", 0.0))
                # Extend only if explanation/insight continues.
                if info_density > 0.12 or semantic_quality > 0.55:
                    arc_end = max(arc_end, seg_e)
                else:
                    break
    
            # Enforce min duration by extending forward.
            if (arc_end - arc_start) < min_clip:
                import logging
                logging.getLogger("orchestrator").info(f"\n[CONSTRAINT_HIT] constraint=min_clip_15 candidate={c.get('cid', '?')} natural_duration={arc_end - arc_start:.1f} forced_extension=yes\n")
                for k in range((payoff_idx + 1) if payoff_idx is not None else (hook_idx + 1), len(transcript)):
                    _, seg_e = _seg_bounds(transcript[k])
                    arc_end = max(arc_end, seg_e)
                    if (arc_end - arc_start) >= min_clip:
                        break
    
            # Clamp and complete trailing sentence.
            # Start exactly at the hook.
            # arc_start = max(0.0, arc_start - 1.5)
            arc_end = min(arc_end, arc_start + max_clip)
            arc_end = max(arc_end, arc_start + min_clip)
            # Removed legacy 18s->22s fallback padding to respect narrative bounds
            arc_end = extend_until_sentence_complete(arc_start, arc_end, transcript, max_extend=4.0)
            arc_end = min(arc_end, arc_start + max_clip)

        arc_scores = compute_quality_scores(transcript, arc_start, arc_end) if compute_quality_scores else {}
        open_loop_tail = _clamp01(arc_scores.get("open_loop_score", 0.0))
        tid = c.get("trace_id", c.get("id"))
        if tid and hasattr(ctx, "candidate_threads") and tid in ctx.candidate_threads:
            st = ctx.candidate_threads[tid]
            st.propose_boundary(
                stage="ARC_ASSEMBLER",
                before_start=round(s0, 2),
                before_end=round(e0, 2),
                after_start=round(float(arc_start), 2),
                after_end=round(float(arc_end), 2),
                reason="payoff_found" if payoff_idx is not None else "horizon_expired",
                confidence=round(float(arc_score), 4)
            )
            if payoff_idx is not None:
                st.propose_state("ARC_ASSEMBLER", "PAYOFF_CANDIDATE", "Payoff selected by Arc Assembler", round(float(arc_score), 4))
                if st.state not in ["RESOLVED", "CONTINUED"]:
                    st.state = "PAYOFF_CANDIDATE"
                    st.payoff_candidate = str(payoff_seg.get("text", "") or "")
                st.add_history("ARC_ASSEMBLER", "PAYOFF_CANDIDATE", "Payoff selected by Arc Assembler", round(float(arc_score), 4))
            else:
                st.propose_state("ARC_ASSEMBLER", "OPEN", "No payoff found within horizon", 0.0)
                st.add_history("ARC_ASSEMBLER", "SEARCH_FAILED", "No payoff found within horizon", 0.0)

        if open_loop_tail > 0.5 and not protect_bounds:
            arc_end = min(arc_end + 6.0, arc_start + max_clip)
            arc_scores = compute_quality_scores(transcript, arc_start, arc_end) if compute_quality_scores else {}
        hook_score = _clamp01(arc_scores.get("hook_score", nar.get("hook_score", 0.0)))
        final_hook_score = hook_score
        
        legacy_payoff_resolution = _clamp01(arc_scores.get("payoff_resolution_score", nar.get("payoff_resolution_score", 0.0)))
        engine_score = c.get("payoff_engine_score", 0.0)
        if payoff_idx is None and engine_score > 0:
            print(
                "[ARC_INVARIANT]",
                c.get("id", c.get("cid")),
                engine_score,
                c.get("payoff_source"),
                c.get("completion_state"),
                c.get("arc_score"),
            )
        
        if engine_score > 0.0:
            payoff_resolution = engine_score
        else:
            payoff_resolution = legacy_payoff_resolution
            
        tension_gradient = _clamp01(psych.get("tension_gradient", 0.0))
        info_density = _clamp01(arc_scores.get("information_density_score", nar.get("information_density_score", 0.0)))
        rewatch = _clamp01(arc_scores.get("rewatch_score", nar.get("rewatch_score", 0.0)))
        arc_score = _clamp01(
            (0.30 * hook_score)
            + (0.30 * payoff_resolution)
            + (0.20 * tension_gradient)
            + (0.10 * info_density)
            + (0.10 * rewatch)
        )
        if str(nar.get("trigger_type", "") or "") in ("belief_reversal", "complete_thought", "payoff"):
            arc_score = _clamp01(arc_score * 1.2)
        payoff_source = str(c.get("payoff_source", ""))
        payoff_score_val = c.get("payoff_engine_score", 0.0)
        is_strong_payoff = (payoff_score_val >= 0.55) or (payoff_source in ["TIER1"])
        arc_complete = bool(hook_found and (payoff_idx is not None) and is_strong_payoff)
        loop_state, loop_health = _psychological_loop_state(
            hook_found=hook_found,
            payoff_idx=payoff_idx,
            hook_idx=hook_idx,
            payoff_resolution=payoff_resolution,
            tension_gradient=tension_gradient,
            info_density=info_density,
            rewatch=rewatch,
        )
        if arc_complete and loop_state == "PARTIAL_PAYOFF":
            loop_state = "RESOLVED"
            loop_health = max(loop_health, 0.70)
        if arc_complete:
            arc_score = _clamp01(arc_score * 1.35)
        
        # 🔥 NARRATIVE DURATION SWEET SPOT BONUS - Strongly prefer 60-90s (Long Arc range)
        duration = arc_end - arc_start
        ideal_duration = 75.0
        duration_bonus = 0.0
        if 40.0 <= duration <= 120.0:
            # Maximum preference at 75s, soft decay at edges
            duration_bonus = max(0.0, 1.0 - (abs(duration - ideal_duration) / ideal_duration))
            arc_score = _clamp01(arc_score + (duration_bonus * 0.15))  # +0.15 max bonus

        print(
            "[ARC_SCORE_CALC]",
            c.get("cid", c.get("id")),
            "hook=", round(float(hook_score), 6),
            "payoff=", round(float(payoff_resolution), 6),
            "tension=", round(float(tension_gradient), 6),
            "info=", round(float(info_density), 6),
            "rewatch=", round(float(rewatch), 6),
        )
        tid = c.get("trace_id", c.get("id"))
        if tid and hasattr(ctx, "candidate_threads") and tid in ctx.candidate_threads:
            st = ctx.candidate_threads[tid]
            st.propose_boundary(
                stage="ARC_ASSEMBLER",
                before_start=round(s0, 2),
                before_end=round(e0, 2),
                after_start=round(float(arc_start), 2),
                after_end=round(float(arc_end), 2),
                reason="payoff_found" if payoff_idx is not None else "horizon_expired",
                confidence=round(float(arc_score), 4)
            )
            if payoff_idx is not None:
                st.propose_state("ARC_ASSEMBLER", "PAYOFF_CANDIDATE", "Payoff selected by Arc Assembler", round(float(arc_score), 4))
                if st.state not in ["RESOLVED", "CONTINUED"]:
                    st.state = "PAYOFF_CANDIDATE"
                    st.payoff_candidate = str(payoff_seg.get("text", "") or "")
                # DO NOT overwrite st.resolution_score. The PayoffEngine already set it natively based on the narrative contract.
                st.add_history("ARC_ASSEMBLER", "PAYOFF_CANDIDATE", "Payoff selected by Arc Assembler", round(float(arc_score), 4))
            else:
                st.propose_state("ARC_ASSEMBLER", "OPEN", "No payoff found within horizon", 0.0)
                st.add_history("ARC_ASSEMBLER", "SEARCH_FAILED", "No payoff found within horizon", 0.0)
        
        print(
            "base=(",
            "0.30*hook + 0.30*payoff + 0.20*tension + 0.10*info + 0.10*rewatch",
            ")=",
            round(float(arc_score), 6), # Note: simplified representation here for brevity relative to original
            "trigger_type=", nar.get("trigger_type"),
            "arc_complete=", arc_complete,
            "duration=", round(float(duration), 6),
            "duration_bonus=", round(float(duration_bonus * 0.15), 6),
            "final=", round(float(arc_score), 6),
            "stored=", round(float(arc_score), 4),
        )

        payoff_seg = transcript[payoff_idx] if payoff_idx is not None else transcript[min(len(transcript) - 1, hook_idx)]
        p_s, p_e = _seg_bounds(payoff_seg)
        print(f"[ARC] hook_idx={hook_idx} payoff_idx={payoff_idx} duration={arc_end - arc_start:.1f}s")
        c["start"] = round(float(arc_start), 2)
        _audit_field_mutation(c, "start", s0, c["start"], "_assemble_one()", inspect.currentframe().f_lineno)
        c["end"] = round(float(max(arc_start + 0.01, arc_end)), 2)
        _audit_field_mutation(c, "end", e0, c["end"], "_assemble_one()", inspect.currentframe().f_lineno)
        c["duration"] = round(float(c["end"] - c["start"]), 2)
        c["hook_segment"] = {
            "idx": int(hook_idx),
            "start": round(float(hook_start), 2),
            "end": round(float(hook_end), 2),
            "text": str(hook_seg.get("text", "") or ""),
        }
        c["payoff_segment"] = {
            "idx": int(payoff_idx if payoff_idx is not None else hook_idx),
            "start": round(float(p_s), 2),
            "end": round(float(p_e), 2),
            "text": str(payoff_seg.get("text", "") or ""),
        }
        c["arc_complete"] = arc_complete
        c["arc_score"] = round(float(arc_score), 4)
        c["viral_score"] = round(float(arc_score), 4)
        c["hook_score"] = round(float(hook_score), 4)
        c["hook_hunter_confidence"] = round(float(hook_hunter_confidence), 4)
        c["loop_state"] = loop_state
        c["loop_health"] = round(float(loop_health), 4)
        c["psychological_loop"] = {
            "state": loop_state,
            "health": round(float(loop_health), 4),
            "hook_found": bool(hook_found),
            "payoff_found": bool(payoff_idx is not None),
            "payoff_source": payoff_source or "none",
            "payoff_score": round(float(payoff_resolution), 4),
        }
        _audit_candidate_state(
            ctx,
            "ArcAssembler",
            c,
            hook_idx=hook_idx,
            payoff_idx=payoff_idx,
            loop_state=loop_state,
            resolution_score=payoff_resolution,
            arc_complete=arc_complete,
        )
        c["provenance"] = {"stage": "L10_ARC_ASSEMBLER"}
        c["hook_selection_trace"] = {
            "text": str(hook_seg.get("text", "") or ""),
            "score": round(float(final_hook_score), 4),
            "reason": why_selected,
            "hook_hunter_confidence": round(float(hook_hunter_confidence), 4),
        }
        
        tid = c.get("trace_id", c.get("id"))
        if tid and hasattr(ctx, "candidate_threads") and tid in ctx.candidate_threads:
            st = ctx.candidate_threads[tid]
            st.propose_boundary(
                stage="ARC_ASSEMBLER",
                before_start=round(s0, 2),
                before_end=round(e0, 2),
                after_start=round(float(arc_start), 2),
                after_end=round(float(arc_end), 2),
                reason="payoff_found" if payoff_idx is not None else "horizon_expired",
                confidence=round(float(arc_score), 4)
            )
            if payoff_idx is not None:
                st.propose_state("ARC_ASSEMBLER", "PAYOFF_CANDIDATE", "Payoff selected by Arc Assembler", round(float(arc_score), 4))
                if st.state not in ["RESOLVED", "CONTINUED"]:
                    st.state = "PAYOFF_CANDIDATE"
                    st.payoff_candidate = str(payoff_seg.get("text", "") or "")
                st.add_history("ARC_ASSEMBLER", "PAYOFF_CANDIDATE", "Payoff selected by Arc Assembler", round(float(arc_score), 4))
            else:
                st.propose_state("ARC_ASSEMBLER", "OPEN", "No payoff found within horizon", 0.0)
                st.add_history("ARC_ASSEMBLER", "SEARCH_FAILED", "No payoff found within horizon", 0.0)

        if os.environ.get("HS_TRACE_MODE", "false").strip().lower() == "true":
            tid = c.get("trace_id")
            if tid:
                ctx.trace_state(tid, "EXPANDED")
                ctx.trace_event(
                    trace_id=tid,
                    stage="ARC_ASSEMBLER",
                    event="EXPANDED",
                    changed=(round(float(arc_end), 2) != round(e0, 2) or round(float(arc_start), 2) != round(s0, 2)),
                    impact="HIGH" if (round(float(arc_end), 2) != round(e0, 2)) else "LOW",
                    before={"start": round(s0, 2), "end": round(e0, 2)},
                    after={"start": round(float(arc_start), 2), "end": round(float(arc_end), 2)}
                )
                if payoff_idx is not None:
                    ctx.trace_state(tid, "PAYOFF_FOUND")
                    ctx.trace_event(
                        trace_id=tid,
                        stage="PAYOFF_SELECTION",
                        event="PAYOFF_SELECTED",
                        changed=True,
                        impact="HIGH",
                        after={"payoff_idx": payoff_idx, "payoff_text": str(payoff_seg.get("text", "") or "")}
                    )

        assert int(c["hook_segment"]["idx"]) == int(hook_idx), f"ARC_ASSEMBLER_HOOK_MUTATION: {c['hook_segment']['idx']} != {hook_idx}"
        return c

    # --- Run all candidates in parallel (Tier2 embeddings are the bottleneck) ---
    MAX_ARC_WORKERS = min(8, max(1, len(ranked)))
    with _cf.ThreadPoolExecutor(max_workers=MAX_ARC_WORKERS) as _pool:
        _futures = [_pool.submit(_assemble_one, cand) for cand in ranked]
        out = []
        for _fut in _cf.as_completed(_futures):
            try:
                _result = _fut.result()
                if _result is not None:
                    out.append(_result)
            except AssertionError:
                raise
            except Exception as _arc_exc:
                import logging
                logging.getLogger("orchestrator").warning("[ARC_ASSEMBLER] parallel worker failed: %s", _arc_exc)

    complete_count = sum(1 for c in out if c.get("arc_complete"))

    out = sorted(
        out,
        key=lambda x: (
            _rank_score(x, "arc_score", "viral_score", "score_enriched", "score"),
            _rank_score(x, "viral_score", "score_enriched", "score"),
            _rank_score(x, "score_enriched", "score"),
        ),
        reverse=True,
    )
    # � SMART DEDUPLICATION: Uses overlap-ratio based detection instead of strict time tolerance
    # Fixes duplicate_arcs from overlapping hooks (e.g. hooks 56-59 on same payoff 63)
    out = dedupe_by_overlap(out, overlap_threshold=0.40)
    
    top_k_limit = max(1, int(ctx.top_k or 1))
    if len(out) > top_k_limit:
        import logging
        logging.getLogger("orchestrator").info(f"\n[CONSTRAINT_HIT] constraint=top_k_{top_k_limit} survived_candidates={len(out)} kept={top_k_limit} discarded={len(out) - top_k_limit}\n")
        
    ctx.final_candidates = list(out[:top_k_limit])
    ctx.ranked_output = list(ctx.final_candidates)

    def _audit_key(candidate: Dict[str, Any]) -> Any:
        return candidate.get("cid", candidate.get("id", candidate.get("trace_id")))

    kept_keys = {_audit_key(c) for c in ctx.ranked_output if isinstance(c, dict)}
    survived_keys = {_audit_key(c) for c in out if isinstance(c, dict)}
    for c in ranked:
        if not isinstance(c, dict):
            continue
        key = _audit_key(c)
        if key in kept_keys:
            _audit_candidate_state(ctx, "ArcAssemblerFinal", c)
        elif key in survived_keys:
            _audit_candidate_state(ctx, "ArcAssemblerFinal", c, drop_reason="dropped_by_top_k_limit")
        else:
            _audit_candidate_state(ctx, "ArcAssemblerFinal", c, drop_reason="dropped_during_overlap_deduplication")

    contracts_total = len(getattr(ctx, "narrative_contracts", []) or [])
    contracts_resolved = sum(
        1 for contract in (getattr(ctx, "narrative_contracts", []) or [])
        if float(getattr(contract, "resolution_score", 0.0) or 0.0) > 0.0
    )
    log.info(
        "[ORCH-ARC] assembled=%d complete=%d input=%d contracts_resolved_after_payoff=%d/%d",
        len(ctx.ranked_output),
        complete_count,
        len(ranked),
        contracts_resolved,
        contracts_total,
    )

    from viral_finder.system_observer import get_observer
    obs = get_observer()
    obs.log_stage(
        "ARC_ASSEMBLER",
        input_count=len(ranked),
        output_count=len(ctx.ranked_output),
        wall_time=time.time() - t0
    )
    # Trace candidates
    output_dict = {c.get("cid"): c for c in ctx.ranked_output if c.get("cid")}
    for c in ranked:
        cid = c.get("cid")
        if cid:
            if cid in output_dict:
                out_cand = output_dict[cid]
                obs.modify_candidate(
                    cid,
                    "arc_assembler",
                    {
                        "start": out_cand.get("start"),
                        "end": out_cand.get("end"),
                        "scores": {"arc_score": out_cand.get("arc_score")}
                    }
                )
            else:
                obs.reject_candidate(cid, "arc_assembler", "dropped_during_overlap_deduplication_or_top_k_limit")

    _record_stage(
        ctx,
        "L10_ARC_ASSEMBLER",
        input=len(ranked),
        arcs=len(ctx.ranked_output),
        complete=complete_count,
        contracts_resolved_after_payoff=contracts_resolved,
        contracts_total=contracts_total,
        origins=dict(sorted(Counter(_candidate_origin(c) for c in ctx.ranked_output).items())),
        avg_arc_duration=round(sum(float(c.get("duration", 0.0) or 0.0) for c in ctx.ranked_output) / float(max(1, len(ctx.ranked_output))), 3),
        wall_s=round(time.time() - t0, 3),
    )


def _run_editor_refiner(ctx: PipelineContext) -> None:
    t0 = time.time()
    clips = list(ctx.ranked_output or ctx.final_candidates or [])
    _audit_stage_snapshot("EDITOR_REFINER_IN", clips)
    transcript = list(ctx.transcript or [])
    if (not clips) or (not transcript):
        _record_stage(ctx, "L12_EDITOR_REFINER", input=len(clips), output=len(clips), wall_s=round(time.time() - t0, 3))
        return

    pre_pad = 1.2
    post_pad = 1.5
    pre_hook_context = 1.2
    ideal_len = 75.0
    max_silence_gap = 1.5
    out: List[Dict[str, Any]] = []
    rejected_final: List[Dict[str, Any]] = []

    def _seg_bounds(seg: Dict[str, Any]) -> tuple[float, float]:
        ss = float(seg.get("start", 0.0) or 0.0)
        ee = float(seg.get("end", ss) or ss)
        return ss, max(ss, ee)

    def _find_prev_seg(ts: float) -> Optional[Dict[str, Any]]:
        prev = None
        for seg in transcript:
            _, e = _seg_bounds(seg)
            if e <= ts:
                prev = seg
            else:
                break
        return prev

    def _segments_in_window(s: float, e: float) -> List[Dict[str, Any]]:
        return [seg for seg in transcript if _seg_bounds(seg)[1] > s and _seg_bounds(seg)[0] < e]

    def _motion_spike_at(ts: float) -> float:
        best = 0.0
        for vf in (ctx.visual_features or []):
            try:
                t = float(vf.get("t", vf.get("time", vf.get("start", 0.0))) or 0.0)
                if abs(t - ts) > 1.0:
                    continue
                best = max(best, _clamp01(vf.get("motion", vf.get("motion_energy", vf.get("frame_change", 0.0)))))
            except Exception:
                continue
        return best

    def _best_hook_segment_in_window(s: float, e: float, nar: Dict[str, Any], psych: Dict[str, Any]) -> tuple[Optional[Dict[str, Any]], float]:
        segs = sorted(_segments_in_window(s, e), key=lambda x: float(x.get("start", 0.0) or 0.0))
        if not segs:
            return None, 0.0
        best_seg = None
        best_strength = 0.0
        for seg in segs:
            ss, ee = _seg_bounds(seg)
            q = compute_quality_scores(transcript, ss, ee) if compute_quality_scores else {}
            hook_score = _clamp01(q.get("hook_score", nar.get("hook_score", 0.0)))
            pattern_break = _clamp01(q.get("pattern_break_score", nar.get("pattern_break_score", 0.0)))
            curiosity_peak = _clamp01(psych.get("curiosity_peak", psych.get("curiosity", 0.0)))
            trigger_type = str(nar.get("trigger_type", "") or "")
            qualifies = (
                (hook_score > 0.25)
                or (pattern_break > 0.3)
                or (curiosity_peak > 0.3)
                or (trigger_type in ("belief_reversal", "complete_thought", "payoff"))
            )
            strength = _clamp01((0.45 * hook_score) + (0.35 * pattern_break) + (0.20 * curiosity_peak))
            if qualifies and (strength >= best_strength):
                best_strength = strength
                best_seg = seg
        return best_seg, best_strength

    for clip_idx, clip in enumerate(clips):
        c = dict(clip or {})
        if isinstance(clip, dict):
            _audit_field_mutation(clip, "dict(candidate)", clip.get("cid", clip.get("id", clip.get("trace_id"))), c.get("cid", c.get("id", c.get("trace_id"))), "_run_editor_refiner()", inspect.currentframe().f_lineno)
        s = float(c.get("start", 0.0) or 0.0)
        e = float(c.get("end", s) or s)
        orig_s = s
        orig_e = e
        if e <= s:
            out.append(c)
            continue

        # [EXPERIMENT V1] Check StoryThread Governor
        is_resolved = False
        tid = c.get("trace_id")
        if tid and tid in ctx.candidate_threads:
            st = ctx.candidate_threads[tid]
            if st.state in ("RESOLVED", "CONTINUED"):
                is_resolved = True

        # 1) Context padding
        s = max(0.0, s - pre_pad)
        if os.environ.get("HS_EXPERIMENT_MODE") != "1" and not is_resolved:
            e = e + post_pad

        if not is_resolved:
            # 2) Sentence boundary correction
            prev_seg = _find_prev_seg(s)
            if prev_seg:
                prev_text = str(prev_seg.get("text", "") or "").strip()
                _, prev_end = _seg_bounds(prev_seg)
                if prev_text.endswith((".", "?", "!")):
                    s = max(s, prev_end)

            # 3) REMOVED: Aggressive Silence Trim. It was destroying payoffs by cutting clips at 15s.

        # 5) Transition spike guard
        if _motion_spike_at(s) > 0.6:
            s = min(e - 0.5, s + 0.5)

        # Keep sane bounds
        if e <= s:
            e = s + 0.2
        duration = max(0.01, e - s)

        nar = (c.get("signals", {}) or {}).get("narrative", {}) or {}
        eng = (c.get("signals", {}) or {}).get("engagement", {}) or {}
        psych = (c.get("signals", {}) or {}).get("psychology", {}) or {}
        sem = (c.get("signals", {}) or {}).get("semantic", {}) or {}
        arc_score = _clamp01(c.get("arc_score", c.get("viral_score", 0.0)))
        motion_boost = _clamp01(eng.get("motion", 0.0))
        energy_boost = _clamp01(eng.get("energy", eng.get("classic", 0.0)))
        duration_score = _clamp01(1.0 - (abs(duration - ideal_len) / ideal_len))

        # Hook optimizer: respect Arc Assembler's choice first
        if "hook_segment" in c and c["hook_segment"]:
            hook_seg = c["hook_segment"]
            hook_strength = _clamp01(float(c.get("hook_strength", c.get("hook_score", 0.0)) or 0.0))
        else:
            hook_seg, hook_strength = _best_hook_segment_in_window(s, e, nar, psych)
            
        hook_offset = 0.0
        if hook_seg:
            hs, he = _seg_bounds(hook_seg)
            hook_offset = max(0.0, hs - s)
            # Weak-hook recovery: search forward for stronger pattern-break in window.
            _prov = c.get("provenance", {})
            _is_assembled = (_prov.get("stage") == "L10_ARC_ASSEMBLER") if isinstance(_prov, dict) else (_prov == "L10_ARC_ASSEMBLER")
            if hook_strength < 0.15 and not _is_assembled:
                for seg in sorted(_segments_in_window(s, e), key=lambda x: float(x.get("start", 0.0) or 0.0)):
                    ss, ee = _seg_bounds(seg)
                    q = compute_quality_scores(transcript, ss, ee) if compute_quality_scores else {}
                    if _clamp01(q.get("pattern_break_score", 0.0)) > 0.35:
                        hook_seg = seg
                        hs, he = _seg_bounds(hook_seg)
                        hook_strength = _clamp01((0.45 * _clamp01(q.get("hook_score", 0.0))) + (0.35 * _clamp01(q.get("pattern_break_score", 0.0))) + (0.20 * _clamp01(psych.get("curiosity_peak", psych.get("curiosity", 0.0)))))
                        hook_offset = max(0.0, hs - s)
                        break
            # Reposition start if hook appears late.
            # [DRAGON SLAIN] Disabled aggressive trimming that was destroying Arc Assembler build-ups
            if hook_offset > 999.0: # Was 3.0
                s = max(0.0, max(hs - pre_hook_context, s))
                hook_offset = max(0.0, hs - s)
            # Hook context padding (final guard)
            s = max(0.0, min(s, hs - pre_hook_context))
            hook_offset = max(0.0, hs - s)
        duration = max(0.01, e - s)

        editor_score = _clamp01((0.15 * max(motion_boost, energy_boost)) + (0.10 * duration_score) + (0.20 * _clamp01(nar.get("hook_score", 0.0))))
        final_score = _clamp01((0.75 * arc_score) + (0.25 * editor_score))
        if hook_strength > 0.35:
            final_score = _clamp01(final_score * 1.25)
        hook_text = ""
        if hook_seg:
            hook_text = str(hook_seg.get("text", "") or "").lower()
            if any(p in hook_text for p in ("most people think", "but the truth is", "this changed everything", "the problem is")):
                final_score = _clamp01(final_score * 1.15)
        low_priority = bool(hook_offset > (duration * 0.4))
        if low_priority:
            final_score = _clamp01(final_score * 0.85)
        
        # 🔥 SAFETY: Penalize ultra-short clips (< 8s) - still allows them but ranks lower
        if duration < 8.0:
            low_priority = True
            final_score = _clamp01(final_score * 0.70)  # Reduce by 30% for ultra-short clips

        clip_scores = compute_quality_scores(transcript, s, e) if compute_quality_scores else {}
        hook_metric = _clamp01(clip_scores.get("hook_score", nar.get("hook_score", hook_strength)))
        open_loop_metric = _clamp01(clip_scores.get("open_loop_score", nar.get("open_loop_score", 0.0)))
        payoff_metric = _clamp01(clip_scores.get("payoff_resolution_score", nar.get("payoff_resolution_score", 0.0)))
        build_text = ""
        payoff_seg_obj = c.get("payoff_segment") if isinstance(c.get("payoff_segment"), dict) else None
        if hook_seg and payoff_seg_obj:
            hook_end_for_build = float(hook_seg.get("end", 0.0) or 0.0)
            payoff_start_for_build = float(payoff_seg_obj.get("start", hook_end_for_build) or hook_end_for_build)
            parts = []
            for seg in transcript:
                seg_s, _ = _seg_bounds(seg)
                if hook_end_for_build <= seg_s <= payoff_start_for_build:
                    parts.append(str(seg.get("text", "") or "").strip())
            build_text = " ".join([p for p in parts if p]).strip()

        patterns = []
        if detect_story_pattern:
            try:
                patterns = list(detect_story_pattern(c) or [])
            except Exception:
                patterns = []
        c["story_patterns"] = patterns
        print(f"[PATTERN] clip={int(clip_idx)} patterns={patterns}")

        c["start"] = round(float(s), 2)
        _audit_field_mutation(c, "start", orig_s, c["start"], "_run_editor_refiner()", inspect.currentframe().f_lineno)
        
        # Payoff Boundary Lock (Experiment Mode)
        locked_payoff_time = c.get("locked_payoff_time")
        locked_payoff_text = c.get("locked_payoff_text")
        tid = c.get("trace_id", c.get("id"))
        
        is_resolved = False
        if tid and tid in ctx.candidate_threads:
            is_resolved = (ctx.candidate_threads[tid].state in ("RESOLVED", "CONTINUED"))
        
        if os.environ.get("HS_EXPERIMENT_MODE") == "1" and locked_payoff_time is not None and is_resolved:
            final_end_cap = float(locked_payoff_time) + 2.0
            new_e = min(float(e), final_end_cap)
            
            cid = c.get("cid", c.get("id", "?"))
            final_segs = sorted(_segments_in_window(s, new_e), key=lambda x: float(x.get("start", 0.0) or 0.0))
            final_text = final_segs[-1].get("text", "") if final_segs else ""
            
            log.info("\n[PAYOFF_LIFECYCLE]")
            log.info(f"candidate_id={cid}")
            log.info(f"assembler_payoff_text=\"{locked_payoff_text}\"")
            log.info(f"final_payoff_text=\"{final_text}\"")
            log.info(f"changed={locked_payoff_text != final_text}\n")
            
            e = new_e
            
        if locked_payoff_time is not None and not _clip_contains_time({"start": s, "end": e}, locked_payoff_time):
            e = max(float(e), float(locked_payoff_time) + 0.25)
            log.info(
                "[PAYOFF_INVARIANT] restored editor end to keep locked payoff inside clip cid=%s payoff_time=%.2f end=%.2f",
                c.get("cid", c.get("id", "?")),
                float(locked_payoff_time),
                float(e),
            )

        c["end"] = round(float(e), 2)
        _audit_field_mutation(c, "end", orig_e, c["end"], "_run_editor_refiner()", inspect.currentframe().f_lineno)
        duration = max(0.01, float(e) - float(s))
        
        if tid and hasattr(ctx, "candidate_threads") and tid in ctx.candidate_threads:
            st = ctx.candidate_threads[tid]
            st.propose_boundary(
                stage="EDITOR_REFINER",
                before_start=round(orig_s, 2),
                before_end=round(orig_e, 2),
                after_start=round(float(s), 2),
                after_end=round(float(e), 2),
                reason="silence_trim_and_pad",
                confidence=1.0
            )

        c["duration"] = round(float(duration), 2)
        c["editor_score"] = round(float(editor_score), 4)
        c["editor_presentation_score"] = round(float(final_score), 4)
        c.setdefault("final_score", round(float(c.get("viral_score", final_score) or final_score), 4))
        c["hook_score"] = round(float(hook_metric), 4)
        c["open_loop_score"] = round(float(open_loop_metric), 4)
        c["payoff_score"] = round(float(c.get("payoff_engine_score", payoff_metric) or payoff_metric), 4)
        c["build_text"] = build_text
        c["hook_offset"] = round(float(hook_offset), 3)
        c["hook_strength"] = round(float(hook_strength), 4)
        c["low_priority"] = bool(low_priority)
        
        # 🔥 THUMBNAIL OPTIMIZATION: Find frame with highest motion OR curiosity_peak
        # Instead of using start frame, use the frame with most visual interest
        best_thumbnail_time = float(s)  # Default to clip start
        best_thumbnail_score = 0.0
        for vf in (ctx.visual_features or []):
            try:
                vf_time = float(vf.get("t", vf.get("time", vf.get("start", 0.0))) or 0.0)
                if s <= vf_time <= e:
                    motion = _clamp01(vf.get("motion", vf.get("motion_energy", vf.get("frame_change", 0.0))))
                    # Could also incorporate curiosity from psych signals
                    if motion > best_thumbnail_score:
                        best_thumbnail_score = motion
                        best_thumbnail_time = vf_time
            except Exception:
                continue
        c["thumbnail_frame_time"] = round(float(best_thumbnail_time), 2)
        c["thumbnail_motion_score"] = round(float(best_thumbnail_score), 3)
        
        if hook_seg:
            hs, he = _seg_bounds(hook_seg)
            c["hook_segment"] = {
                "start": round(float(hs), 2),
                "end": round(float(he), 2),
                "text": str(hook_seg.get("text", "") or ""),
            }
        log.info(
            "\n[CLIP %d]\nduration: %.1fs\narc_score: %.3f\neditor_presentation_score: %.3f\n"
            "HOOK_SCORE: %.3f\nOPEN_LOOP_SCORE: %.3f\nPAYOFF_SCORE: %.3f\n"
            "SEMANTIC: impact=%.3f meaning=%.3f novelty=%.3f clarity=%.3f\n\n"
            "HOOK:\n%s\n\nBUILD:\n%s\n\nPAYOFF:\n%s\n\nFULL MOMENT:\n%s\n",
            int(clip_idx),
            float(duration),
            float(arc_score),
            float(final_score),
            float(hook_metric),
            float(open_loop_metric),
            float(c["payoff_score"]),
            float(_clamp01(sem.get("impact", 0.0))),
            float(_clamp01(sem.get("meaning", 0.0))),
            float(_clamp01(sem.get("novelty", 0.0))),
            float(_clamp01(sem.get("clarity", 0.0))),
            str((c.get("hook_segment") or {}).get("text", "") or ""),
            str(build_text or ""),
            str((c.get("payoff_segment") or {}).get("text", "") or ""),
            str(c.get("text", "") or ""),
        )
        c["decision_owner"] = c.get("decision_owner", "RANKING")

        # FIX3: DECISION TIMELINE — record editor refiner changes
        _timeline = c.setdefault("decision_timeline", [])
        _timeline.append({
            "stage":  "EDITOR",
            "event":  "Final Polish",
            "reason": f"Presentation polish only. Ranking decision preserved at {float(c.get('viral_score', 0.0) or 0.0):.3f}",
            "score":  round(float(c.get("viral_score", 0.0) or 0.0), 4),
            "presentation_score": round(float(final_score), 4),
        })
        c["provenance"] = {"stage": "L12_EDITOR_REFINER"}
        final_reject_reasons = _final_quality_reject_reasons(c)
        c["final_quality"] = {
            "accepted": not final_reject_reasons,
            "reasons": list(final_reject_reasons),
            "rescued": False,
        }
        if final_reject_reasons:
            if _final_quality_rescue(c):
                c["final_quality"] = {
                    "accepted": True,
                    "reasons": ["semantic_explanation_rescue"],
                    "rescued": True,
                }
            else:
                for reason in final_reject_reasons:
                    log.info(
                        f"[EDITOR_REJECT] "
                        f"id={c.get('cid', c.get('candidate_id', 'unknown'))} "
                        f"reason={reason} "
                        f"start={c.get('start')} "
                        f"end={c.get('end')} "
                        f"duration={c.get('duration')} "
                        f"origin={c.get('origin', _candidate_origin(c))} "
                        f"groq={c.get('groq_moment')}"
                    )
                rejected_final.append(c)
                log.info(
                    "[FINAL-REJECT] %.2f-%.2f reasons=%s origin=%s final_score=%.3f",
                    float(c.get("start", 0.0) or 0.0),
                    float(c.get("end", 0.0) or 0.0),
                    final_reject_reasons,
                    _candidate_origin(c),
                    float(c.get("final_score", 0.0) or 0.0),
                )
                continue
        cid = c.get("cid")
        if cid:
            changes = {}
            if abs(c["start"] - orig_s) > 0.05:
                changes["start"] = c["start"]
            if abs(c["end"] - orig_e) > 0.05:
                changes["end"] = c["end"]
            if changes:
                from viral_finder.system_observer import get_observer
                try:
                    get_observer().modify_candidate(cid, "editor_refiner", changes)
                except Exception:
                    pass

        if os.environ.get("HS_TRACE_MODE", "false").strip().lower() == "true":
            tid = c.get("trace_id")
            if tid:
                # [EXPERIMENT V1] Write findings to Governor memory
                if tid in ctx.candidate_threads:
                    st = ctx.candidate_threads[tid]
                    st.add_history(
                        "EDITOR_REFINER", 
                        "REFINED_BOUNDARIES", 
                        f"Set final bounds to {c['start']}-{c['end']}s", 
                        float(c.get("viral_score", 0.0))
                    )
                    
                ctx.trace_state(tid, "EDITOR_REFINED")
                ctx.trace_event(
                    trace_id=tid,
                    stage="EDITOR_REFINER",
                    event="REFINED",
                    changed=(round(float(c["start"]), 2) != round(orig_s, 2) or round(float(c["end"]), 2) != round(orig_e, 2)),
                    impact="MEDIUM" if (round(float(c["end"]), 2) != round(orig_e, 2) or round(float(c["start"]), 2) != round(orig_s, 2)) else "LOW",
                    before={"start": round(orig_s, 2), "end": round(orig_e, 2)},
                    after={"start": round(float(c["start"]), 2), "end": round(float(c["end"]), 2)}
                )
        out.append(c)

    out = sorted(
        out,
        key=lambda x: int(x.get("ranking_rank", 10**9) or 10**9),
    )
    ctx.final_candidates = list(out[: max(1, int(ctx.top_k or 1))])
    ctx.ranked_output = list(ctx.final_candidates)

    from viral_finder.system_observer import get_observer
    obs = get_observer()
    
    reject_reasons = {}
    for c in rejected_final:
        for r in ((c.get("final_quality", {}) or {}).get("reasons", []) or []):
            reject_reasons[r] = reject_reasons.get(r, 0) + 1
            
    obs.log_stage(
        "EDITOR_REFINER",
        input_count=len(clips),
        output_count=len(ctx.ranked_output),
        wall_time=time.time() - t0,
        reject_reasons=reject_reasons
    )
    
    # Trace candidates
    output_cids = {c.get("cid") for c in ctx.ranked_output if c.get("cid")}
    for c in clips:
        cid = c.get("cid")
        if cid:
            if cid in output_cids:
                obs.finalize_candidate(cid, "final_clip_output")
            else:
                reasons = (c.get("final_quality", {}) or {}).get("reasons", [])
                obs.reject_candidate(cid, "editor_refiner", ", ".join(reasons) or "filtered_or_deduplicated")

    if ctx.target_min and len(ctx.ranked_output) < int(ctx.target_min):
        log.warning(
            "[ORCH-UNDERFLOW] final=%d target_min=%d raw=%d accepted=%d ranked=%d",
            len(ctx.ranked_output),
            int(ctx.target_min),
            len(ctx.raw_candidates or []),
            len(ctx.validated_candidates or []),
            len(clips),
        )
    _record_stage(
        ctx,
        "L12_EDITOR_REFINER",
        input=len(clips),
        output=len(ctx.ranked_output),
        rejected_final=len(rejected_final),
        rejected_reasons=dict(sorted(Counter(reason for c in rejected_final for reason in ((c.get("final_quality", {}) or {}).get("reasons", []) or [])).items())),
        origins=dict(sorted(Counter(_candidate_origin(c) for c in ctx.ranked_output).items())),
        avg_duration=round(sum(float(c.get("duration", 0.0) or 0.0) for c in ctx.ranked_output) / float(max(1, len(ctx.ranked_output))), 3),
        wall_s=round(time.time() - t0, 3),
    )



def _run_groq_surgeon(ctx: PipelineContext) -> None:
    import time
    from viral_finder.system_observer import get_observer
    t0 = time.time()
    final_candidates = list(ctx.ranked_output or [])
    _audit_stage_snapshot("GROQ_SURGEON_IN", final_candidates)
    full_transcript = getattr(ctx, 'transcript', [])
    _groq_pool = list(final_candidates)
    has_tf_moments = any(c.get('groq_moment') for c in final_candidates)
    # --- HOTSHORT CORTEX (GROQ) LAYER ---
    # Pass the RICHER pre-filter pool to Groq, not just the aggressive top-k.
    # If Groq returns clips → use them as final_candidates.
    # If Groq returns empty + fail_open → keep original final_candidates.
    try:
        from viral_finder.groq_cortex import is_groq_enabled, review_candidates_with_groq, _get_groq_api_key
        _groq_api_key = _get_groq_api_key()
        if is_groq_enabled() and _groq_api_key:
            if has_tf_moments:
                log.info("[GROQ_CORTEX] Skipping candidate-review Cortex because transcript-first Moment Director already discovered moments.")
            else:
                _experiment_mode = os.environ.get("HS_EXPERIMENT_MODE", "0") == "1"
                if _experiment_mode:
                    # [EXPERIMENT FIX] Send arc-assembled final_candidates to Surgeon
                    # so it sees correct 90s boundaries, not pre-assembly 6s fragments.
                    # Without this, EXTEND_RIGHT fires on wrong clips and CID matching fails.
                    _pool = list(final_candidates)
                    log.info("[GROQ_POOL_FIX] experiment_mode=1 → using final_candidates (arc-assembled) for Surgeon input")
                else:
                    _pool = _groq_pool if len(_groq_pool) > len(final_candidates) else final_candidates
                
                # ── SURGEON GATING: Emergency-Only ────────────────────────────────────────
                # Only send candidates to Surgeon that NEED it:
                #   (a) clip duration < 35s  → likely cut short, no payoff yet
                #   (b) no payoff signal     → missing arc resolution
                # Healthy long clips skip Surgeon entirely → saves TPM + latency.
                _SURGEON_MIN_DUR = 35.0
                _payoff_trigger_types = {"payoff", "complete_thought"}

                def _has_payoff_signal(cand: dict) -> bool:
                    """Check if a candidate already has a payoff trigger overlapping it."""
                    cs = float(cand.get("start", 0.0) or 0.0)
                    ce = float(cand.get("end", cs) or cs)
                    for tr in (ctx.narrative_triggers or []):
                        if tr.get("type") in _payoff_trigger_types:
                            ts = float(tr.get("start", 0.0) or 0.0)
                            te = float(tr.get("end", ts) or ts)
                            # Overlaps the candidate window?
                            if ts < ce and te > cs:
                                return True
                    return False

                _all_pool = list(_pool)
                _needs_surgeon = []
                _skipped_surgeon = []
                for _c in _all_pool:
                    _dur = float(_c.get("end", 0.0) or 0.0) - float(_c.get("start", 0.0) or 0.0)
                    _short = _dur < _SURGEON_MIN_DUR
                    _no_payoff = not _has_payoff_signal(_c)
                    if _short or _no_payoff:
                        _needs_surgeon.append(_c)
                    else:
                        _skipped_surgeon.append(_c)

                log.info(
                    f"[GROQ_SURGEON_GATE] pool={len(_all_pool)}"
                    f" → surgeon_queue={len(_needs_surgeon)} (short_or_no_payoff)"
                    f" | skipped={len(_skipped_surgeon)} (healthy long clips)"
                )
                _pool = _needs_surgeon
                pool_before_len = len(_all_pool)

                if not _pool:
                    log.info("[GROQ_CORTEX] Skipping — empty candidate pool.")
                else:
                    transcript = (final_candidates[0].get("transcript") if final_candidates else None)
                    log.info(
                        "[GROQ_CORTEX] groq_input_candidates_count=%d (ranked_output=%d, enriched_pool=%d)",
                        len(_pool), len(final_candidates), len(_groq_pool),
                    )
                    
                    groq_result = review_candidates_with_groq(_pool, full_transcript, ctx.candidate_threads)
                    
                    import re
                    def _check_quote_valid(q, segments):
                        if not q or q.lower() == "none": return False
                        clean_q = re.sub(r'[^a-z0-9]', '', q.lower())
                        if len(clean_q) < 10: return False
                        full_t = "".join([s.get("text", "") for s in segments])
                        clean_t = re.sub(r'[^a-z0-9]', '', full_t.lower())
                        return clean_q in clean_t
                        
                    
                    keep_count = 0
                    move_hook_count = 0
                    extend_right_count = 0
                    extend_right_valid = 0
                    extend_right_invalid = 0
                    reject_count = 0
                    rejection_types = {}
                    
                    for c in groq_result:
                        surgeon = c.get("groq_surgeon")
                        if surgeon:
                            dec = surgeon.get("decision", "")
                            if dec == "KEEP": keep_count += 1
                            elif dec == "MOVE_HOOK": move_hook_count += 1
                            elif dec == "EXTEND_RIGHT": 
                                extend_right_count += 1
                                pq = surgeon.get("proposed_payoff_quote", "")
                                if _check_quote_valid(pq, full_transcript):
                                    extend_right_valid += 1
                                else:
                                    extend_right_invalid += 1
                            elif dec == "REJECT": 
                                reject_count += 1
                                rej_type = surgeon.get("rejection_type", "NONE")
                                rejection_types[rej_type] = rejection_types.get(rej_type, 0) + 1
                            
                    log.info("\n[SURGEON_RESPONSE]")
                    log.info(f"keep={keep_count}")
                    log.info(f"move_hook={move_hook_count}")
                    log.info(f"extend_right={extend_right_count}")
                    log.info(f"reject={reject_count}")
                    for rt, count in rejection_types.items():
                        log.info(f"  {rt.lower()}={count}")
                        
                    log.info("\n[EXTEND_RIGHT_AUDIT]")
                    log.info(f"total={extend_right_count}")
                    log.info(f"valid_quote={extend_right_valid}")
                    log.info(f"invalid_quote={extend_right_invalid}")
                    acc = int((extend_right_valid / extend_right_count * 100) if extend_right_count > 0 else 0)
                    log.info(f"accuracy={acc}%\n")
                    
                    log.info("[GROQ_SURGEON] Phase 2: MOVE_HOOK execution active.")
                    for c in groq_result:
                        surgeon = c.get("groq_surgeon")
                        if surgeon:
                            dec = surgeon.get("decision", "")
                            try:
                                conf = float(surgeon.get("confidence", 0.0))
                            except ValueError:
                                conf = 0.0
                                
                            if dec == "MOVE_HOOK":
                                try:
                                    hook_idx = int(surgeon.get("hook_segment_index", -1))
                                except ValueError:
                                    hook_idx = -1
                                    
                                log.info(f"[SURGEON_MOVE_HOOK_EVAL] cid={c.get('cid', '?')} conf={conf} required=0.75 hook_idx={hook_idx} valid_bounds={0 <= hook_idx < len(full_transcript)}")
                                
                                if 0 <= hook_idx < len(full_transcript):
                                    old_start = float(c.get("start", 0.0))
                                    new_start = float(full_transcript[hook_idx].get("start", 0.0))
                                    
                                    move_distance = abs(old_start - new_start)
                                    
                                    old_text = ""
                                    for seg in full_transcript:
                                        ss = float(seg.get("start", 0.0))
                                        ee = float(seg.get("end", ss))
                                        if ss <= old_start <= max(ss, ee):
                                            old_text = str(seg.get("text", "")).strip()
                                            break
                                            
                                    new_text = str(full_transcript[hook_idx].get("text", "")).strip()
                                    cid = c.get("id", c.get("cid", "?"))
                                    
                                    if (conf >= 0.75 
                                        and move_distance <= 8.0 
                                        and new_text != old_text 
                                        and len(new_text.split()) >= 4):
                                        
                                        log.info("\n[HOOK_REPAIR]")
                                        log.info(f"candidate_id={cid}")
                                        log.info(f"old_start={old_start}")
                                        log.info(f"new_start={new_start}")
                                        log.info(f"old_hook_text={old_text}")
                                        log.info(f"new_hook_text={new_text}")
                                        log.info(f"confidence={conf}\n")
                                    
                                        
                                        c["start"] = new_start
                                        _audit_field_mutation(c, "start", old_start, new_start, "_run_groq_surgeon()", inspect.currentframe().f_lineno)
                                        
                                        # The candidates in groq_result are copies of final_candidates
                                        # We must write the repaired boundary back to the original objects
                                        for fc in final_candidates:
                                            if fc.get("cid") == cid and cid != "?":
                                                fc["start"] = new_start
                                                _audit_field_mutation(fc, "start", old_start, new_start, "_run_groq_surgeon()", inspect.currentframe().f_lineno)
                                                from viral_finder.system_observer import get_observer
                                                try:
                                                    get_observer().modify_candidate(cid, "surgeon_cortex", {"start": new_start})
                                                except Exception:
                                                    pass
                                                break
                                    else:
                                        log.info(f"[HOOK_REPAIR_BLOCKED] cid={cid} conf={conf} dist={move_distance}s old_text='{old_text}' new_text='{new_text}'")
                                            
                            elif dec == "EXTEND_RIGHT":
                                try:
                                    payoff_idx = int(surgeon.get("payoff_segment_index", -1))
                                except ValueError:
                                    payoff_idx = -1
                                    
                                if 0 <= payoff_idx < len(full_transcript):
                                    start_ts = float(c.get("start", 0.0))
                                    end_ts = float(c.get("end", 0.0))
                                    
                                    hook_text = ""
                                    for seg in full_transcript:
                                        ss = float(seg.get("start", 0.0))
                                        ee = float(seg.get("end", ss))
                                        if ss <= start_ts <= max(ss, ee):
                                            hook_text = str(seg.get("text", "")).strip()
                                            break
                                            
                                    old_end_text = ""
                                    for seg in full_transcript:
                                        ss = float(seg.get("start", 0.0))
                                        ee = float(seg.get("end", ss))
                                        if ss <= end_ts <= max(ss, ee):
                                            old_end_text = str(seg.get("text", "")).strip()
                                            break
                                            
                                    new_end_text = str(full_transcript[payoff_idx].get("text", "")).strip()
                                    cid = c.get("id", c.get("cid", "?"))
                                    
                                    h_i = str(surgeon.get("hook_idea", "none"))
                                    d_s = str(surgeon.get("development_summary", "none"))
                                    try:
                                        d_score = float(surgeon.get("development_score", 0))
                                    except ValueError:
                                        d_score = 0.0
                                    p_i = str(surgeon.get("payoff_idea", "none"))
                                    s_i = surgeon.get("same_idea", False)
                                    i_k = surgeon.get("idea_keywords", [])
                                    c_source = str(surgeon.get("core_idea_source", "UNKNOWN"))
                                    
                                    
                                    try:
                                        c_score = float(surgeon.get("continuity_score", 0))
                                    except ValueError:
                                        c_score = 0.0
                                        
                                    c_reason = str(surgeon.get("continuity_reason", "none"))
                                    
                                    try:
                                        r_s = float(surgeon.get("resolution_strength", 0))
                                    except ValueError:
                                        r_s = 0.0
                                        
                                    proposed_quote = str(surgeon.get("proposed_payoff_quote", "none"))
                                    
                                    log.info(f"[SURGEON_EXTEND_RIGHT_EVAL] cid={cid} r_s={r_s} required=8 payoff_idx={payoff_idx} valid_bounds={0 <= payoff_idx < len(full_transcript)}")
                                    
                                    if r_s >= 8 and 0 <= payoff_idx < len(full_transcript):
                                        log.info("\n[EXTEND_RIGHT_PREVIEW]")
                                        log.info(f"candidate_id={cid}")
                                        log.info(f"HOOK_TEXT={hook_text}")
                                        log.info(f"CURRENT_END_TEXT={old_end_text}")
                                        log.info(f"PROPOSED_PAYOFF_TEXT={new_end_text}")
                                        log.info(f"PROPOSED_PAYOFF_QUOTE={proposed_quote}")
                                        log.info(f"hook_idea={h_i}")
                                        log.info(f"core_idea_source={c_source}")
                                        log.info(f"development_summary={d_s}")
                                        log.info(f"development_score={d_score}")
                                        log.info(f"payoff_idea={p_i}")
                                        log.info(f"same_idea={s_i}")
                                        log.info(f"idea_keywords={i_k}")
                                        log.info(f"continuity_score={c_score}")
                                        log.info(f"continuity_reason={c_reason}")
                                        log.info(f"resolution_strength={r_s}\n")
                                        
                                        # 🚨 INJECTING MISSING STATE UPDATE 🚨
                                        old_end = float(c.get("end", 0.0))
                                        new_end = float(full_transcript[payoff_idx].get("end", 0.0))
                                        
                                        # Never shrink the boundary if it was already extended (e.g. by 90s experiment)
                                        c["end"] = max(old_end, new_end)
                                        
                                        tid = c.get("trace_id", c.get("id"))
                                        if tid and hasattr(ctx, "candidate_threads") and tid in ctx.candidate_threads:
                                            st = ctx.candidate_threads[tid]
                                            st.propose_boundary(
                                                stage="GROQ_SURGEON",
                                                before_start=float(c.get("start", 0.0)),
                                                before_end=round(old_end, 2),
                                                after_start=float(c.get("start", 0.0)),
                                                after_end=round(float(max(old_end, new_end)), 2),
                                                reason="extend_right",
                                                confidence=0.9
                                            )
                                        
                                        for fc in final_candidates:
                                            if fc.get("cid") == cid and cid != "?":
                                                fc["end"] = max(old_end, new_end)
                                                if os.environ.get("HS_TRACE_MODE", "false").strip().lower() == "true":
                                                    tid = fc.get("trace_id")
                                                    if tid:
                                                        ctx.trace_state(tid, "SURGEON_VALIDATED")
                                                        ctx.trace_event(
                                                            trace_id=tid,
                                                            stage="GROQ_SURGEON",
                                                            event="EXTEND_RIGHT",
                                                            changed=(round(max(old_end, new_end), 2) != round(old_end, 2)),
                                                            impact="CRITICAL" if (round(max(old_end, new_end), 2) != round(old_end, 2)) else "LOW",
                                                            before={"end": round(old_end, 2)},
                                                            after={"end": round(max(old_end, new_end), 2)}
                                                        )
                                                from viral_finder.system_observer import get_observer
                                                try:
                                                    get_observer().modify_candidate(cid, "surgeon_cortex", {"end": max(old_end, new_end)})
                                                except Exception:
                                                    pass
                                                break
                                                
                                        log.info(
                                            f"[EXTEND_RIGHT_APPLIED] "
                                            f"cid={cid} old_end={old_end:.2f} "
                                            f"new_end={new_end:.2f}\n"
                                        )
                            elif dec == "KEEP":
                                if os.environ.get("HS_TRACE_MODE", "false").strip().lower() == "true":
                                    tid = c.get("trace_id")
                                    if tid:
                                        ctx.trace_state(tid, "SURGEON_VALIDATED")
                                        ctx.trace_event(
                                            trace_id=tid,
                                            stage="GROQ_SURGEON",
                                            event="KEEP",
                                            changed=False,
                                            impact="LOW"
                                        )
    
                    log.info("[GROQ_SURGEON] Phase 4: SURGEON_REPAIR execution active.")
                    rejected_for_repair = []
                    for c in groq_result:
                        surgeon = c.get("groq_surgeon")
                        if surgeon:
                            dec = surgeon.get("decision", "")
                            rej_type = surgeon.get("rejection_type", "")
                            if dec == "REJECT" or rej_type == "INTERCEPTED_35S_REPAIR" or rej_type in ["TOO_SHORT", "NO_MEANINGFUL_PROGRESSION", "PAYOFF_DOES_NOT_RESOLVE_HOOK", "WEAK_HOOK"]:
                                rejected_for_repair.append(c)
                                log.info(f"[SURGEON_REPAIR] Attempting repair for rejection_type={rej_type} cid={c.get('id', '?')}")
                                
                    if rejected_for_repair:
                        from viral_finder.groq_cortex import repair_rejected_clips_with_groq
                        repaired_clips = repair_rejected_clips_with_groq(rejected_for_repair, full_transcript)
                        
                        repaired_count = 0
                        for rep_c in repaired_clips:
                            cid = rep_c.get("id")
                            surgeon = rep_c.get("groq_surgeon", {})
                            if surgeon.get("decision") == "EXTEND_RIGHT":
                                payoff_idx = int(surgeon.get("payoff_segment_index", -1))
                                if 0 <= payoff_idx < len(full_transcript):
                                    old_end = float(rep_c.get("end", 0.0))
                                    new_end = float(full_transcript[payoff_idx].get("end", 0.0))
                                    
                                    for fc in final_candidates:
                                        if fc.get("cid") == cid or fc.get("id") == cid:
                                            fc["end"] = max(old_end, new_end)
                                            fc["groq_surgeon"] = surgeon
                                            fc["groq_surgeon"]["repair_applied"] = True
                                            repaired_count += 1
                                            log.info(f"[SURGEON_REPAIR] SUCCESS: Replaced cid={cid} with repaired candidate.")
                                            break
    
        elif is_groq_enabled() and not _groq_api_key:
            log.warning("[GROQ_CORTEX] Enabled but GROQ_API_KEY missing — skipping.")
    except Exception as e:
        log.warning("[GROQ_CORTEX] Exception during review: %s", e)
    # ------------------------------------

def _run_staged_pipeline(path: str, top_k: int, prefer_gpu: bool, use_cache: bool, allow_fallback: bool):
    start = time.time()
    print("PIPELINE STAGE: start staged pipeline")
    has_tf_moments = False
    # OPT-1: reset memoization cache at pipeline start
    cqs_cache_reset()
    ctx = PipelineContext(
        path=path,
        top_k=max(1, int(top_k)),
        allow_fallback=bool(allow_fallback),
        prefer_gpu=bool(prefer_gpu),
        use_cache=bool(use_cache),
    )
    t0 = time.time()
    trace_enabled = _env_bool("HS_PIPELINE_TRACE", False)
    trace = PipelineTrace(enabled=trace_enabled, logger=log) if PipelineTrace else None
    if trace:
        trace.enter("L1_MEDIA_INPUT")
    _record_stage(ctx, "INPUT_MEDIA", path=os.path.basename(path))
    if trace:
        trace.exit("L1_MEDIA_INPUT", {"path": os.path.basename(path)})

    if trace:
        trace.enter("L2_TRANSCRIPTION")
    _run_transcription(ctx)
    print("STAGE OK: transcription")
    if trace:
        trace.exit("L2_TRANSCRIPTION", {"segments": len(ctx.transcript or []), "source": ctx.transcript_source})
    if not ctx.transcript:
        log.warning("[ORCH] staged pipeline produced empty transcript")
        if trace:
            trace.error("L2_TRANSCRIPTION", "empty_transcript")
            trace.render()
        return []
    total_dur = float(ctx.transcript[-1].get("end", ctx.transcript[-1].get("start", 0.0)) or 0.0)
    ctx.target_min = _resolve_min_target(total_dur, ctx.top_k)
    _record_stage(
        ctx,
        "TARGETS",
        duration_s=round(total_dur, 2),
        top_k=int(ctx.top_k),
        target_min=int(ctx.target_min),
    )

    if trace:
        trace.enter("L3_AUDIO_VISUAL")
    _run_av_features(ctx)
    print("STAGE OK: av_features")
    if trace:
        trace.exit(
            "L3_AUDIO_VISUAL",
            {
                "audio_frames": len(ctx.audio_features or []),
                "visual_frames": len(ctx.visual_features or []),
            },
        )

    if trace:
        trace.enter("L4_CURIOSITY_ENGINE")
    _run_curiosity(ctx)
    print("STAGE OK: curiosity")
    if trace:
        trace.exit(
            "L4_CURIOSITY_ENGINE",
            {"candidates": len(ctx.curiosity_candidates or []), "curve_points": len(ctx.curiosity_curve or [])},
        )

    if trace:
        trace.enter("L5_NARRATIVE_TRIGGER_ENGINE")
    _run_narrative_trigger_stage(ctx)
    print("STAGE OK: narrative triggers")
    if trace:
        tdist: Dict[str, int] = {}
        for t in (ctx.narrative_triggers or []):
            k = str(t.get("type", "unknown"))
            tdist[k] = int(tdist.get(k, 0)) + 1
        trace.exit(
            "L5_NARRATIVE_TRIGGER_ENGINE",
            {
                "triggers": len(ctx.narrative_triggers or []),
                "belief_reversal": tdist.get("belief_reversal", 0),
                "secret_revelation": tdist.get("secret_revelation", 0),
                "mistake_explanation": tdist.get("mistake_explanation", 0),
                "payoff": tdist.get("payoff", 0),
                "complete_thought": tdist.get("complete_thought", 0),
                "strong_claim": tdist.get("strong_claim", 0),
            },
        )

    _run_narrative_intelligence(ctx)
    print("STAGE OK: narrative intelligence")

    if trace:
        trace.enter("L6_IDEA_GRAPH")
    _run_idea_graph(ctx)
    print("STAGE OK: idea graph")
    if trace:
        trace.exit("L6_IDEA_GRAPH", {"nodes": len(ctx.idea_nodes or [])})

    if trace:
        trace.enter("L7_CANDIDATE_GENERATION")
    print("STAGE ENTER: candidate generation")
    _run_candidate_generation(ctx)
    print("STAGE OK: candidate generation")
    if trace:
        trace.exit("L7_CANDIDATE_GENERATION", {"candidates": len(ctx.raw_candidates or [])})

    if trace:
        trace.enter("L6B_GLOBAL_HOOK_HUNTER")
    _run_global_hook_hunter(ctx)
    print("STAGE OK: global hook hunter")
    
    # ── Guarantee every LLM trigger becomes a candidate ───────────────────────
    # Triggers that don't overlap ANY existing candidate are silently dropped.
    # This function prevents that: unmatched triggers become their own clips.
    _inject_unmatched_trigger_candidates(ctx)
    # ──────────────────────────────────────────────────────────────────────────
    
    _maybe_backfill_raw_candidates(ctx)
    if trace:
        trace.exit("L6B_GLOBAL_HOOK_HUNTER", {"candidates": len(ctx.raw_candidates or []), "injected": int((ctx.stage_stats.get("L6B_GLOBAL_HOOK_HUNTER", {}) or {}).get("injected", 0) or 0)})

    # Transcript-First Groq Cortex
    tf_env = os.environ.get("HS_GROQ_TRANSCRIPT_FIRST", "0").strip() == "1"
    tf_force = os.environ.get("HS_GROQ_TRANSCRIPT_FIRST_FORCE", "0").strip() == "1"
    log.info(f"[GROQ_TRANSCRIPT_FIRST] enabled={tf_env} force={tf_force}")
    log.info("[GROQ_TRANSCRIPT_FIRST] checkpoint reached before validation")

    if tf_env or tf_force:
        transcript_source = None
        for attr in ["transcript_segments", "segments", "transcript"]:
            val = getattr(ctx, attr, None)
            if val and isinstance(val, list) and len(val) > 0:
                transcript_source = val
                log.info(f"[GROQ_TRANSCRIPT_FIRST] found transcript in ctx.{attr} (length={len(val)})")
                break
        
        if not transcript_source:
            for attr in ["transcript_words", "words"]:
                words = getattr(ctx, attr, None)
                if words and isinstance(words, list) and len(words) > 0:
                    log.info(f"[GROQ_TRANSCRIPT_FIRST] grouping words from ctx.{attr} into segments (length={len(words)})")
                    grouped = []
                    chunk_size = 20
                    for idx, i in enumerate(range(0, len(words), chunk_size)):
                        chunk = words[i:i+chunk_size]
                        if not chunk:
                            continue
                        text = " ".join(w.get("text", w.get("word", "")) for w in chunk).strip()
                        start = float(chunk[0].get("start", 0))
                        end = float(chunk[-1].get("end", start))
                        grouped.append({
                            "start": start,
                            "end": end,
                            "text": text,
                            "words": chunk
                        })
                    transcript_source = grouped
                    break

        if not transcript_source:
            log.info("[GROQ_TRANSCRIPT_FIRST] skipped: transcript_segments empty")
        else:
            log.info(f"[GROQ_TRANSCRIPT_FIRST] transcript_segments={len(transcript_source)}")
            try:
                from viral_finder.groq_cortex import find_moments_from_transcript
                # Calculate chunks count
                chunk_len = 240
                overlap = 30
                if total_dur <= chunk_len:
                    chunks_count = 1
                else:
                    chunks_count = int((total_dur - overlap) // (chunk_len - overlap)) + 1
                log.info(f"[GROQ_TRANSCRIPT_FIRST] chunks={chunks_count}")

                moments = find_moments_from_transcript(transcript_source, total_dur)
                log.info(f"[GROQ_TRANSCRIPT_FIRST] moments_found={len(moments)}")

                injected_count = 0
                for i, m in enumerate(moments):
                    start = float(m.get("start", 0))
                    end = float(m.get("end", start))
                    duration = round(end - start, 2)
                    
                    # Extract text for the moment from transcript segments
                    seg_texts = []
                    for seg in transcript_source:
                        s_t = float(seg.get("start", 0))
                        e_t = float(seg.get("end", 0))
                        if s_t >= start - 1.0 and e_t <= end + 1.0:
                            seg_texts.append(seg.get("text", ""))
                    text = " ".join(seg_texts).strip() or m.get("text", "")
                    
                    # Construct candidate dict
                    cand = {
                        "start": start,
                        "end": end,
                        "duration": duration,
                        "text": text,
                        "viral_score": float(m.get("viral_score", 80)) / 100.0 if float(m.get("viral_score", 80)) > 1.0 else float(m.get("viral_score", 0.80)),
                        "reason": "groq_transcript_first",
                        "origin": "groq_transcript_first",
                        "cortex_enabled": True,
                        "title": m.get("title", ""),
                        "opening_caption": m.get("opening_caption", ""),
                        "clip_archetype": m.get("clip_archetype", ""),
                        "editing_notes": m.get("editing_notes", {}),
                        "groq_moment": True,
                        "completeness_signal": m.get("completeness_signal", ""),
                        "psychology_scores": m.get("psychology_scores", {})
                    }
                    # Emit intelligence so the transport verifier sees evidence
                    # (surgeon is skipped when has_tf_moments, so this is the only
                    # evidence producer on the transcript-first path).
                    _art = IntelligenceArtifact()
                    _psy = m.get("psychology_scores", {}) or {}
                    _art.evidence_stream.extend([
                        Evidence(type="stop_scroll", value=float(cand["viral_score"]), producer="groq_moment_director", confidence=0.9),
                        Evidence(type="memorability", value=float(_psy.get("memorability", 0) or 0) / 100.0, producer="groq_moment_director"),
                        Evidence(type="usefulness", value=float(_psy.get("usefulness", 0) or 0) / 100.0, producer="groq_moment_director"),
                        Evidence(type="completeness", value=1.0 if m.get("completeness_signal") else 0.0, producer="groq_moment_director"),
                    ])
                    cand["intelligence"] = _art
                    if not ctx.raw_candidates:
                        ctx.raw_candidates = []
                    ctx.raw_candidates.append(cand)
                    injected_count += 1
                log.info(f"[GROQ_TRANSCRIPT_FIRST] injected_candidates={injected_count}")
                if injected_count > 0:
                    has_tf_moments = True
            except Exception as e:
                log.warning("[GROQ_TRANSCRIPT_FIRST] Failed: %s", e)

    # 1. Log GROQ_TRANSCRIPT_FIRST stage to SystemObserver
    from viral_finder.system_observer import get_observer
    obs = get_observer()
    if tf_env or tf_force:
        obs.log_stage(
            "GROQ_TRANSCRIPT_FIRST",
            input_count=len(transcript_source) if 'transcript_source' in locals() and transcript_source else 0,
            output_count=injected_count if 'injected_count' in locals() else 0,
            wall_time=0.0
        )
    else:
        obs.log_stage("GROQ_TRANSCRIPT_FIRST", 0, 0, 0.0)

    # 2. Assign stable IDs & initialize in SystemObserver
    for idx, cand in enumerate(ctx.raw_candidates or []):
        if not cand.get("cid"):
            cand["cid"] = f"c_{idx+1:04d}"
        
        cid = cand["cid"]
        origin = cand.get("origin") or cand.get("reason") or "candidate_generation"
        if cand.get("hook_seed"):
            origin = "hook_hunter"
        elif cand.get("backfill"):
            origin = "backfill"
        elif cand.get("groq_moment"):
            origin = "groq_transcript_first"
            
        obs.init_candidate(
            cid=cid,
            created_by=origin,
            text=cand.get("text", ""),
            start=float(cand.get("start", 0.0)),
            end=float(cand.get("end", 0.0)),
            scores={
                "score": float(cand.get("score", 0.0)),
                "curiosity": float(cand.get("curiosity", 0.0)),
                "punch": float(cand.get("punch_confidence", 0.0)),
                "semantic": float(cand.get("semantic_quality", 0.0)),
            }
        )

    if trace:
        trace.enter("L8_SEMANTIC_SCORING")
    print("STAGE ENTER: semantic scoring")
    _run_semantic_scoring(ctx)
    print("STAGE OK: semantic scoring")
    if trace:
        trace.exit("L8_SEMANTIC_SCORING", {"brain_loaded": 1 if ctx.brain is not None else 0})

    if trace:
        trace.enter("L9_SIGNAL_ENRICHMENT")
    print("STAGE ENTER: enrichment")
    _run_enrichment(ctx)
    print("STAGE OK: enrichment")
    if trace:
        missing = 0
        for c in (ctx.enriched_candidates or []):
            sig = c.get("signals", {}) or {}
            families = ("psychology", "semantic", "narrative", "engagement")
            if not all(k in sig for k in families):
                missing += 1
        if missing > 0:
            trace.error("L9_SIGNAL_ENRICHMENT", "missing_signal_family", {"missing_candidates": missing})
        trace.exit("L9_SIGNAL_ENRICHMENT", {"enriched": len(ctx.enriched_candidates or [])})

    if trace:
        trace.enter("L8B_INSIGHT_DETECTOR")
    _run_insight_detector(ctx)
    print("STAGE OK: insight detector")
    if trace:
        trace.exit("L8B_INSIGHT_DETECTOR", {"found": int((ctx.stage_stats.get("L8B_INSIGHT_DETECTOR", {}) or {}).get("found", 0) or 0)})

    if trace:
        trace.enter("L10_VALIDATION")
    print("STAGE ENTER: validation")
    _run_validation(ctx)
    print("STAGE OK: validation")
    if trace:
        trace.exit(
            "L10_VALIDATION",
            {
                "accepted": len(ctx.validated_candidates or []),
                "rejected": len(ctx.rejected_candidates or []),
            },
        )

    # ── FIX: RECONNECT STORY COMPLETION ENGINE ─────────────────────────────────
    if trace:
        trace.enter("L10A_STORY_COMPLETION")
    print("STAGE ENTER: story completion")
    _run_story_completion(ctx)
    print("STAGE OK: story completion")
    if trace:
        trace.exit("L10A_STORY_COMPLETION", {})

    # ── FIX1: ARC ASSEMBLER before RANKING ─────────────────────────────────────
    # Previously: Ranking (L4528) → Arc Assembler (L4575)
    # Bug: ranking judged pre-assembly clips that don't exist in final output.
    # Fix: Assembler runs first (Transform), then Ranking judges the real clips (Judge).
    if trace:
        trace.enter("L11_ARC_ASSEMBLER")
    if os.environ.get("HS_EXPERIMENT_MODE") == "1" and os.environ.get("HS_EXPERIMENT_COMPARE_LEGACY") == "1":
        import copy
        ctx_legacy = copy.deepcopy(ctx)
        ctx_v2 = copy.deepcopy(ctx)

        _run_arc_assembler(ctx_legacy)
        _run_arc_assembler_v2(ctx_v2)

        # EXPERIMENT_COMPARE Telemetry
        legacy_arcs = {c.get("cid", c.get("id", "")): c for c in ctx_legacy.final_candidates or []}
        v2_arcs = {c.get("cid", c.get("id", "")): c for c in ctx_v2.final_candidates or []}

        all_cids = set(list(legacy_arcs.keys()) + list(v2_arcs.keys()))
        log.info(f"\\n{'='*50}\\n[EXPERIMENT_MODE_RESULTS]\\n{'='*50}")
        for cid in all_cids:
            old_c = legacy_arcs.get(cid)
            new_c = v2_arcs.get(cid)
            if old_c and new_c:
                old_text = str(old_c.get("text", "")).replace("\\n", " ")
                new_text = str(new_c.get("text", "")).replace("\\n", " ")

                old_dur = float(old_c.get("end", 0.0)) - float(old_c.get("start", 0.0))
                new_dur = float(new_c.get("end", 0.0)) - float(new_c.get("start", 0.0))

                old_score = float(old_c.get("arc_score", 0.0))
                new_score = float(new_c.get("arc_score", 0.0))

                log.info(f"\\n[EXPERIMENT_COMPARE] candidate_id={cid}")
                log.info(f'OLD_PAYOFF: "{old_text[:80]}..."')
                log.info(f'NEW_PAYOFF: "{new_text[:80]}..."')
                log.info(f"OLD_DURATION: {old_dur:.1f}s")
                log.info(f"NEW_DURATION: {new_dur:.1f}s")
                log.info(f"OLD_SCORE: {old_score:.3f}")
                log.info(f"NEW_SCORE: {new_score:.3f}\\n")

        ctx.final_candidates = ctx_v2.final_candidates
        ctx.ranked_output = ctx_v2.ranked_output
        if hasattr(ctx_v2, "candidate_threads"):
            ctx.candidate_threads = ctx_v2.candidate_threads
    else:
        if os.environ.get("HS_ARC_ASSEMBLER_LEGACY", "0") == "1":
            log.error("[ORCH-ARC] HS_ARC_ASSEMBLER_LEGACY=1 ignored; legacy assembler violates single payoff truth.")
            _run_arc_assembler_v2(ctx)
        else:
            log.info("[ORCH-ARC] using resolver-aware assembler v2")
            _run_arc_assembler_v2(ctx)
    print("STAGE OK: arc assembler")
    if trace:
        trace.exit("L11_ARC_ASSEMBLER", {"assembled": len(ctx.ranked_output or [])})

    if trace:
        trace.enter("L11B_GROQ_SURGEON")
    _run_groq_surgeon(ctx)
    bridged_after_surgeon = _bridge_intelligence_to_signals(ctx.ranked_output or [], "pre_ranking_intelligence_bridge")
    if bridged_after_surgeon:
        log.info("[INTEL_BRIDGE] pre_ranking bridged=%d evidence signal(s) after Groq Surgeon", bridged_after_surgeon)
    if trace:
        trace.exit("L11B_GROQ_SURGEON")

    # ── RANKING after ARC ASSEMBLY (FIX1) ──────────────────────────────────────
    # Ranking now reads ctx.ranked_output (assembled clips) and writes
    # ctx.final_candidates (top-k winners judged on the real assembled clip).
    if trace:
        trace.enter("L10_RANKING")
    print("STAGE ENTER: ranking")
    _run_ranking(ctx)
    print("STAGE OK: ranking")
    if trace:
        trace.exit("L10_RANKING", {"final": len(ctx.ranked_output or [])})

    if trace:
        trace.enter("L12_EDITOR_REFINER")
    _run_editor_refiner(ctx)
    print("STAGE OK: editor refiner")
    if trace:
        trace.exit("L12_EDITOR_REFINER", {"final": len(ctx.ranked_output or [])})

    out = ctx.ranked_output or ctx.final_candidates or []
    if not out and ctx.allow_fallback and ultron_engine:
        log.info("[ORCH] staged output empty, fallback -> legacy ultron")
        if trace:
            trace.error("STAGED_PIPELINE", "fallback_to_legacy_ultron")
        try:
            env = ultron_engine(path, top_k=top_k, allow_fallback=True)
            out = env.get("candidates", [])
        except Exception:
            out = []

    # FIX3: DECISION TIMELINE — Print full timeline for winners
    for c in out:
        if isinstance(c, dict) and "decision_timeline" in c:
            log.info(f"\n[DECISION_TIMELINE] cid={c.get('cid','?')}")
            for entry in c["decision_timeline"]:
                _stage = entry.get("stage", "UNKNOWN").ljust(12)
                _event = entry.get("event", "Changed")
                log.info(f"  {_stage} | Event: {_event}")
                if "old_bounds" in entry:
                    log.info(f"               Old: {entry['old_bounds']}")
                    log.info(f"               New: {entry['new_bounds']}")
                log.info(f"               Reason: {entry.get('reason', '')}")
                log.info(f"               Score: {entry.get('score', 0.0)}")
            log.info("-" * 40)
            log.info("")

    # Attach transcript to every candidate so downstream consumer (WCE/worker) has access to it
    for c in out:
        if isinstance(c, dict):
            c["transcript"] = ctx.transcript
            c["transcript_segments"] = ctx.transcript

    # --- BUILD GROQ PRE-FILTER POOL ---
    # Give Groq a richer candidate pool than the aggressively-filtered ranked_output.
    # Pool = enriched (post-signal-enrichment, pre-validation-rejection) +
    #        validated (post-validation, pre-arc) + ranked_output.
    # Deduplicate by (round(start,1), round(end,1)) key; sort by viral_score desc.
    _pool_seen: set = set()
    _groq_pool: list = []
    _transcript_ref = ctx.transcript  # reference for downstream
    for _c in list(ctx.enriched_candidates or []) + list(ctx.validated_candidates or []) + list(out):
        if not isinstance(_c, dict):
            continue
        _key = (round(float(_c.get("start", 0) or 0), 1), round(float(_c.get("end", 0) or 0), 1))
        if _key in _pool_seen:
            continue
        _pool_seen.add(_key)
        _cp = dict(_c)
        _cp.setdefault("transcript", _transcript_ref)
        _cp.setdefault("text", " ".join(
            seg.get("text", "") for seg in (_transcript_ref or [])
            if float(seg.get("start", 0) or 0) >= float(_cp.get("start", 0) or 0)
            and float(seg.get("end", 0) or 0) <= float(_cp.get("end", 0) or 0)
        ).strip() or _cp.get("text", ""))
        _groq_pool.append(_cp)
    _groq_pool.sort(key=lambda x: float(x.get("viral_score", x.get("score", 0)) or 0), reverse=True)
    log.info(
        "[ORCH] groq_pool built: pool=%d enriched=%d validated=%d ranked=%d",
        len(_groq_pool), len(ctx.enriched_candidates or []),
        len(ctx.validated_candidates or []), len(out),
    )
    # ----------------------------------

    # OPT-1: log cache stats before reset
    _cqs_stats = cqs_cache_stats()
    log.info("[CQS-CACHE] pipeline_end %s", _cqs_stats)
    cqs_cache_reset()
    _record_stage(ctx, "SUMMARY", wall_s=round(time.time() - t0, 3), final=len(out), rejected=len(ctx.rejected_candidates), cqs_cache=_cqs_stats)
    if trace:
        pass
    
    from viral_finder.system_observer import get_observer
    try:
        xray_report = get_observer().render_report()
        log.info(xray_report)
        try:
            print(xray_report)
        except Exception:
            # Fallback for Windows consoles that don't support UTF-8 emojis
            print(xray_report.encode("ascii", "replace").decode("ascii"))
    except Exception:
        log.exception("[XRAY] report failed but pipeline output preserved")
        xray_report = "[XRAY FAILED]"

    print("TOTAL PROCESS TIME:", time.time() - start)
    return out, _groq_pool, has_tf_moments, getattr(ctx, "transcript", []), ctx


def orchestrate(path: str,
                 top_k: int = DEFAULT_TOP_K,
                 prefer_gpu: bool = True,
                 use_cache: bool = True,
                 allow_fallback: bool = False,
                 pipeline_mode: Optional[str] = None) -> List[Dict]:
    """
    High-level orchestration entrypoint.
    Modes:
      - staged (default): explicit cognitive pipeline stages
      - legacy: direct ultron engine passthrough
    """
    from viral_finder.system_observer import reset_observer
    reset_observer()
    print("[ORCH] ORCHESTRATOR STARTED")
    start_time = time.time()
    mode = _pipeline_mode(pipeline_mode)
    log.info("[ORCH] pipeline_mode=%s", mode)
    log.info("[ORCH] Startup Env: HS_GROQ_TRANSCRIPT_FIRST=%s", os.environ.get("HS_GROQ_TRANSCRIPT_FIRST"))
    log.info("[ORCH] Startup Env: HS_GROQ_CORTEX_ENABLED=%s", os.environ.get("HS_GROQ_CORTEX_ENABLED"))
    log.info("[ORCH] Startup Env: HS_FORCE_30S_PADDING=%s", os.environ.get("HS_FORCE_30S_PADDING"))
    log.info("[ORCH] Startup Env: HS_GROQ_TRANSCRIPT_FIRST_FORCE=%s", os.environ.get("HS_GROQ_TRANSCRIPT_FIRST_FORCE"))

    final_candidates = []
    _groq_pool: list = []  # richer pre-filter pool for Groq

    has_tf_moments = False
    full_transcript = []
    ctx = None
    if mode == "staged":
        try:
            _staged_result = _run_staged_pipeline(
                path=path,
                top_k=top_k,
                prefer_gpu=prefer_gpu,
                use_cache=use_cache,
                allow_fallback=allow_fallback,
            )
            if isinstance(_staged_result, tuple):
                if len(_staged_result) == 5:
                    final_candidates, _groq_pool, has_tf_moments, full_transcript, ctx = _staged_result
                elif len(_staged_result) == 4:
                    final_candidates, _groq_pool, has_tf_moments, full_transcript = _staged_result
                elif len(_staged_result) == 3:
                    final_candidates, _groq_pool, has_tf_moments = _staged_result
                else:
                    final_candidates, _groq_pool = _staged_result
                    has_tf_moments = any(c.get("groq_moment") for c in final_candidates)
            else:
                final_candidates = _staged_result  # safety fallback
            log.info("[ORCH] staged returned %d candidates (groq_pool=%d, has_tf_moments=%s).", len(final_candidates), len(_groq_pool), has_tf_moments)
            
            # --- FRACTAL COGNITION ENGINE ---
            if os.environ.get("HS_FRACTAL_ENGINE") == "1":
                try:
                    from viral_finder.fractal_cognition import optimize_boundaries
                    log.info("[FRACTAL] Activating Geometric Cognition Engine...")
                    _fractal_candidates = optimize_boundaries(final_candidates, full_transcript)
                    if _fractal_candidates:
                        final_candidates = _fractal_candidates
                        log.info("[FRACTAL] Successfully optimized candidate boundaries.")
                except Exception as e:
                    import traceback
                    log.error(f"[FRACTAL] Geometric Cognition Engine failed: {e}. Falling back to standard pipeline.\n{traceback.format_exc()}")
            # --------------------------------
        except Exception as exc:
            log.exception("[ORCH] staged pipeline failed: %s", exc)
            if not _env_bool("HS_ORCH_STAGED_FAILOVER_TO_LEGACY", False):
                return []
            log.error("STAGED PIPELINE CRASHED — FALLING BACK TO ULTRON")
            log.info("[ORCH] staged failover -> legacy")

    if not final_candidates:
        if not ultron_engine:
            log.error("[ORCH] FATAL: Ultron V33 engine (ultron_finder_v33.py) is not available.")
            return []

        try:
            result_envelope = ultron_engine(path, top_k=top_k, allow_fallback=allow_fallback)
            final_candidates = result_envelope.get("candidates", [])
            log.info("[ORCH] Ultron V33 Engine returned %d candidates.", len(final_candidates))
        except Exception as exc:
            log.exception("[ORCH] Ultron V33 engine failed: %s", exc)
            return []

    log.info('[ORCH] Orchestration complete (t=%.2fs)', (time.time() - start_time))


    
    # Generate Final Clip Source Report
    cg_count = 0
    gtf_count = 0
    for c in final_candidates:
        if c.get("groq_moment"):
            gtf_count += 1
        else:
            cg_count += 1
            
    log.info("\n[FINAL_CLIP_SOURCE_REPORT]")
    log.info(f"candidate_generation={cg_count}")
    log.info(f"groq_transcript_first={gtf_count}")

    log.info("\n[GROQ_USAGE_REPORT]")
    log.info(f"narrative_enabled={os.environ.get('HS_GROQ_NARRATIVE_ROLES', '0')}")
    log.info(f"transcript_first_enabled={os.environ.get('HS_GROQ_TRANSCRIPT_FIRST', '0')}")
    log.info(f"cortex_enabled={os.environ.get('HS_GROQ_CORTEX', '0')}")

    log.info("\n[PIPELINE_REPORT]")
    raw_cand_count = len(_groq_pool) if _groq_pool else "N/A"
    log.info(f"raw_candidates={raw_cand_count}")
    log.info(f"final_candidates={len(final_candidates)}")
    log.info(f"runtime_seconds={round(time.time() - start_time, 2)}\n")

    if ctx:
        log.info("\n[PIPELINE_ACCOUNTING]")
        log.info(f"Hooks Created = {len(ctx.raw_candidates) + ctx.hooks_suppressed}")
        log.info(f"Hooks Suppressed = {ctx.hooks_suppressed}")
        log.info(f"Candidates Created = {len(ctx.raw_candidates)}")
        log.info(f"Arc Assembler Inputs = {len(ctx.enriched_candidates) if ctx.enriched_candidates else len(ctx.raw_candidates)}")
        log.info(f"Surgeon Inputs = {len(ctx.validated_candidates) if ctx.validated_candidates else len(ctx.raw_candidates)}")
        log.info(f"Final Clips = {len(final_candidates)}\n")

        # --- CANDIDATE LINEAGE AUDIT (PRODUCTION EVIDENCE) ---
        log.info("============================================================")
        log.info("    CANDIDATE LINEAGE AUDIT (PRODUCTION EVIDENCE)")
        log.info("============================================================")
        log.info(f"{'Candidate ID':<15} | {'Timestamp':<12} | {'Hook Strength':<14} | {'StoryThread ID':<30} | {'Suppressed?':<12} | {'Reason':<50} | {'Final injected?'}")
        log.info("-" * 160)
        
        try:
            from viral_finder.system_observer import get_observer
            obs = get_observer()
            
            # Helper to find a candidate in all ctx lists
            def _find_cand(cid):
                for pool in [ctx.raw_candidates, ctx.enriched_candidates, ctx.validated_candidates, final_candidates]:
                    if not pool: continue
                    for p in pool:
                        if isinstance(p, dict) and p.get("cid") == cid:
                            return p
                return {}

            for cid, cand_data in obs.candidates.items():
                start = round(cand_data.get("start") or 0.0, 1)
                end = round(cand_data.get("end") or 0.0, 1)
                ts = f"{start}s-{end}s"
                
                c_full = _find_cand(cid)
                
                hook_strength = float(c_full.get("hook_strength", c_full.get("score", c_full.get("viral_score", cand_data.get("scores", {}).get("hook_strength", 0.0)))))
                
                story_thread_id = str(c_full.get("trace_id", c_full.get("story_thread_id", "N/A")))
                
                final_reason = cand_data.get("final_reason", "")
                suppressed = "Yes" if "rejected" in final_reason or "dropped" in final_reason else "No"
                
                injected = "Yes" if cid in [fc.get("cid") for fc in final_candidates if isinstance(fc, dict)] else "No"
                
                log.info(f"{cid:<15} | {ts:<12} | {hook_strength:<14.3f} | {story_thread_id:<30} | {suppressed:<12} | {final_reason:<50} | {injected}")
                
        except Exception as e:
            log.error(f"Error generating lineage audit: {e}")
            
        log.info("============================================================\n")

    for i, c in enumerate(final_candidates):
        source = "groq_transcript_first" if c.get("groq_moment") else "candidate_generation"
        log.info(f"CLIP {i+1}: source={source} hook_score={c.get('hook_score', 0.0)} payoff_score={c.get('payoff_score', 0.0)} duration={c.get('duration', 0.0)} final_score={c.get('final_score', 0.0)}")
        
        # Print Hook Selection Trace
        trace = c.get("hook_selection_trace", {})
        if trace:
            log.info(f"  [HOOK_SELECTION_TRACE]")
            log.info(f"    selected_hook_score={trace.get('score', 0.0)}")
            if "hook_hunter_confidence" in trace:
                log.info(f"    hook_hunter_confidence={trace['hook_hunter_confidence']}")
            log.info(f"    why_selected={trace.get('reason', 'N/A')}")
            log.info(f"    selected_hook_text='{trace.get('text', '')}'\n")

    if ctx and os.environ.get("HS_TRACE_MODE", "false").strip().lower() == "true":
        log.info("\n" + "=" * 50)
        log.info("NARRATIVE OBSERVATORY: STORY TRACE REPORT")
        log.info("=" * 50)
        for i, c in enumerate(final_candidates):
            tid = c.get("trace_id")
            if not tid or tid not in ctx.trace_logs:
                continue
            ctx.trace_state(tid, "FINALIZED")
            t_obj = ctx.trace_logs[tid]
            ident = t_obj.get("identity", {})
            hist = t_obj.get("state_history", [])
            kids = t_obj.get("suppressed_children", [])
            evts = t_obj.get("events", [])

            log.info(f"\nSTORY #{i+1} [Trace ID: {tid}]")
            log.info("-" * 40)
            log.info("WHO AM I?")
            log.info(f"  Hook: '{ident.get('hook', 'N/A')}'")
            log.info(f"  Start: {ident.get('start', 'N/A')}s")
            log.info(f"  End: {c.get('end')}s")
            log.info(f"  State: {ident.get('state', 'N/A')}")
            br = ident.get("birth_reason", {})
            if br:
                log.info("  Birth Heuristics:")
                for k, v in br.items():
                    log.info(f"    {k}: {v}")
            log.info("-" * 40)
            log.info(f"STATE HISTORY: {' -> '.join(hist)}")
            log.info("-" * 40)
            if kids:
                log.info(f"SUPPRESSED CHILDREN ({len(kids)} absorbed):")
                for ki, kid in enumerate(kids):
                    log.info(f"  {ki+1}. Start: {kid.get('start')}s | Score: {kid.get('score')} | Reason: {kid.get('reason')}")
                    log.info(f"     Text: '{kid.get('text')}'")
            else:
                log.info("SUPPRESSED CHILDREN: None (0 absorbed)")
            log.info("-" * 40)
            log.info("PIPELINE EVENTS:")
            for ev in evts:
                changed_indicator = " [MUTATED]" if ev.get("changed") else ""
                log.info(f"  [{ev.get('stage')}] {ev.get('event')}{changed_indicator} (Impact: {ev.get('impact')})")
                if ev.get("before"):
                    log.info(f"     Before: {ev.get('before')}")
                if ev.get("after"):
                    log.info(f"     After:  {ev.get('after')}")
            log.info("-" * 40)
            
            # Dynamic natural language explanation based on events
            explanations = []
            has_hh = any(e.get("stage") == "HOOK_HUNTER" for e in evts)
            has_sm = any(e.get("stage") == "STORY_MEMORY" for e in evts)
            has_aa = any(e.get("stage") == "ARC_ASSEMBLER" for e in evts)
            has_po = any(e.get("stage") == "PAYOFF_SELECTION" for e in evts)
            has_gs = any(e.get("stage") == "GROQ_SURGEON" for e in evts)
            has_er = any(e.get("stage") == "EDITOR_REFINER" for e in evts)

            if has_hh:
                explanations.append("Hook Hunter created it")
            if has_sm and kids:
                explanations.append(f"Story memory absorbed {len(kids)} fragment{'s' if len(kids) > 1 else ''}")
            if has_aa:
                # Find assembler delta
                aa_ev = next((e for e in evts if e.get("stage") == "ARC_ASSEMBLER"), None)
                if aa_ev and aa_ev.get("changed"):
                    before_dur = aa_ev["before"].get("end", 0) - aa_ev["before"].get("start", 0)
                    after_dur = aa_ev["after"].get("end", 0) - aa_ev["after"].get("start", 0)
                    diff = round(after_dur - before_dur, 2)
                    if diff > 0:
                        explanations.append(f"Arc Assembler expanded it by {diff}s")
                    else:
                        explanations.append("Arc Assembler assembled the boundaries")
                else:
                    explanations.append("Arc Assembler locked the narrative setup")
            if has_po:
                po_ev = next((e for e in evts if e.get("stage") == "PAYOFF_SELECTION"), None)
                if po_ev:
                    explanations.append(f"Payoff selected segment {po_ev['after'].get('payoff_idx')}")
            if has_gs:
                gs_ev = next((e for e in evts if e.get("stage") == "GROQ_SURGEON" and e.get("event") in ("MOVE_HOOK", "EXTEND_RIGHT")), None)
                if gs_ev:
                    explanations.append(f"Groq Surgeon validated and modified the boundaries ({gs_ev.get('event')})")
                else:
                    explanations.append("Groq Surgeon validated it without edits")
            if has_er:
                er_ev = next((e for e in evts if e.get("stage") == "EDITOR_REFINER"), None)
                if er_ev and er_ev.get("changed"):
                    explanations.append("Editor Refiner padded and korrected sentence alignment")

            log.info("FINAL ANSWER")
            log.info(f"  This clip exists because " + ", ".join(explanations) + ".")
            log.info("=" * 50)

    from viral_finder.system_observer import get_observer
    try:
        xray_report = get_observer().render_report()
        log.info(xray_report)
    except Exception as exc:
        log.warning(f"[ORCH] Error rendering system observer: {exc}")

    # -------------------------------------------------------------------------
    # GOVERNOR TELEMETRY BLOCK (PHASE 1)
    # -------------------------------------------------------------------------
    log.info("\n" + "="*60)
    log.info("GOVERNOR TELEMETRY: PROPOSAL HISTORY (PHASE 1)")
    log.info("="*60)
    if ctx and hasattr(ctx, "candidate_threads"):
        for i, c in enumerate(final_candidates):
            tid = c.get("trace_id", c.get("id"))
            if not tid or tid not in ctx.candidate_threads:
                continue
            
            st = ctx.candidate_threads[tid]
            proposals = st.proposals
            
            log.info(f"\nCLIP {c.get('cid', tid)}")
            log.info("-" * 40)
            
            for stage in ["ARC_ASSEMBLER", "EDITOR_REFINER", "GROQ_SURGEON"]:
                stage_props = proposals.get(stage, [])
                for prop in stage_props:
                    if prop.get("type") == "boundary":
                        bs, be = prop["before"]["start"], prop["before"]["end"]
                        ast, ae = prop["after"]["start"], prop["after"]["end"]
                        log.info(f"{stage} PROPOSED")
                        log.info(f"  before: {bs} -> {be}")
                        log.info(f"  after:  {ast} -> {ae}")
                        log.info(f"  reason: {prop.get('reason')}")
                        log.info(f"  confidence: {prop.get('confidence')}\n")
                        
            log.info("FINAL OUTPUT")
            log.info(f"  start={c.get('start')}")
            log.info(f"  end={c.get('end')}")
            log.info("-" * 40)
    else:
        log.info("No StoryThread proposals found in this run.")
    log.info("="*60 + "\n")

    # --- INTELLIGENCE TRANSPORT VERIFIER ---
    # Every Evidence packet must end as CONSUMED, EXPLICITLY_REJECTED, or ORPHANED.
    # An orphaned packet is a pipeline bug — intelligence generated but never used.
    try:
        from viral_finder.intelligence_verifier import reset_verifier
        _verifier = reset_verifier()
        _all_pool = list(ctx.enriched_candidates or []) + list(ctx.raw_candidates or [])
        _rejected_pool = list(ctx.rejected_candidates or [])
        _final_keys = {str(c.get("cid", c.get("id", id(c)))) for c in (final_candidates or []) if isinstance(c, dict)}
        _intermediate_not_final = [
            c for c in _all_pool
            if not isinstance(c, dict) or str(c.get("cid", c.get("id", id(c)))) not in _final_keys
        ]
        _rejected_leftovers = _reject_unsettled_intelligence(
            _rejected_pool,
            "intelligence_transport_settlement",
            "candidate_rejected_before_final_decision",
        )
        _intermediate_leftovers = _reject_unsettled_intelligence(
            _intermediate_not_final,
            "intelligence_transport_settlement",
            "candidate_not_selected_for_final_decision",
        )
        _final_leftovers = _reject_unsettled_intelligence(
            final_candidates,
            "intelligence_transport_settlement",
            "unsupported_or_late_evidence_not_used_by_ranking",
        )
        if _rejected_leftovers or _intermediate_leftovers or _final_leftovers:
            log.info(
                "[INTEL_SETTLEMENT] rejected_unsettled final=%d intermediate=%d rejected=%d",
                _final_leftovers,
                _intermediate_leftovers,
                _rejected_leftovers,
            )
        _verifier.scan(
            final_candidates=final_candidates,
            all_candidates=_all_pool,
            rejected_candidates=_rejected_pool,
        )
        if _verifier.total == 0:
            log.info(
                "[INTEL_VERIFIER] skipped: no intelligence-producing stage emitted evidence packets"
            )
        else:
            _iv_report = _verifier.render_report()
            log.info(_iv_report)
        if _verifier.has_orphans:
            log.warning(
                "[INTEL_VERIFIER] %d orphaned intelligence packet(s) detected — "
                "pipeline is silently discarding intelligence. See report above.",
                _verifier.orphaned_count,
            )
    except Exception as _iv_exc:
        log.warning("[INTEL_VERIFIER] Audit failed (non-fatal): %s", _iv_exc)
    # -----------------------------------------

    return final_candidates
# -------------------------
# CLI helper
# -------------------------
if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(prog='orchestrator.py')
    p.add_argument('file', help='audio/video file path')
    p.add_argument('--top_k', type=int, default=DEFAULT_TOP_K)
    p.add_argument('--gpu', action='store_true')
    p.add_argument('--no-cache', action='store_true')
    p.add_argument('--allow-fallback', action='store_true')
    p.add_argument('--pipeline-mode', choices=['staged', 'legacy'], default=None)
    args = p.parse_args()

    res = orchestrate(
        args.file,
        top_k=args.top_k,
        prefer_gpu=args.gpu,
        use_cache=(not args.no_cache),
        allow_fallback=args.allow_fallback,
        pipeline_mode=args.pipeline_mode,
    )
    import json
    print(json.dumps(res, indent=2))
