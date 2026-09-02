import os
import json
import logging
import time
from typing import Dict, Any, List

log = logging.getLogger(__name__)

def is_gemini_enabled() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))

def _get_gemini_fallback_chain() -> List[str]:
    return [
        "gemini-3.6-flash",
        "gemini-flash-latest",
        "gemini-3.1-flash-lite",
        "gemini-3.7-flash"
    ]

def post_gemini_completions(prompt: str, response_format_schema: Dict = None) -> str:
    """
    Sends the prompt to Gemini using the official google-genai SDK.
    Enforces JSON output if a schema or format is requested.
    """
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        log.error("[GEMINI_CORTEX] google-genai package is not installed! Run: pip install google-genai")
        return "{}"

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set.")

    # Force a 30 second timeout to prevent hanging (AFC or network issues)
    client = genai.Client(api_key=api_key, http_options={'timeout': 30000})
    models_to_try = _get_gemini_fallback_chain()
    
    config = types.GenerateContentConfig(
        temperature=0.1,
    )
    
    if response_format_schema:
        config.response_mime_type = "application/json"
    
    last_error = None
    for model in models_to_try:
        log.info(f"[GEMINI_CORTEX] Attempting request with model: {model}")
        for attempt in range(2):
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=config,
                )
                return response.text
            except Exception as e:
                last_error = e
                # If it's a 400 (Bad Request), it's likely a prompt issue, no point retrying same model
                # If it's 503 or 429, we should immediately failover to the NEXT model in the chain
                err_str = str(e).upper()
                if "503" in err_str or "429" in err_str or "UNAVAILABLE" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                    log.warning(f"[GEMINI_CORTEX] Model {model} overloaded ({err_str}). Falling back to next model...")
                    break # Break the attempt loop to shift to the next model in models_to_try
                    
                log.warning(f"[GEMINI_CORTEX] Attempt {attempt+1} with {model} failed: {e}. Retrying...")
                time.sleep(2)
                
    log.error(f"[GEMINI_CORTEX] All models in fallback chain exhausted! Last error: {last_error}")
    return "{}"

def parse_gemini_json_safely(text: str) -> Dict[str, Any]:
    """Safely parse Gemini JSON output."""
    if not text:
        return {}
    
    text = text.strip()
    # Strip markdown block wrappers if present
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
        
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError as e:
        log.error(f"[GEMINI_CORTEX] Failed to parse JSON: {e} \nContent: {text[:200]}...")
        return {}
