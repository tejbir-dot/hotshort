"""Patch: replaces _detect_primary_focus_x with new analyzer trio."""
import os

SRC = os.path.join(os.path.dirname(__file__), "..", "effects", "world_class_editor.py")
NEW_CODE_FILE = os.path.join(os.path.dirname(__file__), "_new_tracker_code.txt")

new_code = open(NEW_CODE_FILE, encoding="utf-8").read()

lines = open(SRC, encoding="utf-8").readlines()

start_idx = None
end_idx = None
for i, line in enumerate(lines):
    if "    def _detect_primary_focus_x(" in line:
        start_idx = i
    if start_idx is not None and i > start_idx and line.startswith("    def "):
        end_idx = i
        break

if start_idx is None or end_idx is None:
    raise RuntimeError("Could not find block. start=%s end=%s" % (start_idx, end_idx))

print("Replacing lines %d to %d (0-indexed, %d lines)" % (start_idx, end_idx - 1, end_idx - start_idx))

new_lines = lines[:start_idx] + [new_code + "\n"] + lines[end_idx:]
open(SRC, "w", encoding="utf-8").writelines(new_lines)
print("Done. New line count: %d" % len(new_lines))
