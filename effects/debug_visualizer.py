"""
HotShort Director Debug Visualizer
===================================
Activated via env var: HS_DEBUG_FRAMES=./debug_out

Writes per-clip:
  {debug_dir}/{clip_id}/
      frame_{N:05d}.jpg   — annotated frames (every Nth frame)
      decisions.json      — full structured audit log

decisions.json schema per entry:
  { t, frame_idx, mode, gap, split_eligible,
    left: {x, y, w, h, ema, talking, mouth_roi},
    right: {x, y, w, h, ema, talking, mouth_roi},
    raw_faces: [{x,y,w,h,valid}...] }
"""

import os
import json
import logging
from typing import Optional, List, Dict, Any

log = logging.getLogger("debug_visualizer")

# ── env config ────────────────────────────────────────────────────────────────
# Default to ./debug_out so decisions.json is always written locally.
# Set HS_DEBUG_FRAMES=0 or HS_DEBUG_FRAMES="" to disable on production.
_dbg_env = os.getenv("HS_DEBUG_FRAMES", "./debug_out").strip()
DEBUG_FRAMES_DIR: Optional[str] = None if _dbg_env in ("0", "", "false", "no", "off") else _dbg_env
DEBUG_FRAME_INTERVAL: int = int(os.getenv("HS_DEBUG_FRAME_INTERVAL", "15"))  # save every N frames
DEBUG_ENABLED = DEBUG_FRAMES_DIR is not None


def _get_clip_dir(clip_id: str) -> str:
    assert DEBUG_FRAMES_DIR is not None
    d = os.path.join(DEBUG_FRAMES_DIR, clip_id)
    os.makedirs(d, exist_ok=True)
    return d


# ── colour palette ────────────────────────────────────────────────────────────
C_LEFT_FACE   = (0, 220, 80)    # green
C_RIGHT_FACE  = (0, 160, 255)   # blue
C_REJECTED    = (0, 0, 230)     # red
C_MOUTH_ROI   = (0, 255, 255)   # yellow
C_TEXT_BG     = (10, 10, 10)    # near-black
C_TEXT        = (240, 240, 240) # white
C_MODE_SPLIT  = (200, 80, 255)  # purple
C_MODE_SOLO_L = (0, 220, 80)    # green
C_MODE_SOLO_R = (0, 160, 255)   # blue


def _mode_color(mode: str):
    if mode == "SPLIT":    return C_MODE_SPLIT
    if mode == "SOLO_LEFT": return C_MODE_SOLO_L
    return C_MODE_SOLO_R


def _put_text_with_bg(img, text: str, x: int, y: int, scale=0.55, thickness=1):
    """Draw text with a solid background rectangle so it's always readable."""
    try:
        import cv2
    except ImportError:
        return
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)
    cv2.rectangle(img, (x - 2, y - th - 4), (x + tw + 2, y + 4), C_TEXT_BG, -1)
    cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, C_TEXT, thickness, cv2.LINE_AA)


def annotate_frame(
    frame,                     # BGR numpy frame
    cv2,                       # cv2 module (passed in to avoid import issues)
    t: float,                  # timestamp seconds
    frame_idx: int,
    mode: str,
    gap: float,
    split_eligible: bool,
    left_slot: Optional[Dict],
    right_slot: Optional[Dict],
    raw_faces: List[Dict],     # [{x,y,w,h,valid}]
    ema_left: float,
    ema_right: float,
    left_talking: bool,
    right_talking: bool,
    mouth_roi_left: Optional[tuple],   # (mx1,my1,mx2,my2) or None
    mouth_roi_right: Optional[tuple],
    talking_threshold: float,
    frame_height: int,
    frame_width: int,
) -> Any:
    """Return an annotated copy of the frame with all debug overlays."""
    vis = frame.copy()

    # ── draw raw face detections ──────────────────────────────────────────────
    valid_slots = set()
    if left_slot:
        valid_slots.add((int(left_slot['x']), int(left_slot['y'])))
    if right_slot:
        valid_slots.add((int(right_slot['x']), int(right_slot['y'])))

    for f in raw_faces:
        x, y, w, h = int(f['x']), int(f['y']), int(f['w']), int(f['h'])
        is_slot = (x, y) in valid_slots
        color = (C_LEFT_FACE if left_slot and int(left_slot['x']) == x
                 else C_RIGHT_FACE if right_slot and int(right_slot['x']) == x
                 else C_REJECTED)
        lw = 2 if is_slot else 1
        cv2.rectangle(vis, (x, y), (x + w, y + h), color, lw)
        label = f"h={h}px ({100*h/frame_height:.0f}%)"
        _put_text_with_bg(vis, label, x, y - 6, scale=0.45)

    # ── draw mouth ROIs ───────────────────────────────────────────────────────
    for roi, ema, talking, slot_name in [
        (mouth_roi_left,  ema_left,  left_talking,  "L"),
        (mouth_roi_right, ema_right, right_talking, "R"),
    ]:
        if roi:
            mx1, my1, mx2, my2 = roi
            cv2.rectangle(vis, (mx1, my1), (mx2, my2), C_MOUTH_ROI, 1)
            status = "TALK✓" if talking else f"ema={ema:.1f}"
            _put_text_with_bg(vis, f"{slot_name}: {status}", mx1, my2 + 14, scale=0.45)

    # ── HUD strip at top ──────────────────────────────────────────────────────
    hud_h = 56
    cv2.rectangle(vis, (0, 0), (frame_width, hud_h), (15, 15, 15), -1)

    mc = _mode_color(mode)
    cv2.rectangle(vis, (0, 0), (frame_width, hud_h), mc, 3)

    line1 = (f"t={t:.2f}s  frame={frame_idx}  MODE={mode}  "
             f"GAP={gap:.2f}({'✓' if split_eligible else '✗'})")
    line2 = (f"L_ema={ema_left:.1f} {'[TALKING]' if left_talking else ''}  |  "
             f"R_ema={ema_right:.1f} {'[TALKING]' if right_talking else ''}  |  "
             f"thresh={talking_threshold:.0f}")
    cv2.putText(vis, line1, (12, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.65, mc, 2, cv2.LINE_AA)
    cv2.putText(vis, line2, (12, 46), cv2.FONT_HERSHEY_SIMPLEX, 0.55, C_TEXT, 1, cv2.LINE_AA)

    return vis


class DirectorDebugSession:
    """
    One instance per clip. Call .record_frame() each frame, .close() at end.
    Output: {debug_dir}/{clip_id}/frame_XXXXX.jpg + decisions.json
    """

    def __init__(self, clip_id: str, clip_start: float, clip_end: float):
        if not DEBUG_ENABLED:
            return
        self.clip_id = clip_id
        self.clip_dir = _get_clip_dir(clip_id)
        self._decisions: List[Dict[str, Any]] = []
        self._saved_count = 0
        log.info(f"[DEBUG_VIZ] Session started → {self.clip_dir}")

    def record_frame(
        self,
        frame,
        cv2,
        t: float,
        frame_idx: int,
        mode: str,
        gap: float,
        split_eligible: bool,
        left_slot,
        right_slot,
        raw_faces: List[Dict],
        ema_left: float,
        ema_right: float,
        left_talking: bool,
        right_talking: bool,
        mouth_roi_left,
        mouth_roi_right,
        talking_threshold: float,
        frame_height: int,
        frame_width: int,
        scene_cut: bool = False,  # True on hard camera-angle change frames
    ):
        if not DEBUG_ENABLED:
            return

        # ── structured JSON record (every frame) ─────────────────────────────────
        entry: Dict[str, Any] = {
            "t": round(t, 3),
            "frame_idx": frame_idx,
            "mode": mode,
            "gap": round(gap, 3),
            "split_eligible": split_eligible,
            # ── Autopsy flat fields (read by director_autopsy.py) ─────────
            "left_face":  left_slot is not None,
            "right_face": right_slot is not None,
            "ema_l":      round(ema_left,  2),
            "ema_r":      round(ema_right, 2),
            "scene_cut":  scene_cut,
            # ── Detailed nested fields (for debug visualizer overlay) ──
            "left": {
                "present": left_slot is not None,
                "x": int(left_slot["x"]) if left_slot else None,
                "y": int(left_slot["y"]) if left_slot else None,
                "w": int(left_slot["w"]) if left_slot else None,
                "h": int(left_slot["h"]) if left_slot else None,
                "nose_x": int(left_slot["nose_x"]) if (left_slot and left_slot.get("nose_x") is not None) else None,
                "nose_y": int(left_slot["nose_y"]) if (left_slot and left_slot.get("nose_y") is not None) else None,
                "ema": round(ema_left, 2),
                "talking": left_talking,
                "mouth_roi": list(mouth_roi_left) if mouth_roi_left else None,
            },
            "right": {
                "present": right_slot is not None,
                "x": int(right_slot["x"]) if right_slot else None,
                "y": int(right_slot["y"]) if right_slot else None,
                "w": int(right_slot["w"]) if right_slot else None,
                "h": int(right_slot["h"]) if right_slot else None,
                "nose_x": int(right_slot["nose_x"]) if (right_slot and right_slot.get("nose_x") is not None) else None,
                "nose_y": int(right_slot["nose_y"]) if (right_slot and right_slot.get("nose_y") is not None) else None,
                "ema": round(ema_right, 2),
                "talking": right_talking,
                "mouth_roi": list(mouth_roi_right) if mouth_roi_right else None,
            },
            "raw_faces": [
                {
                    "x": int(f["x"]), "y": int(f["y"]), "w": int(f["w"]), "h": int(f["h"]),
                    "nose_x": int(f["nose_x"]) if f.get("nose_x") is not None else None,
                    "nose_y": int(f["nose_y"]) if f.get("nose_y") is not None else None
                }
                for f in raw_faces
            ],
        }
        self._decisions.append(entry)

        # ── save annotated frame image (every N frames) ───────────────────────
        if frame is not None and frame_idx % DEBUG_FRAME_INTERVAL == 0:
            try:
                vis = annotate_frame(
                    frame, cv2, t, frame_idx, mode, gap, split_eligible,
                    left_slot, right_slot, raw_faces,
                    ema_left, ema_right, left_talking, right_talking,
                    mouth_roi_left, mouth_roi_right, talking_threshold,
                    frame_height, frame_width,
                )
                out_path = os.path.join(self.clip_dir, f"frame_{frame_idx:05d}.jpg")
                cv2.imwrite(out_path, vis, [cv2.IMWRITE_JPEG_QUALITY, 85])
                self._saved_count += 1
            except Exception as e:
                log.warning(f"[DEBUG_VIZ] Frame save failed: {e}")

    def close(self):
        if not DEBUG_ENABLED:
            return
        # write decisions.json
        json_path = os.path.join(self.clip_dir, "decisions.json")
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(self._decisions, fh, indent=2)
        log.info(
            f"[DEBUG_VIZ] Session closed → {self._saved_count} frames saved, "
            f"{len(self._decisions)} decisions → {json_path}"
        )


# ── No-op sentinel when DEBUG_ENABLED=False ───────────────────────────────────
class _NullSession:
    def record_frame(self, *a, **kw): pass
    def close(self): pass


def make_session(clip_id: str, clip_start: float, clip_end: float):
    """Factory — returns a real session if HS_DEBUG_FRAMES is set, else a no-op."""
    if DEBUG_ENABLED:
        return DirectorDebugSession(clip_id, clip_start, clip_end)
    return _NullSession()
