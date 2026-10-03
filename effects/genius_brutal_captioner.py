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
# Audit 2026-10-03: tested all free models live on https://youtu.be/Xdu6j2E1DEI
# qwen/qwen3.8-27b:free → 85.3/100 avg, 7-10s, 0 format failures → PRIMARY
# nemotron-3.5-lightning  → 20% success (thinking chain overflow), 30-90s → FALLBACK
_OPENROUTER_CAPTION_MODELS = [
    os.environ.get("HS_CAPTION_MODEL", ""),            # User override from .env
    "qwen/qwen3.8-27b:free",                           # BEST: 85.3/100, 7-10s
    "nvidia/nemotron-3.5-lightning:free",              # Fallback: slower, thinking chain
    "liquid/lfm-2.5-2.6b:free",                       # Last resort: fast but small
    "inclusionai/ling-3.0-flash-sante:free",          # Emergency fallback
]
_OPENROUTER_CAPTION_MODELS = [m for m in _OPENROUTER_CAPTION_MODELS if m]  # remove empties

# Per-model token budgets — thinking models need extra room to finish their chain
_MODEL_MAX_TOKENS = {
    "qwen/qwen3.8-27b:free":              1800,   # 7-10s, needs ~1600 tokens total
    "nvidia/nemotron-3.5-lightning:free": 2500,   # thinking chain can be 1500+ tokens
    "liquid/lfm-2.5-2.6b:free":           1200,   # small model, less thinking
    "default":                            1800,
}
# Per-model timeouts (seconds)
_MODEL_TIMEOUT = {
    "qwen/qwen3.8-27b:free":              25,
    "nvidia/nemotron-3.5-lightning:free": 50,
    "liquid/lfm-2.5-2.6b:free":           15,
    "default":                            30,
}


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

    def _build_prompt(self, clip_transcript: str, creator_name: str) -> str:
        return f"""You are the #1 viral short-form clip editor in the world. You have studied every 10M+ view clip from 2021–2025 and you know EXACTLY what stops a scroll in 0.3 seconds.

The creator is {creator_name}. Your job is to write 3 DIFFERENT platform captions that each feel like they were written by a different person — NOT the same POV template copy-pasted 3 times.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 1 — EXTRACT THE PAYLOAD (do this in your head, do NOT print it):
Before writing, ask yourself: "What is the single most insane, embarrassing, shocking, or counter-intuitive thing said in this transcript?" That one thing becomes the engine of every hook. If there's a number, USE IT. If there's an admission, USE IT. If there's a contradiction, USE IT.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ELITE HOOK EXAMPLES (calibrate your writing to THIS level):
✅ "This man made $2,300,000 at 23 and DELETED everything to start over"
✅ "He admitted on camera he lost $80k in ONE trade and called it his best investment"
✅ "Nobody talks about the dirty secret behind why 97% of traders blow up in month 1"
✅ "Wait. He bought a $3M watch... while still paying rent???"
✅ "The moment he said this OUT LOUD, the entire internet broke"
✅ "Stop scrolling — he just described your exact bank account without knowing you"
✅ "I can't believe he admitted this publicly. Delete this if it gets too real."

❌ BAD hooks (DO NOT write like this):
❌ "POV: You finally realize why you are broke" (zero specificity, no stakes)
❌ "POV: You are sitting somewhere having an epiphany" (generic, no claim)
❌ "He shares his mindset tips" (sounds like a LinkedIn post)
❌ Any hook that could apply to ANY video on ANY topic (must be THIS specific clip)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HOOK ROTATION RULE — each platform MUST use a different opener style:
• TikTok: Use ONE of → "Wait.", "Nobody admits this but...", "He said [EXACT QUOTE] and I had to rewind it", "I can't stop thinking about what he said at [timestamp context]", "Stop scrolling —"  
• YouTube Shorts: Must lead with the MOST SHOCKING NUMBER or FACT from the clip as an SEO title (no POV:, no fluff)
• Instagram Reels: Use "The truth about...", "Unpopular opinion:", "Real talk:", or a numbered list hook "3 things {creator_name} said that will ruin your 9-5 forever"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CRITICAL RULES:
1. "POV:" is BANNED from TikTok and YouTube captions. Only allowed once on Instagram if nothing better fits.
2. The hook (Line 1) must contain a SPECIFIC claim, number, or direct quote fragment — NO vague abstractions
3. Use CAPS on the single word that would make someone's jaw drop (one word max, not "ONE MENTAL SHIFT")
4. Create a curiosity gap — hint at the payoff WITHOUT revealing it
5. Write like your account already has 800k followers who unfollow instantly if you're generic
6. NO markdown bold (**), NO asterisks. Plain text only.

FORMAT (follow EXACTLY):

📱 TIKTOK CAPTION:
[Line 1: Bold shocking hook — NOT starting with POV:]
[Line 2-3: Stakes/curiosity based on specific transcript content]
[Line 4: Hard CTA — "click link in bio" or "watch before it's gone"]
[Line 5: @{creator_name}]
[Line 6: #clipculture #thegeniusclipper + 3-5 niche hashtags]

--------------------------------------------------

🟥 YOUTUBE SHORTS CAPTION:
[Line 1: SEO title — lead with the shocking number/fact, no POV:]
[Line 2: Loop-curiosity description ending in open question]
[Line 3: CTA]
[Line 4: @{creator_name}]
[Line 5: #clipculture #thegeniusclipper + 5-7 YouTube tags]

--------------------------------------------------

📸 INSTAGRAM REELS CAPTION:
[Line 1: "The truth about...", "Real talk:" or numbered insight hook]
[Line 2-4: Micro-blog punchy insights pulled from specific transcript moments]
[Line 5: CTA — DM keyword or link in bio]
[Line 6: @{creator_name}]
[Line 7: #clipculture #thegeniusclipper + 7-10 IG tags]

TRANSCRIPT:
\"\"\"{clip_transcript}\"\"\"
"""



    # ─────────────────────────────────────────────────────────────────────────
    def _try_gemini(self, prompt: str) -> str | None:
        """Try all Gemini models in order. Returns text or None."""
        if not self.gemini_client:
            return None
        for model_name in _GEMINI_MODELS:
            try:
                from google.genai import types as _gtypes
                response = self.gemini_client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=_gtypes.GenerateContentConfig(
                        temperature=1.0,      # max creativity — breaks generic patterns
                        max_output_tokens=1400,
                    )
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
    @staticmethod
    def _strip_thinking(raw: str) -> str:
        """Strip reasoning/thinking chains from models like Nemotron/Qwen.
        
        These models output their chain-of-thought BEFORE the structured answer.
        We find the LAST occurrence of our output markers to skip the thinking.
        """
        # Try to find final structured output after reasoning
        markers = [
            'TIKTOK CAPTION', '1. TIKTOK', 'TIKTOK:',
            '1.TIKTOK', 'TIKTOK CAPTION:', '## TIKTOK',
        ]
        best_idx = -1
        for marker in markers:
            idx = raw.rfind(marker)   # rfind = LAST occurrence = after thinking chain
            if idx > best_idx:
                best_idx = idx
        if best_idx > 0 and best_idx > len(raw) * 0.3:  # only strip if significant thinking
            stripped = raw[best_idx:].strip()
            if len(stripped) > 50:  # sanity check: result must be substantial
                return stripped
        return raw

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
            max_tok = _MODEL_MAX_TOKENS.get(model, _MODEL_MAX_TOKENS["default"])
            timeout = _MODEL_TIMEOUT.get(model, _MODEL_TIMEOUT["default"])
            payload = {
                "model": model,
                "max_tokens": max_tok,
                "temperature": 0.95,   # high creativity — push past safe generic hooks
                "messages": [{"role": "user", "content": prompt}]
            }
            try:
                r = requests.post(
                    f"{self.openrouter_base}/chat/completions",
                    headers=headers, json=payload, timeout=timeout
                )
                if r.status_code == 200:
                    data = r.json()
                    content = (
                        data["choices"][0]["message"].get("content")
                        or data["choices"][0]["message"].get("reasoning", "")
                    )
                    if content:
                        # Strip thinking chains before returning
                        content = self._strip_thinking(content)
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
