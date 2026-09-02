import cv2
import bolt
from typing import Optional, Dict, Tuple, Any

class VideoContext:
    """
    ⚡ BOLT VideoContext (MVP)
    Single authoritative owner of a video stream.
    Eliminates duplicate VideoCapture() opens on the same file path.
    """
    _cache: Dict[str, "VideoContext"] = {}

    @classmethod
    def get(cls, path: str) -> "VideoContext":
        if path not in cls._cache or cls._cache[path].cap is None:
            cls._cache[path] = cls(path)
        return cls._cache[path]

    @classmethod
    def close_all(cls):
        for vc in list(cls._cache.values()):
            vc.release()
        cls._cache.clear()

    def __init__(self, path: str):
        self.path = path
        bolt.emit("video_open", resource=path, owner="Decode Detective")
        self.cap = cv2.VideoCapture(path)
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 25.0
        self.width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        self.height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        self.frame_count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

    def read(self) -> Tuple[bool, Any]:
        if self.cap is None:
            return False, None
        ok, frame = self.cap.read()
        if ok:
            bolt.emit("frame_decode")
        return ok, frame

    def seek(self, frame_idx: int):
        if self.cap:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)

    def release(self):
        if self.cap:
            self.cap.release()
            self.cap = None
            bolt.emit("video_close", resource=self.path)
        if self.path in self._cache:
            del self._cache[self.path]

# Simple module-level aliases
get_video_context = VideoContext.get
close_all_contexts = VideoContext.close_all
