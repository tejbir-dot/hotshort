import sys

with open('effects/world_class_editor.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
for i, line in enumerate(lines):
    if 'smoothed_solo_x = frame_width * 0.5' in line:
        new_lines.append(line)
        new_lines.append('            last_raw_faces = []\n')
    elif 'rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)' in line and 'gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)' in lines[i+1]:
        new_lines.append(line.replace('rgb', '# rgb (moved inside % 5)'))
    elif 'raw_faces = []' in line and 'if active_detector:' in lines[i+1]:
        new_lines.append('                if frame_idx % 5 == 0:\n')
        new_lines.append('                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)\n')
        new_lines.append('                    raw_faces = []\n')
    elif 'if len(_faces_hc):' in line and 'raw_faces.append({' in lines[i+2]:
        new_lines.append(line)
    elif 'raw_faces.append({' in line and 'x\': float(_x)' in lines[i+1]:
        new_lines.append(line)
    elif 'w\': float(_fw)' in line and '})' in lines[i+1]:
        new_lines.append(line)
    elif '})' in line and 'w\': float(_fw)' in lines[i-1]:
        new_lines.append(line)
        new_lines.append('                    last_raw_faces = raw_faces\n')
        new_lines.append('                else:\n')
        new_lines.append('                    raw_faces = last_raw_faces\n')
    elif 'res = active_detector.process(rgb)' in line or 'if res and res.multi_face_landmarks:' in line or 'for lm in res.multi_face_landmarks:' in line or 'xs = [p.x for p in lm.landmark]' in line or 'ys = [p.y for p in lm.landmark]' in line or ('raw_faces.append({' in line and '\'x\': min(xs)' in lines[i+1]) or '\'x\': min(xs) * frame_width,' in line or '\'y\': min(ys) * frame_height,' in line or '\'w\': (max(xs) - min(xs)) * frame_width,' in line or '\'h\': (max(ys) - min(ys)) * frame_height,' in line or ('})' in line and '\'h\': (max(ys)' in lines[i-1]) or 'elif _podcast_cascade is not None:' in line or '_faces_hc = _podcast_cascade.detectMultiScale(' in line or 'gray,' in line or 'scaleFactor=1.05,' in line or 'minNeighbors=3,' in line or 'minSize=(40, 40),' in line or 'flags=cv2.CASCADE_SCALE_IMAGE,' in line or ('if active_detector:' in line and 'raw_faces = []' in lines[i-1]):
        new_lines.append('    ' + line) # Indent everything inside the if block by 4 spaces
    else:
        new_lines.append(line)

with open('effects/world_class_editor.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
