import os
import sys
import json
import argparse
from PIL import Image, ImageDraw, ImageFont, ImageFilter

sys.path.insert(0, os.path.abspath("."))
from marketing_factory.engine import create_promo_video

PROMOS_JSON = "marketing_factory/god_tier_promos.json"

def generate_cta_bubbles(keyword, reply_text, out_dir="scratch/marketing_factory/custom_bubbles"):
    os.makedirs(out_dir, exist_ok=True)
    user_bubble_path = os.path.join(out_dir, f"bubble_user_{keyword}.png")
    reply_bubble_path = os.path.join(out_dir, f"bubble_reply_{keyword}.png")

    # 1. User Bubble (Turquoise Pill with 3D feathered shadow)
    uw, uh = 280, 110
    pad = 24
    user_canvas = Image.new("RGBA", (uw + pad * 2, uh + pad * 2), (0, 0, 0, 0))
    
    # Shadow
    du_s = ImageDraw.Draw(user_canvas)
    du_s.rounded_rectangle([pad, pad + 10, pad + uw - 1, pad + 10 + uh - 1], radius=45, fill=(0, 0, 0, 160))
    user_canvas = user_canvas.filter(ImageFilter.GaussianBlur(14))
    
    # Foreground pill
    user_fg = Image.new("RGBA", (uw, uh), (0, 0, 0, 0))
    du = ImageDraw.Draw(user_fg)
    du.rounded_rectangle([2, 2, uw - 3, uh - 3], radius=45, fill=(34, 185, 230, 255), outline=(130, 235, 255, 255), width=2)
    
    try:
        font_u = ImageFont.truetype("arialbd.ttf", 46)
    except:
        font_u = ImageFont.load_default()
        
    u_text = f'"{keyword}"'
    ubox = du.textbbox((0, 0), u_text, font=font_u)
    utw = ubox[2] - ubox[0]
    uth = ubox[3] - ubox[1]
    du.text(((uw - utw) // 2, (uh - uth) // 2 - 4), u_text, font=font_u, fill=(255, 255, 255, 255))
    
    user_canvas.alpha_composite(user_fg, (pad, pad))
    user_canvas.save(user_bubble_path)

    # 2. Reply Bubble (White Card with 3D feathered shadow)
    rw, rh = 460, 110
    reply_canvas = Image.new("RGBA", (rw + pad * 2, rh + pad * 2), (0, 0, 0, 0))
    
    # Shadow
    dr_s = ImageDraw.Draw(reply_canvas)
    dr_s.rounded_rectangle([pad, pad + 10, pad + rw - 1, pad + 10 + rh - 1], radius=32, fill=(0, 0, 0, 160))
    reply_canvas = reply_canvas.filter(ImageFilter.GaussianBlur(14))
    
    # Foreground card
    reply_fg = Image.new("RGBA", (rw, rh), (0, 0, 0, 0))
    dr = ImageDraw.Draw(reply_fg)
    dr.rounded_rectangle([2, 2, rw - 3, rh - 3], radius=32, fill=(255, 255, 255, 255), outline=(225, 230, 240, 255), width=2)
    
    try:
        font_r = ImageFont.truetype("arialbd.ttf", 34)
    except:
        font_r = ImageFont.load_default()
        
    rbox = dr.textbbox((0, 0), reply_text, font=font_r)
    rtw = rbox[2] - rbox[0]
    rth = rbox[3] - rbox[1]
    dr.text(((rw - rtw) // 2, (rh - rth) // 2 - 3), reply_text, font=font_r, fill=(15, 20, 30, 255))
    
    reply_canvas.alpha_composite(reply_fg, (pad, pad))
    reply_canvas.save(reply_bubble_path)

    return user_bubble_path, reply_bubble_path

def load_campaign():
    with open(PROMOS_JSON, "r", encoding="utf-8") as f:
        return json.load(f)

def list_clips():
    campaign = load_campaign()
    print("=" * 70)
    print(f"HOTSHORT GOD-TIER PROMO CAMPAIGN: {campaign['campaign_name']} (Total: {len(campaign['clips'])})")
    print("=" * 70)
    for c in campaign["clips"]:
        print(f"[{c['index']:02d}] {c['title']} | Keyword: '{c['keyword']}'")
        print(f"     Hook: \"{c['hook']['audio']}\"")
        print(f"     Target Output: marketing_factory/output/{c['id']}.mp4\n")

def render_single_clip(clip_identifier):
    campaign = load_campaign()
    target_clip = None
    
    if str(clip_identifier).isdigit():
        idx = int(clip_identifier)
        for c in campaign["clips"]:
            if c["index"] == idx:
                target_clip = c
                break
    else:
        for c in campaign["clips"]:
            if c["id"] == clip_identifier or c["keyword"].lower() == clip_identifier.lower():
                target_clip = c
                break
                
    if not target_clip:
        print(f"ERROR: Clip '{clip_identifier}' not found in campaign JSON!")
        return None

    print("\n" + "=" * 70)
    print(f"RENDERING GOD-TIER PROMO #{target_clip['index']}: {target_clip['title']}")
    print(f"KEYWORD: '{target_clip['keyword']}' | PSYCHOLOGY: {target_clip['psychology']}")
    print("=" * 70)

    # 1. Generate customized CTA bubbles with 3D feathered shadows
    reply_str = target_clip["cta"]["bubble_reply"]
    user_bubble, reply_bubble = generate_cta_bubbles(target_clip["keyword"], reply_str)

    # 2. Render through Master Engine
    out_file = f"marketing_factory/output/{target_clip['id']}.mp4"
    rendered_path = create_promo_video(
        script_text=target_clip["full_script"],
        output_filename=out_file,
        cta_user_bubble_path=user_bubble,
        cta_reply_bubble_path=reply_bubble
    )
    print(f"\n[SUCCESS] Clip #{target_clip['index']} ready: {rendered_path}\n")
    return rendered_path

def render_all_clips():
    campaign = load_campaign()
    print("=" * 70)
    print(f"STARTING BATCH GENERATION OF ALL {len(campaign['clips'])} GOD-TIER PROMOS")
    print("=" * 70)
    for c in campaign["clips"]:
        render_single_clip(c["index"])
    print("\nALL 10 GOD-TIER CLIPS HAVE BEEN GENERATED AND ARE READY TO PUBLISH! 🚀💸")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HotShort God-Tier Promo Batch Renderer")
    parser.add_argument("--list", action="store_true", help="List all 10 promo clip concepts")
    parser.add_argument("--clip", type=str, help="Render a specific clip by index (1-10), id, or keyword")
    parser.add_argument("--all", action="store_true", help="Batch render all 10 promo clips sequentially")

    args = parser.parse_args()

    if args.list or len(sys.argv) == 1:
        list_clips()
    elif args.clip:
        render_single_clip(args.clip)
    elif args.all:
        render_all_clips()
