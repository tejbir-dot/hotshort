import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter

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

def create_floating_card_with_image(thumb_path, card_w=300, card_h=460, views="69.3M", is_center=False):
    card = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))

    # Base card
    base = Image.new("RGBA", (card_w, card_h), (16, 18, 24, 255))
    
    # Load and fit thumbnail
    if os.path.exists(thumb_path):
        t_img = Image.open(thumb_path).convert("RGBA")
        # Cover crop
        t_aspect = t_img.width / t_img.height
        target_aspect = card_w / card_h
        if t_aspect > target_aspect:
            new_w = int(t_img.height * target_aspect)
            offset = (t_img.width - new_w) // 2
            t_img = t_img.crop((offset, 0, offset + new_w, t_img.height))
        else:
            new_h = int(t_img.width / target_aspect)
            offset = (t_img.height - new_h) // 2
            t_img = t_img.crop((0, offset, t_img.width, offset + new_h))
        t_img = t_img.resize((card_w, card_h), Image.Resampling.LANCZOS)
        
        # Dark gradient at the bottom so the view counter pops
        grad = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
        g_draw = ImageDraw.Draw(grad)
        for y in range(int(card_h * 0.5), card_h):
            alpha = int(220 * ((y - card_h * 0.5) / (card_h * 0.5)))
            g_draw.line([(0, y), (card_w, y)], fill=(0, 0, 0, alpha))
        t_img = Image.alpha_composite(t_img, grad)
        base.paste(t_img, (0, 0))

    # Rounded card mask
    mask = Image.new("L", (card_w, card_h), 0)
    m_draw = ImageDraw.Draw(mask)
    m_draw.rounded_rectangle([0, 0, card_w - 1, card_h - 1], radius=26, fill=255)

    card.paste(base, (0, 0), mask)
    draw = ImageDraw.Draw(card)

    # Outer border glow
    border_color = (255, 255, 255, 240) if is_center else (140, 150, 180, 160)
    border_width = 3 if is_center else 2
    draw.rounded_rectangle([0, 0, card_w - 1, card_h - 1], radius=26, outline=border_color, width=border_width)

    # Bottom View Count Pill
    font_v = get_font(26, bold=True)
    pill_w, pill_h = 164, 46
    pill_x = 16
    pill_y = card_h - pill_h - 16
    draw.rounded_rectangle([pill_x, pill_y, pill_x + pill_w, pill_y + pill_h], radius=14, fill=(0, 0, 0, 190), outline=(255, 255, 255, 90), width=1)
    
    # Play triangle
    tri_x = pill_x + 18
    tri_y = pill_y + 13
    draw.polygon([(tri_x, tri_y), (tri_x + 14, tri_y + 10), (tri_x, tri_y + 20)], fill=(255, 255, 255, 255))
    
    # View text
    draw.text((tri_x + 24, pill_y + pill_h // 2), views, fill=(255, 255, 255, 255), font=font_v, anchor="lm")

    return card

def generate_hook_cards():
    os.makedirs("marketing_factory/assets", exist_ok=True)
    c1 = create_floating_card_with_image("marketing_factory/assets/thumbs/thumb_stream.jpg", card_w=300, card_h=460, views="76.7M", is_center=False)
    c2 = create_floating_card_with_image("marketing_factory/assets/thumbs/thumb_speed.jpg", card_w=350, card_h=520, views="89.4M", is_center=True)
    c3 = create_floating_card_with_image("marketing_factory/assets/thumbs/thumb_crypto.jpg", card_w=300, card_h=460, views="54.2M", is_center=False)

    c1.save("marketing_factory/assets/hook_card_left.png")
    c2.save("marketing_factory/assets/hook_card_center.png")
    c3.save("marketing_factory/assets/hook_card_right.png")
    print("Upgraded realistic hook cards generated!")

if __name__ == "__main__":
    generate_hook_cards()
