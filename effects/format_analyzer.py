import cv2
import statistics
import logging
from typing import List, Tuple, Optional
from effects.director_strategy import DirectorMode
from dataclasses import dataclass, field

try:
    from effects.mediapipe_detector import detect_faces_mediapipe, is_mediapipe_available
    _MEDIAPIPE_ENABLED = True
except ImportError:
    _MEDIAPIPE_ENABLED = False
    detect_faces_mediapipe = None

log = logging.getLogger(__name__)

def _clamp(val: float, min_v: float, max_v: float) -> float:
    return max(min_v, min(max_v, val))

@dataclass
class VideoFormat:
    """Result of single-pass video analysis. Drives crop expression and caption alignment."""
    format_type: str                        # "monologue" | "podcast" | "motion_graphic" | "fast_cuts"
    face_count_avg: float                   # average faces per sampled frame
    speaker_positions: List[float]          # normalized X for each detected speaker cluster
    face_switch_rate: float                 # face-position transitions per second
    samples: List[Tuple[float, List[float]]] = field(default_factory=list)  # (t_sec, [face_x, ...])
    director_mode: DirectorMode = DirectorMode.LEGACY

_MULTI_CASCADES_CACHED = None

def get_multi_cascades(cv2_mod):
    global _MULTI_CASCADES_CACHED
    if _MULTI_CASCADES_CACHED is None and cv2_mod is not None:
        cascades = []
        for name in ("haarcascade_frontalface_default.xml", "haarcascade_frontalface_alt2.xml", "haarcascade_profileface.xml"):
            try:
                c = cv2_mod.CascadeClassifier(cv2_mod.data.haarcascades + name)
                if not c.empty():
                    cascades.append((name, c))
            except Exception:
                pass
        _MULTI_CASCADES_CACHED = cascades
    return _MULTI_CASCADES_CACHED or []

def detect_faces_multi_haar(gray, cv2_mod, scale_factor=1.1, min_neighbors=2, min_size=(40, 40)):
    """Robust multi-cascade face detector: checks frontal (default+alt2) + profile (left & right facing).
    Eliminates podcast profile-face blind spots (e.g. guest sitting on right table turned sideways).
    """
    cascades = get_multi_cascades(cv2_mod)
    if not cascades or cv2_mod is None:
        return []
    
    h, w = gray.shape[:2]
    all_boxes = []
    
    for name, c in cascades:
        try:
            boxes = c.detectMultiScale(gray, scaleFactor=scale_factor, minNeighbors=min_neighbors, minSize=min_size, flags=cv2_mod.CASCADE_SCALE_IMAGE)
            for (x, y, bw, bh) in boxes:
                all_boxes.append((float(x), float(y), float(bw), float(bh)))
            
            if "profile" in name:
                gray_flip = cv2_mod.flip(gray, 1)
                boxes_flip = c.detectMultiScale(gray_flip, scaleFactor=scale_factor, minNeighbors=min_neighbors, minSize=min_size, flags=cv2_mod.CASCADE_SCALE_IMAGE)
                for (fx, fy, fbw, fbh) in boxes_flip:
                    orig_x = float(w) - (float(fx) + float(fbw))
                    all_boxes.append((orig_x, float(fy), float(fbw), float(fbh)))
        except Exception:
            pass

    if not all_boxes:
        return []

    all_boxes.sort(key=lambda b: b[2] * b[3], reverse=True)
    merged = []
    for box in all_boxes:
        x1, y1, w1, h1 = box
        cx1, cy1 = x1 + w1 / 2.0, y1 + h1 / 2.0
        is_dup = False
        for m in merged:
            mx, my, mw, mh = m
            mcx, mcy = mx + mw / 2.0, my + mh / 2.0
            dist = ((cx1 - mcx)**2 + (cy1 - mcy)**2)**0.5
            if dist < max(w1, mw) * 0.45:
                is_dup = True
                break
        if not is_dup:
            merged.append(box)
            
    return merged

def analyze_video_format(clip_path: str, start_s: float = 0.0, end_s: float = 0.0) -> VideoFormat:
    """Single-pass video format classifier. 15 frame samples, multi-cascade scan.
    Returns VideoFormat. Speed: ~0.3s on a typical 30s clip.
    """
    _null = VideoFormat(
        format_type="monologue", director_mode=DirectorMode.SINGLE_CENTERED, face_count_avg=1.0,
        speaker_positions=[0.5], face_switch_rate=0.0, samples=[],
    )
    if cv2 is None:
        return _null

    cap = cv2.VideoCapture(clip_path)
    if not cap.isOpened():
        return _null

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    
    start_frame = int(start_s * fps)
    end_frame = int(end_s * fps) if end_s > start_s else int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 1000.0)
    total_frames = max(15, end_frame - start_frame)
    step = max(1, int(total_frames / 15))

    samples = []
    sample_indices = [start_frame + int(i * step) for i in range(15)]

    try:
        for target_frame in sample_indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            h, w = frame.shape[:2]
            if h <= 1 or w <= 1:
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            face_xs = []
            
            if _MEDIAPIPE_ENABLED and detect_faces_mediapipe is not None:
                faces = detect_faces_mediapipe(frame, conf_threshold=0.40, min_size=(40, 40))
            else:
                faces = detect_faces_multi_haar(gray, cv2, scale_factor=1.1, min_neighbors=2, min_size=(40, 40))
                
            for (x, y, fw, fh) in faces:
                face_xs.append((x + fw / 2.0) / float(w))
            samples.append((target_frame / fps, face_xs))
    finally:
        cap.release()

    if not samples:
        return _null

    face_counts = [len(s[1]) for s in samples]
    avg_faces = sum(face_counts) / len(face_counts)
    all_xs = [x for _, faces in samples for x in faces]

    if avg_faces < 0.25 or not all_xs:
        log.info(f"[WCE-FORMAT] classified=motion_graphic avg_faces={avg_faces}")
        return VideoFormat(
            format_type="motion_graphic", director_mode=DirectorMode.SINGLE_CENTERED, face_count_avg=avg_faces,
            speaker_positions=[0.5], face_switch_rate=0.0, samples=samples,
        )

    frames_with_two_faces = 0
    total_sampled = len(samples)
    for _, faces in samples:
        if len(faces) >= 2:
            faces.sort()
            # check the gap between the two most prominent faces or just the first two
            gap = abs(faces[1] - faces[0])
            if gap > 0.15:
                frames_with_two_faces += 1

    co_occurrence_rate = frames_with_two_faces / total_sampled if total_sampled else 0
    log.info(f"[CLASSIFY_DEBUG] clip={clip_path} avg_faces={avg_faces:.2f} "
             f"co_occurrence_rate={co_occurrence_rate:.2f} "
             f"frames_with_two_faces={frames_with_two_faces}/{total_sampled}")

    left_xs  = [x for x in all_xs if x < 0.45]
    right_xs = [x for x in all_xs if x > 0.55]
    # is_bimodal alone is NOT sufficient — a single speaker turning head creates bimodal
    # positions with low co_occurrence. Require BOTH signals to confirm two real speakers.
    is_bimodal = len(left_xs) >= 2 and len(right_xs) >= 2  # raised from >=1 to >=2

    # If we see 2 faces simultaneously in at least 2 frames (out of 15), it is 100% a podcast.
    if (is_bimodal and co_occurrence_rate >= 0.10) or co_occurrence_rate >= 0.13:
        lc = (sum(left_xs) / len(left_xs)) if left_xs else 0.30
        rc = (sum(right_xs) / len(right_xs)) if right_xs else 0.70
        spk_positions = [round(lc, 3), round(rc, 3)]
        single_sides = [
            "L" if faces[0] < 0.5 else "R"
            for _, faces in samples if len(faces) == 1
        ]
        switches = sum(1 for i in range(1, len(single_sides)) if single_sides[i] != single_sides[i - 1])
        clip_dur = max(1.0, samples[-1][0] - samples[0][0])
        log.info(
            "[WCE-FORMAT] classified=podcast left=%.2f right=%.2f switches/s=%.2f avg_faces=%.2f co_occ=%.2f"
            % (lc, rc, switches / clip_dur, avg_faces, co_occurrence_rate)
        )
        return VideoFormat(
            format_type="podcast", director_mode=DirectorMode.PODCAST, face_count_avg=avg_faces,
            speaker_positions=spk_positions, face_switch_rate=switches / clip_dur, samples=samples,
        )

    single_xs = [faces[0] for _, faces in samples if len(faces) == 1]
    if len(single_xs) < 3:
        return _null

    variance = statistics.variance(single_xs)
    median_x = _clamp(float(statistics.median(single_xs)), 0.15, 0.85)
    log.info("[WCE-FORMAT] single-face variance=%.4f median_x=%.3f avg_faces=%.2f" % (variance, median_x, avg_faces))

    if variance > 0.07:
        log.info("[WCE-FORMAT] classified=fast_cuts")
        return VideoFormat(
            format_type="fast_cuts", director_mode=DirectorMode.SINGLE_CENTERED, face_count_avg=avg_faces,
            speaker_positions=[0.5], face_switch_rate=0.0, samples=samples,
        )

    log.info("[WCE-FORMAT] classified=monologue")
    return VideoFormat(
        format_type="monologue", director_mode=DirectorMode.SINGLE_CENTERED, face_count_avg=avg_faces,
        speaker_positions=[median_x], face_switch_rate=0.0, samples=samples,
    )
