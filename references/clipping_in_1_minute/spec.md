# How to start clipping in less than 1 minute 🤔 _ai _aitools _clipping (MP4) (1)
Source: ref.mp4 | duration: 21.83s | fps: 30.0 | resolution: 576x1024 (h264)

## Global
- background: near-black (#070707 / #0a0a0a) | accent colours: #E6004D, #4ADE80, #FFE071
- fonts: Montserrat, Anton, Inter
- rhythm: avg word interval ~0.28s, target static gap <= 0.4s

## Motion vocabulary
- `WORD_POP`: spring, scale 0.7->1.15->1, damping 12, ~8 frames
- `CARD_FAN`: 3-card arc pop (left, center, right), spring damping 11, overshoot 1.15
- `PROOF_POP`: staggered bottom cards with subscriber / view badges (+34M, +18M, +12M)
- `PHONE_PUNCH_IN`: camera punch-in scale 1.0->1.25 on PhoneMock wrapper (bezel visible)
- `CURSOR_FLOW`: smooth fly-in, touch swipe down, tap with ripple + mech click SFX
- `WHIP_BLUR`: fast scene transition blur (frame 104-110, blur 0->18px)
- `CAROUSEL_GLIDE`: horizontal flex scroll showcasing 34 generated clips with active card expansion

## Words Transcript
```json
[
  {
    "text": "How",
    "start": 0.0,
    "end": 0.12
  },
  {
    "text": "to",
    "start": 0.12,
    "end": 0.22
  },
  {
    "text": "start",
    "start": 0.22,
    "end": 0.42
  },
  {
    "text": "clipping",
    "start": 0.42,
    "end": 0.7
  },
  {
    "text": "in",
    "start": 0.7,
    "end": 0.96
  },
  {
    "text": "less",
    "start": 0.96,
    "end": 1.14
  },
  {
    "text": "than",
    "start": 1.14,
    "end": 1.36
  },
  {
    "text": "one",
    "start": 1.36,
    "end": 1.56
  },
  {
    "text": "minute",
    "start": 1.56,
    "end": 1.72
  },
  {
    "text": "first,",
    "start": 1.72,
    "end": 2.1
  },
  {
    "text": "find",
    "start": 2.28,
    "end": 2.44
  },
  {
    "text": "a",
    "start": 2.44,
    "end": 2.56
  },
  {
    "text": "trending",
    "start": 2.56,
    "end": 2.84
  },
  {
    "text": "YouTube",
    "start": 2.84,
    "end": 3.16
  },
  {
    "text": "channel.",
    "start": 3.16,
    "end": 3.6
  },
  {
    "text": "Pick",
    "start": 3.72,
    "end": 3.78
  },
  {
    "text": "any",
    "start": 3.78,
    "end": 3.96
  },
  {
    "text": "video",
    "start": 3.96,
    "end": 4.28
  },
  {
    "text": "and",
    "start": 4.28,
    "end": 4.54
  },
  {
    "text": "copy",
    "start": 4.54,
    "end": 4.86
  },
  {
    "text": "its",
    "start": 4.86,
    "end": 5.08
  },
  {
    "text": "URL.",
    "start": 5.08,
    "end": 5.42
  },
  {
    "text": "Second,",
    "start": 5.82,
    "end": 6.04
  },
  {
    "text": "go",
    "start": 6.3,
    "end": 6.38
  },
  {
    "text": "to",
    "start": 6.38,
    "end": 6.54
  }
]
```

## Scenes (Grammar)
### S1 (0.0s - 3.33s) Viral Proof Hook
- principle: Pattern interrupt (cards pop on 0.15s, 0.35s, 0.55s), word-synced captions, authority proof badges
- layout: cards 3-25% H, word 48% H, avatar 55-100% H
- timeline:
  | t | element | action | ms | easing | trigger |
  | 0.00s | avatar | slide in upward | 300ms | spring | frame 3 |
  | 0.17s | card_left | pop in left tilt | 200ms | spring | word 'HOW' |
  | 0.37s | card_center | pop in center | 200ms | spring | word 'MAKE' |
  | 0.57s | card_right | pop in right tilt | 200ms | spring | word 'THESE' |
  | 2.13s | proof_cards | 3 cascading metric cards | 300ms | spring | word 'MILLIONS' |
- compare times: 0.5, 1.2, 2.5

### S2 (3.33s - 7.00s) Real YouTube Discovery
- principle: Show real process, tactile cursor interaction, credible proof
- layout: phone mock centered at 1080x1920 (width 870px), bezel visible
- timeline:
  | t | element | action | ms | easing | trigger |
  | 3.33s | phone | punch-in 1.0->1.03 | 600ms | easeInOut | cut |
  | 5.16s | video_card | tap card + ripple | 150ms | spring | frame 55 |
  | 6.16s | share_sheet | pop + tap copy link | 200ms | spring | frame 85 |
- compare times: 4.2, 5.5, 6.8

### S3 (7.00s - 19.43s) HotShort 34 Clips Glide & Jump Cuts
- principle: Reward, overwhelming value proof (34 clips), live video preview, clear CTA
- compare times: 8.5, 11.0, 14.5, 18.0
