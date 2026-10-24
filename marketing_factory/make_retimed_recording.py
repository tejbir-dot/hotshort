import os
import subprocess

def create_retimed_yt_search():
    engine_dir = r"c:\Users\n\Documents\hotshort\marketing_factory\remotion_engine"
    raw_input = os.path.join(engine_dir, "public", "yt_search.mp4")
    output_mp4 = os.path.join(engine_dir, "public", "yt_search_synced.mp4")
    
    # 110 frames total @ 30fps = 3.667s
    # Segment 1: Typing 'ishowspeed' (from 5.3s to 7.3s, 2.0s -> 0.70s = 21 frames)
    # Segment 2: Search results & scrolling (from 9.4s to 12.4s, 3.0s -> 1.30s = 39 frames) -> ends at frame 60 (2.00s)
    # At frame 55 (t=1.83s), the video thumbnail "BUYING THE NEW iPHONE DUO!" is right in center & tapped!
    # Segment 3: Watch page playing (from 14.3s to 16.7s, 2.4s -> 1.67s = 50 frames) -> frames 60 to 110
    # Total duration = 0.70s + 1.30s + 1.667s = 3.667s (exactly 110 frames @ 30fps)
    
    filter_complex = (
        "[0:v]trim=start=5.3:end=7.3,setpts=PTS-STARTPTS,setpts=PTS/2.857[v1];"
        "[0:v]trim=start=9.4:end=12.4,setpts=PTS-STARTPTS,setpts=PTS/2.307[v2];"
        "[0:v]trim=start=14.3:end=16.8,setpts=PTS-STARTPTS,setpts=PTS/1.50[v3];"
        "[v1][v2][v3]concat=n=3:v=1:a=0[vconcat];"
        "[vconcat]fps=30,scale=392:852,format=yuv420p[vout]"
    )
    
    cmd = [
        "ffmpeg", "-y",
        "-i", raw_input,
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-c:v", "libx264", "-crf", "18", "-preset", "slow",
        output_mp4
    ]
    
    print("Running FFmpeg to create seamless 30fps video...")
    subprocess.run(cmd, check=True)
    print(f"Created: {output_mp4}")

if __name__ == "__main__":
    create_retimed_yt_search()
