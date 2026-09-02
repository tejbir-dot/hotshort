import logging
from typing import Dict, Any, List

log = logging.getLogger("shot_planner")

def _seg_bounds(seg: Dict[str, Any]) -> tuple[float, float]:
    ss = float(seg.get("start", 0.0) or 0.0)
    ee = float(seg.get("end", ss) or ss)
    return ss, max(ss, ee)

def build_shot_plan(cand: Dict[str, Any], profile: Dict[str, Any], transcript: list) -> List[Dict[str, Any]]:
    """
    Converts a Director Profile and candidate boundaries into a timeline of discrete shots.
    """
    s = float(cand.get("start", 0.0) or 0.0)
    e = float(cand.get("end", 0.0) or 0.0)
    
    camera_rules = profile.get("camera", {})
    shot_plan = []
    
    # Simple Segment-Based Planner
    # Iterates over transcript segments in the window and assigns camera actions
    
    current_shot_start = s
    last_speaker = None
    
    for seg in transcript:
        seg_s, seg_e = _seg_bounds(seg)
        if seg_e <= s or seg_s >= e:
            continue
            
        # Determine the shot intent for this segment
        shot_intent = "medium_shot"
        zoom_level = 1.0
        
        # Apply Profile Rules
        if camera_rules.get("reaction_cut") and last_speaker and last_speaker != seg.get("speaker"):
            shot_intent = "reaction_shot"
            
        if camera_rules.get("slow_push_in"):
            shot_intent = "slow_push_in"
            zoom_level = 1.15
            
        if camera_rules.get("climax_zoom") and "?" in str(seg.get("text", "")):
            # Fake heuristic for climax
            shot_intent = "punch_in"
            zoom_level = 1.3
            
        shot_plan.append({
            "start": max(s, seg_s),
            "end": min(e, seg_e),
            "intent": shot_intent,
            "target_speaker": seg.get("speaker", "unknown"),
            "zoom": zoom_level,
            "crop": camera_rules.get("crop", "dynamic_9_16")
        })
        
        last_speaker = seg.get("speaker")
        
    # If no segments matched, provide a fallback shot
    if not shot_plan:
        shot_plan.append({
            "start": s,
            "end": e,
            "intent": "static_wide",
            "zoom": 1.0,
            "crop": camera_rules.get("crop", "dynamic_9_16")
        })
        
    return shot_plan
