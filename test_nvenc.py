import os
import subprocess
def _nvenc_available() -> bool:
    if not hasattr(_nvenc_available, "_cached"):
        try:
            r = subprocess.run(
                ["ffmpeg", "-hide_banner", "-f", "lavfi", "-i",
                 "nullsrc=s=64x64:d=0.1", "-c:v", "h264_nvenc",
                 "-f", "null", "-"],
                capture_output=True, timeout=10,
            )
            combined = (r.stdout + r.stderr).decode("utf-8", errors="replace")
            _nvenc_available._cached = (
                r.returncode == 0
                or "h264_nvenc" in combined.lower()
            )
            print(f"returncode: {r.returncode}")
            print(f"combined: {combined}")
        except Exception as e:
            print(f"Exception: {e}")
            _nvenc_available._cached = False
    return _nvenc_available._cached

print("NVENC available:", _nvenc_available())
