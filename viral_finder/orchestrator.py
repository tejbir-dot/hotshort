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
import re
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed
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
except Exception:
    gemini_transcribe = None
    transcribe_and_analyze = None

try:
    from viral_finder.transcript_engine import transcribe_file as legacy_transcribe, extract_transcript
except Exception:
    legacy_transcribe = None
    extract_transcript = None

try:
    from viral_finder.visual_audio_engine import analyze_audio, analyze_visual
except Exception:
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
except Exception:
    analyze_curiosity_and_detect_punches = None
    build_idea_graph = None
    select_candidate_clips = None
    sentence_complete_extend = None
    detect_payoff_end = None

try:
    from viral_finder.curiosity_engine import run_curiosity as run_curiosity_stage
except Exception:
    run_curiosity_stage = None

try:
    from viral_finder.validation_gates import apply_post_enrichment_validation
except Exception:
    apply_post_enrichment_validation = None

try:
    from viral_finder.clip_selector import rank_and_diversify
except Exception:
    rank_and_diversify = None

try:
    from viral_finder.narrative_trigger_engine import detect_narrative_triggers
except Exception:
    detect_narrative_triggers = None

try:
    from utils.narrative_intelligence import compute_quality_scores
except Exception:
    compute_quality_scores = None
try:
    from utils.narrative_intelligence import detect_message_punch as _detect_message_punch
except Exception:
    _detect_message_punch = None
try:
    from utils.story_patterns import detect_story_pattern
except Exception:
    detect_story_pattern = None

try:
    from viral_finder.pipeline_trace import PipelineTrace
except Exception:
    PipelineTrace = None

try:
    from .global_fields import build_cognition_cache
    from .dominance_selector import select_dominant_arcs, SelectorConfig
except ImportError:
    build_cognition_cache = None
    select_dominant_arcs = None
    SelectorConfig = None

try:
    from .ultron_finder_v33 import find_viral_moments as ultron_engine
except ImportError:
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
    novelty = 1.0
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


def dedupe_by_overlap(clips, overlap_threshold=0.75):
    """
    🚀 Smart deduplication based on clip overlap ratio (IoU).
    Removes clips that overlap > threshold with higher-scored clips.
    
    Example: If clips 15.8-40.5 and 16.2-40.2 overlap > 75%, keep only the best-scored one.
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

def enrich_candidate(candidate: Dict, aud: List[Dict], vis: List[Dict], brain) -> Dict:
    """Add audio/motion/brain/semantic fields to a candidate dict.
    Runs fast local fallbacks when heavy models are missing.
    """
    try:
        a_avg = _slice_mean(aud, 'energy', candidate['start'], candidate['end'])
        m_avg = _slice_mean(vis, 'motion', candidate['start'], candidate['end'])
    except Exception:
        a_avg = 0.0; m_avg = 0.0

    try:
        impact, meaning, novelty, emotion, clarity = _runtime_ultron_brain_score(candidate.get('text','') or '', brain)
    except Exception:
        impact = meaning = novelty = emotion = clarity = 0.0

    # fuse -> classic energy
    classic = fuse(0.05 + candidate.get('hook', 0.0), a_avg, m_avg)

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

    # recalc a simple semantic_quality if not present
    if 'semantic_quality' not in candidate or candidate.get('semantic_quality') is None:
        try:
            from utils.narrative_intelligence import estimate_semantic_quality
            candidate['semantic_quality'] = round(float(estimate_semantic_quality(candidate.get('text',''), candidate.get('score',0.0))), 3)
        except Exception:
            candidate['semantic_quality'] = round(candidate.get('score', 0.0), 3)

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

    semantic_strength = max(semantic_quality, (0.5 * impact) + (0.3 * meaning) + (0.2 * clarity))
    narrative_strength = max(completion, trigger_score, viral_density)

    if failure_reason == "no_curiosity_drop":
        return semantic_strength >= 0.56 and narrative_strength >= 0.40
    if failure_reason in {"payoff_low", "no_curve", "too_short_window", "no_curiosity_peak"}:
        return (
            semantic_strength >= 0.60
            and narrative_strength >= 0.42
            and (alignment >= 0.08 or payoff_conf >= 0.35 or impact >= 0.35)
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


@dataclass
class PipelineContext:
    path: str
    top_k: int
    allow_fallback: bool
    prefer_gpu: bool = True
    use_cache: bool = True
    transcript: List[Dict[str, Any]] = field(default_factory=list)
    audio_features: List[Dict[str, Any]] = field(default_factory=list)
    visual_features: List[Dict[str, Any]] = field(default_factory=list)
    av_features: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    curiosity_curve: List[Any] = field(default_factory=list)
    curiosity_candidates: List[Any] = field(default_factory=list)
    curiosity: Dict[str, Any] = field(default_factory=dict)
    narrative: Dict[str, Any] = field(default_factory=dict)
    narrative_triggers: List[Dict[str, Any]] = field(default_factory=list)
    idea_nodes: List[Any] = field(default_factory=list)
    raw_candidates: List[Dict[str, Any]] = field(default_factory=list)
    enriched_candidates: List[Dict[str, Any]] = field(default_factory=list)
    validated_candidates: List[Dict[str, Any]] = field(default_factory=list)
    rejected_candidates: List[Dict[str, Any]] = field(default_factory=list)
    final_candidates: List[Dict[str, Any]] = field(default_factory=list)
    ranked_output: List[Dict[str, Any]] = field(default_factory=list)
    narrative_score_cache: Dict[str, Dict[str, float]] = field(default_factory=dict)
    brain: Any = None
    stage_stats: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    transcript_source: str = "unknown"


def _record_stage(ctx: PipelineContext, stage: str, **stats: Any) -> None:
    ctx.stage_stats[stage] = stats
    compact = " ".join([f"{k}={v}" for k, v in stats.items()])
    log.info("[ORCH][%s] %s", stage, compact)


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
    if ctx.use_cache:
        transcript = _load_cached_transcript(ctx.path) or []
        if transcript:
            source = "cache"
    if not transcript:
        if gemini_transcribe:
            transcript = gemini_transcribe(ctx.path) or []
            source = "gemini"
        elif extract_transcript:
            transcript = extract_transcript(ctx.path, prefer_gpu=ctx.prefer_gpu) or []
            source = "legacy_extract"
        elif legacy_transcribe:
            transcript = legacy_transcribe(ctx.path) or []
            source = "legacy_transcribe"
    if transcript and ctx.use_cache:
        _save_cached_transcript(ctx.path, transcript)
    ctx.transcript = transcript or []
    ctx.transcript_source = source
    _record_stage(
        ctx,
        "L1_TRANSCRIPTION",
        transcript_segments=len(ctx.transcript),
        source=source,
        reuse_cache=1 if source == "cache" else 0,
        wall_s=round(time.time() - t0, 3),
    )


def _run_av_features(ctx: PipelineContext) -> None:
    t0 = time.time()
    try:
        ctx.audio_features = analyze_audio(ctx.path) or []
    except Exception:
        ctx.audio_features = []
    try:
        ctx.visual_features = analyze_visual(ctx.path) or []
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
        for seg in ctx.transcript:
            txt = str(seg.get("text", "") or "").lower()
            if "?" in txt or any(k in txt for k in ("did you know", "what if", "ever wondered")):
                role = "HOOK"
            elif any(k in txt for k in ("that's why", "the point is", "in conclusion", "bottom line", "therefore")):
                role = "PAYOFF"
            elif any(k in txt for k in ("because", "so", "for example", "then", "next")):
                role = "BUILD"
            else:
                role = "BUILD"
            role_tags.append(role)

        for r in role_tags:
            if not role_paths or role_paths[-1] != r:
                role_paths.append(r)

    # Performance-safe narrative summary: avoid expensive per-window quality scoring here.
    payoff_hints = []
    for cand in (ctx.curiosity_candidates or []):
        if isinstance(cand, dict):
            payoff_hints.append(float(cand.get("payoff_confidence", cand.get("payoff_conf", 0.0)) or 0.0))
    if payoff_hints:
        payoff_strength = sum(payoff_hints) / float(len(payoff_hints))
    elif role_tags:
        payoff_strength = float(sum(1 for r in role_tags if r == "PAYOFF")) / float(max(1, len(role_tags)))

    # Keep tiny sample for observability without heavy compute.
    narrative_samples = [
        {"role": role_tags[i], "idx": float(i)}
        for i in range(0, min(len(role_tags), 12), max(1, len(role_tags) // 6 if len(role_tags) > 6 else 1))
    ]

    ctx.narrative = {
        "role_tags": role_tags,
        "role_paths": role_paths,
        "payoff_strength": round(float(payoff_strength), 4),
        "samples": narrative_samples,
    }
    _record_stage(
        ctx,
        "L4_NARRATIVE_INTELLIGENCE",
        role_tags=len(role_tags),
        role_paths=len(role_paths),
        payoff_strength=round(float(payoff_strength), 4),
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
    _record_stage(
        ctx,
        "L4_NARRATIVE_TRIGGER_ENGINE",
        triggers=len(triggers),
        belief_reversal=dist.get("belief_reversal", 0),
        secret_revelation=dist.get("secret_revelation", 0),
        mistake_explanation=dist.get("mistake_explanation", 0),
        strong_claim=dist.get("strong_claim", 0),
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
                min_target=max(0, int(ctx.top_k)),
                diversity_mode="balanced",
            ) or []
        except Exception as exc:
            log.warning("[ORCH] candidate generation degraded: %s", exc)
            candidates = []
    ctx.raw_candidates = candidates
    _record_stage(ctx, "L5_CANDIDATE_GENERATION", produced=len(candidates), wall_s=round(time.time() - t0, 3))


def _run_global_hook_hunter(ctx: PipelineContext) -> None:
    t0 = time.time()
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
        seg_scores = compute_quality_scores(transcript, seg_start, seg_end) if compute_quality_scores else {}
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
        if hook_strength > hook_threshold or pattern_break_score > 0.40 or curiosity_peak > 0.45:
            payload = {
                "start": round(seg_start, 2),
                "end": round(seg_end, 2),
                "text": seg_text,
                "score": round(float(hook_strength), 4),
                "hook_seed": True,
                "hook_strength": round(float(hook_strength), 4),
                "semantic_quality": round(float(semantic_quality), 4),
                "provenance": "L6B_GLOBAL_HOOK_HUNTER",
            }
            hooks.append(payload)
            if debug_enabled and (len(hooks) <= 8 or hook_strength >= 0.65):
                log.info('[HOOK] idx=%d strength=%.2f text="%s"', idx, hook_strength, seg_text[:120])

    hooks = sorted(hooks, key=lambda x: float(x.get("hook_strength", x.get("score", 0.0)) or 0.0), reverse=True)[:max_global_hooks]
    injected: List[Dict[str, Any]] = []
    seen = list(existing)
    for hook in hooks:
        if _is_duplicate_seed(hook, seen):
            continue
        injected.append(hook)
        seen.append(hook)

    if injected:
        ctx.raw_candidates = list(existing) + injected
    log.info("[HOOK-HUNTER] scanned=%d strong_hooks=%d", len(transcript), len(hooks))
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
    cache_obj = cand.get("_narr_cache")
    cache = cache_obj if isinstance(cache_obj, dict) else None
    if not compute_quality_scores:
        return {}
    try:
        s = float(cand.get("start", 0.0) or 0.0)
        e = float(cand.get("end", s) or s)
        if not transcript or e <= s:
            return {}
        cache_key = f"{round(s, 2)}:{round(e, 2)}:{len(transcript)}"
        if cache is not None and cache_key in cache:
            return dict(cache[cache_key])
        payload = compute_quality_scores(transcript, s, e) or {}
        norm = {k: _clamp01(v) for k, v in payload.items() if isinstance(v, (int, float))}
        if cache is not None:
            cache[cache_key] = dict(norm)
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
    for c in (ctx.raw_candidates or []):
        cand = dict(c)
        cand["_narr_cache"] = ctx.narrative_score_cache
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
            cand_start = max(0.0, cand_start - 3.0)
            cand_end = min(media_end, cand_end + 4.0)
            cand["start"] = round(cand_start, 2)
            cand["end"] = round(max(cand_start + 0.01, cand_end), 2)

        cand.setdefault("score_base", float(cand.get("score", 0.0) or 0.0))
        cand = enrich_candidate(cand, ctx.audio_features, ctx.visual_features, ctx.brain)
        semantic_quality = float(cand.get("semantic_quality", cand.get("score_base", 0.0)) or 0.0)
        score_enriched = (
            0.40 * float(cand.get("impact", 0.0) or 0.0) +
            0.22 * float(cand.get("classic", 0.0) or 0.0) +
            0.20 * float(cand.get("meaning", 0.0) or 0.0) +
            0.18 * semantic_quality
        )
        cand["score_enriched"] = round(float(score_enriched), 4)
        curiosity_at_start = _clamp01((cand.get("metrics", {}) or {}).get("curiosity_at_start", cand.get("curiosity", 0.0)))
        curiosity_peak = _clamp01((cand.get("metrics", {}) or {}).get("curiosity_peak", cand.get("curiosity", 0.0)))
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
        trigger_density = float(len(overlapping_triggers)) / max(1.0, duration_s / 6.0)
        trigger_density = _clamp01(trigger_density)
        trigger_bonus = 0.2 if "belief_reversal" in trigger_types else 0.0
        narrative_density = _clamp01(narrative_scores.get("information_density_score", 0.0))
        viral_density = _clamp01(
            min(1.0, (float(insight_count) / max(1.0, duration_s)) * 0.65 + (narrative_density * 0.35))
        ) if enable_viral_density else 0.0
        surprise_factor = _clamp01(max(cand.get("novelty", 0.0), narrative_scores.get("pattern_break_score", 0.0)))
        cand["signals"] = {
            "psychology": {
                "curiosity": float(cand.get("curiosity", 0.0) or 0.0),
                "curiosity_peak": curiosity_peak,
                "curiosity_start": curiosity_at_start,
                "punch_confidence": float(cand.get("punch_confidence", 0.0) or 0.0),
                "payoff_confidence": payoff_conf,
                "tension_gradient": tension_gradient,
            },
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
        cand.pop("_narr_cache", None)
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
            cand["validation"] = {"accepted": bool(ok), "reasons": [] if ok else [reason]}
            if ok:
                accepted.append(cand)
            else:
                rejected.append(cand)

    # Smart fallback: if validation removed everything, reuse already-computed candidates.
    if not accepted:
        fallback_source = enriched_before_validation or list(ctx.raw_candidates or [])
        if fallback_source:
            log.warning("[ORCH-FALLBACK] validation removed all candidates, using enriched candidates")
            accepted = sorted(
                fallback_source,
                key=lambda x: float((x or {}).get("score_enriched", (x or {}).get("score", 0.0)) or 0.0),
                reverse=True,
            )[: max(1, int(ctx.top_k or 1))]
            rejected = []

    ctx.enriched_candidates = accepted
    ctx.validated_candidates = list(accepted or [])
    ctx.rejected_candidates = rejected
    _record_stage(
        ctx,
        "L8_VALIDATION_GATES",
        accepted=len(accepted),
        rejected=len(rejected),
        wall_s=round(time.time() - t0, 3),
    )


def _run_ranking(ctx: PipelineContext) -> None:
    t0 = time.time()
    use_viral_score = _env_bool("HS_ENABLE_ALIGNMENT_SCORING", True)
    for cand in (ctx.enriched_candidates or []):
        psych = cand.get("signals", {}).get("psychology", {})
        sem = cand.get("signals", {}).get("semantic", {})
        nar = cand.get("signals", {}).get("narrative", {})
        eng = cand.get("signals", {}).get("engagement", {})
        curiosity_peak = _clamp01(psych.get("curiosity_peak", psych.get("curiosity", 0.0)))
        semantic_impact = _clamp01(sem.get("impact", 0.0))
        semantic_score = _clamp01((0.5 * semantic_impact) + (0.3 * _clamp01(sem.get("meaning", 0.0))) + (0.2 * _clamp01(sem.get("clarity", 0.0))))
        engagement_energy = _clamp01(eng.get("energy", eng.get("classic", 0.0)))
        engagement_score = _clamp01((0.6 * engagement_energy) + (0.25 * _clamp01(eng.get("audio", 0.0))) + (0.15 * _clamp01(eng.get("motion", 0.0))))
        trigger_density = _clamp01(nar.get("trigger_density", 0.0))
        trigger_score = _clamp01(nar.get("trigger_score", 0.0))
        trigger_type = str(nar.get("trigger_type", "") or "")
        narrative_score = _clamp01((0.55 * trigger_score) + (0.45 * trigger_density) + (0.2 if trigger_type == "belief_reversal" else 0.0))
        payoff_confidence = _clamp01(psych.get("payoff_confidence", cand.get("payoff_confidence", 0.0)))
        base_viral_score = (
            0.40 * curiosity_peak +
            0.30 * semantic_score +
            0.20 * engagement_score +
            0.10 * narrative_score
        )
        cand["base_viral_score"] = round(float(base_viral_score), 4)
        viral_score = float(base_viral_score * payoff_confidence)
        if bool(cand.get("insight_candidate", False)):
            viral_score *= 1.08
        cand["viral_score"] = round(float(viral_score), 4)

    ranked = sorted(
        (ctx.enriched_candidates or []),
        key=lambda x: float(
            x.get("viral_score", x.get("score_enriched", x.get("score", 0.0)))
            if use_viral_score else x.get("score_enriched", x.get("score", 0.0))
        ),
        reverse=True,
    )
    ranked = dedupe_by_overlap(ranked, overlap_threshold=0.75)
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
    for c in final:
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
        avg_viral_score=round(sum(float(c.get("viral_score", 0.0) or 0.0) for c in final) / float(max(1, len(final))), 4),
        wall_s=round(time.time() - t0, 3),
    )


def _run_arc_assembler(ctx: PipelineContext) -> None:
    t0 = time.time()
    transcript = list(ctx.transcript or [])
    ranked = list(ctx.ranked_output or ctx.final_candidates or [])
    if (not transcript) or (not ranked):
        _record_stage(ctx, "L10_ARC_ASSEMBLER", input=len(ranked), arcs=0, complete=0, wall_s=round(time.time() - t0, 3))
        return

    min_clip = 15.0
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
        for j in range(max(0, start_idx - 2), hook_scan_end):
            seg_s, seg_e = _seg_bounds(transcript[j])
            seg_scores = compute_quality_scores(transcript, seg_s, seg_e) if compute_quality_scores else {}
            hook_score = _clamp01(seg_scores.get("hook_score", nar.get("hook_score", 0.0)))
            pattern_break = _clamp01(seg_scores.get("pattern_break_score", nar.get("pattern_break_score", 0.0)))
            if (hook_score > 0.2) or (pattern_break > 0.25) or (candidate_curiosity_peak > 0.25):
                hook_idx = j
                hook_found = True
                break

        hook_seg = transcript[hook_idx]
        hook_start, hook_end = _seg_bounds(hook_seg)
        arc_start = hook_start
        # Backward expansion: include short setup context immediately before hook.
        for seg in reversed(transcript[:hook_idx]):
            prev_s, prev_e = _seg_bounds(seg)
            if prev_e < hook_start and (hook_start - prev_e) < lookback_s:
                arc_start = min(arc_start, prev_s)
                break
        arc_end = max(hook_end, e0)
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
        # Avoid abrupt starts by keeping a small amount of pre-hook context.
        arc_start = max(0.0, arc_start - 1.5)
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
        if str(nar.get("trigger_type", "") or "") == "belief_reversal":
            arc_score = _clamp01(arc_score * 1.2)
        arc_complete = bool(hook_found and (payoff_idx is not None))
        if arc_complete:
            complete_count += 1
            arc_score = _clamp01(arc_score * 1.35)
        
        # 🔥 DURATION SWEET SPOT BONUS - Strongly prefer 12-25s (TikTok range)
        duration = arc_end - arc_start
        ideal_duration = 18.0
        if 12.0 <= duration <= 25.0:
            # Maximum preference at 18s, soft decay at edges
            duration_bonus = max(0.0, 1.0 - (abs(duration - ideal_duration) / ideal_duration))
            arc_score = _clamp01(arc_score + (duration_bonus * 0.10))  # +0.10 max bonus

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
        c["viral_score"] = round(float(arc_score), 4)
        c["provenance"] = {"stage": "L10_ARC_ASSEMBLER"}
        out.append(c)

    out = sorted(out, key=lambda x: float(x.get("arc_score", x.get("viral_score", x.get("score_enriched", 0.0))) or 0.0), reverse=True)
    # � SMART DEDUPLICATION: Uses overlap-ratio based detection instead of strict time tolerance
    # Fixes duplicate_arcs from overlapping hooks (e.g. hooks 56-59 on same payoff 63)
    out = dedupe_by_overlap(out, overlap_threshold=0.75)
    ctx.final_candidates = list(out[: max(1, int(ctx.top_k or 1))])
    ctx.ranked_output = list(ctx.final_candidates)
    log.info("[ORCH-ARC] assembled=%d complete=%d input=%d", len(ctx.ranked_output), complete_count, len(ranked))
    _record_stage(
        ctx,
        "L10_ARC_ASSEMBLER",
        input=len(ranked),
        arcs=len(ctx.ranked_output),
        complete=complete_count,
        avg_arc_duration=round(sum(float(c.get("duration", 0.0) or 0.0) for c in ctx.ranked_output) / float(max(1, len(ctx.ranked_output))), 3),
        wall_s=round(time.time() - t0, 3),
    )


def _run_editor_refiner(ctx: PipelineContext) -> None:
    t0 = time.time()
    clips = list(ctx.ranked_output or ctx.final_candidates or [])
    transcript = list(ctx.transcript or [])
    if (not clips) or (not transcript):
        _record_stage(ctx, "L12_EDITOR_REFINER", input=len(clips), output=len(clips), wall_s=round(time.time() - t0, 3))
        return

    pre_pad = 1.2
    post_pad = 1.5
    pre_hook_context = 1.2
    ideal_len = 22.0
    max_silence_gap = 1.5
    out: List[Dict[str, Any]] = []

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
                or (trigger_type == "belief_reversal")
            )
            strength = _clamp01((0.45 * hook_score) + (0.35 * pattern_break) + (0.20 * curiosity_peak))
            if qualifies and (strength >= best_strength):
                best_strength = strength
                best_seg = seg
        return best_seg, best_strength

    for clip_idx, clip in enumerate(clips):
        c = dict(clip or {})
        s = float(c.get("start", 0.0) or 0.0)
        e = float(c.get("end", s) or s)
        if e <= s:
            out.append(c)
            continue

        # 1) Context padding
        s = max(0.0, s - pre_pad)
        e = e + post_pad

        # 2) Sentence boundary correction
        prev_seg = _find_prev_seg(s)
        if prev_seg:
            prev_text = str(prev_seg.get("text", "") or "").strip()
            _, prev_end = _seg_bounds(prev_seg)
            if prev_text.endswith((".", "?", "!")):
                s = max(s, prev_end)

        # 3) Silence trim (cut at first large internal gap)
        segs = sorted(_segments_in_window(s, e), key=lambda x: float(x.get("start", 0.0) or 0.0))
        if len(segs) >= 2:
            for i in range(len(segs) - 1):
                _, a_e = _seg_bounds(segs[i])
                b_s, _ = _seg_bounds(segs[i + 1])
                gap = b_s - a_e
                if gap > max_silence_gap and (a_e - s) >= 15.0:
                    e = a_e
                    break

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

        # Hook optimizer: ensure hook lands in first 0-3s where possible.
        hook_seg, hook_strength = _best_hook_segment_in_window(s, e, nar, psych)
        hook_offset = 0.0
        if hook_seg:
            hs, he = _seg_bounds(hook_seg)
            hook_offset = max(0.0, hs - s)
            # Weak-hook recovery: search forward for stronger pattern-break in window.
            if hook_strength < 0.15:
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
            if hook_offset > 3.0:
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
        c["end"] = round(float(e), 2)
        c["duration"] = round(float(duration), 2)
        c["editor_score"] = round(float(editor_score), 4)
        c["final_score"] = round(float(final_score), 4)
        c["hook_score"] = round(float(hook_metric), 4)
        c["open_loop_score"] = round(float(open_loop_metric), 4)
        c["payoff_score"] = round(float(payoff_metric), 4)
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
            "\n[CLIP %d]\nduration: %.1fs\narc_score: %.3f\nfinal_score: %.3f\n"
            "HOOK_SCORE: %.3f\nOPEN_LOOP_SCORE: %.3f\nPAYOFF_SCORE: %.3f\n"
            "SEMANTIC: impact=%.3f meaning=%.3f novelty=%.3f clarity=%.3f\n\n"
            "HOOK:\n%s\n\nBUILD:\n%s\n\nPAYOFF:\n%s\n\nFULL MOMENT:\n%s\n",
            int(clip_idx),
            float(duration),
            float(arc_score),
            float(final_score),
            float(hook_metric),
            float(open_loop_metric),
            float(payoff_metric),
            float(_clamp01(sem.get("impact", 0.0))),
            float(_clamp01(sem.get("meaning", 0.0))),
            float(_clamp01(sem.get("novelty", 0.0))),
            float(_clamp01(sem.get("clarity", 0.0))),
            str((c.get("hook_segment") or {}).get("text", "") or ""),
            str(build_text or ""),
            str((c.get("payoff_segment") or {}).get("text", "") or ""),
            str(c.get("text", "") or ""),
        )
        c["viral_score"] = round(float(final_score), 4)
        c["provenance"] = {"stage": "L12_EDITOR_REFINER"}
        out.append(c)

    out = sorted(out, key=lambda x: float(x.get("final_score", x.get("arc_score", x.get("viral_score", 0.0))) or 0.0), reverse=True)
    out = dedupe_by_overlap(out, overlap_threshold=0.75)
    ctx.final_candidates = list(out[: max(1, int(ctx.top_k or 1))])
    ctx.ranked_output = list(ctx.final_candidates)
    _record_stage(
        ctx,
        "L12_EDITOR_REFINER",
        input=len(clips),
        output=len(ctx.ranked_output),
        avg_duration=round(sum(float(c.get("duration", 0.0) or 0.0) for c in ctx.ranked_output) / float(max(1, len(ctx.ranked_output))), 3),
        wall_s=round(time.time() - t0, 3),
    )


def _run_staged_pipeline(path: str, top_k: int, prefer_gpu: bool, use_cache: bool, allow_fallback: bool) -> List[Dict]:
    start = time.time()
    print("PIPELINE STAGE: start staged pipeline")
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
    if trace:
        trace.exit("L6B_GLOBAL_HOOK_HUNTER", {"candidates": len(ctx.raw_candidates or []), "injected": int((ctx.stage_stats.get("L6B_GLOBAL_HOOK_HUNTER", {}) or {}).get("injected", 0) or 0)})

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

    if trace:
        trace.enter("L10_RANKING")
    print("STAGE ENTER: ranking")
    _run_ranking(ctx)
    print("STAGE OK: ranking")
    if trace:
        trace.exit("L10_RANKING", {"final": len(ctx.ranked_output or [])})

    if trace:
        trace.enter("L11_ARC_ASSEMBLER")
    _run_arc_assembler(ctx)
    print("STAGE OK: arc assembler")
    if trace:
        trace.exit("L11_ARC_ASSEMBLER", {"final": len(ctx.ranked_output or [])})

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
    _record_stage(ctx, "SUMMARY", wall_s=round(time.time() - t0, 3), final=len(out), rejected=len(ctx.rejected_candidates))
    if trace:
        trace.render()
    print("TOTAL PROCESS TIME:", time.time() - start)
    return out


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
    print("🚨 ORCHESTRATOR ENTRYPOINT HIT")
    start_time = time.time()
    mode = _pipeline_mode(pipeline_mode)
    log.info("[ORCH] pipeline_mode=%s", mode)

    if mode == "staged":
        try:
            out = _run_staged_pipeline(
                path=path,
                top_k=top_k,
                prefer_gpu=prefer_gpu,
                use_cache=use_cache,
                allow_fallback=allow_fallback,
            )
            log.info("[ORCH] staged returned %d candidates.", len(out))
            log.info('[ORCH] Orchestration complete (t=%.2fs)', (time.time() - start_time))
            return out
        except Exception as exc:
            log.exception("[ORCH] staged pipeline failed: %s", exc)
            if not _env_bool("HS_ORCH_STAGED_FAILOVER_TO_LEGACY", False):
                return []
            log.error("STAGED PIPELINE CRASHED — FALLING BACK TO ULTRON")
            log.info("[ORCH] staged failover -> legacy")

    if not ultron_engine:
        log.error("[ORCH] FATAL: Ultron V33 engine (ultron_finder_v33.py) is not available.")
        return []

    try:
        result_envelope = ultron_engine(path, top_k=top_k, allow_fallback=allow_fallback)
        godmode_candidates = result_envelope.get("candidates", [])
        log.info("[ORCH] Ultron V33 Engine returned %d candidates.", len(godmode_candidates))
        elapsed = time.time() - start_time
        log.info('[ORCH] Orchestration complete (t=%.2fs)', elapsed)
        return godmode_candidates
    except Exception as exc:
        log.exception("[ORCH] Ultron V33 engine failed: %s", exc)
        return []

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
