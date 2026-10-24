from viral_source_hunter.hunter import _get_video_subtitles, _compute_overlap
import tempfile
import sys

url = "https://www.youtube.com/watch?v=M947j6x8mBc" # Sample Luke Belmar video
viral_text = "I'm gonna give this shit some room to work though. Bro. 87,000 dollars. Lost a bro. The The The The The The"

print(f"Testing URL: {url}")
with tempfile.TemporaryDirectory() as tmpdir:
    subs = _get_video_subtitles(url, tmpdir)
    print(f"Fetched {len(subs)} subtitle segments")
    if subs:
        print(f"Sample sub: {subs[0]}")
    overlap = _compute_overlap(viral_text, subs)
    print(f"Overlap: {overlap}")
