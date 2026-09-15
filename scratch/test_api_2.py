import urllib.request, urllib.error, json, os

api_key = os.environ.get('GPT_API', 'xpl_adb5714d9b9cc12beb8a18b1a9858245ce90165c')
req = urllib.request.Request(
    'https://api.experientiallabs.ai/v1/chat/completions',
    headers={
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json'
    },
    data=json.dumps({
        'model': 'llama-3.1-8b-instant',
        'messages': [{'role': 'user', 'content': 'Hello'}]
    }).encode('utf-8')
)
try:
    urllib.request.urlopen(req)
    print("Success")
except urllib.error.HTTPError as e:
    print(f"HTTP Error {e.code}: {e.reason}")
    print(e.read().decode('utf-8'))
