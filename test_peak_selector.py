import json
from viral_finder.peak_selector import PeakSelector

class MockStoryThread:
    def __init__(self, hook_text, start_s, trace_id):
        self.hook_text = hook_text
        self.start_s = start_s
        self.trace_id = trace_id
        
    def is_expired(self, start_s, horizon):
        return (start_s - self.start_s) > horizon
        
    def does_segment_continue(self, text, compute_bonus, threshold):
        # Mock logic: same topic if words overlap
        w1 = set(self.hook_text.lower().split())
        w2 = set(text.lower().split())
        overlap = len(w1.intersection(w2))
        return 0.8 if overlap > 0 else 0.0
        
    def __repr__(self):
        return f"<MockStoryThread '{self.hook_text[:20]}...'>"

# 3 hooks, the first two are in the same narrative cluster (overlap in words)
hooks = [
    {"start": 10.0, "text": "The secret to AI is data.", "hook_strength": 0.6, "trace_id": "t1"},
    {"start": 12.0, "text": "Because without data, AI is nothing.", "hook_strength": 0.9, "trace_id": "t2"}, # Stronger, same arc
    {"start": 40.0, "text": "Let's talk about hardware now.", "hook_strength": 0.5, "trace_id": "t3"}  # Different arc
]

def run_test():
    selector = PeakSelector()
    for h in hooks:
        selector.collect_candidate(h)
        
    def cluster_fn(cand, state):
        if state.is_expired(cand["start"], 30.0):
            return False
        return state.does_segment_continue(cand["text"], False, 0.5) >= 0.5
        
    def create_state_fn(cand):
        return MockStoryThread(hook_text=cand["text"], start_s=cand["start"], trace_id=cand["trace_id"])
        
    def score_fn(cand):
        return float(cand["hook_strength"])
        
    suppressed = []
    
    def publish_fn(winner, losers, state):
        suppressed.extend(losers)
        print(f"✅ Published Peak: strength={winner['hook_strength']}, text='{winner['text']}'")
        if losers:
            print(f"   -> Suppressed {len(losers)} weaker competitors in this cluster.")
        return winner
        
    winners = selector.execute(cluster_fn, create_state_fn, score_fn, publish_fn)
    
    print("\n--- Summary ---")
    print(f"Original Hooks: {len(hooks)}")
    print(f"Final Published Peaks: {len(winners)}")
    print(f"Suppressed Candidates: {len(suppressed)}")
    
    assert len(winners) == 2
    assert winners[0]["hook_strength"] == 0.9
    assert len(suppressed) == 1

if __name__ == "__main__":
    run_test()
