from viral_source_hunter.hunter import COOKIES_PATH
import tempfile, subprocess, os, sys

url = "https://www.youtube.com/watch?v=1F_n9c6m_B0" 
with tempfile.TemporaryDirectory() as tmpdir:
    r = subprocess.run([
        sys.executable, "-m", "yt_dlp",
        "--cookies", COOKIES_PATH,
        "--write-subs", "--write-auto-subs",
        "--sub-langs", "en", "--sub-format", "vtt",
        "--skip-download", "--no-playlist",
        "-o", os.path.join(tmpdir, "%(id)s.%(ext)s"),
        url
    ], capture_output=True, text=True)
    
    print("YT-DLP ERROR:")
    print(r.stderr)
    print("\nFILES IN TMPDIR:")
    for f in os.listdir(tmpdir):
        print(f)
        if f.endswith(".vtt"):
            with open(os.path.join(tmpdir, f), "r", encoding="utf-8") as fvtt:
                print(f"\nCONTENT OF {f} (first 200 chars):")
                print(fvtt.read()[:200])
