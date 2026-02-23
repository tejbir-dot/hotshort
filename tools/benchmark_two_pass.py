#!/usr/bin/env python
"""
Benchmark baseline vs two-pass transcription on one media file.

Usage:
  python tools/benchmark_two_pass.py --file path/to/video.mp4 --model small
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import time
from typing import Dict, List, Optional


def _words(text: str) -> List[str]:
    return re.findall(r"[a-zA-Z0-9']+", (text or "").lower())


def _first_word_start(segments: List[Dict]) -> Optional[float]:
    for s in sorted(segments or [], key=lambda x: float(x.get("start", 0.0) or 0.0)):
        if (s.get("text") or "").strip():
            return float(s.get("start", 0.0) or 0.0)
    return None


def _metrics(segments: List[Dict]) -> Dict:
    txt = " ".join((s.get("text", "") or "").strip() for s in (segments or []) if (s.get("text") or "").strip())
    toks = _words(txt)
    return {
        "segments": int(len(segments or [])),
        "words": int(len(toks)),
        "first_word_start_s": _first_word_start(segments),
        "text_sha1": hashlib.sha1(txt.encode("utf-8")).hexdigest()[:16] if txt else "",
    }


def _set_mode(gte, *, baseline: bool, two_pass_compare: bool) -> None:
    # Keep env + module globals aligned for deterministic behavior.
    os.environ["HS_FORCE_BASELINE"] = "1" if baseline else "0"
    os.environ["HS_TWO_PASS"] = "0" if baseline else "1"
    os.environ["HS_VAD_PREGATE"] = "0" if baseline else "1"
    os.environ["HS_TWO_PASS_BASELINE_COMPARE"] = "0" if baseline else ("1" if two_pass_compare else "0")

    gte.HS_FORCE_BASELINE = baseline
    gte.HS_TWO_PASS = (not baseline)
    gte.VAD_PREGATE = (not baseline)
    gte.HS_TWO_PASS_BASELINE_COMPARE = (not baseline and two_pass_compare)


def _run_once(gte, path: str, model: str, prefer_gpu: bool, baseline: bool, two_pass_compare: bool) -> Dict:
    _set_mode(gte, baseline=baseline, two_pass_compare=two_pass_compare)
    label = "baseline" if baseline else "optimized"
    t0 = time.perf_counter()
    segs = gte.extract_transcript(
        path,
        model_name=model,
        prefer_gpu=prefer_gpu,
        force_recompute=True,
        prefer_trust=False,
    )
    dt = time.perf_counter() - t0
    m = _metrics(segs)
    m["mode"] = label
    m["seconds"] = round(dt, 3)
    return m


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--file", required=True, help="Local media path (video/audio).")
    p.add_argument("--model", default=os.environ.get("HS_TRANSCRIPT_MODEL", "small"))
    p.add_argument("--cpu", action="store_true", help="Force CPU.")
    p.add_argument("--skip-warmup", action="store_true", help="Skip model warmup.")
    p.add_argument(
        "--two-pass-compare",
        action="store_true",
        help="Enable baseline-compare rollback inside optimized run.",
    )
    args = p.parse_args()

    path = os.path.abspath(args.file)
    if not os.path.exists(path):
        raise FileNotFoundError(path)

    from viral_finder import gemini_transcript_engine as gte

    prefer_gpu = not args.cpu
    if not args.skip_warmup:
        gte.warmup(model_name=args.model, prefer_gpu=prefer_gpu)

    base = _run_once(
        gte,
        path=path,
        model=args.model,
        prefer_gpu=prefer_gpu,
        baseline=True,
        two_pass_compare=args.two_pass_compare,
    )
    opt = _run_once(
        gte,
        path=path,
        model=args.model,
        prefer_gpu=prefer_gpu,
        baseline=False,
        two_pass_compare=args.two_pass_compare,
    )

    base_t = float(base["seconds"] or 0.0)
    opt_t = float(opt["seconds"] or 0.0)
    speedup_x = (base_t / opt_t) if opt_t > 0 else 0.0
    speedup_pct = ((base_t - opt_t) / base_t * 100.0) if base_t > 0 else 0.0

    base_n = int(base["segments"] or 0)
    opt_n = int(opt["segments"] or 0)
    seg_delta_pct = (abs(opt_n - base_n) / max(1, base_n)) * 100.0

    b0 = base.get("first_word_start_s")
    o0 = opt.get("first_word_start_s")
    shift_ms = abs(float(o0) - float(b0)) * 1000.0 if (b0 is not None and o0 is not None) else None

    print("\n=== Transcription Benchmark ===")
    print(f"file: {path}")
    print(f"model: {args.model}  device: {'cpu' if args.cpu else 'auto/gpu'}")
    print("")
    print(f"baseline:  {base_t:.2f}s  segs={base_n}  words={base['words']}  first={base.get('first_word_start_s')}")
    print(f"optimized: {opt_t:.2f}s  segs={opt_n}  words={opt['words']}  first={opt.get('first_word_start_s')}")
    print("")
    print(f"speedup: {speedup_x:.2f}x  ({speedup_pct:.1f}% faster)")
    print(f"segment delta: {seg_delta_pct:.2f}%")
    print(f"first-word shift: {('%.1fms' % shift_ms) if shift_ms is not None else 'n/a'}")
    print(f"text hash (base/opt): {base['text_sha1']} / {opt['text_sha1']}")

    quality_ok = (seg_delta_pct <= 5.0) and (shift_ms is None or shift_ms <= 150.0)
    print(f"quality_guard_pass: {quality_ok}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

