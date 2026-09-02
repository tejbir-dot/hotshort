import os
import time
import logging
from typing import Dict, Any, List

try:
    from viral_finder.director_reasoner import select_director
    from viral_finder.shot_planner import build_shot_plan
except ImportError:
    # Handle direct testing/running
    from director_reasoner import select_director  # type: ignore
    from shot_planner import build_shot_plan  # type: ignore

log = logging.getLogger("visual_director")

def apply_visual_contract(cand: Dict[str, Any], ctx: Any) -> Dict[str, Any]:
    """
    Acts as the AI Film Director for a single candidate.
    """
    try:
        # 1. Reasoner: Choose the Director Profile
        profile, reason, confidence = select_director(cand, ctx.visual_features, ctx.transcript)
        
        # 2. Planner: Build the Shot Plan
        shot_plan = build_shot_plan(cand, profile, ctx.transcript)
        
        # 3. Assemble the Visual Contract v2
        visual_contract = {
            "version": 1,
            "director": profile.get("name", "base"),
            "profile_rules": profile,
            "shot_plan": shot_plan,
            "confidence": confidence,
            "reason": reason
        }
        
        cand["visual_contract"] = visual_contract
        
        if os.environ.get("HS_TRACE_MODE", "false").strip().lower() == "true":
            tid = cand.get("trace_id")
            if tid:
                ctx.trace_event(
                    trace_id=tid,
                    stage="VISUAL_DIRECTOR",
                    event="CONTRACT_GENERATED",
                    changed=True,
                    impact="HIGH",
                    after={"director": visual_contract["director"], "reason": reason}
                )
                
    except Exception as e:
        log.error(f"[VISUAL_DIRECTOR] Failed to build visual contract for {cand.get('id', 'unk')}: {e}")
        
    return cand

def _run_visual_director(ctx: Any) -> None:
    """
    Pipeline Layer 11.5: Visual Director AI.
    Runs immediately before the Editor Refiner.
    """
    import os
    if os.environ.get("HS_ENABLE_VISUAL_DIRECTOR", "1").strip() != "1":
        return

    t0 = time.time()
    candidates = list(ctx.ranked_output or ctx.final_candidates or [])
    
    if not candidates:
        return
        
    for cand in candidates:
        apply_visual_contract(cand, ctx)
        
        vc = cand.get("visual_contract", {})
        if vc:
            log.info(f"\n[VISUAL_DIRECTOR] cid={cand.get('id', cand.get('cid', 'unk'))} | Director: {vc.get('director').upper()}")
            log.info(f"  Reason: {vc.get('reason')}")
            log.info(f"  Shots Planned: {len(vc.get('shot_plan', []))}\n")
            
    # Record stage time (assumes ctx has a method or dict for this)
    if hasattr(ctx, "record_stage_metric"):
        ctx.record_stage_metric("L11.5_VISUAL_DIRECTOR", time.time() - t0)
