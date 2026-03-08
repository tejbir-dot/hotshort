import os
import time
import logging
from typing import Optional, Dict, Any, List

from models.user import db, Job
from worker import contracts
from worker import signal_acquisition_engine as sae

logger = logging.getLogger("worker.main")


def fetch_pending_job() -> Optional[Job]:
    """Return one pending job if available.
    We rely on the existing Job table; status="pending" indicates queue entry.
    The worker should claim a job by updating its status to "processing" before
    working on it to avoid duplication.
    """
    job = Job.query.filter_by(status="pending").order_by(Job.created_at).first()
    return job


def process_job(job: Job):
    """Main per-job orchestration logic.

    Reads request payload from ``job.analysis_data`` (as stored by render),
    runs acquisition/cognition/etc, updates the Job.record with the result
    envelope when done.
    """
    try:
        req_payload = {}
        if job.analysis_data:
            import json
            try:
                req_payload = json.loads(job.analysis_data)
            except Exception:
                logger.warning("job %s contained invalid JSON input", job.id)
                req_payload = {}
        # ensure the payload validates (or at least normalize it)
        try:
            params = contracts.validate_worker_request(req_payload)
        except Exception as e:
            logger.error("job %s invalid request: %s", job.id, e)
            job.status = "failed"
            job.analysis_data = json.dumps({"error": str(e)})
            db.session.commit()
            return

        # Acquire signal (stages A-D)
        acq = sae.acquire_signal(params.get("source_url"), profile=params.get("profile"))
        sq = sae.compute_signal_scores(acq)
        acq["signal_quality"] = sq

        # initial envelope, will be updated as we go
        result: Dict[str, Any] = {
            "job_id": job.id,
            "status": "ok",
            "selection_mode": params.get("profile", "godmode"),
            "low_confidence": False,
            "confidence_score": sq.get("acquisition_score", 0.0),
            "signal_quality": sq,
            "clips": [],
            "diagnostics": {
                "segments_count": sq.get("segment_count", 0),
                "idea_nodes": 0,
                "raw_candidates": 0,
                "dominant_cluster_score": 0.0,
            },
        }

        # if acquisition indicated an unusually low transcript count relative to
        # expected duration, force an orch cache bypass so that we re‑transcribe
        # rather than reuse stale/short data.  this mimics the "low‑segment"
        # guard described in the v2 design doc.
        duration = acq.get("metadata", {}).get("duration", 0)
        seg_count = sq.get("segment_count", 0)
        min_expected = max(3, int(duration // 10))
        use_cache = True
        if seg_count < min_expected:
            logger.warning(
                "[WORKER] low transcript segments (%d < %d); will bypass orch cache",
                seg_count,
                min_expected,
            )
            use_cache = False

        # attempt to download the selected segment (if we have any) so that
        # orchestrator operates on a local file path.  we swallow all errors
        # because tests may run without network or yt libraries.
        video_path: Optional[str] = None
        try:
            from app import acquire_youtube_media_robust
            start_ts = acq.get("metadata", {}).get("pre_segment_start", 0.0)
            end_ts = acq.get("metadata", {}).get("pre_segment_end", None)
            video_path, acq_score, attempts, probe, js_ok = acquire_youtube_media_robust(
                url=params.get("source_url"),
                start=start_ts,
                end=end_ts,
                output_dir="downloads",
                job_id=str(job.id),
                metadata=acq.get("metadata"),
            )
            # update diagnostic info from acquisition
            result["diagnostics"]["acquisition_attempts"] = attempts
            result["diagnostics"]["video_path"] = video_path
            # record path on the job itself for debugging/replay
            if video_path:
                job.video_path = video_path
            # if the download quality differs from initial score, update it
            sq["acquisition_score"] = acq_score
            result["confidence_score"] = acq_score
        except ImportError as e:
            logger.warning("[WORKER] download helper unavailable: %s", e)
        except Exception:
            logger.exception("[WORKER] media acquisition failed, continuing with empty path")

        # invoke orchestrator to compute final clips if we have a usable path
        clips: List[Dict[str, Any]] = []
        try:
            from viral_finder import orchestrator

            orch_args = {
                "prefer_gpu": False,
                "use_cache": use_cache,
                "pipeline_mode": "staged",
                "allow_fallback": False,  # Force disable legacy fallback
            }
            # ⚡ HARD-FORCE STAGED MODE: Match app.py strictness
            os.environ["HS_ORCH_PIPELINE_MODE"] = "staged"

            if video_path:
                clips = orchestrator.orchestrate(video_path, **orch_args)
            else:
                # fall back to URL; orchestrator may or may not tolerate this but
                # it'll at least log an error which we catch.
                clips = orchestrator.orchestrate(params.get("source_url"), **orch_args)

            result["clips"] = clips or []
            result["diagnostics"]["raw_candidates"] = len(clips or [])
            if clips:
                # copy a few statistics from the top candidate if present
                best = clips[0]
                result["diagnostics"]["idea_nodes"] = best.get("idea_nodes", 0)
                result["diagnostics"]["dominant_cluster_score"] = best.get(
                    "dominant_cluster_score", 0.0
                )
                # propagate any shadow metrics so front end can inspect if needed
                if "shadow_metrics" in best:
                    result["diagnostics"]["shadow_metrics"] = best["shadow_metrics"]
        except Exception:
            logger.exception("[WORKER] orchestrator invocation failed")
            result["status"] = "failed_internal"

        # adjust degraded flag based on possibly updated scores
        sae.make_degraded_if_needed(result)

        # commit output to job
        import json
        job.analysis_data = json.dumps(result)
        job.status = "completed" if result.get("status") != "failed_internal" else "failed"
        from datetime import datetime
        job.completed_at = datetime.utcnow()
        db.session.commit()
        logger.info("job %s processed, status=%s", job.id, result.get("status"))
    except Exception as e:
        logger.exception("Unhandled error processing job %s: %s", job.id, e)
        try:
            job.status = "failed"
            db.session.commit()
        except Exception:
            pass


def worker_loop(poll_interval: float = 2.0):
    """Run until killed: fetch pending jobs and process them."""
    logger.info("worker starting (mode=%s)", os.environ.get("HS_WORKER_MODE"))
    while True:
        job = fetch_pending_job()
        if job:
            logger.info("found pending job %s", job.id)
            # claim it
            job.status = "processing"
            db.session.commit()
            process_job(job)
        else:
            time.sleep(poll_interval)


if __name__ == "__main__":
    # simple entrypoint so `python -m worker.main` works
    os.environ.setdefault("FLASK_APP", "app.py")
    from app import app  # ensure Flask and DB initialised

    with app.app_context():
        worker_loop()
