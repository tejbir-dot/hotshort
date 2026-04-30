from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger("runpod_transcription")


def _runpod_task_url(endpoint: str) -> str:
    mode = os.getenv("RUNPOD_MODE", "serverless").strip().lower()
    if mode == "pod":
        return f"https://{endpoint}-8000.proxy.runpod.net/run"
    return f"https://api.runpod.ai/v2/{endpoint}/run"


def _runpod_status_url(endpoint: str, run_id: str) -> str:
    mode = os.getenv("RUNPOD_MODE", "serverless").strip().lower()
    if mode == "pod":
        return f"https://{endpoint}-8000.proxy.runpod.net/status/{run_id}"
    return f"https://api.runpod.ai/v2/{endpoint}/status/{run_id}"


def _wait_for_runpod_completion(
    *,
    endpoint: str,
    headers: dict,
    initial_data: dict,
    request_url: str,
    request_payload: dict,
    timeout: int,
    task_label: str,
    poll_timeout_s: int,
    poll_interval_s: int,
) -> dict:
    """Poll RunPod until the async job reaches a terminal state."""
    import requests

    data = initial_data or {}
    status = data.get("status")
    run_id = data.get("id") or data.get("run_id")
    log.info("[RUNPOD] %s STATUS: %s (run_id=%s)", task_label, status, run_id)

    # Local workers (or custom gateways) may return the final payload immediately.
    if status in ("ok", "OK") and ("output" in data or "segments" in data):
        return data

    start_polling_time = time.time()
    while time.time() - start_polling_time < poll_timeout_s:
        if status == "COMPLETED":
            return data
        if status == "FAILED":
            raise RuntimeError(f"RunPod {task_label} failed: FAILED")

        time.sleep(poll_interval_s)

        if run_id:
            status_url = _runpod_status_url(endpoint, run_id)
            resp = requests.get(status_url, headers=headers, timeout=60)
        else:
            resp = requests.post(request_url, json=request_payload, headers=headers, timeout=timeout)

        if resp.status_code != 200:
            raise RuntimeError(f"RunPod {task_label} failed: {resp.status_code} - {resp.text}")

        data = resp.json()
        status = data.get("status")
        run_id = run_id or data.get("id") or data.get("run_id")
        log.info("[RUNPOD] %s STATUS: %s (run_id=%s)", task_label, status, run_id)

    raise RuntimeError(f"RunPod {task_label} timed out (status={status})")


def _upload_to_cloudinary(local_path: str) -> Optional[str]:
    try:
        import cloudinary
        import cloudinary.uploader
    except Exception:
        return None

    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME")
    api_key = os.getenv("CLOUDINARY_API_KEY")
    api_secret = os.getenv("CLOUDINARY_API_SECRET")
    if not (cloud_name and api_key and api_secret):
        return None

    cloudinary.config(
        cloud_name=cloud_name,
        api_key=api_key,
        api_secret=api_secret,
    )

    try:
        result = cloudinary.uploader.upload(local_path, resource_type="video")
        return result.get("secure_url")
    except Exception as exc:
        log.warning("[RUNPOD] Cloudinary upload failed: %s", exc)
        return None


def _upload_to_s3(local_path: str) -> Optional[str]:
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError
    except Exception:
        return None

    bucket = os.environ.get("AWS_S3_BUCKET") or os.environ.get("S3_BUCKET")
    if not bucket:
        return None

    region = os.environ.get("AWS_REGION", "us-east-1")
    key = os.path.basename(local_path)

    try:
        s3 = boto3.client(
            "s3",
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
            region_name=region,
        )
        s3.upload_file(local_path, bucket, key, ExtraArgs={"ACL": "public-read"})
        return f"https://{bucket}.s3.{region}.amazonaws.com/{key}"
    except (BotoCoreError, ClientError, Exception) as exc:
        log.warning("[RUNPOD] S3 upload failed: %s", exc)
        return None


def transcribe_media_url(
    media_url: str,
    *,
    poll_timeout_s: Optional[int] = None,
    poll_interval_s: Optional[int] = None,
    timeout: int = 600,
) -> List[Dict[str, Any]]:
    """Transcribe a public media URL using a RunPod worker."""
    import requests

    endpoint = (os.getenv("RUNPOD_ENDPOINT_ID") or "").strip()
    api_key = (os.getenv("RUNPOD_API_KEY") or "").strip()
    if not endpoint or not api_key:
        raise RuntimeError("RunPod not configured (missing RUNPOD_ENDPOINT_ID and/or RUNPOD_API_KEY)")

    request_url = _runpod_task_url(endpoint)
    request_payload = {"input": {"task": "transcribe_url", "media_url": media_url}}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    poll_timeout_s = int(
        poll_timeout_s
        if poll_timeout_s is not None
        else float(os.getenv("HS_RUNPOD_TRANSCRIPTION_POLL_TIMEOUT_SECONDS", "900") or 900.0)
    )
    poll_interval_s = int(
        poll_interval_s
        if poll_interval_s is not None
        else float(os.getenv("HS_RUNPOD_POLL_INTERVAL_SECONDS", "3") or 3.0)
    )

    resp = requests.post(request_url, json=request_payload, headers=headers, timeout=timeout)
    if resp.status_code != 200:
        raise RuntimeError(f"RunPod transcription request failed: {resp.status_code} - {resp.text}")

    result = _wait_for_runpod_completion(
        endpoint=endpoint,
        headers=headers,
        initial_data=resp.json(),
        request_url=request_url,
        request_payload=request_payload,
        timeout=timeout,
        task_label="transcription",
        poll_timeout_s=poll_timeout_s,
        poll_interval_s=poll_interval_s,
    )

    output = result.get("output") if isinstance(result, dict) else None
    if isinstance(output, dict):
        return list(output.get("segments") or [])
    if isinstance(result, dict) and "segments" in result:
        return list(result.get("segments") or [])
    return []


def transcribe_local_media_path(local_path: str) -> List[Dict[str, Any]]:
    """Upload a local file to a public URL and transcribe it using a RunPod worker."""
    if str(local_path or "").startswith(("http://", "https://")):
        return transcribe_media_url(str(local_path))

    if not os.path.exists(local_path):
        raise FileNotFoundError(local_path)

    media_url = _upload_to_cloudinary(local_path) or _upload_to_s3(local_path)
    if not media_url:
        raise RuntimeError(
            "No upload provider configured for RunPod transcription. "
            "Set Cloudinary (CLOUDINARY_CLOUD_NAME/CLOUDINARY_API_KEY/CLOUDINARY_API_SECRET) "
            "or S3 (AWS_S3_BUCKET/AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY)."
        )
    return transcribe_media_url(media_url)
