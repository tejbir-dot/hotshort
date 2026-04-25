import os
from dotenv import load_dotenv

load_dotenv()

RUNPOD_MODE = os.getenv("RUNPOD_MODE", "serverless").strip().lower()

def _runpod_task_url(endpoint: str) -> str:
    # Always use the asynchronous /run endpoint. The app architecture polls for completion.
    # /runsync can cause 404 errors if the pod is still booting and no workers are registered.
    if RUNPOD_MODE == "pod":
        print("Using proxy url")
        return f"https://{endpoint}-8000.proxy.runpod.net/run"
    return f"https://api.runpod.ai/v2/{endpoint}/run"

endpoint = os.getenv("RUNPOD_ENDPOINT_ID")
url = _runpod_task_url(endpoint)
print("URL:", url)
