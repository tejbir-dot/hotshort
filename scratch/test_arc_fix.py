#!/usr/bin/env python3
"""
Before/After test for TIER3 arc_complete fix.
Runs pipeline on same transcript, logs to file.
"""
import os
import sys
import json
import logging
from io import StringIO

# Setup environment for v2 pipeline
os.environ['HS_EXPERIMENT_MODE'] = '1'
os.environ['HS_TRACE_MODE'] = 'true'
os.environ['HS_UNLIMITED_MODE'] = '1'

sys.path.insert(0, ".")

# Load cached transcript
TRANSCRIPT_PATH = r"c:\Users\n\Documents\hotshort\.hotshort_transcripts_cache\17391602f63bf04260926df9bdf4e0330c24060b.json"
with open(TRANSCRIPT_PATH, "r", encoding="utf-8") as f:
    TRANSCRIPT = json.load(f)

# Capture all logging to file and console
log_output = StringIO()
log_file = None

def setup_logging(filename):
    """Setup logging to both file and console"""
    global log_file
    log_file = open(filename, "w", encoding="utf-8")
    
    # Configure root logger
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    
    # Remove existing handlers
    for h in root.handlers[:]:
        root.removeHandler(h)
    
    # File handler
    fh = logging.FileHandler(filename, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter('%(message)s'))
    root.addHandler(fh)
    
    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))
    root.addHandler(ch)

def run_pipeline():
    """Run the arc assembler pipeline"""
    from viral_finder import orchestrator
    
    # Mock transcript loading and audio/visual analysis
    orchestrator._load_cached_transcript = lambda _p: TRANSCRIPT
    orchestrator._save_cached_transcript = lambda _p, _s: None
    orchestrator.analyze_audio = lambda _p: [{"time": float(i*4), "energy": 0.5} for i in range(len(TRANSCRIPT))]
    orchestrator.analyze_visual = lambda _p: [{"time": float(i*4), "motion": 0.4} for i in range(len(TRANSCRIPT))]
    orchestrator._ensure_brain_runtime_loaded = lambda: None
    orchestrator._brain_import_ok = False
    
    # Run the pipeline - use a fake URL, mocks will handle it
    try:
        clips = orchestrator.orchestrate(
            youtube_url="https://www.youtube.com/watch?v=test",
            top_k=8,
            prefer_gpu=False,
            use_cache=False,
            allow_fallback=False,
            pipeline_mode="staged",
        )
        
        log = logging.getLogger("test")
        log.info(f"\n[PIPELINE_COMPLETE] Returned {len(clips or [])} clips")
        
        # Log clip details
        for i, clip in enumerate(clips or []):
            cid = clip.get("cid") or clip.get("id") or f"clip_{i}"
            arc_score = clip.get("arc_score", "N/A")
            start = clip.get("start", 0)
            end = clip.get("end", 0)
            log.info(f"  Clip {i}: {cid} | arc_score={arc_score} | {start:.1f}s-{end:.1f}s")
        
        return clips
        
    except Exception as e:
        log = logging.getLogger("test")
        log.error(f"Pipeline failed: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python test_arc_fix.py <output_log_file>")
        sys.exit(1)
    
    output_file = sys.argv[1]
    
    print(f"[TEST] Running pipeline, output to {output_file}")
    print(f"[TEST] HS_EXPERIMENT_MODE={os.environ.get('HS_EXPERIMENT_MODE')}")
    
    setup_logging(output_file)
    
    try:
        clips = run_pipeline()
        print(f"[TEST] ✓ Pipeline completed, {len(clips or [])} clips returned")
        print(f"[TEST] ✓ Log written to {output_file}")
    finally:
        if log_file:
            log_file.close()
