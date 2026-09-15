import json, os, sys
import logging

sys.path.insert(0, ".")
from viral_finder import orchestrator

TRANSCRIPT_PATH = r"c:\Users\n\Documents\hotshort\.hotshort_transcripts_cache\17391602f63bf04260926df9bdf4e0330c24060b.json"

with open(TRANSCRIPT_PATH, "r", encoding="utf-8") as f:
    transcript = json.load(f)

# The hook the user mentioned: "What’s the one thing that actually matters?"
hook_text_ref = "one thing that you can do today that actually matters"
hook_seg = None
for seg in transcript:
    if hook_text_ref.lower() in str(seg.get("text", "")).lower():
        hook_seg = seg
        break

if not hook_seg:
    print("Could not find exact hook segment")
    sys.exit(1)

print(f"THREAD HOOK: [{hook_seg['start']}] {hook_seg['text']}")

print("\n--- STATE TRANSITION ATTEMPTS ---")
# Simulating the PipelineContext Trace log for this candidate
print("trace_state(trace_id, 'OPEN') -> Emitted by Hook Hunter")
print("trace_state(trace_id, 'CONTINUED') -> Never emitted because Arc Assembler doesn't call it")
print("trace_state(trace_id, 'PAYOFF_FOUND') -> Never emitted because Arc Assembler didn't lock the thread payload")

print("\n--- CANDIDATE SEGMENTS IN ARC WINDOW ---")
window_end = 600.0

for seg in transcript:
    s = float(seg.get("start", 0.0))
    if s < hook_seg["start"]: continue
    if s > window_end: break
    
    text = seg.get("text", "")
    ending_strength = float(seg.get("ending_strength", 0.0))
    payoff_res = float(seg.get("payoff_resolution", 0.0))
    groq_role = seg.get("groq_role", "BUILD")
    hook_res_bonus = orchestrator.compute_hook_resolution_bonus(text, hook_seg["text"])
    
    # Calculate what Arc Assembler legacy score would be
    legacy_score = (ending_strength + payoff_res) / 2.0
    groq_bonus = 0.4 if groq_role == "PAYOFF" else 0.0
    final = legacy_score + groq_bonus + hook_res_bonus
    
    marker = "  "
    if "5%" in text and "95%" in text:
        marker = ">>"
    
    print(f"{marker} [{s:.1f}] {text[:55]:<55} | end_str={ending_strength:.3f} | payoff_res={payoff_res:.3f} | role={groq_role:<6} | hook_bonus={hook_res_bonus:.3f} | TOTAL={final:.3f}")

