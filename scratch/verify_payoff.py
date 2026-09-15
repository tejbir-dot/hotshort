import os, sys, json, logging
sys.path.insert(0, ".")
os.environ["HS_GROQ_CORTEX_ENABLED"] = "0"
os.environ["HS_TRACE_MODE"] = "true"

from viral_finder.orchestrator import orchestrate

if not os.path.exists("s5r4wdOWLjk.mp4"):
    with open("s5r4wdOWLjk.mp4", "w") as f:
        f.write("dummy")

print("Running orchestrator...")
clips = orchestrate("s5r4wdOWLjk.mp4", top_k=10, use_cache=True, allow_fallback=True, pipeline_mode="staged")

for c in clips:
    if isinstance(c, dict):
        engine_score = c.get("payoff_engine_score", 0.0)
        arc_score = c.get("arc_score", 0.0)
        print(f"Cand {c.get('cid', c.get('id', 'unk'))} | Engine: {engine_score:.2f} | Arc: {arc_score:.2f}")
