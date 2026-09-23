import os
import subprocess
import shutil
import sys

# Windows UTF-8 fix — emoji characters cause crash on cp1252 terminal
if sys.platform == 'win32':
    import io
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

def apply_watermarks(input_dir, watermark_text="@DoubleCoverageClips", image_path=None):
    """
    Applies watermark to all .mp4 files in input_dir.
    Creates a temp output directory, processes, and then replaces the original files.
    Skips test files (*_wm_test.mp4) automatically.
    """
    temp_dir = os.path.join(input_dir, "temp_watermarked")
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)

    for filename in os.listdir(input_dir):
        # Skip test files and already-in-temp files
        if not filename.endswith(".mp4") or "_wm_test" in filename:
            continue

        input_path = os.path.join(input_dir, filename)
        output_path = os.path.join(temp_dir, filename)

        print(f"    [WM] Processing: {filename}...")

        if image_path and os.path.exists(image_path):
            # FFmpeg: image overlay (Center-Bottom at 80% height)
            cmd = [
                'ffmpeg', '-y',
                '-i', input_path,
                '-i', image_path,
                '-filter_complex', 'overlay=(W-w)/2:(H-h)*0.8',
                '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
                '-c:a', 'copy',
                output_path
            ]
        else:
            # FFmpeg: text watermark fallback (semi-transparent, center-bottom)
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
            print(f"    [WM] OK: {filename}")
        else:
            err = result.stderr.decode(errors='replace')[-500:]
            print(f"    [WM] FAILED on {filename}: {err}")

    # Clean up temp dir (should be empty if all succeeded)
    try:
        os.rmdir(temp_dir)
    except OSError:
        pass  # not empty = some files failed, leave for debug

    print("    [WM] Done! All clips processed.")

if __name__ == "__main__":
    # Standalone test — apply to Output/Double_Coverage_Podcast clips
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", help="Folder containing .mp4 files")
    parser.add_argument("--image", help="Path to watermark image", default=None)
    args = parser.parse_args()
    apply_watermarks(args.folder, image_path=args.image)
