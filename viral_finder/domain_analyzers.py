#!/usr/bin/env python3
"""
🧠 Domain-Specific Analyzers for Multi-Domain Intelligence
Specialized analysis for education, entertainment, debate, and podcast content
"""

import re
import logging
from typing import Dict, List, Any, Optional
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

class DomainAnalyzer(ABC):
    """Abstract base class for domain-specific analyzers"""

    @abstractmethod
    def analyze_content(self, content: str) -> Dict[str, Any]:
        """Analyze content using domain-specific intelligence"""
        pass

    def extract_topics(self, content: str) -> List[str]:
        """Extract relevant topics from content"""
        # Basic topic extraction
        words = re.findall(r'\b\w{4,}\b', content.lower())
        common_words = {'that', 'with', 'have', 'this', 'will', 'your', 'from', 'they', 'know', 'want', 'been', 'good', 'much', 'some', 'time', 'very', 'when', 'come', 'here', 'just', 'like', 'long', 'make', 'many', 'over', 'such', 'take', 'than', 'them', 'well', 'were'}

        topics = []
        for word in words:
            if word not in common_words and len(word) > 3:
                if word not in topics:
                    topics.append(word)
                if len(topics) >= 15:
                    break

        return topics

class EducationAnalyzer(DomainAnalyzer):
    """Specialized analyzer for educational content"""

    def __init__(self):
        self.educational_indicators = {
            'learning_objectives': [
                'learn', 'understand', 'know', 'able to', 'comprehend',
                'master', 'grasp', 'explain', 'demonstrate', 'apply'
            ],
            'teaching_methods': [
                'example', 'demonstration', 'explanation', 'practice',
                'exercise', 'quiz', 'test', 'assessment', 'review'
            ],
            'difficulty_markers': {
                'beginner': ['basic', 'simple', 'easy', 'introduction', 'fundamentals'],
                'intermediate': ['intermediate', 'moderate', 'some experience', 'building on'],
                'advanced': ['advanced', 'complex', 'expert', 'deep dive', 'specialized']
            }
        }

    def analyze_content(self, content: str) -> Dict[str, Any]:
        """Analyze educational content with domain expertise"""

        topics = self.extract_topics(content)

        # Detect learning objectives
        learning_objectives = self._extract_learning_objectives(content)

        # Assess difficulty level
        difficulty = self._assess_difficulty(content)

        # Identify teaching patterns
        teaching_patterns = self._identify_teaching_patterns(content)

        # Calculate educational quality score
        quality_score = self._calculate_educational_quality(
            learning_objectives, teaching_patterns, difficulty
        )

        return {
            'domain': 'education',
            'topics': topics,
            'learning_objectives': learning_objectives,
            'difficulty_level': difficulty,
            'teaching_patterns': teaching_patterns,
            'educational_quality': quality_score,
            'content_type': self._classify_content_type(content),
            'engagement_score': self._calculate_engagement(content),
            'confidence': 0.85
        }

    def _extract_learning_objectives(self, content: str) -> List[str]:
        """Extract learning objectives from educational content"""
        objectives = []
        sentences = content.split('.')

        for sentence in sentences:
            sentence = sentence.lower().strip()
            if any(indicator in sentence for indicator in self.educational_indicators['learning_objectives']):
                if len(sentence) > 10:  # Filter very short sentences
                    objectives.append(sentence)

        return objectives[:5]  # Top 5 objectives

    def _assess_difficulty(self, content: str) -> str:
        """Assess the difficulty level of educational content"""
        content_lower = content.lower()

        difficulty_scores = {level: 0 for level in ['beginner', 'intermediate', 'advanced']}

        for level, markers in self.educational_indicators['difficulty_markers'].items():
            for marker in markers:
                if marker in content_lower:
                    difficulty_scores[level] += 1

        # Return level with highest score, default to intermediate
        best_level = max(difficulty_scores, key=difficulty_scores.get)
        return best_level if difficulty_scores[best_level] > 0 else 'intermediate'

    def _identify_teaching_patterns(self, content: str) -> Dict[str, Any]:
        """Identify teaching patterns and methods used"""
        patterns = {
            'expository': 0,  # Direct explanation
            'discovery': 0,   # Guided discovery
            'practice': 0,    # Hands-on practice
            'assessment': 0   # Testing/checking understanding
        }

        content_lower = content.lower()

        # Count pattern indicators
        if any(word in content_lower for word in ['explain', 'describe', 'define', 'overview']):
            patterns['expository'] += 1
        if any(word in content_lower for word in ['discover', 'explore', 'find out', 'investigate']):
            patterns['discovery'] += 1
        if any(word in content_lower for word in ['practice', 'exercise', 'try', 'do it']):
            patterns['practice'] += 1
        if any(word in content_lower for word in ['quiz', 'test', 'check', 'assessment']):
            patterns['assessment'] += 1

        total_patterns = sum(patterns.values())
        effectiveness = total_patterns / 4.0 if total_patterns > 0 else 0.5

        return {
            'patterns': patterns,
            'total_patterns': total_patterns,
            'effectiveness': effectiveness
        }

    def _calculate_educational_quality(self, objectives: List, patterns: Dict, difficulty: str) -> float:
        """Calculate overall educational quality score"""
        base_score = 0.5

        # Boost for clear learning objectives
        objective_boost = min(len(objectives) * 0.1, 0.3)

        # Boost for effective teaching patterns
        pattern_boost = patterns['effectiveness'] * 0.2

        # Adjust for difficulty (intermediate content often highest quality)
        difficulty_multiplier = {'beginner': 0.8, 'intermediate': 1.0, 'advanced': 0.9}[difficulty]

        final_score = (base_score + objective_boost + pattern_boost) * difficulty_multiplier
        return min(final_score, 1.0)

    def _classify_content_type(self, content: str) -> str:
        """Classify the type of educational content"""
        content_lower = content.lower()

        if any(word in content_lower for word in ['tutorial', 'how to', 'guide', 'step by step']):
            return 'tutorial'
        elif any(word in content_lower for word in ['lecture', 'course', 'class', 'lesson']):
            return 'lecture'
        elif any(word in content_lower for word in ['workshop', 'training', 'seminar']):
            return 'workshop'
        else:
            return 'educational_video'

    def _calculate_engagement(self, content: str) -> float:
        """Calculate educational engagement score"""
        engagement_indicators = ['question', 'think about', 'consider', 'imagine', 'what if', 'why']
        sentences = content.split('.')

        engagement_count = 0
        for sentence in sentences:
            if any(indicator in sentence.lower() for indicator in engagement_indicators):
                engagement_count += 1

        return min(engagement_count / len(sentences), 1.0) if sentences else 0.0

class EntertainmentAnalyzer(DomainAnalyzer):
    """Specialized analyzer for entertainment content"""

    def __init__(self):
        self.genre_indicators = {
            'comedy': ['funny', 'joke', 'laugh', 'hilarious', 'comedy', 'humor'],
            'drama': ['emotional', 'story', 'character', 'plot', 'dramatic', 'intense'],
            'action': ['action', 'fight', 'adventure', 'thrill', 'exciting', 'fast-paced'],
            'horror': ['scary', 'horror', 'fear', 'terror', 'spooky', 'nightmare'],
            'romance': ['love', 'romantic', 'relationship', 'heart', 'passion', 'romance']
        }

        self.emotional_arc_patterns = {
            'rising_action': ['building', 'increasing', 'growing', 'escalating'],
            'climax': ['peak', 'highest point', 'turning point', 'crisis'],
            'falling_action': ['resolution', 'conclusion', 'wrapping up', 'ending']
        }

    def analyze_content(self, content: str) -> Dict[str, Any]:
        """Analyze entertainment content with genre expertise"""

        topics = self.extract_topics(content)

        # Detect genre
        genre = self._detect_genre(content)

        # Analyze entertainment value
        entertainment_score = self._calculate_entertainment_value(content, genre)

        # Analyze emotional arc
        emotional_arc = self._analyze_emotional_arc(content)

        # Assess pacing
        pacing_score = self._assess_pacing(content)

        # Predict viral potential
        viral_potential = self._predict_viral_potential(content, genre, entertainment_score)

        return {
            'domain': 'entertainment',
            'topics': topics,
            'genre': genre,
            'entertainment_value': entertainment_score,
            'emotional_arc': emotional_arc,
            'pacing_score': pacing_score,
            'viral_potential': viral_potential,
            'content_type': 'entertainment_video',
            'engagement_score': entertainment_score,  # Entertainment = engagement for this domain
            'confidence': 0.80
        }

    def _detect_genre(self, content: str) -> str:
        """Detect the entertainment genre"""
        content_lower = content.lower()

        genre_scores = {}
        for genre, indicators in self.genre_indicators.items():
            score = sum(1 for indicator in indicators if indicator in content_lower)
            genre_scores[genre] = score

        # Return genre with highest score, default to comedy
        best_genre = max(genre_scores, key=genre_scores.get)
        return best_genre if genre_scores[best_genre] > 0 else 'comedy'

    def _calculate_entertainment_value(self, content: str, genre: str) -> float:
        """Calculate entertainment value score"""
        base_score = 0.5

        # Genre-specific scoring
        genre_multipliers = {
            'comedy': 1.2,  # Comedy often most entertaining
            'action': 1.1,  # Action is exciting
            'drama': 0.9,   # Drama can be hit or miss
            'horror': 1.0,  # Horror has strong reactions
            'romance': 0.8  # Romance more niche
        }

        genre_multiplier = genre_multipliers.get(genre, 1.0)

        # Content-based scoring
        content_indicators = ['exciting', 'amazing', 'incredible', 'awesome', 'fantastic']
        indicator_count = sum(1 for indicator in content_indicators if indicator in content.lower())

        indicator_boost = min(indicator_count * 0.1, 0.3)

        final_score = (base_score + indicator_boost) * genre_multiplier
        return min(final_score, 1.0)

    def _analyze_emotional_arc(self, content: str) -> Dict[str, Any]:
        """Analyze the emotional arc of entertainment content"""
        arc_scores = {phase: 0 for phase in ['rising_action', 'climax', 'falling_action']}

        content_lower = content.lower()
        sentences = content.split('.')

        # Analyze each sentence for emotional arc indicators
        for i, sentence in enumerate(sentences):
            for phase, indicators in self.emotional_arc_patterns.items():
                if any(indicator in sentence for indicator in indicators):
                    arc_scores[phase] += 1

        # Calculate arc completeness
        total_indicators = sum(arc_scores.values())
        completeness = min(total_indicators / 3.0, 1.0)  # Ideal: all 3 phases present

        return {
            'arc_scores': arc_scores,
            'completeness': completeness,
            'strongest_phase': max(arc_scores, key=arc_scores.get)
        }

    def _assess_pacing(self, content: str) -> float:
        """Assess pacing score for entertainment content"""
        sentences = content.split('.')
        if not sentences:
            return 0.5

        # Calculate average sentence length as pacing indicator
        avg_length = sum(len(s.split()) for s in sentences) / len(sentences)

        # Shorter sentences = faster pacing
        if avg_length < 10:
            pacing = 0.9  # Very fast-paced
        elif avg_length < 15:
            pacing = 0.7  # Fast-paced
        elif avg_length < 20:
            pacing = 0.5  # Moderate
        else:
            pacing = 0.3  # Slow-paced

        return pacing

    def _predict_viral_potential(self, content: str, genre: str, entertainment_score: float) -> float:
        """Predict viral potential for entertainment content"""
        base_viral = 0.4

        # Genre viral multipliers
        genre_viral_multipliers = {
            'comedy': 1.5,    # Comedy spreads easily
            'horror': 1.3,    # Horror creates strong reactions
            'action': 1.2,    # Action is shareable
            'drama': 0.8,     # Drama more niche
            'romance': 0.7    # Romance least viral
        }

        genre_multiplier = genre_viral_multipliers.get(genre, 1.0)

        # Entertainment boost
        entertainment_boost = entertainment_score * 0.3

        # Content virality indicators
        viral_indicators = ['shocking', 'unbelievable', 'crazy', 'insane', 'epic']
        viral_count = sum(1 for indicator in viral_indicators if indicator in content.lower())
        viral_boost = min(viral_count * 0.1, 0.2)

        final_viral = (base_viral + entertainment_boost + viral_boost) * genre_multiplier
        return min(final_viral, 1.0)

class DebateAnalyzer(DomainAnalyzer):
    """Specialized analyzer for debate content"""

    def __init__(self):
        self.argumentation_indicators = {
            'evidence': ['study', 'research', 'data', 'statistics', 'fact', 'evidence'],
            'logic': ['therefore', 'because', 'thus', 'consequently', 'follows that'],
            'rhetoric': ['clearly', 'obviously', 'certainly', 'undoubtedly', 'absolutely'],
            'counterargument': ['however', 'but', 'although', 'despite', 'on the other hand']
        }

        self.logical_fallacies = [
            'ad hominem', 'straw man', 'false dilemma', 'slippery slope',
            'appeal to emotion', 'bandwagon', 'authority fallacy'
        ]

    def analyze_content(self, content: str) -> Dict[str, Any]:
        """Analyze debate content with argumentation expertise"""

        topics = self.extract_topics(content)

        # Extract arguments
        arguments = self._extract_arguments(content)

        # Detect logical fallacies
        fallacies = self._detect_fallacies(content)

        # Assess evidence quality
        evidence_quality = self._assess_evidence_quality(content)

        # Calculate argumentation strength
        argument_strength = self._calculate_argument_strength(arguments, evidence_quality)

        # Assess persuasiveness
        persuasiveness = self._calculate_persuasiveness(arguments, evidence_quality, fallacies)

        # Classify debate type
        debate_type = self._classify_debate_type(content)

        return {
            'domain': 'debate',
            'topics': topics,
            'arguments': arguments,
            'logical_fallacies': fallacies,
            'evidence_quality': evidence_quality,
            'argument_strength': argument_strength,
            'persuasiveness_score': persuasiveness,
            'debate_type': debate_type,
            'content_type': 'debate_video',
            'engagement_score': self._calculate_debate_engagement(content),
            'confidence': 0.75
        }

    def _extract_arguments(self, content: str) -> List[Dict[str, Any]]:
        """Extract arguments from debate content"""
        arguments = []
        sentences = content.split('.')

        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 10:
                continue

            # Check if sentence contains argumentative language
            has_evidence = any(indicator in sentence.lower() for indicator in self.argumentation_indicators['evidence'])
            has_logic = any(indicator in sentence.lower() for indicator in self.argumentation_indicators['logic'])
            has_rhetoric = any(indicator in sentence.lower() for indicator in self.argumentation_indicators['rhetoric'])

            if has_evidence or has_logic or has_rhetoric:
                argument_type = 'evidence' if has_evidence else 'logic' if has_logic else 'rhetoric'

                arguments.append({
                    'text': sentence,
                    'type': argument_type,
                    'strength': self._assess_argument_strength(sentence)
                })

                if len(arguments) >= 10:  # Limit arguments
                    break

        return arguments

    def _detect_fallacies(self, content: str) -> List[str]:
        """Detect logical fallacies in debate content"""
        detected_fallacies = []
        content_lower = content.lower()

        # Simple fallacy detection based on keywords
        fallacy_indicators = {
            'ad hominem': ['stupid', 'idiot', 'fool', 'ignorant', 'incompetent'],
            'straw man': ['extremist', 'radical', 'extreme view', 'ridiculous claim'],
            'false dilemma': ['either or', 'black or white', 'only two choices'],
            'appeal to emotion': ['scary', 'terrifying', 'horrible outcome', 'disaster']
        }

        for fallacy, indicators in fallacy_indicators.items():
            if any(indicator in content_lower for indicator in indicators):
                detected_fallacies.append(fallacy)

        return detected_fallacies

    def _assess_evidence_quality(self, content: str) -> float:
        """Assess the quality of evidence presented"""
        evidence_indicators = self.argumentation_indicators['evidence']
        content_lower = content.lower()

        # Count evidence mentions
        evidence_count = sum(1 for indicator in evidence_indicators if indicator in content_lower)

        # Assess specificity (mentions of numbers, studies, etc.)
        specificity_indicators = ['study shows', 'research indicates', 'data reveals', 'statistics show', 'percent', 'number']
        specificity_count = sum(1 for indicator in specificity_indicators if indicator in content_lower)

        # Calculate quality score
        base_quality = min(evidence_count * 0.1, 0.5)
        specificity_boost = min(specificity_count * 0.15, 0.4)

        return min(base_quality + specificity_boost, 1.0)

    def _calculate_argument_strength(self, arguments: List[Dict], evidence_quality: float) -> float:
        """Calculate overall argument strength"""
        if not arguments:
            return 0.0

        # Average argument strength
        avg_strength = sum(arg['strength'] for arg in arguments) / len(arguments)

        # Boost from evidence quality
        evidence_boost = evidence_quality * 0.3

        # Quantity boost (more arguments generally stronger)
        quantity_boost = min(len(arguments) * 0.05, 0.2)

        return min(avg_strength + evidence_boost + quantity_boost, 1.0)

    def _calculate_persuasiveness(self, arguments: List[Dict], evidence_quality: float, fallacies: List[str]) -> float:
        """Calculate persuasiveness score"""
        base_persuasiveness = 0.5

        # Argument strength contribution
        argument_contribution = len(arguments) * 0.05

        # Evidence quality contribution
        evidence_contribution = evidence_quality * 0.3

        # Fallacy penalty
        fallacy_penalty = len(fallacies) * 0.1

        final_score = base_persuasiveness + argument_contribution + evidence_contribution - fallacy_penalty
        return max(0.0, min(final_score, 1.0))

    def _classify_debate_type(self, content: str) -> str:
        """Classify the type of debate"""
        content_lower = content.lower()

        if any(word in content_lower for word in ['political', 'policy', 'government', 'election']):
            return 'political'
        elif any(word in content_lower for word in ['philosophy', 'ethics', 'moral', 'existential']):
            return 'philosophical'
        elif any(word in content_lower for word in ['science', 'technology', 'research', 'study']):
            return 'scientific'
        elif any(word in content_lower for word in ['social', 'culture', 'society', 'community']):
            return 'social'
        else:
            return 'general'

    def _assess_argument_strength(self, argument_text: str) -> float:
        """Assess the strength of an individual argument"""
        strength = 0.5

        # Boost for evidence
        if any(indicator in argument_text.lower() for indicator in self.argumentation_indicators['evidence']):
            strength += 0.2

        # Boost for logic
        if any(indicator in argument_text.lower() for indicator in self.argumentation_indicators['logic']):
            strength += 0.15

        # Boost for rhetoric (but less than evidence/logic)
        if any(indicator in argument_text.lower() for indicator in self.argumentation_indicators['rhetoric']):
            strength += 0.1

        return min(strength, 1.0)

    def _calculate_debate_engagement(self, content: str) -> float:
        """Calculate engagement score for debate content"""
        engagement_indicators = ['question', 'challenge', 'counter', 'rebuttal', 'argue', 'debate']
        sentences = content.split('.')

        engagement_count = 0
        for sentence in sentences:
            if any(indicator in sentence.lower() for indicator in engagement_indicators):
                engagement_count += 1

        return min(engagement_count / len(sentences), 1.0) if sentences else 0.0

class PodcastAnalyzer(DomainAnalyzer):
    """Specialized analyzer for podcast content"""

    def __init__(self):
        self.podcast_formats = {
            'interview': ['interview', 'guest', 'host', 'conversation', 'chat'],
            'discussion': ['discuss', 'talk about', 'conversation', 'panel', 'roundtable'],
            'storytelling': ['story', 'narrative', 'tale', 'experience', 'journey'],
            'educational': ['learn', 'teach', 'explain', 'educational', 'informative']
        }

        self.engagement_indicators = {
            'questions': ['what do you think', 'how do you feel', 'tell me about', 'what was it like'],
            'active_listening': ['interesting', 'tell me more', 'go on', 'really', 'wow'],
            'follow_up': ['building on that', 'related to', 'speaking of', 'that reminds me']
        }

    def analyze_content(self, content: str) -> Dict[str, Any]:
        """Analyze podcast content with audio expertise"""

        topics = self.extract_topics(content)

        # Detect podcast format
        format_type = self._detect_podcast_format(content)

        # Calculate engagement score
        engagement_score = self._calculate_engagement_score(content)

        # Analyze conversation flow
        conversation_flow = self._analyze_conversation_flow(content)

        # Assess topic depth
        topic_depth = self._assess_topic_depth(content)

        # Predict audio viral potential
        viral_potential = self._predict_audio_virality(content, format_type, engagement_score)

        return {
            'domain': 'podcast',
            'topics': topics,
            'format_type': format_type,
            'engagement_score': engagement_score,
            'conversation_flow': conversation_flow,
            'topic_depth': topic_depth,
            'viral_potential': viral_potential,
            'content_type': 'podcast_episode',
            'audio_quality_score': self._assess_audio_quality(content),
            'confidence': 0.70
        }

    def _detect_podcast_format(self, content: str) -> str:
        """Detect the podcast format type"""
        content_lower = content.lower()

        format_scores = {}
        for format_type, indicators in self.podcast_formats.items():
            score = sum(1 for indicator in indicators if indicator in content_lower)
            format_scores[format_type] = score

        # Return format with highest score, default to discussion
        best_format = max(format_scores, key=format_scores.get)
        return best_format if format_scores[best_format] > 0 else 'discussion'

    def _calculate_engagement_score(self, content: str) -> float:
        """Calculate listener engagement score"""
        base_engagement = 0.5

        # Analyze question usage
        question_boost = self._analyze_question_usage(content) * 0.2

        # Analyze active listening
        listening_boost = self._analyze_active_listening(content) * 0.15

        # Analyze follow-up questions
        followup_boost = self._analyze_followup_questions(content) * 0.15

        # Conversation flow boost
        flow_boost = self._analyze_conversation_flow(content)['smoothness'] * 0.1

        final_score = base_engagement + question_boost + listening_boost + followup_boost + flow_boost
        return min(final_score, 1.0)

    def _analyze_question_usage(self, content: str) -> float:
        """Analyze how effectively questions are used"""
        sentences = content.split('.')

        question_count = sum(1 for s in sentences if '?' in s)
        total_sentences = len(sentences)

        if total_sentences == 0:
            return 0.0

        # Ideal question ratio for engaging podcast
        question_ratio = question_count / total_sentences
        ideal_ratio = 0.15  # 15% questions is very engaging

        # Score based on how close to ideal
        if question_ratio >= ideal_ratio:
            return 1.0
        else:
            return question_ratio / ideal_ratio

    def _analyze_active_listening(self, content: str) -> float:
        """Analyze active listening indicators"""
        content_lower = content.lower()

        listening_score = 0
        for category, indicators in self.engagement_indicators.items():
            if category == 'active_listening':
                matches = sum(1 for indicator in indicators if indicator in content_lower)
                listening_score += min(matches * 0.1, 0.3)  # Cap per category

        return listening_score

    def _analyze_followup_questions(self, content: str) -> float:
        """Analyze follow-up question usage"""
        followup_indicators = self.engagement_indicators['follow_up']
        content_lower = content.lower()

        followup_count = sum(1 for indicator in followup_indicators if indicator in content_lower)

        # Normalize to 0-1 scale
        return min(followup_count * 0.2, 1.0)

    def _analyze_conversation_flow(self, content: str) -> Dict[str, Any]:
        """Analyze the flow of conversation"""
        sentences = content.split('.')

        # Analyze transition smoothness
        transition_indicators = ['so', 'well', 'anyway', 'moving on', 'speaking of', 'that reminds me']
        transitions = sum(1 for s in sentences if any(indicator in s.lower() for indicator in transition_indicators))

        # Calculate flow metrics
        transition_ratio = transitions / len(sentences) if sentences else 0

        # Assess monologue vs dialogue
        avg_sentence_length = sum(len(s.split()) for s in sentences) / len(sentences) if sentences else 0

        # Shorter sentences often indicate more interactive dialogue
        dialogue_score = max(0, 1 - (avg_sentence_length / 50))  # Normalize

        smoothness = (transition_ratio + dialogue_score) / 2

        return {
            'transitions': transitions,
            'transition_ratio': transition_ratio,
            'avg_sentence_length': avg_sentence_length,
            'dialogue_score': dialogue_score,
            'smoothness': smoothness
        }

    def _assess_topic_depth(self, content: str) -> float:
        """Assess how deeply topics are explored"""
        # Analyze topic coverage and detail level
        words = content.split()
        word_count = len(words)

        # Depth indicators
        depth_indicators = [
            'because', 'therefore', 'however', 'moreover', 'furthermore',
            'specifically', 'particularly', 'essentially', 'fundamentally'
        ]

        depth_count = sum(1 for indicator in depth_indicators if indicator in content.lower())

        # Calculate depth score
        base_depth = min(word_count / 2000, 1.0)  # Longer content can be deeper
        depth_boost = min(depth_count * 0.05, 0.3)  # Depth indicators boost

        return min(base_depth + depth_boost, 1.0)

    def _predict_audio_virality(self, content: str, format_type: str, engagement_score: float) -> float:
        """Predict viral potential for audio content"""
        base_viral = 0.3  # Audio generally less viral than video

        # Format-specific multipliers
        format_multipliers = {
            'interview': 1.3,    # Celebrity interviews spread well
            'storytelling': 1.2, # Stories are shareable
            'discussion': 0.9,   # Discussions more niche
            'educational': 0.8  # Educational less viral
        }

        format_multiplier = format_multipliers.get(format_type, 1.0)

        # Engagement boost
        engagement_boost = engagement_score * 0.4

        # Content virality indicators
        viral_indicators = ['shocking', 'unbelievable', 'controversial', 'emotional', 'powerful story']
        viral_count = sum(1 for indicator in viral_indicators if indicator in content.lower())
        viral_boost = min(viral_count * 0.1, 0.2)

        final_viral = (base_viral + engagement_boost + viral_boost) * format_multiplier
        return min(final_viral, 1.0)

    def _assess_audio_quality(self, content: str) -> float:
        """Assess the quality of audio content (based on transcript)"""
        # This is a proxy based on transcript quality
        # In real implementation, would analyze actual audio

        # Analyze transcript quality as proxy for audio quality
        sentences = content.split('.')
        avg_sentence_length = sum(len(s.split()) for s in sentences) / len(sentences) if sentences else 0

        # Well-structured audio tends to have varied sentence lengths
        sentence_variation = self._calculate_sentence_variation(sentences)

        # Combine metrics
        length_score = min(avg_sentence_length / 20, 1.0)  # Ideal around 15-20 words
        variation_score = sentence_variation

        return (length_score + variation_score) / 2

    def _calculate_sentence_variation(self, sentences: List[str]) -> float:
        """Calculate sentence length variation"""
        if len(sentences) < 2:
            return 0.5

        lengths = [len(s.split()) for s in sentences if s.strip()]
        if not lengths:
            return 0.5

        avg_length = sum(lengths) / len(lengths)
        variation = sum(abs(l - avg_length) for l in lengths) / len(lengths)

        # Normalize variation (some variation is good, too much is bad)
        normalized_variation = min(variation / avg_length, 1.0)
        return max(0, 1 - normalized_variation)  # Higher variation = lower score
