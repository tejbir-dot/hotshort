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

def ease_out_back(t, s=1.70158):
    t = max(0.0, min(1.0, t))
    t = t - 1.0
    return t * t * ((s + 1.0) * t + s) + 1.0

def create_promo_video(
    script_text,
    output_filename="marketing_factory/output/hotshort_generativo_promo.mp4",
    bg_video_path="marketing_factory/assets/bg_generativo.mp4",
    voice="en-US-BrianMultilingualNeural",
    cta_user_bubble_path=None,
    cta_reply_bubble_path=None
):
    print("=" * 60)
    print("HOTSHORT MARKETING FACTORY - RENDERING MASTER VIRAL PROMO")
    print("=" * 60)
    os.makedirs(os.path.dirname(os.path.abspath(output_filename)), exist_ok=True)

    # 1. Synthesize Voiceover & Timestamps
    print("[1/6] Synthesizing Voiceover & Extracting Word Timestamps...")
    audio_path, caption_chunks = generate_voiceover(
        script_text,
        voice=voice,
        output_path="scratch/marketing_factory/promo_voice.mp3"
    )
    voice_clip = AudioFileClip(audio_path)
    total_duration = max(21.8, voice_clip.duration + 0.8)
    print(f"      Voice Duration: {voice_clip.duration:.2f}s | Total Video: {total_duration:.2f}s | Captions: {len(caption_chunks)} chunks")

    # 2. Base Background Layer (for CTA and transitions)
    print("[2/6] Loading 3D Generative Particle Wave Background...")
    raw_bg = VideoFileClip(bg_video_path).resize(RESOLUTION).without_audio()
    if raw_bg.duration < total_duration:
        bg_clip = raw_bg.loop(duration=total_duration)
    else:
        bg_clip = raw_bg.subclip(0, total_duration)

    # 3. Hook Layer (0.0s to 4.5s) - 3 Live Playing Video Cards with View Pills + Cyber Avatar
    print("[3/6] Attaching Live Playing Hook Track (3 Speed Video Cards + Cyber Avatar)...")
    hook_duration = 4.5
    hook_track_path = "marketing_factory/assets/hook_track.mp4"
    hook_track = (
        VideoFileClip(hook_track_path)
        .without_audio()
        .set_start(0.0)
        .set_duration(hook_duration)
    )

    # 4. Center Phone Layer (starts at 4.5s to 17.5s) - Cinematic InShot + HotShort + Short Reveal
    print("[4/6] Compositing Cinematic Dynamic Camera UI Track (YouTube InShot + HotShort + Short Reveal)...")
    ui_start = 4.5
    cta_start = 17.5
    ui_end = cta_start
    ui_duration = ui_end - ui_start

    cinematic_ui_path = "marketing_factory/assets/cinematic_ui_bg_track.mp4"
    cinematic_track = (
        VideoFileClip(cinematic_ui_path)
        .without_audio()
        .set_start(ui_start)
        .set_duration(ui_duration)
        .crossfadein(0.2)
    )

    # 5. Avatar CTA Layer (17.5s to total_duration)
    print("[5/6] Preparing Cyber Vision Pro Avatar for CTA...")
    avatar_rgb_path = "marketing_factory/assets/Man_speaking_with_VR_headset_20261021215440.mp4"
    avatar_mask_path = "marketing_factory/assets/avatar_mask.mp4"
    avatar_w = 640

    raw_avatar_rgb = VideoFileClip(avatar_rgb_path).without_audio()
    raw_avatar_mask = VideoFileClip(avatar_mask_path).to_mask()
    animated_avatar = raw_avatar_rgb.set_mask(raw_avatar_mask).resize(width=avatar_w)

    cta_duration = total_duration - cta_start
    cta_clip_start = 2.5
    avatar_cta = (
        animated_avatar.subclip(cta_clip_start, min(raw_avatar_rgb.duration, cta_clip_start + cta_duration))
        .set_start(cta_start)
        .set_duration(cta_duration)
        .set_pos(("center", 580))
        .crossfadein(0.25)
    )

    # CTA Speech Bubbles with Ease-Out Back Spring Dynamics
    user_bubble_img = cta_user_bubble_path or "marketing_factory/assets/cta_user_bubble.png"
    reply_bubble_img = cta_reply_bubble_path or "marketing_factory/assets/cta_reply_bubble.png"

    im_u = Image.open(user_bubble_img)
    base_uw = 260
    base_uh = int(im_u.height * (base_uw / float(im_u.width)))
    u_cx, u_cy = 490, 330
    u_pop_dur = 0.35

    def u_scale_fn(t):
        if t < 0:
            return 0.01
        if t < u_pop_dur:
            return max(0.01, ease_out_back(t / u_pop_dur, s=2.2))
        return 1.0

    def u_pos_fn(t):
        s = u_scale_fn(t)
        return (int(round(u_cx - (base_uw * s) / 2.0)), int(round(u_cy - (base_uh * s) / 2.0)))

    cta_bubble_user = (
        ImageClip(user_bubble_img)
        .resize(width=base_uw)
        .resize(u_scale_fn)
        .set_start(cta_start + 0.3)
        .set_duration(cta_duration - 0.3)
        .set_pos(u_pos_fn)
    )

    im_r = Image.open(reply_bubble_img)
    base_rw = 440
    base_rh = int(im_r.height * (base_rw / float(im_r.width)))
    r_cx, r_cy = 325, 450
    r_pop_dur = 0.38

    def r_scale_fn(t):
        if t < 0:
            return 0.01
        if t < r_pop_dur:
            return max(0.01, ease_out_back(t / r_pop_dur, s=2.2))
        return 1.0

    def r_pos_fn(t):
        s = r_scale_fn(t)
        return (int(round(r_cx - (base_rw * s) / 2.0)), int(round(r_cy - (base_rh * s) / 2.0)))

    cta_bubble_reply = (
        ImageClip(reply_bubble_img)
        .resize(width=base_rw)
        .resize(r_scale_fn)
        .set_start(cta_start + 0.8)
        .set_duration(cta_duration - 0.8)
        .set_pos(r_pos_fn)
    )

    # 6. Dynamic Word Captions
    print("[6/6] Generating Dynamic Captions with High-Contrast Punch...")
    caption_clips = []
    for chunk in caption_chunks:
        c_text = chunk["text"]
        c_start = float(chunk["start"])
        c_end = float(chunk["end"])
        dur = max(0.2, c_end - c_start)

        # Positioning:
        # During Hook: above avatar / between cards (y = 510)
        # During UI: comfortably below phone (y = 1040)
        # During CTA: top center (y = 170)
        if c_start < hook_duration:
            y_pos = 510
        elif c_start < ui_end:
            y_pos = 1040
        else:
            y_pos = 170

        frame_arr = render_caption_frame(c_text.upper(), width=680, height=130, font_size=56)
        c_clip = (
            ImageClip(frame_arr)
            .set_start(c_start)
            .set_duration(dur)
            .set_pos(("center", y_pos))
        )
        caption_clips.append(c_clip)

    # 7. Audio Compositing (Voice + Beat + Precision SFX)
    print("      Compositing High-Impact SFX Audio Tracks...")
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

    # Intro Hook: Sequential ASMR pops as the 3 viral thumbnails spring in
    add_sfx("marketing_factory/assets/sfx/whoosh_swoosh.mp3", start_t=0.0, volume=0.40)
    add_sfx("marketing_factory/assets/sfx/pop_bubble.mp3", start_t=0.15, volume=0.70)  # Left Card spring bounce
    add_sfx("marketing_factory/assets/sfx/pop_click.mp3", start_t=0.35, volume=0.70, max_dur=0.4)   # Right Card spring bounce
    add_sfx("marketing_factory/assets/sfx/pop_bubble.mp3", start_t=0.55, volume=0.85)  # Center Card front bounce
    add_sfx("marketing_factory/assets/sfx/money_ching.mp3", start_t=0.85, volume=0.60) # Millions view count lock

    # Transition to YouTube mobile screen
    add_sfx("marketing_factory/assets/sfx/whoosh_fast.mp3", start_t=max(0, ui_start - 0.2), volume=0.40)

    # InShot YouTube Share & Copy Link taps
    add_sfx("marketing_factory/assets/sfx/pop_bubble.mp3", start_t=ui_start + 3.2, volume=0.60)
    add_sfx("marketing_factory/assets/sfx/money_ching.mp3", start_t=ui_start + 4.2, volume=0.60)

    # Transition to HotShort Studio (ui_start + 4.80s = 9.30s)
    add_sfx("marketing_factory/assets/sfx/whoosh_fast.mp3", start_t=ui_start + 4.8, volume=0.35)

    # Micro-Interaction 1: Dropdown Click (t = ui_start + 5.52 = 10.02s)
    add_sfx("marketing_factory/assets/sfx/mouse_click_mech.mp3", start_t=ui_start + 5.52, volume=0.85)

    # Micro-Interaction 2: "Hormozi Bold" Caption Select (t = ui_start + 6.32 = 10.82s)
    add_sfx("marketing_factory/assets/sfx/pop_bubble.mp3", start_t=ui_start + 6.32, volume=0.80)

    # Micro-Interaction 3: AI Face-Tracking Toggle ON flip (t = ui_start + 7.04 = 11.54s)
    add_sfx("marketing_factory/assets/sfx/mouse_click_mech.mp3", start_t=ui_start + 7.04, volume=0.90)

    # Micro-Interaction 4: Ignite Button Click & AI Pulse (t = ui_start + 7.84 = 12.34s)
    add_sfx("marketing_factory/assets/sfx/mouse_click_mech.mp3", start_t=ui_start + 7.84, volume=0.95)
    add_sfx("marketing_factory/assets/sfx/money_ching.mp3", start_t=ui_start + 7.95, volume=0.55)

    # Transition into Reveal Playing Viral Short (t = ui_start + 8.60s = 13.10s)
    add_sfx("marketing_factory/assets/sfx/whoosh_swoosh.mp3", start_t=ui_start + 8.6, volume=0.50)
    add_sfx("marketing_factory/assets/sfx/money_ching.mp3", start_t=ui_start + 10.5, volume=0.45)

    # CTA transition whoosh + DM bubble pops + money ching (t = cta_start = 17.5s)
    add_sfx("marketing_factory/assets/sfx/whoosh_swoosh.mp3", start_t=max(0, cta_start - 0.1), volume=0.40)
    add_sfx("marketing_factory/assets/sfx/pop_bubble.mp3", start_t=cta_start + 0.3, volume=0.80)  # User bubble spring pop
    add_sfx("marketing_factory/assets/sfx/pop_bubble.mp3", start_t=cta_start + 0.8, volume=0.85)  # Reply card spring pop
    add_sfx("marketing_factory/assets/sfx/money_ching.mp3", start_t=cta_start + 1.5, volume=0.65)  # Free link chime

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
            print("      Clean instrumental trap beat attached (12% volume)")
        except Exception as e:
            print(f"      Note: Background beat skipped ({e})")

    audio_tracks.extend(sfx_tracks)
    final_audio = CompositeAudioClip(audio_tracks)

    # 8. Assembly & Rendering
    print("      Encoding Final Masterpiece Video with MoviePy & FFmpeg...")
    final_video = CompositeVideoClip(
        [
            bg_clip,
            hook_track,
            cinematic_track,
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

    print(f"\n============================================================")
    print(f"RENDER COMPLETE! Master Video saved to: {output_filename}")
    print(f"============================================================")
    return output_filename

if __name__ == "__main__":
    demo_script = (
        "Here is how I make these viral streamer clips that are generating millions of views. "
        "First, go to YouTube, pick any viral stream record, and copy its link. "
        "Step two, paste it into HotShort and hit analyze. "
        "And in just seconds, you get crystal-clear viral shorts with dynamic captions. "
        "Comment AI, and I will DM you the link for free."
    )
    create_promo_video(demo_script, output_filename="marketing_factory/output/hotshort_generativo_promo.mp4")
