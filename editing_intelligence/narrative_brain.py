from typing import List, Dict, Any, Optional
from .schema import NarrativeBlock, TimeWindow

class NarrativeBrain:
    """
    Narrative Brain (Structural Intelligence)
    Maps the semantic layout of the clip, identifying the hook, development steps, and final payoff.
    """

    def __init__(self, transcript: List[Dict[str, Any]], topic_embeddings: Optional[Any] = None, narrative_triggers: Optional[List[Dict[str, Any]]] = None):
        self.transcript = transcript
        self.topic_embeddings = topic_embeddings
        self.narrative_triggers = narrative_triggers or []

    def analyze_structure(self) -> str:
        """
        Locates the transition between the Hook and Build. 
        Returns an archetype identifier.
        """
        # TODO: Implement actual semantic layout mapping logic
        if not self.transcript:
            return "unknown"
            
        # Example naive heuristic:
        return "contradiction_reversal" if self.narrative_triggers else "educational_linear"

    def identify_payoff(self) -> TimeWindow:
        """
        Identifies the logical end of the clip.
        Returns the payoff window.
        """
        # TODO: Implement actual payoff detection
        if not self.transcript:
            return TimeWindow(start=0.0, end=0.0)
            
        last_seg = self.transcript[-1]
        start_time = float(last_seg.get("start", 0.0))
        end_time = float(last_seg.get("end", start_time + 1.0))
        # Arbitrarily pick the last few seconds as payoff
        payoff_start = max(0.0, end_time - min(5.0, end_time - start_time))
        
        return TimeWindow(start=payoff_start, end=end_time)

    def identify_hook(self) -> TimeWindow:
        """
        Identifies the hook window.
        """
        if not self.transcript:
            return TimeWindow(start=0.0, end=0.0)
            
        first_seg = self.transcript[0]
        start_time = float(first_seg.get("start", 0.0))
        end_time = float(first_seg.get("end", start_time + 2.0))
        
        hook_end = min(end_time, start_time + 4.0)
        return TimeWindow(start=start_time, end=hook_end)

    def determine_pace_profile(self) -> str:
        """
        Determines the pace profile based on transcript and triggers.
        """
        return "high_dynamic" if len(self.transcript) > 10 else "steady_educational"

    def generate_blueprint_block(self) -> NarrativeBlock:
        """
        Populates the narrative metadata block to coordinate speed ramping, zoom triggers, and caption sizes.
        """
        archetype = self.analyze_structure()
        pace_profile = self.determine_pace_profile()
        hook_window = self.identify_hook()
        payoff_window = self.identify_payoff()

        return NarrativeBlock(
            archetype=archetype,
            pace_profile=pace_profile,
            hook_window=hook_window,
            payoff_window=payoff_window
        )
