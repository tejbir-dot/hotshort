import sys
import os

# Ensure the module can be imported
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from utils.narrative_intelligence import compute_payoff_resolution_score, compute_ending_strength

def mock_transcript(text):
    return [{'start': 0.0, 'end': 5.0, 'text': text, 'words': [{'word': w, 'start': 0.0, 'end': 5.0} for w in text.split()]}]

test_sentences = [
    "And the crazy part is, most businesses don't even know this exists yet.",
    "So let's start with the first idea.",
    "They don't got a bot.",
    "That's why it works.",
    "The lesson is you have to try it."
]

print("--- PAYOFF FORENSIC ANALYSIS ---")
for s in test_sentences:
    t = mock_transcript(s)
    end_score, end_break = compute_ending_strength(t, 5.0, look_s=4.0, debug=True)
    res_score, res_break = compute_payoff_resolution_score(t, 0.0, 5.0, tail_look_s=6.0, debug=True)
    
    print(f'\nText: "{s}"')
    
    end_components = ", ".join(f"{k}=+{v:.2f}" if v > 0 else f"{k}={v:.2f}" for k, v in end_break.items())
    print(f'Ending Strength:   {end_score:.2f} ({end_components})')
    
    res_components = ", ".join(f"{k}=+{v:.2f}" if v > 0 else f"{k}={v:.2f}" for k, v in res_break.items())
    print(f'Payoff Resolution: {res_score:.2f} ({res_components})')
