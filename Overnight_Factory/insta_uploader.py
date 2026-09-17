import asyncio
import random
from playwright.async_api import async_playwright
import psutil
import re

def get_dolphin_ws_endpoint():
    print("🔍 Scanning OS for ANY hidden debugging port...")
    for p in psutil.process_iter(['cmdline']): # Naam ki condition hata di
        try:
            cmd_args = p.info.get('cmdline') or []
            # List ko string banaya taaki dhoondhne mein aasaani ho
            cmd = " ".join([str(arg) for arg in cmd_args if arg is not None])
            
            # Agar cmd mein remote debugging port hai (chahe process ka naam kuch bhi ho)
            if '--remote-debugging-port=' in cmd:
                match = re.search(r'--remote-debugging-port=(\d+)', cmd)
                if match:
                    port = match.group(1)
                    print(f"🎯 TARGET ACQUIRED! Hidden Browser running on Port: {port}")
                    return f"http://127.0.0.1:{port}"
        except Exception:
            pass # Access denied wale processes ko ignore karo
            
    raise Exception("❌ Koi browser running nahi hai! Pehle Dolphin mein START click kar.")

async def run_insta_uploader(video_path, caption):
    print(f"🚀 STARTING GHOST FACTORY: GOD MODE FOR INSTAGRAM")
    
    ws_endpoint = get_dolphin_ws_endpoint()
    
    async with async_playwright() as p:
        # --- 1. THE CDP CONNECTION ---
        print("🔗 Connecting Playwright to running Dolphin Profile...")
        browser = await p.chromium.connect_over_cdp(ws_endpoint)
        context = browser.contexts[0]
        page = await context.new_page()

        # --- 2. WARM-UP SHIELD (Instagram Homepage Scroll) ---
        print("🧘‍♂️ Warming up the Algorithm... Scrolling IG Feed...")
        await page.goto("https://www.instagram.com/", timeout=60000)
        await asyncio.sleep(random.uniform(4.0, 7.0))
        
        # Pop-up Check: "Turn on Notifications" ya "Save Info"
        try:
            not_now_btn = page.get_by_role("button", name="Not Now").first
            if await not_now_btn.is_visible(timeout=3000):
                print("🛡️ Bypassing 'Not Now' popup...")
                await not_now_btn.click()
                await asyncio.sleep(2.0)
        except:
            pass

        # Human-like scroll
        await page.mouse.wheel(0, 800)
        await asyncio.sleep(random.uniform(2.0, 4.0))
        await page.mouse.wheel(0, 1200)
        print("✅ Warm-up complete! Looking like a real USA scroller.")
        await asyncio.sleep(2.0)

        # --- 3. TRIGGERING UPLOAD FLOW ---
        print("🖱️ Clicking 'Create' button...")
        try:
            await page.locator("svg[aria-label='New post']").click()
            await asyncio.sleep(random.uniform(1.5, 3.0))
            
            # Select 'Post' from dropdown if it appears
            dropdown_post = page.get_by_text("Post", exact=True)
            if await dropdown_post.is_visible():
                await dropdown_post.click()
            await asyncio.sleep(random.uniform(2.0, 4.0))
        except Exception as e:
            print("⚠️ Create button UI changed, trying fallback...")

        # --- 4. INJECT VIDEO FILE ---
        print(f"📂 Injecting Video File: {video_path}...")
        await page.set_input_files("input[type='file']", video_path)
        print("⏳ Waiting for IG servers to process media...")
        await asyncio.sleep(random.uniform(5.0, 8.0))

        # --- 5. BYPASSING CROP & FILTER SCREENS ---
        print("⏭️ Bypassing Crop & Filter screens...")
        try:
            # First Next (Crop screen) - Reels usually require clicking "Next" to continue
            next_btn_1 = page.get_by_role("button", name="Next")
            if await next_btn_1.is_visible():
                await next_btn_1.click()
                await asyncio.sleep(random.uniform(2.0, 3.5))
            
            # Second Next (Filter screen)
            next_btn_2 = page.get_by_role("button", name="Next")
            if await next_btn_2.is_visible():
                await next_btn_2.click()
                await asyncio.sleep(random.uniform(2.0, 4.0))
        except:
            print("⚠️ Next buttons not found, attempting to proceed...")

        # --- 6. HUMAN TYPING (Caption) ---
        print("✍️ Typing Caption & Hashtags like a human...")
        try:
            caption_box = page.get_by_role("textbox")
            await caption_box.click()
            await asyncio.sleep(1.0)
            
            for char in caption:
                await page.keyboard.type(char)
                await asyncio.sleep(random.uniform(0.02, 0.1))
                
            await asyncio.sleep(random.uniform(2.0, 3.0))
        except Exception as e:
            print(f"⚠️ Caption box error: {e}")

        # --- 7. THE SHARE BUTTON ---
        print("🔥 SMASHING THE SHARE BUTTON!")
        try:
            await page.get_by_role("button", name="Share").click()
        except:
            print("⚠️ Share button failed. Trying alternative selector...")
            await page.locator("text='Share'").last.click()

        print("⏳ Waiting 45 seconds for IG to process the Reel upload...")
        await asyncio.sleep(45.0) 
        
        print("\n" + "="*50)
        print("✅ BINGO! INSTAGRAM REEL UPLOADED SUCCESSFULLY!")
        print("="*50 + "\n")
        
        await page.close()
        await browser.disconnect()  # 🚨 Browser khula rahega agle uploader ke liye!
        print("🚪 Script Detached gracefully.")

# Sync wrapper for Manager.py
def upload_video(video_path, caption):
    asyncio.run(run_insta_uploader(video_path, caption))

# --- QUICK TEST EXECUTION ---
if __name__ == "__main__":
    test_vid = r"C:\Users\n\Documents\hotshort\Overnight_Factory\Output\Daniel_Rewards\clip_0_0_71.mp4" # Path adjust kar lena
    test_cap = "Crazy facts you didn't know! 🤯\n\n#shorts #facts #viral"
    upload_video(test_vid, test_cap)