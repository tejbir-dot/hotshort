
with open("runpodworker.py", "r", encoding="utf-8") as f:
    content = f.read()

old = (
    '                            print(f"[WORKER] Running world_class_editor on clip {i}\u2026")\n'
    '                            edit_result = editor.enhance_pretrimmed_clip(\n'
    '                                input_path=clip_path,\n'
    '                                output_path=edited_path,\n'
    '                                source_start=start,\n'
    '                                source_end=end,\n'
    '                                transcript=clip_transcript,\n'
    '                                config=edit_cfg,\n'
    '                                clip_title=clip.get("text", "") or "",\n'
    '                                is_free=clip.get("is_free", False) or is_free_user,\n'
    '                            )'
)

new = (
    '                            # Build cortex_hints from Groq Cortex data if present on this clip\n'
    '                            cortex_hints = None\n'
    '                            if clip.get("cortex_enabled"):\n'
    '                                cortex_hints = {\n'
    '                                    "cortex_enabled": True,\n'
    '                                    "opening_caption": clip.get("opening_caption", ""),\n'
    '                                    "title": clip.get("title", ""),\n'
    '                                    "hook_type": clip.get("hook_type", ""),\n'
    '                                    "cortex_score": clip.get("cortex_score", 0),\n'
    '                                    "learning_signal_for_hotshort": clip.get("learning_signal_for_hotshort", {}),\n'
    '                                }\n'
    "                                print(f\"[WORKER] Cortex hints loaded for clip {i}: hook_type={clip.get('hook_type', '-')}\")\n"
    '\n'
    '                            # Prefer Groq title/opening_caption for hook overlay\n'
    '                            clip_title_str = (\n'
    '                                clip.get("opening_caption")\n'
    '                                or clip.get("title")\n'
    '                                or clip.get("text", "")\n'
    '                                or ""\n'
    '                            )\n'
    '\n'
    '                            print(f"[WORKER] Running world_class_editor on clip {i}...")\n'
    '                            edit_result = editor.enhance_pretrimmed_clip(\n'
    '                                input_path=clip_path,\n'
    '                                output_path=edited_path,\n'
    '                                source_start=start,\n'
    '                                source_end=end,\n'
    '                                transcript=clip_transcript,\n'
    '                                config=edit_cfg,\n'
    '                                clip_title=clip_title_str,\n'
    '                                is_free=clip.get("is_free", False) or is_free_user,\n'
    '                                cortex_hints=cortex_hints,\n'
    '                            )'
)

if old in content:
    content = content.replace(old, new)
    with open("runpodworker.py", "w", encoding="utf-8") as f:
        f.write(content)
    print("PATCHED OK")
else:
    print("Still not found.")
    idx = content.find('[WORKER] Running world_class_editor')
    print(repr(content[max(0,idx-50):idx+400]))
