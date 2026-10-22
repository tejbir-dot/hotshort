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

    # 4. Center Phone Layer (starts at 3.8s until cta_start) - Real HotShort App & Results Carousel
    print("[4/6] Compositing Pixel-Perfect iPhone 16 Pro Mockup with Floating Levitation & Results Carousel...")
    ui_start = 3.8
    cta_start = 17.5
    ui_end = cta_start
    ui_duration = ui_end - ui_start

    screen_w = 400
    screen_h = 869 # Exact 440:956 iPhone 16 Pro Max ratio
    border_w = 8
    phone_w = screen_w + 2 * border_w # 416
    phone_h = screen_h + 2 * border_w # 885

    screen_x = (RESOLUTION[0] - screen_w) // 2 # 160
    screen_y = 68
    phone_x = screen_x - border_w # 152
    phone_y = screen_y - border_w # 60

    demo_asset = "marketing_factory/assets/real_app_demo.mp4" if os.path.exists("marketing_factory/assets/real_app_demo.mp4") else "marketing_factory/assets/hotshort_screen_demo.mp4"
    raw_ui = VideoFileClip(demo_asset).without_audio()
    if raw_ui.duration < ui_duration:
        hold_dur = ui_duration - raw_ui.duration
        last_frame_clip = raw_ui.to_ImageClip(t=raw_ui.duration - 0.05).set_duration(hold_dur)
        from moviepy.editor import concatenate_videoclips
        raw_ui = concatenate_videoclips([raw_ui, last_frame_clip])
    else:
        raw_ui = raw_ui.subclip(0, ui_duration)

    # Load screen mask directly as exact float numpy array (avoids MoviePy mask resize bug)
    mask_arr = np.array(Image.open("marketing_factory/assets/screen_mask.png").convert("L")).astype('float32') / 255.0
    screen_mask = ImageClip(mask_arr, ismask=True)

    # Floating levitation physics (sinusoidal gentle bobbing)
    def float_phone(t):
        offset_y = 10.0 * math.sin(2.0 * math.pi * 0.40 * t)
        return (phone_x, int(round(phone_y + offset_y)))

    def float_screen(t):
        offset_y = 10.0 * math.sin(2.0 * math.pi * 0.40 * t)
        return (screen_x, int(round(screen_y + offset_y)))

    ui_clip = (
        raw_ui.resize((screen_w, screen_h))
        .set_mask(screen_mask)
        .set_start(ui_start)
        .set_duration(ui_duration)
        .set_pos(float_screen)
        .crossfadein(0.25)
    )

    phone_frame = (
        ImageClip("marketing_factory/assets/phone_frame.png")
        .set_start(ui_start)
        .set_duration(ui_duration)
        .set_pos(float_phone)
        .crossfadein(0.25)
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
    cta_start = 17.5
    cta_duration = total_duration - cta_start
    cta_clip_start = 3.0
    avatar_cta = (
        animated_avatar.subclip(cta_clip_start, min(raw_avatar_rgb.duration, cta_clip_start + cta_duration))
        .set_start(cta_start)
        .set_duration(cta_duration)
        .set_pos(("center", 580))
        .crossfadein(0.3)
    )

    # 7. CTA Layer (Last seconds)
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
        # During UI: comfortably below the floating phone frame (y=980)
        # During CTA: top/middle (y=200)
        if c_start < hook_duration:
            y_pos = 500
        elif c_start < ui_end:
            y_pos = 980
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

    # SFX 2b: YouTube Speed Share button tap
    add_sfx("marketing_factory/assets/sfx/pop_bubble.mp3", start_t=ui_start + 0.6, volume=0.60)

    # SFX 2c: YouTube Speed Copy Link tap & Toast notification
    add_sfx("marketing_factory/assets/sfx/money_ching.mp3", start_t=ui_start + 1.25, volume=0.60)

    # SFX 2d: Fast transition to HotShort landing page
    add_sfx("marketing_factory/assets/sfx/whoosh_fast.mp3", start_t=ui_start + 2.5, volume=0.35)

    # SFX 3: Mechanical Mouse Click at Analyze Now button (t = 4.9s in demo)
    add_sfx("marketing_factory/assets/sfx/mouse_click_mech.mp3", start_t=ui_start + 4.9, volume=0.85)

    # SFX 4: Results Page load whoosh + 100% Viral badge chime
    add_sfx("marketing_factory/assets/sfx/whoosh_fast.mp3", start_t=ui_start + 5.2, volume=0.40)
    add_sfx("marketing_factory/assets/sfx/money_ching.mp3", start_t=ui_start + 5.5, volume=0.55)

    # SFX 5: Carousel Smooth Swipes (Card 1 -> Card 2, Card 2 -> Card 3)
    add_sfx("marketing_factory/assets/sfx/whoosh_fast.mp3", start_t=ui_start + 6.8, volume=0.35)
    add_sfx("marketing_factory/assets/sfx/whoosh_fast.mp3", start_t=ui_start + 10.0, volume=0.35)

    # SFX 6: CTA transition whoosh + DM bubble pops + money ching
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
