import time
import json
import os
from contextlib import contextmanager
from typing import Dict, Any, Optional

class BoltRuntime:
    """
    ⚡ BOLT Runtime (MVP)
    Lightweight performance telemetry & observability engine.
    No dependencies, < 200 lines.
    """
    def __init__(self):
        self.reset()

    def reset(self):
        self.start_time = time.perf_counter()
        self.stage_times: Dict[str, float] = {}
        self.counters: Dict[str, int] = {
            "video_open": 0,
            "ffmpeg_encode": 0,
            "frames_decoded": 0,
            "frames_consumed": 0,
            "duplicate_decodes": 0,
        }
        self.active_stages = []
        self._stage_starts = {}

    @contextmanager
    def stage(self, name: str):
        """Context manager to measure wall-clock execution time of a pipeline stage."""
        t0 = time.perf_counter()
        self.active_stages.append(name)
        try:
            yield
        finally:
            elapsed = time.perf_counter() - t0
            self.stage_times[name] = self.stage_times.get(name, 0.0) + elapsed
            if self.active_stages and self.active_stages[-1] == name:
                self.active_stages.pop()

    def counter(self, name: str, inc: int = 1):
        """Increment a named performance counter (e.g., 'video_open', 'ffmpeg_encode')."""
        self.counters[name] = self.counters.get(name, 0) + inc

    def emit(self, event: str, **payload):
        """Emit standardized BOLT events and automatically map to counters."""
        if event == "video_open":
            self.counter("video_open")
        elif event == "encode_start" or event == "ffmpeg_encode":
            self.counter("ffmpeg_encode")
        elif event == "frame_decode" or event == "frame_decoded":
            self.counter("frames_decoded", payload.get("count", 1))
        elif event == "frame_consumed":
            self.counter("frames_consumed", payload.get("count", 1))

    def get_report_data(self) -> Dict[str, Any]:
        """Generate structured dictionary of telemetry metrics."""
        total_time = time.perf_counter() - self.start_time
        # Use sum of top stages if stage_times exists, else total_time
        return {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "pipeline_total_s": round(total_time, 2),
            "stages_s": {k: round(v, 2) for k, v in self.stage_times.items()},
            "counters": dict(self.counters),
        }

    def format_report(self) -> str:
        """Format human-readable ⚡ BOLT REPORT summary."""
        data = self.get_report_data()
        lines = [
            "\n" + "="*40,
            "⚡ BOLT REPORT",
            "="*40,
        ]
        if data["stages_s"]:
            for stage, duration in data["stages_s"].items():
                lines.append(f"{stage.ljust(20)} {duration:.1f}s")
            lines.append("-" * 40)
        
        for counter_name, val in data["counters"].items():
            if val > 0 or counter_name in ("video_open", "ffmpeg_encode"):
                label = counter_name.replace("_", " ").title()
                lines.append(f"{label.ljust(20)} {val}")
                
        lines.append(f"{'Pipeline Total'.ljust(20)} {data['pipeline_total_s']:.1f}s")
        lines.append("="*40 + "\n")
        return "\n".join(lines)

    def save_report(self, filepath: str = "bolt_report.json", print_report: bool = True):
        """Save telemetry report to JSON and optionally print CLI summary."""
        data = self.get_report_data()
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[BOLT] Error saving JSON report to {filepath}: {e}")

        if print_report:
            try:
                print(self.format_report(), flush=True)
            except UnicodeEncodeError:
                print(self.format_report().replace("⚡", "[BOLT]").encode("ascii", "replace").decode("ascii"), flush=True)
        return data

# Singleton global runtime instance
_default_runtime = BoltRuntime()

# Clean module-level exports for exact user syntax:
# import utils.bolt as bolt -> bolt.stage("Decode"), bolt.counter(...)
stage = _default_runtime.stage
counter = _default_runtime.counter
emit = _default_runtime.emit
save_report = _default_runtime.save_report
get_report_data = _default_runtime.get_report_data
format_report = _default_runtime.format_report
reset = _default_runtime.reset
