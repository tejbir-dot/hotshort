import os
import time
import requests
import json
from dotenv import load_dotenv

load_dotenv()

OPEN_ROUTER_API = os.getenv("OPEN_ROUTER_API")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

sample_transcript = [
  {"start": 10.0, "end": 15.0, "text": "Yaar jadon main pehli vaar startup shuru kitta si na, mainu lagga si sab easy aa."},
  {"start": 15.0, "end": 20.0, "text": "Par funding milan toh baad pata lagga asli game taan hun shuru hoyi aa."},
  {"start": 20.0, "end": 25.0, "text": "Log kehnde ne ki you just need an idea, bro, no, you need a team."},
  {"start": 25.0, "end": 30.0, "text": "Jehdi team 2 vaje raat nu uth ke bug fix kar sake."},
  {"start": 30.0, "end": 35.0, "text": "Otherwise tuhada competitor thonu kha jauga, straight up."},
  {"start": 35.0, "end": 40.0, "text": "Paisa machana is not the goal, surviving is the goal."}
]

system_prompt = """
You are HotShort Moment Director: a world-class short-form content director.
Read the transcript segments (Hinglish/Punjabi) and identify the single most valuable viral moment.
Return JSON ONLY with this structure:
{
  "moments": [
    {
      "start": 0.0,
      "end": 0.0,
      "viral_score": 90,
      "title": "Title here",
      "why_valuable": "Why this works in the cultural context of the language used."
    }
  ]
}
"""

def call_groq():
    print("\\n--- GROQ (Llama-3.1-70b-versatile) ---")
    start_t = time.time()
    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(sample_transcript)}
                ],
                "response_format": {"type": "json_object"},
                "max_tokens": 500
            }
        )
        print(f"Time: {time.time() - start_t:.2f}s")
        print(json.dumps(response.json()["choices"][0]["message"]["content"], indent=2))
    except Exception as e:
        print("Groq failed:", e)
        if 'response' in locals():
            print(response.text)

def call_qwen():
    print("\\n--- QWEN (qwen/qwen-2.5-72b-instruct via OpenRouter) ---")
    start_t = time.time()
    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPEN_ROUTER_API}"},
            json={
                "model": "qwen/qwen-2.5-72b-instruct",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(sample_transcript)}
                ],
                "response_format": {"type": "json_object"},
                "max_tokens": 500
            }
        )
        print(f"Time: {time.time() - start_t:.2f}s")
        print(json.dumps(response.json()["choices"][0]["message"]["content"], indent=2))
    except Exception as e:
        print("Qwen failed:", e)
        if 'response' in locals():
            print(response.text)

if __name__ == "__main__":
    call_groq()
    call_qwen()
