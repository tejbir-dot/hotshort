import argparse
import csv
import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path
import numpy as np

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class CandidateResult:
    video_id: str
    start_s: float
    end_s: float
    legacy_score: float | None
    legacy_selected: bool
    new_score: float | None
    new_selected: bool
    transcript_excerpt: str = ""

_CTX_CACHE = {}

def run_legacy_pipeline(video_path: Path) -> list[dict]:
    from viral_finder.orchestrator import _run_staged_pipeline
    res = _run_staged_pipeline(str(video_path), top_k=8, prefer_gpu=True, use_cache=True, allow_fallback=False)
    if isinstance(res, tuple) and len(res) == 5:
        final_candidates, _groq_pool, has_tf_moments, full_transcript, ctx = res
    else:
        return []

    _CTX_CACHE[video_path.stem] = (ctx, final_candidates, full_transcript)
    selected_cids = {c.get("cid", c.get("id")) for c in final_candidates}
    
    out = []
    candidates = getattr(ctx, "enriched_candidates", getattr(ctx, "raw_candidates", []))
    for c in candidates:
        cid = c.get("cid", c.get("id"))
        out.append({
            "video_id": video_path.stem,
            "start_s": float(c.get("start", 0)),
            "end_s": float(c.get("end", 0)),
            "score": float(c.get("score", 0)),
            "selected": cid in selected_cids,
            "transcript_excerpt": c.get("text", "")[:200],
            "cid": cid
        })
    return out

def run_new_pipeline(video_path: Path) -> list[dict]:
    if video_path.stem not in _CTX_CACHE:
        return []
        
    ctx, final_candidates, transcript = _CTX_CACHE[video_path.stem]
    candidates = getattr(ctx, "enriched_candidates", getattr(ctx, "raw_candidates", []))
    
    from viral_finder.delta_math import fuse_scores, audio_delta, rolling_zscore, cosine_distance
    from viral_finder.transcript_engine import load_audio_to_memory
    
    try:
        from sentence_transformers import SentenceTransformer
        emb_model = SentenceTransformer("all-MiniLM-L6-v2")
    except ImportError:
        emb_model = None
    
    audio = load_audio_to_memory(str(video_path))
    rms_series = []
    sr = 16000
    frame_len = int(sr * 0.1) # 100ms
    if audio is not None:
        frames_n = len(audio) // frame_len
        if frames_n > 0:
            trimmed = audio[:frames_n * frame_len]
            frames = trimmed.reshape(frames_n, frame_len)
            rms_series = np.sqrt(np.mean(frames * frames, axis=1) + 1e-12).tolist()
            
    ad_array = audio_delta(rms_series)
    ad_z = rolling_zscore(ad_array, window=50) # 5 seconds
    # emb_model is already initialized above
    out = []
    for c in candidates:
        cid = c.get("cid", c.get("id"))
        start_s = float(c.get("start", 0))
        end_s = float(c.get("end", 0))
        
        start_idx = int(start_s * 10)
        end_idx = int(end_s * 10)
        window_ad = ad_z[start_idx:end_idx] if ad_z else []
        a_delta = max(window_ad) if window_ad else 0.0
        
        pre_text = " ".join([seg.get("text", "") for seg in transcript 
                             if float(seg.get("start", 0)) >= max(0, start_s - 10) 
                             and float(seg.get("end", 0)) < start_s])
        cur_text = c.get("text", "")
        
        s_delta = 0.0
        if emb_model and pre_text.strip() and cur_text.strip():
            emb_pre = emb_model.encode([pre_text])[0]
            emb_cur = emb_model.encode([cur_text])[0]
            raw_s = cosine_distance(emb_pre, emb_cur)
            s_delta = min(1.0, raw_s) # Cosine distance is ~0-1 usually, scale to 1.
            
        v_delta = 0.0
        
        # Scale Z-score (0 to 3) into [0, 1]
        a_delta_norm = max(0.0, min(1.0, a_delta / 3.0))
        
        score = fuse_scores(s_delta, a_delta_norm, v_delta)
        
        out.append({
            "video_id": video_path.stem,
            "start_s": start_s,
            "end_s": end_s,
            "score": score,
            "selected": False,
            "transcript_excerpt": cur_text[:200],
            "cid": cid
        })
        
    out.sort(key=lambda x: x["score"], reverse=True)
    top_k = min(8, len(out))
    for i in range(top_k):
        out[i]["selected"] = True
        
    out.sort(key=lambda x: x["start_s"])
    return out


# ---------------------------------------------------------------------------
# Merge + compare (do not need to modify below this line)
# ---------------------------------------------------------------------------

TOLERANCE_S = 2.0  # boundary tolerance when matching candidates across runs

def _windows_overlap(a_start, a_end, b_start, b_end, tol=TOLERANCE_S) -> bool:
    return (a_start - tol) <= b_end and (b_start - tol) <= a_end

def merge_results(legacy: list[dict], new: list[dict], video_id: str) -> list[CandidateResult]:
    merged: list[CandidateResult] = []
    matched_new_indices = set()

    for lc in legacy:
        match = None
        for i, nc in enumerate(new):
            if i in matched_new_indices:
                continue
            if _windows_overlap(lc["start_s"], lc["end_s"], nc["start_s"], nc["end_s"]):
                match = (i, nc)
                break
        if match:
            i, nc = match
            matched_new_indices.add(i)
            merged.append(CandidateResult(
                video_id=video_id,
                start_s=lc["start_s"], end_s=lc["end_s"],
                legacy_score=lc["score"], legacy_selected=lc["selected"],
                new_score=nc["score"], new_selected=nc["selected"],
                transcript_excerpt=lc.get("transcript_excerpt", ""),
            ))
        else:
            merged.append(CandidateResult(
                video_id=video_id,
                start_s=lc["start_s"], end_s=lc["end_s"],
                legacy_score=lc["score"], legacy_selected=lc["selected"],
                new_score=None, new_selected=False,
                transcript_excerpt=lc.get("transcript_excerpt", ""),
            ))

    for i, nc in enumerate(new):
        if i not in matched_new_indices:
            merged.append(CandidateResult(
                video_id=video_id,
                start_s=nc["start_s"], end_s=nc["end_s"],
                legacy_score=None, legacy_selected=False,
                new_score=nc["score"], new_selected=nc["selected"],
                transcript_excerpt=nc.get("transcript_excerpt", ""),
            ))

    return merged

def compute_metrics(all_results: list[CandidateResult]) -> dict:
    total = len(all_results)
    both_selected = sum(1 for r in all_results if r.legacy_selected and r.new_selected)
    legacy_only = [r for r in all_results if r.legacy_selected and not r.new_selected]
    new_only = [r for r in all_results if r.new_selected and not r.legacy_selected]
    legacy_selected_count = sum(1 for r in all_results if r.legacy_selected)
    new_selected_count = sum(1 for r in all_results if r.new_selected)

    agreement_rate = (
        both_selected / max(legacy_selected_count, new_selected_count, 1)
    )

    legacy_scores = [r.legacy_score for r in all_results if r.legacy_score is not None]
    new_scores = [r.new_score for r in all_results if r.new_score is not None]

    def _stats(scores):
        if not scores:
            return {"min": None, "max": None, "mean": None}
        return {
            "min": round(min(scores), 4),
            "max": round(max(scores), 4),
            "mean": round(sum(scores) / len(scores), 4),
        }

    return {
        "total_candidate_windows": total,
        "legacy_selected_count": legacy_selected_count,
        "new_selected_count": new_selected_count,
        "both_selected_count": both_selected,
        "agreement_rate": round(agreement_rate, 4),
        "legacy_only_count": len(legacy_only),
        "new_only_count": len(new_only),
        "legacy_score_stats": _stats(legacy_scores),
        "new_score_stats": _stats(new_scores),
        "legacy_only_examples": [asdict(r) for r in legacy_only[:5]],
        "new_only_examples": [asdict(r) for r in new_only[:5]],
    }

def write_csv(all_results: list[CandidateResult], out_path: Path):
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(all_results[0]).keys()) if all_results else [])
        writer.writeheader()
        for r in all_results:
            writer.writerow(asdict(r))

def write_report(metrics: dict, timing: dict, out_path: Path):
    lines = []
    lines.append("# A/B Comparison Report: Legacy vs. Delta/Contrast Engine\n")
    lines.append(f"Generated from {metrics['total_candidate_windows']} candidate windows.\n")

    lines.append("## Headline numbers\n")
    lines.append(f"- Legacy selected: **{metrics['legacy_selected_count']}** clips")
    lines.append(f"- New engine selected: **{metrics['new_selected_count']}** clips")
    lines.append(f"- Both agreed on: **{metrics['both_selected_count']}** clips")
    lines.append(f"- Agreement rate: **{metrics['agreement_rate'] * 100:.1f}%**")
    lines.append(f"- Legacy-only (potential regressions): **{metrics['legacy_only_count']}**")
    lines.append(f"- New-only (potential new catches): **{metrics['new_only_count']}**\n")

    lines.append("## Score distributions\n")
    lines.append(f"- Legacy: {metrics['legacy_score_stats']}")
    lines.append(f"- New: {metrics['new_score_stats']}\n")

    lines.append("## Timing\n")
    for k, v in timing.items():
        lines.append(f"- {k}: {v:.2f}s")
    lines.append("")

    lines.append("## ⚠️ Legacy-only clips (new engine dropped these -- check first)\n")
    if not metrics["legacy_only_examples"]:
        lines.append("None -- no regressions detected in this sample.\n")
    for ex in metrics["legacy_only_examples"]:
        lines.append(f"- `{ex['video_id']}` [{ex['start_s']:.1f}s-{ex['end_s']:.1f}s] "
                      f"legacy_score={ex['legacy_score']:.3f} -- "
                      f"\"{ex['transcript_excerpt']}\"")
    lines.append("")

    lines.append("## ✅ New-only clips (potential wins)\n")
    if not metrics["new_only_examples"]:
        lines.append("None found in this sample.\n")
    for ex in metrics["new_only_examples"]:
        lines.append(f"- `{ex['video_id']}` [{ex['start_s']:.1f}s-{ex['end_s']:.1f}s] "
                      f"new_score={ex['new_score']:.3f} -- "
                      f"\"{ex['transcript_excerpt']}\"")
    lines.append("")

    lines.append("## Manual review required\n")
    lines.append(
        "This report shows what changed mechanically. It does NOT tell you which "
        "system actually picked better clips -- a human needs to watch the "
        "legacy-only and new-only clips above and judge them. Per the test plan, "
        "do not ship the new engine unless new-only wins outnumber legacy-only "
        "regressions on manual review.\n"
    )

    out_path.write_text("\n".join(lines), encoding="utf-8")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--videos", type=Path, required=True,
                         help="Directory of locked test videos (e.g. test_downloads/)")
    parser.add_argument("--out", type=Path, default=Path("ab_report_output"))
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)

    video_files = sorted(args.videos.glob("*.mp4")) + sorted(args.videos.glob("*.mov"))
    if not video_files:
        raise SystemExit(f"No video files found in {args.videos}")

    print(f"Locked test set: {[v.name for v in video_files]}")
    (args.out / "locked_video_set.json").write_text(
        json.dumps([v.name for v in video_files], indent=2), encoding="utf-8"
    )

    all_results: list[CandidateResult] = []
    timing = {}

    t0 = time.time()
    legacy_runs = {}
    for v in video_files:
        legacy_runs[v.stem] = run_legacy_pipeline(v)
    timing["legacy_total_time"] = time.time() - t0

    t0 = time.time()
    new_runs = {}
    for v in video_files:
        new_runs[v.stem] = run_new_pipeline(v)
    timing["new_total_time"] = time.time() - t0

    for v in video_files:
        merged = merge_results(legacy_runs[v.stem], new_runs[v.stem], v.stem)
        all_results.extend(merged)

    write_csv(all_results, args.out / "comparison.csv")
    metrics = compute_metrics(all_results)
    write_report(metrics, timing, args.out / "report.md")
    (args.out / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    print(f"\nDone. See {args.out}/report.md for the comparison and proof artifacts.")

if __name__ == "__main__":
    main()
