import os
import sys
import subprocess
from PIL import Image, ImageDraw, ImageFont
import numpy as np

REF_VIDEO = r"Overnight_Factory\Output\TJR_trader_new\cXlVBiwIlbI\Here is how I make viral streamer clips 🎥🤖 _tiktokautomation _ai _aitools _contentcreator _makemoneyontiktok (MP4).mp4"
OUTPUT_VIDEO = r"marketing_factory/output/hotshort_master_viral_clip.mp4"

def get_font(size, bold=True):
    candidates = [
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

def prepare_audio_patch():
    """
    Splices 'hotshort dot a i' into the original audio at 8.98s - 10.10s.
    """
    os.makedirs("scratch/marketing_factory", exist_ok=True)
    orig_audio = "marketing_factory/assets/ref_audio.mp3"
    voice_patch = "scratch/marketing_factory/hotshort_voice.mp3"

    # Part A: 0.0s to 8.95s
    subprocess.run([
        "ffmpeg", "-y", "-i", orig_audio, "-t", "8.95",
        "-c:a", "libmp3lame", "scratch/marketing_factory/part_a.mp3"
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Part C: 10.15s to end
    subprocess.run([
        "ffmpeg", "-y", "-ss", "10.15", "-i", orig_audio,
        "-c:a", "libmp3lame", "scratch/marketing_factory/part_c.mp3"
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Concat
    concat_txt = "scratch/marketing_factory/audio_concat.txt"
    with open(concat_txt, "w") as f:
        f.write("file 'part_a.mp3'\n")
        f.write("file 'hotshort_voice.mp3'\n")
        f.write("file 'part_c.mp3'\n")

    patched_audio = "scratch/marketing_factory/patched_master_audio.mp3"
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_txt,
        "-c:a", "libmp3lame", patched_audio
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("Patched master audio ready!")
    return patched_audio

def process_and_render_video():
    os.makedirs("marketing_factory/output", exist_ok=True)
    patched_audio = prepare_audio_patch()

    font_search = get_font(25, bold=False)
    font_bold = get_font(23, bold=True)
    font_pill = get_font(18, bold=True)
    font_bubble = get_font(31, bold=True)

    print("Opening source video stream...")
    fps = 30.0

    in_cmd = [
        "ffmpeg", "-i", REF_VIDEO,
        "-f", "image2pipe",
        "-pix_fmt", "rgb24",
        "-vcodec", "rawvideo", "-"
    ]
    in_proc = subprocess.Popen(in_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    out_cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo",
        "-vcodec", "rawvideo",
        "-s", "576x1024",
        "-pix_fmt", "rgb24",
        "-r", str(fps),
        "-i", "-",
        "-i", patched_audio,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "18",
        "-c:a", "aac",
        "-shortest",
        OUTPUT_VIDEO
    ]
    out_proc = subprocess.Popen(out_cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)

    frame_size = 576 * 1024 * 3
    frame_idx = 0

    print("Processing frames with pixel-perfect HotShort branding...")
    while True:
        raw_frame = in_proc.stdout.read(frame_size)
        if not raw_frame or len(raw_frame) < frame_size:
            break

        t = frame_idx / fps

        # 1. Google Search Scene (8.2s <= t < 11.2s)
        if 8.2 <= t < 11.2:
            img = Image.frombytes("RGB", (576, 1024), raw_frame)
            draw = ImageDraw.Draw(img)
            # Cover search input box text (x: 170 to 480, y: 255 to 295)
            draw.rectangle([170, 255, 480, 295], fill=(255, 255, 255))
            draw.text((175, 275), "hotshort.ai", fill=(30, 30, 30), font=font_search, anchor="lm")
            draw.line([(300, 260), (300, 290)], fill=(66, 133, 244), width=2)

            # Cover suggestions block entirely (x: 170 to 520, y: 310 to 860)
            draw.rectangle([170, 310, 520, 860], fill=(255, 255, 255))
            # Write crisp HotShort suggestions
            suggestions = [
                "hotshort",
                "hotshort ai",
                "hotshort.ai free",
                "hotshort viral streamer clips",
                "hotshort ai generator",
                "hotshort video maker",
                "hotshort app download",
                "hotshort automation"
            ]
            for idx, text in enumerate(suggestions):
                sy = 345 + idx * 68
                draw.text((175, sy), text, fill=(30, 30, 30), font=font_bold, anchor="lm")
            raw_frame = img.tobytes()

        # 2. Browser Bottom Address Pill (11.2s <= t < 21.2s)
        elif 11.2 <= t < 21.2:
            img = Image.frombytes("RGB", (576, 1024), raw_frame)
            draw = ImageDraw.Draw(img)
            # Address pill exact coordinates: x: 215 to 370, y: 890 to 922
            draw.rectangle([215, 890, 370, 922], fill=(241, 241, 242))
            draw.text((220, 906), "app.hotshort.ai", fill=(30, 30, 35), font=font_pill, anchor="lm")
            raw_frame = img.tobytes()

        # 3. Call To Action Bubble (30.4s <= t)
        elif t >= 30.4:
            img = Image.frombytes("RGB", (576, 1024), raw_frame)
            draw = ImageDraw.Draw(img)
            # White link bubble (x: 95 to 420, y: 520 to 585)
            draw.rectangle([95, 520, 420, 585], fill=(255, 255, 255))
            draw.text((105, 552), "https://hotshort.ai/", fill=(18, 18, 20), font=font_bubble, anchor="lm")
            raw_frame = img.tobytes()

        out_proc.stdin.write(raw_frame)
        frame_idx += 1

    in_proc.stdout.close()
    in_proc.wait()
    out_proc.stdin.close()
    out_proc.wait()

    print(f"\n Master Viral Clip Rendered: {OUTPUT_VIDEO}")
    return OUTPUT_VIDEO

if __name__ == "__main__":
    process_and_render_video()
