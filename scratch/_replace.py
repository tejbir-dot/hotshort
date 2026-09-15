import sys

with open('effects/world_class_editor.py', 'r', encoding='utf-8') as f:
    text = f.read()

target = '''            smoothed_solo_x = frame_width * 0.5

            # ── Per-frame analysis loop ──────────────────────────────────────────
            while True:
                ok, frame = cap.read()
                if not ok:
                    break

                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                t = frame_idx / fps

                # 1. Detect raw faces — FaceMesh (preferred) or haarcascade fallback
                raw_faces = []
                if active_detector:
                    res = active_detector.process(rgb)
                    if res and res.multi_face_landmarks:
                        for lm in res.multi_face_landmarks:
                            xs = [p.x for p in lm.landmark]
                            ys = [p.y for p in lm.landmark]
                            raw_faces.append({
                                'x': min(xs) * frame_width,
                                'y': min(ys) * frame_height,
                                'w': (max(xs) - min(xs)) * frame_width,
                                'h': (max(ys) - min(ys)) * frame_height,
                            })
                elif _podcast_cascade is not None:
                    # Haarcascade fallback (relaxed params — Step 3 fix)
                    _faces_hc = _podcast_cascade.detectMultiScale(
                        gray,
                        scaleFactor=1.05,   # finer scale (was 1.1)
                        minNeighbors=3,     # easier to detect (was 6)
                        minSize=(40, 40),   # smaller minimum (was 80,80)
                        flags=cv2.CASCADE_SCALE_IMAGE,
                    )
                    if len(_faces_hc):
                        for _x, _y, _fw, _fh in _faces_hc:
                            raw_faces.append({
                                'x': float(_x), 'y': float(_y),
                                'w': float(_fw), 'h': float(_fh),
                            })'''

replacement = '''            smoothed_solo_x = frame_width * 0.5
            last_raw_faces = []

            # ── Per-frame analysis loop ──────────────────────────────────────────
            while True:
                ok, frame = cap.read()
                if not ok:
                    break

                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                t = frame_idx / fps

                # 1. Detect raw faces — FaceMesh (preferred) or haarcascade fallback
                if frame_idx % 5 == 0:
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    raw_faces = []
                    if active_detector:
                        res = active_detector.process(rgb)
                        if res and res.multi_face_landmarks:
                            for lm in res.multi_face_landmarks:
                                xs = [p.x for p in lm.landmark]
                                ys = [p.y for p in lm.landmark]
                                raw_faces.append({
                                    'x': min(xs) * frame_width,
                                    'y': min(ys) * frame_height,
                                    'w': (max(xs) - min(xs)) * frame_width,
                                    'h': (max(ys) - min(ys)) * frame_height,
                                })
                    elif _podcast_cascade is not None:
                        # Haarcascade fallback (relaxed params — Step 3 fix)
                        _faces_hc = _podcast_cascade.detectMultiScale(
                            gray,
                            scaleFactor=1.05,   # finer scale (was 1.1)
                            minNeighbors=3,     # easier to detect (was 6)
                            minSize=(40, 40),   # smaller minimum (was 80,80)
                            flags=cv2.CASCADE_SCALE_IMAGE,
                        )
                        if len(_faces_hc):
                            for _x, _y, _fw, _fh in _faces_hc:
                                raw_faces.append({
                                    'x': float(_x), 'y': float(_y),
                                    'w': float(_fw), 'h': float(_fh),
                                })
                    last_raw_faces = raw_faces
                else:
                    raw_faces = last_raw_faces'''

if target in text:
    new_text = text.replace(target, replacement)
    with open('effects/world_class_editor.py', 'w', encoding='utf-8') as f:
        f.write(new_text)
    print("Replaced successfully!")
else:
    print("Target not found.")

