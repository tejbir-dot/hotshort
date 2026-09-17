"""
==========================================
  TIKTOK UPLOADER — NATIVE STEALTH MODE
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
from playwright_stealth import Stealth

# ============================================================
#  ⚙️ FACTORY CONFIG — Edit only here
# ============================================================
FACTORY_DIR   = Path(__file__).parent
PROFILE_DIR   = str(FACTORY_DIR / "Ghost_Profile" / "tiktok")
COOKIE_FILE   = str(FACTORY_DIR / "tiktok_cookie.json")
TIKTOK_HANDLE = "eliteclipper.studios1"  # ← Tera TikTok handle
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
async def run_tiktok_uploader(video_path: str, caption: str):
    print("\n" + "="*52)
    print("  🥷  GHOST FACTORY: TIKTOK STEALTH ENGINE v4.0")
    print("="*52)

    # Parse platform-specific caption
    tt_caption = caption
    if "TIKTOK CAPTION:" in caption:
        block = caption.split("TIKTOK CAPTION:")[1]
        tt_caption = block.split("----")[0].strip()

    print(f"  📋  Caption : {tt_caption[:60]}...")
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

        # ── 3. INJECT COOKIES ─────────────────────────────
        print("[3/8] 🍪  Injecting TikTok Session Cookies...")
        cookies = load_cookies(COOKIE_FILE)
        if cookies:
            await context.add_cookies(cookies)
            print(f"      ✅  {len(cookies)} cookies injected — login bypassed!")
        else:
            print("      ⚠️  No cookies. Will rely on saved profile session.")

            # ── 4. GO STRAIGHT TO TIKTOK UPLOAD ──────────
            print("[4/6] 🎬  Going straight to TikTok Creator Center...")
            await page.goto("https://www.tiktok.com/creator-center/upload", timeout=90000, wait_until="commit")
            await asyncio.sleep(random.uniform(3.0, 5.0))


            # ── 6. INJECT VIDEO FILE ──────────────────────
            print(f"[6/8] 📂  Injecting video: {os.path.basename(video_path)}")
            file_input = page.locator('input[type="file"]').first
            await file_input.set_input_files(video_path)
            print("      ⏳  Waiting for TikTok to process video (12–18s)...")
            await asyncio.sleep(random.uniform(12.0, 18.0))

            # ── 7. FILL CAPTION ───────────────────────────
            print("[7/8] ✍️   Typing caption like a human...")
            await page.keyboard.press('Escape')
            await asyncio.sleep(0.8)

            caption_box = page.locator('div[contenteditable="true"]').first
            await caption_box.click(force=True)
            await asyncio.sleep(0.8)
            await page.keyboard.press('Control+A')
            await asyncio.sleep(0.3)
            await page.keyboard.press('Backspace')
            await asyncio.sleep(0.5)
            await caption_box.click(force=True)
            await asyncio.sleep(0.4)
            await human_type_raw(page, tt_caption)
            await asyncio.sleep(random.uniform(2.0, 3.5))

            # Set privacy to Everyone
            print("      🌍  Setting privacy to 'Everyone'...")
            try:
                everyone = page.locator('text="Everyone"').last
                if await everyone.is_visible(timeout=4000):
                    await everyone.evaluate("node => node.click()")
                    await asyncio.sleep(1.0)
            except:
                print("      ℹ️  Privacy already set or selector changed.")

            # ── 8. POST ───────────────────────────────────
            print("      🔥  SMASHING THE POST BUTTON...")
            post_btn = page.locator('div[role="button"]:has-text("Post"), button:has-text("Post")').last
            await post_btn.scroll_into_view_if_needed()
            await asyncio.sleep(random.uniform(1.0, 2.0))
            await post_btn.evaluate("node => node.click()")

            await asyncio.sleep(8.0)

            # Post-publish popup
            try:
                post_now = page.locator('div[role="button"]:has-text("Post now"), button:has-text("Post now")').last
                if await post_now.is_visible(timeout=4000):
                    print("      🚨  Popup detected! Clicking 'Post now'...")
                    await post_now.evaluate("node => node.click()")
            except:
                print("      ℹ️  No popup detected, moving on.")

            print("      ⏳  Waiting for server confirmation (20s)...")
            await asyncio.sleep(20.0)

            # Save video URL
            try:
                await page.goto(f"https://www.tiktok.com/@{TIKTOK_HANDLE}", timeout=30000)
                await asyncio.sleep(5.0)
                first_video = page.locator('a[href*="/video/"]').first
                video_url = await first_video.get_attribute('href')
                print(f"\n{'='*52}")
                print("  ✅  BINGO! TIKTOK VIDEO UPLOADED SUCCESSFULLY!")
                print(f"  🔗  URL: {video_url}")
                print(f"{'='*52}\n")
                with open(str(FACTORY_DIR / "published_links.txt"), "a") as f:
                    f.write(f"TIKTOK: {video_url}\n")
            except Exception as e:
                print(f"      ⚠️  Could not fetch video URL: {e}")
                print("\n" + "="*52)
                print("  ✅  TIKTOK UPLOAD COMPLETE (URL fetch failed)")
                print("="*52 + "\n")

        except Exception as e:
            print(f"\n  ❌  TikTok Upload FAILED: {e}\n")
            raise

        finally:
            print("[8/8] 🚪  Closing browser context cleanly...")
            await context.close()


# ============================================================
#  📦 SYNC WRAPPER (called by Manager.py)
# ============================================================
def upload_video(video_path: str, caption: str):
    asyncio.run(run_tiktok_uploader(video_path, caption))


# ============================================================
#  🧪 STANDALONE TEST
# ============================================================
if __name__ == "__main__":
    _test_vid = r"C:\Users\n\Documents\hotshort\Overnight_Factory\Pending_Videos\clip_1_0_70.mp4"
    _test_cap = (
        "TIKTOK CAPTION:\n"
        "How he grew to 1 MILLION subscribers just posting Shorts! 📈 "
        "The secret is choosing a niche you actually enjoy. Watch till the end! "
        "#youtubeshorts #sidehustle #entrepreneur #rich #foryou\n"
        "----"
    )
    upload_video(_test_vid, _test_cap)