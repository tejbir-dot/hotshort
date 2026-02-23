# viral_finder/ignition.py
import math
import numpy as np
import re
from typing import List, Dict, Tuple, Optional

_WORDS_RE = re.compile(r"\w+", flags=re.UNICODE)

def tokens(s: str):
    return _WORDS_RE.findall((s or "").lower())

def default_arousal_lexicon() -> Dict[str, float]:
    # small default; extend with VAD/NRC maps or external lexicons
    lex = {
        "secret": 0.95, "exposed": 0.9, "lie": 0.9, "lied": 0.9,
        "money": 0.9, "million": 0.9, "billion": 0.95, "death": 0.95,
        "mistake": 0.85, "shocking": 0.9, "truth": 0.9, "scared": 0.85,
        "danger": 0.9, "forbidden": 0.95, "surprising": 0.8,
        "why": 0.65, "how": 0.65, "why does": 0.7, "what if": 0.7,
        "best": 0.5, "worst": 0.6, "only": 0.6, "never": 0.6,
        "stop": 0.7, "don't": 0.6, "don't do": 0.7, "don't miss": 0.75,
        "warning": 0.85, "wake up": 0.8, "remember": 0.65, "listen": 0.6,
        # filler low scores
        "the": 0.01, "is": 0.01, "and": 0.01, "so": 0.02
    }
    return lex

def semantic_heat_for_text(text: str, lexicon: Dict[str, float], cap_per_word: float = 1.0) -> float:
    if not text:
        return 0.0
    ws = tokens(text)
    if not ws:
        return 0.0
    score = 0.0
    for w in ws:
        score += float(lexicon.get(w, 0.0))
    # normalize by sqrt of word count to keep density meaningful
    return float(score / max(1.0, math.sqrt(len(ws))))

def map_time_to_segments(transcript: List[Dict]) -> Tuple[float, float]:
    # return start_time, end_time of transcript
    if not transcript:
        return 0.0, 0.0
    start = min(float(s.get("start", 0.0)) for s in transcript)
    end = max(float(s.get("end", s.get("start", 0.0))) for s in transcript)
    return start, end

def compute_semantic_spectrogram(
    transcript: List[Dict],
    feats: Optional[List[Dict]] = None,
    lexicon: Optional[Dict[str, float]] = None,
    window_sec: float = 1.5,
    step_sec: float = 0.25
) -> Dict[str, np.ndarray]:
    """
    Build a time-series spectrogram-like structure:
      times, semantic_heat, audio_energy (if feats), motion (if feats)
    transcript: list of {start,end,text}
    feats: list of {start,end,audio_energy,motion} aligned to transcript segments OR None
    """
    if lexicon is None:
        lexicon = default_arousal_lexicon()

    t0, t1 = map_time_to_segments(transcript)
    if t1 <= t0:
        return {"times": np.array([]), "semantic": np.array([]), "audio": np.array([]), "motion": np.array([])}

    times = np.arange(t0, t1 + 1e-6, step_sec)
    sem = np.zeros_like(times, dtype=float)
    audio = np.zeros_like(times, dtype=float)
    motion = np.zeros_like(times, dtype=float)

    # precompute segment textual heats and segment-level audio/motion
    seg_heats = []
    seg_audio = []
    seg_motion = []
    for seg in transcript:
        seg_heats.append(semantic_heat_for_text(seg.get("text", ""), lexicon))
        seg_audio.append(float((seg.get("audio_energy") if seg.get("audio_energy") is not None else (feats and feats and feats[0].get("audio_energy", 0.0)) if feats else 0.0)))
        seg_motion.append(float((seg.get("motion") if seg.get("motion") is not None else (feats and feats and feats[0].get("motion", 0.0)) if feats else 0.0)))

    # helper: find segments overlapping a time window center
    for i, t in enumerate(times):
        w0 = t - (window_sec / 2.0)
        w1 = t + (window_sec / 2.0)
        accum_sem = 0.0
        accum_audio = 0.0
        accum_motion = 0.0
        weight_sum = 0.0
        for j, seg in enumerate(transcript):
            s0 = float(seg.get("start", 0.0))
            s1 = float(seg.get("end", s0))
            # compute overlap fraction
            overlap = max(0.0, min(s1, w1) - max(s0, w0))
            if overlap <= 0.0:
                continue
            frac = overlap / (w1 - w0)
            accum_sem += seg_heats[j] * frac
            accum_audio += seg_audio[j] * frac
            accum_motion += seg_motion[j] * frac
            weight_sum += frac
        if weight_sum > 0.0:
            sem[i] = accum_sem / weight_sum
            audio[i] = accum_audio / weight_sum
            motion[i] = accum_motion / weight_sum
        else:
            sem[i] = 0.0
            audio[i] = 0.0
            motion[i] = 0.0

    return {"times": times, "semantic": sem, "audio": audio, "motion": motion}

def short_delta(arr: np.ndarray, lookback_sec: float, step_sec: float) -> np.ndarray:
    # compute difference between current and mean over lookback window (in seconds)
    lookback = max(1, int(round(lookback_sec / step_sec)))
    res = np.zeros_like(arr)
    for i in range(len(arr)):
        start = max(0, i - lookback)
        if i - start <= 0:
            res[i] = 0.0
        else:
            res[i] = arr[i] - np.mean(arr[start:i])
    return res

def compute_ignition_score(
    spect: Dict[str, np.ndarray],
    step_sec: float = 0.25,
    audio_weight: float = 0.2,
    motion_weight: float = 0.15,
    semantic_weight: float = 0.5,
    semantic_lookback: float = 2.0,
    audio_lookback: float = 2.0,
    motion_lookback: float = 2.0
) -> Dict[str, np.ndarray]:
    times = spect["times"]
    sem = spect["semantic"]
    audio = spect["audio"]
    motion = spect["motion"]

    # normalize each channel to [0,1] robustly
    def norm(x):
        if x.size == 0:
            return x
        mi, ma = np.nanmin(x), np.nanmax(x)
        if ma - mi < 1e-6:
            return np.zeros_like(x)
        return (x - mi) / (ma - mi)

    nsem = norm(sem)
    naud = norm(audio)
    nmot = norm(motion)

    # compute short deltas (how big change relative to recent past)
    dsem = short_delta(nsem, semantic_lookback, step_sec)
    daud = short_delta(naud, audio_lookback, step_sec)
    dmot = short_delta(nmot, motion_lookback, step_sec)

    # ignition base score: semantic signal magnitude + deltas
    # Semantic magnitude itself matters (people stop for content), and its slope (prediction error) matters.
    ignition_base = semantic_weight * (nsem + dsem) + audio_weight * (naud + daud) + motion_weight * (nmot + dmot)

    # rectify and normalize ignition_base
    ignition_base = np.maximum(0.0, ignition_base)
    if ignition_base.size:
        ignition_norm = (ignition_base - ignition_base.min()) / max(1e-9, (ignition_base.max() - ignition_base.min()))
    else:
        ignition_norm = ignition_base

    return {
        "times": times,
        "semantic": nsem,
        "audio": naud,
        "motion": nmot,
        "dsemantic": dsem,
        "daudio": daud,
        "dmotion": dmot,
        "ignition": ignition_norm
    }

def detect_ignitions(
    ignition_ts: Dict[str, np.ndarray],
    top_k: int = 6,
    slope_window: int = 3,
    slope_thresh: float = 0.25,
    pre_offset: float = 0.5,
    min_score: float = 0.25
) -> List[Dict]:
    """
    Returns list of dicts: {time, score, slope, pre_time}
    - slope: measured rise across slope_window frames (fraction)
    - pre_time: time to start clip (time - pre_offset)
    """
    times = ignition_ts["times"]
    ign = ignition_ts["ignition"]
    results = []
    if len(times) == 0:
        return results

    # compute slope (difference over slope_window)
    sl = np.zeros_like(ign)
    L = len(ign)
    for i in range(L):
        j0 = max(0, i - slope_window)
        j1 = i
        if j1 - j0 <= 0:
            sl[i] = 0.0
        else:
            sl[i] = (ign[i] - np.mean(ign[j0:j1]))  # raw rise
    # candidate indices where ignition and slope high
    cand_idx = [i for i in range(len(times)) if ign[i] >= min_score and sl[i] >= slope_thresh]
    # score candidates by a mixture of ign value and slope
    scored = []
    for i in cand_idx:
        score = 0.6 * float(ign[i]) + 0.4 * float(sl[i])
        scored.append((score, i, float(sl[i])))

    scored.sort(reverse=True, key=lambda x: x[0])
    picked = []
    used_time = set()
    for score, idx, slope_val in scored:
        if len(picked) >= top_k:
            break
        t = float(times[idx])
        # avoid picking points too close
        if any(abs(t - ut) < 1.0 for ut in used_time):
            continue
        start = max(0.0, t - float(pre_offset))
        picked.append({"time": round(t, 3), "score": round(float(score), 3), "slope": round(float(slope_val), 4), "pre_time": round(start, 3)})
        used_time.add(t)

    return picked

# Integration helper: single-call pipeline
def find_ignitions_from_transcript(
    transcript: List[Dict],
    feats: Optional[List[Dict]] = None,
    lexicon: Optional[Dict[str, float]] = None,
    window_sec: float = 1.5,
    step_sec: float = 0.25,
    top_k: int = 6
) -> Dict:
    spect = compute_semantic_spectrogram(transcript, feats=feats, lexicon=lexicon, window_sec=window_sec, step_sec=step_sec)
    ignition_ts = compute_ignition_score(spect, step_sec=step_sec)
    ignitions = detect_ignitions(ignition_ts, top_k=top_k)
    return {"spectrogram": spect, "ignition_ts": ignition_ts, "ignitions": ignitions}
