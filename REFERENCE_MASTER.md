# REFERENCE MASTER
How to learn from a reference video, rebuild its motion language with our Remotion
engine, compare against the original, and polish until it passes.

Put this file at the repo root (or in .cursor/rules / AGENTS.md). Read it fully
before ANY task that mentions a reference video. If a task conflicts with this
file, say so and ask. Do not skip phases.

---------------------------------------------------------------------------
## 0. MISSION AND NON-GOALS

Mission: learn the GRAMMAR of a reference (timing, rhythm, layout, motion
vocabulary, proof devices) and re-express it with NEW content, so the output
is unique but feels the same.

Non-goals:
- Do not copy pixels, brand assets, logos, or a real person's likeness.
- Do not "approximately" match. Either a check passes with evidence or it fails.
- Do not say "done" without frames you have actually looked at.

Core belief: a video feels good because EVERY animation fires on a spoken word
or a beat, and something changes on screen every 0.2-0.4s (pattern interrupt).

---------------------------------------------------------------------------
## 1. THE LOOP (never skip a phase)

DECODE -> EXTRACT PRINCIPLES -> BUILD (thin slice) -> COMPARE -> DIAGNOSE -> FIX -> VERIFY -> POLISH

One scene, one fix per round. Smallest vertical slice first (3 seconds), then widen.

---------------------------------------------------------------------------
## 2. PHASE 1 - DECODE THE REFERENCE (no code yet)

Output: references/<name>/spec.md (template in section 9) + frames/ folder.

Steps:
1. Probe: `ffprobe -v error -show_entries stream=codec_type,width,height,r_frame_rate,duration -of default=nw=1 ref.mp4`
2. Overview sheets (2 fps, 8 per row), one sheet per ~8 seconds:
   `ffmpeg -ss S -t 8 -i ref.mp4 -map 0:v:0 -vf "fps=2,scale=240:-1,tile=8x2" sheetN.jpg`
3. Dense sheets (10 fps) for any segment with fast motion (hooks, transitions):
   `ffmpeg -ss S -t 2.4 -i ref.mp4 -map 0:v:0 -vf "fps=10,scale=200:-1,tile=8x3" fineN.jpg`
4. Full-res stills at every key moment: `ffmpeg -ss T -i ref.mp4 -frames:v 1 -update 1 frames/t_T.jpg`
5. Transcript with WORD timestamps (WhisperX or faster-whisper). Save words.json.
   If the reference has on-screen words, those are the script; note them.
6. Scene segmentation: list scene boundaries with timestamps (PySceneDetect or by eye).
7. For EACH scene write an EVENT TIMELINE (one line per event):
   `t_start | element | action | duration_ms | easing guess | trigger (word/beat/none)`
   Example: `0.10s | word "HERE'S" | pop scale 0.7->1.15->1 | 250ms | spring | word.start`
8. LAYER INVENTORY per scene: background, hero element, text, props, UI, overlays.
9. LAYOUT GRID: where each layer sits as % of frame height/width
   (e.g. cards 3-25% H, word 48% H, avatar 55-100% H).
10. MOTION VOCABULARY: give every recurring motion a NAME and parameters.
    Example: `WORD_POP`, `CARD_DROP`, `COUNTER_TICK`, `PUNCH_IN`, `WHIP_BLUR`,
    `GLITCH_SLICE`, `CURSOR_CLICK`, `BUBBLE_POP`.
11. RHYTHM STATS: average seconds between visible changes, longest static gap,
    cut frequency. These become lint rules.
12. AUDIO MAP: where the voice, music, and sfx hits fall.

Rule: do not guess what you cannot see. If a detail is unclear at 2 fps, extract
10 fps. If still unclear, write "UNKNOWN" in the spec; do not invent.

---------------------------------------------------------------------------
## 3. PHASE 2 - EXTRACT PRINCIPLES (the "why")

For each scene write 1-3 lines: why does this work on a viewer?
Typical answers (use only if true for this reference):
- Pattern interrupt: something new every 0.2-0.4s.
- Word-sync: motion fires on word.start, never on a hand-picked frame.
- Proof device: counters, view numbers, "34 clips" badges show results, not claims.
- Show the process: real screen recording + cursor + zoom makes it believable.
- Contrast: bright foreground on near-black background; one accent colour.
- Reward/curiosity: result shown fast, link/CTA at the end.

These principles decide what to KEEP when we change the content.
Unique content, same principles.

---------------------------------------------------------------------------
## 4. PHASE 3 - BUILD (Remotion)

- One component per named motion/scene. Props come from JSON, not hardcoded.
- All timing derives from `word.start` or a named beat. No magic frame numbers
  in scene code; put them in the timeline JSON.
- Use spring() for entrances, easeInOut for camera, never linear.
- ZOOM RULE: apply scale/translate to the OUTERMOST wrapper that contains the whole
  PhoneMock (bezel + screen). Never scale the inner screen on its own.
- Real UI = real screen recording (Playwright, deviceScaleFactor 3), not a hand-built
  fake. Overlays (cursor, ripple, zoom, badges) are added in Remotion.
- Keep PhoneMock the same size/position across steps of one scene.
- Output renders to a NEW filename each round (v1, v2, ...) and print `ls -l`.
  Same hash as the previous render = the render did not happen.
- Build a thin slice first: 3 seconds of one scene, show frames, then continue.

---------------------------------------------------------------------------
## 5. PHASE 4 - COMPARE (evidence, not opinion)

Tool: tools/compare.py
`python tools/compare.py --ref references/<name>/ref.mp4 --render out_vN.mp4 --times 0.5,1.2,2.5,4,8`
Writes compare_out/compare_<t>.jpg (reference LEFT, render RIGHT, same height,
timestamp stamped) and compare_out/sheet.jpg.

Procedure:
1. Render, then run compare.py at the timestamps listed in spec.md for that scene.
2. LOOK at every compare image (open the file). Do not infer from code.
3. Fill the RUBRIC (section 7) per frame with yes/no and one-line evidence.
4. Anything "no" becomes a fix item. Anything "unsure" is a "no".

Optional automation: tools/critic.py sends each ref/render pair plus the rubric to a
vision model and returns JSON {frame, check, pass, issue, fix_hint}. The critic
suggests; evidence (the image) decides. Max 3 automatic rounds, then ask a human.

---------------------------------------------------------------------------
## 6. PHASE 5 - DIAGNOSE BEFORE FIXING (for any bug)

Do not edit until step 4.
1. FIND: grep the relevant code (transform, scale, zoom, interpolate, spring).
   List file:line for each hit.
2. TRACE: write the component tree from scene root to the visible element. For each
   level: transform? overflow? width/height? transformOrigin?
3. REPRODUCE: render stills at the failing frames and describe what you see.
4. REPORT: root cause (file:line), why it happens, planned change. Then proceed.
5. FIX: smallest change that removes the root cause. One fix per round.
6. VERIFY: re-render the same stills, answer the same checks.
7. REGRESSION: re-check previously passing frames from earlier rounds.

---------------------------------------------------------------------------
## 7. RUBRIC (score each frame; all measurable)

STRUCTURE (20)
- scene order and beats match spec.md
- no dead frames (black/empty) longer than 3 frames
TIMING (25)
- every animation starts within +-2 frames of its trigger word/beat
- longest static gap <= 0.4s (spec rhythm stats)
- scene length within +-10% of the target
LAYOUT (15)
- each layer inside its grid zone from spec.md (+-3% of frame height)
- nothing overlaps a status bar, notch, or other UI it should not cover
- no text clipped at any edge
MOTION (20)
- named motions use the specified easing/overshoot
- zoom keeps the phone bezel visible on >= 2 sides
- cursor path is smooth and lands on the target before the click
TYPOGRAPHY (10)
- weight/stroke/size match spec; one word at a time where specified
- caption layers visible at once: exactly 1 (unless spec says 2)
COLOUR AND TEXTURE (10)
- background per spec (near-black, no unplanned gradients/tints)
- avatar in specified colour mode
- one accent colour used consistently

Pass = every check yes. Score is for tracking progress, not for shipping.

---------------------------------------------------------------------------
## 8. POLISH ORDER (always this order, one item per round)

structure -> timing -> layout -> motion -> typography -> colour -> texture/grain.
Never polish colour while timing is wrong.

Variation for "unique" outputs (apply AFTER the match passes):
- parameter jitter: fan angle +-3deg, spring damping +-2, pop scale 1.10-1.18
- swap assets (thumbnails, clips, numbers, bg variant)
- reorder beats only where the story allows

---------------------------------------------------------------------------
## 9. TEMPLATES

### spec.md template (one per reference)
```
# <name>
Source: ref.mp4 | duration | fps | resolution
## Global
- background: ... | accent colours: ... | fonts: ... | avatar: ...
- rhythm: avg change interval Xs, longest static gap Ys
## Motion vocabulary
- WORD_POP: spring, scale 0.7->1.15->1, damping 12, 8 frames
- ...
## Scenes
### S1 (0.0-2.3s) Hook
- principle: ...
- layout: cards 3-25% H, word 48% H, avatar 55-100% H
- timeline:
  | t | element | action | ms | easing | trigger |
- compare times: 0.5, 1.2, 2.0
- checks: (copy relevant rubric lines)
```

### round report (agent replies with this every round)
```
ROUND N | file: output/<name>_vN.mp4 | ls -l: <size, time> | hash differs from N-1: yes/no
Fix attempted: <one item>
Frames checked: <t1,t2,...> (compare images: <paths>)
Per frame: <t> | check | yes/no | evidence
Regressions: none / <list>
Next item: <one item>
```

---------------------------------------------------------------------------
## 10. KNOWN PITFALLS (learned on this project; check them every time)

1. Zoom applied to the inner screen -> bezel disappears, text clipped. Zoom the PhoneMock wrapper.
2. Recording at low DPR -> blurry zoomed text. Record at deviceScaleFactor 3.
3. Dead start: empty/black frames or an idle cursor at t=0. Trim the recording.
4. A status badge placed over the notch/status bar or over UI. Put badges outside the phone.
5. Clips with two caption layers (top block + word-by-word). Use clips with one.
6. Cropping/zooming a clip to hide something cuts its captions at the edges. Use native 9:16, scale 1.
7. Ad or unrelated UI visible inside a real recording (e.g. a YouTube ad). Re-record or pick another video.
8. Avatar greyscale/desaturated -> alphamerge took colour from the mask. Colour from the source, alpha from the mask (gray).
9. Unplanned purple/colourful background gradients. Spec says near-black.
10. Same file hash as last render -> render did not happen / wrong output path.
11. Black bands inside card previews -> object-fit: cover, 9:16 sources.
12. Profanity in captions, unverifiable stats ("20M+ hours"), and real people's names/likeness in paid ads. Flag and avoid.
13. Doing 5 fixes in one round. One fix per round.
14. Claiming done from reading code. Evidence = frames you opened.

---------------------------------------------------------------------------
## 11. HOW TO ADD A NEW REFERENCE

1. mkdir references/<name>; put ref.mp4 there.
2. Run tools/ref_analyzer.py (cuts, words, OCR, motion spikes, contact sheets) if present.
3. Do Phase 1 and 2, fill spec.md. Ask the human to confirm UNKNOWN items.
4. Build the thin slice (first 3 s), compare, fix, then widen.
5. Only after one reference is at 90%+, extract reusable components into the library
   and move scene props into JSON (plan.json) for the director.
