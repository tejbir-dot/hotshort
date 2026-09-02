import os
import json
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime
import uuid

log = logging.getLogger("candidate_lineage")

class CandidateJourney:
    def __init__(self, cid: str, initial_state: Dict[str, Any], created_by: str):
        self.cid = cid
        self.history = []
        self.field_owner = {}
        
        # Initial registration
        self.current_state = {}
        self._record_change(created_by, "CREATED", {}, initial_state, "initial_generation")
    
    def _record_change(self, stage: str, action: str, before: Dict[str, Any], after: Dict[str, Any], reason: Optional[str] = None):
        mutations = {}
        ownership_transfers = []
        
        for key, new_val in after.items():
            old_val = before.get(key)
            if old_val != new_val:
                mutations[key] = {
                    "old": old_val,
                    "new": new_val
                }
                
                # Check ownership transfer
                old_owner = self.field_owner.get(key)
                if old_owner and old_owner != stage:
                    ownership_transfers.append({
                        "field": key,
                        "from": old_owner,
                        "to": stage
                    })
                self.field_owner[key] = stage
                self.current_state[key] = new_val

        # Always record the event so we see the pipeline flow
        if not mutations and action == "MUTATED":
            action = "VALIDATED"
            
        event = {
            "stage": stage,
            "action": action,
            "timestamp": datetime.utcnow().isoformat(),
            "mutations": mutations,
            "ownership_transfers": ownership_transfers,
            "reason": reason
        }
        self.history.append(event)
        return True if mutations else False

class LineageSystem:
    def __init__(self):
        self.job_id = str(uuid.uuid4())[:8]
        self.candidates: Dict[str, CandidateJourney] = {}
        self.mutations_count = 0
        self.ownership_transfers_count = 0
        self.discarded_changes_count = 0

    def init_candidate(self, cid: str, state: Dict[str, Any], stage: str = "CANDIDATE_GENERATION"):
        if cid not in self.candidates:
            self.candidates[cid] = CandidateJourney(cid, state, stage)

    def trace_change(self, cid: str, stage: str, before: Dict[str, Any], after: Dict[str, Any], reason: Optional[str] = None):
        if cid not in self.candidates:
            self.init_candidate(cid, before, "UNKNOWN_SOURCE")
            
        c = self.candidates[cid]
        changed = c._record_change(stage, "MUTATED", before, after, reason)
        
        if changed:
            event = c.history[-1]
            self.mutations_count += len(event["mutations"])
            self.ownership_transfers_count += len(event["ownership_transfers"])

    def record_discarded_change(self, cid: str, stage: str, proposed_change: Dict[str, Any], reason: str):
        if cid not in self.candidates:
            return
            
        c = self.candidates[cid]
        c.history.append({
            "stage": stage,
            "action": "DISCARDED",
            "timestamp": datetime.utcnow().isoformat(),
            "proposed": proposed_change,
            "reason": reason
        })
        self.discarded_changes_count += 1

    def export_traces(self, final_clips_count: int, output_dir: str = "traces"):
        job_dir = os.path.join(output_dir, self.job_id)
        cands_dir = os.path.join(job_dir, "candidates")
        os.makedirs(cands_dir, exist_ok=True)
        
        # 1. Summary JSON
        summary = {
            "job_id": self.job_id,
            "clips_final": final_clips_count,
            "candidates_total": len(self.candidates),
            "mutations": self.mutations_count,
            "ownership_transfers": self.ownership_transfers_count,
            "discarded_changes": self.discarded_changes_count,
            "timestamp": datetime.utcnow().isoformat()
        }
        with open(os.path.join(job_dir, "summary.json"), "w") as f:
            json.dump(summary, f, indent=2)

        # 2. Individual HTML files & Mermaid flows
        for cid, cand in self.candidates.items():
            self._generate_candidate_html(cand, cands_dir)
            
        # 3. Main Index HTML
        self._generate_index_html(job_dir, summary)
        
        return job_dir
        
    def _generate_candidate_html(self, cand: CandidateJourney, output_dir: str):
        # Generate Mermaid
        stages = []
        links = []
        for i, ev in enumerate(cand.history):
            node_id = f"N{i}"
            stage_name = ev["stage"]
            
            # Sublabel based on key mutations
            sublabels = []
            if ev["action"] == "CREATED":
                sublabels.append(f"start={ev['mutations'].get('start',{}).get('new')}s")
            elif ev["action"] == "MUTATED":
                if "payoff_text" in ev["mutations"]:
                    sublabels.append("payoff changed")
                if "end" in ev["mutations"]:
                    sublabels.append(f"end={ev['mutations']['end']['new']}s")
            elif ev["action"] == "DISCARDED":
                sublabels.append("DISCARDED")
            
            label = stage_name
            if sublabels:
                label += "<br/>" + "<br/>".join(sublabels)
                
            stages.append(f'{node_id}["{label}"]')
            if i > 0:
                links.append(f'N{i-1} --> N{i}')
                
        mermaid = "flowchart TD\n    " + "\n    ".join(stages) + "\n    " + "\n    ".join(links)
        
        # History JSON for display
        history_html = ""
        for i, ev in enumerate(cand.history):
            if i > 0:
                history_html += "<div class='history-arrow'>&#9660;</div>\n"
            history_html += f"<div class='event-box'>\n"
            history_html += f"  <h3>{ev['stage']} <span class='action-badge'>{ev['action']}</span></h3>\n"
            if ev.get('reason'):
                history_html += f"  <div class='reason'>{ev['reason']}</div>\n"
            for k, mut in ev.get('mutations', {}).items():
                if k == 'text' or k == 'payoff_text':
                    history_html += f"  <div class='mutation text-mutation'>\n"
                    history_html += f"    <b>{k}</b><br/>\n"
                    history_html += f"    <div class='old-text'>OLD:<br/>\"{mut['old']}\"</div>\n"
                    history_html += f"    <div class='arrow'>&darr;</div>\n"
                    history_html += f"    <div class='new-text'>NEW:<br/>\"{mut['new']}\"</div>\n"
                    history_html += f"  </div>\n"
                else:
                    history_html += f"  <div class='mutation'><b>{k}</b>: {mut['old']} &rarr; {mut['new']}</div>\n"
            history_html += f"</div>\n"
            
        history_json = history_html
        
        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Journey - {cand.cid}</title>
    <script type="module">
        import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
        mermaid.initialize({{ startOnLoad: true }});
    </script>
    <style>
        body {{ font-family: monospace; background: #1e1e1e; color: #d4d4d4; padding: 20px; }}
        .mermaid {{ background: white; padding: 20px; border-radius: 5px; }}
        .event-box {{ background: #2d2d2d; padding: 15px; margin-bottom: 10px; border-radius: 5px; border-left: 4px solid #4daafc; }}
        .action-badge {{ font-size: 0.8em; background: #4daafc; color: #1e1e1e; padding: 2px 6px; border-radius: 3px; float: right; }}
        .reason {{ color: #888; font-style: italic; margin-bottom: 10px; }}
        .text-mutation {{ margin-top: 10px; }}
        .old-text {{ color: #f48771; }}
        .new-text {{ color: #81c995; }}
        .arrow {{ text-align: center; color: #888; margin: 5px 0; font-weight: bold; }}
        .history-arrow {{ text-align: center; color: #4daafc; font-size: 24px; margin: 10px 0; }}
    </style>
</head>
<body>
    <h1>Candidate: {cand.cid}</h1>
    <a href="../index.html" style="color: #4daafc;">Back to Index</a>
    
    <h2>Pipeline Flow</h2>
    <div class="mermaid">
    {mermaid}
    </div>
    
    <h2>Mutation History</h2>
    <div>{history_json}</div>
</body>
</html>"""
        
        with open(os.path.join(output_dir, f"{cand.cid}.html"), "w") as f:
            f.write(html)

    def _generate_index_html(self, output_dir: str, summary: Dict[str, Any]):
        cands_links = "\n".join([f'<li><a href="candidates/{cid}.html">{cid}</a></li>' for cid in self.candidates.keys()])
        
        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Pipeline Trace - {self.job_id}</title>
    <style>
        body {{ font-family: monospace; background: #1e1e1e; color: #d4d4d4; padding: 20px; }}
        a {{ color: #4daafc; }}
        .stat-box {{ background: #2d2d2d; padding: 15px; border-radius: 5px; margin-bottom: 20px; }}
    </style>
</head>
<body>
    <h1>HOTSHORT PIPELINE TRACE - {self.job_id}</h1>
    
    <div class="stat-box">
        <h3>Summary</h3>
        <ul>
            <li>Final Clips: {summary['clips_final']}</li>
            <li>Total Candidates: {summary['candidates_total']}</li>
            <li>Total Mutations: {summary['mutations']}</li>
            <li>Ownership Transfers: {summary['ownership_transfers']}</li>
            <li>Discarded Changes: {summary['discarded_changes']}</li>
        </ul>
    </div>
    
    <h2>Candidate Journeys</h2>
    <ul>
        {cands_links}
    </ul>
</body>
</html>"""
        
        with open(os.path.join(output_dir, "index.html"), "w") as f:
            f.write(html)

# Global Singleton
_active_lineage: Optional[LineageSystem] = None

def get_lineage() -> LineageSystem:
    global _active_lineage
    if _active_lineage is None:
        _active_lineage = LineageSystem()
    return _active_lineage

def reset_lineage() -> LineageSystem:
    global _active_lineage
    _active_lineage = LineageSystem()
    return _active_lineage
