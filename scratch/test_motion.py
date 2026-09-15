import cv2
import os
from effects.world_class_editor import ClipEditor
from effects.format_analyzer import VideoFormat
from effects.world_class_editor import ClipEditConfig
from effects.director_strategy import DirectorMode

class MockFormat:
    def __init__(self):
        self.director_mode = DirectorMode.PODCAST
        self.face_count_hint = 2

# We need a face cache that simulates two faces being detected
# We will just put one cluster spanning 0 to 1000 frames
mock_faces = [
    {
        "_cluster_id": "c1",
        "_cluster_start": 0,
        "_cluster_end": 10000,
        "x": 100, "y": 100, "w": 200, "h": 200 # left face
    },
    {
        "_cluster_id": "c1",
        "_cluster_start": 0,
        "_cluster_end": 10000,
        "x": 800, "y": 100, "w": 200, "h": 200 # right face
    }
]

mock_face_cache = {
    0.0: mock_faces
}

class MockFaceCache:
    def items(self):
        return mock_face_cache.items()

if __name__ == "__main__":
    video_path = "test.mp4" # Or any video that has a few seconds
    if not os.path.exists(video_path):
        print("Fallback to test_slice.mp4")
        video_path = "test_slice.mp4"
        
    fmt = MockFormat()
    cfg = ClipEditConfig()
    cfg.enable_hook_zoom = False
    
    cache = MockFaceCache()
    editor = ClipEditor(work_dir=".")
    
    print("Testing _get_crop_expression for MOTION_DEBUG...")
    res = editor._get_crop_expression(fmt, [], cfg, clip_path=video_path, face_cache=cache)
    print("Done")
