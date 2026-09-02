import cv2

class FaceTracker:
    """
    Wraps a single lightweight OpenCV tracker for one face slot (left or
    right). Initialized once from a Haar-detected bbox, then updated every
    frame cheaply. Falls back to signaling "lost" so the caller can trigger
    a fresh Haar re-detect.
    """
    def __init__(self, slot_name: str, confidence_floor: int = 3):
        self.slot_name = slot_name
        self.tracker = None
        self.initialized = False
        self.consecutive_low_confidence = 0
        self.confidence_floor = confidence_floor  # frames of failure before declaring "lost"
        self.last_bbox = None
        self.last_center_x = None

    def init(self, frame, bbox_xywh):
        """bbox_xywh: (x, y, w, h) in pixel coords, from Haar detection."""
        try:
            self.tracker = cv2.legacy.TrackerCSRT_create()
        except AttributeError:
            self.tracker = cv2.TrackerCSRT_create()  # older/newer API fallback
        bbox_int = tuple([int(v) for v in bbox_xywh])
        self.tracker.init(frame, bbox_int)
        self.initialized = True
        self.consecutive_low_confidence = 0
        self.last_bbox = bbox_int
        self.last_center_x = bbox_int[0] + bbox_int[2] / 2.0
        print(f"[FACE_TRACK] slot={self.slot_name} initialized bbox={bbox_int}")

    def update(self, frame):
        """Returns (success: bool, center_x: float or None, bbox: tuple or None)."""
        if not self.initialized:
            return False, None, None
        ok, bbox = self.tracker.update(frame)
        if ok:
            self.consecutive_low_confidence = 0
            x, y, w, h = bbox
            center_x = x + w / 2.0
            self.last_bbox = bbox
            self.last_center_x = center_x
            return True, center_x, bbox
        else:
            self.consecutive_low_confidence += 1
            return False, None, None

    def is_lost(self):
        # Uninitialized tracker must be treated as lost so the engine keeps
        # calling MediaPipe/Haar until it can anchor a real face bbox.
        # Without this, consecutive_low_confidence=0 on an uninitialized tracker
        # fools the render loop into thinking the camera is coasting, permanently
        # disabling redetection for the entire clip.
        return not self.initialized or self.consecutive_low_confidence >= self.confidence_floor


class SmoothedPosition:
    def __init__(self, alpha=0.3):
        self.alpha = alpha  # higher = more responsive, lower = smoother
        self.value = None

    def update(self, new_value):
        if new_value is None:
            return self.value  # hold last known position
        if self.value is None:
            self.value = new_value
        else:
            self.value = self.alpha * new_value + (1 - self.alpha) * self.value
        return self.value
