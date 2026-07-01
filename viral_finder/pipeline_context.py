from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

@dataclass
class PipelineContext:
    """
    A dataclass to hold all relevant data and state throughout the HotShort
    viral clip generation pipeline. This centralizes context and avoids
    passing numerous arguments between stages.
    """
    path: str
    top_k: int
    allow_fallback: bool
    prefer_gpu: bool = True
    use_cache: bool = True
    transcript: List[Dict[str, Any]] = field(default_factory=list)
    audio_features: List[Dict[str, Any]] = field(default_factory=list)
    visual_features: List[Dict[str, Any]] = field(default_factory=list)
    av_features: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    curiosity_curve: List[Any] = field(default_factory=list)
    curiosity_candidates: List[Any] = field(default_factory=list)
    curiosity: Dict[str, Any] = field(default_factory=dict)
    narrative: Dict[str, Any] = field(default_factory=dict)
    narrative_triggers: List[Dict[str, Any]] = field(default_factory=list)
    idea_nodes: List[Any] = field(default_factory=list)
    raw_candidates: List[Dict[str, Any]] = field(default_factory=list)
    enriched_candidates: List[Dict[str, Any]] = field(default_factory=list)
    validated_candidates: List[Dict[str, Any]] = field(default_factory=list)
    rejected_candidates: List[Dict[str, Any]] = field(default_factory=list)
    final_candidates: List[Dict[str, Any]] = field(default_factory=list)
    ranked_output: List[Dict[str, Any]] = field(default_factory=list)
    narrative_score_cache: Dict[str, Dict[str, float]] = field(default_factory=dict)
    candidate_feature_cache: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    brain: Any = None
    stage_stats: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    transcript_source: str = "unknown"
    target_min: int = 0
    # Fields added for transcription_router.py and other stages
    duration: float = 0.0
    vad_signals: Dict[str, Any] = field(default_factory=dict)
    transcription_engine: str = "unknown"
    transcription_config: Dict[str, Any] = field(default_factory=dict)
    trace_logs: Dict[str, Any] = field(default_factory=dict)

    def trace_state(self, trace_id: str, state: str) -> None:
        if trace_id in self.trace_logs:
            self.trace_logs[trace_id].setdefault("state_history", []).append(state)

    def trace_event(self, trace_id: str, stage: str, event: str, changed: bool, before: Any = None, after: Any = None) -> None:
        if trace_id in self.trace_logs:
            self.trace_logs[trace_id].setdefault("events", []).append({
                "stage": stage,
                "event": event,
                "changed": changed,
                "before": before,
                "after": after
            })