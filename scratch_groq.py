import os
import json
from unittest import mock

# Set up env variables for testing
os.environ["HS_GROQ_CORTEX_ENABLED"] = "1"
os.environ["GROQ_API_KEY"] = "fake-key"
os.environ["HS_GROQ_LOG_REASONING"] = "1"

from viral_finder.groq_cortex import review_candidates_with_groq

def test_groq_integration():
    print("Testing Groq Cortex Integration...")
    candidates = [
        {
            "start": 10.5,
            "end": 35.0,
            "duration": 24.5,
            "text": "This is a great hook right here. And the payoff is mind-blowing.",
            "viral_score": 0.85,
            "reason": "semantic arc match"
        },
        {
            "start": 50.0,
            "end": 80.0,
            "duration": 30.0,
            "text": "Another clip, but it's okay.",
            "viral_score": 0.60,
            "reason": "backfill"
        }
    ]

    mock_response = {
        "clips": [
            {
                "candidate_id": "c0",
                "start_adjustment_seconds": 1.5,
                "end_adjustment_seconds": -2.0,
                "viral_score": 0.95,
                "confidence": 0.9,
                "title": "Mind-blowing Payoff",
                "opening_caption": "Wait for it...",
                "hook_type": "Curiosity",
                "completeness_score": 0.9,
                "why_dangerous_hook": "High tension.",
                "why_people_keep_watching": "Suspense.",
                "learning_signal_for_hotshort": {"meaning_pattern": "Contradiction"}
            }
        ],
        "rejected_candidates": [
            {
                "candidate_id": "c1",
                "reason": "Not strong enough."
            }
        ]
    }

    mock_requests_post = mock.Mock()
    mock_requests_post.return_value.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(mock_response)
                }
            }
        ]
    }
    
    # Mock requests.post
    with mock.patch("requests.post", mock_requests_post):
        results = review_candidates_with_groq(candidates)
        
    print(f"Original candidates: {len(candidates)}")
    print(f"Returned candidates: {len(results)}")
    
    if len(results) == 1:
        print("Success! Filtered properly.")
        c = results[0]
        print(f"cortex_enabled: {c.get('cortex_enabled')}")
        print(f"viral_score: {c.get('viral_score')}")
        print(f"title: {c.get('title')}")
        print(f"start (adjusted): {c.get('start')} (orig: 10.5 + 1.5 = 12.0)")
        print(f"end (adjusted): {c.get('end')} (orig: 35.0 - 2.0 = 33.0)")
    else:
        print("Failed. Result length should be 1.")

if __name__ == "__main__":
    test_groq_integration()
