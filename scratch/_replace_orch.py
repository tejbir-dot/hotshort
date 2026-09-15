import sys

with open('viral_finder/orchestrator.py', 'r', encoding='utf-8') as f:
    text = f.read()

target = '''try:
    from utils.narrative_intelligence import compute_hook_resolution_bonus
except Exception as e:
    log.warning(f"[ORCH] Import fallback triggered for utils.narrative_intelligence: {e}")
    compute_hook_resolution_bonus = None'''

replacement = '''# Story memory feature fallback
compute_hook_resolution_bonus = None'''

if target in text:
    new_text = text.replace(target, replacement)
    with open('viral_finder/orchestrator.py', 'w', encoding='utf-8') as f:
        f.write(new_text)
    print("Replaced successfully!")
else:
    print("Target not found.")

