import sys
sys.path.insert(0, ".")
from utils.payoff_resolver import PayoffResolver, tier1_structural_score

# Simulate the real symptom: a valid payoff with NO closure keywords
segments = [
    {"start": 0.0,  "end": 2.5,  "text": "If you want to make real money these are the four things."},
    {"start": 2.5,  "end": 5.0,  "text": "Most people never talk about this."},
    {"start": 5.0,  "end": 8.0,  "text": "First you need to track your time relentlessly every single day."},
    {"start": 8.0,  "end": 11.0, "text": "Second remove all the distractions from your environment completely."},
    {"start": 11.0, "end": 14.0, "text": "Third focus only on the single bottleneck."},
    {"start": 14.0, "end": 18.0, "text": "And fourth act like the person you want to become before you become them."},
    {"start": 19.5, "end": 21.0, "text": "And that is it."},  # gap=1.5s after prev — silence signal
    {"start": 21.5, "end": 24.0, "text": "Now let me tell you about book number two."},  # topic shift
]

print("--- TIER 1 SCORES ---")
for i, seg in enumerate(segments):
    t1 = tier1_structural_score(segments, i, hook_start_s=0.0)
    print(f'  [{i}] t1={t1:.2f}  "{seg["text"][:55]}"')

print()

resolver = PayoffResolver()
result = resolver.find(
    hook_text="If you want to make real money these are the four things.",
    hook_start_s=0.0,
    candidate_window=[{**s, "idx": i} for i, s in enumerate(segments)],
    full_transcript=segments,
    thread_id="test_001",
)

if result:
    print(f"WINNER -> Tier {result['tier']}")
    print(f"Text: {result['text']}")
    print(f"end={result['end']}s")
else:
    print("NO WINNER FOUND")
