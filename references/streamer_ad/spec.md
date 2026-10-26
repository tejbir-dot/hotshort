# streamer_ad (Reference #1)
Source: ref.mp4 | 32.9s | 30fps | 9:16 (576x1024 content, 720x1280 cover stream)
Note: timings are approximate (+-0.1s), read from 2fps and 10fps frame sheets. Audio was transcribed via Whisper into words.json.
Script (from on-screen words): "Here's how I make these viral streamer clips that generating millions of views ... go on YouTube, search, paste the link, create video ... this video ... [result] ... 'AI' https://remakeit.io/"
The reference promotes another product; we only copy the grammar. Do not use its brand name, avatar, or UI.

## Global
- background: near-black (#0a0a0a) with a very faint dark pattern; accent colours used sparingly (orange hex transition, cyan "AI" bubble)
- text: white, black-weight (900), heavy black stroke ~10-12px, one word at a time, fixed position between cards and avatar
- avatar: illustrated anime character, COLOUR (brown hair, white hoodie, VR headset), bottom-anchored
- rhythm: a visible change every ~0.2-0.4s in S1; every ~0.5-1s in S3-S4; no static gap > 0.5s
- phone mock: iPhone with rose-gold bezel, ~75-80% frame width; fake white arrow cursor added in post

## Motion vocabulary
- WORD_POP: spring, scale 0.7 -> 1.15 -> 1.0, ~8 frames, fires on word.start, replaces previous word
- CARD_DROP: centre card drops from above (spring overshoot), side cards tilt +-6deg
- COUNTER_TICK: view counter (e.g. "▷ 14.0M") ticks 0 -> ~84M, steps ~2M then ~5M, ease-in, on all 3 cards
- AVATAR_SLIDE_UP: ~6 frames from below; mouth sprite changes every ~100ms while speaking
- CARD_FLING: cards rotate and exit up/left in ~6 frames
- CARD_STACK: one card added per word (1 -> 2 -> 3), "Pinned" badge, slight tilt
- PHONE_RISE: phone slides up with spring, scale 0.92 -> 1
- FEED_SCROLL: vertical scroll with inertia (ease-out)
- CURSOR_CLICK: bezier path 400-700ms, click = scale 1 -> 0.85 -> 1 + ripple
- PUNCH_IN: camera zoom 1.0 -> ~1.6-2.2 toward the active region on every UI step
- STICKER_POP: PNG sticker with white outline, rotate -20 -> 0 with spring, over orange hex bg
- RESULT_BOUNCE: result phone frame scales/rotates slightly on every caption change
- CAPTION_HIGHLIGHT: small white caption, ONE word in yellow
- GLITCH_SLICE: horizontal strips displaced 3-5 frames at scene cuts inside result clip
- BUBBLE_POP: scale 0.3 -> 1.05 -> 1, from its own side; bubbles slide out right at the end
- WARP_GRID_BG: black bg + white grid lines displaced by sin waves

## Scenes
### S1 Hook (0.0-2.3s)
- principle: pattern interrupt + proof (view counters) + talking avatar
- layout: cards 3-25% H, word ~48% H, avatar 52-100% H
- timeline:
  | 0.00-0.30 | first word "HERE'S" | WORD_POP | 250ms | spring | word.start |
  | 0.10-0.30 | avatar | AVATAR_SLIDE_UP | 200ms | spring | beat |
  | 0.10-0.40 | centre card + 2 side cards | CARD_DROP | 300ms | spring | beat |
  | 0.20-2.0  | counters | COUNTER_TICK 0 -> 84M | 1.8s | ease-in | continuous |
  | every ~0.25s | next word (HOW, I, MAKE, THESE, VIRAL, STREAMER, CLIPS) | WORD_POP | 250ms | spring | word.start |
- compare times: 0.3, 1.0, 1.7

### S2 Stack (2.0-4.0s)
- principle: proof escalates (more cards = more views)
- timeline:
  | 2.0-2.3 | all cards | CARD_FLING | 300ms | ease-in | beat |
  | 2.0 | word "THAT" alone, avatar gone | WORD_POP | | | |
  | 2.5-3.5 | words GENERATING / MILLIONS / VIEWS, one card added per word | CARD_STACK | | spring | word.start |
- compare times: 2.2, 2.8, 3.4

### S3 YouTube browse (4.0-8.0s) [no captions, voiceover only]
- principle: show the real process; believability from a real recording
- timeline:
  | 4.0-4.3 | phone | PHONE_RISE | | spring | beat |
  | 4.3-5.5 | YouTube feed | FEED_SCROLL | | ease-out | |
  | 5.5-6.5 | cursor to a thumbnail, tap | CURSOR_CLICK | 500ms | bezier | |
  | 6.5-8.0 | share sheet up, cursor to "Copy link", PUNCH_IN | PUNCH_IN | | spring | |
- compare times: 4.5, 5.8, 7.0

### S4 Tool demo (8.0-19.0s) [no captions]
- principle: show 3 simple steps (paste, analyze, choose, create)
- timeline: type in search -> paste link -> Analyze -> dropdowns -> Create video; every step PUNCH_IN + CURSOR_CLICK
- compare times: 9.0, 12.0, 15.0, 18.0

### S5 Transition (18.3-19.5s)
- orange hex bg, STICKER_POP hand then watch ("00:29" = "in 29 seconds"), avatar peeks from below, words "VIDEO", "THIS"
- compare times: 18.6, 19.1

### S6 Result demo (19.5-29.0s)
- principle: payoff; the output is the proof
- layout: result phone ~70% frame width, rounded white frame, blurred 9:16 bg
- timeline: RESULT_BOUNCE on every caption change; CAPTION_HIGHLIGHT; GLITCH_SLICE at clip cuts (~25.3s, ~26.4s)
- compare times: 21.0, 24.0, 26.0

### S7 Outro (29.0-32.9s)
- timeline:
  | 29.0-29.5 | orange WARP_GRID_BG flash | | | | |
  | 29.5 | cyan bubble "AI" | BUBBLE_POP from right | | spring | |
  | 30.5 | white bubble "https://..." | BUBBLE_POP from left | | spring | |
  | 32.6 | both bubbles | slide out right | | ease-in | |
- compare times: 29.7, 31.0, 32.5

## Our adaptation (HotShort)
- Replace the product with HotShort UI recordings (real screen recordings, DPR 3).
- Replace the CTA bubbles with a "Comment AI" card (already built).
- Avatar: colour version of our character. Brand colours stay secondary to near-black bg.
