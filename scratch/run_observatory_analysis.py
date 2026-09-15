import os
import sys
import json
import logging

# Configure Environment Variables
os.environ['HS_TRACE_MODE'] = 'true'
os.environ['HS_HOOK_HUNTER_DEBUG'] = '1'
os.environ['HS_EXPERIMENT_MODE'] = '1'

# Insert root to path
sys.path.insert(0, ".")

# Output log file path
log_file_path = r"c:\Users\n\Documents\hotshort\scratch\observatory_final.log"

# Setup file logger
logger = logging.getLogger()
logger.setLevel(logging.INFO)
# Clear existing handlers
for h in list(logger.handlers):
    logger.removeHandler(h)

file_handler = logging.FileHandler(log_file_path, mode='w', encoding='utf-8')
file_handler.setFormatter(logging.Formatter("%(message)s"))
logger.addHandler(file_handler)

# Also redirect sys.stdout and sys.stderr to the same file
class FileRedirector:
    def __init__(self, filepath):
        self.file = open(filepath, 'a', encoding='utf-8')
    def write(self, data):
        self.file.write(data)
        self.file.flush()
    def flush(self):
        self.file.flush()

redirector = FileRedirector(log_file_path)
# Save originals
orig_stdout = sys.stdout
orig_stderr = sys.stderr

sys.stdout = redirector
sys.stderr = redirector

from viral_finder import orchestrator

# Load the target real transcript
transcript_path = r"c:\Users\n\Documents\hotshort\.hotshort_transcripts_cache\17391602f63bf04260926df9bdf4e0330c24060b.json"
with open(transcript_path, "r", encoding="utf-8") as f:
    transcript = json.load(f)

# Mock external dependencies & caching to avoid transcription/GPU checks
class MonkeyPatch:
    def __init__(self):
        self.originals = {}
    def patch(self, obj, attr, value):
        self.originals[(obj, attr)] = getattr(obj, attr)
        setattr(obj, attr, value)
    def undo(self):
        for (obj, attr), val in self.originals.items():
            setattr(obj, attr, val)

mp = MonkeyPatch()
mp.patch(orchestrator, "_load_cached_transcript", lambda _p: transcript)
mp.patch(orchestrator, "_save_cached_transcript", lambda _p, _s: None)
mp.patch(orchestrator, "analyze_audio", lambda _p: [{"time": float(idx * 4), "energy": 0.5} for idx in range(len(transcript))])
mp.patch(orchestrator, "analyze_visual", lambda _p: [{"time": float(idx * 4), "motion": 0.4} for idx in range(len(transcript))])
mp.patch(orchestrator, "_ensure_brain_runtime_loaded", lambda: None)
mp.patch(orchestrator, "_brain_import_ok", False)

try:
    print("=" * 70)
    print("RUNNING NARRATIVE OBSERVATORY ON REAL TRANSCRIPT")
    print("=" * 70)
    
    # Run Staged Pipeline
    results = orchestrator.orchestrate(
        path="dummy.mp4",
        top_k=8,
        pipeline_mode="staged",
        allow_fallback=False
    )
    
    print("=" * 70)
    print(f"PIPELINE COMPLETED. FOUND {len(results)} FINAL CLIPS.")
    print("=" * 70)

finally:
    mp.undo()
    sys.stdout = orig_stdout
    sys.stderr = orig_stderr
    redirector.file.close()
