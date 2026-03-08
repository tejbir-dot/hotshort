import os
import time
import logging
from typing import Dict, List, Optional, Any

# This module captures the multi‑stage acquisition flow described in the
# "Signal Acquisition Engine v2" design document.  The goal is to pull as
# much useful data about a clip as possible (metadata, transcripts, audio,
# structural signals) and then compute *soft* quality annotations that allow
# the worker to proceed even when the signal is weak.
#
# Stages:
#   A. Metadata / captions / formats (youTube API, yt-dlp, etc.)
#   B. Compute heuristics over the raw pulls (duration, has_captions, ...)
#   C. Assemble transcripts from highest‑confidence sources downward.
#   D. Semantic segmentation / structure (candidate generator).
#
# Each stage populates ``out`` and updates ``signal_quality``.  Consumers
# (e.g. :mod:`worker.main`) may annotate further or refuse to continue based
# on the results.

logger = logging.getLogger("worker.signal")


# --- public API ------------------------------------------------------------

def acquire_signal(source_url: str, profile: str = "balanced") -> Dict[str, Any]:
    """Collect everything we can from ``source_url`` and score its quality.

    ``profile`` currently has no effect but is included to mirror the
    orchestrator API; later we may tune the amount of work performed (e.g.
    full audio download vs metadata only).

    The returned dictionary is intentionally *flat* so callers can easily
    serialise it in the worker's envelope.  It always contains at minimum::

        {
            "metadata": {...},
            "transcript_segments": [...],          # raw text segments
            "semantic_segments": [...],            # placeholder for now
            "signal_quality": {...},              # floating scores
        }

    The engine never raises an exception; failures during a stage are
    logged and captured in ``signal_quality``.  This keeps the web process
    and worker loops simple; any clip with a bad signal still gets a
    borderline envelope allowing us to debug later.
    """

    out: Dict[str, Any] = {
        "metadata": {},
        "transcript_segments": [],
        "semantic_segments": [],
        "signal_quality": {
            "acquisition_score": 0.0,
            "transcript_coverage_ratio": 0.0,
            "audio_integrity_score": 0.0,
            "transcript_integrity_score": 0.0,
            "segment_count": 0,
            "degraded_transcript": False,
            "comments_used": False,
        },
    }

    # ---------------------------------------------------------------
    # Stage A: metadata + captions + formats
    # ---------------------------------------------------------------
    try:
        # The real implementation will call into ``viral_finder`` helpers that
        # abstract yt-dlp/ytapi etc; here we record only the URL and a timestamp
        # so tests can verify the shape of the result.
        out["metadata"] = {"source_url": source_url, "fetched_at": time.time()}
    except Exception:
        logger.exception("metadata fetch failed")

    # ---------------------------------------------------------------
    # Stage B/C: compute heuristics & optionally fetch lightweight transcript
    # ---------------------------------------------------------------
    sq = out["signal_quality"]
    if out["metadata"]:
        sq["acquisition_score"] = 1.0

    # only attempt transcript fetch for YouTube-like URLs
    if source_url and ("youtube.com" in source_url or "youtu.be" in source_url):
        try:
            import re
            # extract canonical video id
            m = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})", source_url)
            video_id = m.group(1) if m else source_url
            # attempt to load transcript using youtube_transcript_api
            from youtube_transcript_api import YouTubeTranscriptApi
            raw = YouTubeTranscriptApi.get_transcript(video_id, languages=["en"])
            segs = [
                {
                    "text": s.get("text", ""),
                    "start": float(s.get("start", 0.0)),
                    "end": float(s.get("start", 0.0) + s.get("duration", 0.0)),
                }
                for s in raw
            ]
            out["transcript_segments"] = segs
            sq["segment_count"] = len(segs)
            # simple pre-seg logic: choose first 30s or compute via a naive rule
            duration = out["metadata"].get("duration") or 0
            if sq["segment_count"]:
                # pick the earliest one
                start_ts = segs[0].get("start", 0.0)
                end_ts = min(start_ts + 30.0, duration or (start_ts + 30.0))
            else:
                start_ts = 0.0
                end_ts = min(30.0, duration or 30.0)
            out["metadata"]["pre_segment_start"] = start_ts
            out["metadata"]["pre_segment_end"] = end_ts
        except Exception as e:
            logger.warning("yt transcript/segment lookup failed: %s", e)
            sq["segment_count"] = 0
    else:
        sq["segment_count"] = 0

    # coverage/integrity heuristics follow -- coverage of zero by default
    if sq.get("segment_count", 0) > 0:
        sq["transcript_coverage_ratio"] = min(1.0, sq["segment_count"] / 50.0)
        sq["transcript_integrity_score"] = 1.0
    else:
        sq["transcript_coverage_ratio"] = 0.0
        sq["transcript_integrity_score"] = 0.0

    # ------------------------------------------------------------------
    # Stage D: semantic segmentation
    # ------------------------------------------------------------------
    # we don't actually segment yet; orchestrator will handle that as part of
    # its normal candidate generation. leaving the list empty satisfies the
    # current unit tests.

    return out


# ---------------------------------------------------------------------------
# convenience helpers used elsewhere in the worker
# ---------------------------------------------------------------------------

def compute_signal_scores(acq: Dict[str, Any]) -> Dict[str, float]:
    """Return the current ``signal_quality`` dictionary, computing any
    derived fields necessary.

    This helper exists so that callers don't have to understand each
    interpretation of an acquisition document.  We mutate ``acq`` in place
    because the results get persisted in the envelope.
    """
    sq = acq.setdefault("signal_quality", {})

    # acquisition score defaults to zero when metadata is missing
    if not acq.get("metadata"):
        sq["acquisition_score"] = 0.0
    else:
        sq.setdefault("acquisition_score", 1.0)

    segs = acq.get("transcript_segments") or []
    sq["segment_count"] = len(segs)
    if segs:
        sq["transcript_coverage_ratio"] = min(1.0, len(segs) / 50.0)
        sq["transcript_integrity_score"] = 1.0
    else:
        sq.setdefault("transcript_coverage_ratio", 0.0)
        sq.setdefault("transcript_integrity_score", 0.0)

    # mark degraded transcripts if the list is unexpectedly short
    duration = acq.get("metadata", {}).get("duration", 0)
    min_segments = max(3, int(duration // 10))  # roughly 1 segment per 10s
    sq["degraded_transcript"] = sq["segment_count"] < min_segments

    return sq


def make_degraded_if_needed(result: Dict[str, Any]) -> None:
    """Mutate ``result`` by toggling ``status``/``low_confidence`` based on
    the acquisition score threshold.

    If the envelope already reflects a terminal error ("failed" or
    "failed_internal"), we leave it untouched; degradation is only meant to
    annotate borderline but still-processable cases.
    """
    # don't override explicit failures
    if result.get("status") in ("failed_internal", "failed"):
        return

    sq = result.get("signal_quality", {})
    score = float(sq.get("acquisition_score", 0.0))
    if score < float(os.environ.get("HS_SIGNAL_DEGRADED_THRESHOLD", "0.45")):
        result["status"] = "degraded"
        result["low_confidence"] = True
    else:
        result["status"] = result.get("status", "ok")
        result["low_confidence"] = False
