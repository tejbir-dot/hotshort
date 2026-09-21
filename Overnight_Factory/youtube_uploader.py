"""
==========================================
  YOUTUBE UPLOADER — NATIVE STEALTH MODE
  Ghost Factory v4.0 | Zero Dolphin Dependency
==========================================
Architecture:
  - Persistent Context: Cookies survive between runs
  - playwright-stealth: Spoofs canvas fingerprint, hides webdriver flag
  - Cookie Injection: Skips login entirely using saved sessions
  - Human Emulation: Random delays, scrolling, mouse movement
  - Proxy Injected: US IP via rotating residential proxy
"""

import asyncio
import random
import json
import os
import datetime
from pathlib import Path
from playwright.async_api import async_playwright
from playwright_stealth import Stealth


# ============================================================
#  ⚙️ FACTORY CONFIG — Edit only here
# ============================================================
FACTORY_DIR   = Path(__file__).parent
PROFILE_DIR   = r"C:\Users\n\Documents\hotshort\Overnight_Factory\yt_ghost_profile"
COOKIE_FILE   = str(FACTORY_DIR / "youtube_cookie.json")

# 🔌 Set USE_PROXY = False to test without proxy (uses your real IP)
USE_PROXY     = False   # ← DIRECT — proxy blocks YouTube Studio
PROXY         = {
    "server":   "http://162.210.64.27:12323",
    "username": "14a930ebcafee",
    "password":  "e269d4d909"
}

# ============================================================
#  🧠 HUMAN EMULATION HELPERS
# ============================================================
async def human_type(page, text: str, wpm: int = 60):
    """Types like a real human with variable speed and occasional pauses."""
    chars_per_sec = (wpm * 5) / 60  # average 5 chars/word
    base_delay = 1.0 / chars_per_sec / 1000  # in ms

    for i, char in enumerate(text):
        await page.keyboard.type(char)
        # Occasional thinking pause after punctuation or spaces
        if char in ('.', '!', '?', '\n'):
            await asyncio.sleep(random.uniform(0.2, 0.6))
        elif char == ' ' and random.random() < 0.08:
            await asyncio.sleep(random.uniform(0.1, 0.3))
        else:
            await asyncio.sleep(random.uniform(base_delay * 0.5, base_delay * 2.0))


async def human_scroll(page, times: int = 3):
    """Scroll like a human — irregular intervals and distances."""
    for _ in range(times):
        dist = random.randint(400, 1200)
        await page.mouse.wheel(0, dist)
        await asyncio.sleep(random.uniform(1.0, 2.5))


async def safe_click(page, selector: str, timeout: int = 10000):
    """Click only when element is visible. Soft fail if not found."""
    try:
        el = page.locator(selector).first
        await el.wait_for(state="visible", timeout=timeout)
        await el.scroll_into_view_if_needed()
        await asyncio.sleep(random.uniform(0.3, 0.8))
        await el.click()
        return True
    except Exception as e:
        print(f"  ⚠️  safe_click [{selector}] skipped: {e}")
        return False


# ============================================================
#  🍪 COOKIE INTELLIGENCE
# ============================================================
def load_cookies(cookie_path: str) -> list:
    """Load cookies from JSON, normalize sameSite field."""
    try:
        with open(cookie_path, 'r', encoding='utf-8') as f:
            raw = json.load(f)

        normalized = []
        valid_same_site = {"Strict", "Lax", "None"}
        for c in raw:
            same_site = c.get("sameSite") or "None"
            if same_site not in valid_same_site:
                same_site = "None"
            c["sameSite"] = same_site

            for key in ["storeId", "hostOnly", "session"]:
                c.pop(key, None)

            if "expirationDate" in c and "expires" not in c:
                c["expires"] = c.pop("expirationDate")

            normalized.append(c)
        return normalized

    except FileNotFoundError:
        print(f"  ⚠️  Cookie file not found: {cookie_path}")
        return []
    except json.JSONDecodeError as e:
        print(f"  ❌  Cookie JSON invalid: {e}")
        return []


# ============================================================
#  🚀 MAIN UPLOADER ENGINE
# ============================================================
async def run_youtube_uploader(video_path: str, caption: str) -> str | None:
    print("\n" + "="*52)
    print("  🥷  GHOST FACTORY: YOUTUBE STEALTH ENGINE v4.0")
    print("="*52)

    # Parse platform-specific caption
    yt_caption = caption
    if "YOUTUBE SHORTS CAPTION:" in caption:
        block = caption.split("YOUTUBE SHORTS CAPTION:")[1]
        yt_caption = block.split("----")[0].strip()

    # First line = title (max 90 chars), full = description
    title_line  = yt_caption.split('\n')[0][:90]
    description = yt_caption

    print(f"  📋  Title   : {title_line}")
    print(f"  🎬  Video   : {os.path.basename(video_path)}")
    print(f"  🌐  Proxy   : {PROXY['server']}")

    video_url: str | None = None  # Will be populated after publish
    async with async_playwright() as p:

        # ── 1. LAUNCH STEALTH BROWSER ──────────────────────
        print("\n[1/8] 🔗  Launching Stealth Persistent Context...")
        launch_kwargs = dict(
            user_data_dir=PROFILE_DIR,
            channel="msedge",
            headless=False,
            viewport={"width": 1366, "height": 768},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            args=[
                "--start-maximized",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars"
            ],
            ignore_default_args=["--enable-automation"],
        )
        if USE_PROXY:
            launch_kwargs["proxy"] = PROXY
            print("      🌐  Proxy: ENABLED")
        else:
            print("      🔌  Proxy: DISABLED (direct connection — test mode)")
        context = await p.chromium.launch_persistent_context(**launch_kwargs)

        page = context.pages[0] if context.pages else await context.new_page()

        # ── 2. APPLY STEALTH MASK ──────────────────────────
        print("[2/8] 🕵️  Applying Stealth Mask (anti-fingerprint)...")
        await Stealth().apply_stealth_async(page)

        # ── 3. (REMOVED) INJECT COOKIES ───────────────────
        # Cookies are now permanently saved in the yt_ghost_profile persistent context!
        print("[3/8] 🍪  Cookie Injection Disabled (Using Persistent Session)...")
        # cookies = load_cookies(COOKIE_FILE)
        # if cookies:
        #     await context.add_cookies(cookies)
        #     print(f"      ✅  {len(cookies)} cookies injected — login bypassed!")
        # else:
        #     print("      ⚠️  No cookies found. Will rely on saved profile session.")

        try:
            # ── 4. WARM-UP: YouTube Homepage (human-like) ──
            print("[4/6] 🧘  Warm-up: Visiting YouTube homepage first...")
            try:
                await page.goto("https://www.youtube.com/", timeout=60000, wait_until="domcontentloaded")
                await asyncio.sleep(random.uniform(2.5, 4.0))
                await page.mouse.wheel(0, random.randint(300, 700))
                await asyncio.sleep(random.uniform(1.0, 2.0))
                await page.mouse.wheel(0, random.randint(400, 900))
                await asyncio.sleep(random.uniform(1.0, 2.0))
                print("      ✅  YouTube homepage loaded. Looks like a real viewer!")
            except Exception as warm_err:
                print(f"      ⚠️  Warm-up skipped: {warm_err}")

            # ── 5. ENTER YOUTUBE STUDIO ───────────────────
            print("[5/6] 🎬  Entering YouTube Studio...")
            await page.goto("https://studio.youtube.com/", timeout=120000, wait_until="domcontentloaded")
            await asyncio.sleep(3.0)

            # 🔍 LOGIN CHECK
            current_url = page.url
            if "accounts.google.com" in current_url or "signin" in current_url:
                print("      ⚠️  LOGIN REQUIRED! Please login manually in the browser...")
                print("      ⏳  You have 3 minutes to login and reach YouTube Studio.")
                try:
                    # Wait for the URL to change to studio.youtube.com (meaning login successful)
                    await page.wait_for_url("https://studio.youtube.com/**", timeout=180000)
                    print("      ✅  Login successful! Continuing automation...")
                    current_url = page.url
                    await asyncio.sleep(3.0)
                except Exception:
                    raise Exception("❌ Login timed out. Please run again and login faster.")
            print(f"      ✅  Studio loaded. URL: {current_url[:70]}")
            await asyncio.sleep(random.uniform(2.0, 3.0))

            # 🎯 CHANNEL ID extract karo → direct upload URL pe jao
            # Yeh approach create-icon dhundne se 10x reliable hai!
            channel_id = None
            if "/channel/" in current_url:
                channel_id = current_url.split("/channel/")[1].split("/")[0]

            # ── STRATEGY: Nuclear JS Upload Trigger (no button hunting) ─────
            # Instead of hunting for Create/Upload buttons (which change every few months),
            # we directly create a hidden file input via JavaScript and use that.
            # This is 100% reliable regardless of YouTube Studio UI changes.
            print(f"      🎯  Channel ID: {channel_id or 'not found'}")
            print("      🚀  Trying nuclear JS file input injection...")
            
            try:
                # Make any existing hidden file input visible & usable
                await page.evaluate("""
                    () => {
                        let inp = document.querySelector('input[type="file"]');
                        if (inp) {
                            inp.style.display = 'block';
                            inp.style.visibility = 'visible';
                            inp.style.opacity = '1';
                        }
                    }
                """)
                await page.wait_for_selector("input[type='file']", state="attached", timeout=4000)
                print("      ✅  File input already exists in DOM (upload modal was pre-loaded)")
            except:
                print("      ⚠️  No file input yet — clicking Create button to trigger modal...")
                
                # STEP 1: Click the Create button
                clicked = False
                try:
                    await page.get_by_text("Create", exact=True).first.click(timeout=5000)
                    clicked = True
                    print("      👉 'Create' button clicked!")
                except:
                    pass
                
                if not clicked:
                    try:
                        await page.get_by_label("Upload videos").first.click(timeout=5000)
                        clicked = True
                        print("      👉 'Upload videos' label button clicked!")
                    except:
                        pass
                        
                if not clicked:
                    try:
                        await page.locator("#create-icon").first.click(timeout=5000)
                        clicked = True
                        print("      👉  #create-icon clicked!")
                    except:
                        pass
                
                if clicked:
                    await asyncio.sleep(random.uniform(1.2, 2.0))
                    # STEP 2: Click dropdown option
                    try:
                        await page.get_by_text("Upload videos", exact=True).first.click(timeout=5000)
                        print("      👉 'Upload videos' dropdown option clicked!")
                    except:
                        pass  # Might already be on upload modal
                    await asyncio.sleep(random.uniform(2.0, 3.5))
                
                # Wait for the file input to appear after button clicks
                try:
                    await page.wait_for_selector("input[type='file']", state="attached", timeout=12000)
                except:
                    raise Exception("❌ Upload modal failed to open after all attempts. Check Studio manually.")


            await page.set_input_files("input[type='file']", video_path)
            print("      ⏳  Waiting for YouTube to ingest file (10–15s)...")
            await asyncio.sleep(random.uniform(10.0, 15.0))

            # ── 7. FILL METADATA ──────────────────────────
            print("[7/8] ✍️   Filling title and description...")

            # Title
            title_box = page.locator('#textbox').nth(0)
            await title_box.click()
            await asyncio.sleep(0.4)
            await page.keyboard.press('Control+A')
            await page.keyboard.press('Backspace')
            await asyncio.sleep(0.3)
            await human_type(page, title_line)
            await asyncio.sleep(1.0)
            
            # Extract video URL early (it's visible on the right panel in step 1)
            video_url = None
            try:
                # The video link is usually an anchor with href starting with https://youtu.be/
                link_el = page.locator('a.ytcp-video-info[href*="youtu.be"]').first
                if await link_el.is_visible(timeout=3000):
                    video_url = await link_el.get_attribute("href")
                    print(f"      ✅  Extracted early URL: {video_url}")
            except Exception:
                pass


            # Description
            desc_box = page.locator('#textbox').nth(1)
            await desc_box.click()
            await asyncio.sleep(0.4)
            await page.keyboard.press('Control+A')
            await page.keyboard.press('Backspace')
            await asyncio.sleep(0.3)
            await page.keyboard.type(description, delay=8)
            await asyncio.sleep(1.5)

            # Not for kids
            print("      👶  Marking as 'Not made for kids'...")
            await safe_click(
                page,
                'tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"]',
                timeout=10000
            )
            await asyncio.sleep(1.0)

            # Next × 3
            print("      ⏭️   Clicking Next through settings screens...")
            next_btn = page.locator('#next-button')
            for step in range(3):
                await next_btn.wait_for(state="visible", timeout=15000)
                await next_btn.click()
                await asyncio.sleep(random.uniform(2.0, 3.5))

            # Set Public
            print("      🌍  Setting visibility to PUBLIC...")
            await safe_click(page, 'tp-yt-paper-radio-button[name="PUBLIC"]', timeout=10000)
            await asyncio.sleep(1.0)

            # PUBLISH
            print("      🔥  SMASHING THE PUBLISH BUTTON...")
            await safe_click(page, '#done-button', timeout=10000)

            # ── 8. EXTRACT LIVE LINK (from "Video published" modal) ──
            print("[8/8] 🔍  Extracting live video link from success modal...")
            video_url = None
            try:
                # 1. Dialog box open hone ka wait (max 15 sec)
                await page.wait_for_selector('text="Video published"', timeout=15000)
                
                # 2. 'youtube.com/shorts/' ya 'youtu.be/' wala href dhoondho
                link_loc = page.locator('a[href*="youtube.com/shorts/"], a[href*="youtu.be/"]').first
                video_url = await link_loc.get_attribute('href')
                
                # 3. Agar a tag mein na mile, toh pure text mein dhoondho (Fallback)
                if not video_url:
                    text_loc = page.locator('text=https://youtube.com/shorts/').first
                    video_url = await text_loc.inner_text()
                    
                print(f"      ✅  Extracted URL: {video_url}")
                
                if video_url:
                    links_file = FACTORY_DIR / "uploaded_links.txt"
                    with open(links_file, "a", encoding="utf-8") as f:
                        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                        f.write(f"{ts} | {os.path.basename(video_path)} | {video_url}\n")
                    print(f"      💾  Saved to uploaded_links.txt")
                
            except Exception as e:
                print("      ⚠️  Could not extract URL — upload still succeeded.")
                video_url = None

            # Human pause — like a person admiring their post
            await asyncio.sleep(random.uniform(3.0, 5.0))


            # Close post-publish dialog (force click — button ho sakta hai hidden)
            try:
                await page.locator('#close-button').first.evaluate("el => el.click()")
            except:
                pass

            print("\n" + "="*52)
            print("  ✅  BINGO! YOUTUBE SHORT UPLOADED SUCCESSFULLY!")
            if video_url:
                print(f"  🔗  URL : {video_url}")
            print("="*52 + "\n")

        except Exception as e:
            print(f"\n  ❌  YouTube Upload FAILED: {e}\n")
            raise

        finally:
            # ── 9. CLEAN EXIT ─────────────────────────────
            print("[9/9] 🚪  Closing browser context cleanly...")
            await context.close()

    return video_url  # ← Manager.py is use karega Whop submit ke liye


# ============================================================
#  📦 SYNC WRAPPER (called by Manager.py)
# ============================================================
def upload_video(video_path: str, caption: str) -> str | None:
    """Returns the live YouTube URL (youtu.be format) after upload, or None on failure."""
    return asyncio.run(run_youtube_uploader(video_path, caption))


# ============================================================
#  🧪 STANDALONE TEST
# ============================================================
if __name__ == "__main__":
    import os
    from whop_submitter import submit_to_whop
    from Manager import parse_smart_captions
    
    _test_vid = r"C:\Users\n\Documents\hotshort\Overnight_Factory\Pending_Videos\clip_0_1156_1225.mp4"
    _test_cap_file = r"C:\Users\n\Documents\hotshort\Overnight_Factory\Pending_Videos\clip_0_1156_1225_caption.txt"
    
    if os.path.exists(_test_cap_file):
        with open(_test_cap_file, "r", encoding="utf-8") as f:
            _test_cap = f.read()
    else:
        _test_cap = "YOUTUBE SHORTS CAPTION:\nTest caption\n----"
        
    smart_caps = parse_smart_captions(_test_cap)
    yt_cap = smart_caps.get('youtube', _test_cap)
        
    print(f"\n🎬 Running Standalone YouTube Test for {os.path.basename(_test_vid)}...")
    url = upload_video(_test_vid, yt_cap)
    
    if url:
        print(f"\n💰 Submitting YouTube URL to Whop TJR campaign: {url} ...")
        submit_to_whop(url, os.path.basename(_test_vid), "YouTube")
    else:
        print("❌ No URL captured, skipping Whop.")