"""
WCE Face Detection Simulator
Run this to test all face filters on debug frames WITHOUT running the full pipeline.
Usage: python scratch/sim_wce_face.py <frame.jpg> [face_x] [face_y] [face_w] [face_h]
"""
import sys
import os
import cv2
import numpy as np

# Add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from effects.world_class_editor import MIN_VALID_FACE_HEIGHT_RATIO, MAX_VALID_FACE_HEIGHT_RATIO

frame_path = sys.argv[1] if len(sys.argv) > 1 else r"debug_out\clip_0_29_99\frame_00000.jpg"
frame = cv2.imread(frame_path)
if frame is None:
    print(f"[ERROR] Could not load {frame_path}")
    sys.exit(1)

frame_height, frame_width = frame.shape[:2]
print(f"\n{'='*60}")
print(f"Frame: {os.path.basename(frame_path)}")
print(f"Size: {frame_width}x{frame_height}")
print(f"MIN_VALID_FACE_HEIGHT_RATIO: {MIN_VALID_FACE_HEIGHT_RATIO} ({MIN_VALID_FACE_HEIGHT_RATIO*frame_height:.0f}px min)")
print(f"MAX_VALID_FACE_HEIGHT_RATIO: {MAX_VALID_FACE_HEIGHT_RATIO} ({MAX_VALID_FACE_HEIGHT_RATIO*frame_height:.0f}px max)")
print(f"{'='*60}\n")

# Run Haar detection
cascade_xml = r"C:\Users\n\Documents\hotshort\.venv\Lib\site-packages\cv2\data\haarcascade_frontalface_default.xml"
cascade = cv2.CascadeClassifier(cascade_xml)
gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
raw = cascade.detectMultiScale(gray, scaleFactor=1.15, minNeighbors=3, minSize=(40, 40))
print(f"[HAAR] Raw detections: {len(raw)}\n")

_BRIGHT_REJECT_BASE = 185.0
_frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
_frame_mean = float(_frame_gray.mean())
_adaptive_thresh = max(_BRIGHT_REJECT_BASE, _frame_mean + 45.0)
print(f"[BRIGHTNESS] frame_mean={_frame_mean:.1f}  adaptive_thresh={_adaptive_thresh:.1f}")
print()

smoothed_face_h = None

for i, (x, y, w, h) in enumerate(raw):
    print(f"  Face {i}: x={x} y={y} w={w} h={h}")
    cx = x + w / 2.0
    cy = y + h / 2.0
    min_h = frame_height * MIN_VALID_FACE_HEIGHT_RATIO
    max_h = frame_height * MAX_VALID_FACE_HEIGHT_RATIO
    aspect_wh = w / max(1.0, h)

    verdict = "✅ PASS"
    reasons = []

    # Guard 1: height
    if h < min_h:
        verdict = "❌ REJECT"
        reasons.append(f"too_small h={h}px < min={min_h:.0f}px ({MIN_VALID_FACE_HEIGHT_RATIO*100:.0f}% of {frame_height})")
    elif h > max_h:
        verdict = "❌ REJECT"
        reasons.append(f"too_big h={h}px > max={max_h:.0f}px")

    # Guard 2: aspect
    if aspect_wh < 0.60 or aspect_wh > 1.45:
        verdict = "❌ REJECT"
        reasons.append(f"bad_aspect wh={aspect_wh:.2f}")

    # Guard 3: vertical
    if cy < frame_height * 0.12 or cy > frame_height * 0.92:
        verdict = "❌ REJECT"
        reasons.append(f"edge_cy cy={cy:.0f}")

    # Guard 4: horizontal
    if cx < frame_width * 0.03 or cx > frame_width * 0.97:
        verdict = "❌ REJECT"
        reasons.append(f"edge_cx cx={cx:.0f}")

    # Guard 5: brightness
    try:
        roi = frame[int(y):int(y+h), int(x):int(x+w)]
        roi_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        roi_mean = float(roi_gray.mean())
        if roi_mean > _adaptive_thresh:
            verdict = "❌ REJECT"
            reasons.append(f"bright_src roi_mean={roi_mean:.1f} thresh={_adaptive_thresh:.1f}")
        else:
            # Guard 6: laplacian
            lap_var = float(cv2.Laplacian(roi_gray, cv2.CV_64F).var())
            if lap_var < 25 or lap_var > 1200:
                verdict = "❌ REJECT"
                reasons.append(f"laplacian lap_var={lap_var:.1f} range=[25,1200]")
    except Exception as e:
        reasons.append(f"roi_error: {e}")

    # Guard 8: temporal size
    if verdict == "✅ PASS":
        if smoothed_face_h is None:
            smoothed_face_h = h
        elif h < smoothed_face_h * 0.35:
            verdict = "❌ REJECT"
            reasons.append(f"size_mismatch h={h}px expected~={smoothed_face_h:.0f}px threshold={smoothed_face_h*0.35:.0f}px")
        else:
            smoothed_face_h = smoothed_face_h * 0.9 + h * 0.1

    print(f"    {verdict}")
    for r in reasons:
        print(f"    ⚠  {r}")
    print(f"    cx={cx:.0f} cy={cy:.0f} aspect={aspect_wh:.2f} height={h}px ({h/frame_height*100:.1f}%)")
    print()

print(f"\n{'='*60}")
print("Now running Haar with STRICTER minNeighbors=5 (more conservative):")
raw2 = cascade.detectMultiScale(gray, scaleFactor=1.10, minNeighbors=5, minSize=(int(frame_height*0.08), int(frame_height*0.08)))
print(f"[HAAR strict] Raw detections: {len(raw2)}")
for i, (x, y, w, h) in enumerate(raw2):
    cx = x + w / 2.0
    cy = y + h / 2.0
    print(f"  Face {i}: x={x} y={y} w={w} h={h} ({h/frame_height*100:.1f}%) cx={cx:.0f} cy={cy:.0f}")

# Save annotated frame
out = frame.copy()
for (x, y, w, h) in raw:
    # All raw detections in red
    cv2.rectangle(out, (x, y), (x+w, y+h), (0, 0, 255), 2)
for (x, y, w, h) in raw2:
    # Strict detections in green
    cv2.rectangle(out, (x, y), (x+w, y+h), (0, 255, 0), 3)
cv2.putText(out, f"RED=loose(min_h 5%), GREEN=strict(min_h 8%+neighbors5)", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255,255,0), 2)
out_path = r"scratch\sim_result.jpg"
cv2.imwrite(out_path, out)
print(f"\n[OUTPUT] Annotated frame saved to: {out_path}")
print("  RED boxes  = loose Haar (old logic, catches false positives)")
print("  GREEN boxes = strict Haar (new logic, smarter detection)")
