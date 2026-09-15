import sys

with open('effects/world_class_editor.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    if line.startswith('                    if len(_faces_hc):'):
        new_lines.append('                        if len(_faces_hc):\n')
    elif line.startswith('                        for _x, _y, _fw, _fh in _faces_hc:'):
        new_lines.append('                            for _x, _y, _fw, _fh in _faces_hc:\n')
    elif line.startswith('                            raw_faces.append({'):
        new_lines.append('                                raw_faces.append({\n')
    elif line.startswith('                                \'x\': float(_x)'):
        new_lines.append('                                    \'x\': float(_x), \'y\': float(_y),\n')
    elif line.startswith('                                \'w\': float(_fw)'):
        new_lines.append('                                    \'w\': float(_fw), \'h\': float(_fh),\n')
    elif line.startswith('                            })'):
        new_lines.append('                                })\n')
    elif '# rgb (moved inside % 5)' in line:
        pass
    else:
        new_lines.append(line)

with open('effects/world_class_editor.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
