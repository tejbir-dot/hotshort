import os
import sys

# Add the project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from viral_finder.optimized_passes import OptimizedPassSelector

class DummyNode:
    def __init__(self):
        self.text = "This is a test node."
        self.start_time = 10.5
        self.end_time = 25.2
        self.semantic_quality = 0.8
        self.punch_confidence = 0.8
        self.curiosity_score = 0.8
        self.fingerprint = "dummy_fp"

def main():
    selector = OptimizedPassSelector({'quality_gate': 0.0})
    dummy_node = DummyNode()
    
    # Call _build_candidates directly
    candidates = selector._build_candidates(
        candidates=[dummy_node],
        pass_type='strict',
        thresholds={'curio_delta': 0.1, 'punch_delta': 0.1, 'semantic_floor': 0.1}
    )
    
    print("\n--- EXACT RUNTIME DICTIONARY ---")
    if candidates:
        import pprint
        pprint.pprint(candidates[0])
    else:
        print("No candidates returned.")

if __name__ == "__main__":
    main()
