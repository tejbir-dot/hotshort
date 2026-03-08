"""
Lightweight runtime pipeline trace for orchestrator stage visibility.
Enabled via HS_PIPELINE_TRACE=1.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional


class PipelineTrace:
    def __init__(self, enabled: bool = False, logger: Optional[Any] = None):
        self.enabled = bool(enabled)
        self.logger = logger
        self.trace: List[Dict[str, Any]] = []
        self._open: Dict[str, float] = {}

    def enter(self, stage_name: str) -> None:
        if not self.enabled:
            return
        now = time.time()
        self._open[stage_name] = now
        self.trace.append(
            {
                "stage": stage_name,
                "timestamp": now,
                "status": "enter",
                "metrics": {},
            }
        )

    def exit(self, stage_name: str, metrics: Optional[Dict[str, Any]] = None) -> None:
        if not self.enabled:
            return
        now = time.time()
        started = self._open.pop(stage_name, None)
        payload = dict(metrics or {})
        if started is not None:
            payload.setdefault("wall_ms", int((now - started) * 1000.0))
        self.trace.append(
            {
                "stage": stage_name,
                "timestamp": now,
                "status": "ok",
                "metrics": payload,
            }
        )

    def error(self, stage_name: str, reason: str, metrics: Optional[Dict[str, Any]] = None) -> None:
        if not self.enabled:
            return
        now = time.time()
        payload = dict(metrics or {})
        payload["reason"] = str(reason or "unknown")
        self.trace.append(
            {
                "stage": stage_name,
                "timestamp": now,
                "status": "error",
                "metrics": payload,
            }
        )

    def render(self) -> None:
        if not self.enabled:
            return
        # Only render terminal entries (ok/error) and dedupe by latest per stage.
        latest: Dict[str, Dict[str, Any]] = {}
        order: List[str] = []
        for row in self.trace:
            st = str(row.get("stage", ""))
            if not st:
                continue
            if row.get("status") in ("ok", "error"):
                if st not in latest:
                    order.append(st)
                latest[st] = row

        lines = ["PIPELINE TRACE"]
        for idx, stage in enumerate(order):
            row = latest.get(stage, {})
            status = row.get("status", "ok")
            metrics = row.get("metrics", {}) or {}
            branch = "└" if idx == len(order) - 1 else "├"
            if status == "error":
                lines.append(f"{branch} {stage} [ERROR]")
            else:
                lines.append(f"{branch} {stage}")
            if metrics:
                for k, v in metrics.items():
                    lines.append(f"│   {k}={v}")

        out = "\n".join(lines)
        if self.logger is not None:
            try:
                self.logger.info("\n%s", out)
                return
            except Exception:
                pass
        print(out)

