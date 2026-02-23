try:
    from langdetect import detect as _ld_detect
except Exception:
    _ld_detect = None


def detect_language(text: str) -> str:
    if not text:
        return "en"
    if _ld_detect is None:
        # langdetect not available: fallback to English
        return "en"
    try:
        return _ld_detect(text)
    except Exception:
        return "en"
