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
Write a hyper-viral, high-retention caption for an Instagram Reel/Short.
The video features {creator_name} talking about making money, tech, or business.

Rules:
1. Line 1: An extreme clickbait (but true) hook to stop the scroll. Include an emoji.
2. Line 2-3: Build insane curiosity about the transcript.
3. Line 4: Hard Call-To-Action (CTA) telling them to click the link in bio/comments for the full system.
4. Line 5: 5-7 highly targeted SEO hashtags.
5. NO markdown formatting. Do not output asterisks or bold text. 

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
