import os
import requests
from dotenv import load_dotenv

load_dotenv()

endpoint = os.getenv("RUNPOD_ENDPOINT_ID")
api_key = os.getenv("RUNPOD_API_KEY")

if not endpoint or not api_key:
    print("Missing env vars")
    exit(1)

url = f"https://api.runpod.ai/v2/{endpoint}/health"
headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json",
}

print("Checking RunPod Endpoint Health...")
resp = requests.get(url, headers=headers)
print("Status:", resp.status_code)
try:
    print(resp.json())
except Exception as e:
    print(resp.text)

