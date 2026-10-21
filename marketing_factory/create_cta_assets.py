import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter

def get_font(size, bold=True):
    # Try system fonts on Windows
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

def create_cta_bubbles():
    os.makedirs("marketing_factory/assets", exist_ok=True)

    # 1. User "AI" comment bubble (Right aligned, Cyan/Teal)
    w, h = 320, 140
    bubble = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(bubble)

    # Shadow
    s_img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    s_draw = ImageDraw.Draw(s_img)
    s_draw.rounded_rectangle([15, 20, w - 15, h - 20], radius=32, fill=(0, 0, 0, 90))
    s_img = s_img.filter(ImageFilter.GaussianBlur(radius=8))
    bubble = Image.alpha_composite(bubble, s_img)
    draw = ImageDraw.Draw(bubble)

    # Cyan gradient or vibrant cyan pill
    pill_box = [15, 15, w - 15, h - 25]
    draw.rounded_rectangle(pill_box, radius=32, fill=(45, 185, 220, 255), outline=(120, 230, 255, 255), width=2)

    # Text: "AI"
    font = get_font(52, bold=True)
    draw.text((w // 2, h // 2 - 8), '"AI"', fill=(255, 255, 255, 255), font=font, anchor="mm")
    bubble.save("marketing_factory/assets/cta_user_bubble.png")

    # 2. HotShort DM link reply bubble (Left aligned, sleek dark card with glow)
    rw, rh = 540, 140
    reply = Image.new("RGBA", (rw, rh), (0, 0, 0, 0))
    draw_r = ImageDraw.Draw(reply)

    # Ambient glow
    r_shadow = Image.new("RGBA", (rw, rh), (0, 0, 0, 0))
    rs_draw = ImageDraw.Draw(r_shadow)
    rs_draw.rounded_rectangle([15, 20, rw - 15, rh - 20], radius=30, fill=(117, 91, 255, 80))
    r_shadow = r_shadow.filter(ImageFilter.GaussianBlur(radius=12))
    reply = Image.alpha_composite(reply, r_shadow)
    draw_r = ImageDraw.Draw(reply)

    # White / Sleek light pill (like iOS Messages)
    r_box = [15, 15, rw - 15, rh - 25]
    draw_r.rounded_rectangle(r_box, radius=30, fill=(255, 255, 255, 255), outline=(220, 225, 235, 255), width=2)

    # Text: https://hotshort.ai
    font_link = get_font(38, bold=True)
    draw_r.text((rw // 2, rh // 2 - 8), "https://hotshort.ai", fill=(18, 20, 25, 255), font=font_link, anchor="mm")
    reply.save("marketing_factory/assets/cta_reply_bubble.png")

    print("CTA bubble assets created!")

if __name__ == "__main__":
    create_cta_bubbles()
