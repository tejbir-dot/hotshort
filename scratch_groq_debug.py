import os, requests, json
from dotenv import load_dotenv
load_dotenv()

api_key = os.environ["GROQ_API_KEY"]
prompt = (
    'Review these 2 clips. Return ONLY valid JSON with this exact structure:\n'
    '{\n'
    '  "clips": [\n'
    '    {\n'
    '      "candidate_id": "c0",\n'
    '      "viral_score": 85,\n'
    '      "confidence": 80,\n'
    '      "title": "...",\n'
    '      "hook_type": "...",\n'
    '      "completeness_score": 80,\n'
    '      "why_dangerous_hook": "...",\n'
    '      "why_people_keep_watching": "...",\n'
    '      "payoff": "...",\n'
    '      "retention_risk": "...",\n'
    '      "start_adjustment_seconds": 0,\n'
    '      "end_adjustment_seconds": 0,\n'
    '      "learning_signal_for_hotshort": {\n'
    '        "meaning_pattern": "...",\n'
    '        "psychological_trigger": "..."\n'
    '      }\n'
    '    }\n'
    '  ],\n'
    '  "rejected_candidates": []\n'
    '}\n\n'
    'Candidates:\n'
    '[\n'
    '  {"candidate_id": "c0", "text": "Alright everyone. Welcome to the unveiling. Introducing the Quantum Core.", "start": 1.0, "end": 18.0, "existing_score": 0.71},\n'
    '  {"candidate_id": "c2", "text": "But there is always a but. We found an anomaly. The Quantum Core is sentient. It is alive. We do not know how.", "start": 41.0, "end": 61.0, "existing_score": 0.83}\n'
    ']\n'
    'IMPORTANT: viral_score is required for every clip. Use integers 0-100.'
)

resp = requests.post(
    "https://api.groq.com/openai/v1/chat/completions",
    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    json={
        "model": "llama-3.1-8b-instant",
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "user", "content": prompt}]
    },
    timeout=25
)
data = resp.json()
print(data["choices"][0]["message"]["content"][:3000])
