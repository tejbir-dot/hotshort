"""
payoff_resolver.py

Three-tier payoff detection system for HotShort.

Philosophy (from gpt.txt):
  Don't ask: "Did we fix code?"
  Ask:        "Did output change?"

The current PayoffEngine uses rigid keyword heuristics (debt_match gate).
It fails ~90% of threads because real payoffs say "And that changes everything."
instead of "therefore" or "meaning".

This module gives the Arc Assembler three escalating chances to find the payoff
BEFORE it collapses the clip to the Idea Graph defaults.

Tier 1 — Structural signals (0ms, free)
  Speakers physically behave differently when landing a payoff:
  - Short sentence after long ones
  - Silence/gap after the segment
  - Next segment shifts topic
  These are language-model-free, deterministic, and always available.

Tier 2 — Embedding contrast (~50ms, local MiniLM already loaded)
  The payoff is semantically DIFFERENT from the hook (it resolves, not restates)
  but closes the same loop.
  Score = semantic_distance(hook, candidate) * closure_signal(candidate)
  We use the already-loaded all-MiniLM-L6-v2 model; no new dependency.

Tier 3 — Groq batch fallback (400-800ms, ONE call per video for all failures)
  Called only for threads that Tier 1+2 could not resolve.
  Prompt is a single batched JSON with all failing threads.
  Anti-hallucination: must quote verbatim.
  The result is used to pin the Arc Assembler's end boundary.

Usage (from orchestrator or PayoffEngine):

    from utils.payoff_resolver import PayoffResolver

    resolver = PayoffResolver()

    # Returns the best payoff segment dict or None
    result = resolver.find(
        hook_text="If you want to make real money...",
        hook_start_s=10.0,
        candidate_window=list_of_seg_dicts,   # same format as transcript
        full_transcript=full_transcript,
        thread_id="c_cand_0",                  # for Groq batch grouping
    )

    if result:
        arc_end = result["end"]
"""

from __future__ import annotations

import logging
import math
import os
import re
from typing import Any, Dict, List, Optional

log = logging.getLogger("payoff_resolver")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Tier 1: how much shorter can a sentence be vs. the rolling average
# to count as a "punch-line drop"
_PUNCHLINE_LENGTH_RATIO = 0.45          # candidate is < 45% of avg length
_SILENCE_GAP_THRESHOLD_S = 0.35        # gap between segment end and next start
_TOPIC_SHIFT_WINDOW = 3                 # segments to look ahead for topic shift
_MIN_CANDIDATE_WORDS = 4               # ignore trivially short fragments

# Tier 1 closure vocabulary (language-agnostic in spirit but English-dominant)
_CLOSURE_VOCAB = frozenset([
    "that's why", "that's how", "that's the", "and that's",
    "so remember", "bottom line", "the point is", "in other words",
    "which means", "what this means", "this is why", "and that is",
    "the key is", "so basically", "ultimately", "finally",
    "and now you know", "that changes everything", "period",
    "full stop", "done", "game changer", "the answer is",
    "the lesson is", "so the lesson", "at the end of the day",
    # Hinglish
    "isliye", "yahi wajah", "matlab ye hai", "seedhi baat", "to samjho",
    "yahi karan", "ab samjhe",
])

_TOPIC_SHIFT_VOCAB = frozenset([
    "anyway", "moving on", "next", "so yeah", "alright",
    "let me", "now let's", "another thing", "the third",
    "the fourth", "and the last", "number two", "number three",
    "number four", "book two", "book three",
])

# Tier 2: thresholds
_EMBEDDING_CONTRAST_THRESHOLD = 0.18   # min cosine distance from hook (not a restatement)
_EMBEDDING_CLOSURE_THRESHOLD = 0.20    # min structural closure score from Tier 1

# Tier 3: Groq
_GROQ_MODEL = os.getenv("HS_PAYOFF_GROQ_MODEL", "llama-3.1-8b-instant")
_GROQ_TIMEOUT = 25

# ---------------------------------------------------------------------------
# Tier 1 — Structural Signal Scorer
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _word_count(text: str) -> int:
    return len(_normalize(text).split())


def _has_closure_vocab(text: str) -> bool:
    t = _normalize(text)
    return any(v in t for v in _CLOSURE_VOCAB)


def _next_segment_shifts_topic(segments: List[Dict], idx: int) -> bool:
    """Check if the segment AFTER idx starts a new topic."""
    for lookahead in range(1, _TOPIC_SHIFT_WINDOW + 1):
        nxt = idx + lookahead
        if nxt >= len(segments):
            break
        nxt_text = _normalize(segments[nxt].get("text", ""))
        if any(v in nxt_text for v in _TOPIC_SHIFT_VOCAB):
            return True
        # If a new list item is announced (e.g. "number two", "the second book")
        if re.search(r"\b(number|book|step|point|thing|part)\s+(one|two|three|four|five|\d)\b", nxt_text):
            return True
    return False


def _silence_after(segments: List[Dict], idx: int) -> float:
    """Return gap in seconds between end of segments[idx] and start of segments[idx+1]."""
    if idx + 1 >= len(segments):
        return 999.0  # EOF = silence
    cur_end = float(segments[idx].get("end", 0) or 0)
    nxt_start = float(segments[idx + 1].get("start", 0) or 0)
    return max(0.0, nxt_start - cur_end)


def _rolling_avg_word_count(segments: List[Dict], idx: int, window: int = 5) -> float:
    start = max(0, idx - window)
    counts = [_word_count(segments[i].get("text", "")) for i in range(start, idx)]
    return sum(counts) / max(1, len(counts))


def tier1_structural_score(
    segments: List[Dict],
    candidate_idx: int,
    hook_start_s: float,
) -> float:
    """
    Returns a 0-1 structural payoff score for segments[candidate_idx].
    Pure heuristics, zero latency.
    """
    seg = segments[candidate_idx]
    text = seg.get("text", "") or ""

    if _word_count(text) < _MIN_CANDIDATE_WORDS:
        return 0.0

    score = 0.0
    reasons = []

    # Must be after the hook
    seg_start = float(seg.get("start", 0) or 0)
    if seg_start < hook_start_s:
        return 0.0

    # Closure vocabulary (strong signal)
    if _has_closure_vocab(text):
        score += 0.45
        reasons.append("closure_vocab")

    # Silence after (speaker breathes after landing the point)
    gap = _silence_after(segments, candidate_idx)
    if gap >= _SILENCE_GAP_THRESHOLD_S:
        score += 0.20
        reasons.append(f"silence_gap={gap:.2f}s")

    # Punchline length drop (short sentence after long build)
    avg_len = _rolling_avg_word_count(segments, candidate_idx)
    this_len = _word_count(text)
    if avg_len > 8 and this_len < avg_len * _PUNCHLINE_LENGTH_RATIO:
        score += 0.15
        reasons.append(f"punchline_drop={this_len}/{avg_len:.0f}")

    # Topic shifts after this segment (natural ending)
    if _next_segment_shifts_topic(segments, candidate_idx):
        score += 0.20
        reasons.append("topic_shift_after")

    # Ends with strong punctuation
    stripped = text.strip()
    if stripped and stripped[-1] in ".!":
        score += 0.05
        reasons.append("terminal_punct")

    if reasons:
        log.debug("[T1] idx=%d score=%.2f reasons=%s text='%s'",
                  candidate_idx, score, reasons, text[:60])

    return min(1.0, score)


# ---------------------------------------------------------------------------
# Tier 2 — Embedding Contrast Scorer
# ---------------------------------------------------------------------------

_embedding_model = None
_embedding_model_failed = False


import threading
_embedding_model_lock = threading.Lock()

def _get_embedding_model():
    global _embedding_model, _embedding_model_failed
    if _embedding_model_failed:
        return None
    if _embedding_model is not None:
        return _embedding_model
        
    with _embedding_model_lock:
        if _embedding_model_failed:
            return None
        if _embedding_model is not None:
            return _embedding_model
            
        try:
            from sentence_transformers import SentenceTransformer
            import torch
            dev = "cuda" if torch.cuda.is_available() else "cpu"
            _embedding_model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2", device=dev)
            log.info(f"[T2] Embedding model loaded (MiniLM-L6-v2) on {dev}")
        except Exception as exc:
            log.warning("[T2] Could not load embedding model: %s — Tier 2 disabled", exc)
            _embedding_model_failed = True
            
    return _embedding_model


def _cosine(a, b) -> float:
    try:
        import numpy as np
        a = np.array(a, dtype=float)
        b = np.array(b, dtype=float)
        denom = (np.linalg.norm(a) * np.linalg.norm(b))
        if denom < 1e-9:
            return 0.0
        return float(np.dot(a, b) / denom)
    except Exception:
        return 0.0


def tier2_embedding_score(
    hook_text: str,
    candidate_text: str,
    t1_score: float,
) -> float:
    """
    Payoffs are semantically DISTANT from the hook (they resolve, not restate)
    but share the same topic domain.

    score = contrast * closure_signal
    where contrast = 1 - cosine_sim(hook_embed, candidate_embed)
    and closure_signal = t1_score (already computed structural signals)

    Returns 0.0 if embedding model is unavailable.
    """
    model = _get_embedding_model()
    if model is None:
        return 0.0

    if not hook_text or not candidate_text:
        return 0.0

    try:
        vecs = model.encode([hook_text, candidate_text], show_progress_bar=False)
        sim = _cosine(vecs[0], vecs[1])
        contrast = 1.0 - sim  # how different is payoff from hook

        # [FIX] Old formula: score = contrast * ... → maximally UNRELATED payoffs won.
        # A real payoff is somewhat different from hook (it resolves, not restate)
        # but still shares the same topic domain. Target sim range: 0.15 - 0.55
        # Sweet spot: sim=0.30 → contrast=0.70 → moderate_contrast peaks at 1.0
        # A completely unrelated segment (sim≈0, contrast≈1) gets lower score.
        # A near-restatement (sim≈0.9, contrast≈0.1) also gets lower score.
        # This curve rewards the middle: resolved-but-related payoffs.
        _IDEAL_CONTRAST = 0.65  # ideal semantic distance for a payoff
        moderate_contrast = max(0.0, 1.0 - abs(contrast - _IDEAL_CONTRAST) / _IDEAL_CONTRAST)

        # Structural closure (t1_score) is still a strong multiplier
        closure_weight = 0.4 + 0.6 * t1_score  # range: 0.4 (no structure) to 1.0 (strong structure)

        score = moderate_contrast * closure_weight
        print(f"[TIER2_DEBUG] sim={sim:.4f} contrast={contrast:.4f} moderate_contrast={moderate_contrast:.4f} t1_score={t1_score:.4f} score={score:.4f}")
        log.debug("[T2] sim=%.3f contrast=%.3f moderate_contrast=%.3f t1=%.2f score=%.3f text='%s'",
                  sim, contrast, moderate_contrast, t1_score, score, candidate_text[:60])
        return min(1.0, score)
    except Exception as exc:
        log.warning("[T2] Embedding scoring failed: %s", exc)
        return 0.0


# ---------------------------------------------------------------------------
# Tier 3 — Groq Batch Fallback
# ---------------------------------------------------------------------------

def tier3_groq_batch(
    pending: List[Dict[str, Any]],
) -> Dict[str, Dict]:
    """
    Send a single batched Groq call for all pending threads.

    pending = [
        {
            "thread_id": str,
            "hook_text": str,
            "transcript_window": str,   # pre-formatted text, NOT a list
        },
        ...
    ]

    Returns: { thread_id -> { "payoff_quote": str, "resolution_score": float } }
    """
    if not pending:
        return {}

    try:
        from viral_finder.groq_cortex import is_groq_enabled, _get_groq_api_key, post_groq_completions
        if not is_groq_enabled():
            log.info("[T3] Groq disabled — Tier 3 skipped")
            return {}
        api_key = _get_groq_api_key()
        if not api_key:
            log.warning("[T3] GROQ_API_KEY not set — Tier 3 skipped")
            return {}
    except ImportError:
        return {}

    import json
    import requests

    system_prompt = (
        "You are a Narrative Resolution Engine for a video clipping system.\n\n"
        "I will give you a list of open story threads. Each has:\n"
        " - thread_id: a unique identifier\n"
        " - hook_text: the opening promise made to the audience\n"
        " - transcript_window: the next 90 seconds of spoken text, segment by segment\n\n"
        "Your job: for each thread, find the EXACT sentence in the transcript_window "
        "that resolves the promise made in the hook.\n\n"
        "STRICT RULES:\n"
        "1. The payoff is the structural resolution — the 'aha', the final lesson, "
        "the actionable answer, or the climax of the story.\n"
        "2. You MUST return the exact verbatim quote from the transcript_window. "
        "Do not paraphrase or alter a single word.\n"
        "3. If the hook is never resolved within the window, return payoff_found=false.\n"
        "4. NEVER hallucinate text that is not in the transcript_window.\n"
        "5. You must provide a resolution_score between 0.0 and 1.0 representing your confidence that the quote perfectly resolves the hook.\n\n"
        "Return JSON ONLY in this exact format:\n"
        "{\n"
        '  "resolutions": [\n'
        "    {\n"
        '      "thread_id": "...",\n'
        '      "payoff_found": true,\n'
        '      "exact_payoff_quote": "The exact verbatim sentence from the transcript",\n'
        '      "resolution_score": 0.85,\n'
        '      "reasoning": "One sentence explaining why this is the payoff.",\n'
        '      "clip_title": "A 3-5 word punchy, catchy title summarizing the core idea of the entire storyline"\n'
        "    }\n"
        "  ]\n"
        "}"
    )

    payload = {
        "model": _GROQ_MODEL,
        "temperature": 0.05,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(pending, indent=2)},
        ],
    }

    log.info("[T3] Groq batch call: %d threads", len(pending))
    
    parsed = {}
    try:
        resp = post_groq_completions(payload=payload, timeout=_GROQ_TIMEOUT, max_retries=5)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        parsed = json.loads(content)
    except Exception as exc:
        log.error("[T3] Groq batch call failed after retries: %s", exc)
        return {}
    
    if not parsed:
        return {}

    results: Dict[str, Dict] = {}
    for item in parsed.get("resolutions", []):
        tid = str(item.get("thread_id", ""))
        if not tid:
            continue
        if not item.get("payoff_found", False):
            log.info("[T3] thread_id=%s → payoff_found=false", tid)
            continue
        quote = str(item.get("exact_payoff_quote", "")).strip()
        score = float(item.get("resolution_score", 0.0) or 0.0)
        reasoning = str(item.get("reasoning", ""))
        clip_title = str(item.get("clip_title", ""))
        log.info("[T3] thread_id=%s score=%.2f quote='%s' title='%s'", tid, score, quote[:80], clip_title)
        results[tid] = {"payoff_quote": quote, "resolution_score": score, "reasoning": reasoning, "clip_title": clip_title}

    return results


# ---------------------------------------------------------------------------
# Utilities: map a verbatim quote back to a transcript segment
# ---------------------------------------------------------------------------

def _quote_to_segment(
    quote: str,
    segments: List[Dict],
    search_start_s: float = 0.0,
) -> Optional[Dict]:
    """
    Find the transcript segment that best matches a verbatim quote string.
    Returns the segment dict or None.
    """
    if not quote or not segments:
        return None

    q_norm = _normalize(quote)
    best_seg = None
    best_overlap = 0

    q_tokens = set(q_norm.split())

    for i, seg in enumerate(segments):
        seg_start = float(seg.get("start", 0) or 0)
        if seg_start < search_start_s:
            continue
        seg_text = _normalize(seg.get("text", "") or "")
        if not seg_text:
            continue

        # Exact containment
        if q_norm in seg_text or seg_text in q_norm:
            seg_copy = dict(seg)
            seg_copy["idx"] = i
            return seg_copy

        # Token overlap
        seg_tokens = set(seg_text.split())
        overlap = len(q_tokens & seg_tokens) / max(1, len(q_tokens | seg_tokens))
        if overlap > best_overlap:
            best_overlap = overlap
            best_seg = seg
            best_idx = i

    # Accept if overlap is strong enough
    if best_overlap >= 0.55 and best_seg is not None:
        seg_copy = dict(best_seg)
        seg_copy["idx"] = best_idx
        return seg_copy

    return None


# ---------------------------------------------------------------------------
# Main Public API
# ---------------------------------------------------------------------------

class PayoffResolver:
    """
    Three-tier payoff resolver.

    Designed to be called from inside PayoffEngine.resolve() as a complement,
    or from the Arc Assembler directly when PayoffEngine returns None.

    The key insight (from gpt.txt engineering principle):
      Don't ask "Did we fix code?" — ask "Did output change?"
      The output here is arc_end. This module's job is to push arc_end to the
      correct timestamp instead of letting it collapse to the Idea Graph default.
    """

    # Tier 1 threshold: structural score to count as "found"
    TIER1_ACCEPT_THRESHOLD: float = 0.50

    # Tier 2 threshold: embedding contrast score to count as "found"
    TIER2_ACCEPT_THRESHOLD: float = 0.32

    # Tier 3: collected across the whole video, flushed once
    _groq_pending: List[Dict] = []
    _groq_results: Dict[str, Dict] = {}

    def __init__(self):
        # Per-instance pending so multi-video runs don't cross-contaminate
        self._groq_pending: List[Dict] = []
        self._groq_results: Dict[str, Dict] = {}

    # ------------------------------------------------------------------

    def find(
        self,
        hook_text: str,
        hook_start_s: float,
        candidate_window: List[Dict],
        full_transcript: List[Dict],
        thread_id: str = "",
        run_tier3: bool = True,
    ) -> Optional[Dict]:
        """
        Find the payoff for a single story thread.

        Returns a segment dict (with start/end/text/tier keys) or None.
        Call flush_groq_batch() at the end of the video to resolve Tier-3 results.

        candidate_window: list of segment dicts (start, end, text, idx)
                          covering the 90s after the hook.
        full_transcript:  full video transcript for Tier-3 window building.
        """
        if not candidate_window:
            return None

        # --- Tier 1 ---
        best_t1_idx: Optional[int] = None
        best_t1_score = 0.0

        for i, seg in enumerate(candidate_window):
            # Find position of this candidate in the full transcript for gap calc
            seg_start = float(seg.get("start", 0) or 0)
            # Locate in full_transcript for silence-gap computation
            full_idx = None
            for fi, fseg in enumerate(full_transcript):
                if abs(float(fseg.get("start", -9999) or -9999) - seg_start) < 0.05:
                    full_idx = fi
                    break
            if full_idx is None:
                full_idx = i  # fallback: use window index

            t1 = tier1_structural_score(full_transcript, full_idx, hook_start_s)
            if t1 > best_t1_score:
                best_t1_score = t1
                best_t1_idx = i

        if best_t1_score >= self.TIER1_ACCEPT_THRESHOLD and best_t1_idx is not None:
            winner = dict(candidate_window[best_t1_idx])
            seg_start = float(winner.get("start", 0) or 0)
            full_idx = winner.get("idx")
            if full_idx is None:
                for fi, fseg in enumerate(full_transcript):
                    if abs(float(fseg.get("start", -9999) or -9999) - seg_start) < 0.05:
                        full_idx = fi
                        break
            winner["idx"] = full_idx if full_idx is not None else best_t1_idx
            
            log.info(
                "\n[PAYOFF_RESOLVER] TIER1 SUCCESS\n"
                "  hook='%s'\n"
                "  payoff='%s'\n"
                "  t1_score=%.2f",
                hook_text[:60], str(winner.get("text", ""))[:60], best_t1_score,
            )
            return {**winner, "tier": 1, "tier1_score": best_t1_score}

        # --- Tier 2 ---
        best_t2_idx: Optional[int] = None
        best_t2_score = 0.0

        for i, seg in enumerate(candidate_window):
            seg_text = seg.get("text", "") or ""
            seg_start = float(seg.get("start", 0) or 0)
            
            # Skip the hook segment itself — comparing hook vs hook always gives sim=1.0
            if seg_start <= hook_start_s:
                continue
            if not seg_text or seg_text.strip() == hook_text.strip():
                continue
            
            # Use the stored full-transcript index if available; fallback to linear scan
            full_idx = seg.get("idx")
            if full_idx is None:
                for fi, fseg in enumerate(full_transcript):
                    if abs(float(fseg.get("start", -9999) or -9999) - seg_start) < 0.05:
                        full_idx = fi
                        break
            if full_idx is None:
                full_idx = i  # last-resort fallback
            
            t1_i = tier1_structural_score(full_transcript, full_idx, hook_start_s)
            t2 = tier2_embedding_score(hook_text, seg_text, t1_i)
            if t2 > best_t2_score:
                best_t2_score = t2
                best_t2_idx = i


        if best_t2_score >= self.TIER2_ACCEPT_THRESHOLD and best_t2_idx is not None:
            winner = dict(candidate_window[best_t2_idx])
            seg_start = float(winner.get("start", 0) or 0)
            full_idx = winner.get("idx")
            if full_idx is None:
                for fi, fseg in enumerate(full_transcript):
                    if abs(float(fseg.get("start", -9999) or -9999) - seg_start) < 0.05:
                        full_idx = fi
                        break
            winner["idx"] = full_idx if full_idx is not None else best_t2_idx
            
            log.info(
                "\n[PAYOFF_RESOLVER] TIER2 SUCCESS\n"
                "  hook='%s'\n"
                "  payoff='%s'\n"
                "  t2_score=%.2f",
                hook_text[:60], str(winner.get("text", ""))[:60], best_t2_score,
            )
            return {**winner, "tier": 2, "tier2_score": best_t2_score}

        # --- Tier 3: Execute Groq call inline immediately ---
        if run_tier3 and thread_id:
            window_text = "\n".join(
                f"[{i}] {seg.get('text', '').strip()}"
                for i, seg in enumerate(candidate_window)
            )
            pending_item = {
                "thread_id": thread_id,
                "hook_text": hook_text,
                "transcript_window": window_text,
            }
            log.info(
                "[PAYOFF_RESOLVER] TIER3 INLINE EXEC thread_id=%s hook='%s'",
                thread_id, hook_text[:60],
            )
            
            # Execute synchronously
            raw_results = tier3_groq_batch([pending_item])
            if thread_id in raw_results:
                data = raw_results[thread_id]
                quote = data.get("payoff_quote", "")
                seg = _quote_to_segment(quote, full_transcript, search_start_s=hook_start_s)
                if seg:
                    log.info(
                        "\n[PAYOFF_RESOLVER] TIER3 SUCCESS thread_id=%s\n  quote='%s'\n",
                        thread_id, quote[:60],
                    )
                    return {
                        **seg,
                        "tier": 3,
                        "tier3_score": data.get("resolution_score", 0.0),
                        "tier3_reasoning": data.get("reasoning", ""),
                        "tier3_quote": quote,
                        "tier3_title": data.get("clip_title", ""),
                    }
                else:
                    log.warning("[PAYOFF_RESOLVER] TIER3 quote not found in transcript: '%s'", quote[:80])

        return None

    # ------------------------------------------------------------------

    def flush_groq_batch(
        self,
        full_transcript: List[Dict],
        hook_start_lookup: Dict[str, float],
    ) -> Dict[str, Dict]:
        """
        Fire ONE Groq API call for all queued threads.
        Returns mapping: { thread_id -> segment_dict }
        Call this once at the end of Arc Assembly.

        hook_start_lookup: { thread_id -> hook_start_s } so we can
        do the quote→segment mapping correctly.
        """
        if not self._groq_pending:
            return {}

        raw_results = tier3_groq_batch(self._groq_pending)
        self._groq_pending = []

        resolved: Dict[str, Dict] = {}
        for tid, data in raw_results.items():
            quote = data.get("payoff_quote", "")
            hook_start = hook_start_lookup.get(tid, 0.0)
            seg = _quote_to_segment(quote, full_transcript, search_start_s=hook_start)
            if seg:
                resolved[tid] = {
                    **seg,
                    "tier": 3,
                    "tier3_score": data.get("resolution_score", 0.0),
                    "tier3_reasoning": data.get("reasoning", ""),
                    "tier3_quote": quote,
                    "tier3_title": data.get("clip_title", ""),
                }
                log.info(
                    "\n[PAYOFF_RESOLVER] TIER3 RESOLVED thread_id=%s\n"
                    "  quote='%s'\n"
                    "  seg_end=%.2f",
                    tid, quote[:60], float(seg.get("end", 0)),
                )
            else:
                log.warning(
                    "[PAYOFF_RESOLVER] TIER3 quote not found in transcript: '%s'", quote[:80]
                )

        self._groq_results.update(resolved)
        return resolved


# ---------------------------------------------------------------------------
# Convenience: standalone score a single segment (used for telemetry)
# ---------------------------------------------------------------------------

def score_segment_as_payoff(
    hook_text: str,
    hook_start_s: float,
    segment: Dict,
    segment_idx_in_transcript: int,
    full_transcript: List[Dict],
) -> Dict[str, float]:
    """
    Returns a full scoring breakdown for a single candidate segment.
    Useful for telemetry and debug logging.
    """
    t1 = tier1_structural_score(full_transcript, segment_idx_in_transcript, hook_start_s)
    t2 = tier2_embedding_score(hook_text, segment.get("text", "") or "", t1)
    return {
        "t1_structural": round(t1, 3),
        "t2_embedding": round(t2, 3),
        "combined": round((t1 * 0.55 + t2 * 0.45), 3),
    }


__all__ = [
    "PayoffResolver",
    "tier1_structural_score",
    "tier2_embedding_score",
    "tier3_groq_batch",
    "score_segment_as_payoff",
]
