import os
import sys
import logging
from unittest.mock import patch

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
os.environ["HS_ENABLE_AV1_NVDEC"] = "1"

from effects.world_class_editor import ClipEditor, _hwaccel_decode_args

# Monkeypatch to force AV1 flow
import effects.world_class_editor as wce
wce._input_video_codec = lambda path: "av1"
wce._ffmpeg_decoder_available = lambda codec: True

# Mock the fallback command so it doesn't actually run a real encode and hang
original_without = wce.ClipEditor._without_cuda_decode

def mock_without(cmd):
    # just return a harmless command like ffmpeg -version
    return ["ffmpeg", "-version"]

wce.ClipEditor._without_cuda_decode = staticmethod(mock_without)

editor = ClipEditor(work_dir="temp_test_dir")

for i in range(3):
    print(f"\n=== Processing Clip {i+1} ===")
    args = _hwaccel_decode_args("dummy.mp4")
    print("Dec args:", args)
    
    # Construct a command that will fail with the exact chroma format error
    # We can simulate this by running a python script that prints to stderr and exits with 1
    
    if args:
        cmd = [sys.executable, "-c", "import sys; sys.stderr.write('Codec av1_cuvid is not supported with this chroma format\\n'); sys.exit(1)"]
        # Add the expected flags so _uses_cuda_decode returns True
        cmd.extend(args)
    else:
        cmd = [sys.executable, "-c", "print('CPU decode OK')"]
        
    try:
        editor._run(cmd, timeout_s=5)
    except Exception as e:
        print("Exception:", e)
