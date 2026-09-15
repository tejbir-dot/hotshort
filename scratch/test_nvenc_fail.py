import subprocess
cmd = [
    'ffmpeg', '-y', '-nostdin', '-f', 'lavfi', '-i', 'color=c=black:s=1080x1920:d=1',
    '-c:v', 'h264_nvenc', '-preset', 'p1', '-tune', 'hq', '-profile:v', 'high',
    '-rc', 'vbr', '-cq', '23', '-b:v', '3M', '-maxrate', '8000k', '-bufsize', '16000k',
    '-pix_fmt', 'yuv420p', '-f', 'null', '-'
]
res = subprocess.run(cmd, capture_output=True, text=True)
print("RC:", res.returncode)
print("STDOUT:", res.stdout)
print("STDERR:", res.stderr)
