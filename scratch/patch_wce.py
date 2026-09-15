import os

file_path = "c:/Users/n/Documents/hotshort/effects/world_class_editor.py"
with open(file_path, "r", encoding="utf-8") as f:
    code = f.read()

# 1. Apply subagent's solo_x bug fix

# Target 1:
t1 = """            last_raw_faces = []
            locked_cluster_id = None
            locked_solo_x = None
            cluster_transition_from_x = smoothed_solo_x
            cluster_transition_remaining = 0
            # Slot stability counters (used by mouth-motion EMA gating below)"""

r1 = """            last_raw_faces = []
            locked_cluster_id = None
            locked_cluster_slot = None
            locked_solo_x = None
            cluster_transition_from_x = smoothed_solo_x
            cluster_transition_remaining = 0
            last_solo_slot = None
            # Slot stability counters (used by mouth-motion EMA gating below)"""

code = code.replace(t1, r1)

# Target 2:
t2 = """                else:
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
                        )"""

r2 = """                else:
                    sx = None

                solo_slot = active_slot if mode in ("SOLO_LEFT", "SOLO_RIGHT") else None

                if sx is not None and cluster_id is not None:
                    cluster_lock_changed = (
                        cluster_id != locked_cluster_id
                        or solo_slot != locked_cluster_slot
                    )
                    if cluster_lock_changed:
                        locked_cluster_id = cluster_id
                        locked_cluster_slot = solo_slot
                        locked_solo_x = sx
                        cluster_transition_from_x = smoothed_solo_x
                        # A side switch is semantic, not camera drift. Do it immediately
                        # so SOLO_RIGHT cannot render with the previous left anchor.
                        if last_solo_slot is not None and solo_slot != last_solo_slot:
                            cluster_transition_remaining = 0
                            smoothed_solo_x = locked_solo_x
                        else:
                            cluster_transition_remaining = CLUSTER_TRANSITION_FRAMES
                        log.info(
                            "[CLUSTER_SCAN] cluster=%s slot=%s locked_anchor_x=%d zoom=1.00 "
                            "frame_range=[%s-%s]",
                            cluster_id, solo_slot, int(locked_solo_x),
                            cluster_frame_range[0], cluster_frame_range[1],
                        )"""

code = code.replace(t2, r2)


# Target 3:
t3 = """                    else:
                        smoothed_solo_x = smoothed_solo_x * (1 - SMOOTH_ALPHA) + sx * SMOOTH_ALPHA

                if frame_idx % 25 == 0:"""

r3 = """                    else:
                        smoothed_solo_x = smoothed_solo_x * (1 - SMOOTH_ALPHA) + sx * SMOOTH_ALPHA

                if solo_slot is not None:
                    last_solo_slot = solo_slot

                if frame_idx % 25 == 0:"""

code = code.replace(t3, r3)


# 2. Apply static box rejection fix

# Target 4:
t4 = """            # Slot stability counters (used by mouth-motion EMA gating below)
            _left_stable = 0
            _right_stable = 0
            
            ENABLE_CONTINUOUS_TRACKING = False"""

r4 = """            # Slot stability counters (used by mouth-motion EMA gating below)
            _left_stable = 0
            _right_stable = 0
            box_stability_map = {}
            
            ENABLE_CONTINUOUS_TRACKING = False"""
code = code.replace(t4, r4)

# Target 5:
t5 = """                        if _lap_var < _LAP_MIN or _lap_var > _LAP_MAX:
                            if _log_reason:
                                log.info(
                                    f"[FACE_FILTER] REJECT laplacian  lap_var={_lap_var:.1f} "
                                    f"range=[{_LAP_MIN:.0f},{_LAP_MAX:.0f}] "
                                    f"face=({x:.0f},{y:.0f},{w:.0f},{h:.0f})"
                                )
                            return False

                    except Exception:"""

r5 = """                        if _lap_var < _LAP_MIN or _lap_var > _LAP_MAX:
                            if _log_reason:
                                log.info(
                                    f"[FACE_FILTER] REJECT laplacian  lap_var={_lap_var:.1f} "
                                    f"range=[{_LAP_MIN:.0f},{_LAP_MAX:.0f}] "
                                    f"face=({x:.0f},{y:.0f},{w:.0f},{h:.0f})"
                                )
                            return False

                        # ── guard 7: static box rejection ─────────────────────────
                        _static = det.get('_static_frames', 0)
                        if _static > 50:
                            if _log_reason:
                                log.info(
                                    f"[FACE_FILTER] REJECT static_box frames={_static} "
                                    f"face=({x:.0f},{y:.0f},{w:.0f},{h:.0f})"
                                )
                            return False

                    except Exception:"""

code = code.replace(t5, r5)

# Target 6:
t6 = """                # ────────────────────────────────────────────────────────────────

                valid_faces = [f for f in raw_faces if is_valid_face(f, frame=frame)]"""

r6 = """                # ────────────────────────────────────────────────────────────────

                new_stability_map = {}
                for _f in raw_faces:
                    _key = (round(_f['x']), round(_f['y']), round(_f['w']), round(_f['h']))
                    _f['_static_frames'] = box_stability_map.get(_key, 0) + 1
                    new_stability_map[_key] = _f['_static_frames']
                box_stability_map = new_stability_map

                valid_faces = [f for f in raw_faces if is_valid_face(f, frame=frame)]"""
code = code.replace(t6, r6)


with open(file_path, "w", encoding="utf-8") as f:
    f.write(code)

print("Patch applied.")
