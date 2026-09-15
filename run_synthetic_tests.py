import csv
import math
import numpy as np
from viral_finder.delta_math import fuse_scores, audio_delta, rolling_zscore, cosine_distance

def legacy_score(semantic_avg, punch_avg, curiosity_avg):
    return (0.28 * semantic_avg) + (0.22 * punch_avg) + (0.18 * curiosity_avg)

scenarios = []

# Scenario 1: Scream -> instant dead silence, mid-sentence
rms = [0.1, 0.1, 0.9, 0.01, 0.01]
ad_max = max(abs(d) for d in audio_delta(rms))
rms_avg = sum(rms)/len(rms)
scenarios.append({
    "id": 1,
    "scenario": "Scream -> instant dead silence",
    "legacy_score": round(legacy_score(semantic_avg=0.5, punch_avg=rms_avg, curiosity_avg=0.2), 3),
    "new_score": round(fuse_scores(semantic_delta=0.5, audio_delta=ad_max, visual_delta=0.1), 3)
})

# Scenario 2: Monotone narration
rms = [0.4, 0.4, 0.4, 0.4, 0.4]
ad_max = max(abs(d) for d in audio_delta(rms))
rms_avg = sum(rms)/len(rms)
scenarios.append({
    "id": 2,
    "scenario": "Monotone narration",
    "legacy_score": round(legacy_score(semantic_avg=0.4, punch_avg=rms_avg, curiosity_avg=0.0), 3),
    "new_score": round(fuse_scores(semantic_delta=0.1, audio_delta=ad_max, visual_delta=0.1), 3)
})

# Scenario 3: Visual-only spike
scenarios.append({
    "id": 3,
    "scenario": "Visual-only spike",
    "legacy_score": round(legacy_score(semantic_avg=0.2, punch_avg=0.2, curiosity_avg=0.1), 3),
    "new_score": round(fuse_scores(semantic_delta=0.1, audio_delta=0.1, visual_delta=0.9), 3)
})

# Scenario 4: Loud music/noise spike
rms = [0.9, 0.9, 0.9, 0.9]
ad_max = max(abs(d) for d in audio_delta(rms))
rms_avg = sum(rms)/len(rms)
scenarios.append({
    "id": 4,
    "scenario": "Loud music/noise spike",
    "legacy_score": round(legacy_score(semantic_avg=0.1, punch_avg=rms_avg, curiosity_avg=0.1), 3),
    "new_score": round(fuse_scores(semantic_delta=0.1, audio_delta=ad_max, visual_delta=0.1), 3)
})

# Scenario 5: Sarcasm (tonal shift only)
rms = [0.3, 0.3, 0.8, 0.8]
ad_max = max(abs(d) for d in audio_delta(rms))
scenarios.append({
    "id": 5,
    "scenario": "Sarcasm (tonal shift only)",
    "legacy_score": round(legacy_score(semantic_avg=0.1, punch_avg=0.2, curiosity_avg=0.0), 3),
    "new_score": round(fuse_scores(semantic_delta=0.1, audio_delta=ad_max, visual_delta=0.1), 3)
})

# Scenario 6: Non-English clip
scenarios.append({
    "id": 6,
    "scenario": "Non-English clip",
    "legacy_score": 0.0,
    "new_score": round(fuse_scores(semantic_delta=0.8, audio_delta=0.8, visual_delta=0.5), 3)
})

# Scenario 7: All-zero / empty audio track
rms = [0.0, 0.0, 0.0]
ad_max = max(abs(d) for d in audio_delta(rms))
scenarios.append({
    "id": 7,
    "scenario": "All-zero audio track",
    "legacy_score": round(legacy_score(semantic_avg=0.0, punch_avg=0.0, curiosity_avg=0.0), 3),
    "new_score": round(fuse_scores(semantic_delta=0.0, audio_delta=ad_max, visual_delta=0.0), 3)
})

with open('synthetic_edge_case_results.csv', 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=["id", "scenario", "legacy_score", "new_score"])
    writer.writeheader()
    writer.writerows(scenarios)

print("Synthetic edge cases written to synthetic_edge_case_results.csv")
for s in scenarios:
    print(f"[{s['id']}] {s['scenario'][:30]:<30} | Legacy: {s['legacy_score']:.3f} | New: {s['new_score']:.3f}")
