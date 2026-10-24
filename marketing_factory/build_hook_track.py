import os
import cv2
import numpy as np
import math
from PIL import Image, ImageDraw, ImageFont, ImageFilter

def ease_out_back(t, s=1.70158):
    t = max(0.0, min(1.0, t))
    t = t - 1.0
    return t * t * ((s + 1.0) * t + s) + 1.0

def create_feathered_shadow(w, h, radius=22, blur_radius=18, y_offset=12, shadow_alpha=180):
    pad = blur_radius * 2 + 10
    sw, sh = w + pad * 2, h + pad * 2
    shadow_img = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    ds = ImageDraw.Draw(shadow_img)
    ds.rounded_rectangle([pad, pad + y_offset, pad + w - 1, pad + y_offset + h - 1],
                         radius=radius, fill=(0, 0, 0, shadow_alpha))
    shadow_img = shadow_img.filter(ImageFilter.GaussianBlur(blur_radius))
    return shadow_img, pad

def create_card_frame(video_frame, w, h, radius=22, border_w=3, pill_text="34.3M", is_viral=False):
    vf_h, vf_w = video_frame.shape[:2]
    scale = max(w / vf_w, h / vf_h)
    nw, nh = int(round(vf_w * scale)), int(round(vf_h * scale))
    resized = cv2.resize(video_frame, (nw, nh), interpolation=cv2.INTER_LANCZOS4)
    x_off = (nw - w) // 2
    y_off = (nh - h) // 2
    cropped = resized[y_off : y_off + h, x_off : x_off + w]
    cropped_rgb = cv2.cvtColor(cropped, cv2.COLOR_BGR2RGB)
    im = Image.fromarray(cropped_rgb).convert("RGBA")
    
    # Rounded mask
    mask = Image.new("L", (w, h), 0)
    draw_m = ImageDraw.Draw(mask)
    draw_m.rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)
    
    # Crisp 3D border
    border = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw_b = ImageDraw.Draw(border)
    draw_b.rounded_rectangle([1, 1, w - 2, h - 2], radius=radius, outline=(255, 255, 255, 230), width=border_w)
    
    card = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    card.paste(im, (0, 0), mask)
    card.alpha_composite(border)
    
    # Pill Badge at bottom
    pw, ph = int(w * 0.65), 32
    px = (w - pw) // 2
    py = h - ph - 14
    pill = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
    dp = ImageDraw.Draw(pill)
    dp.rounded_rectangle([0, 0, pw - 1, ph - 1], radius=ph // 2, fill=(10, 10, 15, 225), outline=(255, 255, 255, 140), width=1)
    
    try:
        font = ImageFont.truetype("arialbd.ttf", 16)
    except:
        font = ImageFont.load_default()
    
    bbox = dp.textbbox((0, 0), pill_text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    
    tri_w = 10
    total_content_w = tri_w + 6 + tw
    start_x = (pw - total_content_w) // 2
    cy_text = (ph - th) // 2 - 1
    cy_tri = ph // 2
    dp.polygon([(start_x, cy_tri - 6), (start_x, cy_tri + 6), (start_x + 9, cy_tri)], fill=(255, 255, 255, 255))
    dp.text((start_x + 15, cy_text), pill_text, font=font, fill=(255, 255, 255, 255))
    
    card.alpha_composite(pill, (px, py))
    
    if is_viral:
        vw, vh = int(w * 0.8), 44
        vx = (w - vw) // 2
        vy = h - ph - 14 - vh - 4
        viral_im = Image.new("RGBA", (vw, vh), (0, 0, 0, 0))
        dv = ImageDraw.Draw(viral_im)
        try:
            vfont = ImageFont.truetype("impact.ttf", 36)
        except:
            vfont = font
        vbox = dv.textbbox((0, 0), "VIRAL", font=vfont)
        vtw = vbox[2] - vbox[0]
        vth = vbox[3] - vbox[1]
        vx_pos = (vw - vtw) // 2
        vy_pos = (vh - vth) // 2
        dv.text((vx_pos + 2, vy_pos + 2), "VIRAL", font=vfont, fill=(0, 0, 0, 240))
        dv.text((vx_pos + 1, vy_pos + 1), "VIRAL", font=vfont, fill=(255, 20, 50, 255))
        dv.text((vx_pos, vy_pos), "VIRAL", font=vfont, fill=(255, 255, 255, 255))
        card.alpha_composite(viral_im, (vx, vy))
        
    return card

def render_bouncing_card(canvas, card_img, base_center_x, base_center_y, t, t_pop_start, pop_duration=0.38, spring_s=2.2):
    """
    Renders card with sequential spring bounce (Ease-Out Back 112% overshoot) and feathered 3D drop shadow!
    """
    if t < t_pop_start:
        return # Hidden until its pop cue
        
    w, h = card_img.size
    
    if t < t_pop_start + pop_duration:
        p = (t - t_pop_start) / float(pop_duration)
        scale = ease_out_back(p, s=spring_s)
    else:
        scale = 1.0
        
    if scale <= 0.01:
        return
        
    cur_w = max(1, int(round(w * scale)))
    cur_h = max(1, int(round(h * scale)))
    scaled_card = card_img.resize((cur_w, cur_h), Image.Resampling.LANCZOS)
    
    # 3D Feathered Drop Shadow
    shadow, pad = create_feathered_shadow(cur_w, cur_h, radius=int(22 * scale), blur_radius=int(18 * scale), y_offset=int(12 * scale), shadow_alpha=int(190 * min(1.0, scale)))
    
    paste_x = int(round(base_center_x - cur_w / 2.0))
    paste_y = int(round(base_center_y - cur_h / 2.0))
    
    # Paste shadow first
    canvas.alpha_composite(shadow, (paste_x - pad, paste_y - pad))
    # Paste card on top
    canvas.alpha_composite(scaled_card, (paste_x, paste_y))

def build_hook_video(output_path="marketing_factory/assets/hook_track.mp4", duration=4.5, fps=25):
    print("=" * 60)
    print("BUILDING MOTION-MATH HOOK TRACK (SEQUENTIAL BOUNCES + 3D SHADOWS)")
    print("=" * 60)
    
    total_frames = int(duration * fps) # 112 frames
    temp_dir = os.path.abspath("scratch/marketing_factory/hook_frames")
    os.makedirs(temp_dir, exist_ok=True)
    
    cap_bg = cv2.VideoCapture("marketing_factory/assets/bg_generativo.mp4")
    
    # Card videos
    cap_c = cv2.VideoCapture("marketing_factory/output/a3f63caa_branded_1_388_467.mp4")
    cap_c.set(cv2.CAP_PROP_POS_FRAMES, 100)
    
    cap_l = cv2.VideoCapture("static/clip_files/77e3be44_branded_6_570_641.mp4")
    cap_l.set(cv2.CAP_PROP_POS_FRAMES, 50)
    
    cap_r = cv2.VideoCapture("static/clip_files/77e3be44_branded_7_775_873.mp4")
    cap_r.set(cv2.CAP_PROP_POS_FRAMES, 80)
    
    # Avatar
    cap_av = cv2.VideoCapture("marketing_factory/assets/Man_speaking_with_VR_headset_20261021215440.mp4")
    cap_av_m = cv2.VideoCapture("marketing_factory/assets/avatar_mask.mp4")
    av_w = 640
    
    # Card base dimensions & centers:
    # Left: w=205, h=360, center_x = 25 + 205/2 = 127, center_y = 115 + 360/2 = 295
    # Center: w=250, h=430, center_x = 235 + 250/2 = 360, center_y = 70 + 430/2 = 285
    # Right: w=205, h=360, center_x = 490 + 205/2 = 592, center_y = 115 + 360/2 = 295
    c_left_cx, c_left_cy = 127, 295
    c_center_cx, c_center_cy = 360, 285
    c_right_cx, c_right_cy = 592, 295
    
    for f in range(total_frames):
        t = f / float(fps)
        
        ret_bg, f_bg = cap_bg.read()
        if not ret_bg:
            cap_bg.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret_bg, f_bg = cap_bg.read()
            
        ret_c, f_c = cap_c.read()
        if not ret_c:
            cap_c.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret_c, f_c = cap_c.read()
            
        ret_l, f_l = cap_l.read()
        if not ret_l:
            cap_l.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret_l, f_l = cap_l.read()
            
        ret_r, f_r = cap_r.read()
        if not ret_r:
            cap_r.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret_r, f_r = cap_r.read()
            
        ret_a, f_a = cap_av.read()
        ret_am, f_am = cap_av_m.read()
        if not ret_a:
            cap_av.set(cv2.CAP_PROP_POS_FRAMES, 0)
            cap_av_m.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret_a, f_a = cap_av.read()
            ret_am, f_am = cap_av_m.read()
            
        # Canvas
        bg_rgb = cv2.cvtColor(f_bg, cv2.COLOR_BGR2RGB)
        canvas = Image.fromarray(bg_rgb).resize((720, 1280), Image.Resampling.LANCZOS).convert("RGBA")
        
        # Continuous organic 3D levitation bobbing
        bob_l = int(6.0 * math.sin(2.0 * math.pi * 0.45 * t))
        bob_c = int(8.0 * math.sin(2.0 * math.pi * 0.45 * t + 1.2))
        bob_r = int(6.0 * math.sin(2.0 * math.pi * 0.45 * t + 2.4))
        
        card_l = create_card_frame(f_l, 205, 360, radius=20, border_w=2, pill_text="37.7M", is_viral=False)
        card_c = create_card_frame(f_c, 250, 430, radius=24, border_w=3, pill_text="34.3M", is_viral=True)
        card_r = create_card_frame(f_r, 205, 360, radius=20, border_w=2, pill_text="42.7M", is_viral=False)
        
        # 1. Pop Left Card at t = 0.15s
        render_bouncing_card(canvas, card_l, c_left_cx, c_left_cy + bob_l, t, t_pop_start=0.15, pop_duration=0.36, spring_s=2.2)
        
        # 2. Pop Right Card at t = 0.35s
        render_bouncing_card(canvas, card_r, c_right_cx, c_right_cy + bob_r, t, t_pop_start=0.35, pop_duration=0.36, spring_s=2.2)
        
        # 3. Pop Center Card in FRONT at t = 0.55s
        render_bouncing_card(canvas, card_c, c_center_cx, c_center_cy + bob_c, t, t_pop_start=0.55, pop_duration=0.40, spring_s=2.4)
        
        # 4. Avatar in front
        im_a = Image.fromarray(cv2.cvtColor(f_a, cv2.COLOR_BGR2RGB)).convert("RGBA")
        im_am = Image.fromarray(cv2.cvtColor(f_am, cv2.COLOR_BGR2GRAY))
        im_a.putalpha(im_am)
        scale_av = av_w / im_a.width
        av_h = int(im_a.height * scale_av)
        im_a = im_a.resize((av_w, av_h), Image.Resampling.LANCZOS)
        
        canvas.alpha_composite(im_a, ((720 - av_w) // 2, 560))
        
        out_fpath = os.path.join(temp_dir, f"frame_{f:04d}.jpg")
        canvas.convert("RGB").save(out_fpath, quality=95)
        
    cap_bg.release()
    cap_c.release()
    cap_l.release()
    cap_r.release()
    cap_av.release()
    cap_av_m.release()
    
    print(f"Encoding upgraded hook track to {output_path}...")
    import subprocess
    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-i", os.path.join(temp_dir, "frame_%04d.jpg"),
        "-c:v", "libx264",
        "-crf", "14",
        "-preset", "slow",
        "-pix_fmt", "yuv420p",
        output_path
    ]
    subprocess.run(cmd, check=True)
    print(f"SUCCESS: Upgraded Hook track created at {output_path}")

if __name__ == "__main__":
    build_hook_video()
