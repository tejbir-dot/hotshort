import os
import sys
import math
import subprocess
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

def create_phone_shadow(w, h, blur_radius=22, y_offset=16, shadow_alpha=185):
    pad = blur_radius * 2 + 10
    sw, sh = w + pad * 2, h + pad * 2
    shadow_img = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    ds = ImageDraw.Draw(shadow_img)
    corner_rad = max(12, int(42 * (w / 416.0)))
    ds.rounded_rectangle([pad, pad + y_offset, pad + w - 1, pad + y_offset + h - 1],
                         radius=corner_rad, fill=(0, 0, 0, shadow_alpha))
    shadow_img = shadow_img.filter(ImageFilter.GaussianBlur(blur_radius))
    return shadow_img, pad


def ease_in_out(t):
    return 2 * t * t if t < 0.5 else -1 + (4 - 2 * t) * t

def get_camera_params(t):
    # t in [0.0, 13.0]
    if t < 3.0:
        # YouTube Wide Overview
        return 1.05, 208.0, 442.0, 500.0
    elif t < 4.8:
        # Punch-in zoom to Copy Link
        p = ease_in_out((t - 3.0) / 1.8)
        scale = 1.05 + (1.45 - 1.05) * p
        fx = 208.0
        fy = 442.0 + (760.0 - 442.0) * p
        cy = 500.0 + (550.0 - 500.0) * p
        return scale, fx, fy, cy
    elif t < 8.5:
        # Close-up on HotShort input & Analyze Now button
        return 1.45, 208.0, 360.0, 540.0
    elif t < 9.2:
        # Smooth cinematic pull back to full phone reveal
        p = ease_in_out((t - 8.5) / 0.7)
        scale = 1.45 + (1.08 - 1.45) * p
        fx = 208.0
        fy = 360.0 + (442.0 - 360.0) * p
        cy = 540.0 + (490.0 - 540.0) * p
        return scale, fx, fy, cy
    else:
        # Playing Viral Short in full phone
        return 1.08, 208.0, 442.0, 490.0


def build_cinematic_track(
    demo_video_path="marketing_factory/assets/real_app_demo.mp4",
    bg_video_path="marketing_factory/assets/bg_generativo.mp4",
    output_path="marketing_factory/assets/cinematic_ui_bg_track.mp4",
    ui_start_t=4.5,
    fps=25
):
    print("=" * 60)
    print("BUILDING CINEMATIC DYNAMIC CAMERA UI TRACK")
    print("=" * 60)

    phone_img = Image.open("marketing_factory/assets/phone_frame.png").convert("RGBA")
    mask_img = Image.open("marketing_factory/assets/screen_mask.png").convert("L")

    screen_w, screen_h = 400, 869
    border_w = 8
    phone_w = screen_w + 2 * border_w # 416
    phone_h = screen_h + 2 * border_w # 885

    cap_demo = cv2.VideoCapture(demo_video_path)
    total_frames = int(cap_demo.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f"Total input demo frames: {total_frames} ({total_frames / fps:.2f}s)")

    cap_bg = cv2.VideoCapture(bg_video_path)
    bg_fps = cap_bg.get(cv2.CAP_PROP_FPS) or 30.0
    # Seek bg to ui_start_t
    cap_bg.set(cv2.CAP_PROP_POS_FRAMES, int(ui_start_t * bg_fps))

    temp_frames_dir = os.path.abspath("scratch/marketing_factory/cinematic_frames")
    os.makedirs(temp_frames_dir, exist_ok=True)

    print("Compositing frames with dynamic camera zoom-punches and 3D levitation...")
    for f in range(total_frames):
        ret_d, frame_d = cap_demo.read()
        if not ret_d:
            break

        ret_b, frame_b = cap_bg.read()
        if not ret_b:
            cap_bg.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret_b, frame_b = cap_bg.read()

        t = f / float(fps)
        scale, fx, fy, cy = get_camera_params(t)

        # 3D sinusoidal floating levitation
        float_y = 8.0 * math.sin(2.0 * math.pi * 0.40 * t)

        # 1. Screen preparation
        frame_d_rgb = cv2.cvtColor(frame_d, cv2.COLOR_BGR2RGB)
        im_screen = Image.fromarray(frame_d_rgb).resize((screen_w, screen_h), Image.Resampling.LANCZOS)

        masked_screen = Image.new("RGBA", (screen_w, screen_h), (0, 0, 0, 0))
        masked_screen.paste(im_screen, (0, 0), mask_img)

        # 2. Base Phone assembly (416 x 885)
        phone_comp = Image.new("RGBA", (phone_w, phone_h), (0, 0, 0, 0))
        phone_comp.paste(masked_screen, (border_w, border_w))
        phone_comp.alpha_composite(phone_img, (0, 0))

        # 3. Dynamic Camera Scaling & Panning
        scaled_w = int(round(phone_w * scale))
        scaled_h = int(round(phone_h * scale))
        scaled_phone = phone_comp.resize((scaled_w, scaled_h), Image.Resampling.LANCZOS)

        # Calculate canvas paste position to place (fx, fy) at (360, cy + float_y)
        paste_x = int(round(360 - fx * scale))
        paste_y = int(round((cy + float_y) - fy * scale))

        # 4. Composite onto Generative 3D Background with 3D Feathered Drop Shadow
        frame_b_rgb = cv2.cvtColor(frame_b, cv2.COLOR_BGR2RGB)
        bg_im = Image.fromarray(frame_b_rgb).resize((720, 1280), Image.Resampling.LANCZOS).convert("RGBA")
        
        # 3D Feathered Drop Shadow
        phone_shadow, s_pad = create_phone_shadow(scaled_w, scaled_h, blur_radius=int(22 * scale), y_offset=int(16 * scale), shadow_alpha=185)
        bg_im.alpha_composite(phone_shadow, (paste_x - s_pad, paste_y - s_pad))
        bg_im.alpha_composite(scaled_phone, (paste_x, paste_y))

        final_rgb = bg_im.convert("RGB")
        frame_path = os.path.join(temp_frames_dir, f"frame_{f:04d}.jpg")
        final_rgb.save(frame_path, quality=95)

        # Save verification frames for inspection
        if f in [10, 45, 95, 145, 230]:
            final_rgb.save(f"scratch/marketing_factory/verify_cinematic_{f:03d}.jpg", quality=95)

        if f % 50 == 0:
            print(f"  Frame {f}/{total_frames} (t={t:.2f}s, scale={scale:.2f})...")

    cap_demo.release()
    cap_bg.release()

    print(f"Encoding {total_frames} frames to {output_path} with ffmpeg (CRF 14)...")
    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-i", os.path.join(temp_frames_dir, "frame_%04d.jpg"),
        "-c:v", "libx264",
        "-crf", "14",
        "-preset", "slow",
        "-pix_fmt", "yuv420p",
        output_path
    ]
    subprocess.run(ffmpeg_cmd, check=True)
    print(f"SUCCESS: Cinematic UI track built at {output_path}")

if __name__ == "__main__":
    build_cinematic_track()
