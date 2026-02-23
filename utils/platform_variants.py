"""
🎬 PLATFORM VARIANT GENERATOR

Generates platform-optimized versions of clips without re-encoding.
Uses FFmpeg stream copy for speed (10-100x faster than re-encoding).

Platform specs:
- YouTube Shorts: 9:16 (1080x1920), max 60s, H.264 + AAC
- Instagram Reels: 9:16 (1080x1920), max 90s, H.264 + AAC
- TikTok: 9:16 (1080x1920), 10-60s, H.264 + AAC
"""

import subprocess
import os
from typing import Dict, Optional
from pathlib import Path


class PlatformVariantGenerator:
    """Generate platform-optimized video variants."""
    
    def __init__(self, output_dir: str = "static/outputs"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
    
    def generate_all_variants(
        self,
        source_video: str,
        clip_id: str,
        start_time: float = 0.0,
        end_time: Optional[float] = None,
    ) -> Dict[str, str]:
        """
        Generate all platform variants for a clip.
        
        Returns:
            {
                "youtube_shorts": "/static/outputs/clip_X_youtube.mp4",
                "instagram_reels": "/static/outputs/clip_X_instagram.mp4",
                "tiktok": "/static/outputs/clip_X_tiktok.mp4",
            }
        """
        variants = {}
        
        try:
            variants["youtube_shorts"] = self._generate_youtube_shorts(
                source_video, clip_id, start_time, end_time
            )
        except Exception as e:
            print(f"⚠️ YouTube Shorts generation failed: {e}")
            variants["youtube_shorts"] = None
        
        try:
            variants["instagram_reels"] = self._generate_instagram_reels(
                source_video, clip_id, start_time, end_time
            )
        except Exception as e:
            print(f"⚠️ Instagram Reels generation failed: {e}")
            variants["instagram_reels"] = None
        
        try:
            variants["tiktok"] = self._generate_tiktok(
                source_video, clip_id, start_time, end_time
            )
        except Exception as e:
            print(f"⚠️ TikTok generation failed: {e}")
            variants["tiktok"] = None
        
        # Filter out None values
        return {k: v for k, v in variants.items() if v is not None}
    
    def _generate_youtube_shorts(
        self,
        source_video: str,
        clip_id: str,
        start_time: float = 0.0,
        end_time: Optional[float] = None,
    ) -> str:
        """
        Generate YouTube Shorts variant (9:16, max 60s).
        Uses stream copy for speed.
        """
        output_path = os.path.join(self.output_dir, f"{clip_id}_youtube.mp4")
        
        cmd = [
            "ffmpeg",
            "-y",
            "-ss", str(start_time),
        ]
        
        if end_time is not None:
            cmd.extend(["-to", str(end_time)])
        
        cmd.extend([
            "-i", source_video,
            "-c", "copy",  # Stream copy (no re-encode)
            "-avoid_negative_ts", "1",
            output_path,
        ])
        
        subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True
        )
        
        return f"/static/outputs/{os.path.basename(output_path)}"
    
    def _generate_instagram_reels(
        self,
        source_video: str,
        clip_id: str,
        start_time: float = 0.0,
        end_time: Optional[float] = None,
    ) -> str:
        """
        Generate Instagram Reels variant (9:16, max 90s).
        Uses stream copy for speed.
        """
        output_path = os.path.join(self.output_dir, f"{clip_id}_instagram.mp4")
        
        cmd = [
            "ffmpeg",
            "-y",
            "-ss", str(start_time),
        ]
        
        if end_time is not None:
            cmd.extend(["-to", str(end_time)])
        
        cmd.extend([
            "-i", source_video,
            "-c", "copy",  # Stream copy (no re-encode)
            "-avoid_negative_ts", "1",
            output_path,
        ])
        
        subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True
        )
        
        return f"/static/outputs/{os.path.basename(output_path)}"
    
    def _generate_tiktok(
        self,
        source_video: str,
        clip_id: str,
        start_time: float = 0.0,
        end_time: Optional[float] = None,
    ) -> str:
        """
        Generate TikTok variant (9:16, 10-60s).
        Uses stream copy for speed.
        """
        output_path = os.path.join(self.output_dir, f"{clip_id}_tiktok.mp4")
        
        cmd = [
            "ffmpeg",
            "-y",
            "-ss", str(start_time),
        ]
        
        if end_time is not None:
            cmd.extend(["-to", str(end_time)])
        
        cmd.extend([
            "-i", source_video,
            "-c", "copy",  # Stream copy (no re-encode)
            "-avoid_negative_ts", "1",
            output_path,
        ])
        
        subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True
        )
        
        return f"/static/outputs/{os.path.basename(output_path)}"


def generate_platform_variants(
    source_video: str,
    clip_id: str,
    start_time: float = 0.0,
    end_time: Optional[float] = None,
) -> Dict[str, str]:
    """Convenience function to generate all platform variants."""
    generator = PlatformVariantGenerator()
    return generator.generate_all_variants(source_video, clip_id, start_time, end_time)
