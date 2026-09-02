"""
TEMPORARY

Delete after migration.
Adapter to convert the pure CompiledClip back into the legacy candidate dictionary
expected by VisualDirector, EditorRefiner, and Ranking modules.
"""

from typing import Dict, Any
from .narrative_compiler import CompiledClip

class LegacyAdapter:
    @staticmethod
    def to_legacy_dict(clip: CompiledClip) -> Dict[str, Any]:
        """
        Converts the pristine CompiledClip into the sprawling, bloated legacy dictionary
        expected by the rest of the HotShort pipeline.
        """
        return {
            "id": clip.id,
            "start": clip.start,
            "end": clip.end,
            "duration": clip.duration,
            "hook_idx": clip.hook_idx,
            "hook_segment": {
                "idx": clip.hook_idx,
                "text": clip.hook_text,
            },
            "payoff_contract": {
                "idx": clip.payoff_idx,
                "text": clip.payoff_text,
                "time": clip.end,
                "owner": "narrative_compiler",
                "version": clip.narrative_contract.get("contract_version", 1) if isinstance(clip.narrative_contract, dict) else 1
            },
            # Populate standard legacy scores to prevent crashes
            "arc_score": clip.score,
            "viral_score": clip.score,
            "final_score": clip.score,
            "payoff_engine_score": clip.score,
            "hook_strength": clip.score, # Fallback
            "arc_complete": clip.story_complete,
            "provenance": {"stage": "L10_NARRATIVE_COMPILER"},
        }
