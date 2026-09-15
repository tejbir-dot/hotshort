#!/usr/bin/env python3
"""
Simple test runner for before/after comparison.
Runs behavioral_experiment's core pipeline and logs all output.
"""
import os, sys, json, logging

# Setup environment for v2 pipeline
os.environ['HS_TRACE_MODE'] = 'true'
os.environ['HS_EXPERIMENT_MODE'] = '1'
os.environ['HS_UNLIMITED_MODE'] = '1'

sys.path.insert(0, ".")

TRANSCRIPT_PATH = r"c:\Users\n\Documents\hotshort\.hotshort_transcripts_cache\17391602f63bf04260926df9bdf4e0330c24060b.json"

with open(TRANSCRIPT_PATH, "r", encoding="utf-8") as f:
    TRANSCRIPT = json.load(f)

# Setup logging to file
log_file = sys.argv[1] if len(sys.argv) > 1 else "observatory_test.log"
logging.basicConfig(
    level=logging.DEBUG,
    format='%(message)s',
    handlers=[
        logging.FileHandler(log_file, mode='w', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

log = logging.getLogger("test")

log.info("[START] Running pipeline...")
log.info(f"[ENV] HS_EXPERIMENT_MODE={os.environ.get('HS_EXPERIMENT_MODE')}")

from viral_finder import orchestrator

# Mocks from behavioral_experiment.py
orchestrator._load_cached_transcript = lambda _p: TRANSCRIPT
orchestrator._save_cached_transcript = lambda _p, _s: None
orchestrator.analyze_audio = lambda _p: [{"time": float(i*4), "energy": 0.5} for i in range(len(TRANSCRIPT))]
orchestrator.analyze_visual = lambda _p: [{"time": float(i*4), "motion": 0.4} for i in range(len(TRANSCRIPT))]
orchestrator._ensure_brain_runtime_loaded = lambda: None
orchestrator._brain_import_ok = False

try:
    log.info("[EXEC] Calling orchestrate...")
    clips = orchestrator.orchestrate(
        path="dummy.mp4",
        top_k=8,
        prefer_gpu=False,
        use_cache=True,  # Must be True to use cached transcript mock
        allow_fallback=False,
        pipeline_mode="staged",
    )
    
    log.info(f"[SUCCESS] Pipeline returned {len(clips or [])} clips\n")
    
    # Log each clip's key metrics
    for i, c in enumerate(clips or []):
        cid = c.get("cid") or c.get("id") or f"clip_{i}"
        arc_score = c.get("arc_score", "N/A")
        payoff_source = c.get("payoff_source", "N/A")
        payoff_score = c.get("payoff_engine_score", "N/A")
        start = c.get("start", 0)
        end = c.get("end", 0)
        log.info(
            f"[CLIP_{i}] id={cid} | arc_score={arc_score} | "
            f"payoff_source={payoff_source} | payoff_score={payoff_score} | "
            f"duration={float(end)-float(start):.1f}s"
        )
    
    log.info(f"\n[DONE] Output logged to {log_file}")
    
except Exception as e:
    log.error(f"[ERROR] Pipeline failed: {e}", exc_info=True)
    sys.exit(1)
