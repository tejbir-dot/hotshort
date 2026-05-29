
with open("runpodworker.py", "r", encoding="utf-8") as f:
    content = f.read()

# Replace any crlf with lf for matching
content_lf = content.replace("\r\n", "\n")

old = '''                            # Build cortex_hints from Groq Cortex data if present on this clip
                            cortex_hints = None
                            if clip.get("cortex_enabled"):
                                cortex_hints = {
                                    "cortex_enabled": True,
                                    "opening_caption": clip.get("opening_caption", ""),
                                    "title": clip.get("title", ""),
                                    "hook_type": clip.get("hook_type", ""),
                                    "cortex_score": clip.get("cortex_score", 0),
                                    "learning_signal_for_hotshort": clip.get("learning_signal_for_hotshort", {}),
                                }'''

new = '''                            # Build cortex_hints from Groq Cortex data if present on this clip
                            cortex_hints = None
                            if clip.get("cortex_enabled"):
                                cortex_hints = {
                                    "cortex_enabled": True,
                                    "opening_caption": clip.get("opening_caption", ""),
                                    "title": clip.get("title", ""),
                                    "hook_type": clip.get("hook_type", ""),
                                    "cortex_score": clip.get("cortex_score", 0),
                                    "learning_signal_for_hotshort": clip.get("learning_signal_for_hotshort", {}),
                                    "editing_notes": clip.get("editing_notes", {}),
                                }'''

if old in content_lf:
    content_lf = content_lf.replace(old, new)
    with open("runpodworker.py", "w", encoding="utf-8", newline="\n") as f:
        f.write(content_lf)
    print("PATCHED OK")
else:
    print("Not found")
