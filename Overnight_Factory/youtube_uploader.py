import asyncio
import random
from playwright.async_api import async_playwright
import psutil
import re

def get_dolphin_ws_endpoint():
    print("🔍 Scanning OS for Dolphin Anty's hidden port...")
    for p in psutil.process_iter(['name', 'cmdline']):
        try:
            cmd_args = p.info.get('cmdline') or []
            cmd = " ".join(cmd_args)
            name = (p.info.get('name') or '').lower()
            
            if 'chrome' in name and '--remote-debugging-port=' in cmd:
                match = re.search(r'--remote-debugging-port=(\d+)', cmd)
                if match:
                    port = match.group(1)
                    print(f"🎯 TARGET ACQUIRED! Dolphin running on Port: {port}")
                    return f"http://127.0.0.1:{port}"
        except Exception:
            pass
            
    raise Exception("❌ Dolphin Anty profile running nahi hai! Pehle app mein START click kar.")

async def run_youtube_uploader(video_path, caption):
    print(f"🚀 STARTING GHOST FACTORY: GOD MODE FOR YOUTUBE")
    
    ws_endpoint = get_dolphin_ws_endpoint()
    
    async with async_playwright() as p:
        # --- 1. THE CDP CONNECTION ---
        print("🔗 Connecting Playwright to running Dolphin Profile...")
        browser = await p.chromium.connect_over_cdp(ws_endpoint)
        context = browser.contexts[0]
        page = await context.new_page()

        # --- 2. WARM-UP SHIELD (YouTube Homepage Scroll) ---
        print("🧘‍♂️ Warming up the Algorithm... Scrolling YouTube Homepage...")
        await page.goto("https://www.youtube.com/", timeout=60000)
        await asyncio.sleep(random.uniform(3.0, 5.0))
        
        # Thoda human jaisa scroll
        await page.mouse.wheel(0, 800)
        await asyncio.sleep(random.uniform(2.0, 4.0))
        await page.mouse.wheel(0, 1200)
        print("✅ Warm-up complete! Looking like a real USA viewer.")
        await asyncio.sleep(2.0)

        try:
            # --- 3. NAVIGATE TO YT STUDIO ---
            print("🛡️ Entering YouTube Studio Mainframe...")
            await page.goto("https://studio.youtube.com/", timeout=60000)
            await asyncio.sleep(random.uniform(5.0, 8.0))

            # Click "Create" Button
            print("🖱️ Clicking 'Create'...")
            await page.locator('#create-icon').click()
            await asyncio.sleep(random.uniform(1.0, 2.0))
            
            # Click "Upload videos"
            await page.locator('#text:has-text("Upload videos")').first.click()
            await asyncio.sleep(random.uniform(2.0, 3.0))

            # --- 4. INJECT VIDEO FILE ---
            print(f"📂 Injecting Video File: {video_path}")
            await page.set_input_files("input[type='file']", video_path)
            
            print("⏳ Waiting for USA servers to ingest file...")
            await asyncio.sleep(random.uniform(8.0, 12.0)) # Video load hone ka time

            # --- 5. HUMAN TYPING (Title & Description) ---
            print("✍️ Typing Title and Description...")
            # Title Box (Pehla contenteditable)
            title_box = page.locator('#textbox').nth(0)
            await title_box.click()
            await asyncio.sleep(0.5)
            await page.keyboard.press('Control+A')
            await page.keyboard.press('Backspace')
            await asyncio.sleep(1.0)
            
            # YouTube Shorts ke liye chota title nikal rahe hain (Pehli line)
            short_title = caption.split('\n')[0][:90] 
            
            for char in short_title:
                await page.keyboard.type(char)
                await asyncio.sleep(random.uniform(0.02, 0.1))
                
            await asyncio.sleep(1.0)

            # Description Box (Doosra contenteditable)
            desc_box = page.locator('#textbox').nth(1)
            await desc_box.click()
            await asyncio.sleep(0.5)
            await page.keyboard.press('Control+A')
            await page.keyboard.press('Backspace')
            
            # Type full caption in description (Thoda fast)
            await page.keyboard.type(caption, delay=10) 
            await asyncio.sleep(2.0)

            # --- 6. 'NOT FOR KIDS' SETTING ---
            print("👶 Setting 'Not made for kids'...")
            kids_radio = page.locator('tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"]')
            await kids_radio.scroll_into_view_if_needed()
            await kids_radio.click()
            await asyncio.sleep(1.0)

            # --- 7. NEXT, NEXT, NEXT (Bypassing steps) ---
            print("⏭️ Bypassing Checks and Elements...")
            next_btn = page.locator('#next-button')
            
            for _ in range(3): # Teen baar Next dabana padta hai
                await next_btn.click()
                await asyncio.sleep(random.uniform(1.5, 3.0))

            # --- 8. PUBLISH SETTINGS ---
            print("🌍 Setting visibility to PUBLIC...")
            public_radio = page.locator('tp-yt-paper-radio-button[name="PUBLIC"]')
            await public_radio.click()
            await asyncio.sleep(1.0)

            print("🔥 SMASHING THE PUBLISH BUTTON!")
            done_btn = page.locator('#done-button')
            await done_btn.click()

            print("⏳ Waiting for YouTube to process the final publish...")
            await asyncio.sleep(15.0)

            # Dialog band karna (Video published modal)
            try:
                close_btn = page.locator('#close-button').first
                if await close_btn.is_visible():
                    await close_btn.click()
            except:
                pass

            print("\n" + "="*50)
            print("✅ BINGO! YOUTUBE SHORT UPLOADED SUCCESSFULLY!")
            print("="*50 + "\n")

        except Exception as e:
            print(f"❌ YouTube Upload Failed: {e}")
            
        finally:
            await page.close()
            await browser.disconnect()  # 🚨 Browser khula rahega agle uploader ke liye!
            print("🚪 Script Detached gracefully.")

# Sync Wrapper for Manager.py
def upload_video(video_path, caption):
    asyncio.run(run_youtube_uploader(video_path, caption))

# --- QUICK TEST EXECUTION ---
if __name__ == "__main__":
    test_vid = "C:/Users/n/Documents/hotshort/Overnight_Factory/Output/Daniel_Rewards/clip_0_0_71.mp4" # Path adjust kar lena
    test_cap = "Crazy new AI strategy! 🤯\n\n#shorts #entrepreneur #mindset"
    upload_video(test_vid, test_cap)