import os, sys, json
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ['HS_TRACE_MODE'] = 'true'

import yt_dlp
from viral_finder import orchestrator

def download_video(url, output_path):
    print(f"Downloading {url} to {output_path}...")
    ydl_opts = {
        'format': 'worstvideo[ext=mp4]+worstaudio[ext=m4a]/mp4',
        'outtmpl': output_path,
        'quiet': True,
        'no_warnings': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

class DummyContext:
    def __init__(self):
        self.transcript = []
        self.raw_candidates = []
        self.hooks_suppressed = 0
        self.candidate_feature_cache = {}
        self.trace_logs = {}
        self.candidate_threads = {}
        self.curiosity_curve = []
        self.stage_stats = {}
        self.hooks_discovered = 0
        
        self.suppressed_hooks = []

    def trace_state(self, *args, **kwargs): pass
    def trace_event(self, *args, **kwargs): pass
    def trace_suppressed_child(self, trace_id, start, text, score, reason):
        self.suppressed_hooks.append({
            "trace_id": trace_id,
            "start": start,
            "text": text,
            "score": score,
            "reason": reason
        })

def run_trace():
    url = "https://youtu.be/tpDE0RJ7yoM"
    vid_path = "scratch/test_vid.mp4"
    if not os.path.exists(vid_path):
        download_video(url, vid_path)
    
    # Extract transcript
    from viral_finder.gemini_transcript_engine import extract_transcript
    print("Extracting transcript...")
    transcript = extract_transcript(vid_path)
    
    ctx = DummyContext()
    ctx.transcript = transcript
    ctx.path = vid_path
    
    # Provide a dummy get_feature_cache if needed
    import viral_finder.orchestrator
    
    print(f"Running Hook Hunter on {len(transcript)} segments...")
    viral_finder.orchestrator._run_global_hook_hunter(ctx)
    
    print("\n=============================================================")
    print(f"   PRODUCTION FORENSIC TRACE: {url} ")
    print("=============================================================")
    
    print("\n--- INJECTED CANDIDATES (SURVIVED) ---")
    injected_by_strength = sorted(ctx.raw_candidates, key=lambda x: x.get("hook_strength", 0), reverse=True)
    for c in injected_by_strength:
        print(f"Candidate ID: {c.get('id', 'unknown')}")
        print(f"Timestamp: {c['start']:>6.1f}s")
        print(f"Hook Strength: {c.get('hook_strength', 0):.2f}")
        print(f"StoryThread ID: N/A")
        print(f"Suppressed? No")
        print(f"Reason: N/A")
        print(f"Final injected? Yes")
        print("---")
        
    print("\n--- SUPPRESSED CANDIDATES (KILLED BY STORYTHREAD) ---")
    suppressed_by_strength = sorted(ctx.suppressed_hooks, key=lambda x: x["score"], reverse=True)
    for c in suppressed_by_strength:
        print(f"Candidate ID: {c.get('id', 'unknown')}")
        print(f"Timestamp: {c['start']:>6.1f}s")
        print(f"Hook Strength: {c['score']:.2f}")
        print(f"StoryThread ID: {c['trace_id'][:8]}...")
        print(f"Suppressed? Yes")
        print(f"Reason: {c['reason']}")
        print(f"Final injected? No")
        print("---")
    
    highest_injected = injected_by_strength[0] if injected_by_strength else None
    highest_suppressed = suppressed_by_strength[0] if suppressed_by_strength else None
    
    print("\n=============================================================")
    print("                    FORENSIC VERDICT                         ")
    print("=============================================================")
    print(f"Was the highest hook_strength candidate suppressed?")
    
    if highest_suppressed and highest_injected and highest_suppressed["score"] > highest_injected.get("hook_strength", 0):
        print("YES.")
        print(f"- Highest surviving hook:  Strength {highest_injected.get('hook_strength', 0):.2f} at {highest_injected['start']}s")
        print(f"- Highest suppressed hook: Strength {highest_suppressed['score']:.2f} at {highest_suppressed['start']}s")
        diff = highest_suppressed["score"] - highest_injected.get("hook_strength", 0)
        print(f"- Difference in strength:  +{diff:.2f}")
        print(f"- Which StoryThread suppressed it: Thread {highest_suppressed['trace_id']}")
        print(f"- Which line of code made the decision: orchestrator.py, line 2312 (the 'continue' after logging suppression)")
    else:
        print("NO.")
        if highest_injected:
            print(f"Highest surviving hook was {highest_injected.get('hook_strength', 0):.2f}")
        if highest_suppressed:
            print(f"Highest suppressed hook was {highest_suppressed['score']:.2f}")
        else:
            print("No hooks were suppressed by StoryThread.")

if __name__ == "__main__":
    run_trace()
