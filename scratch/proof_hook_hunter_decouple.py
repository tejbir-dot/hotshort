"""
Executable proof for the _run_global_hook_hunter decoupling refactor.

Goal: prove that a story-thread CONTINUATION decision can no longer prevent
CREATION of a hook candidate, and that no valid hook is silently discarded at
discovery time. Suppression of a story-duplicate is now an explicit, logged,
counted decision taken in the LATER dedup/ranking stage.

We inject working stubs for the story-memory primitives (which are dormant/None
in the shipped code) so the continuation path is actually exercised.
"""
import sys, types
sys.path.insert(0, ".")

# The real ultron_finder_v33 pulls in faster_whisper/transformers, which fail to
# import in this environment. It is irrelevant to the hook hunter, so stub it out
# before importing the orchestrator (mirrors the module's own import-fallback intent).
_stub = types.ModuleType("viral_finder.ultron_finder_v33")
_stub.find_viral_moments = lambda *a, **k: []
sys.modules["viral_finder.ultron_finder_v33"] = _stub

import viral_finder.orchestrator as orch
from viral_finder.pipeline_context import PipelineContext


# ── Working StoryThread stub (the real one is not present in the repo) ──────────
class StubThread:
    def __init__(self, hook_text, start_s, start_idx, trace_id):
        self.hook_text = hook_text
        self.start_s = start_s
        self.start_idx = start_idx
        self.trace_id = trace_id
        self.development_points = []
        # attributes the orchestrator sets after construction
        self.promise = None
        self.narrative_debt = None
        self.promise_type = None
        self.contract = None

    def is_expired(self, seg_start, horizon):
        return (seg_start - self.start_s) > horizon

    def does_segment_continue(self, text, compute_bonus, threshold):
        # continuity = word overlap with the hook that opened the thread
        w1 = set(self.hook_text.lower().split())
        w2 = set(text.lower().split())
        return 0.8 if (w1 & w2) else 0.0

    def add_development_point(self, text, start, continuity):
        self.development_points.append((start, continuity, text))

    def __repr__(self):
        return f"<StubThread '{self.hook_text[:20]}' t={self.start_s}>"


# Inject the dormant primitives so the continuation branch runs.
ni = sys.modules.setdefault("utils.narrative_intelligence",
                            types.ModuleType("utils.narrative_intelligence"))
import utils.narrative_intelligence as real_ni
real_ni.StoryThread = StubThread
real_ni.infer_narrative_promise_and_debt = lambda text: ("promise", "debt", "curiosity")
real_ni.build_contract = lambda ptype, text: {"type": ptype}

# Truthy resolution-bonus fn (only its truthiness + being passed through matters).
orch.compute_hook_resolution_bonus = lambda *a, **k: 0.8

# Deterministic quality scores: every segment clears the strength gate.
def fake_quality_scores(transcript, s, e):
    return {"hook_score": 1.0, "pattern_break_score": 0.0,
            "open_loop_score": 1.0, "rewatch_score": 0.0}
orch.compute_quality_scores = fake_quality_scores


def build_ctx():
    ctx = PipelineContext(path="x", top_k=10, allow_fallback=True)
    # A opens an arc; B is a DISTINCT, STRONGER hook that continues A's arc;
    # C is an independent hook on a different topic.
    ctx.transcript = [
        {"start": 10.0, "end": 14.0,
         "text": "Discipline separates winners from everyone else in life"},          # A (opener)
        {"start": 15.0, "end": 19.0,
         "text": "Discipline really is why winners keep winning every single day"},    # B (continuation of A)
        {"start": 60.0, "end": 64.0,
         "text": "Graphics hardware architecture powers modern computing systems today"},  # C (independent)
    ]
    ctx.raw_candidates = []
    return ctx


def reference_old_behavior(ctx):
    """Reconstruct the pre-refactor gate: a continuation is NEVER created."""
    threads = []
    created = []
    horizon = 120.0
    thr = 0.30
    for seg in ctx.transcript:
        text = seg["text"]
        continuing = False
        threads = [t for t in threads if not t.is_expired(seg["start"], horizon)]
        for t in threads:
            if t.does_segment_continue(text, True, thr) >= thr:
                continuing = True
                break
        if not continuing:                      # <-- OLD GATE: creation blocked
            tid = f"tid-{len(created)}"
            created.append(dict(seg, trace_id=tid))
            threads.append(StubThread(text, seg["start"], 0, tid))
    return created


def main():
    # ---- NEW behavior (real function under test) ----
    ctx = build_ctx()
    orch._run_global_hook_hunter(ctx)

    injected = ctx.raw_candidates
    injected_texts = [c["text"][:25] for c in injected]

    # ---- OLD behavior (reference model) ----
    ref_created = reference_old_behavior(build_ctx())
    old_texts = [c["text"][:25] for c in ref_created]

    print("=== OLD (discovery-time suppression) ===")
    print("  candidates that EXISTED at all:", old_texts)
    print("=== NEW (discovery decoupled from suppression) ===")
    print("  injected into raw_candidates   :", injected_texts)
    print("  hooks_suppressed (explicit)    :", ctx.hooks_suppressed)
    print("  trace_logs threads             :", len(ctx.trace_logs))

    # Which trace ids recorded a suppressed child (proof it was explicit, not silent)?
    supp_children = {tid: v.get("suppressed_children", [])
                     for tid, v in ctx.trace_logs.items()
                     if v.get("suppressed_children")}

    # ── Assertions ──────────────────────────────────────────────────────────
    # 1. The independent hook C is injected (continuation of A never blocked it).
    assert any("Graphics hardware" in c["text"] for c in injected), \
        "INDEPENDENT hook C was discarded!"

    # 2. The opener A is injected.
    assert any(c["text"].startswith("Discipline separates") for c in injected), \
        "Opener A missing!"

    # 3. Exactly one story-duplicate (B) was suppressed — and it was EXPLICIT
    #    (counted + traced), not a silent discovery-time drop.
    assert ctx.hooks_suppressed == 1, f"expected 1 suppressed, got {ctx.hooks_suppressed}"
    assert supp_children, "suppression was not traced (silent discard!)"

    # 4. OLD behavior never even created B (proving the discovery-time coupling).
    assert not any(c["text"].startswith("Discipline really") for c in ref_created), \
        "reference model unexpectedly created B"

    # 5. Every segment that cleared the gate was DISCOVERED in the new code:
    #    injected (A, C) + suppressed (B) == 3.
    assert len(injected) + ctx.hooks_suppressed == 3, \
        "a hook hypothesis was silently lost at discovery"

    print("\nALL ASSERTIONS PASSED")
    print("  -> Continuation no longer blocks creation.")
    print("  -> Independent hooks always injected.")
    print("  -> Story-duplicate suppression is explicit + traced at the dedup stage.")


if __name__ == "__main__":
    main()
