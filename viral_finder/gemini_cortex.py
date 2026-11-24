import os
import json
import logging
import time
import threading
from typing import Dict, Any, List, Optional
from dotenv import dotenv_values

log = logging.getLogger(__name__)

# Thread-safe Key Pool & Cooldown Management
_POOL_LOCK = threading.Lock()
_KEY_COOLDOWNS: Dict[str, float] = {}  # key -> cooldown expiry timestamp
_KEY_INDEX: int = 0
_CLIENT_CACHE: Dict[str, Any] = {}

def mask_key(k: str) -> str:
    """Masks key for safe, secure logging. Never leaks raw credentials."""
    if not k:
        return "[EMPTY_KEY]"
    k_str = str(k).strip()
    if len(k_str) <= 10:
        return "***"
    return f"{k_str[:6]}...{k_str[-4:]}"

def get_gemini_api_keys() -> List[str]:
    """
    Returns all configured Gemini API keys in priority order.
    Searches os.environ and inspects .env.worker, .env.local, and .env.
    Supports GEMINI_API_KEY, GEMINI_API_KEY_2, GEMINI_API_KEY_3, GEMINI_API_KEY_4, GOOGLE_API_KEY.
    """
    keys: List[str] = []
    key_names = [
        "GEMINI_API_KEY",
        "GEMINI_API_KEY_2",
        "GEMINI_API_KEY_3",
        "GEMINI_API_KEY_4",
        "GEMINI_API_KEY_5",
        "GOOGLE_API_KEY",
    ]

    # 1. Check os.environ first
    for k_name in key_names:
        val = (os.environ.get(k_name) or "").strip()
        if val and val not in keys:
            keys.append(val)

    # 2. If fewer than 2 keys found in os.environ, inspect local env files
    if len(keys) < 2:
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        env_files = [
            os.path.join(base_dir, ".env.worker"),
            os.path.join(base_dir, ".env"),
            os.path.join(base_dir, ".env.local"),
        ]
        for env_path in env_files:
            if os.path.exists(env_path):
                try:
                    vals = dotenv_values(env_path)
                    for k_name in key_names:
                        val = (vals.get(k_name) or "").strip()
                        if val and val not in keys:
                            keys.append(val)
                            # Sync into os.environ for other modules
                            if not os.environ.get(k_name):
                                os.environ[k_name] = val
                except Exception:
                    pass

    return keys

def is_gemini_enabled() -> bool:
    return len(get_gemini_api_keys()) > 0

def _get_gemini_fallback_chain() -> List[str]:
    return [
        "gemini-3.5-flash-lite",     # Primary: lightning fast (1.3s avg)
        "gemini-flash-lite-latest",  # Secondary: rock-solid backup
        "gemini-3.5-flash",          # Tertiary fallback
    ]

def _get_client_for_key(api_key: str):
    """Reuse cached genai.Client instances per key with 15s timeout."""
    with _POOL_LOCK:
        if api_key in _CLIENT_CACHE:
            return _CLIENT_CACHE[api_key]
        try:
            from google import genai
            client = genai.Client(api_key=api_key, http_options={'timeout': 15000})
            _CLIENT_CACHE[api_key] = client
            return client
        except Exception as e:
            log.error(f"[GEMINI_CORTEX] Failed to init client for key {mask_key(api_key)}: {e}")
            return None

def _get_ordered_keys(requested_key: Optional[str] = None) -> List[str]:
    """
    Returns keys prioritized by availability and cooldown status.
    Rotates keys round-robin if no specific key is requested.
    """
    global _KEY_INDEX
    all_keys = get_gemini_api_keys()
    if not all_keys:
        return []

    now = time.time()
    with _POOL_LOCK:
        # Separate healthy vs cooldown keys
        healthy_keys = [k for k in all_keys if _KEY_COOLDOWNS.get(k, 0) <= now]
        cooldown_keys = [k for k in all_keys if _KEY_COOLDOWNS.get(k, 0) > now]

        # Sort cooldown keys by earliest expiry
        cooldown_keys.sort(key=lambda k: _KEY_COOLDOWNS.get(k, 0))

        if requested_key and requested_key in all_keys:
            # Requested key first, followed by others
            remaining_healthy = [k for k in healthy_keys if k != requested_key]
            remaining_cd = [k for k in cooldown_keys if k != requested_key]
            return [requested_key] + remaining_healthy + remaining_cd

        # Round-robin distribution among healthy keys
        if healthy_keys:
            start_idx = _KEY_INDEX % len(healthy_keys)
            _KEY_INDEX = (_KEY_INDEX + 1) % len(healthy_keys)
            ordered_healthy = healthy_keys[start_idx:] + healthy_keys[:start_idx]
            return ordered_healthy + cooldown_keys
        else:
            # All keys are currently in cooldown; return by earliest expiry
            return cooldown_keys

def _mark_key_cooldown(key: str, seconds: float = 60.0):
    with _POOL_LOCK:
        _KEY_COOLDOWNS[key] = time.time() + seconds
        log.warning(
            f"[GEMINI_CORTEX] ⏳ Key {mask_key(key)} hit rate limit / exhaustion. "
            f"Cooldown for {int(seconds)}s. Auto-rotating to other available keys."
        )

def _clear_key_cooldown(key: str):
    with _POOL_LOCK:
        if key in _KEY_COOLDOWNS:
            del _KEY_COOLDOWNS[key]

def _try_openrouter_fallback(prompt: str, json_mode: bool = False) -> Optional[str]:
    """Emergency fallback to OpenRouter when all direct Gemini keys are exhausted."""
    or_key = (os.environ.get("OPENROUTER_API_KEY") or os.environ.get("GPT_API") or "").strip()
    if not or_key:
        return None
    try:
        import requests
        log.info("[GEMINI_CORTEX] 🔄 Invoking OpenRouter emergency fallback...")
        payload: Dict[str, Any] = {
            "model": "google/gemini-2.5-flash-lite",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 2048,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {or_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://hotshort.app",
                "X-Title": "HotShort Emergency Fallback",
            },
            json=payload,
            timeout=25,
        )
        if r.status_code == 200:
            res_json = r.json()
            content = res_json.get("choices", [{}])[0].get("message", {}).get("content")
            if content:
                log.info("[GEMINI_CORTEX] 🚀 OpenRouter fallback SUCCESS.")
                return content
        else:
            log.warning(f"[GEMINI_CORTEX] OpenRouter fallback returned {r.status_code}: {r.text[:150]}")
    except Exception as e:
        log.warning(f"[GEMINI_CORTEX] OpenRouter fallback exception: {e}")
    return None

def post_gemini_completions(prompt: str, response_format_schema: Dict = None, api_key: str = None) -> str:
    """
    Sends the prompt to Gemini using the official google-genai SDK.
    Enforces automatic key rotation, per-key cooldowns on 429 RESOURCE_EXHAUSTED,
    multi-model fallback chains, and OpenRouter safety net.
    """
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        log.error("[GEMINI_CORTEX] google-genai package is not installed! Run: pip install google-genai")
        return "{}"

    candidate_keys = _get_ordered_keys(requested_key=api_key)
    if not candidate_keys:
        log.error("[GEMINI_CORTEX] No Gemini API keys configured!")
        # Try OpenRouter if present
        fallback_res = _try_openrouter_fallback(prompt, json_mode=bool(response_format_schema))
        return fallback_res or "{}"

    models_to_try = _get_gemini_fallback_chain()
    config = types.GenerateContentConfig(
        temperature=0.1,
    )
    if response_format_schema:
        config.response_mime_type = "application/json"

    last_error = None

    # Outer loop: Rotate across all available keys
    for k_idx, cur_key in enumerate(candidate_keys):
        cur_masked = mask_key(cur_key)
        now = time.time()
        cd_left = _KEY_COOLDOWNS.get(cur_key, 0) - now

        # If key is still cooling down and we have alternative healthy keys, skip it
        if cd_left > 0 and k_idx < len(candidate_keys) - 1:
            log.info(f"[GEMINI_CORTEX] Key {cur_masked} cooling down ({int(cd_left)}s left). Skipping to next key...")
            continue

        # If all keys are cooling down and cd_left is short, sleep briefly
        if cd_left > 0 and cd_left <= 3.0:
            log.info(f"[GEMINI_CORTEX] Key {cur_masked} cooldown almost done ({cd_left:.1f}s). Pausing briefly...")
            time.sleep(cd_left + 0.2)

        client = _get_client_for_key(cur_key)
        if not client:
            continue

        key_hit_429 = False

        # Inner loop: Try models with this key
        for model in models_to_try:
            if key_hit_429:
                # Quota limits are PER KEY, not per model!
                # Do NOT waste time trying other models on an exhausted key.
                break

            for attempt in range(2):
                t_call = time.time()
                try:
                    log.info(f"[GEMINI_CORTEX] Calling model={model} using key={cur_masked} (Attempt {attempt+1})")
                    response = client.models.generate_content(
                        model=model,
                        contents=prompt,
                        config=config,
                    )
                    elapsed = round(time.time() - t_call, 2)
                    _clear_key_cooldown(cur_key)
                    log.info(f"[GEMINI_CORTEX] Model {model} on key {cur_masked} SUCCESS in {elapsed}s")
                    return response.text or "{}"
                except Exception as e:
                    elapsed = round(time.time() - t_call, 2)
                    last_error = e
                    err_str = str(e).upper()

                    # 429 RESOURCE_EXHAUSTED / QUOTA EXCEEDED
                    if any(x in err_str for x in ("429", "RESOURCE_EXHAUSTED", "QUOTA_EXCEEDED")):
                        _mark_key_cooldown(cur_key, seconds=60.0)
                        key_hit_429 = True
                        break  # Immediately break to next key

                    # 503 / 504 / DEADLINE_EXCEEDED
                    if any(x in err_str for x in ("503", "504", "DEADLINE", "TIMEOUT", "UNAVAILABLE")):
                        log.warning(f"[GEMINI_CORTEX] Model {model} temporary failure after {elapsed}s ({e}). Failover...")
                        break  # Try next model

                    # 404 NOT_FOUND: model does not exist
                    if "404" in err_str or "NOT_FOUND" in err_str:
                        log.warning(f"[GEMINI_CORTEX] Model {model} not found (404) — trying next model...")
                        break

                    log.warning(f"[GEMINI_CORTEX] Attempt {attempt+1} with {model} on key {cur_masked} failed: {e}. Retrying...")
                    time.sleep(0.5)

    log.error(f"[GEMINI_CORTEX] All configured Gemini keys and models failed. Last error: {last_error}")

    # Fallback to OpenRouter if available
    fallback_res = _try_openrouter_fallback(prompt, json_mode=bool(response_format_schema))
    if fallback_res:
        return fallback_res

    return "{}"

def parse_gemini_json_safely(text: str) -> Dict[str, Any]:
    """Safely parse Gemini JSON output."""
    if not text:
        return {}

    text = text.strip()
    # Strip markdown codeblock wrappers if present
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]

    try:
        return json.loads(text.strip())
    except json.JSONDecodeError as e:
        log.error(f"[GEMINI_CORTEX] Failed to parse JSON: {e} \nContent: {text[:200]}...")
        return {}
