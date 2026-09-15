"""
HotShort Pipeline Benchmark
============================
Instruments the full pipeline and reports per-stage hardware usage.

Usage:
    python benchmark.py --url "https://youtu.be/..." [--top-k 3]
    python benchmark.py --file path/to/video.mp4 [--top-k 3]

Output:
    Stage table: CPU%, GPU%, RAM GB, VRAM GB, Disk R/W MB, Time, GPU Temp
    Timeline bar chart
    benchmark_results.json saved to cwd
"""

import argparse
import os
import sys
import time
import threading
import json
import shutil
import statistics
import subprocess
from dataclasses import dataclass, field
from typing import List, Optional
from contextlib import contextmanager

# ── Optional deps ─────────────────────────────────────────────────────────────
try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False
    print("[BENCH] psutil not installed — install: pip install psutil")

try:
    import pynvml
    pynvml.nvmlInit()
    _nvml_handle = pynvml.nvmlDeviceGetHandleByIndex(0)
    _HAS_NVML = True
except Exception:
    _HAS_NVML = False


# ── Data ──────────────────────────────────────────────────────────────────────
@dataclass
class Sample:
    ts: float
    cpu_pct: float
    ram_gb: float
    disk_read_mb: float
    disk_write_mb: float
    gpu_pct: float = 0.0
    vram_gb: float = 0.0
    gpu_temp_c: float = 0.0


@dataclass
class StageResult:
    name: str
    wall_s: float
    samples: List[Sample] = field(default_factory=list)

    def _agg(self, vals):
        if not vals:
            return 0.0, 0.0, 0.0
        return min(vals), statistics.mean(vals), max(vals)

    @property
    def cpu(self): return self._agg([s.cpu_pct for s in self.samples])
    @property
    def ram(self): return self._agg([s.ram_gb for s in self.samples])
    @property
    def gpu(self): return self._agg([s.gpu_pct for s in self.samples])
    @property
    def vram(self): return self._agg([s.vram_gb for s in self.samples])
    @property
    def gpu_temp_max(self):
        t = [s.gpu_temp_c for s in self.samples]
        return max(t) if t else 0.0
    @property
    def disk_r(self):
        v = [s.disk_read_mb for s in self.samples]
        return (max(v) - min(v)) if len(v) > 1 else 0.0
    @property
    def disk_w(self):
        v = [s.disk_write_mb for s in self.samples]
        return (max(v) - min(v)) if len(v) > 1 else 0.0


# ── Sampler ───────────────────────────────────────────────────────────────────
class HardwareSampler:
    def __init__(self, interval: float = 0.5):
        self.interval = interval
        self._samples: List[Sample] = []
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._disk_base_r = 0.0
        self._disk_base_w = 0.0
        if _HAS_PSUTIL:
            c = psutil.disk_io_counters()
            if c:
                self._disk_base_r = c.read_bytes / 1e6
                self._disk_base_w = c.write_bytes / 1e6

    def start(self):
        self._samples.clear()
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> List[Sample]:
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
        return list(self._samples)

    def _loop(self):
        while self._running:
            self._samples.append(self._collect())
            time.sleep(self.interval)

    def _collect(self) -> Sample:
        cpu_pct = ram_gb = disk_r = disk_w = gpu_pct = vram_gb = gpu_temp = 0.0

        if _HAS_PSUTIL:
            try:
                cpu_pct = psutil.cpu_percent(interval=None)
                ram_gb = psutil.virtual_memory().used / 1e9
                dc = psutil.disk_io_counters()
                if dc:
                    disk_r = dc.read_bytes / 1e6 - self._disk_base_r
                    disk_w = dc.write_bytes / 1e6 - self._disk_base_w
            except Exception:
                pass

        if _HAS_NVML:
            try:
                util = pynvml.nvmlDeviceGetUtilizationRates(_nvml_handle)
                gpu_pct = float(util.gpu)
                mem = pynvml.nvmlDeviceGetMemoryInfo(_nvml_handle)
                vram_gb = mem.used / 1e9
                gpu_temp = float(pynvml.nvmlDeviceGetTemperature(
                    _nvml_handle, pynvml.NVML_TEMPERATURE_GPU))
            except Exception:
                pass
        elif shutil.which("nvidia-smi"):
            try:
                out = subprocess.check_output(
                    ["nvidia-smi",
                     "--query-gpu=utilization.gpu,memory.used,temperature.gpu",
                     "--format=csv,noheader,nounits"],
                    timeout=2, stderr=subprocess.DEVNULL
                ).decode().strip().split(",")
                gpu_pct = float(out[0])
                vram_gb = float(out[1]) / 1024.0
                gpu_temp = float(out[2])
            except Exception:
                pass

        return Sample(ts=time.time(), cpu_pct=cpu_pct, ram_gb=ram_gb,
                      disk_read_mb=disk_r, disk_write_mb=disk_w,
                      gpu_pct=gpu_pct, vram_gb=vram_gb, gpu_temp_c=gpu_temp)


# ── Globals ───────────────────────────────────────────────────────────────────
_sampler = HardwareSampler(interval=0.5)
_results: List[StageResult] = []


@contextmanager
def stage(name: str):
    print(f"\n[BENCH] >> {name}", flush=True)
    _sampler.start()
    t0 = time.perf_counter()
    try:
        yield
    finally:
        wall_s = time.perf_counter() - t0
        samples = _sampler.stop()
        r = StageResult(name=name, wall_s=wall_s, samples=samples)
        _results.append(r)
        print(f"[BENCH] << {name}  done in {wall_s:.1f}s", flush=True)


# ── Report ────────────────────────────────────────────────────────────────────
def print_report():
    SEP = "=" * 115
    print(f"\n\n{SEP}")
    print("  HOTSHORT PIPELINE BENCHMARK REPORT")
    print(SEP)
    print(f"  {'Stage':<26} {'Time':>7}  {'CPU avg/max':>12}  {'RAM GB':>7}  "
          f"{'GPU avg/max':>12}  {'VRAM GB':>7}  {'Temp':>5}  {'Disk R':>7}  {'Disk W':>7}")
    print("-" * 115)

    total = 0.0
    for r in _results:
        total += r.wall_s
        _, ca, cm = r.cpu
        _, ra, _  = r.ram
        _, ga, gm = r.gpu
        _, va, _  = r.vram
        print(f"  {r.name[:26]:<26} {r.wall_s:>6.1f}s  "
              f"{ca:>5.1f}/{cm:>5.1f}%  {ra:>5.2f} GB  "
              f"{ga:>5.1f}/{gm:>5.1f}%  {va:>5.2f} GB  "
              f"{r.gpu_temp_max:>4.0f}C  "
              f"{r.disk_r:>5.0f} MB  {r.disk_w:>5.0f} MB")

    print("-" * 115)
    print(f"  {'TOTAL':<26} {total:>6.1f}s")
    print(SEP)

    print("\n  PIPELINE TIMELINE\n")
    for r in _results:
        pct = r.wall_s / max(total, 0.001) * 100
        bar = "\u2588" * int(pct / 100 * 55)
        print(f"  {r.name[:22]:<22}  {bar:<55}  {r.wall_s:>6.1f}s  ({pct:.1f}%)")

    # Save JSON
    out = {"total_wall_s": total, "stages": [
        {"name": r.name, "wall_s": r.wall_s,
         "cpu_avg": r.cpu[1], "cpu_max": r.cpu[2],
         "ram_avg_gb": r.ram[1],
         "gpu_avg": r.gpu[1], "gpu_max": r.gpu[2],
         "vram_avg_gb": r.vram[1],
         "gpu_temp_max_c": r.gpu_temp_max,
         "disk_read_mb": r.disk_r,
         "disk_write_mb": r.disk_w}
        for r in _results
    ]}
    json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "benchmark_results.json")
    with open(json_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\n  Results saved -> {json_path}\n")


# ── Pipeline runner ───────────────────────────────────────────────────────────
def run_benchmark(video_source: str, top_k: int = 3, is_url: bool = True):
    import tempfile
    import traceback

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    tmp_dir = tempfile.mkdtemp(prefix="hs_bench_")
    video_path = video_source

    try:
        # Stage 1: Download
        if is_url:
            video_path = os.path.join(tmp_dir, "video.mp4")
            with stage("1. yt-dlp Download"):
                rc = subprocess.run([
                    sys.executable, "-m", "yt_dlp",
                    "--format", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                    "--merge-output-format", "mp4",
                    "-o", video_path, video_source
                ], capture_output=True, timeout=600)
                if rc.returncode != 0:
                    print(f"[BENCH] Download failed: {rc.stderr.decode()[:300]}")
                    return
        else:
            _results.append(StageResult("1. yt-dlp Download", 0.0))  # N/A for local file

        sz = os.path.getsize(video_path) / 1e6
        print(f"\n[BENCH] Video: {video_path}  ({sz:.1f} MB)\n")

        # Stage 2: Orchestration (Hook Hunter + clip selection)
        clips = []
        with stage("2. Orchestration"):
            try:
                from viral_finder.orchestrator import orchestrate
                clips = orchestrate(video_path, top_k=top_k, prefer_gpu=True,
                                    use_cache=True, allow_fallback=False,
                                    pipeline_mode="staged")
                print(f"[BENCH]   Selected {len(clips)} clips")
            except Exception as e:
                print(f"[BENCH] Orchestration error: {e}")
                traceback.print_exc()

        if not clips:
            print("[BENCH] No clips selected. Stopping.")
            return

        # Stage 3: FaceCache Haar Scan
        face_cache = None
        with stage("3. FaceCache (Haar Scan)"):
            try:
                from local_worker import FaceCache
                face_cache = FaceCache(video_path, clips)
                print(f"[BENCH]   {len(face_cache.cache)} frames cached")
            except Exception as e:
                print(f"[BENCH] FaceCache error: {e}")
                traceback.print_exc()

        # Stage 4: Clip extraction (ffmpeg decode + encode)
        raw_clips = []
        with stage("4. Clip Extraction (ffmpeg)"):
            try:
                from effects.world_class_editor import _hwaccel_decode_args, _video_encode_args
                for i, clip in enumerate(clips):
                    s = float(clip.get("start", 0))
                    e = float(clip.get("end", s + 30))
                    rp = os.path.join(tmp_dir, f"raw_{i}.mp4")
                    try:
                        # Build GPU-accelerated FFmpeg command
                        cmd = ["ffmpeg", "-y", "-nostdin"]
                        
                        # Add NVDEC decode args BEFORE input
                        cmd.extend(_hwaccel_decode_args(video_path))
                        
                        cmd.extend(["-ss", str(s), "-to", str(e), "-i", video_path])
                        
                        # Add NVENC encode args AFTER input
                        encode_args = _video_encode_args(crf=18, preset="fast")
                        
                        # Remove specific complex WCE encoding args for simple raw extraction
                        # Keep it simple: use the encoder and preset
                        vcodec = "libx264"
                        preset = "ultrafast"
                        if "h264_nvenc" in encode_args:
                            vcodec = "h264_nvenc"
                            preset = "p4"
                            
                        cmd.extend(["-c:v", vcodec, "-preset", preset, "-c:a", "aac", rp])
                        
                        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       timeout=300, check=True)
                        raw_clips.append((i, clip, rp))
                        print(f"[BENCH]   clip {i}: {s:.1f}-{e:.1f}s  "
                              f"[{vcodec}] ({os.path.getsize(rp)/1e6:.1f} MB)")
                    except Exception as ex:
                        print(f"[BENCH]   clip {i} failed: {ex}")
            except Exception as ex:
                print(f"[BENCH] Clip extraction setup failed: {ex}")

        # Stage 5: World Class Editor (Director + crop + captions)
        edited_clips = []
        with stage("5. World Class Editor"):
            try:
                from effects.world_class_editor import ClipEditor, ClipEditConfig
                wd = os.path.join(tmp_dir, "wce")
                os.makedirs(wd, exist_ok=True)
                editor = ClipEditor(wd)
                cfg = ClipEditConfig()
                for i, clip, rp in raw_clips:
                    s = float(clip.get("start", 0))
                    e = float(clip.get("end", s + 30))
                    op = os.path.join(tmp_dir, f"edited_{i}.mp4")
                    try:
                        res = editor.process(
                            rp, output_path=op,
                            source_start=s, source_end=e,
                            transcript=clip.get("transcript") or [],
                            config=cfg,
                            precomputed_face_cache=(
                                face_cache.get_clip_cache(clip) if face_cache else {}
                            ),
                        )
                        if res:
                            edited_clips.append(op)
                            esz = os.path.getsize(op) / 1e6
                            print(f"[BENCH]   edited clip {i}  ({esz:.1f} MB)")
                    except Exception as ex:
                        print(f"[BENCH]   editor clip {i} failed: {ex}")
                        traceback.print_exc()
            except Exception as ex:
                print(f"[BENCH] WCE load error: {ex}")
                traceback.print_exc()

        # Stage 6: Output write
        out_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "scratch", "bench_out"
        )
        os.makedirs(out_dir, exist_ok=True)
        with stage("6. Output Write"):
            final = edited_clips or [r[2] for r in raw_clips]
            for i, path in enumerate(final):
                dst = os.path.join(out_dir, f"bench_clip_{i}.mp4")
                shutil.copy2(path, dst)
                print(f"[BENCH]   -> {dst}  ({os.path.getsize(dst)/1e6:.1f} MB)")

        print(f"\n[BENCH] Output directory: {out_dir}")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        print_report()


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HotShort Pipeline Benchmark")
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--url",  help="YouTube URL to download and benchmark")
    grp.add_argument("--file", help="Local video file path")
    parser.add_argument("--top-k", type=int, default=3,
                        help="Number of clips to select (default: 3)")
    args = parser.parse_args()

    if not _HAS_PSUTIL:
        print("[BENCH] Installing psutil...")
        subprocess.run([sys.executable, "-m", "pip", "install", "psutil", "-q"])
        import psutil  # noqa: F811
        _HAS_PSUTIL = True

    if args.url:
        run_benchmark(args.url,  top_k=args.top_k, is_url=True)
    else:
        run_benchmark(args.file, top_k=args.top_k, is_url=False)
