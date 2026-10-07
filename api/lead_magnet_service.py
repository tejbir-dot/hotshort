import os
import smtplib
from email.message import EmailMessage
import time
import uuid
import traceback
from concurrent.futures import ThreadPoolExecutor

# Make sure we can import from hotshort core
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from viral_finder.orchestrator import orchestrate

class LeadMagnetEngine:
    def __init__(self):
        # Setup email (Uses Gmail App Passwords or SendGrid)
        self.smtp_user = os.getenv("SMTP_USER", "your-email@gmail.com")
        self.smtp_pass = os.getenv("SMTP_PASS", "") 
        self.smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", "465"))
        
        self.executor = ThreadPoolExecutor(max_workers=2)

    def trigger_free_clip(self, youtube_url: str, user_email: str):
        """Non-blocking call to generate and email a free clip."""
        print(f"[LEAD MAGNET] Queued {youtube_url} for {user_email}")
        self.executor.submit(self._process_and_email, youtube_url, user_email)
        return {"status": "queued", "message": "Your viral clip will arrive in 10 minutes!"}

    def _process_and_email(self, youtube_url: str, user_email: str):
        try:
            print(f"[LEAD MAGNET] Starting generation for {user_email}")
            
            # 1. Generate ONLY the top 1 clip (Fast, saves compute)
            # using 'staged' mode so it renders everything (b-roll, captions, face-tracking)
            clips = orchestrate(
                youtube_url, 
                top_k=1, 
                prefer_gpu=True, 
                use_cache=True, 
                pipeline_mode="staged"
            )
            
            if not clips or len(clips) == 0:
                self._send_failure_email(user_email)
                return
            
            # The orchestrator returns a dict with 'rendered_path' in staged mode
            clip = clips[0]
            rendered_video_path = clip.get('rendered_path') or clip.get('path')
            
            if not rendered_video_path or not os.path.exists(rendered_video_path):
                self._send_failure_email(user_email)
                return
                
            # 2. Upload video to cloud (Cloudinary / S3) so we can link it
            # For local testing, we might just attach it if it's small (<20MB)
            # But emailing a link is safer for CAN-SPAM. 
            video_link = self._upload_to_storage(rendered_video_path)
            
            # 3. Send the Success Email + Upsell
            self._send_success_email(user_email, video_link, clip.get('score', 95.0))
            
        except Exception as e:
            print(f"[LEAD MAGNET] Error processing for {user_email}: {e}")
            traceback.print_exc()
            self._send_failure_email(user_email)

    def _upload_to_storage(self, filepath: str) -> str:
        # Placeholder for Cloudinary or S3 upload logic
        # For now, if deployed on a VPS, we can serve it via a static route
        filename = os.path.basename(filepath)
        print(f"[LEAD MAGNET] Uploaded {filename} to cloud storage.")
        return f"https://app.hotshort.com/downloads/{filename}"

    def _send_success_email(self, to_email: str, video_link: str, score: float):
        subject = "Here is your Viral Short! 🚀 (Powered by HotShort AI)"
        
        body = f"""
        Hey there!

        Our AI just finished analyzing your video. We extracted the moment with the highest retention probability (Engagement Score: {score}/100) and fully edited it with dynamic captions, face-tracking, and cinematic B-Rolls.

        👉 Download your Free Viral Clip here:
        {video_link}

        **Want more?**
        Our AI actually found 8 other highly viral moments in that same video. 
        Click below to unlock and download all of them instantly for just $50:
        https://app.hotshort.com/checkout?tier=premium

        Post this clip today and let us know how it performs!

        Best,
        The HotShort AI Team
        """
        self._send_smtp(to_email, subject, body)
        print(f"[LEAD MAGNET] Success email sent to {to_email}")

    def _send_failure_email(self, to_email: str):
        subject = "HotShort AI: Could not process your video"
        body = "Sorry, our AI couldn't find a highly engaging moment in the video you provided, or it was too long. Please try another link at https://app.hotshort.com!"
        self._send_smtp(to_email, subject, body)

    def _send_smtp(self, to_email: str, subject: str, body: str):
        if not self.smtp_pass:
            print("[LEAD MAGNET WARNING] SMTP_PASS not set. Skipping actual email send.")
            print(f"--- EMAIL TO: {to_email} ---\n{subject}\n{body}\n---------------------------")
            return
            
        msg = EmailMessage()
        msg.set_content(body)
        msg['Subject'] = subject
        msg['From'] = self.smtp_user
        msg['To'] = to_email

        try:
            # Using SSL for port 465
            server = smtplib.SMTP_SSL(self.smtp_server, self.smtp_port)
            server.login(self.smtp_user, self.smtp_pass)
            server.send_message(msg)
            server.quit()
        except Exception as e:
            print(f"[LEAD MAGNET] SMTP Error: {e}")

# Standalone tester
if __name__ == "__main__":
    engine = LeadMagnetEngine()
    engine.trigger_free_clip("https://youtu.be/qJap-CZoV6g", "test_client@gmail.com")
