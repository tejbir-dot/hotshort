"""
pipeline_benchmark.py — HotShort Per-Job Hardware Profiler
===========================================================
Auto-imported by local_worker.py.  Creates one report per video run saved to:

    scratch/benchmarks/<job_id>_<timestamp>.json
    scratch/benchmarks/<job_id>_<timestamp>.txt

Usage inside local_worker.py:
    from pipeline_benchmark import JobBenchmark

    bench = JobBenchmark(job_id, youtube_url)
    bench.begin("download")
    ...
    bench.finish("download")
    bench.save()   # at the very end of _process_job
"""

import os
import sys
import time
import json
import threading
import statistics
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# ── Optional deps ─────────────────────────────────────────────────────────────
try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False

try:
    import pynvml
    pynvml.nvmlInit()
    _nvml_handle = pynvml.nvmlDeviceGetHandleByIndex(0)
    _HAS_NVML = True
except Exception:
    _HAS_NVML = False

_BASE_DIR = os.path.abspath(os.path.dirname(__file__))
_BENCH_DIR = os.path.join(_BASE_DIR, "scratch", "benchmarks")


# ── Raw sample ────────────────────────────────────────────────────────────────
@dataclass
class _HWSample:
    ts: float
    cpu_pct: float = 0.0
    ram_gb: float = 0.0
    disk_r_mb: float = 0.0   # cumulative since process start
    disk_w_mb: float = 0.0
    gpu_pct: float = 0.0
    vram_gb: float = 0.0
    gpu_temp_c: float = 0.0


# ── Stage window ──────────────────────────────────────────────────────────────
@dataclass
class _Stage:
    name: str
    t_start: float
    t_end: float = 0.0
    wall_s: float = 0.0

    def close(self):
        self.t_end = time.time()
        self.wall_s = self.t_end - self.t_start


# ── Stats helper ──────────────────────────────────────────────────────────────
def _stats(vals: List[float]) -> Tuple[float, float, float]:
    if not vals:
        return 0.0, 0.0, 0.0
    return min(vals), statistics.mean(vals), max(vals)


def _delta_mb(samples: List[_HWSample], attr: str) -> float:
    """Total MB transferred during a stage window (max - min of cumulative counter)."""
    vals = [getattr(s, attr) for s in samples]
    return (max(vals) - min(vals)) if len(vals) > 1 else 0.0


# ── Continuous sampler ────────────────────────────────────────────────────────
class _Sampler:
    def __init__(self, interval: float = 0.5):
        self.interval = interval
        self._samples: List[_HWSample] = []
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        # disk baseline
        self._disk_r0 = 0.0
        self._disk_w0 = 0.0
        if _HAS_PSUTIL:
            dc = psutil.disk_io_counters()
            if dc:
                self._disk_r0 = dc.read_bytes / 1e6
                self._disk_w0 = dc.write_bytes / 1e6

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                         name="BenchSampler")
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)

    def samples_between(self, t0: float, t1: float) -> List[_HWSample]:
        with self._lock:
            return [s for s in self._samples if t0 <= s.ts <= t1]

    def all_samples(self) -> List[_HWSample]:
        with self._lock:
            return list(self._samples)

    def _loop(self):
        while self._running:
            s = self._collect()
            with self._lock:
                self._samples.append(s)
            time.sleep(self.interval)

    def _collect(self) -> _HWSample:
        s = _HWSample(ts=time.time())
        if _HAS_PSUTIL:
            try:
                s.cpu_pct = psutil.cpu_percent(interval=None)
                s.ram_gb = psutil.virtual_memory().used / 1e9
                dc = psutil.disk_io_counters()
                if dc:
                    s.disk_r_mb = dc.read_bytes / 1e6 - self._disk_r0
                    s.disk_w_mb = dc.write_bytes / 1e6 - self._disk_w0
            except Exception:
                pass

        if _HAS_NVML:
            try:
                util = pynvml.nvmlDeviceGetUtilizationRates(_nvml_handle)
                s.gpu_pct = float(util.gpu)
                mem = pynvml.nvmlDeviceGetMemoryInfo(_nvml_handle)
                s.vram_gb = mem.used / 1e9
                s.gpu_temp_c = float(pynvml.nvmlDeviceGetTemperature(
                    _nvml_handle, pynvml.NVML_TEMPERATURE_GPU))
            except Exception:
                pass
        elif shutil.which("nvidia-smi"):
            try:
                raw = subprocess.check_output(
                    ["nvidia-smi",
                     "--query-gpu=utilization.gpu,memory.used,temperature.gpu",
                     "--format=csv,noheader,nounits"],
                    timeout=2, stderr=subprocess.DEVNULL
                ).decode().strip().split(",")
                s.gpu_pct = float(raw[0])
                s.vram_gb = float(raw[1]) / 1024.0
                s.gpu_temp_c = float(raw[2])
            except Exception:
                pass
        return s


# ── Main class ────────────────────────────────────────────────────────────────
class JobBenchmark:
    """
    Attach to a single _process_job() run.

    bench = JobBenchmark(job_id, youtube_url)
    bench.begin("download")
    ...do work...
    bench.finish("download")
    bench.save()
    """

    def __init__(self, job_id: str, youtube_url: str = ""):
        self.job_id = job_id
        self.youtube_url = youtube_url
        self.t_job_start = time.time()
        self._sampler = _Sampler(interval=0.5)
        self._sampler.start()
        self._stages: List[_Stage] = []
        self._open: Dict[str, _Stage] = {}   # stages that have begun but not finished
        print(f"[BENCH] Job benchmark started: {job_id}", flush=True)

    # ── Stage control ─────────────────────────────────────────────────────────
    def begin(self, name: str):
        """Mark the start of a named stage."""
        st = _Stage(name=name, t_start=time.time())
        self._open[name] = st

    def finish(self, name: str):
        """Mark the end of a named stage."""
        st = self._open.pop(name, None)
        if st is None:
            # stage was never begun — create a zero-duration placeholder
            st = _Stage(name=name, t_start=time.time())
        st.close()
        self._stages.append(st)
        print(
            f"[BENCH] stage={name:30s}  wall={st.wall_s:>7.1f}s",
            flush=True,
        )

    # ── Save ──────────────────────────────────────────────────────────────────
    def save(self):
        """Stop sampler, generate report, write to scratch/benchmarks/."""
        # Close any stages that were started but never finished
        for name, st in list(self._open.items()):
            st.close()
            self._stages.append(st)
        self._open.clear()

        self._sampler.stop()
        t_job_end = time.time()
        total_wall = t_job_end - self.t_job_start

        os.makedirs(_BENCH_DIR, exist_ok=True)
        ts_str = time.strftime("%Y%m%d_%H%M%S", time.localtime(self.t_job_start))
        safe_id = self.job_id[:32].replace("/", "_").replace("\\", "_")
        base_name = f"{safe_id}_{ts_str}"

        txt_path  = os.path.join(_BENCH_DIR, base_name + ".txt")
        json_path = os.path.join(_BENCH_DIR, base_name + ".json")

        report_lines, json_data = self._build_report(total_wall)

        with open(txt_path,  "w", encoding="utf-8") as f:
            f.write("\n".join(report_lines))
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(json_data, f, indent=2)

        # Also print to console
        print("\n" + "\n".join(report_lines), flush=True)
        print(f"\n[BENCH] Saved -> {txt_path}", flush=True)
        print(f"[BENCH] Saved -> {json_path}", flush=True)

    # ── Report builder ────────────────────────────────────────────────────────
    def _build_report(self, total_wall: float):
        SEP = "=" * 120
        lines = [
            "",
            SEP,
            f"  HOTSHORT PIPELINE BENCHMARK",
            f"  Job      : {self.job_id}",
            f"  URL      : {self.youtube_url[:90]}",
            f"  Started  : {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self.t_job_start))}",
            f"  Total    : {total_wall:.1f}s  ({total_wall/60:.1f} min)",
            SEP,
            f"  {'Stage':<32} {'Time':>7}  {'%Total':>7}  "
            f"{'CPU avg/max':>12}  {'RAM GB':>7}  "
            f"{'GPU avg/max':>12}  {'VRAM GB':>7}  "
            f"{'Temp':>5}  {'Disk R':>7}  {'Disk W':>7}",
            "-" * 120,
        ]

        json_stages = []
        for st in self._stages:
            samps = self._sampler.samples_between(st.t_start, st.t_end)
            _, ca, cm = _stats([s.cpu_pct for s in samps])
            _, ra, _  = _stats([s.ram_gb  for s in samps])
            _, ga, gm = _stats([s.gpu_pct for s in samps])
            _, va, _  = _stats([s.vram_gb for s in samps])
            gt = max((s.gpu_temp_c for s in samps), default=0.0)
            dr = _delta_mb(samps, "disk_r_mb")
            dw = _delta_mb(samps, "disk_w_mb")
            pct = st.wall_s / max(total_wall, 0.001) * 100

            lines.append(
                f"  {st.name[:32]:<32} {st.wall_s:>6.1f}s  {pct:>6.1f}%  "
                f"{ca:>5.1f}/{cm:>5.1f}%  {ra:>5.2f} GB  "
                f"{ga:>5.1f}/{gm:>5.1f}%  {va:>5.2f} GB  "
                f"{gt:>4.0f}C  {dr:>5.0f} MB  {dw:>5.0f} MB"
            )
            json_stages.append({
                "name": st.name, "wall_s": round(st.wall_s, 2),
                "pct_total": round(pct, 1),
                "cpu_avg": round(ca, 1), "cpu_max": round(cm, 1),
                "ram_avg_gb": round(ra, 2),
                "gpu_avg": round(ga, 1), "gpu_max": round(gm, 1),
                "vram_avg_gb": round(va, 2),
                "gpu_temp_max_c": round(gt, 0),
                "disk_read_mb": round(dr, 1),
                "disk_write_mb": round(dw, 1),
            })

        lines += [
            "-" * 120,
            f"  {'TOTAL':<32} {total_wall:>6.1f}s  100.0%",
            SEP,
            "",
            "  TIMELINE (proportional)",
            "",
        ]

        # Timeline bar
        for st in self._stages:
            pct = st.wall_s / max(total_wall, 0.001) * 100
            bar = "\u2588" * int(pct / 100 * 60)
            lines.append(f"  {st.name[:28]:<28}  {bar:<60}  {st.wall_s:>6.1f}s  ({pct:.1f}%)")

        lines.append("")
        lines.append(SEP)

        json_data = {
            "job_id": self.job_id,
            "youtube_url": self.youtube_url,
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.t_job_start)),
            "total_wall_s": round(total_wall, 2),
            "hw_available": {
                "psutil": _HAS_PSUTIL,
                "pynvml": _HAS_NVML,
                "nvidia_smi": bool(shutil.which("nvidia-smi")),
            },
            "stages": json_stages,
        }
        return lines, json_data
