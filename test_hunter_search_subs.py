from viral_source_hunter.hunter import _yt_search, _get_video_subtitles
import tempfile
import json

results = _yt_search("Luke Belmar trading loss $47000", 3)
print(f"Found {len(results)} search results")
for c in results:
    print(f"\nCandidate: {c['title']} ({c['url']})")
    with tempfile.TemporaryDirectory() as tmpdir:
        subs = _get_video_subtitles(c['url'], tmpdir)
        print(f"Subtitle segments fetched: {len(subs)}")
