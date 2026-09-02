"""
effects/director_autopsy.py
============================
Self-Refining Director Intelligence — v2 (All 5 Ideas Implemented).

IDEAS IMPLEMENTED:
  1 (Auto-Tune)       : Feed quality score -> param delta logic (LEARNING_RATE lerp)
  2 (Ghost Detector)  : Cross-reference EMA + face_present; identify WHICH slot is ghosting
  3 (Scene Cut Cal.)  : Compare runtime scene_cuts vs face_cache cluster boundaries (F1 score)
  4 (Quality Score)   : 5-dimension 0-100 score per clip
  5 (Channel DNA)     : channel_profiles/{id}.json persisted, loaded before each render

Quality Dimensions (scored 0-100 each):
  A. Mode Switch Rate     -- target: 2-8 switches/min (human editor pace)
  B. SPLIT Coverage       -- target: >15% on podcast clips
  C. HOLD Ratio           -- target: <12% (too much = ghost tracking)
  D. Ghost Frame Ratio    -- target: <8% (face=True but EMA < 20% of threshold)
  E. Scene Cut Accuracy   -- F1 score vs face_cache cluster boundary ground truth

Tunable Params (written as env vars into profile):
  HS_MIN_SWITCH_FRAMES    -- prevents mode jitter
  HS_SPLIT_MIN_GAP        -- controls SPLIT trigger sensitivity
  HS_TALKING_THRESHOLD    -- mouth EMA talking gate
  HS_SCENE_CUT_THRESHOLD  -- perceptual diff sensitivity
  HS_EMA_FLOOR            -- minimum EMA value (prevents crash-to-zero)
"""

import os
import json
import logging
import re
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime

log = logging.getLogger(__name__)

BASE_DIR      = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PROFILES_DIR  = os.path.join(BASE_DIR, "channel_profiles")

PARAM_BOUNDS = {
    "HS_MIN_SWITCH_FRAMES":    (4,    40),
    "HS_SPLIT_MIN_GAP":        (0.15, 0.55),
    "HS_TALKING_THRESHOLD":    (20.0, 200.0),
    "HS_SCENE_CUT_THRESHOLD":  (8.0,  50.0),
    "HS_EMA_FLOOR":            (0.0,  5.0),
}

DEFAULT_PARAMS = {
    "HS_MIN_SWITCH_FRAMES":    12,
    "HS_SPLIT_MIN_GAP":        0.38,
    "HS_TALKING_THRESHOLD":    80.0,
    "HS_SCENE_CUT_THRESHOLD":  22.0,
    "HS_EMA_FLOOR":            0.0,
}

LEARNING_RATE     = 0.25   # conservative: move 25% toward target per run
HISTORY_MAX_RUNS  = 20     # keep rolling history of last N scores


class DirectorAutopsy:
    """
    Post-render intelligence engine.
    Analyzes decisions.json, scores it on 5 dimensions, tunes 5 params,
    and persists a Channel DNA profile that improves every run.
    """

    def __init__(self, channel_id: str = "default"):
        self.channel_id = self._sanitize_id(channel_id)
        self.profile    = self._load_profile(self.channel_id)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        decisions_path: str,
        clip_format: str = "unknown",
        scene_seg_cuts: Optional[List[float]] = None,
    ) -> Dict[str, Any]:
        """Full autopsy. Returns report dict and updates channel profile."""
        if not os.path.exists(decisions_path):
            log.warning(f"[AUTOPSY] decisions.json not found: {decisions_path}")
            return {"score": None, "skipped": True}
        try:
            decisions = json.load(open(decisions_path, encoding="utf-8"))
        except Exception as e:
            log.warning(f"[AUTOPSY] Failed to load decisions.json: {e}")
            return {"score": None, "skipped": True}
        if not decisions:
            return {"score": None, "skipped": True}

        report = self._score(decisions, clip_format, scene_seg_cuts or [])
        deltas = self._compute_deltas(report, clip_format)
        self._apply_deltas(deltas, report["total_score"])
        self._save_profile()

        report["param_deltas"]   = deltas
        report["channel_id"]     = self.channel_id
        report["clip_format"]    = clip_format
        report["runs"]           = self.profile.get("runs", 0)
        report["profile_params"] = dict(self.profile.get("params", {}))
        report["avg_score"]      = self.profile.get("avg_score", report["total_score"])

        log.info(
            f"[AUTOPSY] ch={self.channel_id} fmt={clip_format} "
            f"score={report['total_score']:.1f} avg={report['avg_score']:.1f} "
            f"flags={report['flags']}"
        )
        for param, (old, new) in deltas.items():
            if abs(new - old) > 0.001:
                direction = "UP" if new > old else "DOWN"
                log.info(f"[AUTOPSY] TUNE {direction} {param}: {old:.3f} -> {new:.3f}")
        return report

    def get_env_params(self) -> Dict[str, str]:
        """Returns calibrated params as env-var strings. Call before render."""
        stored = self.profile.get("params", {})
        return {k: str(stored.get(k, DEFAULT_PARAMS[k])) for k in DEFAULT_PARAMS}

    def apply_to_env(self):
        """Inject calibrated params into os.environ for this process."""
        for k, v in self.get_env_params().items():
            os.environ[k] = v
            log.info(f"[AUTOPSY] env[{k}] = {v}")

    # ------------------------------------------------------------------
    # Scoring Engine — Idea 4 + Idea 2 (Ghost Detector)
    # ------------------------------------------------------------------

    def _score(
        self,
        decisions: List[Dict],
        clip_format: str,
        scene_seg_cuts: List[float],
    ) -> Dict[str, Any]:
        total = len(decisions)
        if total == 0:
            return {"total_score": 0.0, "dimension_scores": {}, "flags": []}

        mode_counts: Dict[str, int] = {}
        for d in decisions:
            m = d.get("mode", "UNKNOWN")
            mode_counts[m] = mode_counts.get(m, 0) + 1

        split_count = mode_counts.get("SPLIT", 0)
        hold_count  = mode_counts.get("HOLD", 0)
        fps         = 30.0
        duration    = total / fps

        # ── A: Mode Switch Rate ─────────────────────────────────────────
        switches = sum(
            1 for i in range(1, total)
            if decisions[i].get("mode") != decisions[i-1].get("mode")
        )
        spm = (switches / max(duration, 1)) * 60.0
        if 2.0 <= spm <= 8.0:
            score_a = 100.0
        elif spm < 2.0:
            score_a = max(0, 60.0 + spm * 20.0)
        elif spm <= 15.0:
            score_a = max(0, 100.0 - (spm - 8.0) * 8.0)
        else:
            score_a = max(0, 50.0 - (spm - 15.0) * 3.0)

        # ── B: SPLIT Coverage ───────────────────────────────────────────
        is_podcast = clip_format in ("podcast", "bimodal")
        split_pct  = split_count / total
        if is_podcast:
            score_b = 100.0 if split_pct >= 0.15 else (
                40.0 + split_pct * 400.0 if split_pct >= 0.05 else split_pct * 800.0
            )
        else:
            score_b = 100.0 if split_count == 0 else max(0, 100 - split_count * 2)

        # ── C: HOLD Ratio ───────────────────────────────────────────────
        hold_pct = hold_count / total
        if hold_pct < 0.05:
            score_c = 100.0
        elif hold_pct < 0.12:
            score_c = 100.0 - hold_pct * 400.0
        else:
            score_c = max(0, 60.0 - (hold_pct - 0.12) * 500.0)

        # ── D: Ghost Frame Ratio (Idea 2 — concrete cross-reference) ────
        talking_thresh = float(self.profile.get("params", {}).get(
            "HS_TALKING_THRESHOLD", DEFAULT_PARAMS["HS_TALKING_THRESHOLD"]
        ))
        ghost_floor = talking_thresh * 0.20   # EMA must exceed this to be "real"

        ghost_left  = 0   # how many frames left slot was ghost-tracking
        ghost_right = 0   # how many frames right slot was ghost-tracking
        for d in decisions:
            if d.get("left_face") and d.get("ema_l", 0) < ghost_floor:
                ghost_left += 1
            if d.get("right_face") and d.get("ema_r", 0) < ghost_floor:
                ghost_right += 1

        ghost_frames = ghost_left + ghost_right
        ghost_pct    = ghost_frames / max(total, 1)
        # Which slot is worse? — used to give targeted advice in deltas
        ghost_slot   = "left" if ghost_left > ghost_right else ("right" if ghost_right > ghost_left else "both")

        score_d = 100.0 if ghost_pct < 0.05 else (
            max(0, 100.0 - ghost_pct * 450.0) if ghost_pct < 0.20
            else max(0, 20.0 - (ghost_pct - 0.20) * 100.0)
        )

        # ── E: Scene Cut Accuracy (Idea 3) ──────────────────────────────
        # Compare runtime [SCENE_CUT] frames vs ground-truth cluster boundaries
        scene_cuts_detected = [
            d.get("t", 0) for d in decisions if d.get("scene_cut") is True
        ]
        if not scene_seg_cuts:
            score_e = 85.0   # no ground truth = neutral
        elif not scene_cuts_detected:
            score_e = max(0, 100.0 - len(scene_seg_cuts) * 15.0)
        else:
            matched   = sum(
                1 for gt in scene_seg_cuts
                if any(abs(dt - gt) < 0.5 for dt in scene_cuts_detected)
            )
            recall    = matched / len(scene_seg_cuts)
            precision = matched / max(len(scene_cuts_detected), 1)
            f1        = 2 * recall * precision / max(recall + precision, 0.001)
            score_e   = f1 * 100.0

        # ── Weighted total ──────────────────────────────────────────────
        weights     = {"A": 0.25, "B": 0.25, "C": 0.20, "D": 0.20, "E": 0.10}
        scores      = {"A": score_a, "B": score_b, "C": score_c, "D": score_d, "E": score_e}
        total_score = sum(weights[k] * scores[k] for k in weights)

        # ── Human-readable flags ────────────────────────────────────────
        flags = []
        if spm > 15:
            flags.append(f"MODE_JITTER(spm={spm:.1f})")
        if spm < 1.5:
            flags.append(f"STATIC_CAMERA(spm={spm:.1f})")
        if is_podcast and split_pct < 0.05:
            flags.append(f"SPLIT_BLIND({split_pct*100:.1f}%)")
        if hold_pct > 0.20:
            flags.append(f"HOLD_FLOOD({hold_pct*100:.1f}%)")
        if ghost_pct > 0.20:
            flags.append(f"GHOST_TRACKING(slot={ghost_slot},{ghost_pct*100:.1f}%)")
        if score_e < 50 and scene_seg_cuts:
            flags.append(f"SCENE_CUT_MISS(f1={score_e:.0f}%)")

        return {
            "total_score":      total_score,
            "dimension_scores": scores,
            "switches_per_min": spm,
            "split_pct":        split_pct if is_podcast else None,
            "hold_pct":         hold_pct,
            "ghost_pct":        ghost_pct,
            "ghost_slot":       ghost_slot,   # "left" / "right" / "both"
            "ghost_left_frames": ghost_left,
            "ghost_right_frames": ghost_right,
            "scene_cuts_detected": len(scene_cuts_detected),
            "scene_cuts_ground_truth": len(scene_seg_cuts),
            "flags":            flags,
            "mode_counts":      mode_counts,
            "total_frames":     total,
            "duration_s":       duration,
        }

    # ------------------------------------------------------------------
    # Delta Engine — Idea 1 (Auto-Tune)
    # ------------------------------------------------------------------

    def _compute_deltas(self, report: Dict, clip_format: str) -> Dict[str, Tuple]:
        """Returns {param: (old_val, new_val)} for each param to adjust."""
        stored = self.profile.get("params", {})
        deltas: Dict[str, Tuple] = {}

        def current(key: str) -> float:
            return float(stored.get(key, DEFAULT_PARAMS[key]))

        def suggest(key: str, new_val: float):
            lo, hi = PARAM_BOUNDS[key]
            old    = current(key)
            lerped = old + LEARNING_RATE * (new_val - old)
            deltas[key] = (old, max(lo, min(hi, lerped)))

        flags = set(f.split("(")[0] for f in report.get("flags", []))

        # A: Mode jitter vs static
        if "MODE_JITTER" in flags:
            spm = report["switches_per_min"]
            suggest("HS_MIN_SWITCH_FRAMES",
                    current("HS_MIN_SWITCH_FRAMES") * (1.0 + (spm - 8) / 10.0))
        elif "STATIC_CAMERA" in flags:
            suggest("HS_MIN_SWITCH_FRAMES",
                    current("HS_MIN_SWITCH_FRAMES") * 0.75)

        # B: SPLIT blind vs too much splitting
        if "SPLIT_BLIND" in flags and clip_format in ("podcast", "bimodal"):
            suggest("HS_SPLIT_MIN_GAP", current("HS_SPLIT_MIN_GAP") * 0.85)
        elif clip_format in ("podcast", "bimodal"):
            sp = report.get("split_pct") or 0
            if sp > 0.40:
                suggest("HS_SPLIT_MIN_GAP", current("HS_SPLIT_MIN_GAP") * 1.08)

        # C: Hold flood = talking threshold too strict
        if "HOLD_FLOOD" in flags:
            suggest("HS_TALKING_THRESHOLD", current("HS_TALKING_THRESHOLD") * 0.80)

        # D: Ghost tracking — Idea 2 cross-reference result
        if "GHOST_TRACKING" in flags:
            # Ghost means EMA never crossed threshold: raise threshold SLIGHTLY
            # so the ghost slot needs stronger mouth motion to "claim" talking
            suggest("HS_TALKING_THRESHOLD", current("HS_TALKING_THRESHOLD") * 1.15)
            # Also lift EMA_FLOOR so ghost can't stay at 0 for 60 seconds
            suggest("HS_EMA_FLOOR", max(current("HS_EMA_FLOOR") + 1.0, 2.0))
            # Ghost detector: if one side dominates, record it for future inspection
            ghost_slot = report.get("ghost_slot", "both")
            self.profile.setdefault("ghost_history", []).append({
                "slot": ghost_slot,
                "pct":  round(report["ghost_pct"], 3),
                "ts":   datetime.utcnow().isoformat(),
            })
            # Keep last 10 ghost events
            self.profile["ghost_history"] = self.profile["ghost_history"][-10:]

        # E: Scene cut miss → lower detection threshold
        if "SCENE_CUT_MISS" in flags:
            suggest("HS_SCENE_CUT_THRESHOLD", current("HS_SCENE_CUT_THRESHOLD") * 0.85)

        # Reward: if score improved vs avg, slightly relax MIN_SWITCH_FRAMES
        avg_score = self.profile.get("avg_score", 0)
        if report["total_score"] > avg_score + 10 and "MODE_JITTER" not in flags:
            suggest("HS_MIN_SWITCH_FRAMES",
                    max(4, current("HS_MIN_SWITCH_FRAMES") - 1))

        return deltas

    # ------------------------------------------------------------------
    # Profile management — Idea 5 (Channel DNA)
    # ------------------------------------------------------------------

    def _apply_deltas(self, deltas: Dict, score: float):
        params = self.profile.setdefault("params", {})
        for key, (old, new) in deltas.items():
            params[key] = new

        # Update rolling average score
        history = self.profile.setdefault("score_history", [])
        history.append(round(score, 2))
        if len(history) > HISTORY_MAX_RUNS:
            history.pop(0)
        self.profile["score_history"] = history
        self.profile["avg_score"]     = round(sum(history) / len(history), 2)
        self.profile["best_score"]    = round(max(history), 2)
        self.profile["runs"]          = self.profile.get("runs", 0) + 1
        self.profile["last_updated"]  = datetime.utcnow().isoformat()

    def _load_profile(self, channel_id: str) -> Dict:
        os.makedirs(PROFILES_DIR, exist_ok=True)
        path = os.path.join(PROFILES_DIR, f"{channel_id}.json")
        if os.path.exists(path):
            try:
                p = json.load(open(path, encoding="utf-8"))
                log.info(
                    f"[AUTOPSY] Loaded DNA: {channel_id} "
                    f"runs={p.get('runs',0)} avg_score={p.get('avg_score','N/A')}"
                )
                return p
            except Exception as e:
                log.warning(f"[AUTOPSY] Corrupt profile: {e}")
        return {
            "channel_id":    channel_id,
            "runs":          0,
            "params":        dict(DEFAULT_PARAMS),
            "score_history": [],
            "avg_score":     0.0,
            "best_score":    0.0,
            "ghost_history": [],
        }

    def _save_profile(self):
        os.makedirs(PROFILES_DIR, exist_ok=True)
        path = os.path.join(PROFILES_DIR, f"{self.channel_id}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.profile, f, indent=2)

    @staticmethod
    def _sanitize_id(channel_id: str) -> str:
        return re.sub(r"[^\w\-]", "_", str(channel_id))[:64] or "default"


# ──────────────────────────────────────────────────────────────────────
# Convenience helpers
# ──────────────────────────────────────────────────────────────────────

def load_and_apply_channel_dna(channel_id: str) -> "DirectorAutopsy":
    """
    Call at TOP of render job.
    Loads channel profile, injects calibrated env vars, returns autopsy object.
    """
    autopsy = DirectorAutopsy(channel_id=channel_id)
    autopsy.apply_to_env()
    return autopsy


def run_post_render_autopsy(
    autopsy: "DirectorAutopsy",
    clip_id: str,
    clip_format: str = "unknown",
    scene_seg_cuts: Optional[List[float]] = None,
) -> Optional[Dict]:
    """
    Call AFTER each clip render.
    Locates debug_out/{clip_id}/decisions.json, runs full autopsy.
    Returns report dict or None if no decisions.json found.
    """
    debug_out      = os.path.join(BASE_DIR, "debug_out")
    decisions_path = os.path.join(debug_out, clip_id, "decisions.json")
    if not os.path.exists(decisions_path):
        log.info(f"[AUTOPSY] No decisions.json for clip_id={clip_id} (set HS_DEBUG_FRAMES=1 to enable)")
        return None
    return autopsy.analyze(
        decisions_path,
        clip_format=clip_format,
        scene_seg_cuts=scene_seg_cuts,
    )
