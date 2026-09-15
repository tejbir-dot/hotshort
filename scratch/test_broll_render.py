import os
import sys
import subprocess
import logging

# Add project root to sys.path so we can import effects
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from effects.broll_engine import fetch_broll_asset

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def test_broll_render():
    os.makedirs(os.path.abspath(os.path.join(os.path.dirname(__file__))), exist_ok=True)
    broll_image = os.path.abspath(os.path.join(os.path.dirname(__file__), "test_broll.jpg"))
    output_video = os.path.abspath(os.path.join(os.path.dirname(__file__), "broll_test_output.mp4"))
    
    # 1. Fetch Pollinations Image
    logging.info("Fetching B-Roll from Pollinations...")
    downloaded_path = fetch_broll_asset("luxury sports car parked outside mansion", broll_image, width=1080, height=1920)
    if not downloaded_path:
        logging.error("Failed to fetch B-Roll image!")
        return
        
    # 2. Render with FFmpeg (Ken Burns Zoompan)
    # We will generate a 5-second video from the image
    # zoompan=z='min(zoom+0.0015,1.5)':d=150 (zoom in slowly over 150 frames = 5s @ 30fps)
    logging.info("Rendering B-Roll video with Zoompan...")
    
    # To fix FFmpeg zoompan jitter, we scale the image to 4x (4320x7680) BEFORE zoompan.
    # The zoompan then crops this massive image and outputs 1080x1920.
    # Because the crop window is huge, FFmpeg's integer-rounding errors become microscopic, resulting in butter-smooth zoom.
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", downloaded_path,
        "-vf", "scale=4320:7680,zoompan=z='min(zoom+0.0015,1.5)':d=150:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=30",
        "-c:v", "libx264",
        "-t", "5",
        "-pix_fmt", "yuv420p",
        "-fpsmax", "30",
        output_video
    ]
    
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        logging.info(f"Success! Test video generated at: {output_video}")
    except subprocess.CalledProcessError as e:
        logging.error(f"FFmpeg failed!\n{e.stderr.decode('utf-8', errors='ignore')}")

if __name__ == "__main__":
    test_broll_render()
