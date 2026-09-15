"""
process_video.py — HotShort Standalone Processor
==================================================
Railway, server, kuch nahi chahiye.
Sirf YouTube URL do → clips scratch/hotshort_out/ mein save honge.

Usage:
    python process_video.py "https://youtu.be/..."
    python process_video.py "https://youtu.be/..." --clips 5
    python process_video.py --file path/to/video.mp4
"""

import os
import sys
import time
import shutil
import argparse
import subprocess
import tempfile

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
OUT_DIR  = os.path.join(BASE_DIR, "scratch", "hotshort_out")

# ── inject local bin/ ─────────────────────────────────────────────────────────
_local_bin = os.path.join(BASE_DIR, "bin")
if os.path.isdir(_local_bin):
    os.environ["PATH"] = _local_bin + os.pathsep + os.environ.get("PATH", "")

# ── load env ──────────────────────────────────────────────────────────────────
from dotenv import load_dotenv
for _env in [".env", ".env.local", ".env.worker"]:
    _p = os.path.join(BASE_DIR, _env)
    if os.path.exists(_p):
        load_dotenv(_p, override=True)

sys.path.insert(0, BASE_DIR)


def download_video(url: str, dest: str):
    print(f"\n[STEP 1] Downloading video...", flush=True)
    t0 = time.perf_counter()
    subprocess.run([
        sys.executable, "-m", "yt_dlp",
        "--format", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "--merge-output-format", "mp4",
        "--no-playlist",
        "-o", dest,
        url,
    ], check=True)
    sz = os.path.getsize(dest) / 1e6
    print(f"[STEP 1] Done in {time.perf_counter()-t0:.0f}s — {sz:.0f} MB", flush=True)


def process(video_path: str, top_k: int = 5):
    from viral_finder.orchestrator import orchestrate
    from local_worker import FaceCache

    print(f"\n[STEP 2] Orchestrating (selecting best {top_k} clips)...", flush=True)
    t0 = time.perf_counter()
    clips = orchestrate(
        video_path,
        top_k=top_k,
        prefer_gpu=True,
        use_cache=True,
        allow_fallback=False,
        pipeline_mode=os.getenv("HS_ORCH_PIPELINE_MODE", "staged"),
    )
    print(f"[STEP 2] Done in {time.perf_counter()-t0:.0f}s — {len(clips)} clips selected", flush=True)

    print(f"\n[STEP 3] Face scan (Haar)...", flush=True)
    t0 = time.perf_counter()
    face_cache = FaceCache(video_path, clips)
    print(f"[STEP 3] Done in {time.perf_counter()-t0:.0f}s", flush=True)

    os.makedirs(OUT_DIR, exist_ok=True)

    try:
        from effects.world_class_editor import ClipEditor, ClipEditConfig
        _wce_ok = True
    except Exception as e:
        print(f"[WCE] Not available ({e}) — saving raw cuts", flush=True)
        _wce_ok = False

    results = []
    for i, clip in enumerate(clips):
        start = float(clip.get("start", 0))
        end   = float(clip.get("end",   start + 30))
        label = clip.get("opening_caption") or clip.get("title") or f"clip_{i}"
        out_name = f"clip_{i}_{int(start)}_{int(end)}.mp4"
        out_path = os.path.join(OUT_DIR, out_name)

        print(f"\n[CLIP {i+1}/{len(clips)}] {start:.0f}s-{end:.0f}s  \"{label[:60]}\"", flush=True)

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tf:
            raw_path = tf.name

        # Extract subclip
        print(f"  Extracting...", flush=True)
        t0 = time.perf_counter()
        subprocess.run([
            "ffmpeg", "-y", "-nostdin",
            "-ss", str(start), "-to", str(end),
            "-i", video_path,
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
            "-c:a", "aac", raw_path,
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=300)
        print(f"  Extracted in {time.perf_counter()-t0:.0f}s", flush=True)

        final_path = raw_path

        if _wce_ok:
            print(f"  Editing (Director + crop + captions)...", flush=True)
            t0 = time.perf_counter()
            try:
                _wd = os.path.join(tempfile.gettempdir(), f"hs_wce_{i}")
                os.makedirs(_wd, exist_ok=True)
                editor = ClipEditor(_wd)
                cfg    = ClipEditConfig()
                edited = raw_path.replace(".mp4", "_edited.mp4")
                res = editor.process(
                    raw_path,
                    output_path=edited,
                    source_start=start,
                    source_end=end,
                    transcript=clip.get("transcript") or [],
                    config=cfg,
                    precomputed_face_cache=face_cache.get_clip_cache(clip),
                )
                if res:
                    final_path = edited
                    print(f"  Edited in {time.perf_counter()-t0:.0f}s", flush=True)
                else:
                    print(f"  Editor returned nothing — using raw cut", flush=True)
            except Exception as e:
                print(f"  Editor failed: {e} — using raw cut", flush=True)

        shutil.copy2(final_path, out_path)
        sz = os.path.getsize(out_path) / 1e6
        print(f"  Saved → {out_path}  ({sz:.1f} MB)", flush=True)
        results.append({"path": out_path, "start": start, "end": end, "label": label})

        # cleanup
        for p in [raw_path, raw_path.replace(".mp4", "_edited.mp4")]:
            try: os.unlink(p)
            except: pass

    return results


def main():
    parser = argparse.ArgumentParser(description="HotShort Standalone Processor")
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("url",   nargs="?", default=None, help="YouTube URL")
    grp.add_argument("--file", help="Local video file")
    parser.add_argument("--clips", type=int, default=5, help="Number of clips (default: 5)")
    args = parser.parse_args()

    t_total = time.perf_counter()
    print("\n" + "="*60)
    print("  HOTSHORT STANDALONE PROCESSOR")
    print("="*60)

    video_path = args.file

    if args.url and not args.file:
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tf:
            video_path = tf.name
        try:
            download_video(args.url, video_path)
        except Exception as e:
            print(f"\n[ERROR] Download failed: {e}")
            sys.exit(1)

    if not os.path.exists(video_path):
        print(f"\n[ERROR] File not found: {video_path}")
        sys.exit(1)

    results = process(video_path, top_k=args.clips)

    total = time.perf_counter() - t_total
    print("\n" + "="*60)
    print(f"  DONE — {len(results)} clips in {total:.0f}s ({total/60:.1f} min)")
    print(f"  Output: {OUT_DIR}")
    print("="*60)
    for r in results:
        print(f"  [{r['start']:.0f}s-{r['end']:.0f}s] {r['label'][:55]}")
        print(f"           → {os.path.basename(r['path'])}")
    print()

    # Open output folder
    if sys.platform == "win32":
        subprocess.run(["explorer", OUT_DIR], check=False)


if __name__ == "__main__":
    main()
