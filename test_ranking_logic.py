import sys
import json
import copy

from viral_finder.orchestrator import _run_ranking
from viral_finder.cognition import Evidence, IntelligenceArtifact

class MockContext:
    def __init__(self, candidates):
        self.enriched_candidates = candidates
        
candidates = [
    {
        "id": "1_groq_genius",
        "title": "Groq Genius Trigger (High Psych, Low Local)",
        "cortex_enabled": True,
        "score": 0.95, 
        "intelligence": IntelligenceArtifact(evidence_stream=[
            Evidence(type="stop_scroll", value=0.95, producer="groq_trigger"),
            Evidence(type="memorability", value=0.90, producer="groq_trigger")
        ]),
        "signals": {
            "psychology": {"payoff_confidence": 0.5}, 
            "semantic": {"impact": 0.1, "meaning": 0.1, "clarity": 0.1},
            "engagement": {"energy": 0.1, "audio": 0.1, "motion": 0.1},
            "narrative": {"trigger_density": 0.1, "trigger_score": 0.1}
        }
    },
    {
        "id": "2_loud_local",
        "title": "Loud Local Clip (Low Psych, High Local)",
        "score": 0.0,
        "signals": {
            "psychology": {"curiosity_peak": 0.1, "payoff_confidence": 0.8},
            "semantic": {"impact": 0.9, "meaning": 0.8, "clarity": 0.9},
            "engagement": {"energy": 0.9, "audio": 0.9, "motion": 0.8},
            "narrative": {"trigger_density": 0.7, "trigger_score": 0.8, "trigger_type": "payoff"}
        }
    },
    {
        "id": "3_balanced",
        "title": "Balanced Clip (Mid Psych, Mid Local)",
        "score": 0.0,
        "signals": {
            "psychology": {"curiosity_peak": 0.6, "payoff_confidence": 0.6},
            "semantic": {"impact": 0.6, "meaning": 0.6, "clarity": 0.6},
            "engagement": {"energy": 0.6, "audio": 0.6, "motion": 0.5},
            "narrative": {"trigger_density": 0.5, "trigger_score": 0.5}
        }
    }
]

def old_ranking_math(cands):
    results = []
    for cand in cands:
        c = dict(cand)
        psych = c.get("signals", {}).get("psychology", {})
        sem = c.get("signals", {}).get("semantic", {})
        nar = c.get("signals", {}).get("narrative", {})
        eng = c.get("signals", {}).get("engagement", {})
        
        curiosity_peak = psych.get("curiosity_peak", 0.0)
        semantic_impact = sem.get("impact", 0.0)
        semantic_score = (0.5 * semantic_impact) + (0.3 * sem.get("meaning", 0.0)) + (0.2 * sem.get("clarity", 0.0))
        engagement_energy = eng.get("energy", 0.0)
        engagement_score = (0.6 * engagement_energy) + (0.25 * eng.get("audio", 0.0)) + (0.15 * eng.get("motion", 0.0))
        trigger_density = nar.get("trigger_density", 0.0)
        trigger_score = nar.get("trigger_score", 0.0)
        _t_bonus = 0.3 if nar.get("trigger_type") == "payoff" else 0.0
        narrative_score = (0.55 * trigger_score) + (0.45 * trigger_density) + _t_bonus
        
        payoff_confidence = psych.get("payoff_confidence", 0.0)
        
        base_viral_score = (
            0.40 * curiosity_peak +
            0.30 * semantic_score +
            0.20 * engagement_score +
            0.10 * narrative_score
        )
        blended_payoff = (0.72 * payoff_confidence) + (0.28 * payoff_confidence) 
        
        viral_score = base_viral_score * blended_payoff
        
        # Hook floor
        if c.get("cortex_enabled"):
            hook_floor = c.get("score", 0.0) * 0.40
            if viral_score < hook_floor:
                viral_score = hook_floor
                
        c["viral_score"] = viral_score
        results.append(c)
        
    results.sort(key=lambda x: x["viral_score"], reverse=True)
    return results

print("=== OLD RANKING SYSTEM ===")
old_results = old_ranking_math(candidates)
for i, r in enumerate(old_results):
    print(f"{i+1}. {r['title']} -> Final Score: {r['viral_score']:.4f}")
    
print("\n=== NEW RANKING SYSTEM (Atomic Evidence) ===")
new_candidates = copy.deepcopy(candidates)
ctx = MockContext(new_candidates)
_run_ranking(ctx)

sorted_new = sorted(
    ctx.enriched_candidates,
    key=lambda x: float(x.get("viral_probability", 0.0)),
    reverse=True
)

for i, r in enumerate(sorted_new):
    print(f"{i+1}. {r['title']} -> Final Score: {r['viral_probability']:.4f}")
