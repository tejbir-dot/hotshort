from typing import List, Dict

# -------------------------------
# ATTENTION-AWARE JUMP STITCHER
# -------------------------------
def build_jump_blocks(
    segments: List[Dict],
    min_len: float = 12.0,
    max_len: float = 38.0,
    fuse_gap: float = 2.5,
):
    """
    INPUT:
      [
        {"start": 12.0, "end": 15.4, "score": 0.88},
        ...
      ]

    OUTPUT:
      [
        {
          "start": X,
          "end": Y,
          "energy": 0.82,
          "cuts": N
        }
      ]
    """

    if not segments:
        return []

    # sort by start time
    segs = sorted(segments, key=lambda s: s["start"])

    blocks = []
    cur = {
        "start": segs[0]["start"],
        "end": segs[0]["end"],
        "scores": [segs[0].get("score", 0.5)]
    }

    # -------------------------------
    # FUSE LOGIC (FAST)
    # -------------------------------
    for s in segs[1:]:
        gap = s["start"] - cur["end"]

        if gap <= fuse_gap:
            cur["end"] = max(cur["end"], s["end"])
            cur["scores"].append(s.get("score", 0.5))
        else:
            blocks.append(cur)
            cur = {
                "start": s["start"],
                "end": s["end"],
                "scores": [s.get("score", 0.5)]
            }

    blocks.append(cur)

    # -------------------------------
    # REFINEMENT BRAIN
    # -------------------------------
    refined = []

    for b in blocks:
        dur = b["end"] - b["start"]
        avg_score = sum(b["scores"]) / len(b["scores"])

        # grow weak clips a bit
        if dur < min_len:
            b["end"] = b["start"] + min_len

        # trim boring long clips
        if dur > max_len:
            b["end"] = b["start"] + max_len

        refined.append({
            "start": round(b["start"], 2),
            "end": round(b["end"], 2),
            "energy": round(avg_score, 2),
            "cuts": len(b["scores"])
        })

    return refined
