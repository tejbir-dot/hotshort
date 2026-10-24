import asyncio
import io
import os
import sys
import math
import subprocess
import shutil
import cv2
import numpy as np
from PIL import Image, ImageDraw

def ease_in_out_cubic(t):
    t = max(0.0, min(1.0, t))
    return 4 * t * t * t if t < 0.5 else 1 - math.pow(-2 * t + 2, 3) / 2

def ease_out_back(t, s=1.70158):
    t = max(0.0, min(1.0, t))
    t = t - 1.0
    return t * t * ((s + 1.0) * t + s) + 1.0

async def capture_real_flow():
    print("=" * 60)
    print("UPGRADING REAL APP DEMO TRACK (FEATURE SHOWCASE + MOTION MATH)")
    print("=" * 60)
    
    frames_dir = os.path.abspath("scratch/marketing_factory/flow_frames")
    if os.path.exists(frames_dir):
        shutil.rmtree(frames_dir)
    os.makedirs(frames_dir, exist_ok=True)
    
    fps = 25
    target_w, target_h = 880, 1912  # 2x mobile retina resolution
    
    # -------------------------------------------------------------
    # PART 1: Real InShot YouTube Screen Recording (4.8s = 120 frames)
    # -------------------------------------------------------------
    print("[1/3] Processing Real InShot Mobile YouTube Recording...")
    inshot_path = "marketing_factory/output/InShot_20261023_025813860 (1).mp4"
    cap_in = cv2.VideoCapture(inshot_path)
    
    num_part1_frames = 120
    frame_idx = 0
    
    for i in range(num_part1_frames):
        source_frame_num = int((i / float(num_part1_frames - 1)) * 180)
        cap_in.set(cv2.CAP_PROP_POS_FRAMES, source_frame_num)
        ret, frame = cap_in.read()
        if not ret:
            break
        
        fh, fw = frame.shape[:2]
        scale = max(target_w / fw, target_h / fh)
        nw, nh = int(round(fw * scale)), int(round(fh * scale))
        resized = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_LANCZOS4)
        x_off = (nw - target_w) // 2
        y_off = (nh - target_h) // 2
        cropped = resized[y_off : y_off + target_h, x_off : x_off + target_w]
        
        im = Image.fromarray(cv2.cvtColor(cropped, cv2.COLOR_BGR2RGB)).convert("RGBA")
        
        # When near the end (Copy Link tapped, around i >= 105), add spring tap ripple
        if 105 <= i <= 118:
            ring_f = (i - 105) / 13.0
            radius = int(16 + ease_out_back(ring_f, s=1.5) * 55)
            cx = target_w // 2
            cy = int(target_h * 0.94)  # "Copy link" position at bottom
            overlay = Image.new("RGBA", im.size, (0, 0, 0, 0))
            odraw = ImageDraw.Draw(overlay)
            alpha = max(0, int(230 * (1.0 - ring_f)))
            odraw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], outline=(255, 0, 85, alpha), width=5)
            im = Image.alpha_composite(im, overlay)
            
        out_frame_path = os.path.join(frames_dir, f"frame_{frame_idx:04d}.jpg")
        im.convert("RGB").save(out_frame_path, quality=95)
        frame_idx += 1
        
    cap_in.release()
    print(f"  Captured {frame_idx} Part 1 frames (4.80s @ 25fps).")
    
    # -------------------------------------------------------------
    # PART 2: HotShort Studio Feature Showcase (3.8s = 95 frames)
    # -------------------------------------------------------------
    print("[2/3] Capturing Silicon Valley Feature Showcase with Micro-Interactions...")
    cursor_img = Image.open("marketing_factory/assets/cursor.png").convert("RGBA")
    cursor_img = cursor_img.resize((int(cursor_img.width * 1.5), int(cursor_img.height * 1.5)))
    
    html_path = "file:///" + os.path.abspath("marketing_factory/assets/hotshort_mobile_studio.html").replace("\\", "/")
    
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        context = await browser.new_context(
            viewport={"width": 440, "height": 956},
            device_scale_factor=2, # 880x1912
            is_mobile=True,
            has_touch=True
        )
        page = await context.new_page()
        await page.goto(html_path, wait_until="domcontentloaded")
        await asyncio.sleep(0.3)
        
        # Coordinates in 2x space:
        # Start cursor position:
        c_cur = [550, 1600]
        
        # Sub-sequence A: Link pasted, cursor glides to Caption Preset dropdown (18 frames = 0.72s)
        await page.evaluate("document.getElementById('inputBox').classList.add('focused')")
        dropdown_target = [440, 852]
        
        for f in range(18):
            t = f / 18.0
            # Organic human arc
            arc_offset = int(35 * math.sin(math.pi * t))
            cx = int(c_cur[0] + (dropdown_target[0] - c_cur[0]) * ease_in_out_cubic(t)) - arc_offset
            cy = int(c_cur[1] + (dropdown_target[1] - c_cur[1]) * ease_in_out_cubic(t))
            shot = await page.screenshot(type="jpeg", quality=95)
            im = Image.open(io.BytesIO(shot)).convert("RGBA")
            im.alpha_composite(cursor_img, (cx, cy))
            im.convert("RGB").save(os.path.join(frames_dir, f"frame_{frame_idx:04d}.jpg"), quality=95)
            frame_idx += 1
            
        c_cur = dropdown_target
        
        # Sub-sequence B: Click Dropdown -> Sheet slides up with spring blur (20 frames = 0.80s)
        await page.evaluate("""
            document.getElementById('dropdownTrigger').classList.add('active');
            document.getElementById('sheetOverlay').classList.add('open');
        """)
        
        hormozi_target = [440, 1480]
        for f in range(20):
            t = f / 20.0
            cx = int(c_cur[0] + (hormozi_target[0] - c_cur[0]) * ease_in_out_cubic(t))
            cy = int(c_cur[1] + (hormozi_target[1] - c_cur[1]) * ease_in_out_cubic(t))
            shot = await page.screenshot(type="jpeg", quality=95)
            im = Image.open(io.BytesIO(shot)).convert("RGBA")
            
            # Click ripple on dropdown click (first 8 frames)
            if f < 8:
                r_scale = ease_out_back(f / 8.0, s=1.2)
                rad = int(12 + r_scale * 30)
                ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
                od = ImageDraw.Draw(ov)
                od.ellipse([c_cur[0] - rad, c_cur[1] - rad, c_cur[0] + rad, c_cur[1] + rad],
                           outline=(255, 170, 0, int(220 * (1 - f / 8.0))), width=4)
                im = Image.alpha_composite(im, ov)
                
            im.alpha_composite(cursor_img, (cx, cy))
            im.convert("RGB").save(os.path.join(frames_dir, f"frame_{frame_idx:04d}.jpg"), quality=95)
            frame_idx += 1
            
        c_cur = hormozi_target
        
        # Sub-sequence C: Click "Hormozi Bold" -> Sheet closes (18 frames = 0.72s)
        await page.evaluate("""
            document.getElementById('optHormozi').classList.add('selected');
        """)
        
        # Wait 4 frames then close sheet
        toggle_target = [754, 1050]
        for f in range(18):
            if f == 5:
                await page.evaluate("""
                    document.getElementById('sheetOverlay').classList.remove('open');
                    document.getElementById('dropdownTrigger').classList.remove('active');
                """)
            t = f / 18.0
            cx = int(c_cur[0] + (toggle_target[0] - c_cur[0]) * ease_in_out_cubic(t))
            cy = int(c_cur[1] + (toggle_target[1] - c_cur[1]) * ease_in_out_cubic(t))
            shot = await page.screenshot(type="jpeg", quality=95)
            im = Image.open(io.BytesIO(shot)).convert("RGBA")
            
            if f < 8:
                rad = int(10 + f * 5)
                ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
                od = ImageDraw.Draw(ov)
                od.ellipse([c_cur[0] - rad, c_cur[1] - rad, c_cur[0] + rad, c_cur[1] + rad],
                           outline=(255, 170, 0, int(220 * (1 - f / 8.0))), width=4)
                im = Image.alpha_composite(im, ov)
                
            im.alpha_composite(cursor_img, (cx, cy))
            im.convert("RGB").save(os.path.join(frames_dir, f"frame_{frame_idx:04d}.jpg"), quality=95)
            frame_idx += 1
            
        c_cur = toggle_target
        
        # Sub-sequence D: Click Face-Tracking Switch ON -> Glide to Ignite (20 frames = 0.80s)
        await page.evaluate("""
            document.getElementById('toggleSwitch').classList.add('on');
        """)
        
        ignite_target = [440, 1240]
        for f in range(20):
            t = f / 20.0
            cx = int(c_cur[0] + (ignite_target[0] - c_cur[0]) * ease_in_out_cubic(t))
            cy = int(c_cur[1] + (ignite_target[1] - c_cur[1]) * ease_in_out_cubic(t))
            shot = await page.screenshot(type="jpeg", quality=95)
            im = Image.open(io.BytesIO(shot)).convert("RGBA")
            
            # Switch toggle click pulse
            if f < 8:
                rad = int(10 + f * 5)
                ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
                od = ImageDraw.Draw(ov)
                od.ellipse([c_cur[0] - rad, c_cur[1] - rad, c_cur[0] + rad, c_cur[1] + rad],
                           outline=(0, 230, 118, int(240 * (1 - f / 8.0))), width=4)
                im = Image.alpha_composite(im, ov)
                
            im.alpha_composite(cursor_img, (cx, cy))
            im.convert("RGB").save(os.path.join(frames_dir, f"frame_{frame_idx:04d}.jpg"), quality=95)
            frame_idx += 1
            
        c_cur = ignite_target
        
        # Sub-sequence E: Click Ignite Button with golden spring ripple & Toast reveal (19 frames = 0.76s)
        await page.evaluate("""
            document.getElementById('igniteBtn').classList.add('clicked');
            document.getElementById('analysisToast').classList.add('show');
        """)
        
        for f in range(19):
            shot = await page.screenshot(type="jpeg", quality=95)
            im = Image.open(io.BytesIO(shot)).convert("RGBA")
            if f < 14:
                r_scale = ease_out_back(f / 14.0, s=1.4)
                rad = int(16 + r_scale * 70)
                ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
                od = ImageDraw.Draw(ov)
                alpha = max(0, int(240 * (1.0 - f / 14.0)))
                od.ellipse([c_cur[0] - rad, c_cur[1] - rad, c_cur[0] + rad, c_cur[1] + rad],
                           outline=(255, 170, 0, alpha), width=5)
                im = Image.alpha_composite(im, ov)
                
            im.alpha_composite(cursor_img, (c_cur[0] - 10, c_cur[1] - 10))
            im.convert("RGB").save(os.path.join(frames_dir, f"frame_{frame_idx:04d}.jpg"), quality=95)
            frame_idx += 1
            
        await browser.close()
        
    print(f"  Captured Part 2 frames (total frame_idx = {frame_idx}).")
    
    # -------------------------------------------------------------
    # PART 3: Reveal Full Generated Viral Speed Short Playing (4.6s = 115 frames)
    # -------------------------------------------------------------
    print("[3/3] Appending Playing Crystal-Clear Viral Speed Short...")
    short_clip_path = "marketing_factory/output/a3f63caa_branded_1_388_467.mp4"
    if not os.path.exists(short_clip_path):
        short_clip_path = "static/clip_files/77e3be44_branded_6_570_641.mp4"
        
    cap_short = cv2.VideoCapture(short_clip_path)
    cap_short.set(cv2.CAP_PROP_POS_FRAMES, 60)
    
    num_part3_frames = 115
    for _ in range(num_part3_frames):
        ret, s_frame = cap_short.read()
        if not ret:
            cap_short.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, s_frame = cap_short.read()
            
        sf_h, sf_w = s_frame.shape[:2]
        scale = max(target_w / sf_w, target_h / sf_h)
        nw, nh = int(round(sf_w * scale)), int(round(sf_h * scale))
        resized = cv2.resize(s_frame, (nw, nh), interpolation=cv2.INTER_LANCZOS4)
        x_off = (nw - target_w) // 2
        y_off = (nh - target_h) // 2
        cropped = resized[y_off : y_off + target_h, x_off : x_off + target_w]
        
        im = Image.fromarray(cv2.cvtColor(cropped, cv2.COLOR_BGR2RGB))
        out_frame_path = os.path.join(frames_dir, f"frame_{frame_idx:04d}.jpg")
        im.save(out_frame_path, quality=95)
        frame_idx += 1
        
    cap_short.release()
    print(f"Total Master Demo Frames: {frame_idx} ({(frame_idx / fps):.2f}s @ {fps}fps)")
    
    # Encode to MP4
    output_mp4 = os.path.abspath("marketing_factory/assets/real_app_demo.mp4")
    print(f"Encoding upgraded master demo track to {output_mp4} with ffmpeg (CRF 14)...")
    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-i", os.path.join(frames_dir, "frame_%04d.jpg"),
        "-c:v", "libx264",
        "-crf", "14",
        "-preset", "slow",
        "-pix_fmt", "yuv420p",
        output_mp4
    ]
    subprocess.run(ffmpeg_cmd, check=True)
    print(f"SUCCESS: Upgraded Master App Demo generated at {output_mp4}")

if __name__ == "__main__":
    asyncio.run(capture_real_flow())
