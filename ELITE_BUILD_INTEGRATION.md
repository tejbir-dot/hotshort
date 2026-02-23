# 🎬 ELITE BUILD INTEGRATION GUIDE

## Architecture Overview

This implementation follows the **elite build principle**: Backend decides intelligence, frontend renders explanations.

### Data Flow

```
Ultron Analysis → ClipBuilder → ViralClip Objects → Frontend JSON → Smart UI
```

## Quick Start

### 1. **Update Your Clip Generation Route**

In `app.py`, modify your clip generation endpoint to use the new builder:

```python
from utils.clip_builder import build_clips_from_analysis
from utils.clip_schema import clip_to_dict
import json

@app.route("/results/<job_id>")
def results(job_id):
    # 1. Get your raw analysis from ultron/viral_finder
    raw_analysis = find_viral_moments(youtube_url)  # Your existing code
    
    # 2. Transform to ViralClip objects
    clips = build_clips_from_analysis(
        analysis_results=raw_analysis,
        source_video="/path/to/downloaded/video.mp4",
        full_transcript="Full transcript text..."
    )
    
    # 3. Convert to JSON for frontend
    clips_json = json.dumps([clip_to_dict(c) for c in clips])
    
    # 4. Render template with data
    return render_template(
        "results_new.html",
        clips_json=clips_json
    )
```

### 2. **Update Your Template**

In `results_new.html`, inject the clip data:

```html
<script>
  window.CLIPS_DATA = {{ clips_json | safe }};
</script>
```

### 3. **Key Components**

#### `utils/clip_schema.py`
- `ViralClip` dataclass: The canonical clip structure
- `create_viral_clip()`: Factory to build clips
- `SelectionReason`: Explains why the clip was selected

#### `utils/clip_builder.py`
- `ClipBuilder`: Transforms raw analysis into intelligent clips
- `build_clips_from_analysis()`: Batch processor

#### `utils/platform_variants.py`
- `PlatformVariantGenerator`: Creates YouTube/Instagram/TikTok versions
- `generate_platform_variants()`: Convenience function

#### `routes/clips.py`
- API endpoints for fetching clips, downloading variants, viewing transcripts

#### `templates/results_new.html`
- New confidence-first UI
- Carousel with smart badges
- Details panel showing reasoning
- Platform-aware download menu

---

## Data Contract Reference

### ViralClip Structure

```python
{
  "clip_id": "clip_1",                          # Unique ID
  "title": "Most people learn coding wrong",    # Hook text (~60 chars)
  "clip_url": "/static/outputs/clip_1_main.mp4", # Main video
  
  "platform_variants": {
    "youtube_shorts": "/static/outputs/clip_1_youtube.mp4",
    "instagram_reels": "/static/outputs/clip_1_instagram.mp4",
    "tiktok": "/static/outputs/clip_1_tiktok.mp4"
  },
  
  "hook_type": "Contradiction",                 # "Contradiction", "Question", etc.
  "confidence": 82,                             # 0-100, derived score
  
  "scores": {
    "hook": 0.90,          # 0-1: How strong the hook
    "retention": 0.82,     # 0-1: Audience retention potential
    "clarity": 0.78,       # 0-1: Message clarity
    "emotion": 0.70        # 0-1: Emotional impact
  },
  
  "selection_reason": {
    "primary": "Strong contradiction in first 2.1 seconds",
    "secondary": "High retention spike after hook",
    "risk": "Appeals mainly to beginners"
  },
  
  "why": [
    "Interrupts scrolling with disagreement",
    "Aligns with beginner frustration",
    "Clear promise early in the clip"
  ],
  
  "rank": 1,              # Position in carousel (1-indexed)
  "is_best": true,        # Is this the best clip?
  "transcript": "Full text...",
  
  "start_time": 45.2,     # Seconds in original video
  "end_time": 60.5,
  "duration": 15.3
}
```

---

## Frontend Features

### 1. **Confidence Bar**
```
Shows numeric confidence (0-100) with visual bar
Based on: hook(40%) + retention(35%) + clarity(15%) + emotion(10%)
```

### 2. **Smart Badges**
```
🏆 Best Pick       → is_best === true
🔥 High Confidence → confidence > 80
⚡ Pattern Break    → hook_type === "Contradiction"
```

### 3. **Details Panel**
When user clicks "View Reasons":
- Shows selection reasoning (primary + secondary + risk)
- Displays why bullets (3-5 items explaining virality)
- Shows score breakdown (hook, retention, clarity, emotion)

### 4. **Platform Download**
Download button opens menu with:
- YouTube Shorts (9:16)
- Instagram Reels (9:16)
- TikTok (9:16)

### 5. **Carousel**
- Smooth horizontal scroll
- Best clip emphasizes with scale + glow
- Hover plays video preview
- Click "View Reasons" shows intelligence

---

## Customization

### Add More Hook Types

In `utils/clip_builder.py`, add to `HOOK_PATTERNS`:

```python
HOOK_PATTERNS = {
    "My New Type": [
        r"pattern1",
        r"pattern2",
    ],
    # ... existing types
}
```

### Adjust Confidence Weighting

In `utils/clip_schema.py`, modify `create_viral_clip()`:

```python
confidence = int(
    (hook_score * 0.40 +      # ← Adjust these weights
     retention_score * 0.35 +
     clarity_score * 0.15 +
     emotion_score * 0.10) * 100
)
```

### Add Platform Variants

In `utils/platform_variants.py`:

```python
def _generate_youtube_long(self, ...):
    # Your custom variant logic
    pass

# Register in generate_all_variants()
variants["youtube_long"] = self._generate_youtube_long(...)
```

### Customize UI Colors

In `templates/results_new.html`, modify CSS variables:

```css
:root {
  --gold-100: #ffcf80;        /* Primary accent */
  --gold-200: #ffb347;        /* Secondary accent */
  --accent-success: #4ade80;  /* High confidence */
  --accent-warn: #fbbf24;     /* Pattern break */
}
```

---

## Integration Checklist

- [ ] Import `build_clips_from_analysis` and `clip_to_dict` in your route
- [ ] Update your clip generation logic to create ViralClip objects
- [ ] Convert clips to JSON and pass to template
- [ ] Update template to use `window.CLIPS_DATA`
- [ ] Test platform variant generation (needs FFmpeg)
- [ ] Verify download URLs work
- [ ] Test confidence bar rendering
- [ ] Test badge logic
- [ ] Test details panel
- [ ] Test responsive design on mobile

---

## FAQ

**Q: Where do hook_score, retention_score, etc. come from?**
A: Your existing Ultron/viral_finder analysis. The ClipBuilder takes raw analysis and enriches it.

**Q: Do I need to re-encode videos for variants?**
A: No! We use FFmpeg stream copy (10-100x faster). No quality loss.

**Q: Can I customize the "why" bullets?**
A: Yes! Modify `ClipBuilder.generate_why_bullets()` in `clip_builder.py`.

**Q: How do I add a new platform?**
A: Add a method to `PlatformVariantGenerator`, register in `generate_all_variants()`, add to UI labels in frontend.

**Q: What if a variant fails to generate?**
A: It's skipped and omitted from platform_variants. Frontend handles gracefully.

---

## Success Metrics

When done correctly, users should say:

> "I understand why this clip was chosen, where to post it, and how confident the system is."

That's the definition of intelligent AI UX. ✨
