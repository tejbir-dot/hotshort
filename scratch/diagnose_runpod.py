"""Full diagnostic: check URL building, endpoint health, job submission, and polling."""
import os
import time
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ.get("RUNPOD_API_KEY", "")
ENDPOINT_ID = os.environ.get("RUNPOD_ENDPOINT_ID", "")
RUNPOD_MODE = os.environ.get("RUNPOD_MODE", "serverless").strip().lower()

print("=" * 60)
print("DIAGNOSTIC REPORT")
print("=" * 60)
print(f"RUNPOD_MODE       : {RUNPOD_MODE!r}")
print(f"RUNPOD_ENDPOINT_ID: {ENDPOINT_ID!r}")
print(f"RUNPOD_API_KEY    : {'SET (' + API_KEY[:12] + '...)' if API_KEY else 'MISSING'}")

if RUNPOD_MODE == "pod":
    task_url = f"https://{ENDPOINT_ID}-8000.proxy.runpod.net/run"
    status_prefix = f"https://{ENDPOINT_ID}-8000.proxy.runpod.net/status"
else:
    task_url = f"https://api.runpod.ai/v2/{ENDPOINT_ID}/run"
    status_prefix = f"https://api.runpod.ai/v2/{ENDPOINT_ID}/status"

print(f"\nTask URL   : {task_url}")
print(f"Status URL : {status_prefix}/<run_id>")

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

# ── 1. Health check (if serverless: check endpoint info via /health) ──────────
print("\n[1] Checking endpoint health...")
if RUNPOD_MODE == "serverless":
    health_url = f"https://api.runpod.ai/v2/{ENDPOINT_ID}/health"
    try:
        r = requests.get(health_url, headers=headers, timeout=10)
        print(f"    Status : {r.status_code}")
        print(f"    Body   : {r.text[:300]}")
    except Exception as e:
        print(f"    ERROR  : {e}")
else:
    print(f"    (pod mode - skipping serverless health check)")

# ── 2. Submit a ping job ──────────────────────────────────────────────────────
print("\n[2] Submitting ping job to RunPod...")
payload = {"input": {"task": "healthcheck"}}
try:
    r = requests.post(task_url, json=payload, headers=headers, timeout=30)
    print(f"    Submit status : {r.status_code}")
    print(f"    Submit body   : {r.text[:300]}")
    if r.status_code != 200:
        print("\n    ❌ FAILED TO SUBMIT - this is the 404 bug!")
        raise SystemExit(1)
    data = r.json()
    run_id = data.get("id") or data.get("run_id")
    status = data.get("status")
    print(f"    run_id : {run_id}")
    print(f"    status : {status}")
except SystemExit:
    raise
except Exception as e:
    print(f"    ERROR  : {e}")
    raise SystemExit(1)

# ── 3. Poll for up to 60s ────────────────────────────────────────────────────
if run_id:
    print(f"\n[3] Polling status for run_id={run_id} (max 60s)...")
    for i in range(30):
        time.sleep(2)
        poll_url = f"{status_prefix}/{run_id}"
        try:
            r = requests.get(poll_url, headers=headers, timeout=15)
            data = r.json()
            status = data.get("status")
            print(f"    [{i*2:3d}s] HTTP={r.status_code} status={status!r}")
            if status in ("COMPLETED", "FAILED"):
                print(f"\n    Final output: {data.get('output')}")
                break
        except Exception as e:
            print(f"    [{i*2:3d}s] ERROR: {e}")
    else:
        print(f"\n    ⚠️  Job never completed after 60s (no workers?)")
        print(f"    CONCLUSION: Endpoint exists but NO ACTIVE WORKERS are running!")
else:
    print("\n[3] No run_id returned - skipping poll")

print("\n" + "=" * 60)
print("CONCLUSION SUMMARY")
print("=" * 60)
print(f"  Mode      : {RUNPOD_MODE}")
print(f"  Endpoint  : {ENDPOINT_ID}")
print(f"  Task URL  : {task_url}")
print("  Check the poll section above to determine root cause.")
