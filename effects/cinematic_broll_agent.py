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

_MAX_BROLL       = 8
_CUT_DURATION    = 4.0   # Increased from 3s to 4s — prevents rapid-fire glitch feel
_DL_TIMEOUT      = 45
_YT_SEARCH_PREFIX = "ytsearch5:"

# Blocklist: titles containing these words will be skipped (meme/reaction junk)
_BROLL_TITLE_BLOCKLIST = [
    "meme", "reaction", "reacts", "responds", "tiktok", "trending",
    "pov:", "when you", "nobody:", "me when", "fr fr", "ngl",
    "compilation", "moments", "try not to laugh", "caught on camera"
]



# -- Gemini --------------------------------------------------------------------

def _ask_llm(prompt: str) -> Optional[str]:
    """
    OpenRouter is PRIMARY (unlimited free, already working for captioner).
    Gemini SDK is SECONDARY fallback only.
    """
    import requests as _req

    # --- Groq / OpenRouter FIRST ---
    # Disabled: Keys were returning 401. Falling back to Gemini directly.
    # or_key  = os.getenv("GROQ_API_KEY") or os.getenv("OPENROUTER_API_KEY") or os.getenv("GPT_API", "")
    # ...
    # --- Gemini SDK FALLBACK ---
    try:
        from google import genai as _genai
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if api_key:
            _client = _genai.Client(api_key=api_key)
            for model_name in ["gemini-3.5-flash", "gemini-3.5-flash-lite"]:
                try:
                    resp = _client.models.generate_content(
                        model=model_name, contents=prompt,
                        config={"temperature": 0.7, "max_output_tokens": 256, "response_mime_type": "application/json"},
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

_DIRECTOR_PROMPT = '''You are a world-class B-Roll director for viral short-form videos.

FULL CLIP TRANSCRIPT (read the ENTIRE story before deciding anything):
"{clip_context}"

THE SPECIFIC MOMENT TO FIND B-ROLL FOR (this sentence is playing right now):
"{segment_text}"

Your job: pick the 2 MOST VISUALLY SPECIFIC search queries that will find EXACT real-world footage matching what the speaker is saying in THIS SPECIFIC MOMENT.

CRITICAL RULES — FOLLOW IN EXACT ORDER:
1. READ THE FULL TRANSCRIPT above to understand the overall story topic and major themes.
2. PROPER NOUNS FROM THE CURRENT MOMENT WIN. If the CURRENT SENTENCE (marked above) mentions a NAMED LOCATION, NAMED PERSON, or NAMED EVENT — that MUST be the primary subject of your query.
   - WRONG: Speaker current moment says "your mom's got to be nervous" → you pick "White House" (that was from a DIFFERENT moment in the transcript)
   - RIGHT: Speaker current moment says "your mom's got to be nervous" → you pick "MMA fighter mother watching fight anxiously in arena crowd"
   - RIGHT: Speaker current moment says "White House lawn" → you pick "White House South Lawn sports event"
3. Match the B-roll to the EMOTION or SCENE of the CURRENT SENTENCE — not the overall story topic.
4. NO meme footage. NO reaction clips. NO TikTok trend videos. Real documentary/news/sports footage ONLY.
5. Include the specific person name, place name, or event name from the CURRENT SENTENCE in your query if present.
6. ALWAYS INJECT THE OVERALL NICHE/SPORT (e.g. MMA, UFC, basketball, politics) into EVERY query to avoid generic results.
   - WRONG: "parents watching son sports match"
    - RIGHT: "parents watching son UFC MMA fight nervously"
7. RESOLVE PRONOUNS ('he', 'she', 'they') by using the ORIGINAL VIDEO TITLE context. Always use the actual person's name (e.g. Justin Gaethje, Khabib) in your queries instead of generic pronouns or terms like 'MMA fighter'.
8. If a CAMPAIGN/PODCAST NAME is provided, use it to understand the general context (e.g. if Campaign is "Double_coverage_Podcast", it is an NFL American Football podcast).
9. If no proper noun exists in the current sentence, describe the EXACT visual scene being implied.
10. FIGHT MOMENT PRECISION: If the speaker is discussing a specific FIGHT or EVENT, YOU MUST include the exact name of the event, the opponent (if mentioned), and the year (if known). DO NOT use generic terms like 'UFC fight'. Use specific terms like 'Jon Jones vs Shamil Abdurakhimov UFC 285 walkout'.
11. ACTION VERB RULE: For video queries, prioritize action verbs described in the transcript. If the speaker says 'he knocked him out', the query should be '[Guest Name] knockout [Opponent Name] exact moment'.
- Format: ONLY a valid JSON array. Nothing else. No explanation.
- Output EXACTLY: ["query one", "query two"]'''


def _get_broll_queries(segment_text: str, clip_context: str, original_title: str = None, campaign_name: str = None) -> List[str]:
    title_str = f"ORIGINAL VIDEO TITLE: {original_title}\n" if original_title else ""
    campaign_str = f"CAMPAIGN/PODCAST NAME: {campaign_name}\n\n" if campaign_name else "\n"
    prompt = _DIRECTOR_PROMPT.format(
        segment_text=segment_text[:600],
        clip_context=title_str + campaign_str + clip_context[:2000],  # Full transcript, not just 800 chars
    )
    raw = _ask_gemini(prompt)
    if not raw:
        return []

    # Strip markdown code fences (LLM sometimes wraps output in ```json ... ```)
    raw_clean = re.sub(r'```(?:json)?\s*', '', raw).strip().rstrip('`').strip()

    def _is_valid_query(q: str) -> bool:
        """Reject garbage: backticks, too-short, pure punctuation, code artifacts."""
        q = q.strip()
        if len(q) < 6:
            return False
        # Reject if mostly non-alphanumeric (code fences, brackets, etc.)
        alnum = sum(1 for c in q if c.isalnum())
        if alnum < 4:
            return False
        # Reject obvious code artifacts
        bad = ['```', 'json', 'null', 'undefined', '{{', '}}', 'query one', 'query two']
        if any(b in q.lower() for b in bad):
            return False
        return True

    try:
        match = re.search(r'\[.*?\]', raw_clean, re.DOTALL)
        if match:
            queries = json.loads(match.group())
            valid = [q.strip() for q in queries if isinstance(q, str) and _is_valid_query(q)]
            if valid:
                return valid
    except Exception:
        pass
    # Fallback: parse line by line
    lines = [l.strip().strip('"').strip("'") for l in raw_clean.splitlines()
             if l.strip() and not l.strip().startswith('[') and _is_valid_query(l.strip())]
    return lines[:2]


# -- Downloader ----------------------------------------------------------------

def _safe_filename(q: str) -> str:
    return re.sub(r'[^\w\-_]', '_', q)[:80]


def _wikipedia_image_url(query: str) -> Optional[str]:
    """Try to get a direct image URL from Wikipedia's REST summary API."""
    import requests as _req, urllib.parse
    # Try progressively simpler search terms (e.g. "Leonardo DiCaprio US Open" -> "Leonardo DiCaprio")
    candidates = [query]
    # If query has multiple words, also try just the first 2-3 (likely the name)
    words = query.split()
    if len(words) > 3:
        candidates.append(" ".join(words[:2]))
    if len(words) > 2:
        candidates.append(" ".join(words[:3]))

    headers = {"User-Agent": "HotShortBrollAgent/1.0 (hotshort.app)"}
    for term in candidates:
        try:
            r = _req.get(
                "https://en.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(term),
                headers=headers, timeout=6
            )
            if r.status_code == 200:
                thumb = r.json().get("thumbnail", {}).get("source")
                if thumb and "svg" not in thumb.lower():
                    return thumb
        except Exception:
            continue
    return None


def _download_image_broll(query: str, duration: float = 3.0, width: int = 1080, broll_height: int = 960) -> Optional[str]:
    """
    Download an image and render it as a cinematic Ken Burns animated clip.
    PRIMARY source: Wikipedia API (exact celebrity/brand/event photos, always correct).
    FALLBACK: Bing Images murl extraction.
    """
    import requests as _req
    cache_key = f"{_safe_filename(query)}_img_{width}x{broll_height}_{int(duration*10)}.mp4"
    cache_path = os.path.join(_CACHE_DIR, cache_key)
    if os.path.exists(cache_path) and os.path.getsize(cache_path) > 10_000:
        log.info("[BROLL_AGENT] Image cache hit: %s", cache_key)
        return cache_path

    tmpdir = tempfile.mkdtemp()
    try:
        import urllib.parse, urllib.request

        img_url = None

        # --- STRATEGY 1: Wikipedia API (exact, reliable for names/brands/events) ---
        img_url = _wikipedia_image_url(query)
        if img_url:
            log.info("[BROLL_AGENT] Wikipedia image: %s", img_url[:80])

        # --- STRATEGY 2: Bing Images murl (general fallback) ---
        if not img_url:
            try:
                bing_query = query + " real high quality photo -clipart -drawing -cartoon"
                search_url = "https://www.bing.com/images/search?q=" + urllib.parse.quote(bing_query) + "&form=HDRSC3&first=1"
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
                resp = _req.get(search_url, headers=headers, timeout=10)
                # Use the correct JSON murl pattern
                bing_urls = re.findall(r'"murl":"(https?://[^"]+)"', resp.text)
                # Filter out SVG, GIF, logos, icons, clipart
                bad = ["logo", "icon", ".svg", ".gif", "clipart", "clip-art", "vector"]
                bing_urls = [u for u in bing_urls if not any(b in u.lower() for b in bad)]
                if bing_urls:
                    img_url = bing_urls[0]
                    log.info("[BROLL_AGENT] Bing image: %s", img_url[:80])
            except Exception as e:
                log.warning("[BROLL_AGENT] Bing fallback error: %s", e)

        if not img_url:
            log.warning("[BROLL_AGENT] No image found for: %s", query)
            return None

        # Download the image
        ext = ".jpg"
        for candidate_ext in [".jpg", ".jpeg", ".png", ".webp"]:
            if candidate_ext in img_url.lower():
                ext = candidate_ext
                break
        img_path = os.path.join(tmpdir, f"img{ext}")
        headers_dl = {"User-Agent": "HotShortBrollAgent/1.0 (hotshort.app)"}
        req = urllib.request.Request(img_url, headers=headers_dl)
        with urllib.request.urlopen(req, timeout=8) as resp_img:
            with open(img_path, "wb") as f:
                f.write(resp_img.read())

        if not os.path.exists(img_path) or os.path.getsize(img_path) < 5_000:
            log.warning("[BROLL_AGENT] Image too small or missing: %s", query)
            return None

        fps = 30
        total_frames = int(duration * fps)
        zoom_expr = "min(zoom+0.0005,1.06)"
        kenburns_filter = (
            f"scale=8000:-1,"
            f"zoompan=z='{zoom_expr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={total_frames}:s={width}x{broll_height}:fps={fps},"
            f"format=yuv420p,"
            f"fade=t=in:st=0:d=0.25,fade=t=out:st={max(duration-0.3, 0):.3f}:d=0.25"
        )

        ffmpeg_cmd = [
            "ffmpeg", "-y", "-nostdin",
            "-loop", "1", "-i", img_path,
            "-t", str(duration + 0.1),
            "-vf", kenburns_filter,
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-an",
            cache_path
        ]
        r = subprocess.run(ffmpeg_cmd, capture_output=True, timeout=60)
        if r.returncode == 0 and os.path.exists(cache_path) and os.path.getsize(cache_path) > 5_000:
            log.info("[BROLL_AGENT] Image B-Roll ready: %s", cache_key)
            return cache_path
        else:
            log.warning("[BROLL_AGENT] Ken Burns render failed: %s", r.stderr[-300:].decode("utf-8", errors="ignore"))
            return None
    except Exception as e:
        log.warning("[BROLL_AGENT] Image download error: %s", e)
        return None
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _download_youtube_clip(query: str, duration: float = 10.0, start_offset: float = 5.0, width: int = 1080, height: int = 1920) -> Optional[str]:
    cache_key = f"{_safe_filename(query)}_shorts_{int(start_offset)}_{int(duration)}_{width}x{height}.mp4"
    cache_path = os.path.join(_CACHE_DIR, cache_key)
    if os.path.exists(cache_path) and os.path.getsize(cache_path) > 50_000:
        log.info("[BROLL_AGENT] Cache hit: %s", cache_key)
        return cache_path

    tmpdir = tempfile.mkdtemp()
    try:
        dl_template = os.path.join(tmpdir, "raw.%(ext)s")
        short_query = f"{query} -edit -meme -tiktok -sigma -reaction"
        # Reject meme/reaction junk before downloading — check title against blocklist
        blocklist_filter = " & ".join(
            f"title !*= '{word}'" for word in _BROLL_TITLE_BLOCKLIST
        )
        match_filter = f"duration < 300 & {blocklist_filter}"
        yt_cmd = [
            sys.executable, "-m", "yt_dlp", "--no-playlist", "--max-downloads", "1",
            "--js-runtimes", "node",
            "--cookies", r"c:\Users\n\Documents\hotshort\cookies.txt",
            "--match-filter", match_filter,
            "--write-auto-subs", "--sub-format", "vtt", "--sub-langs", "en",
            "-f", "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]",
            "--merge-output-format", "mp4",
            "--no-warnings",
            "-o", dl_template,
            f"ytsearch10:{short_query}",
        ]
        log.info("[BROLL_AGENT] Downloading Short: %s", short_query)
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

        # --- EXACT MOMENT EXTRACTION (Deep Thinking Fix) ---
        # Instead of a random offset, we find the exact center of the short.
        # Short-form content (reactions/memes) peaks in the middle.
        try:
            ffprobe_cmd = [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", raw_path
            ]
            dur_out = subprocess.check_output(ffprobe_cmd, timeout=10).decode("utf-8").strip()
            raw_duration_sec = float(dur_out) if dur_out else 15.0
        except Exception:
            raw_duration_sec = 15.0

        # --- THE SUBTITLE SNIPER & HOOK CUT FIX ---
        smart_offset = 0.5 if raw_duration_sec > 2.0 else 0.0
        try:
            vtt_path = None
            for f in os.listdir(tmpdir):
                if f.endswith(".vtt"):
                    vtt_path = os.path.join(tmpdir, f)
                    break
            
            if vtt_path:
                with open(vtt_path, "r", encoding="utf-8") as f:
                    vtt_content = f.read()
                
                # High-impact action keywords
                action_words = ["knockout", "sleep", "taps", "submission", "submits", "choke", "crank", "over", "wow", "hurt", "cold", "unbelievable", "crazy", "boom", "bam", "win"]
                
                # Match VTT blocks: 00:00:15.000 --> 00:00:17.000\nText
                blocks = re.findall(r'(\d{2}):(\d{2}):(\d{2})\.(\d{3})\s*-->\s*\d{2}:\d{2}:\d{2}\.\d{3}.*?\n(.*?)(?=\n\n|\Z)', vtt_content, re.DOTALL)
                
                for h, m, s, ms, text in blocks:
                    text_lower = text.lower()
                    if any(w in text_lower for w in action_words):
                        sec = int(h) * 3600 + int(m) * 60 + int(s) + float(ms)/1000.0
                        # Cut 1.5 seconds before the word is spoken to capture the wind-up
                        new_offset = max(0.0, sec - 1.5)
                        if new_offset + duration < raw_duration_sec:
                            smart_offset = new_offset
                            log.info("[BROLL_AGENT] Subtitle Sniper hit! Found '%s' at %.1fs", text.strip().replace('\n', ' '), sec)
                            break
        except Exception as e:
            log.warning("[BROLL_AGENT] Subtitle parse failed: %s", e)

        trim_cmd = [
            "ffmpeg", "-y", "-nostdin",
            "-ss", str(smart_offset),
            "-i", raw_path,
            "-t", str(duration + 1.0),
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-an",
            "-vf", f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1,fps=30",
            cache_path
        ]
        r = subprocess.run(trim_cmd, capture_output=True, timeout=60)
        if r.returncode == 0 and os.path.exists(cache_path) and os.path.getsize(cache_path) > 10_000:
            log.info("[BROLL_AGENT] Saved: %s (Hook Cut @ %.1fs)", cache_key, smart_offset)
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

    hook_end  = float(os.environ.get("HS_BROLL_START_SEC", clip_duration * 0.10))
    cta_start = float(os.environ.get("HS_BROLL_END_SEC", clip_duration * 0.85))
    sample_starts = [float(s.get("start", 0)) for s in transcript_window if s.get("text")]
    _is_relative  = bool(sample_starts) and (max(sample_starts) < clip_duration * 2)

    # Attempt to extract original YouTube video title from folder name (11-char ID)
    original_title = None
    try:
        parent_dir = os.path.basename(os.path.dirname(os.path.abspath(clip_path)))
        if len(parent_dir) == 11 and re.match(r'^[A-Za-z0-9_-]+$', parent_dir):
            log.info("[BROLL_AGENT] Detected YouTube ID %s in path. Fetching title...", parent_dir)
            yt_cmd = [sys.executable, "-m", "yt_dlp", "--cookies", r"c:\Users\n\Documents\hotshort\cookies.txt", "--get-title", f"https://youtube.com/watch?v={parent_dir}"]
            r = subprocess.run(yt_cmd, capture_output=True, text=True, timeout=10)
            if r.returncode == 0 and r.stdout.strip():
                original_title = r.stdout.strip()
                log.info("[BROLL_AGENT] Original Video Title: %s", original_title)
    except Exception as e:
        log.warning("[BROLL_AGENT] Failed to fetch original video title: %s", e)

    # Attempt to read campaign/metadata from clip's .meta.json file
    campaign_name = None
    try:
        meta_path = clip_path.replace(".mp4", ".meta.json")
        if os.path.exists(meta_path):
            with open(meta_path, 'r', encoding='utf-8') as f:
                meta_data = json.load(f)
                campaign_name = meta_data.get("campaign")
                if campaign_name:
                    log.info("[BROLL_AGENT] Loaded Campaign Context: %s", campaign_name)
    except Exception as e:
        log.warning("[BROLL_AGENT] Failed to load meta.json: %s", e)



    candidates = []
    for i, seg in enumerate(transcript_window):
        t_rel = float(seg.get("start", 0)) if _is_relative else (float(seg.get("start", 0)))
        t_rel = max(0.0, t_rel - 0.5)  # Shift B-Roll backward by 0.5s to lead the word
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

        score = len(rich_text.split())
        # Boost score heavily for capitalized words (names, brands, places)
        words = rich_text.split()
        proper_nouns = [w for i, w in enumerate(words) if i > 0 and w and w[0].isupper()]
        score += len(proper_nouns) * 10
        # Boost for strong emotion/impact
        if "!" in rich_text or "?" in rich_text:
            score += 5

        candidates.append({"t": t_rel, "text": rich_text, "score": score, "idx": i})

    if not candidates:
        return []

    # Sort by our new intelligence score
    candidates.sort(key=lambda x: -x["score"])

    # Dynamically calculate gap to force B-rolls to spread evenly across the video
    valid_duration = cta_start - hook_end
    dynamic_gap = max(min_cut_gap_s, valid_duration / (max_cuts + 1.5))

    selected_moments, selected_times = [], []
    for c in candidates:
        if len(selected_moments) >= max_cuts:
            break
        if any(abs(c["t"] - st) < dynamic_gap for st in selected_times):
            continue
        selected_moments.append(c)
        selected_times.append(c["t"])

    if not selected_moments:
        return []

    results: List[Tuple[float, str, float]] = []
    broll_region_h = output_height // 2  # B-Roll target height = bottom half
    used_assets: set = set()       # Track committed cache file paths
    used_wiki_urls: set = set()    # Track committed Wikipedia source URLs (prevents same image with different query names)

    for moment in selected_moments:
        # Build LOCAL context: ±2 segments around this moment (prevents cross-moment proper noun bleeding)
        seg_idx = moment.get("idx", 0)
        local_segs = transcript_window[max(0, seg_idx - 2): seg_idx + 3]
        local_text = " | ".join(s.get("text", "") for s in local_segs if s.get("text")).strip()
        # Full story is background context; local_text is what the LLM must match B-roll to
        combined_context = f"[STORY BACKGROUND]: {context[:600]}\n\n[NEARBY SENTENCES at this moment]: {local_text}"
        queries = _get_broll_queries(moment["text"], combined_context, original_title=original_title, campaign_name=campaign_name)
        log.info("[BROLL_AGENT] t=%.2fs | LLM queries: %s", moment["t"], queries)

        asset_path = None
        for q in queries:
            if not q:
                continue

            # PRE-CHECK: Resolve Wikipedia URL BEFORE downloading.
            # If the same Wikipedia image was already committed, skip image and go straight to video.
            wiki_url = _wikipedia_image_url(q)
            wiki_key = wiki_url[:80] if wiki_url else None
            if wiki_url and wiki_key in used_wiki_urls:
                log.warning("[BROLL_AGENT] Wikipedia image already used (different query, same photo) for: %s — skipping to video", q)
                # Go directly to video fallback for this query
                log.info("[BROLL_AGENT] Trying Short instead: %s", q)
                start_offset = random.uniform(2, 8)
                candidate = _download_youtube_clip(q, duration=cut_duration_s + 1.0,
                                                   start_offset=start_offset,
                                                   width=output_width, height=broll_region_h)
                if candidate and candidate not in used_assets:
                    asset_path = candidate
                    break
                continue

            # PRIMARY: Google Images + Ken Burns (fast, exact scene)
            log.info("[BROLL_AGENT] Trying image for: %s", q)
            candidate = _download_image_broll(q, duration=cut_duration_s, width=output_width, broll_height=broll_region_h)
            if candidate and candidate not in used_assets:
                asset_path = candidate
                log.info("[BROLL_AGENT] Got image B-Roll for: %s", q)
                if wiki_key:
                    used_wiki_urls.add(wiki_key)
                break
            elif candidate and candidate in used_assets:
                log.warning("[BROLL_AGENT] Skipping duplicate cached file for: %s — trying next query", q)
                continue

            # FALLBACK: YouTube Short
            log.info("[BROLL_AGENT] Image failed, trying Short: %s", q)
            start_offset = random.uniform(2, 8)
            candidate = _download_youtube_clip(q, duration=cut_duration_s + 1.0,
                                               start_offset=start_offset,
                                               width=output_width, height=broll_region_h)
            if candidate and candidate not in used_assets:
                asset_path = candidate
                break
            elif candidate and candidate in used_assets:
                log.warning("[BROLL_AGENT] Skipping duplicate short for: %s — trying next query", q)

        if not asset_path:
            log.warning("[BROLL_AGENT] No unique download for: %s", moment["text"][:60])
            continue

        used_assets.add(asset_path)
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
                audio_file = client.files.upload(file=tmp_wav)
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

def get_cinematic_broll_filter(width: int, height: int, fade_dur: float = 0.0, total_dur: float = 0.0, target_height: int = 0) -> str:
    """
    Concrete resizing function to fit B-roll into a sub-region of the vertical screen.
    target_height: the region height (e.g. height//2 for bottom half). Defaults to full height.
    Uses letterboxing (decrease + pad) so no extreme zoom/crop.
    """
    th = target_height if target_height > 0 else height
    f_str = (
        f"scale={width}:{th}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{th}:(ow-iw)/2:(oh-ih)/2:black,"
        f"fps=30"
    )
    if fade_dur > 0 and total_dur > 0:
        f_out = total_dur - fade_dur
        f_str += f",format=yuv420p,fade=t=in:st=0:d={fade_dur:.3f},fade=t=out:st={f_out:.3f}:d={fade_dur:.3f}"
    return f_str

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

    # B-roll goes in the BOTTOM half only — speaker face stays on top
    broll_region_h = height // 2
    broll_y_offset  = height - broll_region_h  # = height//2

    inputs = ["ffmpeg", "-y", "-nostdin", "-i", clip_path]
    for _, asset_path, dur in broll_cuts:
        inputs.extend(["-ss", "0", "-t", str(dur + 0.3), "-i", asset_path])

    fc_parts = []
    prev_pad  = "0:v"
    for idx, (t_start, _, dur) in enumerate(broll_cuts):
        br = f"br{idx}"
        ov = f"ov{idx}"
        # Scale asset to fill ONLY the bottom half region
        base_f = get_cinematic_broll_filter(width, height, target_height=broll_region_h)
        fc_parts.append(f"[{idx+1}:v]setpts=PTS-STARTPTS+{t_start}/TB,{base_f}[{br}]")
        t_end = t_start + dur
        fc_parts.append(
            f"[{prev_pad}][{br}]overlay=x=0:y={broll_y_offset}:enable='between(t,{t_start:.3f},{t_end:.3f})':eof_action=pass[{ov}]"
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

def run_on_clip(clip_path: str, output_path: str, max_cuts: int = 5) -> bool:
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

