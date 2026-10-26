# HotShort Engineering Rules

## No Premature Suppression Before Comparison
Any information produced by an expensive LLM call (like Hook Hunter's Groq triggers) must either (1) influence a downstream decision, or (2) be explicitly discarded with a logged reason. Silent loss of LLM-generated intelligence is a bug.

Never use a "first-acceptable-wins" architecture when multiple candidates share an arc. Always cluster candidates, compare their strengths internally using all available signals (heuristics + psychology), and ONLY commit (e.g. to a StoryThread) AFTER selecting the absolute strongest candidate. Early locking causes chronological shadowing and suppresses high-quality signals.

## Reference Master Protocol (Video Engineering & Ad Creation)
Whenever building, modifying, or testing any marketing ad, hook, or motion graphic inspired by a reference video, you MUST strictly follow the protocol in `REFERENCE_MASTER.md`:
- Follow the loop: DECODE -> EXTRACT PRINCIPLES -> BUILD (thin slice) -> COMPARE -> DIAGNOSE -> FIX -> VERIFY -> POLISH.
- Never guess or approximate without evidence.
- Every animation must fire on a spoken word or beat (pattern interrupt every 0.2-0.4s).
- Verify every change with visual frame evidence using `tools/compare.py`.
- Adhere strictly to the 14 Known Pitfalls in `REFERENCE_MASTER.md`.

