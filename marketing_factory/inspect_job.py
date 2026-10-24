import urllib.request
import re
import json

url = 'http://127.0.0.1:5000/results/99cdb3e7-169'
req = urllib.request.Request(url)
req.add_header('Cookie', 'session=eyJfZnJlc2giOnRydWUsIl91c2VyX2lkIjoiMSJ9.atyl9Q.V9Qp7lM8KUhAe5efnvHlk9U2EM0')

with urllib.request.urlopen(req) as resp:
    html = resp.read().decode('utf-8', errors='ignore')

# Look for embedded JSON or script variables
scripts = re.findall(r'<script[\s\S]*?</script>', html)
print('Total scripts:', len(scripts))

for s in scripts:
    if 'clips' in s.lower() or 'results' in s.lower() or 'job' in s.lower():
        # find variable assignments
        vars = re.findall(r'(?:const|let|var)\s+(\w+)\s*=\s*([^;]+);', s)
        for var_name, val in vars:
            if 'clip' in var_name.lower() or 'data' in var_name.lower():
                print(f"Variable: {var_name} (length: {len(val)})")
                if len(val) < 200:
                    print("   val:", val)

# Also check carousel inner HTML or how cards are created
matches = re.findall(r'<div class="carousel[^"]*"[^>]*>([\s\S]*?)</section>', html)
if matches:
    print('Carousel container markup snippet:')
    print(matches[0][:500])
