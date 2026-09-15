import cv2
from effects.mediapipe_detector import detect_faces_mediapipe, is_mediapipe_available

print("Is MediaPipe available:", is_mediapipe_available())

cap = cv2.VideoCapture("test.mp4")
fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
print(f"Video resolution: {w}x{h} @ {fps}fps")

frames_tested = 0
while True:
    ret, frame = cap.read()
    if not ret:
        break
        
    frames_tested += 1
    
    faces = detect_faces_mediapipe(frame, conf_threshold=0.45, min_size=(40, 40))
    print(f"\nFrame {frames_tested}: Detected {len(faces)} face(s)")
    
    for i, face in enumerate(faces):
        # Verify absolute pixel integers
        x, y, fw, fh = face
        aspect_wh = fw / max(1.0, fh)
        print(f"  Face {i}: box=({x}, {y}, {fw}, {fh}) type=({type(x)}, {type(y)}, {type(fw)}, {type(fh)}) aspect={aspect_wh:.2f}")
        
        # Verify nose tip properties
        nose_x = getattr(face, "nose_x", None)
        nose_y = getattr(face, "nose_y", None)
        print(f"  Nose Tip: ({nose_x}, {nose_y}) type=({type(nose_x)}, {type(nose_y)})")
        
    if frames_tested >= 5:
        break

cap.release()
