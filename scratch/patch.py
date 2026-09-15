import sys

def main():
    path = r"c:\Users\n\Documents\hotshort\effects\world_class_editor.py"
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # 1. Imports
    chunk1_old = "from effects.format_analyzer import detect_faces_multi_haar"
    chunk1_new = "from effects.format_analyzer import detect_faces_multi_haar\nfrom effects.face_tracker import FaceTracker, SmoothedPosition\nimport time"
    if chunk1_old not in content:
        print("chunk1 not found")
        return
    content = content.replace(chunk1_old, chunk1_new)

    # 2. Init
    chunk2_old = """            smoothed_solo_x = frame_width * 0.5
            last_raw_faces = []
            locked_cluster_id = None
            locked_solo_x = None
            cluster_transition_from_x = smoothed_solo_x
            cluster_transition_remaining = 0

            # Pre-sort face_cache keys once"""
    chunk2_new = """            smoothed_solo_x = frame_width * 0.5
            last_raw_faces = []
            locked_cluster_id = None
            locked_solo_x = None
            cluster_transition_from_x = smoothed_solo_x
            cluster_transition_remaining = 0
            
            ENABLE_CONTINUOUS_TRACKING = True
            left_tracker = FaceTracker("left")
            right_tracker = FaceTracker("right")
            left_tracker_smooth = SmoothedPosition(alpha=0.3)
            right_tracker_smooth = SmoothedPosition(alpha=0.3)
            solo_tracker_smooth = SmoothedPosition(alpha=0.3)
            tracking_time = 0.0
            tracking_frames = 0
            haar_redetects = 0

            # Pre-sort face_cache keys once"""
    if chunk2_old not in content:
        print("chunk2 not found")
        return
    content = content.replace(chunk2_old, chunk2_new)

    # 3. Detect and Track
    chunk3_old = """                # 1. Detect raw faces — FaceMesh (preferred) or haarcascade fallback
                if face_cache is not None:
                    # O(log n) binary-search via pre-sorted key list
                    nearest = _nearest_cache_t(t)
                    raw_faces = face_cache.get(nearest, [])
                    last_raw_faces = raw_faces

                elif frame_idx % 15 == 0:
                    raw_faces = []
                    if False and active_detector:
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
                        # Haarcascade fallback (multi-cascade with profile detection)
                        _faces_hc = detect_faces_multi_haar(gray, _cv2, scale_factor=1.15, min_neighbors=3, min_size=(40, 40))
                        if len(_faces_hc):
                            for _x, _y, _fw, _fh in _faces_hc:
                                raw_faces.append({
                                    'x': float(_x), 'y': float(_y),
                                    'w': float(_fw), 'h': float(_fh),
                                })
                    last_raw_faces = raw_faces
                else:
                    raw_faces = last_raw_faces"""
    
    chunk3_new = """                # 0. Update trackers if enabled
                if ENABLE_CONTINUOUS_TRACKING:
                    t_start = time.perf_counter()
                    left_tracker.update(frame)
                    right_tracker.update(frame)
                    tracking_time += (time.perf_counter() - t_start)
                    tracking_frames += 1

                # 1. Detect raw faces — FaceMesh (preferred) or haarcascade fallback
                if face_cache is not None:
                    # O(log n) binary-search via pre-sorted key list
                    nearest = _nearest_cache_t(t)
                    raw_faces = face_cache.get(nearest, [])
                    last_raw_faces = raw_faces

                elif frame_idx % 15 == 0:
                    if not ENABLE_CONTINUOUS_TRACKING or left_tracker.is_lost() or right_tracker.is_lost():
                        raw_faces = []
                        if False and active_detector:
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
                            # Haarcascade fallback (multi-cascade with profile detection)
                            _faces_hc = detect_faces_multi_haar(gray, _cv2, scale_factor=1.15, min_neighbors=3, min_size=(40, 40))
                            if len(_faces_hc):
                                for _x, _y, _fw, _fh in _faces_hc:
                                    raw_faces.append({
                                        'x': float(_x), 'y': float(_y),
                                        'w': float(_fw), 'h': float(_fh),
                                    })
                        last_raw_faces = raw_faces
                        if ENABLE_CONTINUOUS_TRACKING:
                            haar_redetects += 1
                    else:
                        raw_faces = last_raw_faces
                else:
                    raw_faces = last_raw_faces"""
    
    if chunk3_old not in content:
        print("chunk3 not found")
        return
    content = content.replace(chunk3_old, chunk3_new)

    # 4. Slot assign
    chunk4_old = """                if frame_idx % 25 == 0:
                    log.info(
                        f"[SLOT_ASSIGN] t={t:.2f}s left_face={left_slot is not None} "
                        f"right_face={right_slot is not None} valid_count={len(valid_faces)}"
                    )"""
                    
    chunk4_new = """                if ENABLE_CONTINUOUS_TRACKING:
                    cluster_changed = (cluster_id is not None and cluster_id != locked_cluster_id)
                    cluster_length = (cluster_frame_range[1] - cluster_frame_range[0]) if cluster_frame_range else 0
                    
                    if left_tracker.is_lost() or right_tracker.is_lost() or cluster_changed:
                        if not cluster_changed or cluster_length > 5:
                            t_start = time.perf_counter()
                            if left_slot:
                                left_tracker.init(frame, (left_slot['x'], left_slot['y'], left_slot['w'], left_slot['h']))
                            if right_slot:
                                right_tracker.init(frame, (right_slot['x'], right_slot['y'], right_slot['w'], right_slot['h']))
                            tracking_time += (time.perf_counter() - t_start)
                    
                    if left_tracker.initialized and not left_tracker.is_lost() and left_tracker.last_bbox:
                        left_slot = {'x': left_tracker.last_bbox[0], 'y': left_tracker.last_bbox[1], 'w': left_tracker.last_bbox[2], 'h': left_tracker.last_bbox[3]}
                    if right_tracker.initialized and not right_tracker.is_lost() and right_tracker.last_bbox:
                        right_slot = {'x': right_tracker.last_bbox[0], 'y': right_tracker.last_bbox[1], 'w': right_tracker.last_bbox[2], 'h': right_tracker.last_bbox[3]}

                if frame_idx % 25 == 0:
                    log.info(
                        f"[SLOT_ASSIGN] t={t:.2f}s left_face={left_slot is not None} "
                        f"right_face={right_slot is not None} valid_count={len(valid_faces)}"
                    )"""

    if chunk4_old not in content:
        print("chunk4 not found")
        return
    content = content.replace(chunk4_old, chunk4_new)
    
    # 5. Smoothing and locked solo x
    chunk5_old = """                # 6. Smooth position updates (per slot, independent)
                if left_slot is not None:
                    lx = left_slot['x'] + left_slot['w'] / 2.0
                    smoothed_left_x = smoothed_left_x * (1 - SMOOTH_ALPHA) + lx * SMOOTH_ALPHA

                if right_slot is not None:
                    rx = right_slot['x'] + right_slot['w'] / 2.0
                    smoothed_right_x = smoothed_right_x * (1 - SMOOTH_ALPHA) + rx * SMOOTH_ALPHA

                if mode == "SOLO_LEFT" and left_slot is not None:
                    sx = left_slot['x'] + left_slot['w'] / 2.0
                elif mode == "SOLO_RIGHT" and right_slot is not None:
                    sx = right_slot['x'] + right_slot['w'] / 2.0
                else:
                    sx = None

                if sx is not None and cluster_id is not None:
                    if cluster_id != locked_cluster_id:
                        locked_cluster_id = cluster_id
                        locked_solo_x = sx
                        cluster_transition_from_x = smoothed_solo_x
                        cluster_transition_remaining = CLUSTER_TRANSITION_FRAMES
                        log.info(
                            "[CLUSTER_SCAN] cluster=%s locked_anchor_x=%d zoom=1.00 "
                            "frame_range=[%s-%s]",
                            cluster_id, int(locked_solo_x),
                            cluster_frame_range[0], cluster_frame_range[1],
                        )
                    if cluster_transition_remaining > 0:
                        progress = 1.0 - (cluster_transition_remaining / CLUSTER_TRANSITION_FRAMES)
                        smoothed_solo_x = (
                            cluster_transition_from_x * (1.0 - progress)
                            + locked_solo_x * progress
                        )
                        cluster_transition_remaining -= 1
                    else:
                        smoothed_solo_x = locked_solo_x
                elif sx is not None:
                    # Original per-frame Haar behavior when the cache/cluster layer is off.
                    smoothed_solo_x = smoothed_solo_x * (1 - SMOOTH_ALPHA) + sx * SMOOTH_ALPHA"""
                    
    chunk5_new = """                # 6. Smooth position updates (per slot, independent)
                if ENABLE_CONTINUOUS_TRACKING:
                    if left_slot is not None:
                        lx = left_slot['x'] + left_slot['w'] / 2.0
                        smoothed_left_x = left_tracker_smooth.update(lx)
                    if right_slot is not None:
                        rx = right_slot['x'] + right_slot['w'] / 2.0
                        smoothed_right_x = right_tracker_smooth.update(rx)
                else:
                    if left_slot is not None:
                        lx = left_slot['x'] + left_slot['w'] / 2.0
                        smoothed_left_x = smoothed_left_x * (1 - SMOOTH_ALPHA) + lx * SMOOTH_ALPHA

                    if right_slot is not None:
                        rx = right_slot['x'] + right_slot['w'] / 2.0
                        smoothed_right_x = smoothed_right_x * (1 - SMOOTH_ALPHA) + rx * SMOOTH_ALPHA

                if mode == "SOLO_LEFT" and left_slot is not None:
                    sx = left_slot['x'] + left_slot['w'] / 2.0
                elif mode == "SOLO_RIGHT" and right_slot is not None:
                    sx = right_slot['x'] + right_slot['w'] / 2.0
                else:
                    sx = None

                if sx is not None and cluster_id is not None:
                    if cluster_id != locked_cluster_id:
                        locked_cluster_id = cluster_id
                        locked_solo_x = sx
                        cluster_transition_from_x = smoothed_solo_x
                        cluster_transition_remaining = CLUSTER_TRANSITION_FRAMES
                        log.info(
                            "[CLUSTER_SCAN] cluster=%s locked_anchor_x=%d zoom=1.00 "
                            "frame_range=[%s-%s]",
                            cluster_id, int(locked_solo_x),
                            cluster_frame_range[0], cluster_frame_range[1],
                        )
                    if cluster_transition_remaining > 0:
                        progress = 1.0 - (cluster_transition_remaining / CLUSTER_TRANSITION_FRAMES)
                        smoothed_solo_x = (
                            cluster_transition_from_x * (1.0 - progress)
                            + locked_solo_x * progress
                        )
                        cluster_transition_remaining -= 1
                    else:
                        if ENABLE_CONTINUOUS_TRACKING:
                            smoothed_solo_x = solo_tracker_smooth.update(sx)
                        else:
                            smoothed_solo_x = locked_solo_x
                elif sx is not None:
                    # Original per-frame Haar behavior when the cache/cluster layer is off.
                    if ENABLE_CONTINUOUS_TRACKING:
                        smoothed_solo_x = solo_tracker_smooth.update(sx)
                    else:
                        smoothed_solo_x = smoothed_solo_x * (1 - SMOOTH_ALPHA) + sx * SMOOTH_ALPHA"""
                        
    if chunk5_old not in content:
        print("chunk5 not found")
        return
    content = content.replace(chunk5_old, chunk5_new)

    # 6. Perf Log
    chunk6_old = """            cap.release()"""
    chunk6_new = """            cap.release()
            
            if ENABLE_CONTINUOUS_TRACKING:
                log.info(f"[FACE_TRACK_PERF] total_tracking_time={tracking_time:.2f}s "
                         f"frames={tracking_frames} haar_redetects={haar_redetects}")"""
    
    if chunk6_old not in content:
        print("chunk6 not found")
        return
    content = content.replace(chunk6_old, chunk6_new)

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
        
    print("Patch applied successfully")

if __name__ == "__main__":
    main()
