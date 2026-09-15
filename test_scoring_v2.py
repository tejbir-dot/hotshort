import sys
import os
import copy

# Ensure the module can be imported
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from utils.narrative_intelligence import compute_payoff_resolution_score, compute_ending_strength

def mock_transcript(text):
    return [{'start': 0.0, 'end': 5.0, 'text': text, 'words': [{'word': w, 'start': 0.0, 'end': 5.0} for w in text.split()]}]

# You can add more real offenders from the logs here
test_sentences = [
    "the third lives and the fourth lives.",
    "That's just the math.",
    "And the reality is that if you can commit...",
    "And the crazy part is, most businesses don't even know this exists yet.",
    "So let's start with the first idea.",
    "They don't got a bot.",
    "That's why it works.",
    "The lesson is you have to try it.",
    "Here's the thing, it's not even hard.",
    "You want to know the crazy part?",
    "But then...",
    "And that's when everything changed."
]

print("=======================================")
print(" OLD SCORER VS NEW SCORER (V2) ")
print("=======================================\n")

for s in test_sentences:
    t = mock_transcript(s)
    
    # 1. Old Scorer
    os.environ["HS_PAYOFF_SCORE_FIX_V2"] = "0"
    end_old, end_b_old = compute_ending_strength(t, 5.0, look_s=4.0, debug=True)
    res_old, res_b_old = compute_payoff_resolution_score(t, 0.0, 5.0, tail_look_s=6.0, debug=True)
    legacy_old = (end_old + res_old) / 2.0
    
    # 2. New Scorer
    os.environ["HS_PAYOFF_SCORE_FIX_V2"] = "1"
    end_new, end_b_new = compute_ending_strength(t, 5.0, look_s=4.0, debug=True)
    res_new, res_b_new = compute_payoff_resolution_score(t, 0.0, 5.0, tail_look_s=6.0, debug=True)
    legacy_new = (end_new + res_new) / 2.0
    
    print(f'Text: "{s}"')
    
    print(f"OLD:")
    print(f"  Total: {legacy_old:.2f} (Ending: {end_old:.2f}, Resolution: {res_old:.2f})")
    
    print(f"NEW:")
    print(f"  Total: {legacy_new:.2f} (Ending: {end_new:.2f}, Resolution: {res_new:.2f})")
    
    # Print the specific telemetry we injected for V2
    if res_b_new.get("DEBUG_answerish_match"):
        print(f"  [DEBUG] Answerish Match: '{res_b_new['DEBUG_answerish_match']}'")
    if res_b_new.get("DEBUG_setup_question_reason"):
        print(f"  [DEBUG] Setup Question Reason: '{res_b_new['DEBUG_setup_question_reason']}'")
    if res_b_new.get("DEBUG_advice_match"):
        print(f"  [DEBUG] Advice Match: '{res_b_new['DEBUG_advice_match']}'")
    
    diff = legacy_new - legacy_old
    if diff < 0:
        print(f"  Diff: {diff:.2f} - (Dropped)")
    elif diff > 0:
        print(f"  Diff: {diff:.2f} + (Increased)")
    else:
        print(f"  Diff: {diff:.2f} = (Unchanged)")
        
    print("-" * 40)
