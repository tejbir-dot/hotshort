from pathlib import Path
import subprocess

root = Path(r"c:/Users/n/Documents/hotshort")
mp4s = list(root.rglob('*.mp4'))
print(f'Found {len(mp4s)} mp4 files')


def probe_moviepy(p):
    try:
        from moviepy.editor import VideoFileClip
        clip = VideoFileClip(str(p))
        d = clip.duration
        clip.reader.close()
        if clip.audio:
            try:
                clip.audio.reader.close_proc()
            except Exception:
                pass
        return d
    except Exception:
        return None


def probe_ffprobe(p):
    try:
        cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', str(p)]
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().strip()
        return float(out)
    except Exception:
        return None

candidates = []
for p in mp4s:
    d = probe_moviepy(p)
    if d is None:
        d = probe_ffprobe(p)
    if d is None:
        continue
    if 480 <= d <= 720:
        candidates.append((str(p), d))

print('Total candidates (8-12min):', len(candidates))
for f, d in candidates:
    print(f, round(d))
