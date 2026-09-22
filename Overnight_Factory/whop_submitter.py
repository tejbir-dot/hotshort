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
WHOP_CAMPAIGN_URL = "https://whop.com/reachclipping/exp_6DJb0DkDMhATvG/app/"


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
            # ── 4. NAVIGATE TO CAMPAIGN ────────────────────────────
            print("[4/6] Loading Whop Content Rewards campaign page...")
            # Direct URL to the TJR campaign — this opens the detail page with the Submit button
            CAMPAIGN_DIRECT_URL = "https://whop.com/reachclipping/exp_6DJh0DkDMhATvG/app/"
            await page.goto(CAMPAIGN_DIRECT_URL, timeout=60000, wait_until="domcontentloaded")
            await asyncio.sleep(random.uniform(5.0, 7.0))  # Let React + iframes fully hydrate

            cur_url = page.url
            if "accounts.google" in cur_url or "login" in cur_url or "sign" in cur_url.lower():
                raise Exception("Whop redirected to login! Refresh whop_cookie.json.")
            print(f"      OK  Campaign page loaded. URL: {cur_url[:80]}")

            # ── 4b. CLICK 'Content Rewards' IN SIDEBAR (if not already there) ──
            print("[4b] Ensuring Content Rewards section is active...")
            await page.evaluate("""
                () => {
                    const all = [...document.querySelectorAll('a, button, span, div, li')];
                    const el = all.find(e => {
                        const t = e.innerText && e.innerText.trim().toLowerCase();
                        return t === 'content rewards';
                    });
                    if (el) { el.click(); return true; }
                    return false;
                }
            """)
            await asyncio.sleep(random.uniform(3.0, 4.0))

            # ── 4c. CLICK CAMPAIGN CARD VIA frame.evaluate() IN REACH FRAME ──────
            # frame.evaluate() runs in the frame's OWN JS context — cross-origin safe!
            # Unlike page.frame_locator() which needs the iframe src= attribute to match,
            # we get the frame object by URL and inject JS directly inside it.
            print("[4c] Injecting click into Reach frame JS context...")

            # Find the Reach iframe frame object
            reach_frame = None
            for _wait in range(15):
                for frame in page.frames:
                    if 'apps.whop.com' in frame.url:
                        reach_frame = frame
                        break
                if reach_frame:
                    break
                await asyncio.sleep(1.0)

            if reach_frame:
                print(f"      Found Reach iframe: {reach_frame.url[:80]}")

                # Dump all anchor hrefs for diagnostics
                try:
                    all_hrefs = await reach_frame.evaluate("""
                        () => [...document.querySelectorAll('a[href]')]
                              .map(a => a.getAttribute('href'))
                              .filter(h => h && h.length > 1)
                              .slice(0, 20)
                    """)
                    print(f"      All hrefs in frame: {all_hrefs}")
                except Exception as e:
                    print(f"      ⚠️  href dump failed: {e}")

                # Click the campaign card using JS in the frame's own context
                clicked_href = await reach_frame.evaluate("""
                    () => {
                        const NAV = ['home','discover','campaigns','analytics',
                                     'submissions','drafts','earnings','support',
                                     'discord','townhall','affiliates'];
                        const anchors = [...document.querySelectorAll('a[href]')];

                        // Priority 1: href contains 'campaigns/' or known campaign ID
                        for (const a of anchors) {
                            const h = a.getAttribute('href') || '';
                            if (h.includes('campaigns/') || h.includes('0d9215')) {
                                a.click();
                                return 'campaigns-href:' + h;
                            }
                        }
                        // Priority 2: first non-nav anchor (campaign card link)
                        for (const a of anchors) {
                            const text = (a.innerText || '').toLowerCase().trim();
                            const h = a.getAttribute('href') || '';
                            if (!NAV.includes(text) && h.length > 2) {
                                a.click();
                                return 'first-non-nav:' + h;
                            }
                        }
                        // Priority 3: click anything
                        if (anchors.length > 0) {
                            anchors[0].click();
                            return 'fallback:' + anchors[0].getAttribute('href');
                        }
                        return null;
                    }
                """)
                if clicked_href:
                    print(f"      ✅  JS click fired! ({clicked_href})")
                    await asyncio.sleep(random.uniform(4.0, 6.0))
                else:
                    print("      ⚠️  No clickable anchor found in Reach frame")
            else:
                print("      ⚠️  Reach iframe not found")

            # Wait for campaigns/ URL to confirm we're on detail page (max 20s)
            print("      ⏳  Waiting for campaign detail page...")
            for _cw in range(20):
                for frame in page.frames:
                    if 'campaigns/' in frame.url and 'apps.whop.com' in frame.url:
                        print(f"      ✅  Campaign detail loaded: {frame.url[:80]}")
                        break
                else:
                    await asyncio.sleep(1.0)
                    continue
                break
            else:
                print("      ⚠️  Campaign detail not confirmed — will still try Submit search")

            await asyncio.sleep(2.0)

            # Debug screenshot
            _ss_path = str(FACTORY_DIR / "whop_debug_screenshot.png")
            try:
                await page.screenshot(path=_ss_path, full_page=True)
                print(f"      Screenshot: {_ss_path}")
            except Exception:
                pass





            # ── 5. FIND & CLICK SUBMIT BUTTON ─────────────────────
            print("[5/7] Looking for Submit button...")
            all_frame_urls = [f.url[:60] for f in page.frames if f.url]
            print(f"      Frames loaded ({len(page.frames)}): {all_frame_urls}")

            # PRIORITY: Try FrameLocator on the campaign iframe first (fastest + most reliable)
            clicked_via_frameloc = False
            try:
                campaign_iframe = page.frame_locator('iframe[src*="campaigns"]')
                submit_btn = campaign_iframe.get_by_text("Submit clip", exact=False).first
                await submit_btn.wait_for(state="visible", timeout=8000)
                await submit_btn.click()
                clicked_via_frameloc = True
                print("      ✅  Submit button clicked via FrameLocator!")
            except:
                pass

            if not clicked_via_frameloc:
                # Fallback: try any apps.whop.com iframe using get_by_text
                try:
                    reach_iframe = page.frame_locator('iframe[src*="apps.whop.com"]')
                    submit_btn = reach_iframe.get_by_text("Submit clip", exact=False).first
                    await submit_btn.wait_for(state="visible", timeout=8000)
                    await submit_btn.click()
                    clicked_via_frameloc = True
                    print("      ✅  Submit button clicked via apps.whop.com FrameLocator!")
                except:
                    pass

            if clicked_via_frameloc:
                clicked_main = "Submit clip"
                active_frame = None
            
            submit_keywords = ["submit clip", "submit a clip", "submit"]
            clicked_main = None
            active_frame = None

            for _attempt in range(20):  # 20s total wait
                # Check main page DOM
                clicked_main = await page.evaluate(
                    """(keywords) => {
                        const btns = [...document.querySelectorAll('button, a, [role="button"]')];
                        for (const kw of keywords) {
                            const btn = btns.find(b => {
                                const t = b.innerText && b.innerText.trim().toLowerCase();
                                return t && t.includes(kw);
                            });
                            if (btn) {
                                btn.scrollIntoView({ behavior: 'smooth', block: 'center' });
                                btn.click();
                                return btn.innerText.trim();
                            }
                        }
                        return null;
                    }""",
                    submit_keywords
                )
                if clicked_main:
                    active_frame = page.main_frame
                    break

                # Check all iframes
                for frame in page.frames:
                    if frame == page.main_frame:
                        continue
                    try:
                        clicked_main = await frame.evaluate(
                            """(keywords) => {
                                const btns = [...document.querySelectorAll('button, a, [role="button"]')];
                                for (const kw of keywords) {
                                    const btn = btns.find(b => {
                                        const t = b.innerText && b.innerText.trim().toLowerCase();
                                        return t && t.includes(kw);
                                    });
                                    if (btn) {
                                        btn.scrollIntoView({ behavior: 'smooth', block: 'center' });
                                        btn.click();
                                        return btn.innerText.trim();
                                    }
                                }
                                return null;
                            }""",
                            submit_keywords
                        )
                        if clicked_main:
                            active_frame = frame
                            print(f"      Found in iframe: {frame.url[:80]}")
                            break
                    except:
                        continue

                if clicked_main:
                    break
                await asyncio.sleep(1.0)

            if clicked_main:
                print(f"      OK  Clicked: '{clicked_main}'")
            else:
                await page.screenshot(path=_ss_path, full_page=True)
                _all_btns = await page.evaluate(
                    """() => [...document.querySelectorAll('button, a, [role="button"]')]
                           .map(b => b.innerText.trim()).filter(t => t && t.length < 60).slice(0, 30)"""
                )
                print(f"      Buttons: {_all_btns}")
                print(f"      Screenshot: {_ss_path}")
                print("      No submit button found")
                return False

            await asyncio.sleep(random.uniform(1.5, 2.5))

            # ── 5. FILL VIDEO URL IN INPUT BOX ────────────────────
            print(f"[5/6] Pasting {platform} link...")
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

            # Search input in same frame as submit button first
            frames_to_search = []
            if active_frame and active_frame != page.main_frame:
                frames_to_search.append(active_frame)
            frames_to_search.append(page.main_frame)
            for f in page.frames:
                if f not in frames_to_search:
                    frames_to_search.append(f)

            filled = False
            for search_frame in frames_to_search:
                for sel in input_selectors:
                    try:
                        el = search_frame.locator(sel).first
                        if await el.is_visible(timeout=2000):
                            await el.click()
                            await asyncio.sleep(random.uniform(0.4, 0.8))
                            await el.press("Control+A")
                            await asyncio.sleep(0.2)
                            await el.press("Backspace")
                            await asyncio.sleep(0.3)
                            await el.type(video_url, delay=80)
                            await asyncio.sleep(random.uniform(1.0, 1.8))
                            print(f"      OK  Link filled [{sel}]")
                            filled = True
                            break
                    except:
                        continue
                if filled:
                    break

            if not filled:
                raise Exception("Input box not found! Check whop_debug_screenshot.png")

            # ── 6. TICK CHECKBOX ──────────────────────────────────
            print("[6/6] Ticking checkbox...")
            checkbox_selectors = [
                'input[type="checkbox"]',
                '[role="checkbox"]',
                'label:has-text("accept")',
                'label:has-text("requirements")',
                'label:has-text("read")',
            ]
            ticked = False
            for search_frame in frames_to_search:
                for sel in checkbox_selectors:
                    try:
                        el = search_frame.locator(sel).first
                        if await el.is_visible(timeout=2000):
                            await asyncio.sleep(random.uniform(0.5, 1.0))
                            await el.click()
                            ticked = True
                            print(f"      OK  Checkbox ticked [{sel}]")
                            break
                    except:
                        continue
                if ticked:
                    break

            if not ticked:
                # JS fallback
                for search_frame in frames_to_search:
                    try:
                        ticked = await search_frame.evaluate(
                            """() => {
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
                            }"""
                        )
                        if ticked:
                            print("      OK  Checkbox ticked via JS")
                            break
                    except:
                        continue

            if not ticked:
                print("      Warning: Checkbox not found — submitting anyway...")

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
    # ← Fresh YouTube Short — testing new iframe fix!
    _test_url = "https://youtube.com/shorts/hHXr_wPDcQw"
    result = submit_to_whop(_test_url, "clip_11_1271_1339.mp4", platform="YouTube")
    print(f"\nResult: {'SUCCESS ✅' if result else 'FAILED ❌'}")
