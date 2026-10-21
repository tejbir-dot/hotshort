import os
import sys
import subprocess
from moviepy.editor import (
    AudioFileClip,
    CompositeAudioClip,
    CompositeVideoClip,
    ImageClip,
    VideoFileClip,
    concatenate_videoclips
)
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.abspath("."))
from marketing_factory.captions_engine import render_caption_frame

REF_VIDEO = r"Overnight_Factory\Output\TJR_trader_new\cXlVBiwIlbI\Here is how I make viral streamer clips 🎥🤖 _tiktokautomation _ai _aitools _contentcreator _makemoneyontiktok (MP4).mp4"
OUTPUT_FILE = r"marketing_factory/output/hotshort_viral_masterpiece.mp4"
RESOLUTION = (576, 1024)

def build_scene3_hotshort():
    """
    Builds Scene 3: HotShort AI App UI inside iPhone mockup + cursor + captions.
    Duration: 8.2s
    """
    duration = 8.2
    # Base background
    bg = ImageClip("marketing_factory/assets/bg_circles.jpg").resize(RESOLUTION).set_duration(duration)

    # Phone frame & HotShort screen demo
    phone_w = 480
    screen_w = 440
    phone_x = (RESOLUTION[0] - phone_w) // 2
    screen_x = (RESOLUTION[0] - screen_w) // 2
    phone_y = 60
    screen_y = phone_y + 10

    raw_ui = VideoFileClip("marketing_factory/assets/hotshort_screen_demo.mp4")
    ui_clip = raw_ui.subclip(0, duration).resize(width=screen_w).set_pos((screen_x, screen_y)).set_duration(duration)
    phone_frame = ImageClip("marketing_factory/assets/phone_frame.png").resize(width=phone_w).set_pos((phone_x, phone_y)).set_duration(duration)

    # Programmatic cursor
    cursor = ImageClip("marketing_factory/assets/cursor.png").resize(width=54).set_duration(duration)
    def cursor_pos(t):
        if t < 0.8:
            return (RESOLUTION[0] - 80, 800)
        elif 0.8 <= t < 2.0:
            p = (t - 0.8) / 1.2
            return (int((RESOLUTION[0] - 80) - p * 220), int(800 - p * 520))
        elif 2.0 <= t < 3.8:
            return (280, 280)
        elif 3.8 <= t < 5.2:
            p = (t - 3.8) / 1.4
            return (280, int(280 + p * 380))
        elif 5.2 <= t < 5.6:
            return (280, 665)
        else:
            return (310, 680)

    cursor = cursor.set_pos(cursor_pos)

    # Click ripple at t=5.2s
    ripple = (
        ImageClip("marketing_factory/assets/click_ripple.png")
        .resize(width=100)
        .set_start(5.2)
        .set_duration(0.6)
        .set_pos((230, 615))
        .crossfadein(0.1)
    )

    # Dynamic Captions for Scene 3
    # "Step two, I open HotShort, paste in the link, and hit ignite. Then pick your background music, AI voice, and style of captions."
    scene3_captions = [
        ("STEP 2,", 0.0, 1.2),
        ("OPEN HOTSHORT,", 1.2, 2.6),
        ("PASTE THE LINK,", 2.6, 4.0),
        ("HIT IGNITE,", 4.0, 5.5),
        ("PICK CAPTIONS,", 5.5, 6.8),
        ("AND AI VOICE.", 6.8, 8.2)
    ]
    caption_clips = []
    for txt, st, et in scene3_captions:
        arr = render_caption_frame(txt, width=540, height=120, font_size=52)
        c = ImageClip(arr).set_start(st).set_duration(et - st).set_pos(("center", 820))
        caption_clips.append(c)

    # Audio for Scene 3: Voice + Central Cee beat
    voice = AudioFileClip("scratch/marketing_factory/voice_scene3.mp3").set_duration(duration)
    # Loop reference beat at 15% volume
    beat = AudioFileClip("marketing_factory/assets/ref_audio.mp3").subclip(8.0, 8.0 + duration).volumex(0.18)
    audio = CompositeAudioClip([voice, beat])

    scene3 = CompositeVideoClip(
        [bg, ui_clip, phone_frame, cursor, ripple, *caption_clips],
        size=RESOLUTION
    ).set_duration(duration).set_audio(audio)

    return scene3

def build_scene5_cta():
    """
    Builds Scene 5: Funnel Call To Action with Real Colored Vision Pro Avatar & Chat Bubbles.
    Duration: 4.2s
    """
    duration = 4.2
    bg = ImageClip("marketing_factory/assets/bg_circles.jpg").resize(RESOLUTION).set_duration(duration)

    # Real colored Vision Pro Avatar at bottom
    avatar = ImageClip("marketing_factory/assets/ref_avatar_raw.png").resize(width=576).set_pos(("center", 490)).set_duration(duration)

    # Chat bubbles
    user_bubble = (
        ImageClip("marketing_factory/assets/cta_user_bubble.png")
        .resize(width=200)
        .set_start(0.2)
        .set_duration(duration - 0.2)
        .set_pos((330, 240))
        .crossfadein(0.2)
    )
    reply_bubble = (
        ImageClip("marketing_factory/assets/cta_reply_bubble.png")
        .resize(width=340)
        .set_start(0.8)
        .set_duration(duration - 0.8)
        .set_pos((60, 340))
        .crossfadein(0.25)
    )

    # Dynamic Captions
    cta_captions = [
        ("COMMENT AI,", 0.0, 1.4),
        ("I'LL DM YOU,", 1.4, 2.8),
        ("FOR FREE.", 2.8, 4.2)
    ]
    caption_clips = []
    for txt, st, et in cta_captions:
        arr = render_caption_frame(txt, width=540, height=120, font_size=52)
        c = ImageClip(arr).set_start(st).set_duration(et - st).set_pos(("center", 430))
        caption_clips.append(c)

    # Audio
    voice = AudioFileClip("scratch/marketing_factory/voice_scene5.mp3").set_duration(duration)
    beat = AudioFileClip("marketing_factory/assets/ref_audio.mp3").subclip(28.0, 28.0 + duration).volumex(0.20)
    audio = CompositeAudioClip([voice, beat])

    scene5 = CompositeVideoClip(
        [bg, user_bubble, reply_bubble, avatar, *caption_clips],
        size=RESOLUTION
    ).set_duration(duration).set_audio(audio)

    return scene5

def assemble_masterpiece():
    print("=" * 60)
    print("ASSEMBLING HOTSHORT MASTERPIECE VIRAL PROMO CLIP")
    print("=" * 60)
    os.makedirs("marketing_factory/output", exist_ok=True)

    raw_ref = VideoFileClip(REF_VIDEO).resize(RESOLUTION)

    # Scene 1: Hook (0.0s to 3.8s) from ref_video
    print("[1/5] Extracting Scene 1 (Hook with colored avatar & 3 cards)...")
    s1 = raw_ref.subclip(0.0, 3.8)

    # Scene 2: YouTube Link Copy (3.8s to 7.8s) from ref_video
    print("[2/5] Extracting Scene 2 (YouTube app copy link)...")
    s2 = raw_ref.subclip(3.8, 7.8)

    # Scene 3: HotShort AI Web App Showcase (Built programmatically)
    print("[3/5] Building Scene 3 (HotShort AI app demo + cursor click)...")
    s3 = build_scene3_hotshort()

    # Scene 4: Viral Result Short (19.8s to 27.5s from ref_video)
    print("[4/5] Extracting Scene 4 (Viral result preview - IShowSpeed)...")
    s4 = raw_ref.subclip(19.8, 27.5)

    # Scene 5: Funnel Call To Action
    print("[5/5] Building Scene 5 (Chat bubbles + Real Vision Pro Avatar)...")
    s5 = build_scene5_cta()

    print("\nConcatenating scenes into final master video...")
    final = concatenate_videoclips([s1, s2, s3, s4, s5], method="compose")

    print(f"Total Video Duration: {final.duration:.2f}s")
    final.write_videofile(
        OUTPUT_FILE,
        fps=30,
        codec="libx264",
        audio_codec="aac",
        preset="fast",
        threads=8,
        logger=None
    )
    print(f"\n🎉 MASTERPIECE RENDER COMPLETE: {OUTPUT_FILE}")
    return OUTPUT_FILE

if __name__ == "__main__":
    assemble_masterpiece()
