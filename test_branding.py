import os
import subprocess

# create a dummy video 1080x1920
subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=1080x1920:d=2", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo:d=2", "-c:v", "libx264", "-c:a", "aac", "dummy_main.mp4"])
# create dummy outro
subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=blue:s=1080x1920:d=1", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo:d=1", "-c:v", "libx264", "-c:a", "aac", "dummy_outro.mp4"])
# create dummy watermark
subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=red:s=180x180:d=1", "-vframes", "1", "dummy_logo.png"])

filter_complex = (
    "[0:v]split=2[blur][vid];"
    "[blur]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=40[bg];"
    "[vid]scale=1080:1920:force_original_aspect_ratio=decrease[fg];"
    "[bg][fg]overlay=(W-w)/2:(H-h)/2[merged];"
    "[1:v]scale=180:-1,format=rgba,colorchannelmixer=aa=0.8[wm];"
    "[merged][wm]overlay=W-w-50:H-h-250,format=yuv420p,fps=30[main_v];"
    "[2:v]scale=1080:1920:force_original_aspect_ratio=decrease,"
    "pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,format=yuv420p[outro_v];"
    "[0:a]aresample=44100,aformat=channel_layouts=stereo[main_a_res];"
    "[2:a]aresample=44100,aformat=channel_layouts=stereo[outro_a_res];"
    "[main_v][main_a_res][outro_v][outro_a_res]concat=n=2:v=1:a=1[v][a]"
)

cmd = [
    "ffmpeg", "-y",
    "-hwaccel", "auto",
    "-i", "dummy_main.mp4",
    "-i", "dummy_logo.png",
    "-i", "dummy_outro.mp4",
    "-filter_complex", filter_complex,
    "-map", "[v]", "-map", "[a]",
    "-c:v", "h264_nvenc",
    "-preset", "p4",
    "-b:v", "5M",
    "-c:a", "aac",
    "-b:a", "128k",
    "-movflags", "+faststart",
    "dummy_branded.mp4"
]

res = subprocess.run(cmd, capture_output=True, text=True)
print("Return code:", res.returncode)
if res.returncode != 0:
    print(res.stderr[-1000:])
