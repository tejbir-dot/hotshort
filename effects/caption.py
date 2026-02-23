import re
from typing import List, Dict

# --------------------------------
# TEXT CLEANER
# --------------------------------
def clean_text(text: str) -> str:
    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    return text


# --------------------------------
# PUNCH WORD EXTRACTOR
# --------------------------------
def extract_punch_words(text: str) -> List[str]:
    """
    Finds emotionally strong words
    """
    keywords = [
        "never", "always", "truth", "secret", "money", "power",
        "fear", "love", "hate", "change", "break", "control",
        "win", "lose", "real", "fake", "god", "mind", "life",
        "death", "time", "future", "free"
    ]

    words = text.lower().split()
    return [w for w in words if w in keywords]


# --------------------------------
# CAPTION BUILDER (GENIUS)
# --------------------------------
def build_captions(
    transcript: List[Dict],
    max_words: int = 4
):
    """
    INPUT transcript:
      [
        {"start": 12.2, "end": 13.4, "text": "..."},
        ...
      ]

    OUTPUT captions:
      [
        {
          "start": X,
          "end": Y,
          "text": "POWER MOVE"
        }
      ]
    """

    captions = []

    for seg in transcript:
        raw = clean_text(seg.get("text", ""))
        if not raw:
            continue

        words = raw.split()

        # Short punch line
        if len(words) <= max_words:
            caption = raw.upper()
        else:
            punch = extract_punch_words(raw)
            if punch:
                caption = " ".join(punch[:max_words]).upper()
            else:
                caption = " ".join(words[:max_words]).upper()

        captions.append({
            "start": round(seg["start"], 2),
            "end": round(seg["end"], 2),
            "text": caption
        })

    return captions
# effects/caption.py

def captions_to_srt(captions):
    """
    captions = list of {start, end, text}
    returns SRT formatted string
    """
    lines = []
    for i, c in enumerate(captions, start=1):
        start = _format_ts(c["start"])
        end = _format_ts(c["end"])
        text = c["text"].strip()

        lines.append(f"{i}")
        lines.append(f"{start} --> {end}")
        lines.append(text)
        lines.append("")  # blank line

    return "\n".join(lines)


def _format_ts(t):
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int((t - int(t)) * 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"
