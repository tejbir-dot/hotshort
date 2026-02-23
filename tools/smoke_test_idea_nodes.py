import json
import sys
import os

# ensure project root is importable
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from viral_finder.idea_graph import build_idea_graph

# load cached transcript
p = 'cache_transcript_s5r4wdOWLjk.json'
with open(p, 'r', encoding='utf-8') as f:
    trs = json.load(f)

nodes = build_idea_graph(trs)

out = []
for idx, n in enumerate(nodes):
    out.append({
        "id": n.fingerprint,
        "index": idx,
        "start": n.start_time,
        "end": n.end_time,
        "label": n.state,
        "curiosity": n.curiosity_score,
        "punch": n.punch_confidence,
        "semantic_density": n.semantic_quality
    })

print(json.dumps(out, indent=2))
