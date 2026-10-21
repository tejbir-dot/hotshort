import os
import sys
sys.path.insert(0, os.path.abspath("."))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import json
import argparse
from marketing_factory.engine import create_promo_video

CAMPAIGNS_FILE = "marketing_factory/campaigns.json"
OUTPUT_DIR = "marketing_factory/output"

def load_campaigns():
    with open(CAMPAIGNS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def render_campaign(campaign_id, campaign_data):
    print(f"\n🚀 Launching Campaign: [{campaign_id}] - {campaign_data.get('title', '')}")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_file = os.path.join(OUTPUT_DIR, f"{campaign_id}.mp4")
    
    create_promo_video(
        script_text=campaign_data["script"],
        output_filename=out_file,
        bg_theme=campaign_data.get("theme", "circles"),
        voice=campaign_data.get("voice", "en-US-ChristopherNeural")
    )
    print(f"✅ Campaign [{campaign_id}] exported successfully to: {out_file}\n")
    return out_file

def main():
    parser = argparse.ArgumentParser(description="HotShort Automated Marketing Content Factory")
    parser.add_argument("--list", action="store_true", help="List all available promo campaigns")
    parser.add_argument("--campaign", type=str, help="Render a specific campaign by ID")
    parser.add_argument("--all", action="store_true", help="Batch render ALL campaigns in catalog")
    parser.add_argument("--custom", type=str, help="Render a custom script string")
    parser.add_argument("--theme", type=str, default="circles", choices=["circles", "wireframe"], help="Background theme")
    parser.add_argument("--voice", type=str, default="en-US-ChristopherNeural", help="TTS voice model")

    args = parser.parse_args()
    campaigns = load_campaigns()

    if args.list:
        print("\n📋 AVAILABLE MARKETING CAMPAIGNS:")
        print("=" * 60)
        for cid, data in campaigns.items():
            print(f"• ID: {cid}")
            print(f"  Title:  {data['title']}")
            print(f"  Niche:  {data['target_niche']}")
            print(f"  Theme:  {data['theme']} | Voice: {data['voice']}")
            print(f"  Script: {data['script'][:80]}...\n")
        return

    if args.custom:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        out_file = os.path.join(OUTPUT_DIR, "custom_promo.mp4")
        create_promo_video(
            script_text=args.custom,
            output_filename=out_file,
            bg_theme=args.theme,
            voice=args.voice
        )
        print(f"✅ Custom promo generated: {out_file}")
        return

    if args.all:
        print(f"🔥 Starting Batch Render for {len(campaigns)} campaigns...")
        for cid, data in campaigns.items():
            render_campaign(cid, data)
        print("\n🎉 ALL BATCH CAMPAIGNS RENDERED SUCCESSFULLY!")
        return

    if args.campaign:
        if args.campaign not in campaigns:
            print(f"❌ Error: Campaign '{args.campaign}' not found! Run with --list to see options.")
            return
        render_campaign(args.campaign, campaigns[args.campaign])
        return

    # Default: Show help
    parser.print_help()

if __name__ == "__main__":
    main()
