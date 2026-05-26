import os
import requests
import json
import time
from dotenv import load_dotenv

load_dotenv()

youtube_url = "https://www.youtube.com/watch?v=jNQXAC9IVRw"

api_url = "https://youtube-info-download-api.p.rapidapi.com/ajax/download.php"
querystring = {
    "format": "720", 
    "add_info": "0",
    "url": youtube_url,
    "audio_quality": "128",
    "allow_extended_duration": "false",
    "no_merge": "false",
    "audio_language": "en"
}

headers = {
    "x-rapidapi-host": "youtube-info-download-api.p.rapidapi.com",
    "x-rapidapi-key": os.environ.get("RAPIDAPI_KEY")
}

try:
    print("Testing youtube-info-download-api...")
    response = requests.get(api_url, headers=headers, params=querystring, timeout=30)
    response.raise_for_status()
    data = response.json()
    
    progress_url = data.get("progress_url")
    if not progress_url:
        print("Failed to get progress_url")
        exit(1)
        
    print("Polling progress_url:", progress_url)
    
    for i in range(20):
        time.sleep(2)
        prog_resp = requests.get(progress_url, timeout=30)
        prog_data = prog_resp.json()
        print(f"Poll {i+1} Response:", json.dumps(prog_data, indent=2))
        
        final_link = prog_data.get("download_url") or prog_data.get("url") or prog_data.get("file")
        if prog_data.get("success") and final_link:
            print("Successfully got final link:", final_link)
            break
except Exception as e:
    print("Error:", e)
