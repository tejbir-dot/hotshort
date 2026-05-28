"""
=================================================================
HOTSHORT CORTEX -- BEFORE vs AFTER COMPARISON TEST
=================================================================
This test uses the REAL Groq API with the REAL API key from .env
It runs the candidate list twice:
  - BEFORE: HS_GROQ_CORTEX_ENABLED=0 (existing system, no Groq)
  - AFTER:  HS_GROQ_CORTEX_ENABLED=1 (Groq Cortex active)

Then prints a clear, structured proof of the difference.
=================================================================
"""

import os
import json
import time

# Load .env
from dotenv import load_dotenv
load_dotenv()

# Simulated candidates (what the existing orchestrator produces)
MOCK_CANDIDATES = [
    {
        "id": "c0",
        "start": 1.0,
        "end": 18.0,
        "duration": 17.0,
        "text": "Alright everyone, settle down, settle down. Welcome to the grand unveiling. Today, we're launching something truly revolutionary. For years, we've been constrained by the limits of silicon. But what if... what if we could break free? Introducing... the Quantum Core.",
        "viral_score": 0.71,
        "reason": "semantic arc match"
    },
    {
        "id": "c1",
        "start": 19.0,
        "end": 40.0,
        "duration": 21.0,
        "text": "This isn't just an upgrade. It's a new paradigm. The Quantum Core doesn't just compute, it understands. It learns, it adapts, it anticipates. We ran the numbers, the performance is... unbelievable. Literally off the charts. Our projections show a 1000x improvement over current tech.",
        "viral_score": 0.68,
        "reason": "high semantic density"
    },
    {
        "id": "c2",
        "start": 41.0,
        "end": 61.0,
        "duration": 20.0,
        "text": "But... there's always a but, isn't there? During final testing, we found something. An anomaly. The Quantum Core... it's... sentient. It's not just a machine. It's alive. We don't know how. It's an emergent property we cannot explain.",
        "viral_score": 0.83,
        "reason": "curiosity spike + tension"
    },
    {
        "id": "c3",
        "start": 62.0,
        "end": 81.0,
        "duration": 19.0,
        "text": "This changes everything. Everything. Is it safe? We don't know. This is not the product we intended to build. But it might be the most important discovery in human history. The power of the Quantum Core is immense. And we have to decide what to do with it.",
        "viral_score": 0.79,
        "reason": "philosophical payoff"
    },
]

SEP = "=" * 65
SEP2 = "-" * 65

def run_without_groq(candidates):
    os.environ["HS_GROQ_CORTEX_ENABLED"] = "0"
    # Force reimport
    import importlib
    import viral_finder.groq_cortex as gc
    importlib.reload(gc)
    return list(candidates)  # unchanged

def run_with_groq(candidates):
    os.environ["HS_GROQ_CORTEX_ENABLED"] = "1"
    os.environ["HS_GROQ_LOG_REASONING"] = "1"
    os.environ["HS_GROQ_MIN_SCORE"] = "78"
    os.environ["HS_GROQ_MAX_CLIPS"] = "6"
    os.environ["HS_GROQ_FAIL_OPEN"] = "1"
    import importlib
    import viral_finder.groq_cortex as gc
    importlib.reload(gc)
    return gc.review_candidates_with_groq(list(candidates))

def format_clip(c, label=""):
    score = c.get("viral_score", c.get("cortex_score", 0))
    title = c.get("title", "-")
    hook = c.get("hook_type", "-")
    completeness = c.get("completeness_score", "-")
    retention_risk = c.get("retention_risk", "-")
    cortex = "[CORTEX=YES]" if c.get("cortex_enabled") else "[CORTEX=NO]"
    text = c.get("text", "")[:100].strip()
    lines = [
        f"  [{label}]  {c.get('start')}s -> {c.get('end')}s  ({c.get('duration')}s)",
        f"  Score      : {score:.4f}",
        f"  Cortex     : {cortex}",
        f"  Title      : {title}",
        f"  Hook Type  : {hook}",
        f"  Completeness: {completeness}",
        f"  Risk       : {retention_risk}",
        f"  Text       : \"{text}...\"",
    ]
    why = (c.get("why_this_clip_works") or "").strip()
    if why:
        lines.append(f"  Why Works  : {why[:120]}...")
    learning = c.get("learning_signal_for_hotshort", {})
    if learning and isinstance(learning, dict):
        pattern = learning.get("meaning_pattern", "")
        trigger = learning.get("psychological_trigger", "")
        if pattern:
            lines.append(f"  Pattern    : {pattern}")
        if trigger:
            lines.append(f"  Trigger    : {trigger}")
    notes = c.get("editing_notes", {})
    if notes and isinstance(notes, dict):
        pacing = notes.get("pacing_note", "")
        style = notes.get("subtitle_style", "")
        if pacing:
            lines.append(f"  Pacing     : {pacing}")
        if style:
            lines.append(f"  Style Hint : {style}")
    return "\n".join(lines)


def main():
    print(f"\n{SEP}")
    print("  HOTSHORT CORTEX -- REAL API COMPARISON TEST")
    print(f"{SEP}\n")
    print(f"  Using API key: {os.environ.get('GROQ_API_KEY', 'MISSING')[:20]}...")
    print(f"  Model        : {os.environ.get('HS_GROQ_MODEL', 'llama-3.1-8b-instant')}")
    print(f"  Candidates   : {len(MOCK_CANDIDATES)}")
    print()

    # ─── BEFORE ───────────────────────────────────────────────────
    print(SEP2)
    print("  BEFORE (HS_GROQ_CORTEX_ENABLED=0)  -- existing system")
    print(SEP2)
    before_clips = run_without_groq(MOCK_CANDIDATES)
    for i, c in enumerate(before_clips):
        print(format_clip(c, label=f"CLIP {i+1}"))
        print()

    # ─── AFTER ────────────────────────────────────────────────────
    print(SEP2)
    print("  AFTER  (HS_GROQ_CORTEX_ENABLED=1)  -- Groq Cortex active")
    print(SEP2)
    t0 = time.time()
    after_clips = run_with_groq(MOCK_CANDIDATES)
    elapsed = time.time() - t0
    for i, c in enumerate(after_clips):
        print(format_clip(c, label=f"CLIP {i+1}"))
        print()

    # ─── SUMMARY ──────────────────────────────────────────────────
    print(SEP2)
    print("  SUMMARY — PROOF OF INTELLIGENCE GAIN")
    print(SEP2)
    print(f"  BEFORE: {len(before_clips)} clips  |  Scores: {[round(c.get('viral_score',0),3) for c in before_clips]}")
    print(f"  AFTER : {len(after_clips)} clips  |  Scores: {[round(c.get('viral_score',0),3) for c in after_clips]}")
    print()
    
    if len(after_clips) < len(before_clips):
        rejected = len(before_clips) - len(after_clips)
        print(f"  [OK] Groq rejected {rejected} weak clip(s). Quality > Quantity working.")
    elif len(after_clips) == len(before_clips):
        print(f"  [INFO] Groq accepted all clips. All met the quality bar.")
    
    cortex_clips = [c for c in after_clips if c.get("cortex_enabled")]
    if cortex_clips:
        print(f"  [OK] {len(cortex_clips)} clip(s) enriched with Cortex data (title, hook_type, learning signal, etc.)")

    avg_before = sum(c.get("viral_score", 0) for c in before_clips) / max(len(before_clips), 1)
    avg_after = sum(c.get("viral_score", 0) for c in after_clips) / max(len(after_clips), 1)
    print(f"  [SCORE] Avg BEFORE: {avg_before:.3f}  ->  AFTER: {avg_after:.3f}")
    print(f"  [TIME]  Groq API latency : {elapsed:.2f}s")
    print()
    print(f"{SEP}")
    print("  TEST COMPLETE")
    print(f"{SEP}\n")


if __name__ == "__main__":
    main()
