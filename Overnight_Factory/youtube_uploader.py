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
from pathlib import Path
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

# ============================================================
#  ⚙️ FACTORY CONFIG — Edit only here
# ============================================================
FACTORY_DIR   = Path(__file__).parent
PROFILE_DIR   = str(FACTORY_DIR / "Ghost_Profile" / "youtube")
COOKIE_FILE   = str(FACTORY_DIR / "youtube_cookie.json")
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
            # Playwright requires sameSite to be one of these exact strings
            same_site = c.get("sameSite") or "None"
            if same_site not in valid_same_site:
                same_site = "None"
            c["sameSite"] = same_site

            # Remove browser-extension-only fields that playwright rejects
            for key in ["storeId", "hostOnly", "session"]:
                c.pop(key, None)

            # expirationDate → expires (playwright uses 'expires')
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
async def run_youtube_uploader(video_path: str, caption: str):
    print("\n" + "="*52)
    print("  🥷  GHOST FACTORY: YOUTUBE STEALTH ENGINE v4.0")
    print("="*52)

    # Parse platform-specific caption
    yt_caption = caption
    if "YOUTUBE SHORTS CAPTION:" in caption:
        block = caption.split("YOUTUBE SHORTS CAPTION:")[1]
        yt_caption = block.split("----")[0].strip()
    
    # First line = title (max 90 chars), full = description
    title_line   = yt_caption.split('\n')[0][:90]
    description  = yt_caption

    print(f"  📋  Title   : {title_line}")
    print(f"  🎬  Video   : {os.path.basename(video_path)}")
    print(f"  🌐  Proxy   : {PROXY['server']}")

    async with async_playwright() as p:

        # ── 1. LAUNCH STEALTH BROWSER ──────────────────────
        print("\n[1/8] 🔗  Launching Stealth Persistent Context...")
        context = await p.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            channel="chrome",
            headless=False,
            proxy=PROXY,
            viewport={"width": 1366, "height": 768},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--no-first-run",
                "--no-sandbox",
            ],
            ignore_default_args=["--enable-automation"],
        )

        page = await context.new_page()

        # ── 2. APPLY STEALTH MASK ──────────────────────────
        print("[2/8] 🕵️  Applying Stealth Mask (anti-fingerprint)...")
        await Stealth().apply_stealth_async(page)

        # ── 3. INJECT COOKIES (bypass login) ──────────────
        print("[3/8] 🍪  Injecting YouTube Session Cookies...")
        cookies = load_cookies(COOKIE_FILE)
        if cookies:
            await context.add_cookies(cookies)
            print(f"      ✅  {len(cookies)} cookies injected — login bypassed!")
        else:
            print("      ⚠️  No cookies found. Will rely on saved profile session.")

        try:
            # ── 4. STEPPING STONE: Prime the proxy via Google ──
            print("[4/6] 🧘  Warming up proxy tunnel via Google...")
            try:
                await page.goto("https://www.google.com", timeout=45000, wait_until="domcontentloaded")
                await asyncio.sleep(random.uniform(2.0, 3.5))
                print("      ✅  Proxy tunnel ALIVE! Google loaded.")
            except Exception as warm_err:
                print(f"      ⚠️  Google warmup slow/failed: {warm_err}")
                print("      ⚠️  Proxy IP dead hogi — Ctrl+C maar aur dobara run kar (naya IP milega)")
                raise Exception(f"Proxy tunnel failed on Google warmup: {warm_err}")

            # ── 5. ENTER YOUTUBE STUDIO ───────────────────────
            print("[5/6] 🎬  Entering YouTube Studio...")
            await page.goto("https://studio.youtube.com/", timeout=120000, wait_until="domcontentloaded")

            # 🔍 LOGIN CHECK — agar redirect hua toh cookies expired hain
            await asyncio.sleep(3.0)
            current_url = page.url
            if "accounts.google.com" in current_url or "signin" in current_url:
                raise Exception(
                    "❌ YouTube cookies EXPIRED! Studio ne login page pe redirect kiya. "
                    "youtube_cookie.json ko fresh export kar aur replace kar."
                )
            print(f"      ✅  Studio loaded. URL: {current_url[:60]}")

            # Wait for the #create-icon to actually appear (not just blank React shell)
            print("      ⏳  Waiting for Studio UI to fully render...")
            try:
                await page.locator('#create-icon').wait_for(state="visible", timeout=20000)
                print("      ✅  Studio UI ready!")
            except:
                # Sometimes create-icon loads slowly — give it extra time
                await asyncio.sleep(5.0)
                print("      ⚠️  create-icon slow to load, trying anyway...")

            # Open upload dialog
            clicked = await safe_click(page, '#create-icon', timeout=10000)
            if not clicked:
                await safe_click(page, 'ytcp-icon-button[id="create-icon"]', timeout=5000)
            await asyncio.sleep(random.uniform(1.0, 2.0))

            await safe_click(page, '#text:has-text("Upload videos")', timeout=8000)
            await asyncio.sleep(random.uniform(2.0, 3.5))


            # ── 6. INJECT VIDEO FILE ──────────────────────
            print(f"[6/8] 📂  Injecting video: {os.path.basename(video_path)}")
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

            print("      ⏳  Waiting for YouTube to confirm publish (15s)...")
            await asyncio.sleep(15.0)

            # Close post-publish dialog
            await safe_click(page, '#close-button', timeout=5000)

            print("\n" + "="*52)
            print("  ✅  BINGO! YOUTUBE SHORT UPLOADED SUCCESSFULLY!")
            print("="*52 + "\n")

        except Exception as e:
            print(f"\n  ❌  YouTube Upload FAILED: {e}\n")
            raise  # Re-raise so Manager.py catches it and moves to Failed_Videos

        finally:
            # ── 8. CLEAN EXIT ─────────────────────────────
            print("[8/8] 🚪  Closing browser context cleanly...")
            await context.close()


# ============================================================
#  📦 SYNC WRAPPER (called by Manager.py)
# ============================================================
def upload_video(video_path: str, caption: str):
    asyncio.run(run_youtube_uploader(video_path, caption))


# ============================================================
#  🧪 STANDALONE TEST
# ============================================================
if __name__ == "__main__":
    _test_vid = r"C:\Users\n\Documents\hotshort\Overnight_Factory\Pending_Videos\clip_1_0_70.mp4"
    _test_cap = (
        "YOUTUBE SHORTS CAPTION:\n"
        "He made $20,000 in 6 months with YouTube Shorts! 🤯 "
        "Step-by-step blueprint to find a viral niche. 👇 "
        "#youtubeautomation #sidehustle #makemoneyonline #wealth #shorts\n"
        "----"
    )
    upload_video(_test_vid, _test_cap)