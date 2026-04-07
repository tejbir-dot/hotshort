#!/usr/bin/env python3
"""
Simple test to verify optimized_passes module works
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from viral_finder.optimized_passes import OptimizedPassSelector, select_candidates_optimized
    print("✅ Import successful!")

    # Create a simple test
    selector = OptimizedPassSelector({'parallel': True, 'early_termination': True, 'adaptive_relaxation': True})
    print("✅ OptimizedPassSelector created!")

    # Test with empty candidates
    candidates, metrics = selector.select_candidates_optimized([], 6)
    print(f"✅ Test run successful! Got {len(candidates)} candidates")

    print("🎉 All tests passed!")

except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)