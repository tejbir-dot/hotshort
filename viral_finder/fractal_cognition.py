import math
import logging
import copy
from typing import List, Dict, Any, Tuple
import os

log = logging.getLogger(__name__)

# Core Geometric Constants
PHI = 1.618033988749895
INV_PHI = 0.618033988749895 # phi - 1
PHI_CONJUGATE = 0.381966011250105 # 1 - inv_phi

# Lazy-loaded Tensor Engine
_encoder_model = None

def _get_encoder():
    global _encoder_model
    if _encoder_model is None:
        try:
            from sentence_transformers import SentenceTransformer
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
            log.info(f"[FRACTAL_TENSOR] Booting Deep Attention Engine on {device.upper()}...")
            _encoder_model = SentenceTransformer('all-MiniLM-L6-v2', device=device)
        except ImportError:
            raise ImportError(
                "God Mode Tensor Engine missing! "
                "Please run: pip install torch sentence-transformers"
            )
    return _encoder_model

def _cosine_similarity(v1, v2) -> float:
    import torch
    import torch.nn.functional as F
    if v1.dim() == 1: v1 = v1.unsqueeze(0)
    if v2.dim() == 1: v2 = v2.unsqueeze(0)
    sim = F.cosine_similarity(v1, v2)
    return float(sim.item())

def _merge_vectors(v1, v2, decay: float = 1.0):
    return v1 + (v2 * decay)

class CognitiveMatrix:
    def __init__(self, transcript: List[Dict]):
        self.nodes = transcript
        if not transcript:
            self.vectors = []
            return
        texts = [seg.get("text", "").strip() for seg in transcript]
        encoder = _get_encoder()
        log.info(f"[FRACTAL_TENSOR] Vectorizing {len(texts)} semantic nodes into 384-D Hyper-space...")
        self.vectors = encoder.encode(texts, convert_to_tensor=True)

def recursive_fractal_search(start_idx: int, matrix: CognitiveMatrix, max_lookahead: int = 20) -> int:
    if start_idx >= len(matrix.nodes):
        return start_idx

    root_vector = matrix.vectors[start_idx].clone()
    current_idx = start_idx + 1
    end_idx = current_idx
    
    context_vector = root_vector.clone()
    hook_text = matrix.nodes[start_idx].get("text", "").strip()
    print(f"\n[FRACTAL_TREE] --------------------------------------------------")
    print(f"[FRACTAL_TREE] ROOT NODE (HOOK) IDENTIFIED:")
    print(f"[FRACTAL_TREE] -> '{hook_text}'")
    print(f"[FRACTAL_TREE] --------------------------------------------------")
    print(f"[FRACTAL_TREE] BRANCHING FORWARD (Checking next {max_lookahead} nodes):")
    
    while current_idx < len(matrix.nodes) and current_idx - start_idx <= max_lookahead:
        next_vector = matrix.vectors[current_idx]
        next_text = matrix.nodes[current_idx].get("text", "").strip()
        
        resonance = _cosine_similarity(context_vector, next_vector)
        threshold = (INV_PHI * 0.65)
        
        if resonance >= threshold: 
            print(f"[FRACTAL_TREE] [MATCH] Cosine={resonance:.4f} >= {threshold:.4f} | Merging context: '{next_text}'")
            context_vector = _merge_vectors(context_vector, next_vector, decay=INV_PHI)
            end_idx = current_idx
        else:
            print(f"[FRACTAL_TREE] [PRUNE] Cosine={resonance:.4f} < {threshold:.4f}  | TOPIC DRIFT DETECTED!")
            print(f"[FRACTAL_TREE] [PRUNE] Rejected branch: '{next_text}'")
            print(f"[FRACTAL_TREE] --------------------------------------------------")
            break
            
        current_idx += 1
        
    return end_idx

def calculate_fibonacci_resonance(start: float, end: float, transcript: List[Dict]) -> float:
    duration = end - start
    if duration <= 0: return 0.0
    ideal_nodes = [
        1.0 - math.pow(PHI, -1),
        1.0 - math.pow(PHI, -2),
        1.0 - math.pow(PHI, -3)
    ]
    actual_nodes = []
    for seg in transcript:
        s_s = float(seg.get("start", 0))
        s_e = float(seg.get("end", s_s))
        if s_s > start and s_e < end:
            pct = (s_e - start) / duration
            actual_nodes.append(pct)
    if not actual_nodes: return 0.0
    error = 0.0
    for ideal in ideal_nodes:
        closest = min(actual_nodes, key=lambda x: abs(x - ideal))
        error += abs(closest - ideal)
    resonance = max(0.0, 1.0 - (error / len(ideal_nodes)))
    return resonance

def optimize_boundaries(candidates: List[Dict], transcript: List[Dict]) -> List[Dict]:
    if not candidates or not transcript:
        return candidates

    log.info("[FRACTAL_TENSOR] Initializing Deep Cognitive Matrix...")
    matrix = CognitiveMatrix(transcript)
    
    optimized = []
    for c_idx, c in enumerate(candidates):
        orig_start = float(c.get("start", 0))
        orig_end = float(c.get("end", 0))
        
        start_node_idx = 0
        for i, seg in enumerate(transcript):
            if float(seg.get("start", 0)) >= orig_start - 1.0:
                start_node_idx = i
                break
                
        optimal_end_idx = recursive_fractal_search(start_node_idx, matrix, max_lookahead=25)
        
        if optimal_end_idx < len(transcript):
            semantic_end = float(transcript[optimal_end_idx].get("end", orig_end))
        else:
            semantic_end = orig_end
            
        c_refined = copy.deepcopy(c)
        
        best_end = semantic_end
        best_resonance = calculate_fibonacci_resonance(orig_start, best_end, transcript)
        
        nudge_step = PHI_CONJUGATE
        current_end = semantic_end - (nudge_step * 3) 
        
        iterations = 0
        print(f"\n[FIBONACCI_PACING] Optimizing Climax for Candidate {c_idx}")
        print(f"[FIBONACCI_PACING] Starting Resonance: {best_resonance:.6f} at duration {best_end - orig_start:.2f}s")
        
        while iterations < 7: 
            res = calculate_fibonacci_resonance(orig_start, current_end, transcript)
            print(f"[FIBONACCI_PACING] Try T={current_end:.6f}s -> Resonance={res:.6f}")
            if res > best_resonance and (current_end - orig_start) > 3.0:
                best_resonance = res
                best_end = current_end
                
            current_end += nudge_step
            iterations += 1
            
        c_refined["end"] = best_end
        c_refined["duration"] = best_end - orig_start
        c_refined["fractal_resonance"] = best_resonance
        
        print(f"[FIBONACCI_PACING] WINNER: Locked at T={best_end:.6f}s (Score: {best_resonance:.6f})\n")
        optimized.append(c_refined)
        
    return optimized

