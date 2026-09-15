import sys
import json

with open('c:/Users/n/Documents/hotshort/viral_finder/candidate_lineage.py', 'r', encoding='utf-8') as f:
    code = f.read()

old_logic = '''        if mutations or action == "CREATED":
            event = {
                "stage": stage,
                "action": action,
                "timestamp": datetime.utcnow().isoformat(),
                "mutations": mutations,
                "ownership_transfers": ownership_transfers,
                "reason": reason
            }
            self.history.append(event)
            return True
            
        return False'''

new_logic = '''        # Always record the event so we see the pipeline flow
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
        return True if mutations else False'''

code = code.replace(old_logic, new_logic)

old_html = '''        history_json = json.dumps(cand.history, indent=2)'''
new_html = '''        history_html = ""
        for ev in cand.history:
            history_html += f"<div class='event-box'>\\n"
            history_html += f"  <h3>{ev['stage']} <span class='action-badge'>{ev['action']}</span></h3>\\n"
            if ev.get('reason'):
                history_html += f"  <div class='reason'>{ev['reason']}</div>\\n"
            for k, mut in ev.get('mutations', {}).items():
                if k == 'text' or k == 'payoff_text':
                    history_html += f"  <div class='mutation text-mutation'>\\n"
                    history_html += f"    <b>{k}</b><br/>\\n"
                    history_html += f"    <div class='old-text'>OLD:<br/>\\\"{mut['old']}\\\"</div>\\n"
                    history_html += f"    <div class='arrow'>&darr;</div>\\n"
                    history_html += f"    <div class='new-text'>NEW:<br/>\\\"{mut['new']}\\\"</div>\\n"
                    history_html += f"  </div>\\n"
                else:
                    history_html += f"  <div class='mutation'><b>{k}</b>: {mut['old']} &rarr; {mut['new']}</div>\\n"
            history_html += f"</div>\\n"
            
        history_json = history_html'''

code = code.replace(old_html, new_html)

old_style = '''        .mermaid { background: white; padding: 20px; border-radius: 5px; }'''
new_style = '''        .mermaid { background: white; padding: 20px; border-radius: 5px; }
        .event-box { background: #2d2d2d; padding: 15px; margin-bottom: 10px; border-radius: 5px; border-left: 4px solid #4daafc; }
        .action-badge { font-size: 0.8em; background: #4daafc; color: #1e1e1e; padding: 2px 6px; border-radius: 3px; float: right; }
        .reason { color: #888; font-style: italic; margin-bottom: 10px; }
        .text-mutation { margin-top: 10px; }
        .old-text { color: #f48771; }
        .new-text { color: #81c995; }
        .arrow { text-align: center; color: #888; margin: 5px 0; font-weight: bold; }'''
        
code = code.replace(old_style, new_style)

with open('c:/Users/n/Documents/hotshort/viral_finder/candidate_lineage.py', 'w', encoding='utf-8') as f:
    f.write(code)
print('candidate_lineage updated.')
