import os
from PIL import Image, ImageDraw, ImageFilter

def generate_iphone16pro_mockup(
    screen_w=400,
    screen_h=869, # 400 * 956 / 440
    border_w=8,
    corner_radius=40,
    output_dir="marketing_factory/assets"
):
    os.makedirs(output_dir, exist_ok=True)
    
    phone_w = screen_w + 2 * border_w # 416
    phone_h = screen_h + 2 * border_w # 885
    
    # 1. Phone Frame overlay with transparent screen cutout
    frame = Image.new("RGBA", (phone_w, phone_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(frame)
    
    # Outer Titanium Bezel
    draw.rounded_rectangle(
        [0, 0, phone_w - 1, phone_h - 1],
        radius=corner_radius + border_w,
        fill=(18, 20, 24, 255),
        outline=(70, 75, 88, 255),
        width=2
    )
    
    # Inner border line around screen
    draw.rounded_rectangle(
        [border_w - 1, border_w - 1, border_w + screen_w, border_w + screen_h],
        radius=corner_radius,
        outline=(35, 38, 48, 255),
        width=1
    )
    
    # Clear the inner screen area to 100% transparent
    # Using a mask to punch out the exact rounded screen
    punch_mask = Image.new("L", (phone_w, phone_h), 255)
    p_draw = ImageDraw.Draw(punch_mask)
    p_draw.rounded_rectangle(
        [border_w, border_w, border_w + screen_w - 1, border_w + screen_h - 1],
        radius=corner_radius,
        fill=0
    )
    
    # Apply punch mask to frame alpha
    frame_r, frame_g, frame_b, frame_a = frame.split()
    # combine existing alpha with punch mask
    import numpy as np
    a_arr = np.array(frame_a)
    p_arr = np.array(punch_mask)
    combined_a = np.minimum(a_arr, p_arr)
    frame = Image.merge("RGBA", (frame_r, frame_g, frame_b, Image.fromarray(combined_a)))
    
    draw = ImageDraw.Draw(frame)
    
    # Dynamic Island pill cutout at top (sleek 88x18 at y=10)
    di_w, di_h = 88, 18
    di_x = (phone_w - di_w) // 2
    di_y = border_w + 3
    draw.rounded_rectangle(
        [di_x, di_y, di_x + di_w, di_y + di_h],
        radius=9,
        fill=(5, 5, 8, 255),
        outline=(25, 25, 32, 255),
        width=1
    )
    # Camera dot
    draw.ellipse([di_x + 12, di_y + 5, di_x + 20, di_y + 13], fill=(15, 20, 35, 255))
    
    # Bottom Home Bar
    bar_w, bar_h = 130, 4
    bar_x = (phone_w - bar_w) // 2
    bar_y = phone_h - border_w - 14
    draw.rounded_rectangle(
        [bar_x, bar_y, bar_x + bar_w, bar_y + bar_h],
        radius=2,
        fill=(220, 225, 235, 200)
    )
    
    frame_path = os.path.join(output_dir, "phone_frame.png")
    frame.save(frame_path)
    print(f"Generated phone frame: {phone_w}x{phone_h} (inner screen {screen_w}x{screen_h}) at {frame_path}")
    
    # 2. Screen Mask for clipping video (exact rounded inner screen)
    screen_mask = Image.new("L", (screen_w, screen_h), 0)
    sm_draw = ImageDraw.Draw(screen_mask)
    sm_draw.rounded_rectangle(
        [0, 0, screen_w - 1, screen_h - 1],
        radius=corner_radius,
        fill=255
    )
    mask_path = os.path.join(output_dir, "screen_mask.png")
    screen_mask.save(mask_path)
    print(f"Generated screen mask: {screen_w}x{screen_h} at {mask_path}")

if __name__ == "__main__":
    generate_iphone16pro_mockup()
