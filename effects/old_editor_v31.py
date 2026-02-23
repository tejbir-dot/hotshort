import os
import subprocess
import tempfile
import textwrap

def editor_v31_pro(video_path: str, moment: dict, out_path: str):
    """
    Ultra-stable editor:
      - vertical crop 1080x1920
      - zoom punch-in (slow)
      - saturation/contrast lift
      - ASS subtitles
      - no NVENC dependency
      - no special filters that break on Windows
    """

    start = float(moment.get("start", 0))
    end   = float(moment.get("end", start + 15))
    text  = moment.get("text", "")

    if end <= start:
        end = start + 2.0

    # -----------------
    # SAVE ASS CAPTIONS
    # -----------------
    ass_content = textwrap.dedent(f"""
        [Script Info]
        ScriptType: v4.00+
        PlayResX: 1080
        PlayResY: 1920

        [V4+ Styles]
        Format: Name,Fontname,Fontsize,PrimaryColour,OutlineColour,BackColour,Bold,Italic,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
        Style: Caption,Arial,52,&H00FFFFFF,&H00111111,&H00000000,1,0,1,5,0,2,20,20,40,0

        [Events]
        Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
        Dialogue: 0,0:00:01.00,0:00:10.00,Caption,,20,20,40,,{text.replace(",", " ")}
    """)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".ass") as tf:
        capfile = tf.name
        tf.write(ass_content.encode("utf-8"))

    # -----------------
    # FFMPEG COMMAND
    # -----------------
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-ss", str(start),
        "-to", str(end),
        "-vf",
        (
            "scale=1080:1920,"
            "eq=contrast=1.18:saturation=1.23,"
            "zoompan=z='1.03':d=1,"
            f"subtitles='{capfile}'"
        ),
        "-preset", "veryfast",
        "-c:v", "libx264",
        "-c:a", "aac",
        out_path
    ]

    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if proc.returncode != 0:
            print("\n[EDITOR V31_PRO ERROR]\n", proc.stderr)
            return False
        return True
    except Exception as e:
        print("[EDITOR V31_PRO EXCEPTION]", e)
        return False
