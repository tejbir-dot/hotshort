from viral_finder.idea_graph import analyze_curiosity_and_detect_punches
import json

segs = [
    {"start":0,"end":6,"text":"Most people think saving money is hard. But actually there's a simple trick."},
    {"start":6,"end":12,"text":"Here's the thing: automate a small transfer each week."},
    {"start":12,"end":18,"text":"I used to waste my paycheck but now I have a habit."},
    {"start":18,"end":26,"text":"So remember: small automatic rules beat big willpower."},
    {"start":26,"end":32,"text":"By the way, did you know compound interest doubles?"},
    {"start":32,"end":38,"text":"How to start: open two accounts and schedule transfers."},
]

feats, curiosity, candidates = analyze_curiosity_and_detect_punches(segs)
print('FEAT_COUNT:', len(feats))
print('CURIOSITY:', [round(float(x),3) for x in curiosity])
print('\nCANDIDATES:')
print(json.dumps(candidates, indent=2))
