import os
import requests
import json
from dotenv import load_dotenv
load_dotenv()

api_key = os.environ["GROQ_API_KEY"]

candidates = [
    {
        "id": "c0",
        "start": 10.0,
        "end": 45.0,
        "duration": 35.0,
        "text": "And that is why building a startup is so hard. You spend 3 months polishing a product that nobody wants because you didn't do customer development. Customer development is the single most important thing. If you don't talk to customers, you are building in a vacuum.",
        "viral_score": 0.85,
        "reason": "validation"
    },
    {
        "id": "c1",
        "start": 50.0,
        "end": 75.0,
        "duration": 25.0,
        "text": "Yeah, I mean, it's just some basic code. We wrote a React app and put a Node backend on it. Nothing special.",
        "viral_score": 0.35,
        "reason": "backfill"
    },
    {
        "id": "c2",
        "start": 80.0,
        "end": 115.0,
        "duration": 35.0,
        "text": "Here's the contrarian take: raising venture capital is actually a disadvantage for 90% of SaaS companies. When you raise VC, you are forced to go for a 10x exit or die. But if you bootstrap, you can build a highly profitable $5M/year business that you own 100% of.",
        "viral_score": 0.78,
        "reason": "validation"
    }
]

groq_input = []
for c in candidates:
    groq_input.append({
        "candidate_id": str(c.get("id")),
        "start": round(float(c.get("start", 0)), 2),
        "end": round(float(c.get("end", 0)), 2),
        "duration": round(float(c.get("duration", 0)), 2),
        "text": str(c.get("text", "")).strip(),
        "existing_score": round(float(c.get("viral_score", 0)), 2),
        "existing_reason": str(c.get("reason", "none"))
    })

prompt_json = json.dumps(groq_input, indent=2)

from viral_finder.groq_cortex import _get_groq_model, _get_timeout

# Import the system prompt by reading groq_cortex.py file directly to avoid import issues
with open("viral_finder/groq_cortex.py", "r", encoding="utf-8") as f:
    code = f.read()

# Extract system prompt from the file
start_idx = code.find('system_prompt = """') + len('system_prompt = """')
end_idx = code.find('""".replace("{{CANDIDATES_JSON}}", prompt_json)')
system_prompt = code[start_idx:end_idx].strip()
system_prompt = system_prompt.replace("{{CANDIDATES_JSON}}", prompt_json)

resp = requests.post(
    "https://api.groq.com/openai/v1/chat/completions",
    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    json={
        "model": _get_groq_model(),
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "user", "content": system_prompt}]
    },
    timeout=_get_timeout()
)

print(json.dumps(resp.json(), indent=2))
