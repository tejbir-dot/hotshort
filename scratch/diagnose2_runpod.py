"""
Diagnostic v2: cancel stuck jobs and test with a minimal payload
that the worker SHOULD handle even if Whisper/yt-dlp fail.
"""
import os
import time
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ.get("RUNPOD_API_KEY", "")
ENDPOINT_ID = os.environ.get("RUNPOD_ENDPOINT_ID", "")

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}
base = f"https://api.runpod.ai/v2/{ENDPOINT_ID}"

# ── 1. Cancel all stuck IN_QUEUE jobs ─────────────────────────────────────────
print("[1] Purging stuck jobs via /cancel/all ...")
try:
    r = requests.post(f"{base}/cancel/all", headers=headers, timeout=10)
    print(f"    Status: {r.status_code}  Body: {r.text[:200]}")
except Exception as e:
    print(f"    ERROR: {e}")

time.sleep(2)

# ── 2. Re-check health ─────────────────────────────────────────────────────────
print("\n[2] Health after purge...")
r = requests.get(f"{base}/health", headers=headers, timeout=10)
print(f"    {r.text[:300]}")

# ── 3. Submit a VERY minimal job (no Whisper, no yt-dlp) ─────────────────────
print("\n[3] Submitting minimal healthcheck task...")
payload = {"input": {"task": "healthcheck"}}
r = requests.post(f"{base}/run", json=payload, headers=headers, timeout=30)
print(f"    Submit: {r.status_code} - {r.text[:200]}")
if r.status_code != 200:
    print("    FAILED to submit")
    raise SystemExit(1)

data = r.json()
run_id = data.get("id")
print(f"    run_id: {run_id}")

# ── 4. Poll for 90s ───────────────────────────────────────────────────────────
print(f"\n[4] Polling for 90s...")
terminal = ("COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT")
for i in range(45):
    time.sleep(2)
    r = requests.get(f"{base}/status/{run_id}", headers=headers, timeout=15)
    data = r.json()
    status = data.get("status")
    print(f"    [{i*2:3d}s] status={status!r}")
    if status in terminal:
        print(f"\n    FINAL: {data}")
        break
else:
    print("\n    >>> STUCK IN_QUEUE after 90s = WORKERS ARE BROKEN/FROZEN")
    print("    >>> Workers show 'ready' but cannot execute tasks")
    print("    >>> FIX: Redeploy the Docker image to the RunPod endpoint")
    print("    >>> OR:  Check RunPod dashboard logs per-worker for crash errors")
