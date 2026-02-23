import cv2
import numpy as np
from typing import Dict

# --------------------------------
# AI CAMERA ZONE DETECTOR
# --------------------------------
def detect_camera_zone(
    video_path: str,
    zones: int = 3,
    samples: int = 40,
    resize=(144, 256),
    dominance_ratio: float = 1.35
) -> Dict:
    """
    Detects dominant visual zone (speaker focus)

    OUTPUT:
    {
        "zone": "left | center | right",
        "confidence": 0.0–1.0,
        "scores": [..]
    }
    """

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return {"zone": "center", "confidence": 0.0, "scores": []}

    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if total == 0:
        cap.release()
        return {"zone": "center", "confidence": 0.0, "scores": []}

    step = max(1, total // samples)
    prev = None
    scores = np.zeros(zones)

    for i in range(0, total, step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ok, frame = cap.read()
        if not ok:
            break

        gy = cv2.cvtColor(cv2.resize(frame, resize), cv2.COLOR_BGR2GRAY)

        if prev is not None:
            diff = cv2.absdiff(gy, prev)
            h, w = diff.shape
            sw = w // zones

            for z in range(zones):
                scores[z] += diff[:, z*sw:(z+1)*sw].mean()

        prev = gy

    cap.release()

    total_energy = scores.sum()
    if total_energy <= 0:
        return {"zone": "center", "confidence": 0.0, "scores": scores.tolist()}

    idx = int(np.argmax(scores))
    sorted_scores = np.sort(scores)

    # dominance check (avoid random switches)
    dominant = sorted_scores[-1] / (sorted_scores[-2] + 1e-6)

    if dominant < dominance_ratio:
        return {
            "zone": "center",
            "confidence": round(dominant / dominance_ratio, 2),
            "scores": scores.tolist()
        }

    zone = "center"
    if idx == 0:
        zone = "left"
    elif idx == zones - 1:
        zone = "right"

    confidence = min(1.0, dominant / 2.0)

    return {
        "zone": zone,
        "confidence": round(confidence, 2),
        "scores": scores.tolist()
    }
