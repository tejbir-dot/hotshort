import asyncio
import json
from playwright.async_api import async_playwright

async def run_youtube_uploader(video_path, caption):
    print("🚀 Starting YouTube Ghost Factory...")
    
    async with async_playwright() as p:
        # Browser Start (Headless=False taaki nazaara dikhe)
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()

        # 1. 🍪 Injecting Golden Ticket (Cookies)
        print("🍪 Injecting YouTube Cookies...")
        try:
            import os
            cookie_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'youtube_cookie.json')
            with open(cookie_path, 'r') as f:
                raw_cookies = json.load(f)
                
                clean_cookies = []
                for cookie in raw_cookies:
                    # 🧹 CTO AUTO-CLEANER: Fix sameSite values
                    if 'sameSite' in cookie:
                        if cookie['sameSite'] not in ['Strict', 'Lax', 'None']:
                            if cookie['sameSite'] == 'no_restriction':
                                cookie['sameSite'] = 'None'
                            else:
                                del cookie['sameSite'] # Delete if null or invalid
                    
                    # Remove extra keys that Playwright hates
                    for bad_key in ['hostOnly', 'session', 'storeId', 'id']:
                        if bad_key in cookie:
                            del cookie[bad_key]
                            
                    clean_cookies.append(cookie)

                await context.add_cookies(clean_cookies)
            print("✅ Cookies Cleaned & Injected! System Hacked In.")
        except Exception as e:
            print(f"❌ Cookie error: {e}")
            return

        page = await context.new_page()

        try:
            # 2. 🛡️ Navigate to YouTube Studio
            print("🛡️ Navigating to YouTube Studio...")
            await page.goto("https://studio.youtube.com/", timeout=60000)
            await asyncio.sleep(5.0)
            
            # 🛠️ THE NEW CTO BYPASS: Waking up the Upload Box
            print("🖱️ Clicking 'Upload' icon to wake up the system...")
            try:
                # Top right upload arrow icon ko click karega
                await page.locator('#upload-icon').click(timeout=5000)
            except:
                # Agar naya channel hai toh beech wale 'Upload videos' button ko click karega
                await page.locator('#upload-button').click()
                
            await asyncio.sleep(3.0) # Upload box khulne ka wait karega

            # 3. 📂 Direct File Injection
            print(f"📂 Uploading Video directly to server: {video_path}")
            await page.set_input_files("input[type='file']", video_path)
            
            print("⏳ Waiting for upload page to load (10 seconds)...")
            await asyncio.sleep(10.0)

            # 4. ✍️ Typing Title / Caption
            print("✍️ Typing Title & Hashtags...")
            title_box = page.locator('#title-textarea #textbox')
            await title_box.click(force=True)
            await title_box.clear() # Default video naam hatane ke liye
            await title_box.type(caption, delay=100)
            await asyncio.sleep(2.0)

            # 5. 👶 The Kids Policy Check (Bohot zaroori)
            print("🛡️ Selecting 'No, it's not made for kids'...")
            kids_radio = page.locator('tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"]')
            await kids_radio.scroll_into_view_if_needed()
            await kids_radio.click(force=True)
            await asyncio.sleep(2.0)

            # 6. ⏩ Skipping extra checks (Click NEXT 3 times)
            print("⏩ Bypassing extra checks...")
            for i in range(3):
                next_btn = page.locator('#next-button')
                await next_btn.click(force=True)
                await asyncio.sleep(1.5)

            # 7. 🌍 Privacy to Public
            print("🌍 Forcing Privacy to 'Public'...")
            public_radio = page.locator('tp-yt-paper-radio-button[name="PUBLIC"]')
            await public_radio.click(force=True)
            await asyncio.sleep(2.0)

            # 8. 🔥 THE LAUNCH BUTTON
            print("🔥 Clicking PUBLISH button...")
            publish_btn = page.locator('#done-button')
            await publish_btn.click(force=True)

            print("⏳ Uploading to USA Servers... Waiting 20 seconds...")
            await asyncio.sleep(20.0)

            print("🏆 BOOM! Video is LIVE on YouTube Shorts USA!")

        except Exception as e:
            print(f"❌ Error occurred during YouTube upload: {e}")

        finally:
            await browser.close()
            print("🚪 Browser closed securely.")

# --- EXECUTION (Test Fire) ---
if __name__ == "__main__":
    # Yahan test karne ke liye apni koi video ka path daal de
    test_video = r"C:\Users\n\Documents\hotshort\Overnight_Factory\Output\Daniel_Rewards\clip_0_0_71.mp4"
    test_caption = "Crazy facts you didn't know! 🤯 #shorts #usa #viral"
    
    asyncio.run(run_youtube_uploader(test_video, test_caption))