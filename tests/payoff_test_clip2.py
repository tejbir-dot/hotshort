from viral_finder.idea_graph import analyze_curiosity_and_detect_punches, compute_segment_features, compute_curiosity_curve
import json

# Synthetic clip designed to show curiosity peak, development, then payoff
segs = [
    {"start":0,"end":4,"text":"Did you know most people ignore this simple trick?"},
    {"start":4,"end":8,"text":"Imagine saving without thinking about it — sounds impossible, right?"},
    {"start":8,"end":12,"text":"Here's the method: round up purchases and move spare change."},
    {"start":12,"end":16,"text":"You won't feel it, and your balance grows fast."},
    {"start":16,"end":20,"text":"So remember: set it once and let compounding do the rest."},
    {"start":20,"end":24,"text":"That's why this beats trying to will yourself to save."},
]

feats, curiosity, candidates = analyze_curiosity_and_detect_punches(segs)
print('Per-seg curiosity:', [round(float(x),3) for x in curiosity])
print('\nIDEA FEATURES (per segment):')
for f in feats:
    print(f" idx={f['idx']} start={f['start']} sem_density={f['sem_density']:.3f} novelty={f['novelty']:.3f} punct={f['punct']:.3f} impact={f['impact']:.3f}")

print('\nCANDIDATES:')
print(json.dumps(candidates, indent=2))

# If candidates found, print more context
if candidates:
    for c in candidates:
        print('\nCandidate:', c)
        meta = c[2] if isinstance(c, (list, tuple)) and len(c) > 2 else (c if isinstance(c, dict) else {})
        s = meta.get('start_time', meta.get('start'))
        e = meta.get('end_time', meta.get('end'))
        print(f"Clip time: {s} - {e}")
        print(f"Payoff_time: {meta.get('payoff_time')}, payoff_conf: {meta.get('payoff_confidence')}")
