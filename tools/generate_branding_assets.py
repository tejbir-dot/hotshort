from __future__ import annotations

import argparse
import os
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps


def _hex(c: str) -> tuple[int, int, int, int]:
    c = c.strip().lstrip("#")
    if len(c) == 6:
        r = int(c[0:2], 16)
        g = int(c[2:4], 16)
        b = int(c[4:6], 16)
        return (r, g, b, 255)
    raise ValueError(f"Unsupported color: {c}")


def _lerp(a: int, b: int, t: float) -> int:
    return int(a + (b - a) * t)


def _gradient_horizontal(size: tuple[int, int], stops: list[tuple[float, tuple[int, int, int, int]]]) -> Image.Image:
    w, h = size
    stops = sorted(stops, key=lambda x: x[0])
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = img.load()
    for x in range(w):
        t = x / (w - 1) if w > 1 else 0.0
        for i in range(len(stops) - 1):
            t0, c0 = stops[i]
            t1, c1 = stops[i + 1]
            if t0 <= t <= t1:
                u = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
                c = (
                    _lerp(c0[0], c1[0], u),
                    _lerp(c0[1], c1[1], u),
                    _lerp(c0[2], c1[2], u),
                    _lerp(c0[3], c1[3], u),
                )
                for y in range(h):
                    px[x, y] = c
                break
        else:
            _, c = stops[-1]
            for y in range(h):
                px[x, y] = c
    return img


def _find_font(prefer_bold: bool) -> str | None:
    windir = os.environ.get("WINDIR", r"C:\Windows")
    candidates = []
    if prefer_bold:
        candidates.extend(
            [
                os.path.join(windir, "Fonts", "arialbd.ttf"),
                os.path.join(windir, "Fonts", "segoeuib.ttf"),
            ]
        )
    candidates.extend(
        [
            os.path.join(windir, "Fonts", "arial.ttf"),
            os.path.join(windir, "Fonts", "segoeui.ttf"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/Library/Fonts/Arial.ttf",
        ]
    )
    for p in candidates:
        try:
            if p and os.path.exists(p) and not os.path.isdir(p):
                return p
        except Exception:
            pass
    return None


def _render_mark(size: int = 512) -> Image.Image:
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    cx = cy = size // 2
    ring_outer = int(size * 0.44)
    ring_inner = int(size * 0.32)

    # Ring gradient
    grad = _gradient_horizontal(
        (size, size),
        [
            (0.0, _hex("#ff7a18")),
            (0.5, _hex("#ffd27d")),
            (1.0, _hex("#fff2cc")),
        ],
    )
    ring_mask = Image.new("L", (size, size), 0)
    dm = ImageDraw.Draw(ring_mask)
    dm.ellipse((cx - ring_outer, cy - ring_outer, cx + ring_outer, cy + ring_outer), fill=255)
    dm.ellipse((cx - ring_inner, cy - ring_inner, cx + ring_inner, cy + ring_inner), fill=0)
    ring = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ring.paste(grad, (0, 0), ring_mask)

    # Glow
    glow = ring_mask.filter(ImageFilter.GaussianBlur(radius=int(size * 0.03)))
    glow_img = Image.new("RGBA", (size, size), _hex("#ff8a2a"))
    glow_img.putalpha(glow)
    glow_img = glow_img.filter(ImageFilter.GaussianBlur(radius=int(size * 0.015)))

    canvas = Image.alpha_composite(canvas, glow_img)
    canvas = Image.alpha_composite(canvas, ring)

    # Inner dark plate
    plate = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    dp = ImageDraw.Draw(plate)
    plate_r = int(size * 0.29)
    dp.ellipse((cx - plate_r, cy - plate_r, cx + plate_r, cy + plate_r), fill=(8, 10, 20, 210))
    plate = plate.filter(ImageFilter.GaussianBlur(radius=1))
    canvas = Image.alpha_composite(canvas, plate)

    # Play triangle
    tri = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    dt = ImageDraw.Draw(tri)
    t_w = int(size * 0.20)
    t_h = int(size * 0.23)
    x0 = cx - int(t_w * 0.35)
    y0 = cy - t_h // 2
    pts = [(x0, y0), (x0, y0 + t_h), (x0 + t_w, cy)]
    dt.polygon(pts, fill=(255, 170, 70, 230))
    tri = tri.filter(ImageFilter.GaussianBlur(radius=0.6))
    canvas = Image.alpha_composite(canvas, tri)

    # Small highlight on ring
    highlight = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    dh = ImageDraw.Draw(highlight)
    dh.arc(
        (cx - ring_outer, cy - ring_outer, cx + ring_outer, cy + ring_outer),
        start=220,
        end=310,
        fill=(255, 255, 255, 110),
        width=int(size * 0.02),
    )
    highlight = highlight.filter(ImageFilter.GaussianBlur(radius=1.2))
    canvas = Image.alpha_composite(canvas, highlight)

    # Tighten alpha (avoid stray low-alpha pixels)
    r, g, b, a = canvas.split()
    a = ImageChops.multiply(a, Image.new("L", (size, size), 255))
    canvas = Image.merge("RGBA", (r, g, b, a))
    return canvas


def _render_logo(out_w: int = 1600, out_h: int = 560) -> Image.Image:
    img = Image.new("RGBA", (out_w, out_h), (0, 0, 0, 0))

    mark = _render_mark(512).resize((360, 360), Image.Resampling.LANCZOS)
    img.alpha_composite(mark, (80, 80))

    bold_font_path = _find_font(prefer_bold=True)
    reg_font_path = _find_font(prefer_bold=False)
    font_bold = ImageFont.truetype(bold_font_path, 150) if bold_font_path else ImageFont.load_default()
    font_reg = ImageFont.truetype(reg_font_path or bold_font_path, 52) if (reg_font_path or bold_font_path) else ImageFont.load_default()

    # Wordmark: HOT (orange gradient) + SHORT (light)
    text_x = 480
    text_y = 170
    hot = "HOT"
    short = "SHORT"

    draw = ImageDraw.Draw(img)
    hot_bbox = draw.textbbox((0, 0), hot, font=font_bold)
    hot_w = hot_bbox[2] - hot_bbox[0]
    full = hot + short
    full_bbox = draw.textbbox((0, 0), full, font=font_bold)
    full_w = full_bbox[2] - full_bbox[0]

    # HOT gradient fill via mask
    hot_mask = Image.new("L", (hot_w + 10, 200), 0)
    ImageDraw.Draw(hot_mask).text((0, 0), hot, fill=255, font=font_bold)
    hot_grad = _gradient_horizontal(
        hot_mask.size,
        [(0.0, _hex("#ff7a18")), (0.6, _hex("#ffd27d")), (1.0, _hex("#fff2cc"))],
    )
    hot_layer = Image.new("RGBA", hot_mask.size, (0, 0, 0, 0))
    hot_layer.paste(hot_grad, (0, 0), hot_mask)
    hot_layer = hot_layer.filter(ImageFilter.GaussianBlur(radius=0.2))
    img.alpha_composite(hot_layer, (text_x, text_y))

    # SHORT in light metallic tone
    draw.text((text_x + hot_w, text_y), short, font=font_bold, fill=(230, 232, 238, 245))

    # Tagline
    tagline = "Engineered Virality"
    tag_y = text_y + 170
    draw.text((text_x, tag_y), tagline, font=font_reg, fill=(170, 175, 185, 210))

    # Subtle shadow behind wordmark
    shadow = Image.new("RGBA", (out_w, out_h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.text((text_x, text_y + 6), full, font=font_bold, fill=(0, 0, 0, 120))
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=8))
    img = Image.alpha_composite(shadow, img)

    return img


def _remove_dark_background_rgba(src: Image.Image) -> Image.Image:
    """
    Convert near-black backgrounds to transparency.
    Designed for logo images on dark backdrops (safe for watermark usage).
    """
    im = src.convert("RGBA")
    r, g, b, a = im.split()
    rgb = Image.merge("RGB", (r, g, b))
    gray = ImageOps.grayscale(rgb)

    # Soft threshold: keep bright pixels, fade out very dark pixels.
    # alpha = clamp((gray - 18) / 64) * 255
    lut = []
    for i in range(256):
        if i <= 18:
            lut.append(0)
        elif i >= 82:
            lut.append(255)
        else:
            lut.append(int((i - 18) * 255 / (82 - 18)))
    soft = gray.point(lut)

    # Preserve any existing alpha (if present)
    new_a = ImageChops.multiply(a, soft)
    im.putalpha(new_a)
    return im


def _crop_to_alpha(im: Image.Image, pad: int = 8) -> Image.Image:
    im = im.convert("RGBA")
    bbox = im.getchannel("A").getbbox()
    if not bbox:
        return im
    x0, y0, x1, y1 = bbox
    x0 = max(0, x0 - pad)
    y0 = max(0, y0 - pad)
    x1 = min(im.width, x1 + pad)
    y1 = min(im.height, y1 + pad)
    return im.crop((x0, y0, x1, y1))


def _fit_center(im: Image.Image, out_size: int) -> Image.Image:
    im = im.convert("RGBA")
    canvas = Image.new("RGBA", (out_size, out_size), (0, 0, 0, 0))
    scale = min((out_size * 0.86) / im.width, (out_size * 0.86) / im.height)
    nw = max(1, int(im.width * scale))
    nh = max(1, int(im.height * scale))
    im = im.resize((nw, nh), Image.Resampling.LANCZOS)
    x = (out_size - nw) // 2
    y = (out_size - nh) // 2
    canvas.alpha_composite(im, (x, y))
    return canvas


def _extract_icon_region(src: Image.Image) -> Image.Image:
    """
    Attempt to extract the "mark" (icon) from a full logo image.
    Heuristic: choose the largest connected alpha component in the upper ~60% that is roughly square.
    Falls back to the full image if component extraction isn't available.
    """
    try:
        import numpy as np

        try:
            import cv2  # type: ignore
        except Exception:
            cv2 = None  # type: ignore
    except Exception:
        return src

    im = src.convert("RGBA")
    alpha = np.array(im.getchannel("A"))
    mask = (alpha > 24).astype("uint8")
    if mask.sum() == 0:
        return src

    if cv2 is None:
        # Numpy-only fallback: just crop to alpha.
        return _crop_to_alpha(im, pad=12)

    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if num_labels <= 1:
        return _crop_to_alpha(im, pad=12)

    h, w = mask.shape
    candidates: list[tuple[int, tuple[int, int, int, int], float]] = []
    for label in range(1, num_labels):
        x, y, cw, ch, area = stats[label].tolist()
        if area < 200:
            continue
        cx, cy = centroids[label]
        aspect = cw / ch if ch else 10.0
        bbox = (x, y, x + cw, y + ch)
        # Prefer icon-like components: upper portion and near-square.
        score = area
        if cy < h * 0.60 and 0.75 <= aspect <= 1.33:
            score = area * 5
        candidates.append((int(score), bbox, float(cy)))

    if not candidates:
        return _crop_to_alpha(im, pad=12)

    candidates.sort(key=lambda t: t[0], reverse=True)
    _, (x0, y0, x1, y1), _ = candidates[0]

    pad = 14
    x0 = max(0, x0 - pad)
    y0 = max(0, y0 - pad)
    x1 = min(w, x1 + pad)
    y1 = min(h, y1 + pad)
    return im.crop((x0, y0, x1, y1))


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate HotShort branding assets (PNG).")
    parser.add_argument("--force", action="store_true", help="Overwrite existing files.")
    parser.add_argument("--source", type=str, default=None, help="Optional source logo image to derive assets from.")
    args = parser.parse_args()

    branding_dir = Path("static") / "branding"
    branding_dir.mkdir(parents=True, exist_ok=True)

    watermark_path = branding_dir / "watermark.png"
    icon_path = branding_dir / "logo_icon.png"
    hotshort_logo_path = branding_dir / "hotshort_logo.png"
    logo_path = branding_dir / "logo.png"

    source_path = Path(args.source) if args.source else None
    if source_path and source_path.exists() and source_path.is_file():
        src = Image.open(source_path)
        src = _remove_dark_background_rgba(src)
        src = _crop_to_alpha(src, pad=12)
        icon_src = _extract_icon_region(src)

        if args.force or not icon_path.exists():
            icon = _fit_center(icon_src, 512)
            icon.save(icon_path, format="PNG", optimize=True)

        if args.force or not hotshort_logo_path.exists():
            # Alias for the primary icon used in templates/watermarking.
            icon = _fit_center(icon_src, 512)
            icon.save(hotshort_logo_path, format="PNG", optimize=True)

        if args.force or not watermark_path.exists():
            wm = _fit_center(icon_src, 512)
            wm.save(watermark_path, format="PNG", optimize=True)

        if args.force or not logo_path.exists():
            # Keep a wide hero-friendly logo; constrain width for reasonable filesize.
            hero = src
            max_w = 1800
            if hero.width > max_w:
                hero = hero.resize((max_w, int(hero.height * (max_w / hero.width))), Image.Resampling.LANCZOS)
            hero.save(logo_path, format="PNG", optimize=True)
    else:
        if args.force or not icon_path.exists():
            icon = _render_mark(512)
            icon.save(icon_path, format="PNG", optimize=True)

        if args.force or not hotshort_logo_path.exists():
            icon = _render_mark(512)
            icon.save(hotshort_logo_path, format="PNG", optimize=True)

        if args.force or not watermark_path.exists():
            wm = _render_mark(512)
            wm.save(watermark_path, format="PNG", optimize=True)

        if args.force or not logo_path.exists():
            logo = _render_logo()
            logo.save(logo_path, format="PNG", optimize=True)

    print(f"Wrote {watermark_path}")
    print(f"Wrote {icon_path}")
    print(f"Wrote {hotshort_logo_path}")
    print(f"Wrote {logo_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
