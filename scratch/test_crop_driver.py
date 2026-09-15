import json
import os
import cv2
from effects.world_class_editor import ClipEditor
from utils.video_formats import VideoFormat
from utils.config import ClipEditConfig
from collections import namedtuple

class MockConfig:
    enable_hook_zoom = False

class MockFormat:
    def __init__(self):
        self.director_mode = 2 # PODCAST
        self.face_count_hint = 2

# We need a mock face cache that simulates a detection failure
mock_face_cache = {
    0.0: [], # Simulate empty face cache
    0.5: [],
    1.0: [],
}

class MockFaceCache:
    def __init__(self):
        self.cache = mock_face_cache
        
    def items(self):
        return self.cache.items()
        
    def get_clip_cache(self, clip):
        return self.cache

if __name__ == "__main__":
    import os
    # Find a video
    video_path = "The One-Person Startup Era Has Officially Begun [rsSUIvAkjvk].webm"
    if not os.path.exists(video_path):
        print(f"Video {video_path} not found.")
        video_path = "test.mp4"
    
    fmt = MockFormat()
    from effects.director_strategy import DirectorMode
    fmt.director_mode = DirectorMode.PODCAST
    
    cfg = ClipEditConfig()
    cfg.enable_hook_zoom = False
    
    cache = MockFaceCache()
    from effects.world_class_editor import ClipEditor
    editor = ClipEditor()
    
    print("Testing _get_crop_expression...")
    res = editor._get_crop_expression(fmt, [], cfg, clip_path=video_path, face_cache=cache)
    print("Result:", res)

