import os
import time
import requests
from dotenv import load_dotenv

load_dotenv()

endpoint = os.getenv("RUNPOD_ENDPOINT_ID")
api_key = os.getenv("RUNPOD_API_KEY")
youtube_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"  # Rickroll, short video

if not endpoint or not api_key:
    print("Error: RUNPOD_ENDPOINT_ID or RUNPOD_API_KEY not found in .env")
    exit(1)

url = f"https://api.runpod.ai/v2/{endpoint}/run"
headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json"
}

# 1. Preflight Health Check
health_url = f"https://api.runpod.ai/v2/{endpoint}/health"
print("1. Checking Endpoint Health...")
health_resp = requests.get(health_url, headers=headers)
print("Health status:", health_resp.status_code)
print("Health data:", health_resp.json())

# 2. Submit 'download' task
print("\n2. Submitting 'download' task to RunPod...")
payload = {
    "input": {
        "task": "download",
        "youtube_url": youtube_url
    }
}

submit_resp = requests.post(url, json=payload, headers=headers)
print("Submit status:", submit_resp.status_code)
try:
    data = submit_resp.json()
    print("Submit response:", data)
except Exception:
    print("Submit response text:", submit_resp.text)
    exit(1)

run_id = data.get("id") or data.get("run_id")
if not run_id:
    print("Failed to get run_id")
    exit(1)

status_url = f"https://api.runpod.ai/v2/{endpoint}/status/{run_id}"

# 3. Poll for status
print(f"\n3. Polling status for run_id: {run_id}")
for _ in range(30): # Poll for up to ~150 seconds
    status_resp = requests.get(status_url, headers=headers)
    if status_resp.status_code != 200:
        print("Error fetching status:", status_resp.status_code, status_resp.text)
        break
        
    status_data = status_resp.json()
    status = status_data.get("status")
    print(f"[{time.strftime('%X')}] Status: {status}")
    
    if status == "COMPLETED":
        print("\nSuccess! Output:", status_data.get("output"))
        break
    elif status == "FAILED":
        print("\nFailed! Error:", status_data.get("error"))
        break
        
    time.sleep(5)
else:
    print("\nTimeout waiting for task to complete.")
