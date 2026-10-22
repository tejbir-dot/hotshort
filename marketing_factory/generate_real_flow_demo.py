import asyncio
import io
import os
import sys
import math
import subprocess
import shutil
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.abspath("."))
from app import app
from playwright.async_api import async_playwright

with app.test_client() as client:
    with client.session_transaction() as sess:
        sess['_user_id'] = '1'
        sess['_fresh'] = True
    serializer = app.session_interface.get_signing_serializer(app)
    session_cookie_val = serializer.dumps(dict(sess))

def ease_in_out(t):
    return 2 * t * t if t < 0.5 else -1 + (4 - 2 * t) * t

async def capture_studio_flow():
    frames_dir = os.path.abspath("scratch/marketing_factory/flow_frames")
    if os.path.exists(frames_dir):
        shutil.rmtree(frames_dir)
    os.makedirs(frames_dir, exist_ok=True)

    cursor_img = Image.open("marketing_factory/assets/cursor.png").convert("RGBA")
    # Scale cursor for 2x retina display
    cursor_img = cursor_img.resize((int(cursor_img.width * 1.5), int(cursor_img.height * 1.5)))

    fps = 25
    frame_idx = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        context = await browser.new_context(
            viewport={"width": 440, "height": 956},
            device_scale_factor=2, # 880x1912 Retina
            is_mobile=True,
            has_touch=True
        )

        page = await context.new_page()

        # ==============================================================
        # PART 1: YOUTUBE APP - ISHOWSPEED VIDEO (0.0s to 2.8s = 70 frames)
        # ==============================================================
        print("[1/3] Capturing YouTube App with IShowSpeed & Copy Link...")
        yt_html_path = "file:///" + os.path.abspath("marketing_factory/assets/youtube_mobile_speed.html").replace("\\", "/")
        await page.goto(yt_html_path, wait_until="domcontentloaded")
        await asyncio.sleep(0.4)

        share_loc = page.locator('#sharePill')
        share_box = await share_loc.bounding_box()
        share_x = int((share_box['x'] + share_box['width'] / 2) * 2)
        share_y = int((share_box['y'] + share_box['height'] / 2) * 2)

        start_cx, start_cy = 760, 1500

        # Frames 0..14 (0.6s): Cursor moves towards Share button
        for f in range(15):
            t = f / 15.0
            cx = int(start_cx + (share_x - start_cx) * ease_in_out(t))
            cy = int(start_cy + (share_y - start_cy) * ease_in_out(t))
            shot = await page.screenshot(type="jpeg", quality=95)
            im = Image.open(io.BytesIO(shot)).convert("RGBA")
            im.alpha_composite(cursor_img, (cx, cy))
            im.convert("RGB").save(os.path.join(frames_dir, f"frame_{frame_idx:04d}.jpg"), quality=95)
            frame_idx += 1

        # Frame 15: Tap Share button ➔ open share sheet
        await page.evaluate("document.getElementById('shareSheet').classList.add('open')")
        await asyncio.sleep(0.1)

        copy_loc = page.locator('#copyLinkOpt')
        copy_box = await copy_loc.bounding_box()
        copy_x = int((copy_box['x'] + copy_box['width'] / 2) * 2)
        copy_y = int((copy_box['y'] + copy_box['height'] / 2) * 2)

        # Frames 16..30 (0.6s): Sheet slides up, cursor moves to Copy Link button
        for f in range(15):
            t = f / 15.0
            cx = int(share_x + (copy_x - share_x) * ease_in_out(t))
            cy = int(share_y + (copy_y - share_y) * ease_in_out(t))
            shot = await page.screenshot(type="jpeg", quality=95)
            im = Image.open(io.BytesIO(shot)).convert("RGBA")
            im.alpha_composite(cursor_img, (cx, cy))
            im.convert("RGB").save(os.path.join(frames_dir, f"frame_{frame_idx:04d}.jpg"), quality=95)
            frame_idx += 1

        # Frame 31: Tap Copy Link ➔ trigger toast & tap glow
        await page.evaluate("document.getElementById('copiedToast').classList.add('show')")

        # Frames 31..65 (1.4s): Toast shown, copy link highlighted with ripple
        for f in range(35):
            shot = await page.screenshot(type="jpeg", quality=95)
            im = Image.open(io.BytesIO(shot)).convert("RGBA")
            if f < 10:
                radius = 16 + f * 5
                overlay = Image.new("RGBA", im.size, (0, 0, 0, 0))
                odraw = ImageDraw.Draw(overlay)
                odraw.ellipse([copy_x - radius, copy_y - radius, copy_x + radius, copy_y + radius],
                              outline=(255, 0, 85, 220 - f * 20), width=4)
                im = Image.alpha_composite(im, overlay)
            im.alpha_composite(cursor_img, (copy_x - 10, copy_y - 10))
            im.convert("RGB").save(os.path.join(frames_dir, f"frame_{frame_idx:04d}.jpg"), quality=95)
            frame_idx += 1

        print(f"Captured {frame_idx} YouTube Speed frames ({(frame_idx / fps):.2f}s).")

        # ==============================================================
        # PART 2: HOTSHORT HOME - PASTE SPEED LINK (2.8s to 5.2s = 60 frames)
        # ==============================================================
        print("[2/3] Switching to HotShort Landing Page & pasting link...")
        await page.goto("http://127.0.0.1:5000", wait_until="domcontentloaded")
        await asyncio.sleep(0.5)

        input_loc = page.locator('input[name="youtube_url"]').first
        btn_loc = page.locator('#homeAnalyzeBtn').first
        await input_loc.wait_for(state="visible", timeout=5000)

        input_box = await input_loc.bounding_box()
        btn_box = await btn_loc.bounding_box()

        inp_x = int((input_box['x'] + 70) * 2)
        inp_y = int((input_box['y'] + input_box['height'] / 2) * 2)
        btn_x = int((btn_box['x'] + btn_box['width'] / 2) * 2)
        btn_y = int((btn_box['y'] + btn_box['height'] / 2) * 2)

        speed_url = "https://youtube.com/watch?v=speed_brazil"

        # Frames 66..77 (0.5s): Cursor moves to input box
        start_sw_x, start_sw_y = 440, 1600
        for f in range(12):
            t = f / 12.0
            cx = int(start_sw_x + (inp_x - start_sw_x) * ease_in_out(t))
            cy = int(start_sw_y + (inp_y - start_sw_y) * ease_in_out(t))
            shot = await page.screenshot(type="jpeg", quality=95)
            im = Image.open(io.BytesIO(shot)).convert("RGBA")
            im.alpha_composite(cursor_img, (cx, cy))
            im.convert("RGB").save(os.path.join(frames_dir, f"frame_{frame_idx:04d}.jpg"), quality=95)
            frame_idx += 1

        # Frames 78..102 (1.0s): Paste link / type rapidly
        await input_loc.focus()
        chars = len(speed_url)
        for f in range(25):
            chars_to_show = int((f + 1) / 25.0 * chars)
            current_str = speed_url[:chars_to_show]
            await input_loc.fill(current_str)
            text_cx = inp_x + int(chars_to_show * 13)
            shot = await page.screenshot(type="jpeg", quality=95)
            im = Image.open(io.BytesIO(shot)).convert("RGBA")
            im.alpha_composite(cursor_img, (min(760, text_cx), inp_y))
            im.convert("RGB").save(os.path.join(frames_dir, f"frame_{frame_idx:04d}.jpg"), quality=95)
            frame_idx += 1

        # Frames 103..114 (0.5s): Move cursor to Analyze button
        for f in range(12):
            t = f / 12.0
            cx = int(inp_x + (btn_x - inp_x) * ease_in_out(t))
            cy = int(inp_y + (btn_y - inp_y) * ease_in_out(t))
            shot = await page.screenshot(type="jpeg", quality=95)
            im = Image.open(io.BytesIO(shot)).convert("RGBA")
            im.alpha_composite(cursor_img, (cx, cy))
            im.convert("RGB").save(os.path.join(frames_dir, f"frame_{frame_idx:04d}.jpg"), quality=95)
            frame_idx += 1

        # Frames 115..125 (0.4s): Click button with gold ripple ring
        for f in range(11):
            shot = await page.screenshot(type="jpeg", quality=95)
            im = Image.open(io.BytesIO(shot)).convert("RGBA")
            if f < 8:
                radius = 12 + f * 6
                overlay = Image.new("RGBA", im.size, (0, 0, 0, 0))
                odraw = ImageDraw.Draw(overlay)
                odraw.ellipse([btn_x - radius, btn_y - radius, btn_x + radius, btn_y + radius],
                              outline=(255, 200, 80, 220 - f * 25), width=4)
                im = Image.alpha_composite(im, overlay)
            im.alpha_composite(cursor_img, (btn_x - 10, btn_y - 10))
            im.convert("RGB").save(os.path.join(frames_dir, f"frame_{frame_idx:04d}.jpg"), quality=95)
            frame_idx += 1

        print(f"Captured {frame_idx} Home Page frames (total {(frame_idx / fps):.2f}s).")

        # ==============================================================
        # PART 3: RESULTS PAGE & CAROUSEL SCROLL (185 frames = 7.4s)
        # ==============================================================
        print("[3/3] Loading Results Page & scrolling carousel...")
        await context.add_cookies([{
            "name": "session",
            "value": session_cookie_val,
            "domain": "127.0.0.1",
            "path": "/"
        }])

        await page.goto("http://127.0.0.1:5000/results/415951b5-941", wait_until="domcontentloaded")
        await page.locator('#carousel .clip-card').first.wait_for(state="visible", timeout=10000)
        await asyncio.sleep(1.0)

        # Reset carousel scroll to 0
        await page.evaluate("document.getElementById('carousel').scrollTo({left: 0, behavior: 'auto'})")
        await asyncio.sleep(0.3)

        # Phase A: Card 1 in focus (35 frames = 1.4s)
        card1_shot = await page.screenshot(type="jpeg", quality=95)
        for _ in range(35):
            with open(os.path.join(frames_dir, f"frame_{frame_idx:04d}.jpg"), "wb") as f_out:
                f_out.write(card1_shot)
            frame_idx += 1

        # Phase B: Smooth scroll from Card 1 to Card 2 (scrollLeft 0 -> 350, 45 frames = 1.8s)
        print("  Smoothly scrolling to Card 2...")
        scroll_start = 0
        scroll_target1 = 350
        scroll_frames = 45
        for f in range(scroll_frames):
            t = f / float(scroll_frames)
            current_x = int(scroll_start + (scroll_target1 - scroll_start) * ease_in_out(t))
            await page.evaluate(f"document.getElementById('carousel').scrollTo({{left: {current_x}, behavior: 'auto'}})")
            shot = await page.screenshot(type="jpeg", quality=95)
            with open(os.path.join(frames_dir, f"frame_{frame_idx:04d}.jpg"), "wb") as f_out:
                f_out.write(shot)
            frame_idx += 1

        # Phase C: Card 2 in focus (35 frames = 1.4s)
        card2_shot = await page.screenshot(type="jpeg", quality=95)
        for _ in range(35):
            with open(os.path.join(frames_dir, f"frame_{frame_idx:04d}.jpg"), "wb") as f_out:
                f_out.write(card2_shot)
            frame_idx += 1

        # Phase D: Smooth scroll from Card 2 to Card 3 (scrollLeft 350 -> 700, 45 frames = 1.8s)
        print("  Smoothly scrolling to Card 3...")
        scroll_start2 = 350
        scroll_target2 = 700
        for f in range(scroll_frames):
            t = f / float(scroll_frames)
            current_x = int(scroll_start2 + (scroll_target2 - scroll_start2) * ease_in_out(t))
            await page.evaluate(f"document.getElementById('carousel').scrollTo({{left: {current_x}, behavior: 'auto'}})")
            shot = await page.screenshot(type="jpeg", quality=95)
            with open(os.path.join(frames_dir, f"frame_{frame_idx:04d}.jpg"), "wb") as f_out:
                f_out.write(shot)
            frame_idx += 1

        # Phase E: Card 3 in focus (30 frames = 1.2s)
        card3_shot = await page.screenshot(type="jpeg", quality=95)
        for _ in range(30):
            with open(os.path.join(frames_dir, f"frame_{frame_idx:04d}.jpg"), "wb") as f_out:
                f_out.write(card3_shot)
            frame_idx += 1

        print(f"Total high-res frames captured: {frame_idx} ({frame_idx / fps:.2f} seconds @ {fps} fps)")
        await browser.close()

    # Convert frames to ultra-high-clarity MP4 (Retina 880x1912)
    output_mp4 = os.path.abspath("marketing_factory/assets/real_app_demo.mp4")
    print(f"Encoding frames to {output_mp4} with ffmpeg (CRF 12, slow preset)...")
    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-i", os.path.join(frames_dir, "frame_%04d.jpg"),
        "-c:v", "libx264",
        "-crf", "12",
        "-preset", "slow",
        "-pix_fmt", "yuv420p",
        output_mp4
    ]
    subprocess.run(ffmpeg_cmd, check=True)
    print(f"Master App Demo successfully generated: {output_mp4}")

if __name__ == "__main__":
    asyncio.run(capture_studio_flow())
