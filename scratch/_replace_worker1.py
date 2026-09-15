import sys

with open('local_worker.py', 'r', encoding='utf-8') as f:
    text = f.read()

target = '''def _process_job(job: dict, cloudinary_ok: bool):
    job_id      = job["job_id"]
    youtube_url = job.get("youtube_url") or job.get("video_url", "")
    is_free     = False if os.getenv("HS_UNLIMITED_MODE", "0") == "1" else job.get("is_free_user", False)'''

replacement = '''import queue
import threading
from concurrent.futures import ThreadPoolExecutor
import cv2

class FaceCache:
    def __init__(self, video_path: str):
        self.cache = {}
        self.video_path = video_path
        self._done = False
        
    def precompute(self):
        print(f"[FACE_CACHE] Starting background face detection...", flush=True)
        try:
            import mediapipe as mp
            face_detector = mp.solutions.face_mesh.FaceMesh(
                static_image_mode=False, max_num_faces=2,
                min_detection_confidence=0.35, min_tracking_confidence=0.3
            )
        except Exception:
            mp = None
            face_detector = None
            cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
            
        cap = cv2.VideoCapture(self.video_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        frame_num = 0
        
        while True:
            ret, frame = cap.read()
            if not ret:
                break
                
            if frame_num % 5 == 0:
                t = frame_num / fps
                raw_faces = []
                if face_detector:
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    res = face_detector.process(rgb)
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
                else:
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    _faces_hc = cascade.detectMultiScale(
                        gray, scaleFactor=1.05, minNeighbors=3,
                        minSize=(40, 40), flags=cv2.CASCADE_SCALE_IMAGE
                    )
                    if len(_faces_hc):
                        for _x, _y, _fw, _fh in _faces_hc:
                            raw_faces.append({
                                'x': float(_x), 'y': float(_y),
                                'w': float(_fw), 'h': float(_fh),
                            })
                            
                self.cache[t] = raw_faces
            frame_num += 1
            
        cap.release()
        if face_detector:
            face_detector.close()
        self._done = True
        print(f"[FACE_CACHE] Precomputed {len(self.cache)} frames", flush=True)

def _process_job(job: dict, cloudinary_ok: bool):
    job_id      = job["job_id"]
    youtube_url = job.get("youtube_url") or job.get("video_url", "")
    is_free     = False if os.getenv("HS_UNLIMITED_MODE", "0") == "1" else job.get("is_free_user", False)'''

if target in text:
    new_text = text.replace(target, replacement)
    with open('local_worker.py', 'w', encoding='utf-8') as f:
        f.write(new_text)
    print("Replaced successfully!")
else:
    print("Target not found.")

