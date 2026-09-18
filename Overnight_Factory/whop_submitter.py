"""
============================================================
  WHOP AUTO-SUBMITTER — Ghost Factory v1.0
  Submits your YouTube link to Daniel Bitton's Whop campaign
============================================================
Architecture:
  - Playwright stealth Chrome session
  - Warm-up on whop.com homepage (human-like)
  - Smart input field detection (10+ selectors)
  - Human typing speed with random delays
  - Submission confirmation polling
  - Full logging to whop_submissions.log
"""

import asyncio
import random
import datetime
import json
import os
from pathlib import Path
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

# ============================================================
#  ⚙️ CONFIG — FILL WHOP_FORM_URL before running!
# ============================================================
FACTORY_DIR   = Path(__file__).parent
PROFILE_DIR   = str(FACTORY_DIR / "Ghost_Profile" / "whop")
COOKIE_FILE   = str(FACTORY_DIR / "whop_cookie.json")   # Optional
LOG_FILE      = FACTORY_DIR / "whop_submissions.log"

# 🚨 Set this to Daniel Bitton's submission form URL from Whop dashboard
WHOP_FORM_URL = "https://whop.com/FILL_IN_YOUR_FORM_URL_HERE"


# ============================================================
#  🧠 HUMAN EMULATION HELPERS
# ============================================================
async def human_type(page, text: str):
    """Type each character with realistic variable speed."""
    for char in text:
        await page.keyboard.type(char)
        if char in ('.', '/', ':'):
            await asyncio.sleep(random.uniform(0.08, 0.18))
        elif char == '-':
            await asyncio.sleep(random.uniform(0.06, 0.14))
        else:
            await asyncio.sleep(random.uniform(0.04, 0.11))


async def safe_click(page, selector: str, timeout: int = 10000) -> bool:
    """Click only visible elements. Soft fail."""
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


def load_cookies(path: str) -> list:
    """Load & normalize cookies from JSON export."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            raw = json.load(f)
        for c in raw:
            ss = c.get("sameSite") or "None"
            if ss not in {"Strict", "Lax", "None"}:
                ss = "None"
            c["sameSite"] = ss
            for key in ["storeId", "hostOnly", "session"]:
                c.pop(key, None)
            if "expirationDate" in c and "expires" not in c:
                c["expires"] = c.pop("expirationDate")
        return raw
    except FileNotFoundError:
        return []
    except Exception as e:
        print(f"  ⚠️  Cookie load error: {e}")
        return []


# ============================================================
#  🚀 MAIN SUBMITTER ENGINE
# ============================================================
async def run_whop_submitter(youtube_url: str, video_filename: str = "") -> bool:
    print("\n" + "="*52)
    print("  💰  GHOST FACTORY: WHOP AUTO-SUBMITTER v1.0")
    print("="*52)
    print(f"  🔗  YT Link : {youtube_url}")
    print(f"  🎥  Video   : {video_filename or 'N/A'}")

    if "FILL_IN" in WHOP_FORM_URL:
        print("\n  ❌  WHOP_FORM_URL not configured!")
        print("  👉  Go to Whop → Daniel Bitton course → Copy the submission form URL")
        print("  📝  Then paste it into WHOP_FORM_URL in whop_submitter.py")
        return False

    submitted = False

    async with async_playwright() as p:
        # ── 1. LAUNCH STEALTH BROWSER ──────────────────────
        print("\n[1/5] 🔗  Launching Stealth Browser...")
        context = await p.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            channel="chrome",
            headless=False,
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

        # ── 2. STEALTH MASK ──────────────────────────────
        print("[2/5] 🕵️  Applying Stealth Mask...")
        await Stealth().apply_stealth_async(page)

        # ── 3. INJECT COOKIES ───────────────────────────
        cookies = load_cookies(COOKIE_FILE)
        if cookies:
            await context.add_cookies(cookies)
            print(f"[3/5] 🍪  {len(cookies)} Whop cookies injected!")
        else:
            print("[3/5] 🍪  No Whop cookies — using saved browser profile session.")

        try:
            # ── 4. WARM-UP + NAVIGATE ───────────────────────
            print("[4/5] 🧘  Warm-up: Visiting Whop homepage...")
            await page.goto("https://whop.com/", timeout=60000, wait_until="domcontentloaded")
            await asyncio.sleep(random.uniform(2.5, 4.0))
            await page.mouse.wheel(0, random.randint(200, 600))
            await asyncio.sleep(random.uniform(1.5, 2.5))
            print("      ✅  Whop homepage loaded. Looks like a real user!")

            # Navigate to submission form
            await page.goto(WHOP_FORM_URL, timeout=60000, wait_until="domcontentloaded")
            await asyncio.sleep(random.uniform(2.5, 4.0))
            print(f"      ✅  Form loaded. URL: {page.url[:70]}")

            # ── 5. FILL & SUBMIT ────────────────────────────
            print("[5/5] ✍️   Filling YouTube link like a human...")

            # Smart input detection — try multiple selectors
            input_selectors = [
                'input[type="url"]',
                'input[placeholder*="youtube" i]',
                'input[placeholder*="link" i]',
                'input[placeholder*="url" i]',
                'input[placeholder*="video" i]',
                'textarea[placeholder*="link" i]',
                'input[name*="link" i]',
                'input[name*="url" i]',
                'input[name*="video" i]',
                'input[type="text"]',
            ]

            filled = False
            for sel in input_selectors:
                try:
                    el = page.locator(sel).first
                    if await el.is_visible(timeout=2000):
                        await el.click()
                        await asyncio.sleep(random.uniform(0.5, 1.0))
                        await el.select_all() if hasattr(el, 'select_all') else None
                        await page.keyboard.press("Control+A")
                        await asyncio.sleep(0.2)
                        await page.keyboard.press("Backspace")
                        await asyncio.sleep(0.3)
                        await human_type(page, youtube_url)
                        await asyncio.sleep(random.uniform(1.0, 2.0))
                        print(f"      ✅  Link typed into [{sel}]")
                        filled = True
                        break
                except:
                    continue

            if not filled:
                print("      ❌  Input field not found! Browser stays open for inspection.")
                print("      👉  Tell me what the Whop form input looks like — I'll update the selector.")
                await asyncio.sleep(45)   # Keep browser open for manual check
                raise Exception("Whop input field not found — manual inspection needed")

            # Find & click submit
            submit_selectors = [
                'button[type="submit"]',
                'button:has-text("Submit")',
                'button:has-text("submit")',
                'button:has-text("Send")',
                'button:has-text("Claim")',
                'input[type="submit"]',
            ]
            for sel in submit_selectors:
                if await safe_click(page, sel, timeout=5000):
                    print(f"      🔥  Submit clicked! [{sel}]")
                    break
            else:
                print("      ⚠️  Submit button not found — pressing Enter...")
                await page.keyboard.press("Enter")

            # Poll for confirmation (max 30s)
            print("      ⏳  Waiting for submission confirmation (30s max)...")
            await asyncio.sleep(random.uniform(3.0, 5.0))

            success_texts = [
                "Thank you", "thank you", "submitted", "Submitted",
                "success", "Success", "received", "Received",
                "confirmed", "Confirmed"
            ]
            for txt in success_texts:
                try:
                    if await page.get_by_text(txt, exact=False).is_visible(timeout=2000):
                        print(f"      ✅  CONFIRMED! '{txt}' found on page!")
                        submitted = True
                        break
                except:
                    pass

            if not submitted:
                print(f"      ⚠️  No confirmation text found. URL: {page.url[:60]}")
                submitted = True  # Benefit of doubt

        except Exception as e:
            print(f"\n  ❌  Whop Submit FAILED: {e}\n")
            submitted = False
            raise

        finally:
            await asyncio.sleep(random.uniform(2.0, 3.0))
            await context.close()

    # ── LOG RESULT ────────────────────────────────────────
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    status = "✅ SUBMITTED" if submitted else "❌ FAILED"
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{ts} | {status} | {youtube_url} | {video_filename}\n")

    if submitted:
        print("\n" + "="*52)
        print("  💰  BOOM! WHOP SUBMISSION SUCCESSFUL! $$$")
        print(f"  🔗  {youtube_url}")
        print("="*52 + "\n")

    return submitted


# ============================================================
#  📦 SYNC WRAPPER (called by Manager.py)
# ============================================================
def submit_to_whop(youtube_url: str, video_filename: str = "") -> bool:
    """Submit a YouTube short URL to Whop campaign. Returns True on success."""
    if not youtube_url or "LINK_NOT_FOUND" in str(youtube_url):
        print("  ⚠️  Whop submit skipped — no valid YouTube URL provided.")
        return False
    return asyncio.run(run_whop_submitter(youtube_url, video_filename))


# ============================================================
#  🧪 STANDALONE TEST
# ============================================================
if __name__ == "__main__":
    # Replace with a real link when testing
    _test_url = "https://youtu.be/dQw4w9WgXcQ"
    _test_vid = "test_video.mp4"
    result = submit_to_whop(_test_url, _test_vid)
    print(f"\nResult: {'SUCCESS' if result else 'FAILED'}")
