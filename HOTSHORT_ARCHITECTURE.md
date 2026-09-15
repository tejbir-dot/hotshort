# HotShort System Architecture & Bug Analysis

## 1. The "Early Locking" (Chronological Shadowing) Bug
**Error Signature:**
```
RuntimeError: All clips failed to process
No Evidence packets found in any candidate. (IntelligenceArtifact.evidence_stream was never populated.)
```

**Type of Bug:**
Architectural / State Management (specifically: **Premature Commit** or **Chronological Shadowing**).

### Behind the Scenes: What went wrong?
The HotShort pipeline processes video transcripts to find viral moments. It operates in stages:
1. **Hook Hunter**: Scans the transcript to find engaging "hooks" (the start of a viral clip).
2. **Arc Assembler**: Expands the hook into a full narrative arc (finding the payoff).
3. **Groq Surgeon / Evaluators**: Scores the assembled clip and attaches "Evidence" packets (e.g., how viral, complete, and engaging the clip is).

**The Flaw in Hook Hunter:**
Hook Hunter was designed with a "first-acceptable-wins" mechanism. As it scanned chronologically through the transcript, the moment it found a segment that crossed the minimum threshold (e.g., `hook_strength > 0.45`), it immediately created a `StoryThread` (a stateful object locking the narrative arc).

When subsequent segments in the same arc were evaluated—even if they were *significantly stronger* (e.g., `hook_strength = 0.95`)—Hook Hunter would check the active `StoryThread`, ask "does this segment continue you?", and if the answer was yes, it would **suppress** the new segment. 

**The Domino Effect:**
1. Hook Hunter locks onto a mediocre, early hook and suppresses the amazing hook that appears 5 seconds later.
2. The mediocre hook goes to Arc Assembler, which struggles to build a strong narrative because the setup was weak.
3. The resulting clip is sent to Evaluators (Groq Surgeon), which score it poorly or reject it entirely because it lacks punch.
4. The clip is discarded.
5. Because the *best* hook was suppressed early on, and the *accepted* hook failed, **zero clips survive the pipeline**.
6. The pipeline throws `RuntimeError: All clips failed to process` and telemetry reports zero Evidence packets because nothing made it to the final stage.

### The Fix: Cluster and Compare
Instead of locking onto the first acceptable hook, the architecture must:
1. **Cluster**: Group all hooks belonging to the same narrative arc together during the chronological pass.
2. **Compare**: Evaluate all candidates within that cluster internally against each other.
3. **Commit**: Only promote the *absolute strongest* hook from the cluster to a `StoryThread`.

## 2. Core Architectural Philosophy (The "No Premature Suppression" Rule)
Any system handling expensive LLM inference or subjective quality ranking must defer commitment. Information must either:
- Influence a downstream decision, or
- Be explicitly discarded with a logged reason.

Silent loss of intelligence (e.g., dropping a 0.95 hook just because a 0.45 hook appeared first) is a critical pipeline bug. Candidates must compete, not just survive a chronological gate.
