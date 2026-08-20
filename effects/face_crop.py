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
    samples: int = 15  # Increased samples for much higher tracking accuracy
) -> Optional[Tuple[int, int, int, int]]:

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None

    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    
    # Ensure we don't over-sample short clips
    duration = end - start
    if duration < 5.0:
        samples = 8
        
    frames = [int((start + i*(duration)/samples) * fps) for i in range(samples)]

    boxes = []

    for f in frames:
        cap.set(cv2.CAP_PROP_POS_FRAMES, f)
        ok, frame = cap.read()
        if not ok:
            continue

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        # Reduced scaleFactor to 1.05 for high precision (finds faces even when tilted/distant)
        faces = CASCADE.detectMultiScale(gray, scaleFactor=1.05, minNeighbors=5, minSize=(30, 30))

        if len(faces):
            # biggest face = speaker
            boxes.append(max(faces, key=lambda b: b[2]*b[3]))

    cap.release()
    if not boxes:
        return None

    # Use median to ignore outlier false-positives
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

    # --- CLIENT-READY GENIUS CROP LOGIC ---
    # Widen crop to 2.4x face width (was 1.4x). This captures shoulders, 
    # hand gestures, and gives room for the person to move left/right 
    # without instantly leaving the frame. High ROI!
    crop_w = int(fw * 2.4)
    crop_h = int(crop_w * out_h / out_w)

    # X-axis: Center the wide box around the face
    cx = max(0, fx + fw//2 - crop_w//2)
    
    # Y-axis: Rule of thirds. Do NOT center the face perfectly in the middle.
    # Pull the crop higher up (0.35 instead of 0.5) so the top of the head
    # isn't cut off and there is massive room at the bottom for subtitles!
    cy = max(0, fy + fh//2 - int(crop_h * 0.35))

    return (
        f"crop={crop_w}:{crop_h}:{cx}:{cy},"
        "scale=1080:1920"
    )
