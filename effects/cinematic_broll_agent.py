"""
Cinematic B-Roll Agent v1.0
============================
The first HotShort agent that UNDERSTANDS what the speaker is saying
and finds the EXACT visual scene on the internet to prove it.

Pipeline:
  1. Transcribe the clip (faster-whisper or openai-whisper)
  2. Ask Gemini: "speaker bolda X, EXACT scene ki honi chahidi?" -> YouTube search query
  3. Download top YouTube result (yt-dlp, silent, trimmed to cut_duration)
  4. Overlay real-world footage on the clip at the right timestamp
  5. Re-encode final clip with B-Roll burned in

Usage (manual test):
  python effects/cinematic_broll_agent.py "path/to/clip.mp4" --out "path/to/out.mp4"
"""

from __future__ import annotations

import os, re, sys, json, time, shutil, random, logging, tempfile, argparse, subprocess
from typing import List, Tuple, Optional

# Load .env and .env.worker from repo root (same as local_worker.py does)
for _env_file in [".env", ".env.local", ".env.worker"]:
    _env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), _env_file)
    if os.path.exists(_env_path):
        with open(_env_path, encoding="utf-8", errors="ignore") as _ef:
            for _line in _ef:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _, _v = _line.partition("=")
                    os.environ[_k.strip()] = _v.strip()   # override=True like load_dotenv does

log = logging.getLogger("cinematic_broll_agent")

_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "broll_agent_cache")
os.makedirs(_CACHE_DIR, exist_ok=True)

_MAX_BROLL       = 3
_CUT_DURATION    = 2.5
_DL_TIMEOUT      = 45
_YT_SEARCH_PREFIX = "ytsearch2:"


# -- Gemini --------------------------------------------------------------------

def _ask_llm(prompt: str) -> Optional[str]:
    """
    OpenRouter is PRIMARY (unlimited free, already working for captioner).
    Gemini SDK is SECONDARY fallback only.
    """
    import requests as _req

    # --- OpenRouter FIRST (same API as captioner — always works) ---
    or_key  = os.getenv("OPENROUTER_API_KEY") or os.getenv("GPT_API", "")
    or_base = os.getenv("HS_GROQ_API_BASE", "https://openrouter.ai/api/v1").rstrip("/")
    if or_key and "openrouter" in or_base:
        for model in ["qwen/qwen3.8-27b:free", "liquid/lfm-2.5-2.6b:free", "inclusionai/ling-3.0-flash-sante:free"]:
            try:
                r = _req.post(
                    f"{or_base}/chat/completions",
                    headers={"Authorization": f"Bearer {or_key}", "Content-Type": "application/json",
                             "HTTP-Referer": "https://hotshort.app", "X-Title": "HotShort BRoll Agent"},
                    json={"model": model, "max_tokens": 256, "temperature": 0.7,
                          "messages": [{"role": "user", "content": prompt}]},
                    timeout=25,
                )
                if r.status_code == 200:
                    text = (r.json()["choices"][0]["message"].get("content") or "").strip()
                    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
                    if text and len(text) > 5:
                        log.info("[BROLL_AGENT] LLM success via OpenRouter %s", model)
                        return text
                else:
                    log.warning("[BROLL_AGENT] OpenRouter %s -> %s", model, r.status_code)
            except Exception as e:
                log.warning("[BROLL_AGENT] OpenRouter %s error: %s", model, e)

    # --- Gemini SDK FALLBACK ---
    try:
        from google import genai as _genai
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if api_key:
            _client = _genai.Client(api_key=api_key)
            for model_name in ["gemini-3.8-flash", "gemini-3.5-flash-lite"]:
                try:
                    resp = _client.models.generate_content(
                        model=model_name, contents=prompt,
                        config={"temperature": 0.7, "max_output_tokens": 256},
                    )
                    text = (resp.text or "").strip()
                    if text:
                        log.info("[BROLL_AGENT] LLM success via Gemini %s", model_name)
                        return text
                except Exception as e:
                    log.warning("[BROLL_AGENT] Gemini %s: %s", model_name, str(e)[:120])
    except Exception as e:
        log.warning("[BROLL_AGENT] Gemini SDK unavailable: %s", e)

    return None


# Keep old name as alias
_ask_gemini = _ask_llm


# -- Scene Intelligence --------------------------------------------------------

_DIRECTOR_PROMPT = '''You are the world's greatest B-Roll director for viral short-form videos.
You understand that B-Roll must be the EXACT visual proof of what the speaker is saying.

SPEAKER IS SAYING (exact transcript):
"""{segment_text}"""

FULL CLIP CONTEXT:
"""{clip_context}"""

YOUR TASK:
Generate 2 YouTube search queries for the most visually PRECISE footage.

Rules:
- Think like a Netflix documentary director. What real footage would you CUT TO?
- BE SPECIFIC: Not "car driving" but "Lamborghini Urus acceleration slow motion 4K"
- Not "money" but "Federal Reserve money printing machine close up"
- Not "people talking" but "NBA locker room heated argument postgame"
- Prefer: news clips, documentaries, sports highlights, product reveals, nature footage
- NEVER suggest animations, text overlays, or generic stock footage
- The footage must make the viewer FEEL what the speaker is describing

RESPOND with ONLY a JSON array of exactly 2 search queries:
["search query 1 here", "search query 2 here"]'''


def _get_broll_queries(segment_text: str, clip_context: str) -> List[str]:
    prompt = _DIRECTOR_PROMPT.format(
        segment_text=segment_text[:600],
        clip_context=clip_context[:800],
    )
    raw = _ask_gemini(prompt)
    if not raw:
        return []
    try:
        match = re.search(r'\[.*?\]', raw, re.DOTALL)
        if match:
            queries = json.loads(match.group())
            return [q.strip() for q in queries if isinstance(q, str) and q.strip()]
    except Exception:
        pass
    lines = [l.strip().strip('"').strip("'") for l in raw.splitlines() if l.strip() and not l.strip().startswith("[")]
    return lines[:2]


# -- Downloader ----------------------------------------------------------------

def _safe_filename(q: str) -> str:
    return re.sub(r'[^\w\-_]', '_', q)[:80]


def _download_youtube_clip(query: str, duration: float = 10.0, start_offset: float = 5.0, width: int = 1080, height: int = 1920) -> Optional[str]:
    cache_key = f"{_safe_filename(query)}_{int(start_offset)}_{int(duration)}_{width}x{height}.mp4"
    cache_path = os.path.join(_CACHE_DIR, cache_key)
    if os.path.exists(cache_path) and os.path.getsize(cache_path) > 50_000:
        log.info("[BROLL_AGENT] Cache hit: %s", cache_key)
        return cache_path

    tmpdir = tempfile.mkdtemp()
    try:
        dl_template = os.path.join(tmpdir, "raw.%(ext)s")
        yt_cmd = [
            sys.executable, "-m", "yt_dlp", "--no-playlist", "--max-downloads", "1",
            "--js-runtimes", "node",
            "-f", "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]",
            "--merge-output-format", "mp4",
            "--no-warnings",
            "-o", dl_template,
            f"{_YT_SEARCH_PREFIX}{query}",
        ]
        log.info("[BROLL_AGENT] Downloading: %s", query)
        yt_run = subprocess.run(yt_cmd, capture_output=True, timeout=_DL_TIMEOUT)
        if yt_run.returncode != 0:
            log.warning("[BROLL_AGENT] yt-dlp failed: %s", yt_run.stderr.decode("utf-8", errors="ignore"))

        raw_path = None
        for f in os.listdir(tmpdir):
            if f.startswith("raw") and (f.endswith(".mp4") or f.endswith(".mkv") or f.endswith(".webm")):
                raw_path = os.path.join(tmpdir, f)
                break

        if not raw_path or not os.path.exists(raw_path):
            log.warning("[BROLL_AGENT] Download failed: %s", query)
            return None

        trim_cmd = [
            "ffmpeg", "-y", "-nostdin",
            "-ss", str(start_offset),
            "-i", raw_path,
            "-t", str(duration + 1.0),
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-an",
            "-vf", f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1,fps=30",
            cache_path
        ]
        r = subprocess.run(trim_cmd, capture_output=True, timeout=60)
        if r.returncode == 0 and os.path.exists(cache_path) and os.path.getsize(cache_path) > 10_000:
            log.info("[BROLL_AGENT] Saved: %s", cache_key)
            return cache_path
        else:
            log.warning("[BROLL_AGENT] ffmpeg trim failed: %s", r.stderr[-300:].decode("utf-8", errors="ignore"))
            return None
    except subprocess.TimeoutExpired:
        log.warning("[BROLL_AGENT] Timeout: %s", query)
        return None
    except Exception as e:
        log.error("[BROLL_AGENT] Error: %s", e)
        return None
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# -- Public API ----------------------------------------------------------------

def find_cinematic_broll_cuts(
    transcript_window: list,
    clip_path: str,
    clip_duration: float,
    clip_context: str = "",
    max_cuts: int = _MAX_BROLL,
    cut_duration_s: float = _CUT_DURATION,
    min_cut_gap_s: float = 5.0,
    output_width: int = 1080,
    output_height: int = 1920,
) -> List[Tuple[float, str, float]]:
    """
    Analyse transcript, ask Gemini what footage fits, download it from YouTube.
    Returns: List of (clip_relative_start_sec, asset_path, cut_duration_sec)
    Drop-in compatible with smart_broll_matcher.find_broll_cuts().
    """
    if not transcript_window:
        return []

    full_text = " ".join(seg.get("text", "") for seg in transcript_window if seg.get("text")).strip()
    context   = clip_context or full_text[:800]

    hook_end  = clip_duration * 0.10
    cta_start = clip_duration * 0.85
    sample_starts = [float(s.get("start", 0)) for s in transcript_window if s.get("text")]
    _is_relative  = bool(sample_starts) and (max(sample_starts) < clip_duration * 2)

    candidates = []
    for i, seg in enumerate(transcript_window):
        t_rel = float(seg.get("start", 0)) if _is_relative else (float(seg.get("start", 0)))
        text  = seg.get("text", "").strip()
        if not text or t_rel < hook_end or t_rel + cut_duration_s > cta_start:
            continue

        ctx_parts = []
        if i > 0:
            ctx_parts.append(transcript_window[i-1].get("text", ""))
        ctx_parts.append(text)
        if i < len(transcript_window) - 1:
            ctx_parts.append(transcript_window[i+1].get("text", ""))
        rich_text = " ".join(ctx_parts).strip()

        candidates.append({"t": t_rel, "text": rich_text, "word_count": len(rich_text.split())})

    if not candidates:
        return []

    candidates.sort(key=lambda x: -x["word_count"])

    selected_moments, selected_times = [], []
    for c in candidates:
        if len(selected_moments) >= max_cuts:
            break
        if any(abs(c["t"] - st) < min_cut_gap_s for st in selected_times):
            continue
        selected_moments.append(c)
        selected_times.append(c["t"])

    if not selected_moments:
        return []

    results: List[Tuple[float, str, float]] = []
    for moment in selected_moments:
        queries = _get_broll_queries(moment["text"], context)
        log.info("[BROLL_AGENT] t=%.2fs | LLM queries: %s", moment["t"], queries)

        asset_path = None
        for q in queries:
            if not q:
                continue
            start_offset = random.uniform(5, 25)
            asset_path = _download_youtube_clip(q, duration=cut_duration_s + 1.0,
                                                start_offset=start_offset,
                                                width=output_width, height=output_height)
            if asset_path:
                break

        if not asset_path:
            log.warning("[BROLL_AGENT] No download for: %s", moment["text"][:60])
            continue

        results.append((moment["t"], asset_path, cut_duration_s))
        print(f"  [BROLL_AGENT] t={moment['t']:.1f}s -> {os.path.basename(asset_path)}", flush=True)
        time.sleep(0.5)

    results.sort(key=lambda x: x[0])
    return results


# -- Standalone Transcription --------------------------------------------------

def _transcribe_clip(clip_path: str) -> List[dict]:
    """
    Transcription priority:
    1. Companion _caption.txt (already generated by HotShort — instant, no model)
    2. Gemini Audio API (upload wav, get text — no local model)
    3. openai-whisper (last resort, if actually installed cleanly)
    NOTE: faster_whisper is intentionally SKIPPED — ctranslate2.dll is broken on this machine.
    """
    # --- Strategy 1: Companion caption.txt (HotShort already transcribed this) ---
    caption_path = clip_path.replace(".mp4", "_caption.txt")
    if os.path.exists(caption_path):
        raw = open(caption_path, encoding="utf-8", errors="ignore").read()
        # Pull meaningful lines (skip headers, hashtags, @ mentions, separators)
        lines = [
            l.strip() for l in raw.splitlines()
            if l.strip()
            and not l.strip().startswith("#")
            and not l.strip().startswith("@")
            and "CAPTION:" not in l
            and "---" not in l
            and not l.strip().startswith("\U0001f4f1")  # 📱
            and not l.strip().startswith("\U0001f7e5")  # 🟥
            and not l.strip().startswith("\U0001f4f8")  # 📸
        ]
        if lines:
            try:
                probe = subprocess.run(
                    ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", clip_path],
                    capture_output=True, text=True
                )
                dur = float(json.loads(probe.stdout).get("format", {}).get("duration", 60.0))
            except Exception:
                dur = 60.0
            chunk = max(1.0, dur / max(len(lines), 1))
            segs, t = [], 0.0
            for line in lines[:20]:
                segs.append({"start": round(t, 2), "end": round(t + chunk, 2), "text": line})
                t += chunk
            log.info("[BROLL_AGENT] Used caption.txt (%d pseudo-segments)", len(segs))
            return segs

    # --- Strategy 2: Gemini Audio API ---
    try:
        from google import genai
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if api_key:
            client = genai.Client(api_key=api_key)
            tmp_wav = clip_path.replace(".mp4", "_broll_tmp.wav")
            subprocess.run(
                ["ffmpeg", "-y", "-nostdin", "-i", clip_path, "-ac", "1", "-ar", "16000", "-vn", tmp_wav],
                capture_output=True, timeout=30
            )
            if os.path.exists(tmp_wav):
                audio_file = client.files.upload(path=tmp_wav)
                resp = client.models.generate_content(
                    model="gemini-1.5-flash",
                    contents=["Transcribe exactly what is spoken. Return only the spoken words as plain text.", audio_file]
                )
                try:
                    os.remove(tmp_wav)
                except Exception:
                    pass
                text = (resp.text or "").strip()
                if text:
                    sentences = [s.strip() for s in re.split(r'[.!?]+', text) if s.strip()]
                    try:
                        probe = subprocess.run(
                            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", clip_path],
                            capture_output=True, text=True
                        )
                        dur = float(json.loads(probe.stdout).get("format", {}).get("duration", 60.0))
                    except Exception:
                        dur = 60.0
                    chunk = dur / max(len(sentences), 1)
                    t, segs = 0.0, []
                    for s in sentences:
                        segs.append({"start": round(t, 2), "end": round(t + chunk, 2), "text": s})
                        t += chunk
                    log.info("[BROLL_AGENT] Used Gemini Audio API (%d segments)", len(segs))
                    return segs
    except Exception as e:
        log.warning("[BROLL_AGENT] Gemini Audio failed: %s", e)

    # --- Strategy 3: openai-whisper (if cleanly installed) ---
    try:
        import whisper
        m = whisper.load_model("tiny")
        res = m.transcribe(clip_path, language="en")
        return [{"start": s["start"], "end": s["end"], "text": s["text"].strip()} for s in res["segments"]]
    except Exception as e:
        log.error("[BROLL_AGENT] All transcription strategies failed: %s", e)
        return []


# -- Overlay Engine ------------------------------------------------------------

def _overlay_broll_on_clip(clip_path: str, broll_cuts: List[Tuple[float, str, float]], output_path: str) -> bool:
    if not broll_cuts:
        shutil.copy2(clip_path, output_path)
        return True

    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", clip_path],
        capture_output=True, text=True
    )
    width, height = 1080, 1920
    try:
        info = json.loads(probe.stdout)
        for s in info["streams"]:
            if s.get("codec_type") == "video":
                width, height = s["width"], s["height"]
                break
    except Exception:
        pass

    inputs = ["ffmpeg", "-y", "-nostdin", "-i", clip_path]
    for _, asset_path, dur in broll_cuts:
        inputs.extend(["-ss", "0", "-t", str(dur + 0.3), "-i", asset_path])

    fc_parts = []
    prev_pad  = "0:v"
    for idx, (t_start, _, dur) in enumerate(broll_cuts):
        br = f"br{idx}"
        ov = f"ov{idx}"
        fc_parts.append(
            f"[{idx+1}:v]setpts=PTS-STARTPTS+{t_start}/TB,scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},fps=30[{br}]"
        )
        t_end = t_start + dur
        fc_parts.append(
            f"[{prev_pad}][{br}]overlay=x=0:y=0:enable='between(t,{t_start:.3f},{t_end:.3f})':eof_action=pass[{ov}]"
        )
        prev_pad = ov

    cmd = inputs + [
        "-filter_complex", ";".join(fc_parts),
        "-map", f"[{prev_pad}]",
        "-map", "0:a?",
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "copy",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=300)
    if result.returncode != 0:
        log.error("[BROLL_AGENT] FFmpeg overlay failed:\n%s", result.stderr[-800:].decode("utf-8", errors="ignore"))
        return False
    return True


# -- Full Pipeline -------------------------------------------------------------

def run_on_clip(clip_path: str, output_path: str, max_cuts: int = 3) -> bool:
    print(f"\n{'='*60}")
    print(f"  Cinematic B-Roll Agent - HotShort")
    print(f"{'='*60}")
    print(f"  Input:  {clip_path}")
    print(f"  Output: {output_path}")
    print(f"{'='*60}\n")

    print("Step 1: Transcribing clip...", flush=True)
    transcript = _transcribe_clip(clip_path)
    if not transcript:
        print("  FAILED: Could not transcribe.")
        return False
    full_text = " ".join(s["text"] for s in transcript)
    print(f"  {len(transcript)} segments | Preview: {full_text[:120]}...\n", flush=True)

    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", clip_path],
        capture_output=True, text=True
    )
    clip_duration = 60.0
    try:
        info = json.loads(probe.stdout)
        clip_duration = float(info.get("format", {}).get("duration", 60.0))
    except Exception:
        pass
    print(f"  Clip duration: {clip_duration:.1f}s\n", flush=True)

    print("Step 2: Gemini B-Roll Director deciding what footage fits...", flush=True)
    cuts = find_cinematic_broll_cuts(
        transcript_window=transcript,
        clip_path=clip_path,
        clip_duration=clip_duration,
        clip_context=full_text,
        max_cuts=max_cuts,
    )

    if not cuts:
        print("  WARNING: No B-Roll cuts generated.")
        return False

    print(f"\nStep 3: Overlaying {len(cuts)} cinematic B-Roll cuts...", flush=True)
    for t, path, dur in cuts:
        print(f"  t={t:.1f}s ({dur}s) <- {os.path.basename(path)}", flush=True)

    success = _overlay_broll_on_clip(clip_path, cuts, output_path)
    if success:
        mb = os.path.getsize(output_path) / 1e6
        print(f"\n  DONE! {output_path} ({mb:.1f} MB)")
    else:
        print("\n  FAILED: Overlay encode failed.")
    return success


# -- CLI -----------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Cinematic B-Roll Agent - HotShort")
    parser.add_argument("clip", help="Input clip path (.mp4)")
    parser.add_argument("--out", help="Output path (default: clip_broll.mp4)")
    parser.add_argument("--max-cuts", type=int, default=3)
    args = parser.parse_args()

    if not os.path.exists(args.clip):
        print(f"ERROR: Clip not found: {args.clip}")
        sys.exit(1)

    out = args.out or args.clip.replace(".mp4", "_broll.mp4")
    ok  = run_on_clip(args.clip, out, max_cuts=args.max_cuts)
    sys.exit(0 if ok else 1)

