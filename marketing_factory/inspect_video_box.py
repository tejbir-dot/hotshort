import urllib.request
import re

url = 'http://127.0.0.1:5000/results/99cdb3e7-169'
req = urllib.request.Request(url)
req.add_header('Cookie', 'session=eyJfZnJlc2giOnRydWUsIl91c2VyX2lkIjoiMSJ9.atyl9Q.V9Qp7lM8KUhAe5efnvHlk9U2EM0')

with urllib.request.urlopen(req) as resp:
    html = resp.read().decode('utf-8', errors='ignore')

videos = re.findall(r'(<div[^>]*class="[^"]*video[^"]*"[^>]*>[\s\S]*?</div>)', html)
with open('marketing_factory/video_box_dump.txt', 'w', encoding='utf-8') as f:
    f.write(f"Total video matches: {len(videos)}\n")
    for v in videos[:3]:
        f.write("MATCH:\n" + v + "\n\n")

print("Dumped video box markup.")
