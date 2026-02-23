import sys, os
# ensure workspace root is on sys.path for package imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from viral_finder.idea_graph import analyze_curiosity_and_detect_punches, build_idea_graph, select_candidate_clips, debug_print_lens

# Small fake transcript
trs = [
    {"start":0.0, "end":4.0, "text":"Most people think saving money is hard."},
    {"start":4.0, "end":7.0, "text":"But actually there's a simple trick."},
    {"start":7.0, "end":12.0, "text":"Here's the thing: automate a small transfer each week."},
    {"start":12.0, "end":16.0, "text":"I used to waste my paycheck but now I have a habit."},
    {"start":16.0, "end":20.0, "text":"So remember: small automatic rules beat big willpower."},
    {"start":20.0, "end":24.0, "text":"By the way, did you know compound interest doubles?"},
    {"start":24.0, "end":28.0, "text":"How to start: open two accounts and schedule transfers."},
]

# simple fake audio/visual signals (per-second)
aud = [{"time": t, "energy": 0.1 + (0.05 * (t%3))} for t in range(0, 30)]
vis = [{"time": t, "motion": 0.05 + (0.03 * ((t+1)%4))} for t in range(0, 30)]

print("Running analyze_curiosity_and_detect_punches...")
feats, curiosity, candidates = analyze_curiosity_and_detect_punches(trs, aud=aud, vis=vis, brain=None)
print("Feats:", len(feats))
print("Curiosity:", list(curiosity))
print("Candidates:", candidates)

print("Building idea graph with candidates...")
nodes = build_idea_graph(trs, aud=aud, vis=vis, curiosity_candidates=candidates, brain=None)
print(f"Nodes: {len(nodes)}")

print("Selecting candidate clips...")
cands = select_candidate_clips(nodes, top_k=6, transcript=trs, ensure_sentence_complete=True)
print(f"Selected: {len(cands)}")

print("Debug lens output:")
debug_print_lens(cands, transcript=trs, top_n=6)
print("SMOKE TEST COMPLETE")
