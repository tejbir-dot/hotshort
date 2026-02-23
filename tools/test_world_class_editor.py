import argparse
import json
import os

from effects.world_class_editor import ClipEditor, ClipEditConfig


def main() -> None:
    parser = argparse.ArgumentParser(description="Test world-class HotShort clip editing.")
    parser.add_argument("--input", required=True, help="Path to pre-trimmed clip MP4")
    parser.add_argument("--output", required=True, help="Path for enhanced output MP4")
    parser.add_argument("--source-start", type=float, default=0.0, help="Start timestamp in original source")
    parser.add_argument("--source-end", type=float, default=30.0, help="End timestamp in original source")
    parser.add_argument("--transcript-json", default="", help="Path to transcript JSON list with start/end/text")
    parser.add_argument("--ratio", default="9:16", help="Target ratio, e.g. 9:16 or 1:1")
    parser.add_argument("--translate-to", default="", help="Optional caption translation target language code")
    args = parser.parse_args()

    transcript = None
    if args.transcript_json:
        with open(args.transcript_json, "r", encoding="utf-8") as f:
            transcript = json.load(f)

    editor = ClipEditor(work_dir=os.path.join(os.path.dirname(args.output) or ".", "_wc_tmp"))
    config = ClipEditConfig(
        target_ratio=args.ratio,
        translate_to=(args.translate_to.strip() or None),
        add_captions=True,
        enhance_visuals=True,
        enhance_audio=True,
        enable_active_speaker=True,
        enable_hook_speed_ramp=True,
    )
    result = editor.enhance_pretrimmed_clip(
        input_path=args.input,
        output_path=args.output,
        source_start=args.source_start,
        source_end=args.source_end,
        transcript=transcript,
        config=config,
        clip_title="HotShort Test Hook",
    )
    print(json.dumps({"output": result.output_path, "engagement_score": result.engagement_score}, indent=2))


if __name__ == "__main__":
    main()
