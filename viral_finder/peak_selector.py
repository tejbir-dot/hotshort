import logging
from typing import List, Dict, Any, Callable

log = logging.getLogger(__name__)

class PeakSelector:
    """
    A generic selection engine designed to prevent chronological shadowing
    ('First-In-Wins' anti-pattern).
    
    It enforces an Observe -> Collect -> Compare -> Commit pipeline.
    """
    
    def __init__(self):
        self.candidates: List[Dict[str, Any]] = []
        
    def collect_candidate(self, candidate: Dict[str, Any]) -> None:
        """Observe and collect a candidate without committing."""
        self.candidates.append(candidate)
        
    def cluster_candidates(self, cluster_fn: Callable[[Dict[str, Any], Any], bool], create_state_fn: Callable[[Dict[str, Any]], Any]) -> List[Dict[str, Any]]:
        """
        Groups candidates into clusters based on narrative, visual, or chronological continuity.
        cluster_fn: (candidate, state) -> bool (returns True if candidate belongs to the cluster state)
        create_state_fn: (candidate) -> state (initializes the state for a new cluster)
        
        Returns a list of clusters: [{'state': Any, 'candidates': [...]}]
        """
        clusters: List[Dict[str, Any]] = []
        for cand in self.candidates:
            placed = False
            for cluster in clusters:
                if cluster_fn(cand, cluster["state"]):
                    cluster["candidates"].append(cand)
                    placed = True
                    break
            
            if not placed:
                state = create_state_fn(cand)
                clusters.append({"state": state, "candidates": [cand]})
                
        return clusters

    def select_peak(self, clusters: List[Dict[str, Any]], score_fn: Callable[[Dict[str, Any]], float]) -> List[Dict[str, Any]]:
        """
        Compares candidates inside each cluster using score_fn and returns a list of results.
        Returns: [{'state': Any, 'winner': Dict, 'losers': List[Dict]}]
        """
        results = []
        for cluster in clusters:
            cands = cluster["candidates"]
            if not cands:
                continue
                
            # Compare inside cluster
            sorted_cands = sorted(cands, key=score_fn, reverse=True)
            winner = sorted_cands[0]
            losers = sorted_cands[1:]
            
            results.append({
                "state": cluster["state"],
                "winner": winner,
                "losers": losers
            })
            
        return results

    def publish(
        self, 
        results: List[Dict[str, Any]], 
        publish_fn: Callable[[Dict[str, Any], List[Dict[str, Any]], Any], Any]
    ) -> List[Any]:
        """
        Only NOW commit the winners.
        publish_fn: (winner, losers, state) -> Any (returns the final published entity, or None to skip)
        """
        published = []
        for res in results:
            pub = publish_fn(res["winner"], res["losers"], res["state"])
            if pub is not None:
                published.append(pub)
        return published

    def execute(
        self,
        cluster_fn: Callable[[Dict[str, Any], Any], bool],
        create_state_fn: Callable[[Dict[str, Any]], Any],
        score_fn: Callable[[Dict[str, Any]], float],
        publish_fn: Callable[[Dict[str, Any], List[Dict[str, Any]], Any], Any]
    ) -> List[Any]:
        """Convenience method for running the full pipeline on collected candidates."""
        clusters = self.cluster_candidates(cluster_fn, create_state_fn)
        results = self.select_peak(clusters, score_fn)
        return self.publish(results, publish_fn)
