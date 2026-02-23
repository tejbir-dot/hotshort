import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from viral_finder.idea_graph import analyze_curiosity_and_detect_punches, build_idea_graph, select_candidate_clips, debug_print_lens, plot_curiosity_curve

# simple fake transcript (same as smoke test)
trs = [
    {"start":0.0, "end":4.0, "text":"Most people think saving money is hard."},
    {"start":4.0, "end":7.0, "text":"But actually there's a simple trick."},
    {"start":7.0, "end":12.0, "text":"Here's the thing: automate a small transfer each week."},
    {"start":12.0, "end":16.0, "text":"I used to waste my paycheck but now I have a habit."},
    {"start":16.0, "end":20.0, "text":"So remember: small automatic rules beat big willpower."},
    {"start":20.0, "end":24.0, "text":"By the way, did you know compound interest doubles?"},
    {"start":24.0, "end":28.0, "text":"How to start: open two accounts and schedule transfers."},
]

aud = [{"time": t, "energy": 0.1 + (0.05 * (t%3))} for t in range(0, 30)]
vis = [{"time": t, "motion": 0.05 + (0.03 * ((t+1)%4))} for t in range(0, 30)]

# grid to sweep
slopes = [0.04, 0.06, 0.08, 0.12]
drops = [0.35, 0.45, 0.55]

results = []
for s in slopes:
    for d in drops:
        feats, curiosity, candidates = analyze_curiosity_and_detect_punches(trs, aud=aud, vis=vis, brain=None, ignition_min_slope=s, drop_ratio=d)
        nodes = build_idea_graph(trs, aud=aud, vis=vis, curiosity_candidates=candidates, brain=None)
        cands = select_candidate_clips(nodes, top_k=6, transcript=trs, ensure_sentence_complete=True)
        # metrics: number of candidates, avg curiosity_peak
        num = len(candidates)
        avg_peak = 0.0
        if candidates:
            avg_peak = sum((m[2].get('curiosity_peak',0.0) for m in candidates))/len(candidates)
        # store
        results.append((s,d,num,avg_peak,len(cands)))
        print(f"slope={s} drop={d} -> detected={num} avg_peak={avg_peak:.3f} selected={len(cands)}")

# print summary
print('\nSUMMARY')
for r in results:
    print(f"slope={r[0]} drop={r[1]} detected={r[2]} avg_peak={r[3]:.3f} selected={r[4]}")

# also dump curve for one chosen setting
feats, curiosity, candidates = analyze_curiosity_and_detect_punches(trs, aud=aud, vis=vis, brain=None, ignition_min_slope=0.08, drop_ratio=0.45)
print('\nCuriosity curve:')
plot_curiosity_curve(curiosity, feats=feats)

print('\nDone')
