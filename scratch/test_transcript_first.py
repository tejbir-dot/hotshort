import os
import unittest
from unittest.mock import patch, MagicMock

# Set env vars for testing
os.environ["HS_GROQ_CORTEX_ENABLED"] = "1"
os.environ["GROQ_API_KEY"] = "mock-key"
os.environ["HS_GROQ_TRANSCRIPT_FIRST"] = "1"
os.environ["HS_GROQ_DIRECTOR_MIN_SCORE"] = "72"

from viral_finder.groq_cortex import (
    _chunk_transcript,
    validate_groq_moments,
    dedupe_moments,
    find_moments_from_transcript
)
from viral_finder.orchestrator import _final_quality_reject_reasons, _final_quality_rescue


class TestTranscriptFirst(unittest.TestCase):
    def test_chunk_transcript(self):
        # 1. Test chunking with overlap
        segments = [
            {"start": 0.0, "end": 10.0, "text": "Hello"},
            {"start": 120.0, "end": 130.0, "text": "World"},
            {"start": 230.0, "end": 240.0, "text": "This is"},
            {"start": 250.0, "end": 260.0, "text": "A test"},
            {"start": 400.0, "end": 410.0, "text": "Ending"}
        ]
        
        chunks = _chunk_transcript(segments, video_duration=450.0, window_size=240.0, overlap=30.0)
        # Expected chunks:
        # Chunk 0: [0.0, 240.0] -> includes 0, 120, 230
        # Chunk 1: [210.0, 450.0] -> includes 230, 250, 400
        
        self.assertTrue(len(chunks) >= 2)
        
        chunk0_starts = [s["start"] for s in chunks[0]["segments"]]
        chunk1_starts = [s["start"] for s in chunks[1]["segments"]]
        
        self.assertIn(0.0, chunk0_starts)
        self.assertIn(120.0, chunk0_starts)
        self.assertIn(230.0, chunk0_starts)
        
        self.assertIn(230.0, chunk1_starts)
        self.assertIn(250.0, chunk1_starts)
        self.assertIn(400.0, chunk1_starts)

    def test_validate_groq_moments(self):
        # Test validation and exception pass
        moments = [
            # Valid normal pass (score >= 72)
            {
                "start": 10.0,
                "end": 30.0,
                "viral_score": 85,
                "title": "Good hook"
            },
            # Invalid (duration too short)
            {
                "start": 10.0,
                "end": 14.0,
                "viral_score": 90,
                "title": "Too short"
            },
            # Below min_score (72) but has usefulness >= 80 (exceptional pass)
            {
                "start": 40.0,
                "end": 70.0,
                "viral_score": 65,
                "usefulness": 85,
                "insight_strength": 50,
                "title": "Exceptional usefulness"
            },
            # Below min_score (72) but has insight_strength >= 80 (exceptional pass)
            {
                "start": 80.0,
                "end": 110.0,
                "viral_score": 60,
                "usefulness": 40,
                "insight_strength": 90,
                "title": "Exceptional insight"
            },
            # Below min_score, not exceptional (rejected)
            {
                "start": 120.0,
                "end": 150.0,
                "viral_score": 65,
                "usefulness": 50,
                "insight_strength": 50,
                "title": "Not good enough"
            }
        ]
        
        validated = validate_groq_moments(moments, video_duration=200.0)
        titles = [m["title"] for m in validated]
        
        self.assertIn("Good hook", titles)
        self.assertNotIn("Too short", titles)
        self.assertIn("Exceptional usefulness", titles)
        self.assertIn("Exceptional insight", titles)
        self.assertNotIn("Not good enough", titles)

    def test_dedupe_moments(self):
        moments = [
            # Overlapping pair: keep higher score (85 over 75)
            {
                "start": 10.0,
                "end": 40.0,
                "viral_score": 75,
                "title": "Lower score overlap"
            },
            {
                "start": 12.0,
                "end": 41.0,
                "viral_score": 85,
                "title": "Higher score overlap"
            },
            # Non-overlapping
            {
                "start": 60.0,
                "end": 90.0,
                "viral_score": 80,
                "title": "Non-overlapping"
            }
        ]
        
        deduped = dedupe_moments(moments, threshold=0.70)
        titles = [m["title"] for m in deduped]
        
        self.assertIn("Higher score overlap", titles)
        self.assertNotIn("Lower score overlap", titles)
        self.assertIn("Non-overlapping", titles)

    @patch("requests.post")
    def test_find_moments_from_transcript(self, mock_post):
        # Mock requests.post response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": '{"moments": [{"start": 10.0, "end": 40.0, "viral_score": 88, "title": "Mock Moment", "opening_caption": "Start here", "clip_archetype": "story", "editing_notes": {"subtitle_style": "classic"}}]}'
                    }
                }
            ]
        }
        mock_post.return_value = mock_response
        
        segments = [{"start": float(i), "end": float(i+5), "text": f"text {i}"} for i in range(0, 100, 5)]
        moments = find_moments_from_transcript(segments, video_duration=120.0)
        
        self.assertEqual(len(moments), 1)
        self.assertEqual(moments[0]["title"], "Mock Moment")
        self.assertEqual(moments[0]["viral_score"], 88.0)

    def test_validation_relaxations(self):
        # Ensure groq_moment / cortex_enabled candidates bypass quality reject checks and rescue successfully
        cand_groq = {
            "start": 10.0,
            "end": 35.0,
            "duration": 25.0,
            "groq_moment": True,
            "cortex_enabled": True,
            "hook_strength": 0.05,
            "payoff_score": 0.05,
            "motion": 0.0
        }
        
        reasons = _final_quality_reject_reasons(cand_groq)
        is_rescued = _final_quality_rescue(cand_groq)
        
        self.assertEqual(reasons, [])
        self.assertTrue(is_rescued)

    def test_validation_incomplete_payoff(self):
        # 1. incomplete payoff with allowed archetype passes
        moments = [
            {
                "start": 10.0,
                "end": 35.0,
                "viral_score": 80,
                "completeness_score": 50, # low
                "clip_archetype": "curiosity_loop", # allowed
                "title": "Allowed curiosity loop"
            },
            {
                "start": 40.0,
                "end": 65.0,
                "viral_score": 80,
                "completeness_score": 50, # low
                "clip_archetype": "practical_steps", # NOT allowed
                "title": "Not allowed practical steps"
            }
        ]
        validated = validate_groq_moments(moments, video_duration=100.0)
        titles = [m["title"] for m in validated]
        self.assertIn("Allowed curiosity loop", titles)
        self.assertNotIn("Not allowed practical steps", titles)

    @patch("requests.post")
    def test_find_moments_429_retry(self, mock_post):
        # First call: return 429, Second call: return 200 with moments
        mock_response_429 = MagicMock()
        mock_response_429.status_code = 429
        
        mock_response_200 = MagicMock()
        mock_response_200.status_code = 200
        mock_response_200.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": '{"moments": [{"start": 10.0, "end": 40.0, "viral_score": 88, "title": "Success Moment"}]}'
                    }
                }
            ]
        }
        
        mock_post.side_effect = [mock_response_429, mock_response_200]
        
        segments = [{"start": float(i), "end": float(i+5), "text": f"text {i}"} for i in range(0, 100, 5)]
        moments = find_moments_from_transcript(segments, video_duration=120.0)
        
        self.assertEqual(len(moments), 1)
        self.assertEqual(moments[0]["title"], "Success Moment")

    @patch("requests.post")
    def test_rescue_fallback(self, mock_post):
        # Groq returns moments, but all get rejected (e.g. duration too short for normal validation)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": '{"moments": [{"start": 10.0, "end": 16.0, "viral_score": 90, "title": "Too short raw"}]}'
                    }
                }
            ]
        }
        mock_post.return_value = mock_response
        
        segments = [{"start": float(i), "end": float(i+5), "text": f"text {i}"} for i in range(0, 100, 5)]
        moments = find_moments_from_transcript(segments, video_duration=120.0)
        
        # Should rescue the raw moment!
        self.assertEqual(len(moments), 1)
        self.assertEqual(moments[0]["title"], "Too short raw")
        self.assertEqual(moments[0]["reason"], "groq_director_rescue")
        self.assertTrue(moments[0]["needs_manual_review"])


if __name__ == "__main__":
    unittest.main()
