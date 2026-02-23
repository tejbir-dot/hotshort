"""
🎬 INTELLIGENT CLIP BUILDER

Transforms raw ultron output into rich, explainable clip objects.
This is where backend intelligence → frontend data contract happens.
"""

import re
from typing import List, Dict, Optional, Tuple
from utils.clip_schema import (
    ViralClip,
    SelectionReason,
    create_viral_clip,
)
from utils.platform_variants import generate_platform_variants


class ClipBuilder:
    """Transform raw analysis into intelligent clip objects."""
    
    # Hook type patterns (map text patterns to hook types)
    HOOK_PATTERNS = {
        "Contradiction": [
            r"\bwrong\b", r"\bnot\b", r"\bopposite\b", r"\bdisagree\b",
            r"\bnever\b", r"\bdoesn't|doesn't\b", r"\bisn't|isn't\b",
            r"\bmyth\b", r"\bbelieve\b", r"\bthink\b"
        ],
        "Question": [r"\?", r"\bwhy\b", r"\bhow\b", r"\bwhat\b"],
        "Curiosity Gap": [
            r"\bsecret\b", r"\bhidden\b", r"\bfound\b", r"\bdiscovered\b",
            r"\bnobody\b", r"\bmost people\b"
        ],
        "Emotional": [
            r"\blove\b", r"\bhate\b", r"\bawesome\b", r"\fincredible\b",
            r"\blaughable\b", r"\bdevastating\b"
        ],
        "Authority/Proof": [
            r"\bprove\b", r"\bscience\b", r"\bresearch\b", r"\bstudies\b",
            r"\bfacts\b", r"\bevidence\b"
        ],
    }
    
    def __init__(self, transcript: Optional[str] = None):
        """
        Initialize builder.
        
        Args:
            transcript: Full transcript of the source video (for context)
        """
        self.transcript = transcript or ""
    
    def detect_hook_type(self, text: str) -> str:
        """Detect what type of hook this clip uses."""
        text_lower = text.lower()
        
        # Score each hook type
        scores = {}
        for hook_type, patterns in self.HOOK_PATTERNS.items():
            match_count = sum(
                1 for pattern in patterns 
                if re.search(pattern, text_lower)
            )
            scores[hook_type] = match_count
        
        # Return highest-scoring type, default to "Pattern Break"
        if max(scores.values()) > 0:
            return max(scores, key=scores.get)
        return "Pattern Break"
    
    def generate_why_bullets(
        self,
        hook_type: str,
        hook_score: float,
        retention_score: float,
        text: str,
    ) -> List[str]:
        """Generate human-readable bullet points explaining why this clip works."""
        bullets = []
        
        # Bullet 1: Hook explanation
        if hook_type == "Contradiction":
            bullets.append("Opens with disagreement or counter-intuition")
        elif hook_type == "Question":
            bullets.append("Poses an intriguing question immediately")
        elif hook_type == "Curiosity Gap":
            bullets.append("Reveals something rare or surprising")
        elif hook_type == "Emotional":
            bullets.append("Triggers immediate emotional reaction")
        elif hook_type == "Authority/Proof":
            bullets.append("Backs up claim with data or expertise")
        else:
            bullets.append("Breaks expected pattern early")
        
        # Bullet 2: Retention
        if retention_score > 0.8:
            bullets.append("Viewers stay throughout - high momentum")
        elif retention_score > 0.7:
            bullets.append("Holds attention with steady pacing")
        elif retention_score > 0.6:
            bullets.append("Decent retention, but some drop-off mid-clip")
        else:
            bullets.append("Starts strong but may lose momentum")
        
        # Bullet 3: What it's good for
        # Infer from text length and complexity
        word_count = len(text.split())
        if word_count > 100:
            bullets.append("Deep-dive format good for education/explanations")
        elif word_count > 50:
            bullets.append("Balanced length for storytelling")
        else:
            bullets.append("Quick hit - perfect for mobile scrollers")
        
        return bullets
    
    def build_clip(
        self,
        clip_id: str,
        start_time: float,
        end_time: float,
        text: str,  # Clip text/transcript
        hook_score: float,
        retention_score: float,
        clarity_score: float = 0.75,
        emotion_score: float = 0.70,
        source_video: Optional[str] = None,
        rank: int = 1,
        is_best: bool = False,
    ) -> ViralClip:
        """
        Build a complete ViralClip object.
        
        This is the factory function that transforms raw analysis into
        an explainable clip object ready for frontend consumption.
        """
        
        # Detect hook type from text
        hook_type = self.detect_hook_type(text)
        
        # Generate why bullets
        why_bullets = self.generate_why_bullets(
            hook_type, hook_score, retention_score, text
        )
        
        # Create primary clip URL
        clip_url = f"/static/outputs/{clip_id}_main.mp4"
        
        # Generate platform variants (if source video provided)
        platform_variants = {}
        if source_video:
            try:
                platform_variants = generate_platform_variants(
                    source_video, clip_id, start_time, end_time
                )
            except Exception as e:
                print(f"⚠️ Platform variant generation failed: {e}")
                # Fallback: use main clip for all platforms
                platform_variants = {
                    "youtube_shorts": clip_url,
                    "instagram_reels": clip_url,
                    "tiktok": clip_url,
                }
        
        # Build selection reason
        selection_reason = self._build_selection_reason(
            hook_type, hook_score, retention_score, text
        )
        
        # Create the clip
        clip = create_viral_clip(
            clip_id=clip_id,
            title=text[:60] + "..." if len(text) > 60 else text,  # First 60 chars
            clip_url=clip_url,
            platform_variants=platform_variants,
            hook_type=hook_type,
            hook_score=hook_score,
            retention_score=retention_score,
            clarity_score=clarity_score,
            emotion_score=emotion_score,
            why_bullets=why_bullets,
            selection_reason=selection_reason,
            transcript=text,
            rank=rank,
            is_best=is_best,
            start_time=start_time,
            end_time=end_time,
        )
        
        return clip
    
    def _build_selection_reason(
        self,
        hook_type: str,
        hook_score: float,
        retention_score: float,
        text: str,
    ) -> SelectionReason:
        """Build detailed selection reasoning."""
        
        # Primary reason
        if hook_score > 0.85:
            primary = f"Exceptional {hook_type.lower()} hook in first 2-3 seconds"
        elif hook_score > 0.75:
            primary = f"Strong {hook_type.lower()} that interrupts scrolling"
        else:
            primary = f"{hook_type} present with decent engagement potential"
        
        # Secondary reason
        secondary = None
        if retention_score > 0.8:
            secondary = "High audience retention throughout"
        elif retention_score > 0.7:
            secondary = "Momentum maintained across clip"
        
        # Risk/caveat
        risk = None
        if "how to" in text.lower() or "tutorial" in text.lower():
            risk = "Educational format appeals mainly to learners"
        elif "opinion" in text.lower() or "i think" in text.lower():
            risk = "Strong opinion may polarize audience"
        elif hook_score < 0.65:
            risk = "Hook is subtle - may not stop fast scrollers"
        
        return SelectionReason(
            primary=primary,
            secondary=secondary,
            risk=risk,
        )


def build_clips_from_analysis(
    analysis_results: List[Dict],
    source_video: Optional[str] = None,
    full_transcript: Optional[str] = None,
) -> List[ViralClip]:
    """
    Transform raw ultron analysis results into ViralClip objects.
    
    Args:
        analysis_results: List of dicts with keys:
            - start_time, end_time
            - text, hook_score, retention_score, clarity_score, emotion_score
        source_video: Path to source video (for generating variants)
        full_transcript: Full transcript for context
    
    Returns:
        List of ViralClip objects ready for frontend consumption
    """
    builder = ClipBuilder(transcript=full_transcript)
    clips = []
    
    for i, result in enumerate(analysis_results, 1):
        clip = builder.build_clip(
            clip_id=f"clip_{i}",
            start_time=result.get("start_time", 0.0),
            end_time=result.get("end_time", 15.0),
            text=result.get("text", ""),
            hook_score=result.get("hook_score", 0.7),
            retention_score=result.get("retention_score", 0.7),
            clarity_score=result.get("clarity_score", 0.75),
            emotion_score=result.get("emotion_score", 0.70),
            source_video=source_video,
            rank=i,
            is_best=(i == 1),  # First clip is the best
        )
        clips.append(clip)
    
    return clips
