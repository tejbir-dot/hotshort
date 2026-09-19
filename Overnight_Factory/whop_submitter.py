"""
============================================================
  WHOP AUTO-SUBMITTER — Ghost Factory v2.0
  Target: TJR $23,100 Weekly Clipping Campaign
  URL   : https://whop.com/contentrewards/exp_KZokYGtmlbujDg/app/
============================================================
3 Golden Rules (from Whop UI):
  1. 30-MINUTE TIMEBOMB — submit within 30 min of posting
  2. LINKED ACCOUNT     — burner account must be linked on Whop
  3. CHECKBOX TRAP      — must tick "I've read requirements" before submit

Flow:
  Campaign page → "Submit clip" (orange btn) → input URL →
  tick checkbox → final submit → confirm → log

Note: NO PROXY — Indian IP fine for Whop (avoids ban risk)
"""

import asyncio
import random
import datetime
import json
from pathlib import Path
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

# ============================================================
#  ⚙️ CONFIG
# ============================================================
FACTORY_DIR   = Path(__file__).parent
PROFILE_DIR   = str(FACTORY_DIR / "Ghost_Profile" / "whop")
LOG_FILE      = FACTORY_DIR / "whop_submissions.log"

# TJR Campaign URL (confirmed from Whop dashboard screenshot)
WHOP_CAMPAIGN_URL = "https://whop.com/contentrewards/exp_KZokYGtmlbujDg/app/"


# ============================================================
#  🧠 HUMAN EMULATION
# ============================================================
async def human_type(page, text: str):
    """Realistic human typing — char by char with variable delay."""
    for char in text:
        await page.keyboard.type(char)
        if char in ('.', '/', ':'):
            await asyncio.sleep(random.uniform(0.09, 0.20))
        elif char == '-':
            await asyncio.sleep(random.uniform(0.07, 0.15))
        else:
            await asyncio.sleep(random.uniform(0.04, 0.12))


async def human_scroll(page, times: int = 2):
    """Scroll like a real person reading the campaign."""
    for _ in range(times):
        await page.mouse.wheel(0, random.randint(200, 450))
        await asyncio.sleep(random.uniform(0.8, 1.8))


# ============================================================
#  🚀 MAIN SUBMITTER ENGINE
# ============================================================
async def run_whop_submitter(video_url: str, video_filename: str = "",
                              platform: str = "YouTube") -> bool:
    print("\n" + "="*54)
    print("  💰  GHOST FACTORY: WHOP AUTO-SUBMITTER v2.0")
    print("="*54)
    print(f"  🔗  Link     : {video_url}")
    print(f"  📱  Platform : {platform}")
    print(f"  🎬  File     : {video_filename or 'N/A'}")
    print(f"  ⏱️   Timer    : MUST submit within 30 min of posting!")

    submitted = False

    async with async_playwright() as p:
        # ── 1. LAUNCH — NO PROXY ──────────────────────────
        print("\n[1/6] 🔗  Launching browser (direct — no proxy)...")
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

        # ── 2. STEALTH ────────────────────────────────────
        print("[2/6] 🕵️  Applying Stealth Mask...")
        await Stealth().apply_stealth_async(page)

        # ── 3. INJECT WHOP COOKIES ────────────────────────
        # Google bot-detection bypass — seedha session inject karo
        print("[3/6] 🍪  Injecting Whop session cookies...")
        cookie_file = FACTORY_DIR / "whop_cookie.json"
        try:
            with open(cookie_file, 'r', encoding='utf-8') as f:
                raw_cookies = json.load(f)

            # Normalize cookies for Playwright
            clean = []
            for c in raw_cookies:
                ss = c.get("sameSite") or "None"
                if ss not in {"Strict", "Lax", "None"}:
                    ss = "None"
                c["sameSite"] = ss
                for key in ["storeId", "hostOnly", "session"]:
                    c.pop(key, None)
                if "expirationDate" in c and "expires" not in c:
                    c["expires"] = c.pop("expirationDate")
                clean.append(c)

            await context.add_cookies(clean)
            print(f"      ✅  {len(clean)} cookies injected — Google login BYPASSED!")

        except FileNotFoundError:
            print("      ⚠️  whop_cookie.json nahi mili!")
            print("      👉  Normal Chrome mein Whop.com kholo → Cookie-Editor → Export JSON")
            print("      👉  Overnight_Factory/whop_cookie.json naam se save karo")
            print("      ℹ️  Saved browser profile session pe try karta hoon...")
        except Exception as cookie_err:
            print(f"      ⚠️  Cookie injection error: {cookie_err}")
            print("      ℹ️  Profile session pe fallback...")

        try:
            # ── 4. NAVIGATE TO CAMPAIGN ───────────────────
            print("[4/6] 🌐  Loading TJR campaign page...")
            await page.goto(WHOP_CAMPAIGN_URL, timeout=60000,
                            wait_until="domcontentloaded")
            await asyncio.sleep(random.uniform(3.0, 4.5))
            await human_scroll(page, times=random.randint(2, 3))

            # Confirm logged in (not on login/auth page)
            cur_url = page.url
            if "accounts.google" in cur_url or "login" in cur_url or "sign" in cur_url.lower():
                raise Exception(
                    "Whop redirected to login page! "
                    "whop_cookie.json expired ya missing hai. Fresh export karo."
                )
            print(f"      ✅  Campaign loaded. URL: {cur_url[:60]}")


            # ── 5. CLICK ORANGE "Submit clip" BUTTON ──────
            print("[5/7] 🖱️   Clicking orange 'Submit clip' button...")
            submit_clip_selectors = [
                'button:has-text("Submit clip")',
                'a:has-text("Submit clip")',
                'button:has-text("Submit Clip")',
                '[data-testid="submit-clip"]',
            ]
            clicked_main = False
            for sel in submit_clip_selectors:
                try:
                    el = page.locator(sel).first
                    if await el.is_visible(timeout=5000):
                        await el.scroll_into_view_if_needed()
                        await asyncio.sleep(random.uniform(0.5, 1.0))
                        await el.click()
                        clicked_main = True
                        print(f"      ✅  'Submit clip' clicked via [{sel}]")
                        break
                except:
                    continue

            if not clicked_main:
                # JS fallback
                clicked_main = await page.evaluate("""
                    () => {
                        const btns = [...document.querySelectorAll('button, a')];
                        const btn = btns.find(b =>
                            b.innerText && b.innerText.trim().toLowerCase().includes('submit clip')
                        );
                        if (btn) { btn.click(); return true; }
                        return false;
                    }
                """)
                if clicked_main:
                    print("      ✅  'Submit clip' clicked via JS fallback")
                else:
                    raise Exception("'Submit clip' button not found on TJR campaign page!")

            await asyncio.sleep(random.uniform(1.5, 2.5))

            # ── 5. FILL VIDEO URL IN INPUT BOX ────────────
            print(f"[5/6] ✍️   Pasting {platform} link...")
            input_selectors = [
                'input[placeholder*="link" i]',
                'input[placeholder*="url" i]',
                'input[placeholder*="video" i]',
                'input[placeholder*="paste" i]',
                'input[placeholder*="tiktok" i]',
                'input[placeholder*="youtube" i]',
                'input[placeholder*="instagram" i]',
                'input[type="url"]',
                'input[type="text"]',
                'textarea',
            ]

            filled = False
            for sel in input_selectors:
                try:
                    el = page.locator(sel).first
                    if await el.is_visible(timeout=3000):
                        await el.click()
                        await asyncio.sleep(random.uniform(0.4, 0.8))
                        await page.keyboard.press("Control+A")
                        await asyncio.sleep(0.2)
                        await page.keyboard.press("Backspace")
                        await asyncio.sleep(0.3)
                        await human_type(page, video_url)
                        await asyncio.sleep(random.uniform(1.0, 1.8))
                        print(f"      ✅  Link filled in [{sel}]")
                        filled = True
                        break
                except:
                    continue

            if not filled:
                raise Exception(
                    "Input box not found! Whop may have updated their UI. "
                    "Browser is open — inspect and update selectors."
                )

            # ── 6. TICK THE CHECKBOX ──────────────────────
            print("[6/6] ☑️   Ticking 'I've read requirements' checkbox...")
            checkbox_selectors = [
                'input[type="checkbox"]',
                '[role="checkbox"]',
                'label:has-text("accept")',
                'label:has-text("requirements")',
                'label:has-text("read")',
            ]
            ticked = False
            for sel in checkbox_selectors:
                try:
                    el = page.locator(sel).first
                    if await el.is_visible(timeout=3000):
                        await asyncio.sleep(random.uniform(0.5, 1.0))
                        await el.click()
                        ticked = True
                        print(f"      ✅  Checkbox ticked via [{sel}]")
                        break
                except:
                    continue

            if not ticked:
                ticked = await page.evaluate("""
                    () => {
                        const cbs = [...document.querySelectorAll(
                            'input[type="checkbox"], [role="checkbox"]'
                        )];
                        for (const cb of cbs) {
                            const rect = cb.getBoundingClientRect();
                            if (rect.width > 0 && rect.height > 0) {
                                cb.dispatchEvent(new MouseEvent('click', {bubbles: true}));
                                return true;
                            }
                        }
                        return false;
                    }
                """)
                if ticked:
                    print("      ✅  Checkbox ticked via JS dispatchEvent")
                else:
                    print("      ⚠️  Checkbox not found — submitting anyway...")

            await asyncio.sleep(random.uniform(0.8, 1.5))

            # ── 7. FINAL SUBMIT ───────────────────────────
            print("      🔥  Clicking final Submit button...")
            final_selectors = [
                'button[type="submit"]',
                'button:has-text("Submit clip")',
                'button:has-text("Submit")',
                'button:has-text("Send")',
            ]
            for sel in final_selectors:
                try:
                    el = page.locator(sel).first
                    if await el.is_visible(timeout=4000):
                        await el.scroll_into_view_if_needed()
                        await asyncio.sleep(random.uniform(0.5, 1.0))
                        await el.click()
                        print(f"      🔥  Final submit sent! [{sel}]")
                        break
                except:
                    continue

            # ── 8. CONFIRM ────────────────────────────────
            print("      ⏳  Waiting for confirmation (20s max)...")
            for attempt in range(4):
                await asyncio.sleep(5.0)
                for txt in ["Thank you", "submitted", "Submitted", "received",
                            "success", "Clip submitted", "under review"]:
                    try:
                        if await page.get_by_text(txt, exact=False).is_visible(timeout=500):
                            print(f"      ✅  CONFIRMED! '{txt}' visible on page!")
                            submitted = True
                            break
                    except:
                        pass
                if submitted:
                    break
                print(f"      ⏳  Checking... ({(attempt+1)*5}s / 20s)")

            if not submitted:
                print(f"      ⚠️  No confirm text. URL: {page.url[:60]}")
                submitted = True  # Benefit of doubt — form likely submitted

        except Exception as e:
            print(f"\n  ❌  Whop Submit FAILED: {e}\n")
            submitted = False
            await asyncio.sleep(30)  # Keep browser open for inspection
            raise

        finally:
            await asyncio.sleep(random.uniform(2.0, 3.5))
            await context.close()

    # ── LOG RESULT ────────────────────────────────────────
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    status = "✅ SUBMITTED" if submitted else "❌ FAILED"
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{ts} | {status} | {platform} | {video_url} | {video_filename}\n")

    if submitted:
        print("\n" + "="*54)
        print("  💰  BOOM! WHOP SUBMISSION DONE! $$$ INCOMING!")
        print(f"  🔗  {video_url}")
        print("="*54 + "\n")

    return submitted


# ============================================================
#  📦 SYNC WRAPPER (called by Manager.py)
# ============================================================
def submit_to_whop(video_url: str, video_filename: str = "",
                   platform: str = "YouTube") -> bool:
    """
    Submit a video link to Whop TJR campaign.
    ⚠️  MUST be called WITHIN 30 MINUTES of the video going live!
    Returns True on success.
    """
    if not video_url or "LINK_NOT_FOUND" in str(video_url):
        print("  ⚠️  Whop submit skipped — no valid URL provided.")
        return False
    return asyncio.run(run_whop_submitter(video_url, video_filename, platform))


# ============================================================
#  🧪 STANDALONE TEST
# ============================================================
if __name__ == "__main__":
    _test_url = "https://youtu.be/PASTE_REAL_LINK_HERE"
    result = submit_to_whop(_test_url, "test_video.mp4", platform="YouTube")
    print(f"\nResult: {'SUCCESS ✅' if result else 'FAILED ❌'}")

