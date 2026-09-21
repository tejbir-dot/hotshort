"""
genius_brutal_captioner.py
Viral caption generator with dual backend:
  PRIMARY  : Gemini (via google-genai SDK) — if GEMINI_API_KEY is set
  FALLBACK : OpenRouter (via requests, OpenAI-compatible) — uses GPT_API + HS_GROQ_API_BASE
"""

import os
import requests
import traceback

# ── Gemini SDK (optional) ────────────────────────────────────────────────────
try:
    from google import genai
    from google.genai.errors import APIError
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

# ── Current working Gemini model names (as of Sep 2026) ──────────────────────
_GEMINI_MODELS = [
    "gemini-3.8-flash",               # Newest — released Sep 2026
    "gemini-3.5-flash",               # Stable 3.5
    "gemini-3.1-flash",               # Reliable fallback
    "gemini-3.5-flash-lite",          # Lite — cost-sensitive fallback
]

# ── OpenRouter caption model chain (tries in order) ──────────────────────────
# These are the ACTUALLY available free models on OpenRouter (verified Sep 2026)
_OPENROUTER_CAPTION_MODELS = [
    os.environ.get("HS_CAPTION_MODEL", ""),            # User override from .env
    "nvidia/nemotron-3-ultra-550b-a55b:free",          # NVIDIA 550B — highest quality
    "nvidia/nemotron-3-super-120b-a12b:free",          # NVIDIA 120B — fast & smart
    "nex-agi/nex-n2.5-pro:free",                       # Nex Pro — good reasoning
    "google/gemma-4-31b-it:free",                      # Google Gemma 31B
    "inclusionai/ling-3.0-flash-vl:free",              # InclusionAI — last resort
]
_OPENROUTER_CAPTION_MODELS = [m for m in _OPENROUTER_CAPTION_MODELS if m]  # remove empties


class BrutalCaptioner:
    def __init__(self):
        self.gemini_client = None
        self.openrouter_key = None

        # ── Try Gemini first ──────────────────────────────────────────────────
        api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if api_key and HAS_GENAI:
            try:
                self.gemini_client = genai.Client(api_key=api_key)
                print("[CAPTIONER] Gemini client initialized.", flush=True)
            except Exception as e:
                print(f"[CAPTIONER] Gemini init failed: {e}", flush=True)
        elif not api_key:
            print("[CAPTIONER] GEMINI_API_KEY not set -- will use OpenRouter fallback.", flush=True)

        # ── OpenRouter fallback ───────────────────────────────────────────────
        or_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("GPT_API", "")
        or_base = os.environ.get("HS_GROQ_API_BASE", "https://openrouter.ai/api/v1").rstrip("/")
        if or_key and "openrouter" in or_base:
            self.openrouter_key = or_key
            self.openrouter_base = or_base
            print(f"[CAPTIONER] OpenRouter fallback ready ({_OPENROUTER_CAPTION_MODELS[0]}, +{len(_OPENROUTER_CAPTION_MODELS)-1} fallbacks).", flush=True)

    # ─────────────────────────────────────────────────────────────────────────
    def _build_prompt(self, clip_transcript: str, creator_name: str) -> str:
        return f"""You are a god-tier social media growth hacker.
Write 3 SEPARATE, hyper-viral, high-retention captions for the same video, optimized specifically for TikTok, YouTube Shorts, and Instagram Reels.
The video features {creator_name} talking about making money, tech, or business.

Format your response EXACTLY like this (NO markdown asterisks):

📱 TIKTOK CAPTION:
[Line 1: Extreme clickbait hook with an emoji]
[Line 2-3: Insane curiosity based on the transcript]
[Line 4: Hard CTA to click the link in bio]
[Line 5: Must include @{creator_name} (tagging the creator)]
[Line 6: Hashtags: #clipculture #thegeniusclipper + 3-5 TikTok specific tags]

--------------------------------------------------

🟥 YOUTUBE SHORTS CAPTION:
[Line 1: High SEO-value title/hook]
[Line 2: Brief summary creating loop-curiosity]
[Line 3: CTA to pinned comment or related video]
[Line 4: Must include @{creator_name} in the description]
[Line 5: Hashtags: #clipculture #thegeniusclipper + 5-7 YouTube specific tags]

--------------------------------------------------

📸 INSTAGRAM REELS CAPTION:
[Line 1: Aesthetic/Value-driven hook with emoji]
[Line 2-4: Micro-blog style value drop based on the transcript]
[Line 5: CTA to DM a keyword or check the link in bio]
[Line 6: Must include @{creator_name} to tag the creator]
[Line 7: Hashtags: #clipculture #thegeniusclipper + 7-10 highly targeted IG tags]

Transcript to base it on: "{clip_transcript}"
"""

    # ─────────────────────────────────────────────────────────────────────────
    def _try_gemini(self, prompt: str) -> str | None:
        """Try all Gemini models in order. Returns text or None."""
        if not self.gemini_client:
            return None
        for model_name in _GEMINI_MODELS:
            try:
                response = self.gemini_client.models.generate_content(
                    model=model_name,
                    contents=prompt
                )
                if response and response.text:
                    print(f"[CAPTIONER] Gemini [{model_name}] success.", flush=True)
                    return response.text.replace("**", "").replace("*", "").strip()
                else:
                    print(f"[CAPTIONER] {model_name} empty response. Trying next.", flush=True)
            except Exception as e:
                err = str(e)[:120]
                print(f"[CAPTIONER] {model_name} failed: {err}. Trying next.", flush=True)
        return None

    # ─────────────────────────────────────────────────────────────────────────
    def _try_openrouter(self, prompt: str) -> str | None:
        """OpenRouter fallback — tries each model in _OPENROUTER_CAPTION_MODELS."""
        if not self.openrouter_key:
            return None
        headers = {
            "Authorization": f"Bearer {self.openrouter_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://hotshort.app",
            "X-Title": "HotShort Captioner",
        }
        for model in _OPENROUTER_CAPTION_MODELS:
            payload = {
                "model": model,
                "max_tokens": 800,
                "messages": [{"role": "user", "content": prompt}]
            }
            try:
                r = requests.post(
                    f"{self.openrouter_base}/chat/completions",
                    headers=headers, json=payload, timeout=30
                )
                if r.status_code == 200:
                    data = r.json()
                    content = (
                        data["choices"][0]["message"].get("content")
                        or data["choices"][0]["message"].get("reasoning", "")
                    )
                    if content:
                        print(f"[CAPTIONER] OpenRouter [{model}] success.", flush=True)
                        return content.replace("**", "").replace("*", "").strip()
                    print(f"[CAPTIONER] {model} empty. Trying next.", flush=True)
                else:
                    print(f"[CAPTIONER] {model} -> {r.status_code}. Trying next.", flush=True)
            except Exception as e:
                print(f"[CAPTIONER] {model} error: {str(e)[:80]}. Trying next.", flush=True)
        return None


    # ─────────────────────────────────────────────────────────────────────────
    def generate_viral_caption(self, clip_transcript: str, creator_name: str = "TJR") -> str:
        fallback_caption = (
            "🔥 The secret they don't want you to know...\n\n"
            "Watch the full video to find out!\n\n"
            "👇 Click the link in bio for the exact system.\n\n"
            "#money #tech #hustle #wealth"
        )

        if not clip_transcript or not clip_transcript.strip():
            return fallback_caption

        print(f"[CAPTIONER] Brainstorming viral caption for {creator_name}...", flush=True)
        prompt = self._build_prompt(clip_transcript, creator_name)

        # 1. Try Gemini
        result = self._try_gemini(prompt)
        if result:
            return result

        # 2. Fallback to OpenRouter
        result = self._try_openrouter(prompt)
        if result:
            return result

        # 3. Hardcoded fallback
        print("[CAPTIONER] All backends failed. Using hardcoded fallback caption.", flush=True)
        return fallback_caption
