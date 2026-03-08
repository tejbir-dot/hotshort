from typing import Literal, Optional
import uuid

# simple dataclasses / pydantic-like validation without external deps

def validate_worker_request(data: dict) -> dict:
    """Ensure request includes required fields and types.

    Returns normalized dict with defaults applied. Raises ValueError on failure.
    """
    if not isinstance(data, dict):
        raise ValueError("request must be a JSON object")

    job_id = data.get("job_id")
    if job_id is None or not isinstance(job_id, str) or not job_id.strip():
        # generate new uuid if not provided
        job_id = str(uuid.uuid4())
    profile = data.get("profile", "balanced")
    if profile not in ("god_mode", "balanced", "speed"):
        raise ValueError("invalid profile")
    min_clips = data.get("min_clips", 3)
    try:
        min_clips = int(min_clips)
    except Exception:
        raise ValueError("min_clips must be integer")
    max_duration_sec = data.get("max_duration_sec", None)
    if max_duration_sec is not None:
        try:
            max_duration_sec = float(max_duration_sec)
        except Exception:
            raise ValueError("max_duration_sec must be numeric")
    debug = bool(data.get("debug", False))
    source_url = data.get("source_url")
    if not source_url or not isinstance(source_url, str):
        raise ValueError("source_url is required")

    return {
        "job_id": job_id,
        "source_url": source_url,
        "profile": profile,
        "min_clips": min_clips,
        "max_duration_sec": max_duration_sec,
        "debug": debug,
    }


def validate_worker_result(data: dict) -> dict:
    """Basic sanity check for worker result envelope.

    This function will be used by the worker to ensure it constructs a valid
    response before committing to the job record.
    """
    # Minimal checks for required keys
    required = [
        "job_id",
        "status",
        "clips",
        "confidence_score",
        "signal_quality",
        "diagnostics",
    ]
    for key in required:
        if key not in data:
            raise ValueError(f"missing key in worker result: {key}")
    # status must be one of ok|degraded|failed_internal
    if data.get("status") not in ("ok", "degraded", "failed_internal"):
        raise ValueError("invalid status value")
    return data
