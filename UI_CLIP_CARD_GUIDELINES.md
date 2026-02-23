Core UI Principle — Clip Card Guidelines

Goal: "Feels like an experienced editor already watched the video for you." Keep the UI calm, minimal, and decision-focused.

1) Clip Card (Top-level, glanceable)
- Top row (glance):
  - Duration (e.g. "⏱ 12.6s")
  - One badge: either "🔥 Payoff" or "🧠 Insight" (mutually exclusive)
  - Thin confidence bar (visual only; no numeric label)
- Middle (one line):
  - Hook line: first sentence, smart-truncated to one line with ellipsis
- Bottom (micro signals, icon + label):
  - Curiosity: short glyph with 1–3 chevrons (▲▲▲)
  - Payoff: check glyph when detected
  - Clean ending: mark if sentence-complete
- No numbers on the card unless hovered.

2) Replace Scores with Badges
- Map internal signals to human labels (badge text):
  - High curiosity slope -> "Hooked Fast"
  - Sustained curiosity -> "Keeps You Watching"
  - Payoff detected -> "Satisfying End"
  - High semantic density -> "Insight Drop"
  - Rejected payoff -> "Setup Only" (greyed)

3) Curiosity Timeline (hover/expand only)
- Show a single thin curve, no axes, no numbers
- One dot labeled Peak, one dot labeled Payoff

4) "Why this clip?" (one calm sentence)
- Auto-generate one sentence per clip that maps internal signals to plain language:
  - Examples: "Curiosity rises quickly and resolves with a clear insight." / "Strong setup, but no satisfying payoff detected."

5) Rejected Clips = Quiet, Not Error
- Display as greyed card with label: "Not Finished Thought"
- Tooltip: "Good setup, but ending doesn’t resolve yet."

6) Single Toggle: Editor Mode
- Top-right switch: `Editor Mode` (OFF = default)
  - OFF: show only best clips, no explanations
  - ON: show rejected clips + "why" + curiosity curve

7) Micro-interaction polish (simple, high ROI)
- Slide-in cards (not pop)
- Payoff badge appears after 300ms (deliberate)
- Hover highlights the ending sentence (not start)

What NOT to add yet
- No numeric confidence on cards
- No filters, sorting, charts panel, or a settings page

Design intent: the UI should show decisions, not mechanics. Badges and a single-line "why" teach creators without overwhelming them.

Implementation notes
- Backend should supply per-clip: `start,end,duration,primary_badge,confidence(0..1),hook_line,last_sentence,closure_marker,curiosity_curve(cheap compressed)`
- UI uses `confidence` only to render the thin bar; text and badges map from booleans/thresholds.

File: UI_CLIP_CARD_GUIDELINES.md
