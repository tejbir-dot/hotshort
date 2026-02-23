import subprocess
from typing import List, Tuple

# --------------------------------
# FAST SILENCE DETECTOR (FFMPEG)
# --------------------------------
import subprocess
from typing import List, Tuple

def detect_silence_spans(
    video_path: str,
    noise_db: float = -38,
    min_len: float = 0.9,
    max_len: float = 2.5,
    edge_guard: float = 1.5,
    max_remove_ratio: float = 0.3
) -> List[Tuple[float, float]]:
    """
    Smart silence detector for SHORTS
    - ignores silence near edges
    - caps total silence removal
    """

    # get duration
    dur_cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path
    ]
    d = subprocess.run(dur_cmd, stdout=subprocess.PIPE, text=True)
    try:
        total_dur = float(d.stdout.strip())
    except:
        return []

    # very short clips → no silence removal
    if total_dur < 18:
        return []

    cmd = [
        "ffmpeg",
        "-i", video_path,
        "-af", f"silencedetect=noise={noise_db}dB:d={min_len}",
        "-f", "null", "-"
    ]

    p = subprocess.run(cmd, stderr=subprocess.PIPE, text=True)

    silences = []
    start = None
    removed = 0.0

    for line in p.stderr.splitlines():
        if "silence_start" in line:
            start = float(line.split("silence_start:")[1])
        elif "silence_end" in line and start is not None:
            end = float(line.split("silence_end:")[1].split("|")[0])
            dur = end - start

            # guard edges
            if start < edge_guard or end > (total_dur - edge_guard):
                start = None
                continue

            if min_len <= dur <= max_len:
                # cap total removal
                if removed + dur <= total_dur * max_remove_ratio:
                    silences.append((round(start, 2), round(end, 2)))
                    removed += dur

            start = None

    return silences

def build_silence_skip_filter(silences):
    if not silences:
        return ""

    expr = " + ".join(
        [f"between(t,{s},{e})" for s, e in silences]
    )

    # keep frames NOT in silence
    return f"select='not({expr})',setpts=N/FRAME_RATE/TB"
def extend_until_sentence_complete(
    clip_start: float,
    clip_end: float,
    transcript: list,
    max_extend: float = 6.0
):
    """
    Extends clip end if transcript sentence is cut mid-thought
    """

    for seg in transcript:
        ts, te = seg["start"], seg["end"]
        text = seg.get("text", "").strip()

        if ts < clip_end < te:
            # sentence cut in middle
            extra = min(te - clip_end, max_extend)
            return round(clip_end + extra, 2)

    return clip_end
