#!/usr/bin/env python3
"""
🧠 Multi-Domain Knowledge Injection System for HotShort
Making the AI extremely intelligent with diverse domain knowledge
"""

import os
import json
import time
import logging
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)

@dataclass
class KnowledgeItem:
    """Represents a piece of domain knowledge"""
    domain: str
    topic: str
    content: str
    expertise_level: str
    quality_score: float
    source: str
    timestamp: datetime
    metadata: Dict[str, Any]

class DomainKnowledgeBase:
    """Central knowledge base for all domains"""

    def __init__(self):
        self.domains = {}
        self.knowledge_store = {}
        self.domain_analyzers = {}
        self._initialize_domains()

    def _initialize_domains(self):
        """Initialize all domain analyzers"""
        from .domain_analyzers import (
            EducationAnalyzer, EntertainmentAnalyzer,
            DebateAnalyzer, PodcastAnalyzer
        )

        self.domain_analyzers = {
            'education': EducationAnalyzer(),
            'entertainment': EntertainmentAnalyzer(),
            'debate': DebateAnalyzer(),
            'podcast': PodcastAnalyzer()
        }

        # Initialize empty knowledge stores
        for domain in self.domain_analyzers.keys():
            self.knowledge_store[domain] = []

    def inject_knowledge(self, domain: str, knowledge_data: Dict[str, Any]):
        """Inject knowledge into specific domain"""

        if domain not in self.domain_analyzers:
            logger.warning(f"Unknown domain: {domain}")
            return False

        # Validate knowledge data
        if not self._validate_knowledge_data(knowledge_data):
            return False

        # Create knowledge item
        knowledge_item = KnowledgeItem(
            domain=domain,
            topic=knowledge_data.get('topic', ''),
            content=knowledge_data.get('content', ''),
            expertise_level=knowledge_data.get('expertise_level', 'intermediate'),
            quality_score=knowledge_data.get('quality_score', 0.8),
            source=knowledge_data.get('source', 'unknown'),
            timestamp=datetime.now(),
            metadata=knowledge_data.get('metadata', {})
        )

        # Store knowledge
        self.knowledge_store[domain].append(knowledge_item)

        logger.info(f"Injected knowledge: {domain}/{knowledge_item.topic}")
        return True

    def get_domain_expertise(self, domain: str, topic: str) -> List[KnowledgeItem]:
        """Get relevant knowledge for domain and topic"""

        if domain not in self.knowledge_store:
            return []

        # Find relevant knowledge items
        relevant_knowledge = []
        for item in self.knowledge_store[domain]:
            if self._is_topic_relevant(item.topic, topic):
                relevant_knowledge.append(item)

        # Sort by quality and recency
        relevant_knowledge.sort(
            key=lambda x: (x.quality_score, x.timestamp),
            reverse=True
        )

        return relevant_knowledge[:10]  # Top 10 most relevant

    def analyze_content_with_knowledge(self, content: str, detected_domain: str) -> Dict[str, Any]:
        """Analyze content using domain-specific knowledge"""

        if detected_domain not in self.domain_analyzers:
            detected_domain = 'education'  # Default fallback

        analyzer = self.domain_analyzers[detected_domain]

        # Get basic analysis
        basic_analysis = analyzer.analyze_content(content)

        # Enhance with knowledge
        topics = basic_analysis.get('topics', [])
        enhanced_analysis = basic_analysis.copy()

        if topics:
            relevant_knowledge = []
            for topic in topics:
                knowledge = self.get_domain_expertise(detected_domain, topic)
                relevant_knowledge.extend(knowledge)

            # Apply knowledge enhancement
            enhanced_analysis['knowledge_enhanced'] = True
            enhanced_analysis['relevant_knowledge'] = len(relevant_knowledge)
            enhanced_analysis['intelligence_boost'] = self._calculate_intelligence_boost(
                basic_analysis, relevant_knowledge
            )

        return enhanced_analysis

    def _validate_knowledge_data(self, data: Dict[str, Any]) -> bool:
        """Validate knowledge data structure"""
        required_fields = ['topic', 'content']
        return all(field in data for field in required_fields)

    def _is_topic_relevant(self, item_topic: str, query_topic: str) -> bool:
        """Check if knowledge item is relevant to query topic"""
        # Simple relevance check - can be enhanced with embeddings
        item_words = set(item_topic.lower().split())
        query_words = set(query_topic.lower().split())

        overlap = len(item_words.intersection(query_words))
        return overlap > 0 or item_topic.lower() in query_topic.lower()

    def _calculate_intelligence_boost(self, analysis: Dict, knowledge: List[KnowledgeItem]) -> float:
        """Calculate intelligence boost from knowledge injection"""
        base_boost = 0.1  # Base intelligence improvement

        # Boost based on knowledge quality and quantity
        quality_boost = sum(k.quality_score for k in knowledge) / max(len(knowledge), 1) * 0.2
        quantity_boost = min(len(knowledge) * 0.05, 0.3)  # Cap at 0.3

        return base_boost + quality_boost + quantity_boost

class KnowledgeInjector:
    """Handles injection of knowledge from various sources"""

    def __init__(self):
        self.knowledge_base = DomainKnowledgeBase()
        self.injection_stats = {
            'total_injected': 0,
            'domains_covered': set(),
            'sources_used': set(),
            'last_injection': None
        }

    def inject_from_file(self, file_path: str, domain: str) -> Dict[str, Any]:
        """Inject knowledge from JSON file"""

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if isinstance(data, list):
                injected_count = 0
                for item in data:
                    item['source'] = f"file:{os.path.basename(file_path)}"
                    if self.knowledge_base.inject_knowledge(domain, item):
                        injected_count += 1
            else:
                data['source'] = f"file:{os.path.basename(file_path)}"
                injected_count = 1 if self.knowledge_base.inject_knowledge(domain, data) else 0

            # Update stats
            self.injection_stats['total_injected'] += injected_count
            self.injection_stats['domains_covered'].add(domain)
            self.injection_stats['sources_used'].add(f"file:{file_path}")
            self.injection_stats['last_injection'] = datetime.now()

            return {
                'status': 'success',
                'injected_count': injected_count,
                'domain': domain,
                'source': file_path
            }

        except Exception as e:
            logger.error(f"Failed to inject from file {file_path}: {e}")
            return {
                'status': 'error',
                'error': str(e),
                'domain': domain,
                'source': file_path
            }

    def inject_bulk_knowledge(self, knowledge_list: List[Dict], domain: str) -> Dict[str, Any]:
        """Inject multiple knowledge items at once"""

        injected_count = 0
        errors = []

        for item in knowledge_list:
            try:
                if self.knowledge_base.inject_knowledge(domain, item):
                    injected_count += 1
                else:
                    errors.append(f"Failed to inject item: {item.get('topic', 'unknown')}")
            except Exception as e:
                errors.append(f"Error injecting {item.get('topic', 'unknown')}: {e}")

        # Update stats
        self.injection_stats['total_injected'] += injected_count
        self.injection_stats['domains_covered'].add(domain)
        self.injection_stats['last_injection'] = datetime.now()

        return {
            'status': 'completed',
            'injected_count': injected_count,
            'errors': errors,
            'domain': domain,
            'success_rate': injected_count / len(knowledge_list) if knowledge_list else 0
        }

    def get_injection_stats(self) -> Dict[str, Any]:
        """Get knowledge injection statistics"""
        return {
            'total_injected': self.injection_stats['total_injected'],
            'domains_covered': list(self.injection_stats['domains_covered']),
            'sources_used': list(self.injection_stats['sources_used']),
            'last_injection': self.injection_stats['last_injection'].isoformat() if self.injection_stats['last_injection'] else None,
            'knowledge_per_domain': {
                domain: len(knowledge)
                for domain, knowledge in self.knowledge_base.knowledge_store.items()
            }
        }

class IntelligentContentAnalyzer:
    """Main analyzer that uses multi-domain knowledge"""

    def __init__(self):
        self.knowledge_base = DomainKnowledgeBase()
        self.domain_detector = DomainDetector()

    def analyze_video_content(self, video_data: Dict[str, Any]) -> Dict[str, Any]:
        """Perform intelligent analysis using domain knowledge"""

        transcript = video_data.get('transcript', '')
        title = video_data.get('title', '')
        description = video_data.get('description', '')

        # Detect domain
        detected_domain = self.domain_detector.detect_domain(transcript, title, description)

        # Basic content analysis
        basic_analysis = self._perform_basic_analysis(transcript)

        # Enhance with domain knowledge
        enhanced_analysis = self.knowledge_base.analyze_content_with_knowledge(
            transcript, detected_domain
        )

        # Combine results
        final_analysis = {
            'detected_domain': detected_domain,
            'basic_analysis': basic_analysis,
            'enhanced_analysis': enhanced_analysis,
            'intelligence_level': self._calculate_intelligence_level(enhanced_analysis),
            'confidence_score': enhanced_analysis.get('confidence', 0.8),
            'knowledge_boost': enhanced_analysis.get('intelligence_boost', 0.0)
        }

        return final_analysis

    def _perform_basic_analysis(self, transcript: str) -> Dict[str, Any]:
        """Perform basic content analysis"""
        return {
            'word_count': len(transcript.split()),
            'sentence_count': len(transcript.split('.')),
            'topics': self._extract_topics(transcript),
            'sentiment': self._analyze_sentiment(transcript),
            'complexity': self._calculate_complexity(transcript)
        }

    def _extract_topics(self, text: str) -> List[str]:
        """Simple topic extraction - can be enhanced with NLP"""
        # Basic keyword extraction
        words = text.lower().split()
        common_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by'}

        topics = []
        for word in words:
            if len(word) > 4 and word not in common_words:
                if word not in topics:
                    topics.append(word)
                if len(topics) >= 10:  # Limit topics
                    break

        return topics

    def _analyze_sentiment(self, text: str) -> str:
        """Basic sentiment analysis"""
        positive_words = {'good', 'great', 'excellent', 'amazing', 'wonderful', 'fantastic'}
        negative_words = {'bad', 'terrible', 'awful', 'horrible', 'worst'}

        words = text.lower().split()
        positive_count = sum(1 for word in words if word in positive_words)
        negative_count = sum(1 for word in words if word in negative_words)

        if positive_count > negative_count:
            return 'positive'
        elif negative_count > positive_count:
            return 'negative'
        else:
            return 'neutral'

    def _calculate_complexity(self, text: str) -> float:
        """Calculate text complexity score"""
        words = text.split()
        avg_word_length = sum(len(word) for word in words) / len(words) if words else 0
        return min(avg_word_length / 10.0, 1.0)  # Normalize to 0-1

    def _calculate_intelligence_level(self, enhanced_analysis: Dict) -> str:
        """Calculate overall intelligence level of analysis"""
        knowledge_boost = enhanced_analysis.get('intelligence_boost', 0)
        relevant_knowledge = enhanced_analysis.get('relevant_knowledge', 0)

        if knowledge_boost > 0.5 and relevant_knowledge > 5:
            return 'expert'
        elif knowledge_boost > 0.3 and relevant_knowledge > 2:
            return 'advanced'
        elif knowledge_boost > 0.1:
            return 'intermediate'
        else:
            return 'basic'

class DomainDetector:
    """Detects the primary domain of content"""

    def __init__(self):
        self.domain_keywords = {
            'education': {
                'keywords': ['learn', 'teach', 'course', 'tutorial', 'lesson', 'study', 'education', 'academic'],
                'weight': 1.0
            },
            'entertainment': {
                'keywords': ['fun', 'entertainment', 'movie', 'show', 'comedy', 'drama', 'action', 'horror'],
                'weight': 1.0
            },
            'debate': {
                'keywords': ['debate', 'argument', 'discuss', 'opinion', 'controversy', 'politics', 'versus'],
                'weight': 1.0
            },
            'podcast': {
                'keywords': ['podcast', 'episode', 'host', 'guest', 'interview', 'conversation', 'audio'],
                'weight': 1.0
            }
        }

    def detect_domain(self, transcript: str, title: str = '', description: str = '') -> str:
        """Detect the primary domain of content"""

        # Combine all text
        full_text = f"{title} {description} {transcript}".lower()

        # Calculate domain scores
        domain_scores = {}
        for domain, config in self.domain_keywords.items():
            keywords = config['keywords']
            weight = config['weight']

            # Count keyword matches
            matches = sum(1 for keyword in keywords if keyword in full_text)
            score = matches * weight

            domain_scores[domain] = score

        # Return domain with highest score
        best_domain = max(domain_scores, key=domain_scores.get)

        # If no clear domain detected, default to education
        if domain_scores[best_domain] == 0:
            return 'education'

        return best_domain
