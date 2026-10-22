import asyncio
import os
import shutil
import subprocess
from playwright.async_api import async_playwright

async def record_home_screen():
    rec_dir = os.path.abspath("scratch/marketing_factory/recordings")
    os.makedirs(rec_dir, exist_ok=True)
    
    # Clean previous temp files
    for f in os.listdir(rec_dir):
        try: os.remove(os.path.join(rec_dir, f))
        except: pass

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            channel="chrome",
            headless=True
        )
        
        context = await browser.new_context(
            viewport={"width": 393, "height": 852},
            device_scale_factor=2,
            is_mobile=True,
            has_touch=True,
            record_video_dir=rec_dir,
            record_video_size={"width": 393, "height": 852}
        )
        
        page = await context.new_page()
        print("Navigating to http://127.0.0.1:5000...")
        await page.goto("http://127.0.0.1:5000", wait_until="networkidle")
        await asyncio.sleep(1.0)
        
        input_selector = 'input[name="youtube_url"]'
        btn_selector = '#homeAnalyzeBtn'
        
        print("Clicking input box...")
        await page.click(input_selector)
        await asyncio.sleep(0.4)
        
        url_text = "https://youtube.com/watch?v=viral_stream"
        print(f"Typing '{url_text}'...")
        await page.type(input_selector, url_text, delay=45)
        await asyncio.sleep(0.8)
        
        print("Clicking 'Analyze Now' button...")
        await page.click(btn_selector)
        await asyncio.sleep(3.5)
        
        print("Finalizing recording...")
        await context.close()
        video_path = await page.video.path()
        await browser.close()
        
    print(f"Raw recorded video saved to: {video_path}")
    
    # Convert to standard MP4 with ffmpeg
    final_output = os.path.abspath("marketing_factory/assets/real_app_demo.mp4")
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-r", "30",
        final_output
    ]
    subprocess.run(cmd, check=True)
    print(f"Success! Clean mobile app demo saved to: {final_output}")

if __name__ == "__main__":
    asyncio.run(record_home_screen())
