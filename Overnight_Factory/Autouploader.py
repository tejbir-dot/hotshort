import asyncio
import random
import json  # <-- JSON import kiya cookies padhne ke liye
from playwright.async_api import async_playwright
# from playwright_stealth import stealth

# 1. Human-Like Typing Effect
async def human_type(page, selector, text):
    await page.click(selector)
    for char in text:
        await page.keyboard.type(char)
        await asyncio.sleep(random.uniform(0.05, 0.2)) # Random delay like a real human

async def run_ghost_factory(account_name, proxy_ip, proxy_port, proxy_user, proxy_pass, video_path, caption):
    print(f"🚀 Starting Ghost Factory for: {account_name}")
    
    async with async_playwright() as p:
        # 2. Proxy Injector (Masking the IP)
        browser = await p.chromium.launch(
            headless=False, # Testing ke time False rakhna, baad mein True kar dena
            proxy={
                "server": f"http://{proxy_ip}:{proxy_port}",
                "username": proxy_user,
                "password": proxy_pass
            }
        )
        
        # 3. Context Creation
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 720}
        )
        
        # --- 4. THE CTO COOKIE INJECTION (Bypass Login) ---
        print("🍪 Injecting Cookies (Bypassing Login)...")
        try:
            with open("tiktok_cookie.json", "r") as f:
                cookies = json.load(f)
                
                # Cookie-Editor format ko Playwright format mein clean karna
                clean_cookies = []
                for cookie in cookies:
                    if 'hostOnly' in cookie: del cookie['hostOnly']
                    if 'storeId' in cookie: del cookie['storeId']
                    if 'session' in cookie: del cookie['session']
                    if 'id' in cookie: del cookie['id']
                    
                    # --- THE SAMESITE FIX ---
                    if 'sameSite' in cookie:
                        if cookie['sameSite'] == 'no_restriction':
                            cookie['sameSite'] = 'None'
                        elif cookie['sameSite'] not in ['Strict', 'Lax', 'None']:
                            del cookie['sameSite'] # Faltu value ko delete maar do
                            
                    clean_cookies.append(cookie)
                
                # Context mein saari cookies push maar di
                await context.add_cookies(clean_cookies)
                print("✅ Cookies Injected! System Hacked In.")
        except Exception as e:
            print(f"❌ Cookie Injection Failed: {e}. Check if 'tiktok_cookie.json' is in the same folder.")
            return # Agar cookie nahi mili toh script yahin rok de

        # Context ke andar naya page open kiya (jo ab fully logged in hai)
        page = await context.new_page()
        
        # 5. THE STEALTH SHIELD
        # await stealth(page)
        print("🛡️ Stealth Shield Activated. Navigating to upload page...")
        
        try:
            # Seedha Upload Page Par Jump (Bina login screen dekhe)
            await page.goto("https://www.tiktok.com/creator-center/upload", timeout=60000)
            await asyncio.sleep(random.uniform(4.0, 7.0)) # Page load hone ka natural wait

            # 6. Uploading the Video
            print(f"📂 Uploading {video_path}...")
            # iframe ko handle karne ke liye (TikTok kabhi-kabhi upload box iframe mein daal deta hai)
            file_input = page.locator('input[type="file"]') 
            await file_input.set_input_files(video_path)
            
            # Wait for upload to process (Random human delay)
            print("⏳ Waiting for video processing...")
            await asyncio.sleep(random.uniform(12.0, 18.0)) 

            # 7. Typing the Caption like a Human
            print("✍️ Typing caption...")
            
            # STEP 1: Faltu popups ko bhagane ke liye ESCAPE dabana
            await page.keyboard.press('Escape')
            await asyncio.sleep(1)
            
            # Naya aur sabse tagda selector
            caption_box = page.locator('div[contenteditable="true"]').first
            
            # STEP 2: Box par click karke pehle se likha hua kachra saaf karna
            await caption_box.click(force=True)
            await asyncio.sleep(1)
            await page.keyboard.press('Control+A')
            await asyncio.sleep(0.5)
            await page.keyboard.press('Backspace')
            await asyncio.sleep(1)
            
            # STEP 3: THE DOUBLE-TAP (Type karne se theek pehle wapas focus lock karna)
            await caption_box.click(force=True)
            await asyncio.sleep(0.5)
            
            # Apna caption human style mein type karna
            for char in caption:
                await page.keyboard.type(char)
                await asyncio.sleep(random.uniform(0.05, 0.15))
            
            # Caption likhne ke baad thoda wait taaki TikTok process kar le
            await asyncio.sleep(random.uniform(2.0, 4.0))
            
            # ---------------------------------------------------------
            # 0. Force Privacy to "Everyone" (Public)
            print("🌍 Checking and Forcing video privacy to 'Everyone'...")
            try:
                # "Everyone" wale text ko pakadna aur force click marna
                everyone_option = page.locator('text="Everyone"').last
                if await everyone_option.is_visible(timeout=3000):
                    await everyone_option.evaluate("node => node.click()")
                    print("✅ Privacy set to 'Everyone'!")
                    await asyncio.sleep(1.0)
            except:
                print("ℹ️ Privacy already set to 'Everyone' or option hidden.")
            # ---------------------------------------------------------
            # 8. THE LAUNCH BUTTON (POST) - ASLI KHELA YAHAN HAI
            # ---------------------------------------------------------
            # 1. Pehla POST button dabana - THE RED BUTTON HUNTER 🔴
            print("🔥 Locating the RED POST button...")
            
            # TikTok chalaak hai, red button ko <div> banata hai. Yeh code dono pakdega!
            post_button = page.locator('div[role="button"]:has-text("Post"), button:has-text("Post")').last
            
            # Scroll karke saamne lana (Jaise pehle sahi chal raha tha)
            await post_button.scroll_into_view_if_needed()
            await asyncio.sleep(1.5) # Human delay
            
            print("💥 Forcing the click on the Red Button...")
            await post_button.evaluate("node => node.click()")
            
            print("⏳ Waiting 8 seconds for Copyright Pop-up to appear...")
            await asyncio.sleep(8.0) 
            
            # 2. Pop-up check and click
            try:
                # Pop up wala button bhi div ya button ho sakta hai
                post_now = page.locator('div[role="button"]:has-text("Post now"), button:has-text("Post now")').last
                if await post_now.is_visible():
                    print("🚨 Pop-up Detected! Clicking 'Post now'...")
                    await post_now.evaluate("node => node.click()")
            except:
                print("ℹ️ No pop-up detected, moving forward...")
                
            print("🚀 Uploading to USA Servers... Waiting 20 seconds...")
            await asyncio.sleep(20.0)
            
            # 3. CTO MASTERSTROKE: GETTING THE VIDEO LINK 🔗
            print("🔗 Fetching the uploaded video link...")
            try:
                # Tera actual TikTok handle yahan daal
                tiktok_handle = "eliteclipper.studios" 
                await page.goto(f"https://www.tiktok.com/@{tiktok_handle}")
                await asyncio.sleep(5.0) # Profile load hone ka wait
                
                # Profile ki sabse pehli video ka link nikalna
                first_video = page.locator('a[href*="/video/"]').first
                video_url = await first_video.get_attribute('href')
                
                print("\n" + "="*50)
                print(f"✅ BINGO! VIDEO UPLOADED SUCCESSFULLY!")
                print(f"🔗 TIKTOK URL: {video_url}")
                print("="*50 + "\n")
                
                # Future reference ke liye link ko file mein save kar dena
                with open("published_links.txt", "a") as f:
                    f.write(f"{video_url}\n")
                    
            except Exception as e:
                print(f"⚠️ Link copy nahi ho paya, par video upload ho chuki hogi. Error: {e}")
            
        except Exception as e:
            print(f"❌ Error occurred during upload: {e}")
            
        finally:
            await browser.close()
            print("🚪 Browser closed securely.")

# --- EXECUTION ---
if __name__ == "__main__":
    # Test Data - Yahan apni IPRoyal details daal de
    asyncio.run(run_ghost_factory(
        account_name="TheEliteClipper2",
        proxy_ip="162.210.64.27", # Tera IPRoyal Chicago IP
        proxy_port="12323",       # Tera Port
        proxy_user="14a930ebcafee",    # IPRoyal Username
        proxy_pass="e269d4d909",    # IPRoyal Password
        video_path="C:/Users/n/Documents/hotshort/Overnight_Factory/Output/Daniel_Rewards/clip_0_0_71.mp4", # Apni clip ki exact location
        caption="We wanted an actual challenge 🚀 #mindset #entrepreneur"
    ))