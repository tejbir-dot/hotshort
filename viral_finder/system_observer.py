"""
system_observer.py — Centralized Observability & Tracing for HotShort.
Tracks stages and candidate lifecycles to make the pipeline transparent.
"""

from __future__ import annotations
import time
import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger("system_observer")

def safe_fmt(value, fmt=".1f"):
    if value is None:
        return "N/A"
    try:
        return format(value, fmt)
    except Exception:
        return str(value)

class SystemObserver:
    def __init__(self):
        # stage_name -> {input_count, output_count, wall_time, reject_reasons}
        self.stages: Dict[str, Dict[str, Any]] = {}
        # candidate_id -> {created_by, scores, modified_by, rejected_by, rescued_by, final_reason, history}
        self.candidates: Dict[str, Dict[str, Any]] = {}
        # list of messages for general trace debugging
        self.general_logs: List[str] = []

    def log_stage(
        self,
        name: str,
        input_count: int,
        output_count: int,
        wall_time: float,
        reject_reasons: Optional[Dict[str, int]] = None
    ) -> None:
        self.stages[name] = {
            "input_count": input_count,
            "output_count": output_count,
            "wall_time": wall_time,
            "reject_reasons": dict(reject_reasons or {}),
        }

    def init_candidate(self, cid: str, created_by: str, text: str, start: float, end: float, scores: Optional[Dict[str, float]] = None) -> None:
        start_str = f"{safe_fmt(start)}s" if start is not None else "N/A"
        end_str = f"{safe_fmt(end)}s" if end is not None else "N/A"
        self.candidates[cid] = {
            "cid": cid,
            "created_by": created_by,
            "text": text,
            "start": start,
            "end": end,
            "scores": dict(scores or {}),
            "modified_by": [],
            "rejected_by": [],
            "rescued_by": [],
            "final_reason": "active",
            "history": [f"Created by {created_by} at {start_str}-{end_str}"],
        }

    def modify_candidate(self, cid: str, modified_by: str, changes: Optional[Dict[str, Any]] = None) -> None:
        if cid not in self.candidates:
            return
        c = self.candidates[cid]
        c["modified_by"].append(modified_by)
        desc = f"Modified by {modified_by}"
        if changes:
            desc += f" (changes: {changes})"
            for k, v in changes.items():
                if k in ("start", "end"):
                    c[k] = v
                elif k == "scores":
                    c["scores"].update(v)
        c["history"].append(desc)

    def reject_candidate(self, cid: str, rejected_by: str, reason: str) -> None:
        if cid not in self.candidates:
            return
        c = self.candidates[cid]
        c["rejected_by"].append(rejected_by)
        c["final_reason"] = f"rejected ({reason})"
        c["history"].append(f"Rejected by {rejected_by}: {reason}")

    def rescue_candidate(self, cid: str, rescued_by: str, reason: str) -> None:
        if cid not in self.candidates:
            return
        c = self.candidates[cid]
        c["rescued_by"].append(rescued_by)
        c["final_reason"] = "rescued"
        c["history"].append(f"Rescued by {rescued_by}: {reason}")

    def finalize_candidate(self, cid: str, reason: str = "output") -> None:
        if cid not in self.candidates:
            return
        c = self.candidates[cid]
        c["final_reason"] = reason
        c["history"].append(f"Finalized as output: {reason}")

    def render_report(self) -> str:
        try:
            lines = []
            lines.append("=" * 60)
            lines.append("                 HOTSHORT PIPELINE X-RAY")
            lines.append("=" * 60)
            
            # 1. Stage Autopsies
            lines.append("\n[STAGE AUTOPSIES]")
            ordered_stages = [
                "FAST_PREFILTER",
                "STRICT_PASS",
                "RELAXED_PASS",
                "CANDIDATE_GENERATION",
                "HOOK_HUNTER",
                "BACKFILL",
                "GROQ_TRANSCRIPT_FIRST",
                "VALIDATION",
                "ARC_ASSEMBLER",
                "EDITOR_REFINER"
            ]
            
            # Add any other stages that were logged but not in ordered_stages
            all_logged = set(self.stages.keys())
            stages_to_show = ordered_stages + sorted(list(all_logged - set(ordered_stages)))

            for name in stages_to_show:
                if name not in self.stages:
                    continue
                s = self.stages[name]
                lines.append(f"\n⚡ {name}")
                wall_time = s.get("wall_time")
                wall_time_str = f"{safe_fmt(wall_time, '.3f')}s" if wall_time is not None else "N/A"
                lines.append(f"   input={s['input_count']} | output={s['output_count']} | time={wall_time_str}")
                if s["reject_reasons"]:
                    lines.append("   Rejected:")
                    for r, count in s["reject_reasons"].items():
                        lines.append(f"     {r} = {count}")

            # 2. Clip Lifecycles
            lines.append("\n" + "=" * 60)
            lines.append("                CLIP LIFECYCLE TRACE")
            lines.append("=" * 60)

            for cid, c in sorted(self.candidates.items()):
                start = c.get("start")
                end = c.get("end")
                start_str = f"{safe_fmt(start)}s" if start is not None else "N/A"
                end_str = f"{safe_fmt(end)}s" if end is not None else "N/A"
                lines.append(f"\n📌 {cid} | {start_str} - {end_str} | Status: {c['final_reason']}")
                lines.append(f"   Text: \"{c['text'][:100]}...\"")
                if c["scores"]:
                    score_str = ", ".join(f"{k}={safe_fmt(v, '.2f')}" for k, v in c["scores"].items())
                    lines.append(f"   Scores: {score_str}")
                lines.append("   History:")
                for h in c["history"]:
                    lines.append(f"     → {h}")

            lines.append("\n" + "=" * 60)
            return "\n".join(lines)
        except Exception as e:
            log.exception("[XRAY] render_report failed internally")
            return "[XRAY] report generation failed"


# Global singleton for current execution run
# Will be initialized at the start of orchestrate()
_active_observer: Optional[SystemObserver] = None


def get_observer() -> SystemObserver:
    global _active_observer
    if _active_observer is None:
        _active_observer = SystemObserver()
    return _active_observer


def reset_observer() -> SystemObserver:
    global _active_observer
    _active_observer = SystemObserver()
    return _active_observer
