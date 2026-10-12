"""
Viral Source Hunter v1.0
=========================
Takes any viral short clip > Finds original long-form source > Downloads exact segment.

Usage:
  python viral_source_hunter/hunter.py "viral_clip.mp4"
  python viral_source_hunter/hunter.py "https://youtube.com/shorts/XYZ"
  python viral_source_hunter/hunter.py "clip.mp4" --out "segment.mp4" --json
"""

from __future__ import annotations
import os, sys, re, json, time, shutil, logging, tempfile, subprocess, argparse
from typing import Optional
from pathlib import Path

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _env_file in [".env", ".env.local", ".env.worker"]:
    _env_path = os.path.join(_REPO_ROOT, _env_file)
    if os.path.exists(_env_path):
        with open(_env_path, encoding="utf-8", errors="ignore") as _ef:
            for _line in _ef:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _, _v = _line.partition("=")
                    os.environ[_k.strip()] = _v.strip()

sys.path.insert(0, _REPO_ROOT)
log = logging.getLogger("viral_source_hunter")

COOKIES_PATH = os.path.join(_REPO_ROOT, "cookies.txt")
CACHE_DIR    = os.path.join(_REPO_ROOT, "assets", "source_hunter_cache")
os.makedirs(CACHE_DIR, exist_ok=True)
DL_TIMEOUT     = 120
CONFIDENCE_MIN = 40

import random
YTDLP_STEALTH_FLAGS = [
    "--min-sleep-interval", "5",
    "--max-sleep-interval", "15",
    "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "--add-header", "Accept-Language:en-US,en;q=0.9",
    "--sleep-requests", "2"
]


# =========================================================
# LAYER 0 - SIGNAL EXTRACTION
# =========================================================

def extract_keyframes(clip_path: str, tmpdir: str, num_frames: int = 5) -> list:
    frame_paths = []
    try:
        dur_out = subprocess.check_output([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", clip_path
        ], timeout=10).decode().strip()
        duration = float(dur_out) if dur_out else 10.0
    except Exception:
        duration = 10.0

    for i in range(num_frames):
        t = duration * (i + 0.5) / num_frames
        out = os.path.join(tmpdir, f"frame_{i:02d}.jpg")
        r = subprocess.run([
            "ffmpeg", "-y", "-ss", str(t), "-i", clip_path,
            "-frames:v", "1", "-q:v", "2", out
        ], capture_output=True, timeout=15)
        if r.returncode == 0 and os.path.exists(out):
            frame_paths.append(out)

    log.info("[HUNTER] Extracted %d keyframes", len(frame_paths))
    return frame_paths


def transcribe_clip(clip_path: str) -> list:
    try:
        from viral_finder.transcript_engine import transcribe_file_turbo
        segs = transcribe_file_turbo(clip_path, model_name="base.en", prefer_gpu=False)
        log.info("[HUNTER] Transcribed %d segments", len(segs))
        return segs
    except Exception as e:
        log.warning("[HUNTER] transcribe_file_turbo failed: %s — trying whisper directly", e)
    try:
        import whisper
        model = whisper.load_model("base.en")
        result = model.transcribe(clip_path)
        return [{"text": s["text"], "start": s["start"], "end": s["end"]}
                for s in result.get("segments", [])]
    except Exception as e2:
        log.error("[HUNTER] All transcription failed: %s", e2)
        return []


def scrape_metadata_links(url: str) -> Optional[str]:
    if not url.startswith("http"):
        return None
    try:
        result = subprocess.run([
            sys.executable, "-m", "yt_dlp",
            "--cookies", COOKIES_PATH,
            "--dump-json", "--no-playlist", url
        ], capture_output=True, text=True, timeout=20)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            desc = data.get("description", "") or ""
            yt_urls = re.findall(
                r"https?://(?:www\.)?youtube\.com/watch\?v=[\w-]+|https?://youtu\.be/[\w-]+",
                desc
            )
            original_id = data.get("id", "")
            for u in yt_urls:
                if original_id not in u:
                    log.info("[HUNTER] Found source link in metadata: %s", u)
                    return u
    except Exception as e:
        log.debug("[HUNTER] Metadata scrape failed: %s", e)
    return None


# =========================================================
# LAYER 1 - SOURCE IDENTIFICATION (Gemini Vision)
# =========================================================

def _gemini_identify_source(frame_paths: list, transcript_text: str, speaker_hint: str = "") -> dict:
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return {"confidence": 0, "error": "no_gemini_sdk"}

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return {"confidence": 0, "error": "no_api_key"}

    client = genai.Client(api_key=api_key, http_options={"timeout": 45000})

    parts = []
    for fp in frame_paths[:3]:
        try:
            with open(fp, "rb") as f:
                img_bytes = f.read()
            parts.append(types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"))
        except Exception:
            pass

    hint_text = f"\nHINT: The user believes this video is related to the creator/campaign: '{speaker_hint}'. Use this to strongly bias your identification if the face matches." if speaker_hint else ""

    prompt_text = f"""You are a media forensics expert. Analyze these video frames and transcript.
{hint_text}
TRANSCRIPT (first 400 chars): "{transcript_text[:400]}"

Identify the ORIGINAL SOURCE of this short clip. Look for:
- Speaker face / name
- Show or podcast logos, lower-thirds, graphics
- YouTube channel watermarks or handles
- Studio/set design
- Any text overlays, chyrons, or titles

Return ONLY valid JSON:
{{
  "speaker_name": "Full name or unknown",
  "show_name": "Show/podcast name or unknown",
  "channel_name": "YouTube channel or handle or unknown",
  "platform": "youtube | spotify | instagram | tiktok | other",
  "content_type": "podcast | interview | lecture | standup | vlog | other",
  "best_search_query": "Exact YouTube search string — use show name + guest name + topic. MUST be specific enough to return the right episode. Do NOT make up content words.",
  "alternative_queries": ["alternative query 2", "alternative query 3"],
  "episode_guest": "Guest name if identifiable, else unknown",
  "episode_topic": "Main topic discussed in this clip (2-4 words)",
  "confidence": 0,
  "evidence": ["reason1", "reason2"]
}}"""

    parts.append(types.Part.from_text(text=prompt_text))

    for model in ["gemini-3.8-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-2.5-flash"]:
        try:
            log.info("[HUNTER] Gemini model: %s", model)
            response = client.models.generate_content(
                model=model,
                contents=[types.Content(role="user", parts=parts)],
                config=types.GenerateContentConfig(temperature=0.1, response_mime_type="application/json")
            )
            raw = response.text.strip()
            raw = re.sub(r"^```json\s*", "", raw); raw = re.sub(r"\s*```$", "", raw)
            result = json.loads(raw)
            log.info("[HUNTER] Gemini: speaker=%s show=%s channel=%s conf=%s",
                     result.get("speaker_name"), result.get("show_name"),
                     result.get("channel_name"), result.get("confidence"))
            return result
        except Exception as e:
            log.warning("[HUNTER] Model %s failed: %s", model, e)
    return {"confidence": 0, "error": "all_models_failed"}


def _extract_fingerprint_phrases(segments: list) -> list:
    text = " ".join(s.get("text", "") for s in segments)
    sentences = re.split(r"[.!?]", text)
    scored = []
    for sent in sentences:
        sent = sent.strip()
        if len(sent) < 20:
            continue
        score = 0
        if re.search(r"\$[\d,]+|\d+%|\d+ (million|billion|thousand|years|days|months)", sent, re.I):
            score += 3
        score += len(re.findall(r"\b[A-Z][a-z]{2,}\b", sent))
        if any(w in sent.lower() for w in ["um", "uh", "like", "you know", "basically"]):
            score -= 1
        scored.append((score, sent))
    scored.sort(reverse=True)
    return [s[1][:120] for _, s in scored[:5]]


def identify_source(frame_paths: list, viral_segs: list, metadata_link: Optional[str], speaker_hint: str = "") -> dict:
    result = {
        "confidence": 0, "speaker_name": "unknown",
        "show_name": "unknown", "channel_name": "unknown",
        "search_queries": [], "direct_url": None,
    }

    if metadata_link:
        result["direct_url"] = metadata_link
        result["confidence"] += 40
        log.info("[HUNTER] Signal A (metadata link): +40 confidence")

    transcript_text = " ".join(s.get("text", "") for s in viral_segs).strip()
    if frame_paths:
        gdata = _gemini_identify_source(frame_paths, transcript_text, speaker_hint)
        gem_conf_raw = gdata.get("confidence", 0)
        gem_conf = int(float(gem_conf_raw) * 100) if isinstance(gem_conf_raw, float) and gem_conf_raw <= 1.0 else int(gem_conf_raw)
        if gem_conf >= 30:
            result["speaker_name"] = gdata.get("speaker_name", "unknown")
            result["show_name"]    = gdata.get("show_name", "unknown")
            result["channel_name"] = gdata.get("channel_name", "unknown")
            queries = []
            if gdata.get("best_search_query"):
                queries.append(gdata["best_search_query"])
            queries.extend(gdata.get("alternative_queries", []))
            result["search_queries"] = queries
            contrib = min(40, int(gem_conf * 0.4))
            result["confidence"] += contrib
            log.info("[HUNTER] Signal B (Gemini Vision): +%d confidence", contrib)

    # Transcript quote fallback queries
    phrases = _extract_fingerprint_phrases(viral_segs)
    for phrase in phrases[:2]:
        if len(phrase.strip()) < 15:  # Skip garbage short phrases
            continue
        q = f'"{phrase}"'
        if result["speaker_name"] not in ("unknown", "", None):
            q += f" {result['speaker_name']}"
        elif result["show_name"] not in ("unknown", "", None):
            q += f" {result['show_name']}"
        if q not in result["search_queries"] and len(q) > 15:
            result["search_queries"].append(q)

    # Also add episode_guest + show as a clean query if Gemini found them
    guest = result.get("episode_guest", "unknown")
    if guest not in ("unknown", "", None) and result["show_name"] not in ("unknown", "", None):
        clean_q = f"{result['show_name']} {guest}"
        if clean_q not in result["search_queries"]:
            result["search_queries"].insert(0, clean_q)  # Put at front

    log.info("[HUNTER] Confidence: %d | Queries: %s", result["confidence"], result["search_queries"][:2])
    return result


# =========================================================
# LAYER 2 - SOURCE VIDEO FINDER
# =========================================================

def _yt_search(query: str, max_results: int = 5) -> list:
    try:
        result = subprocess.run([
            sys.executable, "-m", "yt_dlp",
            "--cookies", COOKIES_PATH,
            "--dump-json", "--no-playlist", "--flat-playlist",
            f"ytsearch{max_results}:{query}"
        ], capture_output=True, text=True, timeout=30)
        results = []
        for line in result.stdout.strip().splitlines():
            try:
                d = json.loads(line)
                results.append({
                    "url": d.get("url") or f"https://youtube.com/watch?v={d.get('id','')}",
                    "title": d.get("title", ""),
                    "duration": d.get("duration", 0),
                    "id": d.get("id", ""),
                })
            except Exception:
                pass
        return results
    except Exception as e:
        log.warning("[HUNTER] YouTube search failed: %s", e)
        return []


def _parse_vtt(vtt_path: str) -> list:
    segs = []
    try:
        with open(vtt_path, encoding="utf-8", errors="ignore") as f:
            content = f.read()
        blocks = re.findall(
            r"(\d{2}:\d{2}:\d{2}\.\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}\.\d{3})[^\n]*\n(.*?)(?=\n\n|\Z)",
            content, re.DOTALL
        )
        for ts_s, ts_e, text in blocks:
            clean = re.sub(r"<[^>]+>", "", text).strip().replace("\n", " ")
            if clean:
                segs.append({"text": clean, "start": _vtt_to_sec(ts_s), "end": _vtt_to_sec(ts_e)})
    except Exception as e:
        log.warning("[HUNTER] VTT parse failed: %s", e)
    return segs


def _vtt_to_sec(ts: str) -> float:
    try:
        h, m, s = ts.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)
    except Exception:
        return 0.0


def _get_video_subtitles(url: str, tmpdir: str) -> list:
    # 1. Try youtube_transcript_api first (bypasses most yt-dlp blocks)
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        import urllib.parse as urlparse
        parsed = urlparse.urlparse(url)
        video_id = ""
        if "youtube.com" in parsed.netloc:
            video_id = urlparse.parse_qs(parsed.query).get("v", [""])[0]
        elif "youtu.be" in parsed.netloc:
            video_id = parsed.path.lstrip("/")
        
        if video_id:
            api = YouTubeTranscriptApi()
            res = api.fetch(video_id)
            segs = []
            for r in res:
                # FetchedTranscriptSnippet properties
                segs.append({"text": r.text, "start": r.start, "end": r.start + r.duration})
            if segs:
                return segs
    except Exception as e:
        log.warning("[HUNTER] youtube_transcript_api failed (%s), falling back to yt-dlp.", e)

    # 2. Fallback to yt-dlp
    try:
        time.sleep(random.uniform(2.0, 5.0))
        subprocess.run([
            sys.executable, "-m", "yt_dlp",
            "--cookies", COOKIES_PATH,
            "--js-runtimes", "node",
            "--write-subs", "--write-auto-subs",
            "--sub-langs", "en", "--sub-format", "vtt",
            "--skip-download", "--no-playlist"
        ] + YTDLP_STEALTH_FLAGS + [
            "-o", os.path.join(tmpdir, "%(id)s.%(ext)s"),
            url
        ], capture_output=True, timeout=300)
        for p in Path(tmpdir).glob("*.vtt"):
            return _parse_vtt(str(p))
    except Exception as e:
        log.warning("[HUNTER] Subtitle fetch failed: %s", e)
    return []


def _compute_overlap(short_text: str, subs: list) -> float:
    if not subs:
        return 0.0
    full = " ".join(s["text"] for s in subs).lower()
    words = set(re.findall(r"\b\w{4,}\b", short_text.lower()))
    if not words:
        return 0.0
    return sum(1 for w in words if w in full) / len(words)


def find_source_video(identification: dict, viral_text: str) -> Optional[dict]:
    if identification.get("direct_url"):
        url = identification["direct_url"]
        log.info("[HUNTER] Using direct URL: %s", url)
        return {"url": url, "title": "Direct link", "confidence": 95, "overlap_score": 1.0}

    queries = identification.get("search_queries", [])
    if not queries:
        return None

    best, best_score = None, 0.0
    with tempfile.TemporaryDirectory() as tmpdir:
        for query in queries[:4]:
            log.info("[HUNTER] Searching: %s", query)
            for c in _yt_search(query, 5):
                if c["duration"] and c["duration"] < 180:
                    continue  # Skip shorts
                subs = _get_video_subtitles(c["url"], tmpdir)
                overlap = _compute_overlap(viral_text, subs)
                log.info("[HUNTER] Candidate: '%s' | overlap=%.2f", c["title"][:60], overlap)
                if overlap > best_score:
                    best_score = overlap
                    best = {"url": c["url"], "title": c["title"],
                            "duration": c["duration"], "overlap_score": round(overlap, 3),
                            "confidence": int(overlap * 100)}
                if best_score > 0.80:
                    break
            if best_score > 0.80:
                break

    if best:
        log.info("[HUNTER] Best source: '%s' (overlap=%.2f)", best["title"][:60], best["overlap_score"])
    return best if (best and best["overlap_score"] > 0.15) else None


# =========================================================
# LAYER 3 - TIMESTAMP ALIGNMENT
# =========================================================

def align_timestamp(source_url: str, viral_segs: list) -> Optional[dict]:
    viral_text  = " ".join(s.get("text", "") for s in viral_segs).lower()
    viral_words = re.findall(r"\b\w{3,}\b", viral_text)
    if not viral_words:
        return None

    with tempfile.TemporaryDirectory() as tmpdir:
        subs = _get_video_subtitles(source_url, tmpdir)

    if not subs:
        return None

    best_start, best_end, best_score = 0.0, 0.0, 0.0
    window_size = max(5, len(viral_words) // 8)

    for i in range(len(subs)):
        window = subs[i: i + window_size]
        if not window:
            continue
        w_words = set(re.findall(r"\b\w{3,}\b", " ".join(s["text"] for s in window).lower()))
        overlap = len(set(viral_words) & w_words) / len(set(viral_words))
        if overlap > best_score:
            best_score = overlap
            best_start = window[0]["start"]
            best_end   = window[-1]["end"]

    if best_score < 0.20:
        log.warning("[HUNTER] Alignment score too low: %.2f", best_score)
        return None

    log.info("[HUNTER] Aligned: %.1fs→%.1fs (score=%.2f)", best_start, best_end, best_score)
    return {"start_sec": max(0.0, best_start), "end_sec": best_end, "alignment_score": round(best_score, 3)}


# =========================================================
# LAYER 4 - PRECISION DOWNLOAD
# =========================================================

def precision_download(source_url: str, start_sec: float, end_sec: float,
                        output_path: str, lead_in: float = 5.0, tail: float = 10.0) -> bool:
    dl_start = max(0.0, start_sec - lead_in)
    dl_end   = end_sec + tail
    section  = f"*{dl_start:.1f}-{dl_end:.1f}"
    log.info("[HUNTER] Downloading %.1fs–%.1fs", dl_start, dl_end)

    tmpdir = tempfile.mkdtemp()
    try:
        time.sleep(random.uniform(3.0, 6.0))
        tmp_out = os.path.join(tmpdir, "segment.%(ext)s")
        r = subprocess.run([
            sys.executable, "-m", "yt_dlp",
            "--cookies", COOKIES_PATH,
            "--download-sections", section,
            "--force-keyframes-at-cuts",
            "--no-playlist",
            "-f", "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]",
            "--merge-output-format", "mp4",
            "--no-warnings"
        ] + YTDLP_STEALTH_FLAGS + [
            "-o", tmp_out, source_url
        ], capture_output=True, timeout=DL_TIMEOUT)

        if r.returncode != 0:
            log.warning("[HUNTER] yt-dlp failed: %s", r.stderr[-500:].decode("utf-8", errors="ignore"))
            return False

        for fname in os.listdir(tmpdir):
            if fname.endswith(".mp4"):
                shutil.move(os.path.join(tmpdir, fname), output_path)
                log.info("[HUNTER] Saved: %s (%.1f MB)", output_path, os.path.getsize(output_path)/1e6)
                return True

        log.warning("[HUNTER] No .mp4 found after download")
        return False
    except subprocess.TimeoutExpired:
        log.error("[HUNTER] Download timed out")
        return False
    except Exception as e:
        log.error("[HUNTER] Download error: %s", e)
        return False
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# =========================================================
# BONUS - ADJACENT MOMENT DISCOVERY
# =========================================================

def discover_adjacent_moments(found_start: float, found_end: float, source_subs: list) -> list:
    try:
        from viral_finder.narrative_trigger_engine import detect_narrative_triggers
        scan_start = max(0.0, found_start - 180)
        scan_end   = found_end + 180
        window_subs = [s for s in source_subs if s["start"] >= scan_start and s["end"] <= scan_end]
        if not window_subs:
            return []
        triggers = detect_narrative_triggers(window_subs)
        adjacent = []
        for t in triggers:
            t_s, t_e = t.get("start", 0), t.get("end", 0)
            if min(t_e, found_end) - max(t_s, found_start) > 5:
                continue
            adjacent.append({"start_sec": t_s, "end_sec": t_e,
                              "type": t.get("type"), "confidence": t.get("confidence", 0),
                              "phrase": t.get("phrase", "")})
        log.info("[HUNTER] %d adjacent moments found", len(adjacent))
        return adjacent
    except Exception as e:
        log.warning("[HUNTER] Adjacent discovery failed: %s", e)
        return []


# =========================================================
# MAIN ORCHESTRATOR
# =========================================================

def hunt(input_path: str, output_path: Optional[str] = None,
         lead_in: float = 5.0, tail: float = 10.0, speaker_hint: str = "") -> dict:
    t0 = time.time()
    log.info("=" * 60)
    log.info("[HUNTER] Starting hunt: %s", input_path)
    if speaker_hint:
        log.info("[HUNTER] Speaker Hint: %s", speaker_hint)
    log.info("=" * 60)

    result = {
        "input": input_path, "status": "failed",
        "source_url": None, "source_title": None,
        "start_sec": None, "end_sec": None,
        "alignment_score": None, "confidence": 0,
        "output_path": None, "adjacent_moments": [], "elapsed_sec": 0,
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        clip_path = input_path
        is_url    = input_path.startswith("http")

        if is_url:
            log.info("[HUNTER] Downloading viral clip...")
            local_clip = os.path.join(tmpdir, "viral_clip.mp4")
            time.sleep(random.uniform(1.0, 3.0))
            r = subprocess.run([
                sys.executable, "-m", "yt_dlp",
                "--cookies", COOKIES_PATH, "--no-playlist",
                "--js-runtimes", "node",
                "-f", "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=720]+bestaudio/best[height<=720]/best",
                "--merge-output-format", "mp4",
                "--no-warnings"
            ] + YTDLP_STEALTH_FLAGS + [
                "-o", local_clip, input_path
            ], capture_output=True, timeout=300)
            if r.returncode != 0 or not os.path.exists(local_clip):
                stderr = r.stderr.decode("utf-8", errors="ignore")[-500:]
                log.error("[HUNTER] Viral clip download failed: %s", stderr)
                result["error"] = "viral_clip_download_failed"
                return result
            clip_path = local_clip

        # Layer 0
        log.info("[HUNTER] Layer 0: Extracting signals...")
        frame_paths   = extract_keyframes(clip_path, tmpdir)
        viral_segs    = transcribe_clip(clip_path)
        metadata_link = scrape_metadata_links(input_path) if is_url else None
        viral_text    = " ".join(s.get("text", "") for s in viral_segs).strip()

        if not viral_text:
            result["error"] = "empty_transcript"; return result
        log.info("[HUNTER] Transcript: %s...", viral_text[:120])

        # Layer 1
        log.info("[HUNTER] Layer 1: Identifying source...")
        identification    = identify_source(frame_paths, viral_segs, metadata_link, speaker_hint)
        result["confidence"]   = identification["confidence"]
        result["speaker"]      = identification.get("speaker_name")
        result["show"]         = identification.get("show_name")

        # Layer 2
        log.info("[HUNTER] Layer 2: Finding source video...")
        source_video = find_source_video(identification, viral_text)
        if not source_video:
            result["error"] = "source_not_found"
            result["elapsed_sec"] = round(time.time() - t0, 1)
            return result

        result["source_url"]   = source_video["url"]
        result["source_title"] = source_video["title"]
        result["confidence"]   = max(result["confidence"], source_video["confidence"])
        log.info("[HUNTER] Source: %s", source_video["title"][:80])

        # Layer 3
        log.info("[HUNTER] Layer 3: Aligning timestamps...")
        alignment = align_timestamp(source_video["url"], viral_segs)
        if not alignment:
            alignment = {"start_sec": 0.0, "end_sec": 60.0, "alignment_score": 0.0}

        result["start_sec"]       = alignment["start_sec"]
        result["end_sec"]         = alignment["end_sec"]
        result["alignment_score"] = alignment["alignment_score"]

        # Adjacent moments bonus
        log.info("[HUNTER] Bonus: Adjacent moment scan...")
        with tempfile.TemporaryDirectory() as sub_tmpdir:
            source_subs = _get_video_subtitles(source_video["url"], sub_tmpdir)
        result["adjacent_moments"] = discover_adjacent_moments(
            alignment["start_sec"], alignment["end_sec"], source_subs
        )

        # Layer 4
        if output_path is None:
            safe_title = re.sub(r"[^\w\s-]", "", source_video["title"][:40]).strip().replace(" ", "_")
            output_path = os.path.join(CACHE_DIR, f"{safe_title}_{int(alignment['start_sec'])}s.mp4")

        log.info("[HUNTER] Layer 4: Downloading segment...")
        success = precision_download(
            source_video["url"], alignment["start_sec"], alignment["end_sec"],
            output_path, lead_in=lead_in, tail=tail,
        )
        if success:
            result["status"]      = "success"
            result["output_path"] = output_path
        else:
            result["error"] = "download_failed"

    result["elapsed_sec"] = round(time.time() - t0, 1)
    log.info("=" * 60)
    if result["status"] == "success":
        log.info("[HUNTER] SUCCESS in %.1fs | %s | %.1fs→%.1fs | align=%.0f%%",
                 result["elapsed_sec"], result["source_title"],
                 result["start_sec"], result["end_sec"],
                 (result["alignment_score"] or 0) * 100)
        log.info("[HUNTER] Output: %s", result["output_path"])
        log.info("[HUNTER] Adjacent moments: %d", len(result["adjacent_moments"]))
    else:
        log.error("[HUNTER] FAILED: %s", result.get("error"))
    log.info("=" * 60)
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Viral Source Hunter")
    parser.add_argument("input",     help="Viral clip MP4 path or YouTube URL")
    parser.add_argument("--out",     help="Output path", default=None)
    parser.add_argument("--lead-in", type=float, default=5.0)
    parser.add_argument("--tail",    type=float, default=10.0)
    parser.add_argument("--json",    action="store_true")
    args = parser.parse_args()

    result = hunt(args.input, output_path=args.out, lead_in=args.lead_in, tail=args.tail)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if result["status"] == "success":
            print(f"\nSUCCESS!")
            print(f"  Source : {result['source_title']}")
            print(f"  Time   : {result['start_sec']:.1f}s -> {result['end_sec']:.1f}s")
            print(f"  Align  : {int((result['alignment_score'] or 0)*100)}%")
            print(f"  Output : {result['output_path']}")
            if result["adjacent_moments"]:
                print(f"\nAdjacent undiscovered moments:")
                for m in result["adjacent_moments"][:3]:
                    print(f"  [{m['type']}] {m['start_sec']:.1f}s->{m['end_sec']:.1f}s | '{m['phrase'][:60]}'")
        else:
            print(f"\nFAILED: {result.get('error', 'unknown')}")
