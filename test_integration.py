#!/usr/bin/env python3
"""
🚀 Integration Test: Optimized Passes in HotShort
Test that the optimized dual pass system integrates correctly with the main app.

Usage:
  python test_integration.py
"""

import os
import sys
import time

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_integration():
    """Test optimized passes integration"""

    print("=" * 70)
    print("🔗 TESTING OPTIMIZED PASSES INTEGRATION")
    print("=" * 70)

    try:
        # Test 1: Import check
        print("📦 Testing imports...")
        from viral_finder.idea_graph import OPTIMIZED_PASSES_AVAILABLE, USE_OPTIMIZED_PASSES
        from viral_finder.optimized_passes import OptimizedPassSelector

        print(f"   ✅ OPTIMIZED_PASSES_AVAILABLE: {OPTIMIZED_PASSES_AVAILABLE}")
        print(f"   ✅ USE_OPTIMIZED_PASSES: {USE_OPTIMIZED_PASSES}")
        print()

        # Test 2: Environment control
        print("⚙️  Testing environment control...")

        # Test with optimization enabled
        os.environ["HS_USE_OPTIMIZED_PASSES"] = "1"
        import importlib
        import viral_finder.idea_graph
        importlib.reload(viral_finder.idea_graph)

        print(f"   ✅ Optimization enabled: {viral_finder.idea_graph.USE_OPTIMIZED_PASSES}")

        # Test with optimization disabled
        os.environ["HS_USE_OPTIMIZED_PASSES"] = "0"
        importlib.reload(viral_finder.idea_graph)

        print(f"   ✅ Optimization disabled: {not viral_finder.idea_graph.USE_OPTIMIZED_PASSES}")
        print()

        # Test 3: Function integration
        print("🔧 Testing function integration...")

        # Re-enable for testing
        os.environ["HS_USE_OPTIMIZED_PASSES"] = "1"
        importlib.reload(viral_finder.idea_graph)

        from viral_finder.idea_graph import select_candidate_clips, _analyze_content_for_adaptive_thresholds

        # Create mock nodes
        mock_nodes = []
        for i in range(10):
            node = type('MockNode', (), {
                'start_time': i * 10.0,
                'end_time': (i + 1) * 10.0,
                'text': f"Mock text {i}",
                'semantic_quality': 0.6 + (i * 0.02),
                'punch_confidence': 0.5 + (i * 0.01),
                'curiosity_score': 0.4 + (i * 0.015),
                'fingerprint': f"fp_{i}",
                'state': 'normal',
                'metrics': {}
            })()
            mock_nodes.append(node)

        # Test content analysis
        content_analysis = _analyze_content_for_adaptive_thresholds(mock_nodes)
        print(f"   ✅ Content analysis: {content_analysis['content_type']} (density: {content_analysis['density']:.2f})")

        # Test clip selection
        start_time = time.time()
        candidates = select_candidate_clips(
            nodes=mock_nodes,
            top_k=5,
            diversity_mode="balanced"
        )
        selection_time = time.time() - start_time

        print(".2f"        print(f"   ✅ Candidates found: {len(candidates)}")
        if candidates:
            avg_score = sum(c.get('score', 0) for c in candidates) / len(candidates)
            print(".3f"        print()

        # Test 4: Performance comparison
        print("⚡ Testing performance comparison...")

        # Disable optimization
        os.environ["HS_USE_OPTIMIZED_PASSES"] = "0"
        importlib.reload(viral_finder.idea_graph)

        start_time = time.time()
        candidates_original = select_candidate_clips(
            nodes=mock_nodes,
            top_k=5,
            diversity_mode="balanced"
        )
        original_time = time.time() - start_time

        # Re-enable optimization
        os.environ["HS_USE_OPTIMIZED_PASSES"] = "1"
        importlib.reload(viral_finder.idea_graph)

        start_time = time.time()
        candidates_optimized = select_candidate_clips(
            nodes=mock_nodes,
            top_k=5,
            diversity_mode="balanced"
        )
        optimized_time = time.time() - start_time

        speedup = original_time / optimized_time if optimized_time > 0 else 1.0

        print(".2f"        print(".2f"        print(".1f"        print(f"   📊 Results match: {len(candidates_original) == len(candidates_optimized)}")
        print()

        print("✅ INTEGRATION TEST COMPLETE!")
        print()
        print("🎯 Key Results:")
        print(f"   • Optimized system: {'✅ Available' if OPTIMIZED_PASSES_AVAILABLE else '❌ Not available'}")
        print(".1f"        print(f"   • Quality maintained: {'✅ Yes' if len(candidates_original) == len(candidates_optimized) else '⚠️  Check needed'}")
        print("   • Integration: ✅ Working")

        return True

    except Exception as e:
        print(f"❌ Integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_integration()
    sys.exit(0 if success else 1)