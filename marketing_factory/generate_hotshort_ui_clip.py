import os
import math
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import numpy as np
import subprocess

def get_font(size, bold=True):
    candidates = [
        "C:/Windows/Fonts/Montserrat-Bold.ttf" if bold else "C:/Windows/Fonts/Montserrat-Regular.ttf",
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()

def render_hotshort_ui_frame(w=580, h=1020, t=0.0):
    """
    Renders a futuristic HotShort mobile web app UI frame at time t (0 to 10s).
    """
    img = Image.new("RGBA", (w, h), (10, 12, 18, 255))
    draw = ImageDraw.Draw(img)

    # 1. Subtle ambient purple/blue glow at top and center
    ambient = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    a_draw = ImageDraw.Draw(ambient)
    a_draw.ellipse([w // 2 - 200, 100, w // 2 + 200, 500], fill=(117, 91, 255, 35))
    a_draw.ellipse([w // 2 - 150, 400, w // 2 + 150, 700], fill=(246, 196, 83, 20))
    ambient = ambient.filter(ImageFilter.GaussianBlur(radius=60))
    img = Image.alpha_composite(img, ambient)
    draw = ImageDraw.Draw(img)

    # 2. Header: Logo & Status
    font_logo = get_font(28, bold=True)
    draw.text((40, 50), "HOTSHORT AI", fill=(255, 255, 255, 255), font=font_logo)
    
    # Pro Badge
    font_badge = get_font(18, bold=True)
    draw.rounded_rectangle([250, 52, 330, 80], radius=8, fill=(117, 91, 255, 200))
    draw.text((290, 66), "PRO", fill=(255, 255, 255, 255), font=font_badge, anchor="mm")

    # Available credits badge
    font_sub = get_font(20, bold=False)
    draw.text((w - 40, 66), "100 Credits", fill=(180, 190, 210, 255), font=font_sub, anchor="rm")

    # Divider
    draw.line([(40, 100), (w - 40, 100)], fill=(40, 45, 60, 255), width=1)

    # 3. Main Title
    font_title = get_font(34, bold=True)
    draw.text((w // 2, 150), "Turn Streams Into Viral Shorts", fill=(255, 255, 255, 255), font=font_title, anchor="mm")
    
    font_desc = get_font(20, bold=False)
    draw.text((w // 2, 190), "Auto-detect hooks, crop faces, and add viral captions", fill=(140, 150, 175, 255), font=font_desc, anchor="mm")

    # 4. Input Card (URL Box)
    box_y = 230
    box_h = 75
    draw.rounded_rectangle([40, box_y, w - 40, box_y + box_h], radius=16, fill=(18, 22, 32, 255), outline=(60, 70, 95, 255), width=2)
    
    # Simulating URL paste between t=1.5s and t=3.0s
    full_url = "https://youtube.com/watch?v=viral_stream"
    if t < 1.5:
        display_text = "Paste YouTube or Kick Link..."
        text_color = (100, 110, 130, 255)
    elif 1.5 <= t < 3.2:
        chars = int((t - 1.5) / 1.7 * len(full_url))
        display_text = full_url[:chars] + "|"
        text_color = (255, 255, 255, 255)
    else:
        display_text = full_url
        text_color = (255, 255, 255, 255)

    font_input = get_font(22, bold=False)
    draw.text((60, box_y + box_h // 2), display_text, fill=text_color, font=font_input, anchor="lm")

    # Paste button inside input box
    if t < 1.5:
        p_btn_w, p_btn_h = 80, 42
        p_btn_x = w - 40 - p_btn_w - 12
        p_btn_y = box_y + (box_h - p_btn_h) // 2
        draw.rounded_rectangle([p_btn_x, p_btn_y, p_btn_x + p_btn_w, p_btn_y + p_btn_h], radius=10, fill=(40, 48, 70, 255))
        draw.text((p_btn_x + p_btn_w // 2, p_btn_y + p_btn_h // 2), "PASTE", fill=(200, 215, 255, 255), font=font_badge, anchor="mm")

    # 5. Settings Card (Vibe / Captions / B-Roll)
    card_y = 330
    card_h = 320
    draw.rounded_rectangle([40, card_y, w - 40, card_y + card_h], radius=18, fill=(16, 20, 28, 255), outline=(35, 40, 55, 255), width=1)

    # Setting Row 1: Viral Captions
    draw.text((65, card_y + 35), "CAPTION STYLE", fill=(140, 150, 175, 255), font=font_badge)
    # Selected Pill
    draw.rounded_rectangle([65, card_y + 60, 260, card_y + 110], radius=12, fill=(117, 91, 255, 40), outline=(117, 91, 255, 220), width=2)
    draw.text((162, card_y + 85), "Hormozi Bold", fill=(255, 255, 255, 255), font=get_font(20, bold=True), anchor="mm")
    
    draw.rounded_rectangle([280, card_y + 60, 475, card_y + 110], radius=12, fill=(25, 30, 42, 255), outline=(50, 58, 80, 255), width=1)
    draw.text((377, card_y + 85), "Dynamic Glow", fill=(160, 170, 195, 255), font=get_font(20, bold=False), anchor="mm")

    # Setting Row 2: B-Roll & Tracking
    draw.text((65, card_y + 140), "AUTO-FACE TRACKING", fill=(140, 150, 175, 255), font=font_badge)
    draw.rounded_rectangle([65, card_y + 165, 300, card_y + 215], radius=12, fill=(246, 196, 83, 30), outline=(246, 196, 83, 200), width=2)
    draw.text((182, card_y + 190), "AI Smart Crop 9:16", fill=(255, 255, 255, 255), font=get_font(20, bold=True), anchor="mm")

    # Setting Row 3: Narrative Arcs
    draw.text((65, card_y + 245), "HOOK HUNTER ENGINE", fill=(140, 150, 175, 255), font=font_badge)
    draw.text((65, card_y + 275), "Groq Cortex Multi-Arc Analysis", fill=(100, 220, 150, 255), font=get_font(19, bold=True))

    # 6. Big Action Button: "IGNITE VIRAL SHORTS" (at y=680)
    btn_y = 680
    btn_h = 75
    btn_x1, btn_x2 = 40, w - 40
    
    # Click state at t >= 5.5s
    is_clicked = t >= 5.5
    if is_clicked:
        # Pressed glowing gradient
        draw.rounded_rectangle([btn_x1, btn_y, btn_x2, btn_y + btn_h], radius=18, fill=(80, 60, 220, 255), outline=(180, 160, 255, 255), width=3)
        # Pulse spinner text
        pulse_text = "GENERATING 3 VIRAL SHORTS (94%)..."
        draw.text((w // 2, btn_y + btn_h // 2), pulse_text, fill=(255, 255, 255, 255), font=get_font(22, bold=True), anchor="mm")
        
        # Progress bar under button
        progress = min(1.0, (t - 5.5) / 3.0)
        p_w = int((btn_x2 - btn_x1 - 20) * progress)
        draw.rounded_rectangle([btn_x1 + 10, btn_y + btn_h - 12, btn_x1 + 10 + p_w, btn_y + btn_h - 6], radius=3, fill=(246, 196, 83, 255))
    else:
        # Normal state
        draw.rounded_rectangle([btn_x1, btn_y, btn_x2, btn_y + btn_h], radius=18, fill=(117, 91, 255, 255), outline=(160, 140, 255, 255), width=2)
        draw.text((w // 2, btn_y + btn_h // 2), "IGNITE VIRAL CLIPS", fill=(255, 255, 255, 255), font=get_font(24, bold=True), anchor="mm")

    # 7. Subtle footer info
    font_foot = get_font(18, bold=False)
    draw.text((w // 2, 790), "Powered by HotShort AI Engine • Ultra Fast Render", fill=(100, 110, 135, 255), font=font_foot, anchor="mm")

    return np.array(img)

def generate_hotshort_screen_video(output_mp4="marketing_factory/assets/hotshort_screen_demo.mp4", duration=11.0, fps=30):
    os.makedirs(os.path.dirname(output_mp4), exist_ok=True)
    total_frames = int(duration * fps)
    print(f"Generating {total_frames} frames of HotShort UI animation...")

    # Use ffmpeg pipe for ultra fast encoding
    cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo",
        "-vcodec", "rawvideo",
        "-s", "580x1020",
        "-pix_fmt", "rgba",
        "-r", str(fps),
        "-i", "-",
        "-an",
        "-vcodec", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "ultrafast",
        output_mp4
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    for i in range(total_frames):
        t = i / fps
        arr = render_hotshort_ui_frame(580, 1020, t=t)
        proc.stdin.write(arr.tobytes())

    proc.stdin.close()
    proc.wait()
    print(f"HotShort animated UI screen video generated: {output_mp4}")

if __name__ == "__main__":
    generate_hotshort_screen_video()
