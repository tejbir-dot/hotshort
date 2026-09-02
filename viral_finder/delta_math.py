import math
import numpy as np

def cosine_distance(emb_a: np.ndarray, emb_b: np.ndarray) -> float:
    a = np.asarray(emb_a, dtype=float)
    b = np.asarray(emb_b, dtype=float)
    
    if a.size == 0 or b.size == 0:
        return 0.0
        
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    
    if norm_a < 1e-12 or norm_b < 1e-12:
        return 0.0
        
    dot = np.dot(a, b)
    cos_sim = dot / (norm_a * norm_b)
    cos_sim = max(-1.0, min(1.0, cos_sim))
    return float(1.0 - cos_sim)

def rolling_zscore(values: list[float], window: int) -> list[float]:
    out = []
    n = len(values)
    for i in range(n):
        w_bg = values[max(0, i - window): i]
        if len(w_bg) < 2:
            w_bg = values[max(0, i - window): i + 1]
            if len(w_bg) < 2:
                out.append(0.0)
                continue
                
        mean = sum(w_bg) / len(w_bg)
        variance = sum((x - mean)**2 for x in w_bg) / len(w_bg)
        std = math.sqrt(variance)
        
        if std < 1e-12:
            if abs(values[i] - mean) > 1e-12:
                out.append(10.0 if values[i] > mean else -10.0)
            else:
                out.append(0.0)
        else:
            out.append(float((values[i] - mean) / std))
    return out

def audio_delta(rms_series: list[float]) -> list[float]:
    out = []
    for i in range(len(rms_series)):
        if i == 0:
            out.append(0.0)
        else:
            out.append(float(rms_series[i] - rms_series[i-1]))
    return out

def fuse_scores(semantic_delta: float, audio_delta: float, visual_delta: float,
                mode: str = "geometric_mean", epsilon: float = 1e-3) -> float:
    s = max(0.0, min(1.0, semantic_delta))
    a = max(0.0, min(1.0, audio_delta))
    v = max(0.0, min(1.0, visual_delta))
    
    _max = max(s, a, v)
    _prod = s * a * v
    
    score = _max + 0.5 * _prod
    return float(max(0.0, min(1.0, score)))
