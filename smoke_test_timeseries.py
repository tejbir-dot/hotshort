import numpy as np
import csv
from pathlib import Path
from viral_finder.delta_math import audio_delta, rolling_zscore, cosine_distance
from viral_finder.transcript_engine import load_audio_to_memory

def run_smoke_test(video_path: Path):
    print(f"Running smoke test on {video_path.name}...")
    
    # 1. Load Audio and compute RMS (100ms frames)
    audio = load_audio_to_memory(str(video_path))
    if audio is None:
        print("Failed to load audio.")
        return
        
    sr = 16000
    frame_len = int(sr * 0.1) # 100ms
    frames_n = len(audio) // frame_len
    trimmed = audio[:frames_n * frame_len]
    frames = trimmed.reshape(frames_n, frame_len)
    rms_series = np.sqrt(np.mean(frames * frames, axis=1) + 1e-12).tolist()
    
    # 2. Compute audio delta and z-score
    ad_array = audio_delta(rms_series)
    ad_z = rolling_zscore(ad_array, window=50) # 5 second background window
    
    # 3. Compute semantic delta roughly every 1 second (10 frames)
    # We will simulate the rolling context
    try:
        from sentence_transformers import SentenceTransformer
        emb_model = SentenceTransformer("all-MiniLM-L6-v2")
    except ImportError:
        emb_model = None
        
    from viral_finder.orchestrator import _run_staged_pipeline
    res = _run_staged_pipeline(str(video_path), top_k=8, prefer_gpu=True, use_cache=True, allow_fallback=False)
    if isinstance(res, tuple) and len(res) == 5:
        _, _, _, transcript, _ = res
    else:
        transcript = []
        
    timeseries = []
    
    # Evaluate every 1 second
    for sec in range(1, int(frames_n / 10)):
        time_s = float(sec)
        
        # Audio feature for this 1s window (max z-score)
        start_idx = int(time_s * 10)
        end_idx = start_idx + 10
        window_ad = ad_z[start_idx:end_idx] if ad_z else []
        a_delta = max(window_ad) if window_ad else 0.0
        a_delta_norm = max(0.0, min(1.0, a_delta / 3.0))
        
        # Semantic feature: current 1s vs previous 10s
        pre_text = " ".join([seg.get("text", "") for seg in transcript 
                             if float(seg.get("start", 0)) >= max(0, time_s - 10) 
                             and float(seg.get("end", 0)) < time_s])
        cur_text = " ".join([seg.get("text", "") for seg in transcript 
                             if float(seg.get("start", 0)) >= time_s
                             and float(seg.get("end", 0)) < time_s + 1])
                             
        s_delta_raw = 0.0
        if emb_model and pre_text.strip() and cur_text.strip():
            emb_pre = emb_model.encode([pre_text])[0]
            emb_cur = emb_model.encode([cur_text])[0]
            s_delta_raw = cosine_distance(emb_pre, emb_cur)
            
        s_delta_norm = min(1.0, s_delta_raw)
        
        timeseries.append({
            "time_s": time_s,
            "rms_avg": round(sum(rms_series[start_idx:end_idx])/10, 4),
            "a_delta_zscore": round(a_delta, 4),
            "a_delta_norm": round(a_delta_norm, 4),
            "s_delta_raw": round(s_delta_raw, 4),
            "s_delta_norm": round(s_delta_norm, 4)
        })
        
    out_csv = Path("smoke_test_timeseries.csv")
    with open(out_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=timeseries[0].keys())
        writer.writeheader()
        writer.writerows(timeseries)
        
    print(f"Done. Wrote timeseries to {out_csv.name}")
    
    # Print a quick ASCII graph of the normalized signals
    print("\n--- Audio Delta Norm (scaled by 3 z-scores) ---")
    for t in timeseries:
        bars = int(t["a_delta_norm"] * 40)
        print(f"{t['time_s']:04.1f}s | {'#' * bars}")
        
    print("\n--- Semantic Delta Norm ---")
    for t in timeseries:
        bars = int(t["s_delta_norm"] * 40)
        print(f"{t['time_s']:04.1f}s | {'#' * bars}")

if __name__ == "__main__":
    run_smoke_test(Path("test_downloads/test123.mp4"))
