#!/usr/bin/env python3
"""
Quick test of knowledge injection system
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print("Testing knowledge injection system...")

try:
    # Test basic imports
    from viral_finder.knowledge_injection_system import KnowledgeInjector, IntelligentContentAnalyzer
    print("✅ Imports successful")

    # Test knowledge injector
    injector = KnowledgeInjector()
    print("✅ KnowledgeInjector created")

    # Test intelligent analyzer
    analyzer = IntelligentContentAnalyzer()
    print("✅ IntelligentContentAnalyzer created")

    # Test with simple data
    test_data = {
        'transcript': 'Machine learning is a subset of AI that enables computers to learn from data.',
        'title': 'ML Basics',
        'description': 'Understanding machine learning fundamentals'
    }

    result = analyzer.analyze_video_content(test_data)
    print("✅ Analysis completed")
    print(f"   Domain: {result['detected_domain']}")
    print(f"   Intelligence: {result['intelligence_level']}")
    print(".2f")

    print("\n🎉 Basic test passed!")

except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()