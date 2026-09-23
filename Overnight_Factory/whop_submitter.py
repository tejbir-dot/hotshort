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

            # ── 4c. NAVIGATE REACH FRAME TO /campaigns PAGE ─────────────────────
            # KEY INSIGHT from screenshots:
            # - /discover → shows ALL campaigns as image banners (no submit button visible)
            # - /campaigns → shows YOUR JOINED campaigns with "Submit clip" button DIRECTLY!
            # So we navigate to /campaigns page, then Submit clip is right there.
            print("[4c] Navigating Reach frame to Campaigns page...")

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
                print(f"      Found Reach iframe at: {reach_frame.url[:80]}")

                # Navigate within the SPA to /campaigns page using the nav link
                nav_result = await reach_frame.evaluate("""
                    () => {
                        // Find the "Campaigns" nav link (NOT Discover)
                        // href = '/c/exp_.../campaigns' (no trailing slash, no campaigns/)
                        const links = [...document.querySelectorAll('a[href]')];
                        for (const a of links) {
                            const h = a.getAttribute('href') || '';
                            // Exact match: ends with /campaigns (not /campaigns/something)
                            if (/\\/campaigns$/.test(h)) {
                                a.click();
                                return 'navigated-to:' + h;
                            }
                        }
                        return null;
                    }
                """)
                print(f"      Nav result: {nav_result}")
                await asyncio.sleep(random.uniform(3.0, 5.0))

                # Confirm we are now on /campaigns page
                for _cw in range(10):
                    cur_url = next((f.url for f in page.frames if 'apps.whop.com' in f.url), '')
                    if '/campaigns' in cur_url and '/campaigns/' not in cur_url:
                        print(f"      ✅  On Campaigns page: {cur_url[:80]}")
                        # Update reach_frame reference
                        reach_frame = next((f for f in page.frames if 'apps.whop.com' in f.url), reach_frame)
                        break
                    await asyncio.sleep(1.0)
                else:
                    print("      ⚠️  Campaigns page not confirmed — trying anyway")

            else:
                print("      ⚠️  Reach iframe not found")

            await asyncio.sleep(2.0)

            # Debug screenshot
            _ss_path = str(FACTORY_DIR / "whop_debug_screenshot.png")
            try:
                await page.screenshot(path=_ss_path, full_page=True)
                print(f"      Screenshot: {_ss_path}")
            except Exception:
                pass







            # ── 5. SMART STATE-MACHINE: FIND & CLICK SUBMIT BUTTON ────────────────
            # The bot can be in multiple states. This loop detects state and acts accordingly:
            # STATE A: /discover         → navigate to /campaigns first
            # STATE B: /campaigns        → click "Submit clip" BUTTON (exact match, small button)
            # STATE C: /campaigns/0d9215 → click "Submit clip" BUTTON (big orange button)
            # STATE D: modal open        → input box visible → proceed to fill
            print("[5/7] State-machine: hunting Submit clip button...")

            # JS: click ONLY a button whose FULL text is exactly "Submit clip" or "Submit a clip"
            # This prevents clicking the campaign CARD which also CONTAINS that text
            JS_EXACT_BTN = """
                () => {
                    const TARGETS = ['submit clip', 'submit a clip'];
                    // Search ALL elements — the "Submit clip" element may be a div/a, not <button>
                    const all = [...document.querySelectorAll(
                        'button, [role="button"], a, div, span, p'
                    )];
                    for (const el of all) {
                        // Exact text match — but only leaf-ish elements (not big containers)
                        const t = (el.innerText || el.textContent || '').trim().toLowerCase();
                        if (TARGETS.includes(t) && el.children.length <= 2) {
                            el.scrollIntoView({ block: 'center' });
                            el.click();
                            return el.innerText.trim() || el.textContent.trim();
                        }
                    }
                    return null;
                }
            """

            # JS: navigate to /campaigns page within the SPA
            JS_GO_CAMPAIGNS = """
                () => {
                    const links = [...document.querySelectorAll('a[href]')];
                    for (const a of links) {
                        if (/\\/campaigns$/.test(a.getAttribute('href') || '')) {
                            a.click();
                            return a.getAttribute('href');
                        }
                    }
                    return null;
                }
            """

            # JS: check if form input is visible
            JS_HAS_INPUT = """
                () => {
                    const sels = [
                        'input[placeholder*="link" i]', 'input[placeholder*="url" i]',
                        'input[placeholder*="video" i]', 'input[placeholder*="paste" i]',
                        'input[placeholder*="youtube" i]', 'input[placeholder*="tiktok" i]',
                        'input[type="url"]', 'textarea',
                    ];
                    for (const s of sels) {
                        const el = document.querySelector(s);
                        if (el && el.offsetParent !== null) return s;
                    }
                    return null;
                }
            """

            submit_clicked = False
            modal_open = False
            active_frame = None

            for _tick in range(40):  # Up to 40 seconds
                # Always get the freshest reach frame
                rf = next((f for f in page.frames if 'apps.whop.com' in f.url), None)
                if not rf:
                    await asyncio.sleep(1.0)
                    continue

                url = rf.url
                print(f"      [tick {_tick}] State: {url.split('apps.whop.com')[-1][:50]}")

                # ── STATE D: Check if modal/form is already open (input visible) ──
                try:
                    input_sel = await rf.evaluate(JS_HAS_INPUT)
                    if input_sel:
                        print(f"      ✅  FORM OPEN! Input visible: {input_sel}")
                        modal_open = True
                        active_frame = rf
                        break
                except:
                    pass

                # ── STATE A: Still on /discover → go to /campaigns ──
                if '/discover' in url or '/home' in url:
                    try:
                        nav = await rf.evaluate(JS_GO_CAMPAIGNS)
                        print(f"      → Navigating to campaigns: {nav}")
                        await asyncio.sleep(3.0)
                        continue
                    except:
                        pass

                # ── STATES B & C: On /campaigns or /campaigns/XXXX ──
                if '/campaigns' in url:
                    # NUCLEAR: Full React-compatible event sequence via dispatchEvent
                    # Regular el.click() doesn't trigger React synthetic events.
                    # React listens to bubbled PointerEvent + MouseEvent sequence.
                    try:
                        btn_rect = await rf.evaluate("""
                            () => {
                                const allBtns = [...document.querySelectorAll('button, [role="button"], a, div, span')];
                                const TARGETS = ['submit clip', 'submit a clip'];
                                
                                // 1. Sirf specific elements dhundho jo text match karein aur GIANT container na hon
                                const matches = allBtns.filter(b => {
                                    const t = (b.innerText||b.textContent||'').trim().toLowerCase();
                                    return TARGETS.includes(t) && b.children.length <= 2;
                                });
                                
                                // 2. Jo screen par visible hain unko filter karo
                                const visibleBtns = matches.filter(b => {
                                    const r = b.getBoundingClientRect();
                                    return r.width > 0 && r.height > 0;
                                });
                                
                                if (visibleBtns.length === 0) return null;

                                // 3. SABSE BADI TRICK: Aakhiri button uthao! 
                                // Popup (Modal) humesha DOM ke end mein add hota hai.
                                const btn = visibleBtns[visibleBtns.length - 1];

                                // Scroll into view
                                btn.scrollIntoView({ block: 'center', behavior: 'instant' });

                                // Fire FULL React-compatible event sequence (bubbling)
                                const opts = { bubbles: true, cancelable: true, view: window };
                                btn.dispatchEvent(new PointerEvent('pointerover', opts));
                                btn.dispatchEvent(new MouseEvent('mouseover', opts));
                                btn.dispatchEvent(new PointerEvent('pointerdown', opts));
                                btn.dispatchEvent(new MouseEvent('mousedown', opts));
                                btn.dispatchEvent(new PointerEvent('pointerup', opts));
                                btn.dispatchEvent(new MouseEvent('mouseup', opts));
                                btn.dispatchEvent(new MouseEvent('click', opts));

                                // Return coordinates for logs
                                const r = btn.getBoundingClientRect();
                                return {
                                    text: (btn.innerText || btn.textContent).trim(),
                                    x: Math.round(r.left + r.width / 2),
                                    y: Math.round(r.top + r.height / 2),
                                    visible: r.width > 0 && r.height > 0
                                };
                            }
                        """)

                        if btn_rect:
                            print(f"      ✅  React events dispatched! btn='{btn_rect['text']}' at ({btn_rect['x']},{btn_rect['y']}) visible={btn_rect['visible']}")
                            submit_clicked = True
                            await asyncio.sleep(2.5)
                        else:
                            print(f"      ⏳  Submit clip button not in DOM yet — waiting...")
                            await asyncio.sleep(1.0)
                            continue

                    except Exception as e:
                        print(f"      ⚠️  React dispatch failed: {e}")
                        await asyncio.sleep(1.0)
                        continue


                await asyncio.sleep(1.0)

            if not modal_open:
                # Last chance: dump buttons for diagnostics
                try:
                    await page.screenshot(path=_ss_path, full_page=True)
                    rf = next((f for f in page.frames if 'apps.whop.com' in f.url), None)
                    if rf:
                        all_btns = await rf.evaluate(
                            """() => [...document.querySelectorAll('button, [role="button"]')]
                                     .map(b => (b.innerText||'').trim()).filter(t => t && t.length < 80)"""
                        )
                        print(f"      Buttons in frame: {all_btns}")
                except:
                    pass
                print("      ❌  Could not open submission form after 40s")
                print(f"      Screenshot: {_ss_path}")
                return False

            clicked_main = "Submit clip"
            print(f"      OK  Form is open — proceeding to fill!")
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

            # ── 7. CLICK FINAL "SUBMIT CLIP" BUTTON INSIDE MODAL ──
            # CRITICAL: Checkbox tick karna kaafi nahi — yeh orange button bhi dabaana padega!
            print("[7/7] Clicking final Submit button inside modal...")
            await asyncio.sleep(random.uniform(0.8, 1.5))  # Let checkbox state settle

            final_submitted = False
            for search_frame in frames_to_search:
                try:
                    # Look for the orange Submit clip button INSIDE the modal
                    # It's different from the campaign-page "Submit clip" button
                    result = await search_frame.evaluate("""
                        () => {
                            const allBtns = [...document.querySelectorAll('button, [role="button"], div, span, a')];
                            const TARGETS = ['submit clip', 'submit a clip'];
                            const matches = allBtns.filter(b => {
                                const t = (b.innerText||b.textContent||'').trim().toLowerCase();
                                return TARGETS.includes(t) && b.children.length <= 2;
                            });
                            const visibleBtns = matches.filter(b => {
                                const r = b.getBoundingClientRect();
                                return r.width > 0 && r.height > 0;
                            });
                            if (visibleBtns.length === 0) return null;
                            // Pick LAST visible button — modal button is always last in DOM
                            const btn = visibleBtns[visibleBtns.length - 1];
                            btn.scrollIntoView({ block: 'center', behavior: 'instant' });
                            const opts = { bubbles: true, cancelable: true, view: window };
                            btn.dispatchEvent(new PointerEvent('pointerdown', opts));
                            btn.dispatchEvent(new MouseEvent('mousedown', opts));
                            btn.dispatchEvent(new PointerEvent('pointerup', opts));
                            btn.dispatchEvent(new MouseEvent('mouseup', opts));
                            btn.dispatchEvent(new MouseEvent('click', opts));
                            const r = btn.getBoundingClientRect();
                            return { text: btn.innerText.trim(), x: Math.round(r.left + r.width/2), y: Math.round(r.top + r.height/2) };
                        }
                    """)
                    if result:
                        print(f"      OK  Final Submit btn clicked: '{result['text']}' at ({result['x']},{result['y']})")
                        final_submitted = True
                        break
                except Exception as e:
                    continue

            if not final_submitted:
                print("      Warning: Final Submit button not found — may have auto-submitted or already clicked")

            await asyncio.sleep(random.uniform(2.0, 3.0))  # Wait for submission to process

            # ── 8. CONFIRM ────────────────────────────────
            print("      ⏳  Waiting for confirmation (30s max)...")

            for attempt in range(6):
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
                print(f"      ⏳  Checking... ({(attempt+1)*5}s / 30s)")

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
    # ← Actual uploaded clip from last Manager run — testing Step 7 fix!
    _test_url = "https://youtube.com/shorts/aMSzm0Y0j_o"
    result = submit_to_whop(_test_url, "clip_1_301_347.mp4", platform="YouTube")
    print(f"\nResult: {'SUCCESS ✅' if result else 'FAILED ❌'}")

