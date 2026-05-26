import os

new_code = """def resolve_device(prefer_gpu: bool = DEFAULT_PRETEND_GPU) -> str:
    try:
        # 1. Respect explicit environment variable WHISPER_DEVICE
        env_device = os.environ.get("WHISPER_DEVICE", "").strip().lower()
        if env_device in ("cuda", "cpu"):
            return env_device

        # 2. Check ctranslate2 CUDA devices
        try:
            import ctranslate2
            if ctranslate2.get_cuda_device_count() > 0:
                return "cuda"
        except Exception:
            pass

        if prefer_gpu and torch is not None and torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu\""""

old_code = """def resolve_device(prefer_gpu: bool = DEFAULT_PRETEND_GPU) -> str:
    try:
        if prefer_gpu and torch is not None and torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu\""""

for filepath in ['viral_finder/transcript_engine.py', 'viral_finder/gemini_transcript_engine.py']:
    if not os.path.exists(filepath):
        continue
    content = open(filepath, 'r', encoding='utf-8').read()
    # Normalize line endings to LF to ensure exact match
    content_lf = content.replace('\r\n', '\n')
    old_lf = old_code.replace('\r\n', '\n')
    new_lf = new_code.replace('\r\n', '\n')
    if old_lf in content_lf:
        content_lf = content_lf.replace(old_lf, new_lf)
        # Write back in the same line ending style as original
        if '\r\n' in content:
            new_content = content_lf.replace('\n', '\r\n')
        else:
            new_content = content_lf
        open(filepath, 'w', encoding='utf-8').write(new_content)
        print(f"Successfully updated {filepath}")
    else:
        print(f"Target not found in {filepath}")
