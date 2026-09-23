import os
import subprocess
import shutil

def apply_watermarks(input_dir, watermark_text="@DoubleCoverageClips", image_path=None):
    """
    Applies watermark to all .mp4 files in input_dir.
    Creates a temp output directory, processes, and then replaces the original files.
    """
    temp_dir = os.path.join(input_dir, "temp_watermarked")
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)
        
    for filename in os.listdir(input_dir):
        if filename.endswith(".mp4"):
            input_path = os.path.join(input_dir, filename)
            output_path = os.path.join(temp_dir, filename)
            
            print(f"    💧 Processing watermark: {filename}...")
            
            if image_path and os.path.exists(image_path):
                # FFmpeg command for Image overlay (Center-Bottom)
                # scale=X:Y can be added if image is too large, but overlay= keeps it simple
                cmd = [
                    'ffmpeg', '-y', '-i', input_path,
                    '-i', image_path,
                    '-filter_complex', 'overlay=(W-w)/2:(H-h)*0.8', # 80% down the screen (Center-Bottom)
                    '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
                    '-c:a', 'copy',
                    output_path
                ]
            else:
                # FFmpeg command for transparent text watermark (Center-Bottom)
                cmd = [
                    'ffmpeg', '-y', '-i', input_path,
                    '-vf', f"drawtext=text='{watermark_text}':fontcolor=white@0.4:fontsize=48:x=(w-text_w)/2:y=h-(h/4)",
                    '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
                    '-c:a', 'copy',
                    output_path
                ]
            
            result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            if result.returncode == 0:
                shutil.move(output_path, input_path)  # Overwrite original with watermarked version
            else:
                print(f"    ❌ Watermark failed on {filename}: {result.stderr.decode()}")
                
    if os.path.exists(temp_dir):
        os.rmdir(temp_dir)
        
    print("    🔥 Saare clips watermark ho gaye!")

if __name__ == "__main__":
    # Test run standalone
    input_test = "input_clips"
    if os.path.exists(input_test):
        apply_watermarks(input_test)
