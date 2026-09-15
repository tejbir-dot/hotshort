import os
from viral_finder.groq_cortex import review_candidates_with_groq

# Ensure Groq is enabled
os.environ["HS_GROQ_CORTEX_ENABLED"] = "1"

# Mock transcript (simplified)
full_transcript = [
    {"start": 0.0, "end": 5.0, "text": "Hook sentence here."},
    {"start": 5.0, "end": 10.0, "text": "Some build content that raises curiosity."},
    {"start": 10.0, "end": 15.0, "text": "Payoff sentence that resolves the hook."},
]

# Mock candidates (two simple clips)
candidates = [
    {"id": "c1", "start": 0.0, "end": 5.0, "text": "Hook sentence here."},
    {"id": "c2", "start": 5.0, "end": 15.0, "text": "Some build content that raises curiosity. Payoff sentence that resolves the hook."},
]

# Run Groq Cortex review (will hit the real API if key is set, otherwise fallback)
result = review_candidates_with_groq(candidates, full_transcript)
print("=== Review Result ===")
print(result)
