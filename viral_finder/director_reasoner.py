import os
import json
import logging
from typing import Dict, Any, Tuple

log = logging.getLogger("director_reasoner")

PROFILES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "effects", "director_profiles")

def load_profile(name: str) -> Dict[str, Any]:
    path = os.path.join(PROFILES_DIR, f"{name}_director.json")
    if not os.path.exists(path):
        path = os.path.join(PROFILES_DIR, "base_director.json")
    try:
        with open(path, "r") as f:
            profile = json.load(f)
            
        # Handle inheritance
        if "parent" in profile:
            parent = load_profile(profile["parent"])
            # Simple shallow merge for camera settings
            if "camera" in parent:
                merged_camera = dict(parent["camera"])
                merged_camera.update(profile.get("camera", {}))
                profile["camera"] = merged_camera
        return profile
    except Exception as e:
        log.error(f"[DIRECTOR_REASONER] Failed to load profile {name}: {e}")
        return {"name": "base", "camera": {}}

def select_director(cand: Dict[str, Any], visual_features: list, transcript: list) -> Tuple[Dict[str, Any], str, float]:
    """
    Fuses Story Intelligence and Visual DNA to select the best Director Profile.
    Returns: (profile_dict, reasoning_string, confidence_score)
    """
    s = float(cand.get("start", 0.0) or 0.0)
    e = float(cand.get("end", 0.0) or 0.0)
    
    # 1. Extract Story Context
    nar = cand.get("signals", {}).get("narrative", {})
    psych = cand.get("signals", {}).get("psychology", {})
    trigger_type = str(nar.get("trigger_type", "") or "")
    curiosity_peak = float(psych.get("curiosity_peak", 0.0) or 0.0)
    
    is_high_tension = (curiosity_peak > 0.6) or (trigger_type == "belief_reversal")
    
    # 2. Extract Visual DNA (Heuristic face/speaker count)
    # Estimate speakers/faces from visual features overlapping candidate
    face_counts = []
    motion_levels = []
    for vf in (visual_features or []):
        t = float(vf.get("t", vf.get("time", vf.get("start", 0.0))) or 0.0)
        if s <= t <= e:
            faces = vf.get("faces", [])
            face_counts.append(len(faces) if isinstance(faces, list) else int(vf.get("num_faces", 0)))
            motion_levels.append(float(vf.get("motion", vf.get("motion_energy", 0.0)) or 0.0))
            
    avg_faces = sum(face_counts) / max(1, len(face_counts))
    avg_motion = sum(motion_levels) / max(1, len(motion_levels))
    
    # 3. Decision Matrix
    reasoning = []
    director_name = "base"
    confidence = 0.5
    
    if avg_faces > 1.5:
        if is_high_tension:
            director_name = "debate"
            reasoning.append("Multiple faces detected with high tension story trigger.")
            confidence = 0.90
        else:
            director_name = "podcast"
            reasoning.append("Multiple faces detected with standard conversational flow.")
            confidence = 0.85
    elif is_high_tension and avg_motion < 0.2:
        director_name = "motivation"
        reasoning.append("Single face, low motion, but high narrative tension.")
        confidence = 0.88
    else:
        director_name = "base"
        reasoning.append("Standard single-speaker setup.")
        confidence = 0.70
        
    reasoning_str = f"{director_name.capitalize()} Director selected because: {' '.join(reasoning)}"
    profile = load_profile(director_name)
    
    return profile, reasoning_str, confidence
