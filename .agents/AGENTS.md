# HotShort Engineering Rules

## No Premature Suppression Before Comparison
Any information produced by an expensive LLM call (like Hook Hunter's Groq triggers) must either (1) influence a downstream decision, or (2) be explicitly discarded with a logged reason. Silent loss of LLM-generated intelligence is a bug.

Never use a "first-acceptable-wins" architecture when multiple candidates share an arc. Always cluster candidates, compare their strengths internally using all available signals (heuristics + psychology), and ONLY commit (e.g. to a StoryThread) AFTER selecting the absolute strongest candidate. Early locking causes chronological shadowing and suppresses high-quality signals.
