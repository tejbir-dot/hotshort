import os

file_path = "c:/Users/n/Documents/hotshort/effects/world_class_editor.py"
with open(file_path, "r", encoding="utf-8") as f:
    code = f.read()

# Target for brightness:
t1 = """                # ── guard 5: brightness — reject lamps, ring-lights, logos ────────
                # shape guards. Their face ROI has very high brightness.
                # Threshold=185: skin in podcast lighting peaks at ~140 mean gray.
                # Lamps: >200. Overexposed windows: >220. Safe margin: 185.
                _BRIGHT_REJECT_THRESHOLD = float(
                    os.environ.get("HS_FACE_BRIGHT_REJECT", "185")
                )
                if frame is not None:
                    try:
                        _roi_gray = cv2.cvtColor(
                            frame[int(y):int(y + h), int(x):int(x + w)],
                            cv2.COLOR_BGR2GRAY,
                        )
                        _roi_mean = float(_roi_gray.mean())
                        if _roi_mean > _BRIGHT_REJECT_THRESHOLD:
                            if _log_reason:
                                log.info(
                                    f"[FACE_FILTER] REJECT bright_src roi_mean={_roi_mean:.1f} "
                                    f"thresh={_BRIGHT_REJECT_THRESHOLD:.0f} "
                                    f"face=({x:.0f},{y:.0f},{w:.0f},{h:.0f})"
                                )
                            return False"""

r1 = """                # ── guard 5: brightness — reject lamps, ring-lights, logos ────────
                _BASE_BRIGHT_REJECT = float(os.environ.get("HS_FACE_BRIGHT_REJECT", "185"))
                if frame is not None:
                    try:
                        _frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                        _frame_mean = float(_frame_gray.mean())
                        _adaptive_thresh = max(_BASE_BRIGHT_REJECT, _frame_mean + 45.0)

                        _roi_gray = cv2.cvtColor(
                            frame[int(y):int(y + h), int(x):int(x + w)],
                            cv2.COLOR_BGR2GRAY,
                        )
                        _roi_mean = float(_roi_gray.mean())
                        if _roi_mean > _adaptive_thresh:
                            if _log_reason:
                                log.info(
                                    f"[FACE_FILTER] REJECT bright_src roi_mean={_roi_mean:.1f} "
                                    f"thresh={_adaptive_thresh:.1f} (frame={_frame_mean:.1f}) "
                                    f"face=({x:.0f},{y:.0f},{w:.0f},{h:.0f})"
                                )
                            return False"""

if t1 in code:
    code = code.replace(t1, r1)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(code)
    print("Brightness patch applied.")
else:
    print("Target 1 not found.")
