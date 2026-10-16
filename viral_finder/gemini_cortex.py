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
        "gemini-3.5-flash-lite",  # Primary: Ultra-fast (~1.5s), reliable, no 504 timeouts
        "gemini-3.5-flash",       # Secondary fallback
        "gemini-3.8-flash",       # Tertiary fallback
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

    # 15s timeout is plenty for flash-lite (<2s avg). Prevents 30s dead hangs.
    client = genai.Client(api_key=api_key, http_options={'timeout': 15000})
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
            t_call = time.time()
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=config,
                )
                elapsed = round(time.time() - t_call, 2)
                log.info(f"[GEMINI_CORTEX] Model {model} SUCCESS in {elapsed}s")
                return response.text
            except Exception as e:
                elapsed = round(time.time() - t_call, 2)
                last_error = e
                err_str = str(e).upper()
                # If it's 503, 504 (timeout), 429, or DEADLINE_EXCEEDED, immediately failover to the NEXT model
                # NEVER burn another 15-30s retry on a model that just timed out!
                if any(x in err_str for x in ("503", "504", "429", "DEADLINE", "TIMEOUT", "UNAVAILABLE", "RESOURCE_EXHAUSTED")):
                    log.warning(f"[GEMINI_CORTEX] Model {model} failed after {elapsed}s ({e}). Immediate failover to next model...")
                    break  # shift to next model immediately
                if "404" in err_str or "NOT_FOUND" in err_str:
                    log.warning(f"[GEMINI_CORTEX] Model {model} not found (404) after {elapsed}s — removing from session chain")
                    break  # dead model, no retry
                    
                log.warning(f"[GEMINI_CORTEX] Attempt {attempt+1} with {model} failed after {elapsed}s: {e}. Retrying...")
                time.sleep(1)
                
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
