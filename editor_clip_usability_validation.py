#!/usr/bin/env python3
"""
🚀 Editor Clip Usability Validation
Compare before/after the knowledge-enhanced HotShort system using 4 representative content types.
"""

import os
import sys
import math
import json
from copy import deepcopy
from typing import List, Dict, Any

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from viral_finder.idea_graph import _select_candidate_clips_v2, IdeaNode
from viral_finder.knowledge_injection_system import IntelligentContentAnalyzer


def create_test_videos() -> List[Dict[str, Any]]:
    return [
        {
            'slug': 'ai_tutorial',
            'title': 'AI Tutorial: How Machine Learning Works',
            'description': 'A step-by-step explanation of machine learning concepts and neural networks.',
            'transcript': (
                'Machine learning is the science of getting computers to learn from data. In this tutorial, we explain the difference between supervised and unsupervised learning. ' 
                'Neural networks use layers of nodes to recognize patterns. Each node is like a small decision maker. We also cover backpropagation and training loops. '
                'This tutorial shows how models improve by adjusting weights and minimizing loss. In the end, you will be able to understand the core principles of AI systems.'
            ),
            'duration': 420,
            'domain_hint': 'education'
        },
        {
            'slug': 'podcast',
            'title': 'Podcast Episode: Startup Growth and Culture',
            'description': 'A relaxed conversation about building culture, scaling teams, and learning from failure.',
            'transcript': (
                'Welcome back to the show. Today we talk about startup growth and culture. Our guest shares what it means to build teams that learn fast. ' 
                'We discuss how feedback loops shape product strategy, and why communication matters more than process. The episode also includes personal stories and practical advice for founders.'
            ),
            'duration': 360,
            'domain_hint': 'podcast'
        },
        {
            'slug': 'debate_clip',
            'title': 'Debate: Should Social Media Be Regulated?',
            'description': 'A short debate on regulation, free speech, and algorithmic influence.',
            'transcript': (
                'The regulation of social media is one of the most important issues of our time. One side argues that platforms must be held accountable for misinformation and harmful content. ' 
                'The opposing view says that regulation can threaten free speech and innovation. We examine evidence, logic, and ethical consequences to find a balanced position.'
            ),
            'duration': 300,
            'domain_hint': 'debate'
        },
        {
            'slug': 'storytelling',
            'title': 'Storytelling Video: The Hero Journey in Modern Media',
            'description': 'An analysis of how storytelling structure creates emotional engagement.',
            'transcript': (
                'In every great story, the hero starts in an ordinary world and then receives a call to adventure. The journey includes trials, allies, and a final confrontation. ' 
                'This storytelling video explores how creators build emotional arcs with tension and resolution. We also look at the power of character development and payoff.'
            ),
            'duration': 330,
            'domain_hint': 'entertainment'
        }
    ]


def make_transcript_items(video: Dict[str, Any]) -> List[Dict[str, Any]]:
    words = video['transcript'].split()
    segment_count = min(10, max(4, len(words) // 25))
    segment_size = max(1, len(words) // segment_count)
    items = []
    for i in range(segment_count):
        start_word = i * segment_size
        end_word = min(len(words), (i + 1) * segment_size)
        chunk = ' '.join(words[start_word:end_word])
        start_time = (video['duration'] / segment_count) * i
        end_time = (video['duration'] / segment_count) * (i + 1)
        items.append({
            'start': start_time,
            'end': end_time,
            'text': chunk,
        })
    return items


def score_text_features(text: str, domain_hint: str) -> Dict[str, float]:
    lower = text.lower()
    semantic = 0.35
    punch = 0.3
    curiosity = 0.3

    if any(word in lower for word in ['learn', 'explain', 'understand', 'tutorial', 'concept', 'training', 'model']):
        semantic += 0.18
        curiosity += 0.12
    if any(word in lower for word in ['argument', 'evidence', 'debate', 'policy', 'free speech', 'regulated', 'regulation']):
        punch += 0.22
        semantic += 0.12
    if any(word in lower for word in ['story', 'hero', 'emotional', 'character', 'arc', 'journey', 'payoff']):
        curiosity += 0.22
        semantic += 0.12
    if any(word in lower for word in ['welcome', 'show', 'guest', 'conversation', 'episode', 'host', 'audience']):
        curiosity += 0.12
        punch += 0.10

    if domain_hint == 'education':
        semantic += 0.15
        curiosity += 0.08
    elif domain_hint == 'podcast':
        curiosity += 0.18
        punch += 0.08
    elif domain_hint == 'debate':
        punch += 0.20
        semantic += 0.15
    elif domain_hint == 'entertainment':
        curiosity += 0.18
        semantic += 0.12

    return {
        'semantic': min(1.0, semantic),
        'punch': min(1.0, punch),
        'curiosity': min(1.0, curiosity)
    }


def create_nodes(video: Dict[str, Any]) -> (List[IdeaNode], List[Dict[str, Any]]):
    transcript_items = make_transcript_items(video)
    nodes = []
    for idx, segment in enumerate(transcript_items):
        scores = score_text_features(segment['text'], video['domain_hint'])
        motion = 0.18 if video['domain_hint'] in ('education', 'debate') else 0.28
        audio = 0.55
        ending_strength = 0.4 + 0.1 * (idx % 3)
        completion_score = 0.45 + 0.1 * ((idx + 1) % 3)
        nodes.append(IdeaNode(
            start_idx=idx,
            end_idx=idx,
            start_time=segment['start'],
            end_time=segment['end'],
            segments=[segment],
            text=segment['text'],
            state='normal',
            curiosity_score=scores['curiosity'],
            punch_confidence=scores['punch'],
            semantic_quality=scores['semantic'],
            fingerprint=f"{video['slug']}_{idx}",
            metrics={
                'motion_mean': motion,
                'audio_mean': audio,
                'ending_strength': ending_strength,
                'completion_score': completion_score,
            }
        ))
    return nodes, transcript_items


def boost_nodes_with_knowledge(nodes: List[IdeaNode], analysis: Dict[str, Any]) -> List[IdeaNode]:
    boosted = []
    keywords = set(analysis['basic_analysis']['topics'])
    domain = analysis['detected_domain']
    for node in nodes:
        text = node.text.lower()
        semantic = node.semantic_quality
        punch = node.punch_confidence
        curiosity = node.curiosity_score

        if any(topic in text for topic in keywords):
            semantic = min(1.0, semantic + 0.08)
            curiosity = min(1.0, curiosity + 0.06)

        if domain == 'education' and any(word in text for word in ['learn', 'explain', 'understand', 'tutorial']):
            semantic = min(1.0, semantic + 0.05)
            punch = min(1.0, punch + 0.03)
        if domain == 'debate' and any(word in text for word in ['evidence', 'argument', 'policy', 'free speech']):
            punch = min(1.0, punch + 0.08)
        if domain == 'entertainment' and any(word in text for word in ['story', 'hero', 'emotional', 'arc']):
            curiosity = min(1.0, curiosity + 0.08)
        if domain == 'podcast' and any(word in text for word in ['guest', 'conversation', 'episode', 'show']):
            curiosity = min(1.0, curiosity + 0.05)

        boosted.append(node._replace(
            semantic_quality=semantic,
            punch_confidence=punch,
            curiosity_score=curiosity
        ))
    return boosted


def select_clips(nodes: List[IdeaNode], transcript_items: List[Dict[str, Any]], top_k: int = 6) -> List[Dict[str, Any]]:
    return _select_candidate_clips_v2(
        nodes,
        top_k=top_k,
        transcript=transcript_items,
        ensure_sentence_complete=False,
        allow_multi_angle=False,
        min_target=0,
        diversity_mode='balanced',
        max_overlap_ratio=0.35
    )


def analyze_candidates(candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not candidates:
        return {
            'number_of_clips': 0,
            'average_score': 0.0,
            'semantic_strength': 0.0,
            'arc_completion_rate': 0.0,
            'relaxed_pass_usage': 0.0,
            'explanation_clips': 0,
            'clarity_ranking': 0.0,
            'motion_dependence': 1.0
        }
    avg_score = sum(c.get('score', 0) for c in candidates) / len(candidates)
    semantic_strength = sum(c.get('semantic_quality', 0) for c in candidates) / len(candidates)
    arc_rate = sum((c.get('ending_strength', 0) + c.get('completion_score', 0)) / 2 for c in candidates) / len(candidates)
    relaxed_usage = sum(1 for c in candidates if c.get('pass_type') == 'relaxed') / len(candidates)
    explanation_clips = sum(1 for c in candidates if any(word in c.get('text', '').lower() for word in ['explain', 'learn', 'understand', 'tutorial', 'concept']))
    motion = sum(c.get('motion_mean', 0.5) for c in candidates) / len(candidates)
    clarity = 1.0 - motion
    return {
        'number_of_clips': len(candidates),
        'average_score': avg_score,
        'semantic_strength': semantic_strength,
        'arc_completion_rate': arc_rate,
        'relaxed_pass_usage': relaxed_usage,
        'explanation_clips': explanation_clips,
        'clarity_ranking': clarity,
        'motion_dependence': motion
    }


def print_case_results(label: str, analysis: Dict[str, Any]):
    print(f"{label}:")
    print(f"  Clips: {analysis['number_of_clips']}")
    print(f"  Avg Score: {analysis['average_score']:.3f}")
    print(f"  Semantic Strength: {analysis['semantic_strength']:.3f}")
    print(f"  Arc Completion: {analysis['arc_completion_rate']:.3f}")
    print(f"  Relaxed Usage: {analysis['relaxed_pass_usage']:.3f}")
    print(f"  Explanation Clips: {analysis['explanation_clips']}")
    print(f"  Clarity: {analysis['clarity_ranking']:.3f}")
    print(f"  Motion Dependence: {analysis['motion_dependence']:.3f}")
    print()


def compare_cases(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    return {
        'clips_change': after['number_of_clips'] - before['number_of_clips'],
        'ave_score_change': after['average_score'] - before['average_score'],
        'semantic_change': after['semantic_strength'] - before['semantic_strength'],
        'arc_change': after['arc_completion_rate'] - before['arc_completion_rate'],
        'relaxed_change': after['relaxed_pass_usage'] - before['relaxed_pass_usage'],
        'explanation_change': after['explanation_clips'] - before['explanation_clips'],
        'clarity_change': after['clarity_ranking'] - before['clarity_ranking'],
        'motion_change': after['motion_dependence'] - before['motion_dependence']
    }


def run_validation():
    analyzer = IntelligentContentAnalyzer()
    videos = create_test_videos()
    summary = []

    print("=" * 80)
    print("EDITOR CLIP USABILITY VALIDATION")
    print("Compare four uploads before/after knowledge-enhanced selection")
    print("=" * 80)

    for video in videos:
        print(f"\nVideo: {video['title']}")
        nodes, transcript_items = create_nodes(video)
        before_clips = select_clips(nodes, transcript_items)
        before_analysis = analyze_candidates(before_clips)

        analysis = analyzer.analyze_video_content(video)
        boosted_nodes = boost_nodes_with_knowledge(nodes, analysis)
        after_clips = select_clips(boosted_nodes, transcript_items)
        after_analysis = analyze_candidates(after_clips)

        print_case_results('BEFORE', before_analysis)
        print_case_results('AFTER', after_analysis)

        diff = compare_cases(before_analysis, after_analysis)
        print("Delta Results:")
        print(f"  Clips +{diff['clips_change']}")
        print(f"  Avg Score +{diff['ave_score_change']:.3f}")
        print(f"  Semantic +{diff['semantic_change']:.3f}")
        print(f"  Arc Rate +{diff['arc_change']:.3f}")
        print(f"  Relaxed +{diff['relaxed_change']:.3f}")
        print(f"  Explanation Clips +{diff['explanation_change']}")
        print(f"  Clarity +{diff['clarity_change']:.3f}")
        print(f"  Motion Change {diff['motion_change']:.3f}")

        summary.append({
            'video': video['slug'],
            'before': before_analysis,
            'after': after_analysis,
            'diff': diff
        })

    with open('editor_clip_usability_validation_results.json', 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2)

    print("\n" + "=" * 80)
    print("Validation complete. Results saved to editor_clip_usability_validation_results.json")
    print("=" * 80)

    return summary


if __name__ == '__main__':
    run_validation()
