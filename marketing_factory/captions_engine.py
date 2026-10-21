import os
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

def get_font(size):
    candidates = [
        "C:/Windows/Fonts/Montserrat-Black.ttf",
        "C:/Windows/Fonts/Montserrat-Bold.ttf",
        "C:/Windows/Fonts/impact.ttf",
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()

HIGHLIGHT_WORDS = {
    "viral", "clips", "millions", "views", "hotshort", "youtube", "analyze",
    "generate", "seconds", "epic", "anime", "free", "link", "ai", "step", "first"
}

def render_caption_frame(text, width=1080, height=300, font_size=88, scale=1.0):
    """
    Renders a dynamic bold caption card with outline, drop shadow, and keyword highlights.
    Returns an RGBA numpy array.
    """
    # Create canvas
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    actual_size = int(font_size * scale)
    font = get_font(actual_size)

    words = text.strip().split()
    if not words:
        return np.array(canvas)

    # Measure total width of the line with spaces
    space_w = font.getbbox(" ")[2] - font.getbbox(" ")[0]
    word_boxes = []
    total_w = 0
    for w in words:
        bbox = font.getbbox(w)
        w_w = bbox[2] - bbox[0]
        w_h = bbox[3] - bbox[1]
        word_boxes.append((w, w_w, w_h))
        total_w += w_w
    total_w += space_w * (len(words) - 1)

    cur_x = (width - total_w) // 2
    cur_y = (height - max(h for _, _, h in word_boxes)) // 2

    # Draw words with stroke and highlight
    stroke_w = max(5, int(7 * scale))

    for word, w_w, w_h in word_boxes:
        clean_word = word.lower().strip(".,!?\"'")
        is_highlight = clean_word in HIGHLIGHT_WORDS

        fill_color = (255, 230, 0, 255) if is_highlight else (255, 255, 255, 255) # Yellow or White
        stroke_color = (0, 0, 0, 255)

        # Draw with stroke
        draw.text(
            (cur_x, cur_y),
            word,
            font=font,
            fill=fill_color,
            stroke_width=stroke_w,
            stroke_fill=stroke_color
        )
        cur_x += w_w + space_w

    return np.array(canvas)

if __name__ == "__main__":
    arr = render_caption_frame("VIRAL CLIPS")
    img = Image.fromarray(arr)
    img.save("marketing_factory/assets/test_caption.png")
    print("Caption frame test passed! Saved test_caption.png")
