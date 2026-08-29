"""
effects/yolo_detector.py
========================
YOLOv8 person/face detector -- drop-in replacement for Haar cascades.

Strategy:
  - Uses yolov8n.pt (official Ultralytics, COCO-trained, 6MB).
  - Detects class=0 (person) for upper-body tracking.
  - Returns the TOP HALF of each person box as the "face" region.
    This is MORE stable than Haar face detection (no flicker from
    head turns, works for side-facing speakers too).
  - Falls back to Haar on import/model error.

Returns: List of (x, y, w, h) floats -- same format as detect_faces_multi_haar.
"""

import logging
from pathlib import Path
from typing import List, Tuple
import numpy as np

log = logging.getLogger(__name__)

_yolo_model = None
_yolo_failed = False
_MODEL_PATH = Path(__file__).parent.parent / "models" / "yolov8n.pt"


def _load_yolo():
    """Lazy-load YOLOv8n model. Downloads on first run (~6MB)."""
    global _yolo_model, _yolo_failed
    if _yolo_model is not None:
        return _yolo_model
    if _yolo_failed:
        return None

    try:
        from ultralytics import YOLO

        _MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)

        if _MODEL_PATH.exists():
            _yolo_model = YOLO(str(_MODEL_PATH))
        else:
            # Auto-download from Ultralytics hub
            log.info("[YOLO] Downloading yolov8n.pt from Ultralytics hub (~6MB)...")
            _yolo_model = YOLO("yolov8n.pt")
            # Move to our models dir
            import shutil, os
            downloaded = Path("yolov8n.pt")
            if downloaded.exists():
                shutil.move(str(downloaded), str(_MODEL_PATH))
                _yolo_model = YOLO(str(_MODEL_PATH))

        # Warmup
        _yolo_model.predict(
            np.zeros((64, 64, 3), dtype=np.uint8),
            verbose=False, imgsz=64, classes=[0]
        )
        log.info("[YOLO] yolov8n loaded and warmed up (person-detection mode) ✓")
        return _yolo_model

    except Exception as e:
        log.warning(f"[YOLO] Load failed ({e}). Falling back to Haar.")
        _yolo_failed = True
        return None


def detect_faces_yolo(
    frame_bgr: np.ndarray,
    conf_threshold: float = 0.40,
    min_size: Tuple[int, int] = (40, 40),
) -> List[Tuple[float, float, float, float]]:
    """
    Detect persons with YOLOv8n, return top-50% of each box as "face region".
    Returns List of (x, y, w, h) -- identical format to detect_faces_multi_haar.

    Guardrails:
      - conf_threshold: rejects low-confidence detections
      - min_size: rejects tiny detections (mics, logos)
      - Boundary clamp: boxes are clipped to frame
      - Returns only upper body (face zone) not full body
    """
    model = _load_yolo()
    if model is None:
        return []

    try:
        h, w = frame_bgr.shape[:2]

        # Detect persons only (class 0)
        results = model.predict(
            frame_bgr, verbose=False,
            conf=conf_threshold, imgsz=640,
            classes=[0]
        )

        boxes_out = []
        if results and results[0].boxes is not None:
            for box in results[0].boxes:
                conf = float(box.conf[0])
                if conf < conf_threshold:
                    continue

                x1, y1, x2, y2 = box.xyxy[0].tolist()

                # Guardrail 1: clamp to frame
                x1 = max(0.0, x1);  y1 = max(0.0, y1)
                x2 = min(float(w), x2);  y2 = min(float(h), y2)

                bw = x2 - x1
                bh = y2 - y1

                # Guardrail 2: reject tiny boxes
                if bw < min_size[0] or bh < min_size[1]:
                    continue

                # Use only top 50% of person box as "face zone"
                # This gives a stable face-level crop region
                face_h = bh * 0.5
                boxes_out.append((x1, y1, bw, face_h))

        return boxes_out

    except Exception as e:
        log.warning(f"[YOLO] Inference error: {e}")
        return []


def is_yolo_available() -> bool:
    """Check if YOLO model is ready."""
    return _load_yolo() is not None
