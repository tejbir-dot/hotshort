"""
🎬 ELITE BUILD: Results API Routes

Routes that serve intelligent clip data to the frontend.
Backend decides → Frontend displays.
"""

from flask import Blueprint, jsonify, request, render_template
from typing import List, Dict, Optional
from utils.clip_schema import ViralClip, clip_to_dict

# Create blueprint for results/clips API
clips_bp = Blueprint('clips', __name__, url_prefix='/api/clips')


@clips_bp.route('/get_clips', methods=['GET'])
def get_clips():
    """
    Retrieve all clips for a job/session.
    
    Query params:
    - job_id: The job ID (optional, for filtering)
    
    Returns JSON array of ViralClip objects
    """
    # In a real app, you'd fetch from database or session
    # For now, return example data
    
    clips = []
    
    # This would come from your clip generation pipeline
    # Example structure shown here:
    example_clips = [
        {
            "clip_id": "clip_1",
            "title": "Most people learn coding wrong",
            "clip_url": "/static/outputs/clip_1_main.mp4",
            "platform_variants": {
                "youtube_shorts": "/static/outputs/clip_1_youtube.mp4",
                "instagram_reels": "/static/outputs/clip_1_instagram.mp4",
                "tiktok": "/static/outputs/clip_1_tiktok.mp4"
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
            "transcript": "Most people learn coding wrong. They start with syntax, memorizing rules without understanding the principles...",
            "start_time": 45.2,
            "end_time": 60.5,
            "duration": 15.3
        },
        {
            "clip_id": "clip_2",
            "title": "Why function composition matters",
            "clip_url": "/static/outputs/clip_2_main.mp4",
            "platform_variants": {
                "youtube_shorts": "/static/outputs/clip_2_youtube.mp4",
                "instagram_reels": "/static/outputs/clip_2_instagram.mp4",
                "tiktok": "/static/outputs/clip_2_tiktok.mp4"
            },
            "hook_type": "Question",
            "confidence": 71,
            "scores": {
                "hook": 0.75,
                "retention": 0.70,
                "clarity": 0.68,
                "emotion": 0.65
            },
            "selection_reason": {
                "primary": "Intriguing question hooks curiosity",
                "secondary": "Steady engagement throughout",
                "risk": None
            },
            "why": [
                "Poses question that creates knowledge gap",
                "Demonstrates clear value proposition",
                "Moderate length ideal for social"
            ],
            "rank": 2,
            "is_best": False,
            "transcript": "Why does function composition matter? Because it lets you build complex systems...",
            "start_time": 120.0,
            "end_time": 135.0,
            "duration": 15.0
        }
    ]
    
    return jsonify(example_clips)


@clips_bp.route('/download/<clip_id>/<platform>', methods=['GET'])
def download_clip(clip_id: str, platform: str):
    """
    Download a clip variant for a specific platform.
    
    Args:
        clip_id: The clip ID (e.g., "clip_1")
        platform: The platform ("youtube_shorts", "instagram_reels", "tiktok")
    
    Returns: File download
    """
    # In a real app, you'd:
    # 1. Verify the clip exists
    # 2. Check the platform variant exists
    # 3. Return the file
    
    # For now, return a 404 placeholder
    return jsonify({"error": "Clip not found"}), 404


@clips_bp.route('/transcript/<clip_id>', methods=['GET'])
def get_transcript(clip_id: str):
    """
    Get the full transcript for a clip (for modal view).
    
    Args:
        clip_id: The clip ID
    
    Returns: JSON with transcript text
    """
    # In a real app, fetch from database
    return jsonify({
        "clip_id": clip_id,
        "transcript": "Full transcript text here..."
    })
