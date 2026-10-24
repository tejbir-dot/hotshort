import asyncio
import os
import shutil
import subprocess
from playwright.async_api import async_playwright

async def main():
    base_dir = r"c:\Users\n\Documents\hotshort\marketing_factory"
    raw_rec_dir = os.path.join(base_dir, "raw_playwright_rec")
    os.makedirs(raw_rec_dir, exist_ok=True)
    
    # Target output in Remotion public
    final_output = r"c:\Users\n\Documents\hotshort\marketing_factory\remotion_engine\public\yt_search.mp4"
    os.makedirs(os.path.dirname(final_output), exist_ok=True)
    
    chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    if not os.path.exists(chrome_path):
        chrome_path = None # Fallback to default chromium
        
    print(f"Launching browser (Chrome path: {chrome_path})...")
    
    async with async_playwright() as p:
        iphone_opts = p.devices['iPhone 15 Pro'].copy()
        iphone_opts.update({
            'viewport': {'width': 393, 'height': 852},
            'device_scale_factor': 3,
            'is_mobile': True,
            'has_touch': True,
            'color_scheme': 'dark',
            'user_agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1',
        })
        
        browser = await p.chromium.launch(
            executable_path=chrome_path,
            headless=True,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--enable-features=TouchEvents',
            ]
        )
        
        context = await browser.new_context(
            **iphone_opts,
            record_video_dir=raw_rec_dir,
            record_video_size={'width': 393, 'height': 852}
        )
        
        page = await context.new_page()
        
        print("Navigating to m.youtube.com...")
        await page.goto("https://m.youtube.com", timeout=30000)
        await page.wait_for_timeout(1500)
        
        # 1. Handle Consent if shown
        try:
            consent_btn = await page.wait_for_selector(
                "button[aria-label*='Accept'], button[aria-label*='agree'], button:has-text('Accept all'), button:has-text('I agree')",
                timeout=3000
            )
            if consent_btn:
                print("Accepting consent...")
                await consent_btn.click()
                await page.wait_for_timeout(1000)
        except Exception:
            pass

        # 2. Click Search Box / Icon
        print("Opening search input...")
        search_clicked = False
        for sel in ["input[name='search']", "input.search-input", "button[aria-label='Search YouTube']", "a[href*='/results']"]:
            elem = await page.query_selector(sel)
            if elem:
                await elem.click()
                search_clicked = True
                await page.wait_for_timeout(600)
                break
                
        # 3. Type 'ishowspeed' at 60ms/char
        query = "ishowspeed"
        print(f"Typing '{query}' at 60ms per char...")
        input_elem = await page.query_selector("input[name='search'], input[type='search'], input.search-input, input")
        if input_elem:
            await input_elem.focus()
            await page.keyboard.type(query, delay=60)
            await page.wait_for_timeout(500)
            print("Submitting search...")
            await page.keyboard.press("Enter")
        else:
            # Fallback direct search navigation if input not focused
            await page.goto("https://m.youtube.com/results?search_query=ishowspeed", timeout=20000)
            
        await page.wait_for_timeout(2500)
        
        # 4. Realistic scroll with inertia (cubic ease deceleration)
        print("Scrolling results with touch inertia...")
        scroll_steps = [
            25, 45, 65, 80, 95, 105, 110, 105, 90, 75, 55, 35, 15, 5
        ]
        for delta in scroll_steps:
            await page.mouse.wheel(0, delta)
            await page.wait_for_timeout(60)
            
        await page.wait_for_timeout(1200)
        
        # 5. Tap a video thumbnail
        print("Tapping a video...")
        video_thumb = await page.query_selector("ytd-video-renderer, ytm-video-with-context-renderer, a.media-item-thumbnail-container, a[href*='watch']")
        if video_thumb:
            box = await video_thumb.bounding_box()
            if box:
                # Tap near center
                await page.touchscreen.tap(box['x'] + box['width']/2, box['y'] + box['height']/2)
            else:
                await video_thumb.click()
        else:
            await page.mouse.click(200, 350)
            
        await page.wait_for_timeout(2500)
        
        # 6. Open Share Sheet & Copy Link
        print("Looking for Share button...")
        share_btn = await page.query_selector("button[aria-label*='Share'], button:has-text('Share'), yt-button-renderer:has-text('Share')")
        if share_btn:
            await share_btn.click()
            await page.wait_for_timeout(1200)
            
            # Click Copy link
            copy_btn = await page.query_selector("button:has-text('Copy link'), button[aria-label*='Copy link'], ytd-share-target-renderer:has-text('Copy')")
            if copy_btn:
                print("Clicking Copy link...")
                await copy_btn.click()
                await page.wait_for_timeout(1000)
        else:
            print("Share button not found on this view, holding final frame...")
            await page.wait_for_timeout(1500)
            
        print("Finalizing recording...")
        await context.close()
        await browser.close()
        
    # Find recorded webm
    webms = [f for f in os.listdir(raw_rec_dir) if f.endswith(".webm")]
    if not webms:
        raise RuntimeError("No video recorded by Playwright!")
        
    latest_webm = sorted([os.path.join(raw_rec_dir, f) for f in webms], key=os.path.getmtime)[-1]
    print(f"Recorded webm: {latest_webm}")
    
    # Convert to 60fps MP4 at public/yt_search.mp4
    print(f"Converting to 60fps MP4 -> {final_output}...")
    cmd = [
        "ffmpeg", "-y", "-i", latest_webm,
        "-r", "60",
        "-c:v", "libx264", "-crf", "18", "-preset", "slow",
        "-pix_fmt", "yuv420p",
        final_output
    ]
    subprocess.run(cmd, check=True)
    print(f"SUCCESS! Output ready at: {final_output}")

if __name__ == "__main__":
    asyncio.run(main())
