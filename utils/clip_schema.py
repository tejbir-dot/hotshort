"""
🎬 CLIP DATA CONTRACT (Backend → Frontend)

This module defines the canonical clip structure that the backend returns to the frontend.
The frontend is purely a renderer - it never computes intelligence, only displays it.

Every clip object MUST include:
- clip_id, title, clip_url (required for playback)
- platform_variants (required for distribution)
- hook_type, confidence, scores (explain the decision)
- selection_reason, why (show the user why this clip matters)
- rank, is_best (position in carousel)
- transcript (source truth)
"""

from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
import json


@dataclass
class SelectionReason:
    """Explain why this clip was selected."""
    primary: str  # Main reason ("Strong contradiction in first 2.1 seconds")
    secondary: Optional[str] = None  # Supporting reason
    risk: Optional[str] = None  # Caveat ("Appeals mainly to beginners")


@dataclass
class ScoreBreakdown:
    """Raw component scores (0.0-1.0 range)."""
    hook: float  # Hook strength (curiosity/pattern break)
    retention: float  # Audience retention potential
    clarity: float  # Message clarity
    emotion: float  # Emotional resonance


@dataclass
class PlatformVariants:
    """URLs for platform-optimized versions."""
    youtube_shorts: str  # 9:16, 60s max
    instagram_reels: str  # 9:16, 90s max
    tiktok: str  # 9:16, 10s-60s
    # Add more as needed: twitch, youtube_long, etc.


@dataclass
class ViralClip:
    """
    Complete clip object with all metadata.
    This is what the backend sends to the frontend.
    Frontend never modifies this - it only displays it.
    """
    # Playback
    clip_id: str  # Unique identifier ("clip_1", "clip_2", ...)
    title: str  # Auto-generated or hand-tuned hook text
    clip_url: str  # Main video file URL (/static/outputs/clip_1_main.mp4)
    
    # Distribution
    platform_variants: Dict[str, str]  # {"youtube_shorts": "/static/...", ...}
    
    # Intelligence
    hook_type: str  # "Contradiction", "Question", "Curiosity Gap", "Emotional", etc.
    confidence: int  # 0-100 derived from avg of scores
    scores: ScoreBreakdown  # Component breakdown
    
    # Reasoning
    selection_reason: SelectionReason  # Why this clip
    why: List[str]  # Human-readable bullet points (~3-5 items)
    
    # Metadata
    rank: int  # Position in carousel (1-indexed)
    is_best: bool  # Is this the "best pick"?
    transcript: str  # Full transcript text (for "View transcript" modal)
    is_recommended: bool = False  # Highlighted pick (top 2–3), but never hides others
    
    # Optional
    start_time: Optional[float] = None  # Seconds in original video
    end_time: Optional[float] = None  # Seconds in original video
    duration: Optional[float] = None  # Clip duration in seconds


def create_viral_clip(
    clip_id: str,
    title: str,
    clip_url: str,
    platform_variants: dict,
    hook_type: str,
    hook_score: float,
    retention_score: float,
    clarity_score: float,
    emotion_score: float,
    why_bullets: List[str],
    selection_reason: SelectionReason,
    transcript: str,
    rank: int,
    is_best: bool = False,
    is_recommended: bool = False,
    start_time: Optional[float] = None,
    end_time: Optional[float] = None,
) -> ViralClip:
    """
    Factory function to create a ViralClip object.
    
    Confidence is auto-calculated as weighted average:
    - hook: 0.40 weight (most important for virality)
    - retention: 0.35
    - clarity: 0.15
    - emotion: 0.10
    """
    confidence = int(
        (hook_score * 0.40 + 
         retention_score * 0.35 + 
         clarity_score * 0.15 + 
         emotion_score * 0.10) * 100
    )
    
    duration = (end_time - start_time) if (start_time and end_time) else None
    
    return ViralClip(
        clip_id=clip_id,
        title=title,
        clip_url=clip_url,
        platform_variants=platform_variants,
        hook_type=hook_type,
        confidence=confidence,
        scores=ScoreBreakdown(
            hook=round(hook_score, 2),
            retention=round(retention_score, 2),
            clarity=round(clarity_score, 2),
            emotion=round(emotion_score, 2),
        ),
        selection_reason=selection_reason,
        why=why_bullets,
        rank=rank,
        is_best=is_best,
        is_recommended=is_recommended,
        transcript=transcript,
        start_time=start_time,
        end_time=end_time,
        duration=duration,
    )


def clip_to_dict(clip: ViralClip) -> dict:
    """Convert ViralClip to JSON-serializable dictionary."""
    data = asdict(clip)
    # Ensure selection_reason is also a dict
    if isinstance(data['selection_reason'], SelectionReason):
        data['selection_reason'] = asdict(data['selection_reason'])
    if isinstance(data['scores'], ScoreBreakdown):
        data['scores'] = asdict(data['scores'])
    return data


def clip_to_json(clip: ViralClip) -> str:
    """Convert ViralClip to JSON string."""
    return json.dumps(clip_to_dict(clip), indent=2)


# Example structure for documentation:
EXAMPLE_CLIP = {
    "clip_id": "clip_2",
    "title": "Most people learn coding wrong",
    "clip_url": "/static/outputs/clip_2_main.mp4",
    
    "platform_variants": {
        "youtube_shorts": "/static/outputs/clip_2_youtube.mp4",
        "instagram_reels": "/static/outputs/clip_2_instagram.mp4",
        "tiktok": "/static/outputs/clip_2_tiktok.mp4"
    },
    
    "hook_type": "Contradiction",
    "confidence": 82,
    
    "scores": {
        "hook": 0.90,
        "retention": 0.82,
        "clarity": 0.78,
        "emotion": 0.70
    },
    
    "selection_reason": {
        "primary": "Strong contradiction in first 2.1 seconds",
        "secondary": "High retention spike after hook",
        "risk": "Appeals mainly to beginners"
    },
    
    "why": [
        "Interrupts scrolling with disagreement",
        "Aligns with beginner frustration",
        "Clear promise early in the clip"
    ],
    
    "rank": 1,
    "is_best": True,
    "is_recommended": True,
    "transcript": "full transcript text here...",
    
    "start_time": 45.2,
    "end_time": 60.5,
    "duration": 15.3
}
