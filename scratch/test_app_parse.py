import sys
import json
sys.path.append(".")
from app import ViralClip, ScoreBreakdown, SelectionReason, infer_hook_type

simple_clip = {
    "clip_id": "test", "start": 0, "end": 15, "clip_url": "https://test", 
    "score": 0.9, "signals": {"narrative": {}, "engagement": {}, "semantic": {}, "psychology": {}},
    "explanation": {}, "why": []
}

try:
    idx = 0
    signals = simple_clip.get("signals") if isinstance(simple_clip.get("signals"), dict) else {}
    narrative_sig = signals.get("narrative", {}) if isinstance(signals.get("narrative"), dict) else {}
    engagement_sig = signals.get("engagement", {}) if isinstance(signals.get("engagement"), dict) else {}
    semantic_sig = signals.get("semantic", {}) if isinstance(signals.get("semantic"), dict) else {}
    psychology_sig = signals.get("psychology", {}) if isinstance(signals.get("psychology"), dict) else {}

    base_score = float(simple_clip.get("base_score", simple_clip.get("score", 0.5)) or 0.0)
    final_score = float(simple_clip.get("final_score", simple_clip.get("score", 0.5)) or 0.0)
    hook_score = float(simple_clip.get("hook_score", narrative_sig.get("hook_score", final_score)) or 0.0)
    open_loop_score = float(simple_clip.get("open_loop_score", narrative_sig.get("open_loop_score", 0.0)) or 0.0)
    pattern_break_score = float(simple_clip.get("pattern_break_score", hook_score) or 0.0)
    ending_strength = float(simple_clip.get("ending_strength", narrative_sig.get("ending_strength", final_score)) or 0.0)
    payoff_resolution_score = float(simple_clip.get("payoff_resolution_score", narrative_sig.get("payoff_resolution_score", open_loop_score)) or 0.0)
    rewatch_score = float(simple_clip.get("rewatch_score", narrative_sig.get("rewatch_score", final_score)) or 0.0)
    information_density_score = float(simple_clip.get("information_density_score", narrative_sig.get("information_density_score", final_score)) or 0.0)
    virality_confidence = float(simple_clip.get("virality_confidence", narrative_sig.get("virality_confidence", 1.0)) or 0.0)
    duration_score = float(simple_clip.get("duration_score", final_score) or 0.0)
    
    # Simulate clip_to_dict crash
    def clip_to_dict(clip):
        return {
            "arc_quality_breakdown": {
                "hook": int(getattr(clip, "pattern_break_score", 0.0) * 25),
                "payoff": int(getattr(clip, "payoff_resolution_score", 0.0) * 35),
                "ending": int(getattr(clip, "scores", {}).clarity * 20) if hasattr(clip, "scores") else 0,
                "duration": int(getattr(clip, "duration", 0) / 40 * 20) if getattr(clip, "duration", 0) <= 40 else 20,
            }
        }
        
    class MockClip:
        def __init__(self):
            self.pattern_break_score = 0.5
            self.payoff_resolution_score = 0.5
            self.scores = ScoreBreakdown(hook=1, retention=1, clarity=1, emotion=1)
            self.duration = None
            
    print(clip_to_dict(MockClip()))
    print("No crash so far.")
except Exception as e:
    import traceback
    print("CRASH:", traceback.format_exc())
