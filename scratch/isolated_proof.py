import os

# --- Dummy Transcript and Scores ---
# We simulate a transcript where the first acceptable hook is weak,
# and a subsequent hook in the same arc is incredibly strong.
transcript = [
    {"start": 0.0, "end": 5.0, "text": "Hi everyone."},
    {"start": 5.0, "end": 10.0, "text": "I'm going to share a small tip."}, # Weak hook (0.46)
    {"start": 10.0, "end": 15.0, "text": "This is the most insane secret that nobody knows about!"}, # Strong hook (0.95)
    {"start": 15.0, "end": 20.0, "text": "It will literally double your income overnight."}, # Decent hook (0.75)
    {"start": 20.0, "end": 25.0, "text": "So let's get into the details."},
]

def mock_compute_quality_scores(s, e):
    if s == 5.0: return {"hook_score": 0.46, "pattern_break_score": 0.3}
    if s == 10.0: return {"hook_score": 0.95, "pattern_break_score": 0.9}
    if s == 15.0: return {"hook_score": 0.75, "pattern_break_score": 0.6}
    return {"hook_score": 0.1, "pattern_break_score": 0.1}

# --- Dummy StoryThread ---
class DummyStoryThread:
    def __init__(self, hook_text, start_s, trace_id):
        self.hook_text = hook_text
        self.start_s = start_s
        self.trace_id = trace_id
        
    def is_expired(self, current_time, horizon):
        return (current_time - self.start_s) > horizon

    def does_segment_continue(self, text, bonus, threshold):
        # We simulate that the 10s and 15s segments continue the 5s arc
        return 0.99 

def _clamp01(x): return max(0.0, min(1.0, float(x)))

def run_hook_hunter(with_story_thread: bool):
    hooks = []
    active_story_threads = []
    _arc_horizon_s = 120.0
    _story_continuity_threshold = 0.30
    _susp_thread_by_trace = {}

    for idx, seg in enumerate(transcript):
        seg_start = seg["start"]
        seg_end = seg["end"]
        seg_text = seg["text"]
        
        scores = mock_compute_quality_scores(seg_start, seg_end)
        hook_score = scores["hook_score"]
        pattern_break = scores["pattern_break_score"]
        hook_strength = _clamp01((0.35 * hook_score) + (0.25 * pattern_break)) # simplified
        
        if hook_strength > 0.15: # threshold
            
            _continuing_existing_arc = False
            _continuity_thread = None
            _continuity_score = 0.0
            
            if with_story_thread and active_story_threads:
                # Classification pass (Current Logic)
                _active_next = []
                for t in active_story_threads:
                    if not t.is_expired(seg_start, _arc_horizon_s):
                        _active_next.append(t)
                active_story_threads = _active_next
                
                for _thread in active_story_threads:
                    _continuity = _thread.does_segment_continue(seg_text, True, _story_continuity_threshold)
                    if _continuity >= _story_continuity_threshold:
                        _continuing_existing_arc = True
                        _continuity_thread = _thread
                        _continuity_score = _continuity
                        break

            # Discovery pass
            trace_id = f"trace_{idx}"
            payload = {
                "id": f"c_00{idx}",
                "start": seg_start,
                "end": seg_end,
                "text": seg_text,
                "hook_strength": hook_strength,
                "trace_id": trace_id,
                "story_duplicate": bool(_continuing_existing_arc)
            }
            hooks.append(payload)
            
            if _continuing_existing_arc and _continuity_thread is not None:
                _susp_thread_by_trace[trace_id] = (_continuity_thread, _continuity_score, seg_start, seg_text, hook_strength)
            
            if with_story_thread and not _continuing_existing_arc:
                active_story_threads.append(DummyStoryThread(seg_text, seg_start, trace_id))

    # Dedup/Ranking Stage
    hooks = sorted(hooks, key=lambda x: x["hook_strength"], reverse=True)
    final_hooks = []
    
    for hook in hooks:
        if with_story_thread and hook.get("story_duplicate"):
            _susp = _susp_thread_by_trace.get(hook["trace_id"])
            if _susp:
                reason = f"Suppressed: Continues thread starting at {_susp[0].start_s}s (continuity_score={_susp[1]})"
                hook["suppression_reason"] = reason
            continue # SUPPRESSED
            
        final_hooks.append(hook)
        
    return hooks, final_hooks


if __name__ == "__main__":
    print("="*60)
    print("FORENSIC EXPERIMENT: HOOK HUNTER WITH VS WITHOUT STORY THREAD")
    print("="*60)
    
    print("\n1. WITH STORY THREAD (Current Buggy Logic)")
    all_hooks, final_hooks = run_hook_hunter(with_story_thread=True)
    for h in all_hooks:
        status = "INJECTED (SURVIVED)" if h in final_hooks else h.get("suppression_reason", "SUPPRESSED")
        print(f"[{h['id']}] Start: {h['start']:>4}s | Strength: {h['hook_strength']:.2f} | Status: {status}")
        
    print("\n2. WITHOUT STORY THREAD (Proposed Revert)")
    all_hooks2, final_hooks2 = run_hook_hunter(with_story_thread=False)
    for h in all_hooks2:
        status = "INJECTED (SURVIVED)" if h in final_hooks2 else h.get("suppression_reason", "SUPPRESSED")
        print(f"[{h['id']}] Start: {h['start']:>4}s | Strength: {h['hook_strength']:.2f} | Status: {status}")
