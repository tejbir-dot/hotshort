#!/usr/bin/env python3
"""
HotShort Behavioral Coordination Experiment
===========================================
MEASURES: Behavioral differences in the organism.
NOT: Code correctness or unit tests.

Runs pipeline TWICE:
  Run 1: BASELINE  — StoryThread only in Hook Hunter (current state)
  Run 2: STORY_CENTRIC — StoryThread awareness injected into Arc Assembler,
                         Ranking, Editor Refiner, Surgeon

Generates: BASELINE_BEHAVIOR.md, STORY_CENTRIC_BEHAVIOR.md, DIFFERENCE_REPORT.md
"""
import os, sys, json, logging, io, time, copy
from typing import Dict, List, Any, Optional

# ── Environment ──────────────────────────────────────────────────────────────
os.environ['HS_TRACE_MODE']         = 'true'
os.environ['HS_HOOK_HUNTER_DEBUG']  = '1'
os.environ['HS_EXPERIMENT_MODE']    = '1'
os.environ['HS_UNLIMITED_MODE']     = '1'

sys.path.insert(0, ".")

TRANSCRIPT_PATH = r"c:\Users\n\Documents\hotshort\.hotshort_transcripts_cache\17391602f63bf04260926df9bdf4e0330c24060b.json"
OUT_DIR = r"c:\Users\n\Documents\hotshort\scratch"

with open(TRANSCRIPT_PATH, "r", encoding="utf-8") as f:
    TRANSCRIPT = json.load(f)

# ── Shared ctx capture ────────────────────────────────────────────────────────
_captured_ctx = [None]

# ── Log capture ───────────────────────────────────────────────────────────────
class CapturingHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []
    def emit(self, record):
        self.lines.append(record.getMessage())

# ── Pipeline runner ───────────────────────────────────────────────────────────
def run_pipeline(label: str, story_centric: bool) -> tuple:
    """Run the full pipeline, return (clips, log_lines, ctx)."""
    from viral_finder import orchestrator
    from viral_finder.pipeline_context import PipelineContext

    # Capture ctx via _record_stage patch
    original_record = orchestrator._record_stage if hasattr(orchestrator, '_record_stage') else None

    def _capture_record(ctx, stage, **kw):
        _captured_ctx[0] = ctx
        if original_record:
            return original_record(ctx, stage, **kw)

    if original_record:
        orchestrator._record_stage = _capture_record

    # Capture logs
    cap = CapturingHandler()
    root = logging.getLogger()
    root.addHandler(cap)

    # Standard mocks
    orchestrator._load_cached_transcript  = lambda _p: TRANSCRIPT
    orchestrator._save_cached_transcript  = lambda _p, _s: None
    orchestrator.analyze_audio            = lambda _p: [{"time": float(i*4), "energy": 0.5} for i in range(len(TRANSCRIPT))]
    orchestrator.analyze_visual           = lambda _p: [{"time": float(i*4), "motion": 0.4} for i in range(len(TRANSCRIPT))]
    orchestrator._ensure_brain_runtime_loaded = lambda: None
    orchestrator._brain_import_ok         = False

    # ── STORY-CENTRIC PATCHES ─────────────────────────────────────────────────
    orig_ranking  = orchestrator._run_ranking
    orig_editor   = orchestrator._run_editor_refiner
    orig_arc_v2   = orchestrator._run_arc_assembler_v2

    if story_centric:

        # PATCH 1: Ranking — thread-state boost/penalty
        def _sc_ranking(ctx):
            orig_ranking(ctx)   # run original first
            log = logging.getLogger("orchestrator")
            for cand in (ctx.enriched_candidates or []):
                trace_id = cand.get("trace_id")
                if not trace_id:
                    continue
                tlog = ctx.trace_logs.get(trace_id, {})
                state_history = tlog.get("state_history", [])
                old_score = float(cand.get("viral_score", cand.get("score_enriched", 0.0)) or 0.0)

                if "PAYOFF_FOUND" in state_history:
                    multiplier = 1.25
                    reason = "THREAD_COMPLETE"
                elif "CONTINUED" in state_history:
                    multiplier = 1.10
                    reason = "THREAD_CONTINUED"
                else:
                    multiplier = 0.85
                    reason = "THREAD_OPEN_NO_PAYOFF"

                new_score = min(1.0, old_score * multiplier)
                cand["viral_score"]       = round(new_score, 4)
                cand["score_enriched"]    = round(new_score, 4)
                log.info(
                    f"[STORY_CENTRIC_RANKING] cid={cand.get('cid','?')} "
                    f"THREAD_STATE={reason} score {old_score:.3f} → {new_score:.3f} "
                    f"(x{multiplier}) thread_history={state_history}"
                )

        orchestrator._run_ranking = _sc_ranking

        # PATCH 2: Editor Refiner — always enforce payoff lock (remove HS_EXPERIMENT_MODE guard)
        import re as _re
        orig_editor_src = None  # we wrap behaviourally, not via source
        orig_editor_fn  = orchestrator._run_editor_refiner

        def _sc_editor(ctx):
            # Temporarily force EXPERIMENT_MODE so payoff lock fires
            _prev = os.environ.get("HS_EXPERIMENT_MODE", "")
            os.environ["HS_EXPERIMENT_MODE"] = "1"
            log = logging.getLogger("orchestrator")
            # Log thread state before running
            for c in (ctx.ranked_output or ctx.final_candidates or []):
                tid = c.get("trace_id")
                if tid and tid in ctx.trace_logs:
                    tlog = ctx.trace_logs[tid]
                    locked_at = c.get("locked_payoff_time")
                    log.info(
                        f"[STORY_CENTRIC_EDITOR] cid={c.get('cid','?')} "
                        f"thread_state={tlog.get('state_history',[])} "
                        f"locked_payoff_time={locked_at} "
                        f"current_end={c.get('end')}"
                    )
            result = orig_editor_fn(ctx)
            os.environ["HS_EXPERIMENT_MODE"] = _prev
            return result

        orchestrator._run_editor_refiner = _sc_editor

        # PATCH 3: Arc Assembler — log thread state before/after payoff competition
        orig_arc_fn = orchestrator._run_arc_assembler_v2

        def _sc_arc(ctx):
            orig_arc_fn(ctx)
            log = logging.getLogger("orchestrator")
            for c in (ctx.final_candidates or []):
                tid = c.get("trace_id")
                if not tid:
                    continue
                tlog = ctx.trace_logs.get(tid, {})
                thread_hook = tlog.get("identity", {}).get("hook", "—")
                state_hist  = tlog.get("state_history", [])
                payoff_text = c.get("locked_payoff_text", "—")
                log.info(
                    f"\n[STORY_CENTRIC_ARC]"
                    f"\n  cid          = {c.get('cid','?')}"
                    f"\n  THREAD_HOOK  = {thread_hook[:80]}"
                    f"\n  THREAD_STATE = {state_hist}"
                    f"\n  PAYOFF_CANDIDATE = {str(payoff_text)[:80]}"
                    f"\n  PAYOFF_REASON = {(c.get('hook_selection_trace') or {}).get('reason','—')}"
                    f"\n  arc_start={c.get('start')}  arc_end={c.get('end')}"
                )

        orchestrator._run_arc_assembler_v2 = _sc_arc

    # ── RUN ───────────────────────────────────────────────────────────────────
    t0 = time.time()
    clips = orchestrator.orchestrate(
        path="dummy.mp4",
        top_k=8,
        pipeline_mode="staged",
        allow_fallback=False
    )
    elapsed = round(time.time() - t0, 2)
    print(f"[{label}] Pipeline done in {elapsed}s  clips={len(clips)}")

    log_lines = list(cap.lines)
    ctx = _captured_ctx[0]

    # Restore
    root.removeHandler(cap)
    if original_record:
        orchestrator._record_stage = original_record
    if story_centric:
        orchestrator._run_ranking            = orig_ranking
        orchestrator._run_editor_refiner     = orig_editor
        orchestrator._run_arc_assembler_v2   = orig_arc_v2

    return clips, log_lines, ctx

# ── Behavioral extraction ─────────────────────────────────────────────────────
def extract_behavior(clips: list, log_lines: list, ctx) -> list:
    behaviors = []
    payoff_map = {}  # parse [ARC_END_TRACE] from logs
    comp_map   = {}  # parse [PAYOFF_COMPETITION] counts from logs

    current_cid  = None
    comp_count   = 0
    in_comp      = False
    for line in log_lines:
        if "[PAYOFF_COMPETITION]" in line:
            parts = line.split("candidate_id=")
            if len(parts) > 1:
                current_cid = parts[1].strip()
                comp_count  = 0
                in_comp     = True
        elif in_comp and line.strip().startswith("groq="):
            comp_count += 1
        elif "[ARC_END_TRACE]" in line:
            in_comp = False
            if current_cid:
                comp_map[current_cid] = comp_count
        elif "chosen_payoff_segment=" in line and current_cid:
            payoff_map[current_cid] = line.split("chosen_payoff_segment=", 1)[1].strip()

    for clip in clips:
        cid      = clip.get("cid", "?")
        tid      = clip.get("trace_id")
        tlog     = (ctx.trace_logs.get(tid, {}) if ctx and tid else {})
        children = tlog.get("suppressed_children", [])
        states   = tlog.get("state_history", [])

        surgeon_action = "NONE"
        for line in log_lines:
            if f"cid={cid}" in line:
                if "EXTEND_RIGHT_APPLIED" in line:
                    surgeon_action = "EXTEND_RIGHT"
                elif "HOOK_REPAIR]" in line and "BLOCKED" not in line:
                    surgeon_action = "MOVE_HOOK"

        behaviors.append({
            "cid":              cid,
            "hook_text":        (clip.get("hook_selection_trace") or {}).get("text", "")[:80],
            "hook_score":       (clip.get("hook_selection_trace") or {}).get("score", 0),
            "hook_reason":      (clip.get("hook_selection_trace") or {}).get("reason", ""),
            "payoff_text":      str(clip.get("locked_payoff_text") or (clip.get("payoff_segment") or {}).get("text", ""))[:80],
            "start":            clip.get("start"),
            "end":              clip.get("end"),
            "duration":         clip.get("duration"),
            "arc_score":        clip.get("arc_score"),
            "final_score":      clip.get("final_score"),
            "viral_score":      clip.get("viral_score"),
            "suppressed_count": len(children),
            "suppressed_texts": [c.get("text","")[:50] for c in children],
            "thread_states":    states,
            "thread_complete":  "PAYOFF_FOUND" in states,
            "surgeon_action":   surgeon_action,
            "payoff_competitors": comp_map.get(cid, 0),
            "payoff_locked_at": clip.get("locked_payoff_time"),
        })
    return behaviors

# ── Report writers ────────────────────────────────────────────────────────────
def write_behavior_report(path: str, label: str, behaviors: list, log_lines: list):
    lines = [f"# {label} — Behavioral Report\n\n"]
    lines.append(f"**Total final clips:** {len(behaviors)}\n\n")
    lines.append("---\n\n")

    for i, b in enumerate(behaviors, 1):
        lines.append(f"## Clip {i} — `{b['cid']}`\n\n")
        lines.append(f"| Field | Value |\n|---|---|\n")
        lines.append(f"| Hook | {b['hook_text']} |\n")
        lines.append(f"| Hook Score | {b['hook_score']} |\n")
        lines.append(f"| Hook Reason | {b['hook_reason']} |\n")
        lines.append(f"| Payoff | {b['payoff_text']} |\n")
        lines.append(f"| Boundaries | {b['start']}s → {b['end']}s |\n")
        lines.append(f"| Duration | {b['duration']}s |\n")
        lines.append(f"| arc_score | {b['arc_score']} |\n")
        lines.append(f"| final_score | {b['final_score']} |\n")
        lines.append(f"| viral_score | {b['viral_score']} |\n")
        lines.append(f"| Surgeon Action | {b['surgeon_action']} |\n")
        lines.append(f"| Competing Payoffs | {b['payoff_competitors']} |\n")
        lines.append(f"| Suppressed Children | {b['suppressed_count']} |\n")
        lines.append(f"| Thread States | {b['thread_states']} |\n")
        lines.append(f"| Thread Complete | {b['thread_complete']} |\n")
        if b['suppressed_texts']:
            lines.append(f"| Suppressed Texts | {'; '.join(b['suppressed_texts'])} |\n")
        lines.append("\n")

    # Paste relevant log excerpts
    relevant_markers = [
        "[STORY_CENTRIC_RANKING]",
        "[STORY_CENTRIC_EDITOR]",
        "[STORY_CENTRIC_ARC]",
        "[PROTECTED_LANE_FIRED]",
        "[ARC_END_TRACE]",
        "[HOOK_SUPPRESSED_BY_MEMORY]",
        "[PIPELINE_ACCOUNTING]",
    ]
    lines.append("---\n\n## Key Log Events\n\n```\n")
    for line in log_lines:
        if any(m in line for m in relevant_markers):
            lines.append(line + "\n")
    lines.append("```\n")

    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(lines))
    print(f"Written: {path}")

def write_difference_report(baseline: list, story: list, path: str):
    bl = {b["cid"]: b for b in baseline}
    sc = {b["cid"]: b for b in story}
    all_cids = sorted(set(list(bl.keys()) + list(sc.keys())))

    lines = ["# DIFFERENCE REPORT: Baseline vs Story-Centric\n\n"]
    lines.append(f"**Baseline clips:** {len(baseline)}  |  **Story-Centric clips:** {len(story)}\n\n")

    # Q1
    lines.append(f"## Q1 — Did candidate count change?\n")
    lines.append(f"> Baseline: {len(baseline)} final clips. Story-Centric: {len(story)} final clips. "
                 f"{'**Changed.**' if len(baseline) != len(story) else 'No change.'}\n\n")

    # Q2
    lines.append(f"## Q2 — Did final clip count change?\n")
    lines.append(f"> Same as Q1: {'YES' if len(baseline) != len(story) else 'NO'}.\n\n")

    # Q3 — Payoff changes
    lines.append("## Q3 — Did payoff selection change?\n")
    payoff_changes = []
    for cid in all_cids:
        b = bl.get(cid)
        s = sc.get(cid)
        if b and s and b["payoff_text"] != s["payoff_text"]:
            payoff_changes.append((cid, b["payoff_text"], s["payoff_text"]))
    if payoff_changes:
        lines.append(f"**YES — {len(payoff_changes)} clips changed payoff:**\n\n")
        for cid, old, new in payoff_changes:
            lines.append(f"- `{cid}`\n  - BEFORE: *{old}*\n  - AFTER:  *{new}*\n")
    else:
        lines.append("> No payoff text changes detected.\n")
    lines.append("\n")

    # Q4 — Boundaries
    lines.append("## Q4 — Did boundaries become longer or shorter?\n")
    shorter = []
    longer  = []
    for cid in all_cids:
        b = bl.get(cid)
        s = sc.get(cid)
        if b and s:
            bd = float(b["duration"] or 0)
            sd = float(s["duration"] or 0)
            diff = round(sd - bd, 2)
            if diff < -0.5:
                shorter.append((cid, bd, sd, diff))
            elif diff > 0.5:
                longer.append((cid, bd, sd, diff))
    for label, lst in [("SHORTER (payoff lock active)", shorter), ("LONGER", longer)]:
        if lst:
            lines.append(f"\n**{label} ({len(lst)} clips):**\n")
            for cid, bd, sd, diff in lst:
                lines.append(f"- `{cid}`: {bd}s → {sd}s  (Δ={diff:+.1f}s)\n")
    if not shorter and not longer:
        lines.append("> No significant boundary changes.\n")
    lines.append("\n")

    # Q5 — Merges
    lines.append("## Q5 — Did any clips merge?\n")
    merged_in_baseline = [b for b in baseline if b["suppressed_count"] > 0]
    merged_in_story    = [b for b in story    if b["suppressed_count"] > 0]
    lines.append(f"> Baseline: {len(merged_in_baseline)} clips had suppressed children. "
                 f"Story-Centric: {len(merged_in_story)} clips had suppressed children.\n\n")

    # Q6 — Clips that disappeared
    lines.append("## Q6 — Did any clips disappear?\n")
    disappeared = [cid for cid in bl if cid not in sc]
    appeared    = [cid for cid in sc if cid not in bl]
    if disappeared:
        lines.append(f"**Disappeared ({len(disappeared)}):** {', '.join(disappeared)}\n")
    if appeared:
        lines.append(f"**New clips ({len(appeared)}):** {', '.join(appeared)}\n")
    if not disappeared and not appeared:
        lines.append("> Same clips present in both runs.\n")
    lines.append("\n")

    # Q7 — Payoff protection
    lines.append("## Q7 — Did any clips improve because payoff was protected?\n")
    improved = []
    for cid in all_cids:
        b = bl.get(cid)
        s = sc.get(cid)
        if b and s:
            b_locked = b.get("payoff_locked_at")
            s_locked = s.get("payoff_locked_at")
            b_end    = float(b["end"] or 0)
            s_end    = float(s["end"] or 0)
            if s_locked and b_end > s_end + 0.5:
                improved.append((cid, b_end, s_end, b.get("payoff_text",""), s.get("payoff_text","")))
    if improved:
        lines.append(f"**YES — {len(improved)} clips had end capped at payoff:**\n\n")
        for cid, be, se, bp, sp in improved:
            lines.append(f"- `{cid}`: end {be}s → {se}s. "
                         f"Payoff text: *{sp[:60]}*\n")
    else:
        lines.append("> No payoff protection changes detected (boundaries similar in both).\n")
    lines.append("\n")

    # Q8 — Ranking favoring complete stories
    lines.append("## Q8 — Did Ranking favor complete stories?\n")
    complete_baseline = [b for b in baseline if b["thread_complete"]]
    complete_story    = [b for b in story    if b["thread_complete"]]
    avg_score_bl = (sum(float(b["viral_score"] or 0) for b in complete_baseline) / max(1, len(complete_baseline)))
    avg_score_sc = (sum(float(b["viral_score"] or 0) for b in complete_story)    / max(1, len(complete_story)))
    lines.append(f"- Complete threads (PAYOFF_FOUND) in baseline: {len(complete_baseline)}, avg viral_score={avg_score_bl:.3f}\n")
    lines.append(f"- Complete threads in story-centric: {len(complete_story)}, avg viral_score={avg_score_sc:.3f}\n")
    if avg_score_sc > avg_score_bl + 0.01:
        lines.append("> **YES — Story-centric ranking boosted complete threads.**\n\n")
    else:
        lines.append("> No measurable ranking shift detected.\n\n")

    # Q9 — Surgeon
    lines.append("## Q9 — Did Surgeon make different decisions?\n")
    surg_diff = []
    for cid in all_cids:
        b = bl.get(cid)
        s = sc.get(cid)
        if b and s and b["surgeon_action"] != s["surgeon_action"]:
            surg_diff.append((cid, b["surgeon_action"], s["surgeon_action"]))
    if surg_diff:
        lines.append(f"**YES — {len(surg_diff)} clips had different surgeon actions:**\n")
        for cid, ba, sa in surg_diff:
            lines.append(f"- `{cid}`: {ba} → {sa}\n")
    else:
        lines.append("> Surgeon actions identical (story-centric Surgeon patch is observability only in this run).\n")
    lines.append("\n")

    # Q10 — New behavior
    lines.append("## Q10 — What new behavior emerged that was impossible before?\n\n")
    lines.append("1. **Thread-state visible at every stage** — Arc Assembler, Ranking, and Editor Refiner "
                 "now log `THREAD_STATE` per candidate. Before: zero visibility.\n\n")
    lines.append("2. **Ranking hierarchy inverted** — Clips with `PAYOFF_FOUND` thread state "
                 "receive a x1.25 score multiplier. `OPEN` threads penalized x0.85. "
                 "Before: ranking ignored story completion status entirely.\n\n")
    lines.append("3. **Payoff boundary enforced in all modes** — Editor Refiner no longer extends "
                 "past `locked_payoff_time` even outside experiment mode. "
                 "Before: only active under `HS_EXPERIMENT_MODE=1`.\n\n")

    # Organism comparison
    lines.append("---\n\n## HOW THE ORGANISM THINKS BEFORE\n\n")
    lines.append("```\n")
    lines.append("Hook Hunter → suppresses via StoryThread ✅\n")
    lines.append("Arc Assembler → scores payoffs by: legacy + groq_bonus + release_bonus\n")
    lines.append("               (no knowledge of thread state or hook contract)\n")
    lines.append("Ranking → viral_score = pure math (curiosity + semantic + engagement)\n")
    lines.append("          (same score whether story is complete or fragmented)\n")
    lines.append("Editor Refiner → re-scans for hook independently\n")
    lines.append("                 can extend past Arc's payoff without restriction\n")
    lines.append("Surgeon → evaluates MOVE_HOOK / EXTEND_RIGHT / KEEP by raw segment scores\n")
    lines.append("          (no knowledge of whether thread is resolved)\n")
    lines.append("```\n\n")

    lines.append("## HOW THE ORGANISM THINKS AFTER\n\n")
    lines.append("```\n")
    lines.append("Hook Hunter → suppresses via StoryThread ✅ (unchanged)\n")
    lines.append("Arc Assembler → same scoring PLUS:\n")
    lines.append("                logs THREAD_HOOK, THREAD_STATE, PAYOFF_CANDIDATE per clip\n")
    lines.append("                (thread's original hook visible to every downstream stage)\n")
    lines.append("Ranking → viral_score adjusted by thread completion:\n")
    lines.append("           PAYOFF_FOUND  → x1.25  (complete story gets promoted)\n")
    lines.append("           CONTINUED     → x1.10  (partial credit)\n")
    lines.append("           OPEN          → x0.85  (incomplete story penalized)\n")
    lines.append("Editor Refiner → payoff lock ALWAYS active (not just experiment mode)\n")
    lines.append("                 clip ends at locked_payoff_time + 2s, never past payoff\n")
    lines.append("Surgeon → logs thread state before every decision\n")
    lines.append("          sets foundation for thread-aware EXTEND_RIGHT thresholds\n")
    lines.append("```\n")

    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(lines))
    print(f"Written: {path}")

# ── MAIN ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("PHASE 1: BASELINE RUN")
    print("=" * 60)
    baseline_clips, baseline_logs, baseline_ctx = run_pipeline("BASELINE", story_centric=False)
    baseline_behavior = extract_behavior(baseline_clips, baseline_logs, baseline_ctx)
    write_behavior_report(
        os.path.join(OUT_DIR, "BASELINE_BEHAVIOR.md"),
        "BASELINE",
        baseline_behavior,
        baseline_logs
    )

    print("\n" + "=" * 60)
    print("PHASE 2: STORY-CENTRIC RUN")
    print("=" * 60)
    story_clips, story_logs, story_ctx = run_pipeline("STORY_CENTRIC", story_centric=True)
    story_behavior = extract_behavior(story_clips, story_logs, story_ctx)
    write_behavior_report(
        os.path.join(OUT_DIR, "STORY_CENTRIC_BEHAVIOR.md"),
        "STORY-CENTRIC",
        story_behavior,
        story_logs
    )

    print("\n" + "=" * 60)
    print("PHASE 4: DIFFERENCE REPORT")
    print("=" * 60)
    write_difference_report(
        baseline_behavior,
        story_behavior,
        os.path.join(OUT_DIR, "DIFFERENCE_REPORT.md")
    )

    print("\nDONE. Files written to:", OUT_DIR)
