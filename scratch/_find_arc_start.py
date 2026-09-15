import re
with open('viral_finder/orchestrator.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if 'arc_start = max(0.0, arc_start - 1.5)' in line:
        print(f"Line {i+1}: {line.strip()}")
        for j in range(i-2, i+3):
            print(f"  {j+1}: {lines[j].strip()}")
