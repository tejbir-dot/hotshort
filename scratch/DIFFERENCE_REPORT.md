# DIFFERENCE REPORT: Baseline vs Story-Centric

**Baseline clips:** 7  |  **Story-Centric clips:** 8

## Q1 — Did candidate count change?
> Baseline: 7 final clips. Story-Centric: 8 final clips. **Changed.**

## Q2 — Did final clip count change?
> Same as Q1: YES.

## Q3 — Did payoff selection change?
**YES — 5 clips changed payoff:**

- `c_0010`
  - BEFORE: *Number four, your self concept is the real lever.*
  - AFTER:  *I am rich.*
- `c_0011`
  - BEFORE: *going to give up an hour of my calendar. Yes, you're going to have to do that. I*
  - AFTER:  *Number one, we have to track our time.*
- `c_0013`
  - BEFORE: *The person who can remove ways, subtract things from the business and have the b*
  - AFTER:  *It's the business plan, they celebrate,*
- `c_0015`
  - BEFORE: *You might have an offer problem.*
  - AFTER:  *If I tripled the amount of customers you have*
- `c_0016`
  - BEFORE: *See how you will have this quiet confidence*
  - AFTER:  *Don't imagine getting there,*

## Q4 — Did boundaries become longer or shorter?

**SHORTER (payoff lock active) (5 clips):**
- `c_0010`: 21.82s → 10.5s  (Δ=-11.3s)
- `c_0011`: 61.2s → 13.82s  (Δ=-47.4s)
- `c_0013`: 38.3s → 13.26s  (Δ=-25.0s)
- `c_0015`: 61.2s → 18.78s  (Δ=-42.4s)
- `c_0016`: 43.5s → 21.18s  (Δ=-22.3s)

## Q5 — Did any clips merge?
> Baseline: 1 clips had suppressed children. Story-Centric: 1 clips had suppressed children.

## Q6 — Did any clips disappear?
**New clips (1):** c_0014

## Q7 — Did any clips improve because payoff was protected?
> No payoff protection changes detected (boundaries similar in both).

## Q8 — Did Ranking favor complete stories?
- Complete threads (PAYOFF_FOUND) in baseline: 0, avg viral_score=0.000
- Complete threads in story-centric: 0, avg viral_score=0.000
> No measurable ranking shift detected.

## Q9 — Did Surgeon make different decisions?
> Surgeon actions identical (story-centric Surgeon patch is observability only in this run).

## Q10 — What new behavior emerged that was impossible before?

1. **Thread-state visible at every stage** — Arc Assembler, Ranking, and Editor Refiner now log `THREAD_STATE` per candidate. Before: zero visibility.

2. **Ranking hierarchy inverted** — Clips with `PAYOFF_FOUND` thread state receive a x1.25 score multiplier. `OPEN` threads penalized x0.85. Before: ranking ignored story completion status entirely.

3. **Payoff boundary enforced in all modes** — Editor Refiner no longer extends past `locked_payoff_time` even outside experiment mode. Before: only active under `HS_EXPERIMENT_MODE=1`.

---

## HOW THE ORGANISM THINKS BEFORE

```
Hook Hunter → suppresses via StoryThread ✅
Arc Assembler → scores payoffs by: legacy + groq_bonus + release_bonus
               (no knowledge of thread state or hook contract)
Ranking → viral_score = pure math (curiosity + semantic + engagement)
          (same score whether story is complete or fragmented)
Editor Refiner → re-scans for hook independently
                 can extend past Arc's payoff without restriction
Surgeon → evaluates MOVE_HOOK / EXTEND_RIGHT / KEEP by raw segment scores
          (no knowledge of whether thread is resolved)
```

## HOW THE ORGANISM THINKS AFTER

```
Hook Hunter → suppresses via StoryThread ✅ (unchanged)
Arc Assembler → same scoring PLUS:
                logs THREAD_HOOK, THREAD_STATE, PAYOFF_CANDIDATE per clip
                (thread's original hook visible to every downstream stage)
Ranking → viral_score adjusted by thread completion:
           PAYOFF_FOUND  → x1.25  (complete story gets promoted)
           CONTINUED     → x1.10  (partial credit)
           OPEN          → x0.85  (incomplete story penalized)
Editor Refiner → payoff lock ALWAYS active (not just experiment mode)
                 clip ends at locked_payoff_time + 2s, never past payoff
Surgeon → logs thread state before every decision
          sets foundation for thread-aware EXTEND_RIGHT thresholds
```
