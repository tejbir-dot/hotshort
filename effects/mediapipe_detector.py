"""
effects/mediapipe_detector.py
=============================
MediaPipe Face Detection -- drop-in replacement for Haar/YOLO detectors.
Provides high-accuracy facial bounding boxes to avoid aspect ratio rejections.
Uses thread-local initialization to prevent packet timestamp mismatch crashes.
"""

import cv2
import logging
import threading
from typing import List, Tuple, Optional
import numpy as np

log = logging.getLogger(__name__)

_mp_failed = False
_thread_local = threading.local()


class FaceBox(tuple):
    """
    Subclass of tuple that behaves exactly like (x, y, w, h) for backward compatibility,
    but carries optional nose tip pixel coordinates (nose_x, nose_y) for physics.
    """
    def __new__(cls, x: int, y: int, w: int, h: int, nose_x: Optional[int] = None, nose_y: Optional[int] = None, score: Optional[float] = None):
        return super().__new__(cls, (x, y, w, h))

    def __init__(self, x: int, y: int, w: int, h: int, nose_x: Optional[int] = None, nose_y: Optional[int] = None, score: Optional[float] = None):
        self.nose_x = nose_x
        self.nose_y = nose_y
        self.score = score


def _get_detector():
    global _mp_failed
    if _mp_failed:
        return None
        
    detector = getattr(_thread_local, 'detector', None)
    if detector is None:
        try:
            import mediapipe as mp
            mp_face_detection = mp.solutions.face_detection
            
            # model_selection=1: optimized for faces within 2 meters (perfect for close-up talking heads)
            detector = mp_face_detection.FaceDetection(
                model_selection=1,
                min_detection_confidence=0.45
            )
            _thread_local.detector = detector
            log.info(f"[MEDIAPIPE] FaceDetection initialized on thread {threading.current_thread().name} ✓")
        except Exception as e:
            log.warning(f"[MEDIAPIPE] Load failed: {e}")
            _mp_failed = True
            detector = None
    return detector


def detect_faces_mediapipe(
    frame_bgr: np.ndarray,
    conf_threshold: float = 0.45,
    min_size: Tuple[int, int] = (40, 40),
) -> List[FaceBox]:
    """
    Detect faces using MediaPipe Face Detection.
    Returns list of FaceBox objects containing (x, y, w, h) absolute integer pixel coordinates,
    plus absolute nose tip coordinates.
    """
    detector = _get_detector()
    if detector is None:
        return []

    try:
        h, w = frame_bgr.shape[:2]
        
        # MediaPipe expects RGB images
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        results = detector.process(frame_rgb)
        
        boxes_out = []
        if results.detections:
            for detection in results.detections:
                # 1. Score threshold filter
                score = detection.score[0] if detection.score else 0.0
                if score < conf_threshold:
                    continue
                
                bbox = detection.location_data.relative_bounding_box
                
                # 2. Convert normalized relative coordinates to absolute pixels (int)
                rx = int(round(bbox.xmin * w))
                ry = int(round(bbox.ymin * h))
                rw = int(round(bbox.width * w))
                rh = int(round(bbox.height * h))
                
                # Clamp coordinates to frame boundaries
                x1 = max(0, rx)
                y1 = max(0, ry)
                x2 = min(w, rx + rw)
                y2 = min(h, ry + rh)
                
                bw = x2 - x1
                bh = y2 - y1
                
                # Filter out tiny detections
                if bw < min_size[0] or bh < min_size[1]:
                    continue
                
                # 3. Extract Nose Tip Keypoint (Index 2 in MediaPipe Face Detection)
                nose_x = None
                nose_y = None
                if detection.location_data.relative_keypoints:
                    keypoints = detection.location_data.relative_keypoints
                    if len(keypoints) > 2:
                        nose_kp = keypoints[2]
                        # Convert normalized nose coordinate to absolute pixels
                        nose_x = int(round(nose_kp.x * w))
                        nose_y = int(round(nose_kp.y * h))
                        # Clamp nose coordinates to frame boundaries
                        nose_x = max(0, min(w - 1, nose_x))
                        nose_y = max(0, min(h - 1, nose_y))
                
                boxes_out.append(FaceBox(x1, y1, bw, bh, nose_x, nose_y, score))
                
        return boxes_out
    except Exception as e:
        log.warning(f"[MEDIAPIPE] Inference error: {e}")
        return []


def is_mediapipe_available() -> bool:
    return _get_detector() is not None
