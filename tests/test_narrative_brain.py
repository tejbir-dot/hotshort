import pytest
from editing_intelligence.narrative_brain import NarrativeBrain

def test_narrative_brain_mock_generation():
    transcript = [
        {"start": 0.0, "end": 1.5, "text": "This is a hook"},
        {"start": 1.5, "end": 5.0, "text": "Here is the build up"},
        {"start": 5.0, "end": 6.0, "text": "And the payoff"}
    ]
    brain = NarrativeBrain(transcript=transcript)
    
    block = brain.generate_blueprint_block()
    
    assert block.archetype == "educational_linear"
    assert block.pace_profile == "steady_educational"
    assert block.hook_window.start == 0.0
    assert block.hook_window.end == 1.5 or block.hook_window.end <= 4.0
    assert block.payoff_window.start >= 1.0
    assert block.payoff_window.end == 6.0
