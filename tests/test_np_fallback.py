from viral_finder import idea_graph

# simulate numpy missing
idea_graph.np = None

# tiny fake feats
feats = [
    {"novelty":0.1, "meaning":0.2, "energy":0.0, "punct":0.0, "sem_density":0.3},
    {"novelty":0.3, "meaning":0.4, "energy":0.2, "punct":0.0, "sem_density":0.35},
    {"novelty":0.2, "meaning":0.3, "energy":0.1, "punct":0.0, "sem_density":0.32},
]

cur = idea_graph.compute_curiosity_curve(feats, window=2)
print('curiosity (fallback):', cur)
assert isinstance(cur, list)
assert len(cur) == len(feats)
print('np fallback test passed')
