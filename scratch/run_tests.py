import sys
import os

# Add the workspace root to python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

class MonkeyPatch:
    def __init__(self):
        self.undo_list = []
    
    def setattr(self, target, name, value):
        old_val = getattr(target, name, None)
        self.undo_list.append((target, name, old_val))
        setattr(target, name, value)
        
    def setenv(self, name, value):
        old_val = os.environ.get(name)
        self.undo_list.append((os.environ, name, old_val))
        os.environ[name] = value
        
    def undo(self):
        for target, name, old_val in reversed(self.undo_list):
            if target is os.environ:
                if old_val is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = old_val
            else:
                setattr(target, name, old_val)

def run_tests():
    from tests.test_orchestrator_staged_pipeline import (
        test_staged_pipeline_reuses_cached_transcript,
        test_staged_pipeline_validation_rejects_before_rank,
        test_enrichment_budget_prioritizes_strict_candidates
    )
    
    mp = MonkeyPatch()
    try:
        print("Running: test_staged_pipeline_reuses_cached_transcript...")
        test_staged_pipeline_reuses_cached_transcript(mp)
        print("✅ Passed")
    except Exception as e:
        print(f"❌ Failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        mp.undo()

    mp = MonkeyPatch()
    try:
        print("Running: test_staged_pipeline_validation_rejects_before_rank...")
        from viral_finder import validation_gates
        mp.setattr(validation_gates, "STRICT_GATES_ENABLED", True)
        test_staged_pipeline_validation_rejects_before_rank(mp)
        print("✅ Passed")
    except Exception as e:
        print(f"❌ Failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        mp.undo()

    mp = MonkeyPatch()
    try:
        print("Running: test_enrichment_budget_prioritizes_strict_candidates...")
        test_enrichment_budget_prioritizes_strict_candidates(mp)
        print("✅ Passed")
    except Exception as e:
        print(f"❌ Failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        mp.undo()

if __name__ == "__main__":
    run_tests()
