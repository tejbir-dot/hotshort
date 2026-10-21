import os
from PIL import Image, ImageDraw, ImageFilter

def create_phone_frame(width=640, height=1140, corner_radius=52, border_width=10):
    """
    Creates an ultra-clean iPhone 16 Pro mockup frame with rounded bezel,
    dynamic island cutout, subtle metallic border, and screen cutout mask.
    """
    # Outer frame
    frame = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(frame)

    # 1. Subtle glowing ambient shadow behind phone
    shadow = Image.new("RGBA", (width + 60, height + 60), (0, 0, 0, 0))
    s_draw = ImageDraw.Draw(shadow)
    s_draw.rounded_rectangle(
        [20, 20, width + 40, height + 40],
        radius=corner_radius + 8,
        fill=(0, 0, 0, 160)
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=18))

    # Outer bezel (titanium dark grey)
    draw.rounded_rectangle(
        [0, 0, width - 1, height - 1],
        radius=corner_radius,
        fill=(22, 24, 28, 255),
        outline=(60, 65, 75, 255),
        width=3
    )

    # Inner bezel (deep black)
    inner_box = [border_width, border_width, width - border_width - 1, height - border_width - 1]
    draw.rounded_rectangle(
        inner_box,
        radius=corner_radius - 8,
        fill=(0, 0, 0, 0), # Transparent inside for video
        outline=(40, 44, 52, 255),
        width=2
    )

    # Dynamic Island pill cutout at top
    di_w, di_h = 130, 36
    di_x = (width - di_w) // 2
    di_y = border_width + 12
    draw.rounded_rectangle(
        [di_x, di_y, di_x + di_w, di_y + di_h],
        radius=18,
        fill=(10, 10, 12, 255),
        outline=(25, 25, 30, 255),
        width=1
    )

    # Camera lens inside dynamic island
    draw.ellipse([di_x + 18, di_y + 11, di_x + 32, di_y + 25], fill=(20, 25, 45, 255))
    draw.ellipse([di_x + 22, di_y + 15, di_x + 28, di_y + 21], fill=(10, 15, 30, 255))

    # Bottom Home Bar
    bar_w, bar_h = 160, 5
    bar_x = (width - bar_w) // 2
    bar_y = height - border_width - 16
    draw.rounded_rectangle(
        [bar_x, bar_y, bar_x + bar_w, bar_y + bar_h],
        radius=3,
        fill=(200, 205, 215, 180)
    )

    os.makedirs("marketing_factory/assets", exist_ok=True)
    frame.save("marketing_factory/assets/phone_frame.png")

    # Also create the screen mask for clipping video to rounded screen area
    mask = Image.new("L", (width - 2 * border_width, height - 2 * border_width), 0)
    m_draw = ImageDraw.Draw(mask)
    m_draw.rounded_rectangle(
        [0, 0, mask.width - 1, mask.height - 1],
        radius=corner_radius - 8,
        fill=255
    )
    mask.save("marketing_factory/assets/screen_mask.png")
    print(f"Phone frame & screen mask generated: {width}x{height}")

if __name__ == "__main__":
    create_phone_frame()
