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
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Optional

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
    from viral_finder.ultron_brain import load_ultron_brain, ultron_brain_score, ultron_learn
except Exception:
    load_ultron_brain = lambda: None
    ultron_brain_score = lambda text, brain=None: (0.0, 0.0, 0.0, 0.0, 0.0)
    ultron_learn = lambda brain, impact, score: None

# small utility fallbacks that your repo likely already supplies
try:
    from viral_finder.ultron_finder_v33 import fuse, dedupe_by_time, text_overlap, extend_until_sentence_complete
except Exception:
    fuse = lambda hook, audio, motion: float((hook + (audio or 0) + (motion or 0)) / 3.0)
    dedupe_by_time = lambda arr, time_tol=0.5: arr
    text_overlap = lambda a, b: 0.0
    extend_until_sentence_complete = lambda s, p, trs, max_extend=6.0: p

# core config
CACHE_DIR = ".hotshort_transcripts_cache"
DEFAULT_TOP_K = 8
MAX_ENRICH_WORKERS = max(2, (os.cpu_count() or 2) - 1)

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
        impact, meaning, novelty, emotion, clarity = ultron_brain_score(candidate.get('text','') or '', brain)
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
from typing import Tuple
def validate_candidate_by_curiosity(curve, start_t, end_t, payoff_conf, min_peak=0.22, payoff_conf_thresh=0.5) -> Tuple[bool, str]:
    # simple policy gate similar to your previous code
    if payoff_conf is None or payoff_conf < payoff_conf_thresh:
        return False, 'payoff_low'
    if not curve or len(curve) < 3:
        return False, 'no_curve'
    window = [v for (t, v) in curve if start_t <= t <= end_t]
    if not window or len(window) < 3:
        return False, 'too_short_window'
    peak = max(window)
    if peak < min_peak:
        return False, 'no_curiosity_peak'
    if window[-1] > window[-2] + 0.02:
        return False, 'no_curiosity_drop'
    return True, 'ok'

# -------------------------
# Orchestration core
# -------------------------

def orchestrate(path: str,
                 top_k: int = DEFAULT_TOP_K,
                 prefer_gpu: bool = True,
                 use_cache: bool = True,
                 allow_fallback: bool = False) -> List[Dict]:
    """High-level orchestration: returns final candidate clips (list of dicts).

    The function attempts to use the most advanced chain available in the repo.
    It aims to combine: transcript -> curiosity/punch analysis -> idea_graph -> parallel_mind -> candidate selection -> enrichment -> final gating
    """
    start_time = time.time()
    brain = load_ultron_brain()

    # 1) Transcript (try cached)
    trs = None
    if use_cache:
        trs = _load_cached_transcript(path)
        if trs:
            log.info("[ORCH] cache hit for transcript")

    if not trs:
        try:
            # prefer gemini_transcribe / transcribe_and_analyze if available
            if transcribe_and_analyze:
                log.info('[ORCH] running transcribe_and_analyze (gemini)')
                trs, feats, curiosity_curve, curiosity_candidates = transcribe_and_analyze(path, model_name='small', device=('cuda' if prefer_gpu else 'cpu'), aud=None, vis=None, brain=brain)
                if use_cache and isinstance(trs, list):
                    _save_cached_transcript(path, trs)
            elif gemini_transcribe:
                log.info('[ORCH] running gemini_transcribe')
                trs = gemini_transcribe(path, model_name='small', prefer_gpu=prefer_gpu)
                if use_cache and isinstance(trs, list):
                    _save_cached_transcript(path, trs)
            elif legacy_transcribe:
                log.info('[ORCH] running legacy_transcribe')
                trs = legacy_transcribe(path, model_name='small', prefer_gpu=prefer_gpu)
                if use_cache and isinstance(trs, list):
                    _save_cached_transcript(path, trs)
            elif extract_transcript:
                log.info('[ORCH] using extract_transcript')
                trs = extract_transcript(path)
            else:
                raise RuntimeError('no transcription backend available')
        except Exception as exc:
            log.exception('[ORCH] transcription failed: %s', exc)
            trs = []

    total_segs = len(trs or [])
    log.info('[ORCH] transcript segments: %d', total_segs)
    if total_segs < 3:
        log.error('[INVARIANT] transcript_segments too low (got %d) for %s', total_segs, path)

    # 2) audio / visual analysis (fast)
    aud = analyze_audio(path) or []
    vis = analyze_visual(path) or []

    # 3) curiosity/punch candidates
    curiosity_candidates = []
    curiosity_curve = None
    if analyze_curiosity_and_detect_punches and trs:
        try:
            feats, curiosity_curve, curiosity_candidates = analyze_curiosity_and_detect_punches(trs, aud=aud, vis=vis, brain=brain)
            log.info('[ORCH] curiosity candidates: %d', len(curiosity_candidates or []))
        except Exception:
            curiosity_candidates = []

    # 4) idea graph -> nodes
    nodes = []
    if build_idea_graph and trs:
        try:
            nodes = build_idea_graph(trs, aud=aud, vis=vis, curiosity_candidates=curiosity_candidates, brain=brain) or []
            log.info('[ORCH] idea graph nodes: %d', len(nodes))
        except Exception:
            nodes = []

    # 5) candidate selection
    candidates = []
    if select_candidate_clips and nodes:
        try:
            # node -> candidate conversion + initial scoring
            candidates = select_candidate_clips(nodes, top_k=(top_k * 3), transcript=trs, ensure_sentence_complete=True)
            log.info('[ORCH] raw candidates from selector: %d', len(candidates))
        except Exception:
            candidates = []

    if len(candidates) < 2:
        log.error('[INVARIANT] viral_candidates below minimum (got %d) for %s', len(candidates), path)

    # fallback: naive sliding windows if nothing found
    if not candidates and allow_fallback and total_segs:
        log.info('[ORCH] fallback windows generation')
        total_dur = float(trs[-1].get('end', trs[-1].get('start', 0.0) + 60.0)) if trs else 60.0
        step = max(10, int(total_dur // max(1, top_k)))
        for i in range(top_k):
            s = i * step
            e = min(total_dur, s + min(15, step))
            candidates.append({'text': '', 'start': float(s), 'end': float(e), 'score': 0.0, 'fingerprint': _fingerprint('', s, e)})

    # 6) Enrich candidates in parallel (audio/motion/brain)
    enriched = []
    if candidates:
        with ThreadPoolExecutor(max_workers=min(MAX_ENRICH_WORKERS, len(candidates))) as ex:
            futs = {ex.submit(enrich_candidate, dict(c), aud, vis, brain): c for c in candidates}
            for fut in as_completed(futs):
                try:
                    enriched.append(fut.result())
                except Exception as exc:
                    log.exception('[ORCH] enrichment failed: %s', exc)

    # 7) validate via curiosity/payoff curve where available
    validated = []
    for c in enriched:
        payoff_conf = c.get('payoff_confidence') or c.get('payoff_conf') or None
        ok = True
        reason = 'no_curiosity_check'
        if curiosity_curve is not None:
            ok, reason = validate_candidate_by_curiosity(curiosity_curve, c['start'], c['end'], payoff_conf)
        if ok:
            validated.append(c)
        else:
            # keep high-impact or high-semantic as a special-case
            if c.get('impact', 0.0) > 0.6 or c.get('semantic_quality', 0.0) > 0.6:
                validated.append(c)
            else:
                log.debug('[ORCH] rejected candidate %s reason=%s', c.get('fingerprint'), reason)

    # Backfill to preserve requested volume when gates are too strict.
    # Keeps quality-first ordering but avoids collapsing to very low clip counts.
    if len(validated) < top_k and enriched:
        seen = set()
        for c in validated:
            fp = c.get('fingerprint') or _fingerprint(c.get('text', ''), c.get('start', 0.0), c.get('end', 0.0))
            seen.add(fp)

        for c in sorted(enriched, key=lambda x: (-x.get('score', 0.0), x.get('start', 0.0))):
            if len(validated) >= top_k:
                break
            fp = c.get('fingerprint') or _fingerprint(c.get('text', ''), c.get('start', 0.0), c.get('end', 0.0))
            if fp in seen:
                continue
            validated.append(c)
            seen.add(fp)

    # 8) dedupe & stitch
    try:
        deduped = dedupe_by_time(validated, time_tol=0.75)
    except Exception:
        deduped = validated

    # stitch neighbours
    stitched = []
    for c in sorted(deduped, key=lambda x: (x['start'], -x.get('score', 0.0))):
        if not stitched:
            stitched.append(dict(c))
            continue
        prev = stitched[-1]
        if c['start'] - prev['end'] <= 3.0 and text_overlap(prev.get('text',''), c.get('text','')) > 0.32:
            prev['end'] = round(max(prev['end'], c['end']), 2)
            prev['text'] = (prev.get('text','') + ' ' + c.get('text','')).strip()
            prev['score'] = round(max(prev.get('score',0.0), c.get('score',0.0)), 4)
        else:
            stitched.append(dict(c))

    # 9) final ordering & diversity pick
    final = []
    used_starts = []
    for c in sorted(stitched, key=lambda x: (-x.get('score',0.0), x.get('start',0.0))):
        if len(final) >= top_k:
            break
        if any(abs(c['start'] - s) < 3.0 for s in used_starts):
            continue
        # attach unique WHY per clip
        c["why"] = build_why_for_clip(c)

        final.append(c)

        used_starts.append(c['start'])

    elapsed = time.time() - start_time
    log.info('[ORCH] orchestration complete: %d final clips (t=%.2fs)', len(final), elapsed)
    return final

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
    args = p.parse_args()

    res = orchestrate(args.file, top_k=args.top_k, prefer_gpu=args.gpu, use_cache=(not args.no_cache), allow_fallback=args.allow_fallback)
    import json
    print(json.dumps(res, indent=2))
