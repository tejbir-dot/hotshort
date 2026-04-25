import os
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ.get("RUNPOD_API_KEY")
ENDPOINT_ID = os.environ.get("RUNPOD_ENDPOINT_ID")

print(f"Testing Endpoint: {ENDPOINT_ID}")

url = f"https://api.runpod.ai/v2/{ENDPOINT_ID}/run"
headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

payload = {
    "input": {
        "task": "ping"
    }
}

print(f"Requesting {url} ...")
try:
    resp = requests.post(url, json=payload, headers=headers)
    print("Status:", resp.status_code)
    print("Response:", resp.text)
except Exception as e:
    print("Error:", e)
