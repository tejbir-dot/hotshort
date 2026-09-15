import sys
import time
import cv2

cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
cap = cv2.VideoCapture("test.mp4")
fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

total_faces_1_15 = 0
total_time_1_15 = 0

frames_tested = 0
while True:
    ret, frame = cap.read()
    if not ret:
        break
        
    frames_tested += 1
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    
    # 1.15 new
    start = time.time()
    faces_1_15 = cascade.detectMultiScale(
        gray,
        scaleFactor=1.15,
        minNeighbors=3,
        minSize=(40, 40),
        flags=cv2.CASCADE_SCALE_IMAGE,
    )
    total_time_1_15 += time.time() - start
    total_faces_1_15 += len(faces_1_15)
    
    if frames_tested == 1:
        print(f"[DETECT_RAW] result_count={len(faces_1_15)} call_kwargs={{'scaleFactor': 1.15, 'minNeighbors': 3, 'minSize': (40, 40)}}")
    
    if frames_tested >= 10:
        break

print(f"wall_s per clip (est): {total_time_1_15:.4f}")
print(f"Avg result_count at 1.15: {total_faces_1_15 / frames_tested:.2f}")
