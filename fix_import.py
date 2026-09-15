import sys

with open('viral_finder/groq_cortex.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Remove the incorrectly indented import
new_lines = []
for line in lines:
    if line.strip() == 'from viral_finder.cognition import Evidence, IntelligenceArtifact':
        continue
    new_lines.append(line)

# Add it to the top after imports
for i, line in enumerate(new_lines):
    if line.startswith('import os'):
        new_lines.insert(i+1, 'from viral_finder.cognition import Evidence, IntelligenceArtifact\n')
        break

with open('viral_finder/groq_cortex.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
