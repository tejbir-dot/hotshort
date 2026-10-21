import os
import sys
sys.path.insert(0, os.path.abspath("."))
import math
import numpy as np
from PIL import Image
from moviepy.editor import (
    AudioFileClip,
    CompositeAudioClip,
    CompositeVideoClip,
    ImageClip,
    VideoFileClip,
)
from marketing_factory.captions_engine import render_caption_frame
from marketing_factory.tts_engine import generate_voiceover

# Configuration
RESOLUTION = (720, 1280)
FPS = 30

def create_promo_video(
    script_text,
    output_filename="marketing_factory/output/hotshort_generativo_promo.mp4",
    bg_video_path="marketing_factory/assets/bg_generativo.mp4",
    voice="en-US-ChristopherNeural"
):
    print("=" * 60)
    print("HOTSHORT MARKETING FACTORY - RENDERING WITH GENERATIVE 3D WAVE")
    print("=" * 60)
    os.makedirs(os.path.dirname(os.path.abspath(output_filename)), exist_ok=True)

    # 1. Synthesize Voiceover & Timestamps
    print("[1/6] Synthesizing Voiceover & Extracting Timestamps...")
    audio_path, caption_chunks = generate_voiceover(
        script_text,
        voice=voice,
        output_path="scratch/marketing_factory/promo_voice.mp3"
    )
    voice_clip = AudioFileClip(audio_path)
    total_duration = max(18.0, voice_clip.duration + 1.2)
    print(f"      Duration: {total_duration:.2f}s | Captions: {len(caption_chunks)} chunks")

    # 2. Animated Generative 3D Background Layer (Diseño Generativo)
    print("[2/6] Loading 3D Generative Particle Wave Background...")
    raw_bg = VideoFileClip(bg_video_path).resize(RESOLUTION).without_audio()
    if raw_bg.duration < total_duration:
        bg_clip = raw_bg.loop(duration=total_duration)
    else:
        bg_clip = raw_bg.subclip(0, total_duration)

    # 3. Hook Layer (0.0s to 3.8s) - 3 Floating Thumbnail Cards
    print("[3/6] Generating Realistic Hook Cards & Avatar...")
    hook_duration = 3.8
    c_left = (
        ImageClip("marketing_factory/assets/hook_card_left.png")
        .resize(width=220)
        .set_start(0)
        .set_duration(hook_duration)
        .set_pos((25, 140))
        .crossfadein(0.3)
    )
    c_center = (
        ImageClip("marketing_factory/assets/hook_card_center.png")
        .resize(width=270)
        .set_start(0)
        .set_duration(hook_duration)
        .set_pos(("center", 90))
        .crossfadein(0.2)
    )
    c_right = (
        ImageClip("marketing_factory/assets/hook_card_right.png")
        .resize(width=220)
        .set_start(0)
        .set_duration(hook_duration)
        .set_pos((475, 140))
        .crossfadein(0.3)
    )

    # 4. Center Phone Layer (starts at 3.8s until 13.8s) - HotShort Branded App UI
    print("[4/6] Compositing HotShort App UI & Programmatic Cursor...")
    ui_start = 3.8
    ui_end = min(total_duration - 4.2, 14.0)
    ui_duration = ui_end - ui_start

    phone_w = 480
    screen_w = 434
    phone_x = (RESOLUTION[0] - phone_w) // 2
    screen_x = (RESOLUTION[0] - screen_w) // 2
    phone_y = 70
    screen_y = phone_y + 10

    raw_ui = VideoFileClip("marketing_factory/assets/hotshort_screen_demo.mp4").without_audio()
    if raw_ui.duration < ui_duration:
        raw_ui = raw_ui.loop(duration=ui_duration)
    else:
        raw_ui = raw_ui.subclip(0, ui_duration)

    ui_clip = (
        raw_ui.resize(width=screen_w)
        .set_start(ui_start)
        .set_duration(ui_duration)
        .set_pos((screen_x, screen_y))
        .crossfadein(0.3)
    )

    phone_frame = (
        ImageClip("marketing_factory/assets/phone_frame.png")
        .resize(width=phone_w)
        .set_start(ui_start)
        .set_duration(ui_duration)
        .set_pos((phone_x, phone_y))
        .crossfadein(0.3)
    )

    # Programmatic Mouse Cursor Animation
    cursor = ImageClip("marketing_factory/assets/cursor.png").resize(width=52).set_start(ui_start).set_duration(ui_duration)

    def cursor_pos(t):
        if t < 0.6:
            return (RESOLUTION[0] - 80, 800)
        elif 0.6 <= t < 1.8:
            p = (t - 0.6) / 1.2
            return (int((RESOLUTION[0] - 80) - p * 220), int(800 - p * 500))
        elif 1.8 <= t < 3.8:
            return (360, 300)
        elif 3.8 <= t < 5.3:
            p = (t - 3.8) / 1.5
            return (360, int(300 + p * 330))
        elif 5.3 <= t < 5.7:
            return (360, 635)
        else:
            return (390, 650)

    cursor = cursor.set_pos(cursor_pos)

    # Click ripple at ignite button
    ripple_clip = (
        ImageClip("marketing_factory/assets/click_ripple.png")
        .resize(width=100)
        .set_start(ui_start + 5.3)
        .set_duration(0.6)
        .set_pos((310, 585))
        .crossfadein(0.1)
    )

    # 5. Reveal Clip (starts at ui_end until total_duration - 3.2s)
    reveal_start = ui_end
    reveal_end = total_duration - 3.2
    reveal_duration = max(1.0, reveal_end - reveal_start)

    reveal_raw = VideoFileClip("marketing_factory/assets/reveal_clip.mp4").without_audio()
    if reveal_raw.duration < reveal_duration:
        reveal_raw = reveal_raw.loop(duration=reveal_duration)
    else:
        reveal_raw = reveal_raw.subclip(0, reveal_duration)

    reveal_scaled = (
        reveal_raw.resize(width=500)
        .set_start(reveal_start)
        .set_duration(reveal_duration)
        .set_pos(("center", 90))
        .crossfadein(0.3)
    )

    # 6. Avatar Layer (Animated Cyber Vision Pro Avatar with mask)
    avatar_rgb_path = "marketing_factory/assets/Man_speaking_with_VR_headset_20261021215440.mp4"
    avatar_mask_path = "marketing_factory/assets/avatar_mask.mp4"
    avatar_w = 640

    if not os.path.exists(avatar_mask_path):
        print("      Generating avatar mask video...")
        import cv2
        cap_av = cv2.VideoCapture(avatar_rgb_path)
        fps_av = cap_av.get(cv2.CAP_PROP_FPS) or 24.0
        w_av = int(cap_av.get(cv2.CAP_PROP_FRAME_WIDTH))
        h_av = int(cap_av.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out_av = cv2.VideoWriter(avatar_mask_path, fourcc, fps_av, (w_av, h_av), isColor=True)
        while True:
            ret, frame = cap_av.read()
            if not ret: break
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            mask_buf = np.zeros((h_av+2, w_av+2), np.uint8)
            cv2.floodFill(gray.copy(), mask_buf, (0, 0), 255, 18, 18, flags=8 | (255 << 8) | cv2.FLOODFILL_MASK_ONLY)
            cv2.floodFill(gray.copy(), mask_buf, (w_av-1, 0), 255, 18, 18, flags=8 | (255 << 8) | cv2.FLOODFILL_MASK_ONLY)
            bg_mask = mask_buf[1:-1, 1:-1] == 255
            fg_mask = np.where(bg_mask, 0, 255).astype(np.uint8)
            fg_mask = cv2.GaussianBlur(fg_mask, (3, 3), 0)
            out_av.write(cv2.cvtColor(fg_mask, cv2.COLOR_GRAY2BGR))
        cap_av.release()
        out_av.release()

    raw_avatar_rgb = VideoFileClip(avatar_rgb_path).without_audio()
    raw_avatar_mask = VideoFileClip(avatar_mask_path).to_mask()
    animated_avatar = raw_avatar_rgb.set_mask(raw_avatar_mask).resize(width=avatar_w)

    # Hook avatar (0 to hook_duration)
    avatar_hook = (
        animated_avatar.subclip(0, min(raw_avatar_rgb.duration, hook_duration))
        .set_start(0)
        .set_duration(hook_duration)
        .set_pos(("center", 580))
    )

    # CTA avatar (cta_start to total_duration)
    cta_start = total_duration - 3.5
    cta_duration = 3.5
    cta_clip_start = 3.0
    avatar_cta = (
        animated_avatar.subclip(cta_clip_start, min(raw_avatar_rgb.duration, cta_clip_start + cta_duration))
        .set_start(cta_start)
        .set_duration(cta_duration)
        .set_pos(("center", 580))
        .crossfadein(0.3)
    )

    # 7. CTA Layer (Last 3.5 seconds)
    cta_bubble_user = (
        ImageClip("marketing_factory/assets/cta_user_bubble.png")
        .resize(width=250)
        .set_start(cta_start + 0.2)
        .set_duration(cta_duration - 0.2)
        .set_pos((380, 290))
        .crossfadein(0.2)
    )
    cta_bubble_reply = (
        ImageClip("marketing_factory/assets/cta_reply_bubble.png")
        .resize(width=430)
        .set_start(cta_start + 0.7)
        .set_duration(cta_duration - 0.7)
        .set_pos((110, 400))
        .crossfadein(0.25)
    )

    # 8. Dynamic Word Captions
    print("[5/6] Generating Dynamic Captions...")
    caption_clips = []
    for chunk in caption_chunks:
        c_text = chunk["text"]
        c_start = float(chunk["start"])
        c_end = float(chunk["end"])
        dur = max(0.2, c_end - c_start)

        # Place captions nicely:
        # During hook: between cards and avatar (y=500)
        # During UI: near bottom of screen (y=730)
        # During reveal: middle bottom (y=660)
        # During CTA: top/middle (y=200)
        if c_start < hook_duration:
            y_pos = 500
        elif c_start < ui_end:
            y_pos = 730
        elif c_start < cta_start:
            y_pos = 660
        else:
            y_pos = 200

        frame_arr = render_caption_frame(c_text.upper(), width=680, height=130, font_size=58)
        c_clip = (
            ImageClip(frame_arr)
            .set_start(c_start)
            .set_duration(dur)
            .set_pos(("center", y_pos))
        )
        caption_clips.append(c_clip)

    # 9. Audio Compositing (Voice + Music Beat + SFX Sound Effects)
    print("      Attaching High-Impact Kadak Sound Effects (Whoosh, Click, Ching, Pop)...")
    sfx_tracks = []
    
    def add_sfx(path, start_t, volume=1.0, max_dur=None):
        if os.path.exists(path):
            try:
                clip = AudioFileClip(path).volumex(volume)
                if max_dur:
                    clip = clip.subclip(0, min(clip.duration, max_dur))
                clip = clip.set_start(start_t)
                sfx_tracks.append(clip)
            except Exception as ex:
                print(f"      SFX load error {path}: {ex}")

    # SFX 1: Hook whoosh + money ching on view cards
    add_sfx("marketing_factory/assets/sfx/whoosh_swoosh.mp3", start_t=0.0, volume=0.45)
    add_sfx("marketing_factory/assets/sfx/money_ching.mp3", start_t=0.4, volume=0.55)

    # SFX 2: UI transition whoosh
    add_sfx("marketing_factory/assets/sfx/whoosh_fast.mp3", start_t=max(0, ui_start - 0.2), volume=0.40)

    # SFX 3: Mechanical Mouse Click at Ignite button
    click_time = ui_start + 5.3
    add_sfx("marketing_factory/assets/sfx/mouse_click_mech.mp3", start_t=click_time, volume=0.85)

    # SFX 4: Reveal transition whoosh
    add_sfx("marketing_factory/assets/sfx/whoosh_fast.mp3", start_t=max(0, reveal_start - 0.1), volume=0.40)

    # SFX 5: CTA transition whoosh + DM bubble pops + money ching
    add_sfx("marketing_factory/assets/sfx/whoosh_swoosh.mp3", start_t=max(0, cta_start - 0.1), volume=0.40)
    add_sfx("marketing_factory/assets/sfx/pop_bubble.mp3", start_t=cta_start + 0.2, volume=0.70)
    add_sfx("marketing_factory/assets/sfx/pop_bubble.mp3", start_t=cta_start + 0.7, volume=0.70)
    add_sfx("marketing_factory/assets/sfx/money_ching.mp3", start_t=cta_start + 1.8, volume=0.60)

    audio_tracks = [voice_clip]
    music_beat_path = "marketing_factory/assets/bg_music_trap.mp3"
    if os.path.exists(music_beat_path):
        try:
            bg_music = (
                AudioFileClip(music_beat_path)
                .volumex(0.12)
                .set_duration(total_duration)
            )
            audio_tracks.append(bg_music)
            print("      Clean instrumental trap beat attached (12% volume, ZERO vocal bleed)")
        except Exception as e:
            print(f"      Note: Background beat skipped ({e})")

    audio_tracks.extend(sfx_tracks)
    final_audio = CompositeAudioClip(audio_tracks)

    # 10. Assembly & Rendering
    print("[6/6] Compositing Layers & Writing Video File...")
    final_video = CompositeVideoClip(
        [
            bg_clip,
            c_left,
            c_center,
            c_right,
            avatar_hook,
            ui_clip,
            phone_frame,
            cursor,
            ripple_clip,
            reveal_scaled,
            avatar_cta,
            *caption_clips,
            cta_bubble_user,
            cta_bubble_reply,
        ],
        size=RESOLUTION,
    ).set_duration(total_duration)

    final_video = final_video.set_audio(final_audio)

    final_video.write_videofile(
        output_filename,
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        preset="fast",
        threads=8,
        logger=None
    )

    print(f"\nRender Complete! Video saved to: {output_filename}")
    return output_filename

if __name__ == "__main__":
    demo_script = (
        "Here is how I make viral streamer clips generating millions of views. "
        "First, grab any link from YouTube or Kick. "
        "Step two, paste it into HotShort and hit ignite. "
        "And in just seconds, you get viral shorts with dynamic captions. "
        "Comment AI and I will DM you the link for free."
    )
    create_promo_video(demo_script, output_filename="marketing_factory/output/hotshort_generativo_promo.mp4")
