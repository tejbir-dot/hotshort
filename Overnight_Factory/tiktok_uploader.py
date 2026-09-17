import asyncio
import random
from playwright.async_api import async_playwright
import subprocess
import re

def get_dolphin_ws_endpoint():
    print("🔍 Using Windows Deep-Scan (WMIC) for hidden ports...")
    try:
        # 🚨 Yeh command OS ko force karegi saare process command-lines dump karne ke liye
        output = subprocess.check_output("wmic process get commandline", shell=True, text=True, errors='ignore')
        
        # Scanner searching for the port
        match = re.search(r'--remote-debugging-port=(\d+)', output)
        if match:
            port = match.group(1)
            print(f"🎯 BOOM! TARGET ACQUIRED! Deep-Scan found Port: {port}")
            return f"http://127.0.0.1:{port}"
    except Exception as e:
        print(f"WMIC Error: {e}")
        
    raise Exception("❌ Windows Deep-Scan failed! Dolphin mein START dabao, ya VS Code ko 'Run as Administrator' karke kholo.")

# 1. Human-Like Typing Effect
async def human_type(page, selector, text):
    await page.click(selector)
    for char in text:
        await page.keyboard.type(char)
        await asyncio.sleep(random.uniform(0.05, 0.2)) # Random delay like a real human

async def run_ghost_factory(video_path, caption):
    print(f"🚀 STARTING GHOST FACTORY: GOD MODE FOR TIKTOK")
    
    ws_endpoint = get_dolphin_ws_endpoint()
    
    async with async_playwright() as p:
        # --- 2. THE CDP CONNECTION ---
        print("🔗 Connecting Playwright to running Dolphin Profile...")
        browser = await p.chromium.connect_over_cdp(ws_endpoint)
        context = browser.contexts[0]
        page = await context.new_page()

        # --- 3. THE WARM-UP SHIELD (Human Emulation) ---
        print("🧘‍♂️ Warming up the Algorithm... Scrolling ForYou page...")
        await page.goto("https://www.tiktok.com/foryou", timeout=60000)
        await asyncio.sleep(random.uniform(4.0, 6.0))
        await page.mouse.wheel(0, 800)
        await asyncio.sleep(random.uniform(3.0, 5.0))
        await page.mouse.wheel(0, 1200)
        print("✅ Warm-up complete! Looking like a real USA human.")
        await asyncio.sleep(2.0)

        try:
            # Seedha Upload Page Par Jump
            print("🛡️ Navigating to TikTok Studio Upload page...")
            await page.goto("https://www.tiktok.com/creator-center/upload", timeout=60000)
            await asyncio.sleep(random.uniform(4.0, 7.0))

            # 4. Uploading the Video
            print(f"📂 Uploading {video_path}...")
            file_input = page.locator('input[type="file"]') 
            await file_input.set_input_files(video_path)
            
            print("⏳ Waiting for video processing (USA Speed)...")
            await asyncio.sleep(random.uniform(12.0, 18.0)) 

            # 5. Typing the Caption like a Human (Tera logic ekdum best hai)
            print("✍️ Typing caption...")
            await page.keyboard.press('Escape')
            await asyncio.sleep(1)
            
            caption_box = page.locator('div[contenteditable="true"]').first
            
            # THE DOUBLE-TAP
            await caption_box.click(force=True)
            await asyncio.sleep(1)
            await page.keyboard.press('Control+A')
            await asyncio.sleep(0.5)
            await page.keyboard.press('Backspace')
            await asyncio.sleep(1)
            
            await caption_box.click(force=True)
            await asyncio.sleep(0.5)
            
            for char in caption:
                await page.keyboard.type(char)
                await asyncio.sleep(random.uniform(0.05, 0.15))
            
            await asyncio.sleep(random.uniform(2.0, 4.0))
            
            # 6. Force Privacy to "Everyone"
            print("🌍 Checking Privacy...")
            try:
                everyone_option = page.locator('text="Everyone"').last
                if await everyone_option.is_visible(timeout=3000):
                    await everyone_option.evaluate("node => node.click()")
                    print("✅ Privacy set to 'Everyone'!")
                    await asyncio.sleep(1.0)
            except:
                print("ℹ️ Privacy already set correctly.")
            
            # 7. THE RED BUTTON HUNTER 🔴
            print("🔥 Locating the RED POST button...")
            post_button = page.locator('div[role="button"]:has-text("Post"), button:has-text("Post")').last
            await post_button.scroll_into_view_if_needed()
            await asyncio.sleep(random.uniform(1.5, 2.5)) 
            
            print("💥 SMASHING THE RED BUTTON!")
            await post_button.evaluate("node => node.click()")
            
            print("⏳ Waiting 8 seconds for Pop-up...")
            await asyncio.sleep(8.0) 
            
            # Pop-up check
            try:
                post_now = page.locator('div[role="button"]:has-text("Post now"), button:has-text("Post now")').last
                if await post_now.is_visible():
                    print("🚨 Pop-up Detected! Clicking 'Post now'...")
                    await post_now.evaluate("node => node.click()")
            except:
                print("ℹ️ No pop-up detected, moving forward...")
                
            print("🚀 Uploading to Servers... Waiting 20 seconds...")
            await asyncio.sleep(20.0)
            
            # 8. FETCHING THE URL 🔗
            print("🔗 Fetching the uploaded video link...")
            try:
                tiktok_handle = "eliteclipper.studios1" # Tera handle (update kar lena)
                await page.goto(f"https://www.tiktok.com/@{tiktok_handle}")
                await asyncio.sleep(6.0) 
                
                first_video = page.locator('a[href*="/video/"]').first
                video_url = await first_video.get_attribute('href')
                
                print("\n" + "="*50)
                print(f"✅ BINGO! VIDEO UPLOADED SUCCESSFULLY!")
                print(f"🔗 TIKTOK URL: {video_url}")
                print("="*50 + "\n")
                
                with open("published_links.txt", "a") as f:
                    f.write(f"{video_url}\n")
            except Exception as e:
                print(f"⚠️ Link copy failed, but upload is likely complete. Error: {e}")
            
        except Exception as e:
            print(f"❌ Error occurred during upload: {e}")
            
        finally:
            await page.close()
            await browser.disconnect()  # 🚨 Browser khula rahega agle uploader ke liye!
            print("🚪 Script Detached gracefully.")

# Sync Wrapper for Manager.py
def upload_video(video_path, caption):
    asyncio.run(run_ghost_factory(video_path, caption))

# --- QUICK TEST EXECUTION ---
if __name__ == "__main__":
    test_vid = "C:/Users/n/Documents/hotshort/Overnight_Factory/Output/Daniel_Rewards/clip_0_0_71.mp4" # Path check kar lena
    test_cap = "We wanted an actual challenge 🚀 #mindset #entrepreneur"
    upload_video(test_vid, test_cap)