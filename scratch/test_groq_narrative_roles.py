import os
import sys
import json
import requests
import time

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Load .env
env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            if '=' in line and not line.startswith('#'):
                k, v = line.strip().split('=', 1)
                os.environ[k] = v

from viral_finder.groq_cortex import _get_groq_api_key, _get_groq_model, _get_timeout

def legacy_keyword_detector(transcript_segments):
    """The current naive string-matching implementation from orchestrator.py"""
    _HOOK_HI = (
        "kya aap jante hain", "kya aapko pata hai", "socho", "imagine karo",
        "kabhi socha", "aisa kyun", "ye kyun hota hai",
        "क्या आप जानते हैं", "क्या आपको पता है", "सोचो", "क्यों",
    )
    _PAYOFF_HI = (
        "isliye", "to baat ye hai", "yahi wajah hai", "yahi karan hai",
        "matlab ye hai", "seedhi baat", "sach ye hai", "asal mein",
        "yaad rakho", "akhir mein", "to samjho", "sach baat",
        "इसलिए", "तो बात ये है", "यही वजह है", "यही कारण है",
        "मतलब ये है", "सीधी बात", "सच ये है", "असल में",
        "याद रखो", "आखिरकार", "तो समझो",
    )
    _BUILD_HI = (
        "kyunki", "to", "phir", "uske baad", "aur phir", "jaise ki",
        "क्योंकि", "तो", "फिर", "उसके बाद", "और फिर", "जैसे कि",
    )

    roles = []
    for idx, seg in enumerate(transcript_segments):
        txt = str(seg.get("text", "") or "").lower()
        if (
            "?" in txt
            or any(k in txt for k in ("did you know", "what if", "ever wondered"))
            or any(k in txt for k in _HOOK_HI)
        ):
            role = "HOOK"
        elif (
            any(k in txt for k in ("that's why", "the point is", "in conclusion", "bottom line", "therefore"))
            or any(k in txt for k in _PAYOFF_HI)
        ):
            role = "PAYOFF"
        elif (
            any(k in txt for k in ("because", "so", "for example", "then", "next"))
            or any(k in txt for k in _BUILD_HI)
        ):
            role = "BUILD"
        else:
            role = "BUILD"
        roles.append({"idx": idx, "text": seg.get("text", ""), "role": role})
    return roles

def groq_narrative_detector(transcript_segments):
    """The experimental Groq LLM Narrative Role detector"""
    api_key = _get_groq_api_key()
    if not api_key:
        print("Missing Groq API Key")
        return []

    # Prepare minimal input for Groq (save tokens)
    groq_input = []
    for idx, s in enumerate(transcript_segments):
        groq_input.append({
            "id": idx,
            "text": str(s.get("text", "")).strip()
        })
        
    prompt_json = json.dumps(groq_input, indent=2)
    
    system_prompt = """
You are a world-class Narrative Analyst for short-form video.
Read the following transcript segments and assign EXACTLY ONE narrative role to EACH segment.

Valid roles:
1. HOOK: A question, bold claim, or pattern interrupt that grabs attention.
2. STORY: A personal anecdote, example, or narrative progression.
3. PROOF: Data, evidence, or logical justification for a claim.
4. LESSON: The core teaching, framework, or actionable takeaway.
5. PAYOFF: The final satisfying conclusion, punchline, or "aha!" moment.
6. BUILD: General context or setup that doesn't fit the above.

OUTPUT JSON ONLY.
Return this exact structure:
{
  "segments": [
    {"id": 0, "role": "HOOK"},
    {"id": 1, "role": "STORY"},
    {"id": 2, "role": "BUILD"}
  ]
}

Transcript:
""" + prompt_json

    print("Calling Groq API (this may take a few seconds)...")
    response = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        },
        json={
            "model": _get_groq_model(),
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": system_prompt}]
        },
        timeout=45
    )
    
    if response.status_code != 200:
        print(f"Groq API Error: {response.status_code} - {response.text}")
        return []
        
    try:
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        
        # Merge back with transcript text
        results = []
        seg_dict = {s["id"]: s["role"] for s in parsed.get("segments", [])}
        for idx, seg in enumerate(transcript_segments):
            role = seg_dict.get(idx, "BUILD")
            results.append({"idx": idx, "text": seg.get("text", ""), "role": role})
        return results
    except Exception as e:
        print(f"Failed to parse Groq response: {e}")
        return []

def main():
    # Use a real snippet from a business/marketing podcast for testing
    sample_transcript = [
        {"start": 0.0, "end": 2.5, "text": "Are you struggling to get your first 1000 subscribers on YouTube?"},
        {"start": 2.5, "end": 5.0, "text": "Most people think it takes years of grinding."},
        {"start": 5.0, "end": 7.5, "text": "When I started my channel back in 2018, I posted 50 videos."},
        {"start": 7.5, "end": 9.2, "text": "And you know what happened? Absolutely nothing."},
        {"start": 9.2, "end": 12.0, "text": "Then I looked at the data and realized my thumbnails were terrible."},
        {"start": 12.0, "end": 15.5, "text": "So I spent a week studying human psychology and color theory."},
        {"start": 15.5, "end": 18.0, "text": "The framework is simple: high contrast, one face, three words maximum."},
        {"start": 18.0, "end": 21.0, "text": "Because if people can't read it on a tiny phone screen, they won't click."},
        {"start": 21.0, "end": 24.5, "text": "That's why focusing on your content before your packaging is a fatal mistake."},
        {"start": 24.5, "end": 27.0, "text": "Fix the thumbnail first, and the views will follow."}
    ]

    print(f"Running Narrative Intelligence Experiment on {len(sample_transcript)} segments...\n")
    
    legacy_roles = legacy_keyword_detector(sample_transcript)
    groq_roles = groq_narrative_detector(sample_transcript)

    print(f"{'TEXT':<75} | {'LEGACY':<10} | {'GROQ':<10}")
    print("-" * 100)
    
    legacy_payoffs = sum(1 for r in legacy_roles if r["role"] == "PAYOFF")
    groq_payoffs = sum(1 for r in groq_roles if r["role"] == "PAYOFF")

    for i in range(len(sample_transcript)):
        text = sample_transcript[i]['text']
        l_role = legacy_roles[i]['role'] if i < len(legacy_roles) else "N/A"
        g_role = groq_roles[i]['role'] if groq_roles and i < len(groq_roles) else "N/A"
        
        # Color formatting
        l_color = "\033[91m" if l_role == "BUILD" else "\033[92m" # Red if BUILD, Green otherwise
        g_color = "\033[94m" # Blue for Groq
        reset = "\033[0m"
        
        print(f"{text[:73]:<75} | {l_color}{l_role:<10}{reset} | {g_color}{g_role:<10}{reset}")

    print("\n--- Summary ---")
    print(f"Legacy Payoff Strength: {legacy_payoffs}/{len(sample_transcript)} ({(legacy_payoffs/len(sample_transcript)):.2f})")
    print(f"Groq Payoff Strength:   {groq_payoffs}/{len(sample_transcript)} ({(groq_payoffs/len(sample_transcript)):.2f})")
    
if __name__ == "__main__":
    main()
