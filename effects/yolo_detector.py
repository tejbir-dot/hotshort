"""
effects/yolo_detector.py
========================
YOLOv8-face detector -- drop-in replacement for Haar cascades.
Uses yolov8n-face.pt (6MB nano model). Falls back gracefully on import error.

Returns: List of (x, y, w, h) floats -- same format as detect_faces_multi_haar.
"""

import logging
import os
from pathlib import Path
from typing import List, Tuple, Optional
import numpy as np

log = logging.getLogger(__name__)

_yolo_model = None
_yolo_failed = False
_MODEL_NAME = "yolov8n-face.pt"

# Cache model in project/models/ dir
_MODEL_PATH = Path(__file__).parent.parent / "models" / _MODEL_NAME


def _load_yolo():
    """Lazy-load YOLOv8-face model. Downloads on first run (~6MB)."""
    global _yolo_model, _yolo_failed
    if _yolo_model is not None:
        return _yolo_model
    if _yolo_failed:
        return None

    try:
        from ultralytics import YOLO

        _MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)

        if not _MODEL_PATH.exists():
            log.info(f"[YOLO] Downloading {_MODEL_NAME} -> {_MODEL_PATH} ...")
            import urllib.request
            url = f"https://github.com/akanametov/yolov8-face/releases/download/v0.0.0/{_MODEL_NAME}"
            urllib.request.urlretrieve(url, _MODEL_PATH)
            log.info(f"[YOLO] Download complete ({_MODEL_PATH.stat().st_size // 1024}KB)")

        _yolo_model = YOLO(str(_MODEL_PATH))
        # Warmup so first real call is instant
        _yolo_model.predict(np.zeros((64, 64, 3), dtype=np.uint8), verbose=False, imgsz=64)
        log.info("[YOLO] yolov8n-face loaded and warmed up ✓")
        return _yolo_model

    except Exception as e:
        log.warning(f"[YOLO] Load failed ({e}). Falling back to Haar.")
        _yolo_failed = True
        return None


def detect_faces_yolo(
    frame_bgr: np.ndarray,
    conf_threshold: float = 0.45,
    min_size: Tuple[int, int] = (40, 40),
) -> List[Tuple[float, float, float, float]]:
    """
    Detect faces with YOLOv8-face.
    Returns List of (x, y, w, h) -- identical format to detect_faces_multi_haar.

    Guardrails:
      - conf_threshold: rejects low-confidence detections (false positives)
      - min_size: rejects tiny detections (mics, logos)
      - Boundary clamp: boxes outside frame are clipped
    """
    model = _load_yolo()
    if model is None:
        return []

    try:
        h, w = frame_bgr.shape[:2]
        results = model.predict(frame_bgr, verbose=False, conf=conf_threshold, imgsz=640)

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

                boxes_out.append((x1, y1, bw, bh))

        return boxes_out

    except Exception as e:
        log.warning(f"[YOLO] Inference error: {e}")
        return []


def is_yolo_available() -> bool:
    """Check if YOLO model is ready."""
    return _load_yolo() is not None
