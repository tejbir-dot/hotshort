try:
    from google import genai
    from google.genai.errors import APIError
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

import os
import traceback

class BrutalCaptioner:
    def __init__(self):
        # We assume the user has set GEMINI_API_KEY in their environment
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            print("[CAPTIONER] Warning: GEMINI_API_KEY not found. Captions will not be generated.", flush=True)
            self.api_key_valid = False
            return
            
        if not HAS_GENAI:
            print("[CAPTIONER] Warning: google-genai package not found. Please run 'pip install google-genai'.", flush=True)
            self.api_key_valid = False
            return
            
        try:
            self.client = genai.Client(api_key=api_key)
            self.api_key_valid = True
        except Exception as e:
            print(f"[CAPTIONER] Failed to initialize Gemini Client: {e}", flush=True)
            self.api_key_valid = False
            
        # Try Flash Lite first, then fallbacks
        self.model_names = [
            'gemini-2.0-flash-lite-preview-02-05',
            'gemini-2.5-flash',
            'gemini-2.0-flash',
            'gemini-1.5-flash'
        ]
        
    def generate_viral_caption(self, clip_transcript: str, creator_name: str = "Daniel") -> str:
        fallback_caption = "🔥 The secret they don't want you to know...\n\nWatch the full video to find out!\n\n👇 Click the link in bio for the exact system.\n\n#money #tech #hustle #wealth"

        if not getattr(self, 'api_key_valid', False):
            return fallback_caption
            
        if not clip_transcript or not clip_transcript.strip():
            return fallback_caption
            
        system_prompt = f"""You are a god-tier social media growth hacker. 
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
        
        print(f"🧠 [CAPTIONER] Brainstorming viral dopamine caption for {creator_name}...", flush=True)
        for model_name in self.model_names:
            try:
                response = self.client.models.generate_content(
                    model=model_name,
                    contents=system_prompt
                )
                if response and response.text:
                    clean_text = response.text.replace("**", "").replace("*", "")
                    return clean_text.strip()
                else:
                    print(f"[CAPTIONER] {model_name} returned empty response. Trying fallback.", flush=True)
            except Exception as e:
                print(f"[CAPTIONER] {model_name} failed: {str(e)[:150]}... Trying fallback.", flush=True)
                
        print("[CAPTIONER] All Gemini models failed. Using hardcoded fallback caption.", flush=True)
        return fallback_caption
