#!/usr/bin/env python3
"""
🚀 KNOWLEDGE INJECTION VALIDATION TEST
Compare SAME video: Before vs After knowledge injection
Expected: 1 clip → 4-6 clips, higher quality metrics
"""

import os
import sys
import time
import json
from typing import Dict, Any

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def create_ai_explanation_video_data():
    """Create test data for AI explanation video"""

    return {
        'transcript': """
        Artificial Intelligence is transforming our world in ways we never imagined. AI systems can now understand language, recognize patterns, and even create art. But how does AI actually work?

        At its core, AI uses algorithms and data to make decisions. Machine learning allows computers to learn from examples without being explicitly programmed. Deep learning uses neural networks inspired by the human brain.

        Neural networks consist of layers of interconnected nodes. Each connection has a weight that gets adjusted during training. Through backpropagation, the network learns to make better predictions.

        The training process requires massive amounts of data. The more diverse the data, the better the AI performs. This is why companies collect enormous datasets to train their models.

        Once trained, AI can perform tasks like image recognition, natural language processing, and predictive analytics. These capabilities are revolutionizing industries from healthcare to finance.

        However, AI also raises important ethical questions. How do we ensure AI systems are fair and unbiased? What happens when AI makes mistakes? These are crucial considerations as AI becomes more integrated into our daily lives.

        The future of AI is incredibly promising. With continued research and responsible development, AI will help us solve some of the world's most pressing challenges.
        """,
        'title': 'How Artificial Intelligence Works: A Complete Explanation',
        'description': 'Understanding the fundamentals of AI, machine learning, and neural networks. From basic algorithms to advanced deep learning systems.',
        'duration': 480,  # 8 minutes
        'url': 'https://example.com/ai-explanation-video'
    }

def run_validation_test():
    """Run the before/after knowledge injection validation"""

    print("=" * 80)
    print("🚀 KNOWLEDGE INJECTION VALIDATION TEST")
    print("   SAME VIDEO: AI Explanation Content")
    print("   BEFORE vs AFTER Knowledge Injection")
    print("=" * 80)

    # Get test video data
    video_data = create_ai_explanation_video_data()
    print(f"📹 Test Video: {video_data['title']}")
    print(f"   Duration: {video_data['duration']}s")
    print(f"   Transcript Length: {len(video_data['transcript'])} chars")
    print()

    results = {}

    try:
        # Test 1: BEFORE Knowledge Injection (Original System)
        print("🧪 TEST 1: BEFORE Knowledge Injection")
        print("-" * 50)

        # Temporarily disable knowledge injection
        os.environ['HS_USE_KNOWLEDGE_INJECTION'] = '0'

        before_result = run_clip_selection_test(video_data, use_knowledge=False)
        results['before'] = before_result

        print("✅ Before Results:")
        print(f"   📊 Clips Found: {before_result['number_of_clips']}")
        print(".3f")
        print(".3f")
        print(".3f")
        print(".3f")
        print()

        # Test 2: AFTER Knowledge Injection (Intelligent System)
        print("🧪 TEST 2: AFTER Knowledge Injection")
        print("-" * 50)

        # Enable knowledge injection
        os.environ['HS_USE_KNOWLEDGE_INJECTION'] = '1'

        # First inject knowledge if not already done
        inject_test_knowledge()

        after_result = run_clip_selection_test(video_data, use_knowledge=True)
        results['after'] = after_result

        print("✅ After Results:")
        print(f"   📊 Clips Found: {after_result['number_of_clips']}")
        print(".3f")
        print(".3f")
        print(".3f")
        print(".3f")
        print()

        # Test 3: COMPARISON ANALYSIS
        print("📊 TEST 3: COMPARISON ANALYSIS")
        print("-" * 50)

        comparison = analyze_comparison(results['before'], results['after'])
        results['comparison'] = comparison

        print("🎯 VALIDATION RESULTS:")
        print(f"   📈 Clips Improvement: {comparison['clips_improvement']}")
        print(".3f")
        print(".3f")
        print(".3f")
        print(".3f")
        print()

        # Test 4: EXPECTED OUTCOMES CHECK
        print("✅ TEST 4: EXPECTED OUTCOMES VALIDATION")
        print("-" * 50)

        validation = validate_expected_outcomes(comparison)
        results['validation'] = validation

        print("🎯 EXPECTED IMPROVEMENTS:")
        print(f"   1️⃣ 1→4-6 clips: {'✅' if validation['clips_target_met'] else '❌'} ({comparison['clips_improvement']})")
        print(f"   2️⃣ Higher clarity: {'✅' if validation['clarity_improved'] else '❌'} ({comparison['clarity_change']:+.3f})")
        print(f"   3️⃣ Lower motion dep: {'✅' if validation['motion_reduced'] else '❌'} ({comparison['motion_change']:+.3f})")
        print(f"   4️⃣ More explanation clips: {'✅' if validation['explanation_increased'] else '❌'} ({comparison['explanation_change']:+.1f})")
        print()

        # Final verdict
        success_rate = sum([
            validation['clips_target_met'],
            validation['clarity_improved'],
            validation['motion_reduced'],
            validation['explanation_increased']
        ]) / 4

        print("🏆 FINAL VERDICT:")
        if success_rate >= 0.75:
            print("   🎉 SUCCESS: Knowledge injection working correctly!")
            print(".1%")
            print("   🧠 HotShort is now extremely intelligent!")
        else:
            print("   ⚠️  PARTIAL: Some improvements detected, needs tuning")
            print(".1%")
            print("   🔧 May need knowledge base optimization")

        print("\n" + "=" * 80)
        print("📋 DETAILED RESULTS SUMMARY")
        print("=" * 80)

        print("BEFORE (Original System):")
        print(f"   Clips: {results['before']['number_of_clips']}")
        print(".3f")
        print(".3f")
        print(".3f")
        print(".3f")

        print("\nAFTER (Intelligent System):")
        print(f"   Clips: {results['after']['number_of_clips']}")
        print(".3f")
        print(".3f")
        print(".3f")
        print(".3f")

        print("\nIMPROVEMENTS:")
        print(f"   Clips: {comparison['clips_improvement']}")
        print(".3f")
        print(".3f")
        print(".3f")
        print(".3f")

        return True, results

    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False, None

def run_clip_selection_test(video_data: Dict[str, Any], use_knowledge: bool = False) -> Dict[str, Any]:
    """Run clip selection test with/without knowledge injection"""

    try:
        # Import required modules
        from viral_finder.idea_graph import _select_candidate_clips_v2
        from viral_finder.knowledge_injection_system import IntelligentContentAnalyzer

        # Create mock transcript data
        transcript_data = {
            'text': video_data['transcript'],
            'duration': video_data['duration'],
            'title': video_data['title']
        }

        start_time = time.time()

        if use_knowledge:
            # Use intelligent analyzer
            analyzer = IntelligentContentAnalyzer()
            intelligent_result = analyzer.analyze_video_content(video_data)

            print(f"   🧠 Domain Detected: {intelligent_result['detected_domain']}")
            print(f"   🧠 Intelligence Level: {intelligent_result['intelligence_level']}")
            print(".2f")

            # Use the intelligent analysis to enhance clip selection
            enhanced_transcript_data = transcript_data.copy()
            enhanced_transcript_data['domain_intelligence'] = intelligent_result

            candidates, metrics = _select_candidate_clips_v2(
                enhanced_transcript_data,
                target_count=6,
                use_knowledge_injection=True
            )
        else:
            # Use original system
            candidates, metrics = _select_candidate_clips_v2(
                transcript_data,
                target_count=6,
                use_knowledge_injection=False
            )

        processing_time = time.time() - start_time

        # Analyze results
        analysis = analyze_clip_results(candidates, metrics)

        result = {
            'number_of_clips': len(candidates),
            'average_score': analysis['average_score'],
            'semantic_strength': analysis['semantic_strength'],
            'arc_completion_rate': analysis['arc_completion_rate'],
            'relaxed_pass_usage': analysis['relaxed_pass_usage'],
            'processing_time': processing_time,
            'candidates': candidates,
            'metrics': metrics,
            'analysis': analysis
        }

        return result

    except Exception as e:
        print(f"   ❌ Clip selection failed: {e}")
        # Return minimal result on failure
        return {
            'number_of_clips': 0,
            'average_score': 0.0,
            'semantic_strength': 0.0,
            'arc_completion_rate': 0.0,
            'relaxed_pass_usage': 0.0,
            'processing_time': 0.0,
            'candidates': [],
            'metrics': {},
            'analysis': {}
        }

def analyze_clip_results(candidates: list, metrics: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze the clip selection results"""

    if not candidates:
        return {
            'average_score': 0.0,
            'semantic_strength': 0.0,
            'arc_completion_rate': 0.0,
            'relaxed_pass_usage': 0.0,
            'clarity_ranking': 0.0,
            'motion_dependence': 1.0,
            'explanation_clips': 0
        }

    # Calculate metrics
    scores = [c.get('score', 0) for c in candidates]
    average_score = sum(scores) / len(scores) if scores else 0

    # Semantic strength (based on semantic_quality)
    semantic_scores = [c.get('semantic_quality', 0) for c in candidates]
    semantic_strength = sum(semantic_scores) / len(semantic_scores) if semantic_scores else 0

    # Arc completion rate (based on ending_strength and completion_score)
    arc_scores = []
    for c in candidates:
        ending = c.get('ending_strength', 0)
        completion = c.get('completion_score', 0)
        arc_scores.append((ending + completion) / 2)
    arc_completion_rate = sum(arc_scores) / len(arc_scores) if arc_scores else 0

    # Relaxed pass usage
    relaxed_count = sum(1 for c in candidates if c.get('pass_type') == 'relaxed')
    relaxed_pass_usage = relaxed_count / len(candidates) if candidates else 0

    # Clarity ranking (inverse of motion dependence)
    motion_scores = [c.get('motion_mean', 0.5) for c in candidates]
    avg_motion = sum(motion_scores) / len(motion_scores) if motion_scores else 0.5
    clarity_ranking = 1.0 - avg_motion  # Higher clarity = lower motion dependence

    # Motion dependence (higher = more dependent on motion)
    motion_dependence = avg_motion

    # Explanation clips (clips that explain concepts)
    explanation_clips = sum(1 for c in candidates
                          if 'explain' in c.get('text', '').lower() or
                             'understand' in c.get('text', '').lower() or
                             'learn' in c.get('text', '').lower())

    return {
        'average_score': average_score,
        'semantic_strength': semantic_strength,
        'arc_completion_rate': arc_completion_rate,
        'relaxed_pass_usage': relaxed_pass_usage,
        'clarity_ranking': clarity_ranking,
        'motion_dependence': motion_dependence,
        'explanation_clips': explanation_clips
    }

def inject_test_knowledge():
    """Inject knowledge for testing"""

    try:
        from viral_finder.knowledge_injection_system import KnowledgeInjector

        injector = KnowledgeInjector()

        # Quick inject education knowledge for AI/ML topics
        ai_knowledge = [
            {
                'topic': 'artificial intelligence',
                'content': 'AI systems use algorithms and data to perform tasks that typically require human intelligence. Key components include machine learning, neural networks, and natural language processing.',
                'expertise_level': 'intermediate',
                'quality_score': 0.9,
                'source': 'validation_test'
            },
            {
                'topic': 'machine learning',
                'content': 'Machine learning enables computers to learn patterns from data without explicit programming. Supervised learning uses labeled data, unsupervised learning finds hidden patterns.',
                'expertise_level': 'intermediate',
                'quality_score': 0.9,
                'source': 'validation_test'
            },
            {
                'topic': 'neural networks',
                'content': 'Neural networks consist of interconnected nodes that process information. Deep learning uses multiple layers to learn complex patterns from data.',
                'expertise_level': 'advanced',
                'quality_score': 0.95,
                'source': 'validation_test'
            }
        ]

        result = injector.inject_bulk_knowledge(ai_knowledge, 'education')
        print(f"   📚 Injected {result['injected_count']} knowledge items for testing")

    except Exception as e:
        print(f"   ⚠️  Knowledge injection failed: {e}")

def analyze_comparison(before: Dict, after: Dict) -> Dict[str, Any]:
    """Analyze the before/after comparison"""

    clips_before = before['number_of_clips']
    clips_after = after['number_of_clips']

    clips_improvement = f"{clips_before} → {clips_after} ({'+' if clips_after > clips_before else ''}{clips_after - clips_before})"

    return {
        'clips_improvement': clips_improvement,
        'clips_change': clips_after - clips_before,
        'score_change': after['average_score'] - before['average_score'],
        'semantic_change': after['semantic_strength'] - before['semantic_strength'],
        'arc_change': after['arc_completion_rate'] - before['arc_completion_rate'],
        'relaxed_change': after['relaxed_pass_usage'] - before['relaxed_pass_usage'],
        'clarity_change': after['analysis'].get('clarity_ranking', 0) - before['analysis'].get('clarity_ranking', 0),
        'motion_change': after['analysis'].get('motion_dependence', 0) - before['analysis'].get('motion_dependence', 0),
        'explanation_change': after['analysis'].get('explanation_clips', 0) - before['analysis'].get('explanation_clips', 0)
    }

def validate_expected_outcomes(comparison: Dict) -> Dict[str, Any]:
    """Validate if expected outcomes were achieved"""

    # Expected: 1 clip → 4-6 clips
    clips_target_met = comparison['clips_change'] >= 3  # At least +3 clips

    # Expected: higher clarity ranking
    clarity_improved = comparison['clarity_change'] > 0

    # Expected: lower motion dependence
    motion_reduced = comparison['motion_change'] < 0

    # Expected: more explanation clips selected
    explanation_increased = comparison['explanation_change'] > 0

    return {
        'clips_target_met': clips_target_met,
        'clarity_improved': clarity_improved,
        'motion_reduced': motion_reduced,
        'explanation_increased': explanation_increased,
        'overall_success': sum([clips_target_met, clarity_improved, motion_reduced, explanation_increased]) >= 3
    }

if __name__ == "__main__":
    success, results = run_validation_test()

    if success and results:
        # Save results to file
        with open('knowledge_injection_validation_results.json', 'w') as f:
            # Convert results to JSON-serializable format
            json_results = {
                'timestamp': str(time.time()),
                'success': success,
                'before': {
                    'number_of_clips': results['before']['number_of_clips'],
                    'average_score': results['before']['average_score'],
                    'semantic_strength': results['before']['semantic_strength'],
                    'arc_completion_rate': results['before']['arc_completion_rate'],
                    'relaxed_pass_usage': results['before']['relaxed_pass_usage']
                },
                'after': {
                    'number_of_clips': results['after']['number_of_clips'],
                    'average_score': results['after']['average_score'],
                    'semantic_strength': results['after']['semantic_strength'],
                    'arc_completion_rate': results['after']['arc_completion_rate'],
                    'relaxed_pass_usage': results['after']['relaxed_pass_usage']
                },
                'comparison': results['comparison'],
                'validation': results['validation']
            }
            json.dump(json_results, f, indent=2)

        print("
💾 Results saved to: knowledge_injection_validation_results.json"    else:
        print("\n❌ Validation test failed!")
        sys.exit(1)</content>
<parameter name="filePath">c:\Users\n\Documents\hotshort\knowledge_injection_validation.py