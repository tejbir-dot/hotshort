import cv2
import numpy as np
from typing import Optional, Tuple

CASCADE = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
)

# -------------------------------
# FAST FACE SAMPLER (GENIUS)
# -------------------------------
def detect_face_box(
    video_path: str,
    start: float,
    end: float,
    samples: int = 8
) -> Optional[Tuple[int, int, int, int]]:

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None

    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    frames = [int((start + i*(end-start)/samples) * fps) for i in range(samples)]

    boxes = []

    for f in frames:
        cap.set(cv2.CAP_PROP_POS_FRAMES, f)
        ok, frame = cap.read()
        if not ok:
            continue

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = CASCADE.detectMultiScale(gray, 1.15, 4)

        if len(faces):
            # biggest face = speaker
            boxes.append(max(faces, key=lambda b: b[2]*b[3]))

    cap.release()
    if not boxes:
        return None

    return tuple(np.median(np.array(boxes), axis=0).astype(int))


# -------------------------------
# CROP PLANNER (PURE BRAIN)
# -------------------------------
def build_face_crop(
    video_path: str,
    start: float,
    end: float,
    out_w: int = 1080,
    out_h: int = 1920
) -> str:

    face = detect_face_box(video_path, start, end)

    if not face:
        return (
            "scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920"
        )

    fx, fy, fw, fh = face

    crop_w = int(fw * 1.4)
    crop_h = int(crop_w * out_h / out_w)

    cx = max(0, fx + fw//2 - crop_w//2)
    cy = max(0, fy + fh//2 - crop_h//2)

    return (
        f"crop={crop_w}:{crop_h}:{cx}:{cy},"
        "scale=1080:1920"
    )
