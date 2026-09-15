import urllib.request
import json
import os

api_key = os.environ.get('GPT_API', 'xpl_adb5714d9b9cc12beb8a18b1a9858245ce90165c')

def check_endpoint(url, method='GET', data=None):
    print(f"\\n--- Checking {url} ---")
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json'
    }
    req = urllib.request.Request(url, headers=headers, method=method, data=data)
    try:
        resp = urllib.request.urlopen(req)
        print(f"Status: {resp.status}")
        print("Headers:")
        for k, v in resp.headers.items():
            if 'limit' in k.lower() or 'remain' in k.lower() or 'reset' in k.lower():
                print(f"  {k}: {v}")
        print("Body:")
        print(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        print(f"HTTP Error {e.code}")

# Check usage endpoints
check_endpoint('https://api.experientiallabs.ai/api/credits')
check_endpoint('https://api.experientiallabs.ai/api/usage')
check_endpoint('https://api.experientiallabs.ai/api/user')

# Check chat completions for headers
data = json.dumps({'model': 'gpt-5.6-luna', 'messages': [{'role': 'user', 'content': 'Hi'}]}).encode('utf-8')
check_endpoint('https://api.experientiallabs.ai/v1/chat/completions', method='POST', data=data)
