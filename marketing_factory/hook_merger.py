import os
import sys

# Try importing moviepy, if not available suggest installing it
try:
    from moviepy.editor import VideoFileClip, TextClip, CompositeVideoClip, concatenate_videoclips, AudioFileClip, ColorClip
except ImportError:
    print("Please install moviepy: pip install moviepy==1.0.3")
    sys.exit(1)

def build_marketing_video(hook_path: str, generated_clip_path: str, output_path: str):
    """
    Merges a real viral hook (e.g., Lacy BMW) with an AI generated clip,
    adding a high-converting bridge in between.
    """
    print(f"[MARKETING] Loading Hook: {hook_path}")
    hook_clip = VideoFileClip(hook_path)
    
    # We might only need the first 5 seconds of the hook if it's too long
    if hook_clip.duration > 8:
        hook_clip = hook_clip.subclip(0, 8)
        
    print(f"[MARKETING] Loading AI Generated Clip: {generated_clip_path}")
    proof_clip = VideoFileClip(generated_clip_path)
    
    # Ensure all clips are 9:16 vertical video (1080x1920)
    target_resolution = (1080, 1920)
    if hook_clip.size != target_resolution:
        hook_clip = hook_clip.resize(height=1920).crop(x_center=hook_clip.w/2, width=1080)
    
    if proof_clip.size != target_resolution:
        proof_clip = proof_clip.resize(height=1920).crop(x_center=proof_clip.w/2, width=1080)
        
    print("[MARKETING] Creating the 'Bridge'...")
    # The Bridge: 2.5 seconds black screen with bold text
    bridge_duration = 2.5
    bridge_bg = ColorClip(size=target_resolution, color=(15, 15, 15), duration=bridge_duration)
    
    # Needs ImageMagick installed for TextClip, falling back to basic setup
    try:
        txt_clip = TextClip(
            "He made $50k+ clipping videos.\n\nNow AI does it for you in 1 click.",
            fontsize=65, 
            color='white', 
            font='Impact',
            method='caption',
            size=(900, None),
            align='center'
        )
        txt_clip = txt_clip.set_position('center').set_duration(bridge_duration)
        bridge = CompositeVideoClip([bridge_bg, txt_clip])
    except Exception as e:
        print("[WARNING] ImageMagick not found or TextClip failed. Using empty bridge.")
        bridge = bridge_bg

    print("[MARKETING] Concatenating the final masterpiece...")
    # Sequence: Lacy BMW Hook -> Bridge -> HotShort AI Output
    final_video = concatenate_videoclips([hook_clip, bridge, proof_clip], method="compose")
    
    print(f"[MARKETING] Rendering Final Video -> {output_path}")
    final_video.write_videofile(
        output_path, 
        fps=30, 
        codec="libx264", 
        audio_codec="aac", 
        preset="fast",
        threads=4
    )
    
    print("[MARKETING] ✅ Rendering Complete!")
    return output_path

if __name__ == "__main__":
    # Test paths
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    hook_file = os.path.join(BASE_DIR, "master_assets", "lacy_bmw_hook_h264.mp4")
    
    # Use one of the recently generated TJR videos as the proof
    test_proof = os.path.join(BASE_DIR, "Overnight_Factory", "Output", "TJR_trader", "clip_10_65_134.mp4")
    out_file = os.path.join(BASE_DIR, "scratch", "marketing_bmw_ad.mp4")
    
    if not os.path.exists(hook_file):
        print(f"Hook file not found at {hook_file}")
    elif not os.path.exists(test_proof):
        print(f"Proof file not found at {test_proof}")
    else:
        build_marketing_video(hook_file, test_proof, out_file)
