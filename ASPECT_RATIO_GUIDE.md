# 📐 Aspect Ratio Support Guide

## Overview
Your video clip generator now supports **multi-platform aspect ratios** with intelligent padding. Generate clips optimized for:
- 📱 **TikTok** (9:16 vertical)
- 📱 **Instagram Reels** (9:16 vertical)  
- 📺 **YouTube** (16:9 horizontal)
- ⬜ **Instagram Feed** (1:1 square)
- 🎬 **Ultra-wide** (21:9 cinematic)
- 📽️ **Classic** (4:3)
- 📹 **Native** (Original aspect ratio)

---

## Backend Implementation

### New Functions Added

#### 1. `_apply_aspect_ratio(input_path, output_path, aspect_ratio, padding_color)`
Converts video to target aspect ratio using FFmpeg padding.

**Parameters:**
- `input_path` (str): Source video file
- `output_path` (str): Destination video file  
- `aspect_ratio` (str): Target ratio ("16:9", "9:16", "1:1", "4:3", "21:9")
- `padding_color` (str): Padding color ("black", "white", "blur", "transparent")

**Returns:** `bool` - True if successful

**Example:**
```python
success = _apply_aspect_ratio(
    "clip.mp4", 
    "clip_vertical.mp4", 
    "9:16", 
    "black"
)
```

**How it works:**
- Uses FFmpeg's `scale` + `pad` filters
- Preserves original aspect ratio without distortion
- Adds black bars (letterbox) as needed
- Fast processing: ~5-10 seconds per clip

---

### Updated Endpoint

#### `POST /analyze`
Now accepts aspect ratio parameters:

**New Form Parameters:**
```
youtube_url: "https://youtube.com/watch?v=..."  (required)
ratio: "9:16"                                    (optional, default: "16:9")
padding_color: "black"                           (optional, default: "black")
```

**Supported Ratios:**
| Ratio | Label | Best For |
|-------|-------|----------|
| `16:9` | YouTube/Desktop | YouTube, Desktop, Web |
| `9:16` | TikTok/Reels | TikTok, Instagram Reels, YouTube Shorts |
| `1:1` | Instagram Feed | Instagram Feed, Twitter, Pinterest |
| `4:3` | Classic | Older video formats |
| `21:9` | Ultra-wide | Cinematic, ultra-wide displays |
| `native` | Native | Keep original aspect ratio |

**Padding Colors:**
- `black` - Professional, most compatible
- `white` - Clean, high contrast
- `blur` - Blur background (smart choice)
- `transparent` - No padding (crop if needed)

**Example cURL Request:**
```bash
curl -X POST http://localhost:5000/analyze \
  -F "youtube_url=https://youtube.com/watch?v=VIDEO_ID" \
  -F "ratio=9:16" \
  -F "padding_color=black"
```

**Response:**
```json
[
  {
    "title": "Viral Moment #0",
    "clip_url": "/static/outputs/clip_0_23.4_49.8.mp4",
    "job_id": 123,
    "start": 23.4,
    "end": 49.8,
    "score": 0.87,
    "ratio": "9:16"
  },
  ...
]
```

---

## Frontend Integration

### Option 1: Using the Aspect Ratio Selector Component

**HTML:**
```html
<script src="/static/js/aspect-ratio-selector.js"></script>

<form id="analyzeForm" method="POST" action="/analyze">
    <input type="text" name="youtube_url" placeholder="YouTube URL" required>
    
    <!-- Insert aspect ratio selector -->
    <div id="ratioContainer"></div>
    
    <button type="submit">Analyze & Generate Clips</button>
</form>

<script>
    // Add aspect ratio selector to form
    const selector = window.AspectRatioSelector.create();
    document.getElementById("ratioContainer").appendChild(selector);
    
    // Inject ratio data before form submission
    document.getElementById("analyzeForm").addEventListener("submit", (e) => {
        window.AspectRatioSelector.injectToForm(e.target);
    });
</script>
```

**Styles Included:**
- Responsive button grid
- Visual previews of each aspect ratio
- Modern gradient design
- Mobile-friendly layout

### Option 2: Manual Form Fields

```html
<form method="POST" action="/analyze">
    <input type="text" name="youtube_url" required>
    
    <label>Aspect Ratio:</label>
    <select name="ratio">
        <option value="16:9">YouTube/Desktop (16:9)</option>
        <option value="9:16" selected>TikTok/Instagram (9:16)</option>
        <option value="1:1">Instagram Feed (1:1)</option>
        <option value="4:3">Classic (4:3)</option>
        <option value="21:9">Ultra-wide (21:9)</option>
        <option value="native">Native (Original)</option>
    </select>
    
    <label>Padding Color:</label>
    <select name="padding_color">
        <option value="black" selected>Black</option>
        <option value="white">White</option>
        <option value="blur">Blur</option>
    </select>
    
    <button type="submit">Generate Clips</button>
</form>
```

---

## Performance

### Processing Time
- **Clip Extraction** (FFmpeg stream copy): 0.5-2 seconds per clip
- **Aspect Ratio Conversion**: 5-15 seconds per clip (fast preset)
- **Total for 4 clips**: ~20-40 seconds (with ratio conversion)

### Optimization Notes
- Aspect ratio conversion runs **sequentially** after clip extraction
- Can be parallelized further if needed (see "Advanced" section)
- Padding with black is fastest; blur requires additional processing

### Quality Settings
```python
# Current settings in _apply_aspect_ratio():
-preset veryfast  # Fast encoding (2-5x faster than default)
-crf 23          # Quality level (0=lossless, 51=worst, 28=default)
-b:a 128k        # Audio bitrate (sufficient for social media)
```

To increase quality (slower):
```python
"-preset", "fast",      # or "medium" for higher quality
"-crf", "20",          # Lower number = higher quality
```

---

## Advanced Usage

### 1. Parallel Aspect Ratio Conversion (Future Enhancement)

```python
# Modify analyze_video() to process ratios in parallel:
from concurrent.futures import ThreadPoolExecutor, as_completed

with ThreadPoolExecutor(max_workers=2) as ratio_executor:
    ratio_futures = {}
    for idx, abs_path in enumerate(generated_clips):
        future = ratio_executor.submit(
            _apply_aspect_ratio, 
            abs_path, 
            abs_path.replace(".mp4", f"_{aspect_ratio}.mp4"),
            aspect_ratio,
            padding_color
        )
        ratio_futures[future] = abs_path
    
    for future in as_completed(ratio_futures):
        abs_path = ratio_futures[future]
        try:
            if future.result():
                print(f"[RATIO ✅] {abs_path}")
        except Exception as e:
            print(f"[RATIO ⚠️] {e}")
```

### 2. Custom Aspect Ratios

Add to `_apply_aspect_ratio()`:
```python
ratio_configs = {
    "16:9": {"w": 1920, "h": 1080},
    "9:16": {"w": 1080, "h": 1920},
    # Add custom ratios:
    "5:4": {"w": 1280, "h": 1024},
    "2.35:1": {"w": 2560, "h": 1090},
}
```

### 3. Smart Padding (Blur Background)

FFmpeg filter for blurred padding:
```bash
ffmpeg -i input.mp4 \
  -vf "scale=1080:1920:force_original_aspect_ratio=decrease,
        [scaled]pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black,
        [scaled]boxblur=10:2" \
  output.mp4
```

---

## Troubleshooting

### Issue: Aspect ratio not applied
**Solution:**
1. Ensure FFmpeg is installed: `ffmpeg -version`
2. Check file permissions in output directory
3. Verify disk space available

### Issue: Slow processing with aspect ratio
**Solution:**
1. Use `preset=veryfast` (default) for speed
2. Reduce quality (increase `crf` value)
3. Process ratios in parallel (see Advanced)

### Issue: Black bars look bad
**Solution:**
1. Try `padding_color=white` or `blur`
2. Use crop instead of pad (loses video content)
3. Let user choose padding color

---

## Testing

### Test URLs
```bash
# TikTok format
curl -X POST http://localhost:5000/analyze \
  -F "youtube_url=https://youtube.com/watch?v=dQw4w9WgXcQ" \
  -F "ratio=9:16" \
  -F "padding_color=black"

# Instagram square
curl -X POST http://localhost:5000/analyze \
  -F "youtube_url=https://youtube.com/watch?v=dQw4w9WgXcQ" \
  -F "ratio=1:1" \
  -F "padding_color=white"

# YouTube 16:9
curl -X POST http://localhost:5000/analyze \
  -F "youtube_url=https://youtube.com/watch?v=dQw4w9WgXcQ" \
  -F "ratio=16:9"
```

### Expected Behavior
1. Video downloads
2. Clips are extracted (18-50 seconds each, variable)
3. Each clip is converted to target aspect ratio
4. Padding applied with specified color
5. JSON response includes `ratio` field

---

## Recommended Aspect Ratios by Platform

| Platform | Ratio | Width | Height | Notes |
|----------|-------|-------|--------|-------|
| TikTok | 9:16 | 1080px | 1920px | Vertical, fills screen |
| Instagram Reels | 9:16 | 1080px | 1920px | Same as TikTok |
| YouTube Shorts | 9:16 | 1080px | 1920px | Vertical format |
| Instagram Feed | 1:1 | 1080px | 1080px | Square, thumbnail |
| YouTube | 16:9 | 1920px | 1080px | Standard HD |
| Twitter/X | 16:9 | 1200px | 675px | Landscape |
| Pinterest | 4:5 | 1000px | 1250px | Tall portrait |
| Facebook | 16:9 | 1200px | 675px | Landscape |

---

## Database Schema Update (if needed)

Add aspect ratio field to `Clip` model:

```python
# models/clip.py
class Clip(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255))
    file_path = db.Column(db.String(500))
    aspect_ratio = db.Column(db.String(20), default="16:9")  # NEW
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
```

Migration:
```python
# migrations/versions/xxxxx_add_aspect_ratio.py
def upgrade():
    op.add_column('clip', sa.Column('aspect_ratio', sa.String(20), nullable=True))

def downgrade():
    op.drop_column('clip', 'aspect_ratio')
```

Then run:
```bash
flask db upgrade
```

---

## Summary

✅ **What's Implemented:**
- `_apply_aspect_ratio()` function for FFmpeg processing
- Updated `/analyze` endpoint with ratio parameters  
- Aspect ratio selector JavaScript component
- Support for 6+ common aspect ratios
- Flexible padding color options

⚡ **Performance:**
- Fast: ~5-15 seconds per clip with ratio conversion
- Parallel processing ready for future enhancement
- Stream copy extraction maintains speed

📱 **Platforms Supported:**
- TikTok, Instagram Reels, YouTube Shorts (9:16)
- Instagram Feed (1:1)
- YouTube, Facebook, Twitter (16:9)
- Cinematic displays (21:9)

🚀 **Next Steps:**
1. Integrate aspect ratio selector into your dashboard
2. Test with different video types
3. Consider parallel ratio processing for extreme speed
4. Add database field to track clip aspect ratios
5. Add preview gallery showing all ratio variants
