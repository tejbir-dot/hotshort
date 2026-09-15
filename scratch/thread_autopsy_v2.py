import os, sys, json
import logging

os.environ['HS_TRACE_MODE'] = 'true'
sys.path.insert(0, ".")
from viral_finder import orchestrator

# Suppress typical logs to keep output clean
logging.getLogger().setLevel(logging.CRITICAL)

print("Running pipeline to generate Groq scores... (this may take a minute if not fully cached)")

# Run pipeline up to ranking/arc assembler to get the populated transcript
orig_arc = orchestrator._run_arc_assembler_v2
captured_transcript = []

def intercept_arc(ctx):
    global captured_transcript
    captured_transcript = list(ctx.transcript)
    # Don't need to run actual arc, we just want the populated transcript
    pass

orchestrator._run_arc_assembler_v2 = intercept_arc

try:
    orchestrator.orchestrate(
        path="dummy.mp4",
        top_k=8,
        pipeline_mode="staged",
        allow_fallback=False
    )
except Exception:
    pass

hook_text_ref = "one thing that you can do today that actually matters"
hook_seg = None
for seg in captured_transcript:
    if hook_text_ref.lower() in str(seg.get("text", "")).lower():
        hook_seg = seg
        break

if not hook_seg:
    print("Could not find exact hook segment in populated transcript")
    sys.exit(1)

print(f"\nTHREAD HOOK: [{hook_seg['start']}] {hook_seg['text']}")
print("\n--- STATE TRANSITION ATTEMPTS ---")
print("OPEN")
print("CONTINUED (never triggered because Arc Assembler doesn't check thread state)")
print("PAYOFF_FOUND (never triggered because Arc Assembler ignores the thread)")

print("\n--- CANDIDATE SEGMENTS IN ARC WINDOW ---")
window_end = 600.0

for seg in captured_transcript:
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

