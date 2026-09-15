"""Anchor-based scene segmentation for face-detection reuse."""

from __future__ import annotations

import time
from typing import List

import cv2
import numpy as np


SCENE_HASH_THRESHOLD = 10


def _frame_hash(frame_bgr: np.ndarray) -> np.ndarray:
    """Return a dependency-free 64-bit perceptual hash of the full frame.

    This is the OpenCV DCT equivalent of ``imagehash.phash``.  ``imagehash``
    is intentionally not required by the worker image, and the 8x8 low-
    frequency DCT output preserves the same 0-64 Hamming-distance scale.
    """
    # Resize before color conversion/DCT: hashing never needs a full-HD working
    # image. The 64px source preserves scene structure while making the CPU work
    # independent of the decoded frame resolution.
    small = cv2.resize(frame_bgr, (64, 64), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY) if small.ndim == 3 else small
    low_frequency = cv2.dct(gray.astype(np.float32))[:8, :8]
    median = float(np.median(low_frequency.ravel()[1:]))
    return (low_frequency > median).ravel()


def _hash_distance(left: np.ndarray, right: np.ndarray) -> int:
    return int(np.count_nonzero(left != right))


def find_scene_segments(
    frames: List[np.ndarray], threshold: int = SCENE_HASH_THRESHOLD
) -> List[List[int]]:
    """Split frames on anchor-relative scene cuts rather than chain drift.

    The anchor changes *only* after a detected cut. Every other frame is
    compared to the first frame of its segment, preventing adjacent-frame
    motion from fragmenting a stable shot into tiny clusters.
    """
    if not frames:
        print("[SCENE_SEG] built 0 segments from 0 frames, avg_segment_size=0.0", flush=True)
        return []

    threshold = max(0, int(threshold))
    segmentation_start = time.perf_counter()
    segments: List[List[int]] = []
    diffs_seen: List[int] = []
    current_segment = [0]
    anchor_hash = _frame_hash(frames[0])
    print("[SCENE_SEG] frame=0 is anchor (new segment)", flush=True)

    for index, frame in enumerate(frames[1:], start=1):
        current_hash = _frame_hash(frame)
        diff = _hash_distance(current_hash, anchor_hash)
        diffs_seen.append(diff)
        if diff <= threshold:
            current_segment.append(index)
            continue

        print(
            f"[SCENE_SEG] frame={index} diff_from_anchor={diff} > threshold={threshold} "
            f"-> scene cut, closing segment of {len(current_segment)} frames",
            flush=True,
        )
        segments.append(current_segment)
        current_segment = [index]
        anchor_hash = current_hash
        print(f"[SCENE_SEG] frame={index} is anchor (new segment)", flush=True)

    segments.append(current_segment)
    segmentation_elapsed = time.perf_counter() - segmentation_start
    if diffs_seen:
        print(
            f"[SCENE_SEG_DEBUG] diff distribution: min={min(diffs_seen)} "
            f"max={max(diffs_seen)} avg={sum(diffs_seen) / len(diffs_seen):.1f} "
            f"threshold={threshold} segmentation_s={segmentation_elapsed:.3f}",
            flush=True,
        )
    print(
        f"[SCENE_SEG] built {len(segments)} segments from {len(frames)} frames, "
        f"avg_segment_size={len(frames) / len(segments):.1f}",
        flush=True,
    )
    return segments
