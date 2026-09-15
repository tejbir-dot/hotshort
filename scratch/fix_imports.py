import re

with open('viral_finder/orchestrator.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
for i, line in enumerate(lines):
    if 43 <= i <= 145 and (line.startswith('except Exception:') or line.startswith('except ImportError:')):
        module_name = 'unknown'
        if new_lines[-1].strip().startswith('from '):
            module_name = new_lines[-1].strip().split()[1]
        elif len(new_lines) >= 2 and new_lines[-2].strip().startswith('from '):
            module_name = new_lines[-2].strip().split()[1]
        
        replacement = line.replace(':', ' as e:')
        new_lines.append(replacement)
        indent = line[:len(line) - len(line.lstrip())]
        new_lines.append(indent + f'    log.warning(f"[ORCH] Import fallback triggered for {module_name}: {{e}}")\n')
    else:
        new_lines.append(line)

with open('viral_finder/orchestrator.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
