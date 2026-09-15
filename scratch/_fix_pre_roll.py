import re

with open('viral_finder/orchestrator.py', 'r', encoding='utf-8') as f:
    text = f.read()

# Remove Backward expansion logic V1
text = re.sub(
    r'# Backward expansion: include short setup context immediately before hook\.\n\s+for seg in reversed\(transcript\[:hook_idx\]\):\n\s+prev_s, prev_e = _seg_bounds\(seg\)\n\s+if prev_e < hook_start and \(hook_start - prev_e\) < lookback_s:\n\s+arc_start = min\(arc_start, prev_s\)\n\s+break',
    r'# Backward expansion removed to start exactly at hook\n        # for seg in reversed(transcript[:hook_idx]):\n        #     prev_s, prev_e = _seg_bounds(seg)\n        #     if prev_e < hook_start and (hook_start - prev_e) < lookback_s:\n        #         arc_start = min(arc_start, prev_s)\n        #         break',
    text
)

# Remove the -1.5s padding
text = re.sub(
    r'# Avoid abrupt starts by keeping a small amount of pre-hook context\.\n\s+arc_start = max\(0\.0, arc_start - 1\.5\)',
    r'# Start exactly at the hook.\n        # arc_start = max(0.0, arc_start - 1.5)',
    text
)

with open('viral_finder/orchestrator.py', 'w', encoding='utf-8') as f:
    f.write(text)

print("Replaced logic!")

