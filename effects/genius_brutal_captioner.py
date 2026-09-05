import google.generativeai as genai
import os
import traceback

class BrutalCaptioner:
    def __init__(self):
        # We assume the user has set GEMINI_API_KEY in their environment
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            print("[CAPTIONER] Warning: GEMINI_API_KEY not found. Captions will not be generated.", flush=True)
            self.model = None
            return
            
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-1.5-flash')
        
    def generate_viral_caption(self, clip_transcript: str, creator_name: str = "Daniel") -> str:
        if not self.model:
            return ""
            
        if not clip_transcript or not clip_transcript.strip():
            return "🔥 The secret they don't want you to know...\n\nWatch the full video to find out!\n\n👇 Click the link in bio for the exact system.\n\n#money #tech #hustle #wealth"
            
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
        
        try:
            print(f"🧠 [CAPTIONER] Brainstorming viral dopamine caption for {creator_name}...", flush=True)
            response = self.model.generate_content(system_prompt)
            # Remove any markdown asterisks if the model ignores the prompt
            clean_text = response.text.replace("**", "").replace("*", "")
            return clean_text.strip()
        except Exception as e:
            print(f"[CAPTIONER] Failed to generate caption: {e}\n{traceback.format_exc()}", flush=True)
            return ""
