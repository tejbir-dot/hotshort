import asyncio
import random
import requests
from playwright.async_api import async_playwright

# ⚙️ CTO CONFIG: Teri Dolphin ID yahan daal
DOLPHIN_PROFILE_ID = "864437795"  # Same ID jo TikTok me daali thi
  # Same ID jo TikTok me daali thi

def get_dolphin_ws_endpoint():
    """Dolphin Anty API se active browser ka connection port nikalta hai"""
    print(f"🔌 Pinging Dolphin Anty for Profile ID: {DOLPHIN_PROFILE_ID}...")
    url = f"http://localhost:3001/v1.0/browser_profiles/{DOLPHIN_PROFILE_ID}/start?automation=1"
    
    try:
        response = requests.get(url)
        data = response.json()
        
        if data.get("success"):
            ws_url = data["automation"]["wsEndpoint"]
            print(f"✅ Dolphin Hijacked! WS Endpoint: {ws_url}")
            return ws_url
        else:
            raise Exception(f"Dolphin connection failed: {data}")
    except Exception as e:
        print(f"❌ ERROR: Dolphin Anty open nahi hai ya ID galat hai! Error: {e}")
        return None

async def run_youtube_uploader(video_path, caption):
    print(f"🚀 STARTING GHOST FACTORY: GOD MODE FOR YOUTUBE")
    
    ws_endpoint = get_dolphin_ws_endpoint()
    if not ws_endpoint:
        return
    
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
            # 🚨 DISCONNECTING (Not Closing) taaki Dolphin profile safe rahe
            await page.close()
            await browser.disconnect()
            print("🚪 YouTube Script Detached. Dolphin profile still running safely.")

# Sync Wrapper for Manager.py
def upload_video(video_path, caption):
    asyncio.run(run_youtube_uploader(video_path, caption))

# --- QUICK TEST EXECUTION ---
if __name__ == "__main__":
    test_vid = "C:/Users/n/Documents/hotshort/Overnight_Factory/Output/Daniel_Rewards/clip_0_0_71.mp4" # Path adjust kar lena
    test_cap = "Crazy new AI strategy! 🤯\n\n#shorts #entrepreneur #mindset"
    upload_video(test_vid, test_cap)