import sys

with open('viral_finder/orchestrator.py', 'r', encoding='utf-8') as f:
    content = f.read()

if 'from viral_finder.cognition import Evidence, IntelligenceArtifact' not in content:
    content = content.replace('from collections import Counter\n', 'from collections import Counter\nfrom viral_finder.cognition import Evidence, IntelligenceArtifact\n')

target_ranking = '''def _run_ranking(ctx: PipelineContext) -> None:
    t0 = time.time()
    use_viral_score = _env_bool("HS_ENABLE_ALIGNMENT_SCORING", True)
    for cand in (ctx.enriched_candidates or []):
        psych = cand.get("signals", {}).get("psychology", {})
        sem = cand.get("signals", {}).get("semantic", {})
        nar = cand.get("signals", {}).get("narrative", {})
        eng = cand.get("signals", {}).get("engagement", {})
        curiosity_peak = _clamp01(psych.get("curiosity_peak", psych.get("curiosity", 0.0)))
        semantic_impact = _clamp01(sem.get("impact", 0.0))
        semantic_score = _clamp01((0.5 * semantic_impact) + (0.3 * _clamp01(sem.get("meaning", 0.0))) + (0.2 * _clamp01(sem.get("clarity", 0.0))))
        engagement_energy = _clamp01(eng.get("energy", eng.get("classic", 0.0)))
        engagement_score = _clamp01((0.6 * engagement_energy) + (0.25 * _clamp01(eng.get("audio", 0.0))) + (0.15 * _clamp01(eng.get("motion", 0.0))))
        trigger_density = _clamp01(nar.get("trigger_density", 0.0))
        trigger_score = _clamp01(nar.get("trigger_score", 0.0))
        trigger_type = str(nar.get("trigger_type", "") or "")
        _t_bonus = 0.3 if trigger_type in ("complete_thought", "payoff") else (0.2 if trigger_type == "belief_reversal" else 0.0)
        narrative_score = _clamp01((0.55 * trigger_score) + (0.45 * trigger_density) + _t_bonus)
        payoff_confidence = _clamp01(psych.get("payoff_confidence", cand.get("payoff_confidence", 0.0)))
        explanation_strength = _semantic_explanation_strength(cand)
        low_motion_talk = bool(
            explanation_strength >= 0.62
            and _clamp01(eng.get("motion", 0.0)) <= 0.08
            and _clamp01(sem.get("meaning", 0.0)) >= 0.58
        )
        base_viral_score = (
            0.40 * curiosity_peak +
            0.30 * semantic_score +
            0.20 * engagement_score +
            0.10 * narrative_score
        )
        cand["base_viral_score"] = round(float(base_viral_score), 4)
        payoff_floor = max(0.12, 0.28 * explanation_strength)
        payoff_gate = max(payoff_confidence, payoff_floor if low_motion_talk else 0.0)
        blended_payoff = _clamp01((0.72 * payoff_confidence) + (0.28 * payoff_gate))
        viral_score = float(base_viral_score * blended_payoff)
        if bool(cand.get("insight_candidate", False)):
            viral_score *= 1.08
        cand["viral_score"] = round(float(viral_score), 4)
        cand["ranking_payoff_gate"] = round(float(blended_payoff), 4)
        cand["low_motion_talk"] = low_motion_talk

    # ???? Hook-origin floor boost ????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????
    # Hook Hunter clips are injected AFTER semantic scoring, so they carry
    # semantic=0 / engagement=0 / curiosity=0 -> base_viral_score ~= 0.
    # Without a floor they always rank last and get cut before arc assembly.
    # Grant them a minimum viral_score equal to their raw hook_score so they
    # compete fairly with strict candidates.
    for cand in (ctx.enriched_candidates or []):
        if _candidate_origin(cand) == "hook":
            raw_hook = float(cand.get("score", 0.0) or 0.0)
            # Floor = 40% of raw hook score (keeps them below strong strict candidates)
            hook_floor = raw_hook * 0.40
            if cand.get("viral_score", 0.0) < hook_floor:
                cand["viral_score"] = round(hook_floor, 4)
                log.debug("[HOOK-FLOOR] cid=%s viral_score boosted to %.4f (hook_score=%.3f)",
                          cand.get("cid", "?"), hook_floor, raw_hook)
    # ????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????

    ranked = sorted(
        (ctx.enriched_candidates or []),
        key=lambda x: (
            _rank_score(
                x,
                "viral_score" if use_viral_score else "score_enriched",
                "score_enriched",
                "score",
            ),
            _rank_score(x, "score_enriched", "score"),
            _rank_score(x, "score"),
        ),
        reverse=True,
    )'''

replacement_ranking = '''def _run_ranking(ctx: PipelineContext) -> None:
    t0 = time.time()
    for cand in (ctx.enriched_candidates or []):
        # 1. Ensure artifact exists
        artifact = cand.get("intelligence")
        if not artifact:
            artifact = IntelligenceArtifact()
            cand["intelligence"] = artifact
            
        psych = cand.get("signals", {}).get("psychology", {})
        sem = cand.get("signals", {}).get("semantic", {})
        nar = cand.get("signals", {}).get("narrative", {})
        eng = cand.get("signals", {}).get("engagement", {})
        
        # Extract heuristic evidence
        curiosity_peak = _clamp01(psych.get("curiosity_peak", psych.get("curiosity", 0.0)))
        semantic_impact = _clamp01(sem.get("impact", 0.0))
        engagement_energy = _clamp01(eng.get("energy", eng.get("classic", 0.0)))
        motion = _clamp01(eng.get("motion", 0.0))
        trigger_density = _clamp01(nar.get("trigger_density", 0.0))
        payoff_confidence = _clamp01(psych.get("payoff_confidence", cand.get("payoff_confidence", 0.0)))
        
        # 2. Emit Local Evidence
        artifact.evidence_stream.extend([
            Evidence(type="curiosity", value=curiosity_peak, producer="heuristic_engine"),
            Evidence(type="semantic_impact", value=semantic_impact, producer="heuristic_engine"),
            Evidence(type="energy", value=engagement_energy, producer="heuristic_engine"),
            Evidence(type="motion_spike", value=motion, producer="heuristic_engine"),
            Evidence(type="trigger_density", value=trigger_density, producer="heuristic_engine"),
            Evidence(type="payoff_resolved", value=payoff_confidence > 0.4, producer="heuristic_engine"),
            Evidence(type="payoff_confidence", value=payoff_confidence, producer="heuristic_engine")
        ])
        
        # 3. Viral Brain Computation
        stop_scroll = artifact.get_max_value("stop_scroll", 0.0)
        payoff_resolved = artifact.get_bool("payoff_resolved", False)
        motion_spike = artifact.get_max_value("motion_spike", 0.0)
        semantic = artifact.get_max_value("semantic_impact", 0.0)
        curiosity = artifact.get_max_value("curiosity", 0.0)
        
        # If Groq provided stop_scroll, that defines the base. Otherwise rely on local curiosity.
        base_prob = stop_scroll if stop_scroll > 0 else curiosity
        
        # Mix in local semantics if they are strong
        if semantic > 0.6:
            base_prob = (base_prob * 0.7) + (semantic * 0.3)
            
        # Story/Payoff gate
        if payoff_resolved or artifact.get_max_value("payoff_confidence", 0.0) > 0.4:
            base_prob *= 1.25
        else:
            base_prob *= 0.60
            
        # Engagement/Delivery boost
        if motion_spike > 0.70:
            base_prob *= 1.10
            
        cand["viral_probability"] = round(float(min(1.0, max(0.0, base_prob))), 4)
        cand["viral_score"] = cand["viral_probability"]  # Keep for backward compatibility

    ranked = sorted(
        (ctx.enriched_candidates or []),
        key=lambda x: (
            float(x.get("viral_probability", 0.0)),
            _rank_score(x, "score_enriched", "score"),
        ),
        reverse=True,
    )'''

content = content.replace(target_ranking, replacement_ranking)

with open('viral_finder/orchestrator.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated orchestrator.py")
