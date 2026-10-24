from viral_source_hunter.hunter import _get_video_subtitles
import tempfile

url = "https://www.youtube.com/watch?v=0e3GPea1Tyg"  # MrBeast
print("Testing MrBeast:")
with tempfile.TemporaryDirectory() as tmpdir:
    subs = _get_video_subtitles(url, tmpdir)
    print(f"Fetched {len(subs)} subtitle segments")
