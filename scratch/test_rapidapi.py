import urllib.request
import json
import time

API_KEY = "4e36560b9bmshed4bd5976a911f0p11dad7jsn5b88dba81953"
API_HOST = "youtube-media-downloader.p.rapidapi.com"

# Test with a known YouTube video ID
VIDEO_ID = "dQw4w9WgXcQ"  # Rick Astley - Never Gonna Give You Up (always works as test)

headers = {
    "Content-Type": "application/json",
    "x-rapidapi-host": API_HOST,
    "x-rapidapi-key": API_KEY
}

def call_api(endpoint, params=""):
    url = f"https://{API_HOST}{endpoint}?{params}"
    print(f"\n{'='*60}")
    print(f"ENDPOINT : {endpoint}")
    print(f"URL      : {url}")
    req = urllib.request.Request(url, headers=headers)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            elapsed = time.time() - t0
            body = resp.read().decode("utf-8")
            data = json.loads(body)
            print(f"STATUS   : {resp.status} OK  ({elapsed:.2f}s)")
            return data
    except urllib.error.HTTPError as e:
        elapsed = time.time() - t0
        body = e.read().decode("utf-8")
        print(f"HTTP ERR : {e.code} ({elapsed:.2f}s)")
        print(f"BODY     : {body[:300]}")
        return None
    except Exception as e:
        print(f"ERROR    : {e}")
        return None

# ── TEST 1: Video Details ──────────────────────────────────────
print("\n🎯 TEST 1: VIDEO DETAILS")
details = call_api("/v2/video/details", f"videoId={VIDEO_ID}")
if details:
    print(f"TITLE    : {details.get('title', 'N/A')[:70]}")
    print(f"DURATION : {details.get('lengthSeconds', 'N/A')}s")
    print(f"VIEWS    : {details.get('viewCount', 'N/A')}")
    print(f"TOP KEYS : {list(details.keys())}")
    with open(r"C:\Users\n\Documents\hotshort\scratch\rapidapi_video_details.json", "w") as f:
        json.dump(details, f, indent=2)
    print("SAVED    -> scratch/rapidapi_video_details.json")

# ── TEST 2: Video Streams ──────────────────────────────────────
print("\n🎯 TEST 2: VIDEO STREAMS (download URLs)")
streams = call_api("/v2/video/streams", f"videoId={VIDEO_ID}")
if streams:
    print(f"TOP KEYS : {list(streams.keys())}")
    vids = streams.get("videos", {})
    if vids:
        print(f"\n📹 VIDEO STREAMS:")
        items = vids if isinstance(vids, list) else vids.get("items", [])
        for i, v in enumerate(items[:5]):
            print(f"  [{i}] quality={v.get('quality','?')} | ext={v.get('extension','?')} | size={v.get('size',{}).get('text','?')} | hasAudio={v.get('hasAudio','?')}")
            url = v.get("url", "")
            if url:
                print(f"       URL preview: {url[:80]}...")

    auds = streams.get("audios", {})
    if auds:
        print(f"\n🔊 AUDIO STREAMS:")
        items = auds if isinstance(auds, list) else auds.get("items", [])
        for i, a in enumerate(items[:3]):
            print(f"  [{i}] quality={a.get('quality','?')} | ext={a.get('extension','?')} | size={a.get('size',{}).get('text','?')}")
            url = a.get("url", "")
            if url:
                print(f"       URL preview: {url[:80]}...")

    with open(r"C:\Users\n\Documents\hotshort\scratch\rapidapi_video_streams.json", "w") as f:
        json.dump(streams, f, indent=2)
    print("\nSAVED    -> scratch/rapidapi_video_streams.json")

print("\n" + "="*60)
print("✅ ALL TESTS COMPLETE")
