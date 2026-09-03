"""
effects/insightface_detector.py
=================================
InsightFace SCRFD -- GPU-accelerated Face Detection.

Drop-in replacement for MediaPipe face detection.
Uses SCRFD_2.5G model via ONNX Runtime with CUDA execution provider.

Accuracy vs Speed:
    buffalo_sc  = SCRFD_2.5G  -- fastest, ~97% WiderFace
    buffalo_l   = SCRFD_10G   -- more accurate, slower

Provider priority (auto-selected):
    1. CUDA (RTX GPU) via CUDAExecutionProvider   -- ~8x vs MediaPipe CPU
    2. CPU  via CPUExecutionProvider              -- same speed as MediaPipe

Output format:
    Same FaceBox(x, y, w, h, nose_x, nose_y) as mediapipe_detector.py
    Fully backward-compatible with all callers in world_class_editor.py

Env vars:
    HS_INSIGHTFACE_MODEL    = buffalo_sc (default) | buffalo_l
    HS_INSIGHTFACE_DET_SIZE = 320 (default) | 640 (higher accuracy)
    HS_INSIGHTFACE_ENABLED  = 1 (0 to disable and fall back to MediaPipe)
"""

import os
import logging
import threading
from typing import List, Optional, Tuple
import numpy as np

log = logging.getLogger(__name__)

_IF_FAILED    = False
_CUDA_BROKEN  = False   # Set True when cuDNN inference fails → switch to CPU-only
_thread_local = threading.local()

MODEL_NAME    = os.environ.get("HS_INSIGHTFACE_MODEL", "buffalo_sc")
DET_SIZE_CFG  = int(os.environ.get("HS_INSIGHTFACE_DET_SIZE", "640"))
IF_ENABLED    = os.environ.get("HS_INSIGHTFACE_ENABLED", "1") not in ("0", "false", "no")

_init_lock    = threading.Lock()

_PROVIDERS = ["CUDAExecutionProvider", "CPUExecutionProvider"]


class FaceBox(tuple):
    """
    Backward-compatible with mediapipe_detector.FaceBox.
    Behaves like (x, y, w, h) tuple but carries nose coords.
    """
    def __new__(cls, x, y, w, h, nose_x=None, nose_y=None):
        return super().__new__(cls, (x, y, w, h))

    def __init__(self, x, y, w, h, nose_x=None, nose_y=None):
        self.nose_x = nose_x
        self.nose_y = nose_y


def _get_app():
    """Thread-local InsightFace FaceAnalysis instance."""
    global _IF_FAILED
    if _IF_FAILED or not IF_ENABLED:
        return None

    app = getattr(_thread_local, "if_app", None)
    if app is not None:
        return app

    try:
        # ── Provider selection ────────────────────────────────────────────────
        # Default: CPUExecutionProvider (avoids cuDNN DLL conflicts on Windows).
        # Set HS_INSIGHTFACE_CUDA=1 to force CUDA when CUDA Toolkit + cuDNN 9
        # are properly installed system-wide.
        # SCRFD model accuracy is identical on CPU vs GPU — only speed differs.
        _force_cuda = os.environ.get("HS_INSIGHTFACE_CUDA", "0") == "1"
        if _force_cuda:
            try:
                # Add NVIDIA system cuDNN path dynamically
                _cudnn_path = r"C:\Program Files\NVIDIA\CUDNN\v9.25\bin\12.9\x64"
                if os.path.exists(_cudnn_path):
                    os.add_dll_directory(_cudnn_path)
                    log.info("[INSIGHTFACE] Registered system cuDNN from %s", _cudnn_path)
            except Exception as e:
                log.warning("[INSIGHTFACE] Failed to register cuDNN path: %s", e)

        _providers   = ["CUDAExecutionProvider", "CPUExecutionProvider"] if _force_cuda else ["CPUExecutionProvider"]
        _device_name = "CUDA" if _force_cuda else "CPU"
        log.info("[INSIGHTFACE] provider=%s (set HS_INSIGHTFACE_CUDA=1 for GPU)", _device_name)


        import sys
        import onnxruntime
        onnxruntime.set_default_logger_severity(3) # Suppress ONNX info logs

        from insightface.app import FaceAnalysis
        import logging as _logging
        _logging.getLogger("insightface").setLevel(_logging.WARNING)

        class _SuppressStdout:
            def __enter__(self):
                self._original_stdout = sys.stdout
                sys.stdout = open(os.devnull, 'w')
            def __exit__(self, exc_type, exc_val, exc_tb):
                sys.stdout.close()
                sys.stdout = self._original_stdout

        with _init_lock:
            with _SuppressStdout():
                app = FaceAnalysis(
                    name=MODEL_NAME,
                    providers=_providers,          # probe-determined: CUDA or CPU-only
                    allowed_modules=["detection"],
                )
                app.prepare(ctx_id=0, det_size=(DET_SIZE_CFG, DET_SIZE_CFG))

        active = _device_name
        log.info(
            "[INSIGHTFACE] Initialized: model=%s det_size=%dx%d device=%s thread=%s",
            MODEL_NAME, DET_SIZE_CFG, DET_SIZE_CFG, active,
            threading.current_thread().name,
        )
        _thread_local.if_app = app
        return app

    except Exception as e:
        log.warning("[INSIGHTFACE] Init failed: %s -- will fall back to MediaPipe", e)
        _IF_FAILED = True
        return None


def _reinit_cpu_only():
    """Drop CUDA provider and reinitialize on CPU-only. Called when cuDNN is missing."""
    global _CUDA_BROKEN
    _CUDA_BROKEN = True
    _thread_local.if_app = None   # force re-init on next call
    try:
        from insightface.app import FaceAnalysis
        import logging as _logging
        import sys
        _logging.getLogger("insightface").setLevel(_logging.WARNING)

        class _SuppressStdout:
            def __enter__(self):
                self._original_stdout = sys.stdout
                sys.stdout = open(os.devnull, 'w')
            def __exit__(self, exc_type, exc_val, exc_tb):
                sys.stdout.close()
                sys.stdout = self._original_stdout

        with _init_lock:
            with _SuppressStdout():
                app = FaceAnalysis(
                    name=MODEL_NAME,
                    providers=["CPUExecutionProvider"],
                    allowed_modules=["detection"],
                )
                app.prepare(ctx_id=0, det_size=(DET_SIZE_CFG, DET_SIZE_CFG))
        _thread_local.if_app = app
        log.info(
            "[INSIGHTFACE] cuDNN unavailable -- reinitialized on CPU. "
            "Install cuDNN 9 to enable GPU (https://developer.nvidia.com/cudnn)."
        )
        return app
    except Exception as e:
        log.warning("[INSIGHTFACE] CPU reinit also failed: %s", e)
        return None


def detect_faces_insightface(
    frame_bgr: np.ndarray,
    conf_threshold: float = 0.45,
    min_size: Tuple[int, int] = (40, 40),
) -> List[FaceBox]:
    """
    Detect faces using InsightFace SCRFD.
    Returns List[FaceBox(x,y,w,h,nose_x,nose_y)] in absolute pixels.
    Returns empty list if InsightFace not available (caller falls back).
    """
    app = _get_app()
    if app is None:
        return []

    try:
        h, w = frame_bgr.shape[:2]
        faces = app.get(frame_bgr)  # BGR -- no conversion needed (unlike MediaPipe)

        boxes_out = []
        for face in faces:
            score = float(face.det_score)
            if score < conf_threshold:
                continue

            # bbox = [x1, y1, x2, y2] absolute pixels
            x1, y1, x2, y2 = [int(round(v)) for v in face.bbox]
            x1 = max(0, x1); y1 = max(0, y1)
            x2 = min(w, x2); y2 = min(h, y2)
            bw = x2 - x1;    bh = y2 - y1

            if bw < min_size[0] or bh < min_size[1]:
                continue

            # SCRFD 5 keypoints: left_eye, right_eye, nose_tip, left_mouth, right_mouth
            nose_x = nose_y = None
            if face.kps is not None and len(face.kps) >= 3:
                nx, ny   = face.kps[2]
                nose_x   = max(0, min(w - 1, int(round(nx))))
                nose_y   = max(0, min(h - 1, int(round(ny))))

            boxes_out.append(FaceBox(x1, y1, bw, bh, nose_x, nose_y))

        return boxes_out

    except Exception as e:
        err_str = str(e)
        # cuDNN missing: LoadLibrary failed for cudnn64_*.dll
        # Reinit on CPU-only and retry ONCE -- no more CUDA errors after this
        if (not _CUDA_BROKEN) and ("cudnn" in err_str.lower() or "NOT_IMPLEMENTED" in err_str):
            log.warning("[INSIGHTFACE] cuDNN not found -- switching to CPU provider (one-time)")
            cpu_app = _reinit_cpu_only()
            if cpu_app is not None:
                try:
                    return detect_faces_insightface(frame_bgr, conf_threshold, min_size)
                except Exception:
                    pass
        log.warning("[INSIGHTFACE] Inference error: %s", e)
        return []


def is_insightface_available() -> bool:
    return _get_app() is not None


def get_provider_name() -> str:
    try:
        import onnxruntime as ort
        providers = ort.get_available_providers()
        if "CUDAExecutionProvider" in providers:
            return "CUDA"
        return "CPU"
    except Exception:
        return "unknown"
