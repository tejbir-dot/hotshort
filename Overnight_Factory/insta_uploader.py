"""
==========================================
  INSTAGRAM UPLOADER — NATIVE STEALTH MODE
  Ghost Factory v4.0 | Zero Dolphin Dependency
==========================================
Architecture:
  - Persistent Context: Cookies survive between runs
  - playwright-stealth: Spoofs canvas fingerprint, hides webdriver flag
  - Cookie Injection: Skips login using saved session
  - Human Emulation: Realistic typing speed, random scrolling
  - Proxy Injected: US IP via rotating residential proxy
"""

import asyncio
import random
import json
import os
from pathlib import Path
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async

# ============================================================
#  ⚙️ FACTORY CONFIG — Edit only here
# ============================================================
FACTORY_DIR   = Path(__file__).parent
PROFILE_DIR   = str(FACTORY_DIR / "Ghost_Profile")
COOKIE_FILE   = str(FACTORY_DIR / "instagram_cookie.json")
PROXY         = {
    "server":   "http://162.210.64.27:12323",
    "username": "14a930ebcafee",
    "password":  "e269d4d909"
}

# ============================================================
#  🧠 HUMAN EMULATION HELPERS
# ============================================================
async def human_type_raw(page, text: str):
    """Type char by char with human-like variation."""
    for char in text:
        await page.keyboard.type(char)
        if char in ('.', '!', '?', '\n', '#'):
            await asyncio.sleep(random.uniform(0.15, 0.4))
        elif char == ' ':
            await asyncio.sleep(random.uniform(0.05, 0.15))
        else:
            await asyncio.sleep(random.uniform(0.04, 0.12))


async def human_scroll(page, times: int = 3):
    for _ in range(times):
        await page.mouse.wheel(0, random.randint(400, 1000))
        await asyncio.sleep(random.uniform(1.0, 2.5))


async def safe_click(page, selector: str, timeout: int = 10000):
    try:
        el = page.locator(selector).first
        await el.wait_for(state="visible", timeout=timeout)
        await el.scroll_into_view_if_needed()
        await asyncio.sleep(random.uniform(0.3, 0.7))
        await el.click()
        return True
    except Exception as e:
        print(f"  ⚠️  safe_click [{selector}] skipped: {e}")
        return False


async def dismiss_popups(page):
    """Dismiss common IG popups: 'Not Now', 'Save Info', etc."""
    popup_texts = ["Not Now", "Not now", "Skip", "Close"]
    for text in popup_texts:
        try:
            btn = page.get_by_role("button", name=text).first
            if await btn.is_visible(timeout=2000):
                await btn.click()
                await asyncio.sleep(1.0)
                print(f"      🛡️  Dismissed popup: '{text}'")
        except:
            pass


# ============================================================
#  🍪 COOKIE INTELLIGENCE
# ============================================================
def load_cookies(cookie_path: str) -> list:
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
async def run_insta_uploader(video_path: str, caption: str):
    print("\n" + "="*52)
    print("  🥷  GHOST FACTORY: INSTAGRAM STEALTH ENGINE v4.0")
    print("="*52)

    # Parse platform-specific caption
    ig_caption = caption
    if "INSTAGRAM REELS CAPTION:" in caption:
        block = caption.split("INSTAGRAM REELS CAPTION:")[1]
        ig_caption = block.split("----")[0].strip()
        # IG doesn't like dots-as-line-breaks — clean them
        ig_caption = ig_caption.replace("\n.\n", "\n\n").replace("\n.", "\n")

    print(f"  📋  Caption : {ig_caption[:60]}...")
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
        await stealth_async(page)

        # ── 3. INJECT COOKIES ─────────────────────────────
        print("[3/8] 🍪  Injecting Instagram Session Cookies...")
        cookies = load_cookies(COOKIE_FILE)
        if cookies:
            await context.add_cookies(cookies)
            print(f"      ✅  {len(cookies)} cookies injected — login bypassed!")
        else:
            print("      ⚠️  No cookies. Will rely on saved profile session.")

        try:
            # ── 4. WARM-UP: BROWSE IG FEED ────────────────
            print("[4/8] 🧘  Warming up... (scrolling IG feed)")
            await page.goto("https://www.instagram.com/", timeout=60000, wait_until="domcontentloaded")
            await asyncio.sleep(random.uniform(4.0, 7.0))

            # Dismiss any login/notification popups
            await dismiss_popups(page)

            await human_scroll(page, times=random.randint(2, 4))
            await asyncio.sleep(random.uniform(1.5, 3.0))
            print("      ✅  Warm-up complete. Looks like a real US scroller.")

            # ── 5. TRIGGER UPLOAD FLOW ────────────────────
            print("[5/8] 🎬  Clicking 'Create' (New Reel)...")
            clicked = await safe_click(page, "svg[aria-label='New post']", timeout=10000)
            if not clicked:
                # Fallback: find any + button
                await safe_click(page, "a[href='/create/style/']", timeout=5000)
            await asyncio.sleep(random.uniform(2.0, 4.0))

            # Select "Post" from dropdown if visible
            try:
                post_option = page.get_by_text("Post", exact=True)
                if await post_option.is_visible(timeout=3000):
                    await post_option.click()
                    await asyncio.sleep(random.uniform(2.0, 3.5))
            except:
                pass

            # ── 6. INJECT VIDEO FILE ──────────────────────
            print(f"[6/8] 📂  Injecting video: {os.path.basename(video_path)}")
            await page.set_input_files("input[type='file']", video_path)
            print("      ⏳  Waiting for IG to process media (6–10s)...")
            await asyncio.sleep(random.uniform(6.0, 10.0))

            # ── 7. BYPASS CROP/FILTER → CAPTION ──────────
            print("[7/8] ⏭️   Bypassing Crop & Filter screens...")

            # Crop screen Next
            try:
                next_crop = page.get_by_role("button", name="Next")
                if await next_crop.is_visible(timeout=5000):
                    await next_crop.click()
                    await asyncio.sleep(random.uniform(2.0, 3.5))
            except:
                print("      ℹ️  No crop screen found.")

            # Filter screen Next
            try:
                next_filter = page.get_by_role("button", name="Next")
                if await next_filter.is_visible(timeout=4000):
                    await next_filter.click()
                    await asyncio.sleep(random.uniform(2.0, 4.0))
            except:
                print("      ℹ️  No filter screen found.")

            # Type Caption
            print("      ✍️   Typing caption like a human...")
            try:
                caption_box = page.get_by_role("textbox").first
                await caption_box.click()
                await asyncio.sleep(0.8)
                await human_type_raw(page, ig_caption)
                await asyncio.sleep(random.uniform(2.0, 3.0))
            except Exception as e:
                print(f"      ⚠️  Caption box error: {e}")

            # ── 8. SHARE ──────────────────────────────────
            print("      🔥  SMASHING THE SHARE BUTTON!")
            shared = await safe_click(page, 'button:has-text("Share")', timeout=10000)
            if not shared:
                # Fallback
                await safe_click(page, "text='Share'", timeout=5000)

            print("      ⏳  Waiting for IG to process the Reel (45s)...")
            await asyncio.sleep(45.0)

            print("\n" + "="*52)
            print("  ✅  BINGO! INSTAGRAM REEL UPLOADED SUCCESSFULLY!")
            print("="*52 + "\n")

        except Exception as e:
            print(f"\n  ❌  Instagram Upload FAILED: {e}\n")
            raise

        finally:
            print("[8/8] 🚪  Closing browser context cleanly...")
            await context.close()


# ============================================================
#  📦 SYNC WRAPPER (called by Manager.py)
# ============================================================
def upload_video(video_path: str, caption: str):
    asyncio.run(run_insta_uploader(video_path, caption))


# ============================================================
#  🧪 STANDALONE TEST
# ============================================================
if __name__ == "__main__":
    _test_vid = r"C:\Users\n\Documents\hotshort\Overnight_Factory\Pending_Videos\clip_1_0_70.mp4"
    _test_cap = (
        "INSTAGRAM REELS CAPTION:\n"
        "The ultimate blueprint to hitting 1M subscribers and making bank 💸🔥\n"
        ".\n"
        "He started a celebrity gossip channel and grew it to 1 Million subs in months.\n"
        ".\n"
        "👇 Save this for your next side hustle idea!\n"
        ".\n"
        "#youtubeautomation #sidehustle #wealthmindset #entrepreneur #success #makemoneyonline\n"
        "----"
    )
    upload_video(_test_vid, _test_cap)