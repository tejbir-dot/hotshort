# 🎬 CONFIDENCE SCORE & BADGE SYSTEM

## Overview

The confidence bar and badges are **data-driven, never arbitrary**. They're calculated from the actual intelligence scores, not position or magic numbers.

---

## Confidence Score Calculation

```python
confidence = (
    hook_score      * 0.40 +    # How strong the hook (40%)
    retention_score * 0.35 +    # Will viewers watch to end? (35%)
    clarity_score   * 0.15 +    # Is the message clear? (15%)
    emotion_score   * 0.10      # Emotional impact (10%)
) * 100

# Result: 0-100 integer
```

### Why These Weights?

- **Hook (40%)**: Most important for stopping scrollers
- **Retention (35%)**: Keeps them watching (algorithmic reward)
- **Clarity (15%)**: Message lands = higher trust
- **Emotion (10%)**: Bonus for engagement

### Examples

| Hook | Retention | Clarity | Emotion | Confidence |
|------|-----------|---------|---------|------------|
| 0.90 | 0.82      | 0.78    | 0.70    | 82%        |
| 0.85 | 0.75      | 0.80    | 0.75    | 79%        |
| 0.95 | 0.90      | 0.85    | 0.80    | 89%        |
| 0.65 | 0.60      | 0.65    | 0.60    | 63%        |

---

## Badge System

Badges are shown on clip cards based on actual data:

### 🏆 Best Pick
- **Condition**: `is_best === true`
- **Meaning**: Highest-ranked clip in the carousel
- **Styling**: Gold gradient with prominent glow
- **Count**: Always 1 (only the top clip)

### 🔥 High Confidence
- **Condition**: `confidence > 80`
- **Meaning**: System is very confident this will go viral
- **Styling**: Green accent (success color)
- **Count**: Usually 1-2 clips
- **Confidence Ranges**:
  - `> 85`: Exceptional confidence
  - `> 80`: High confidence ✓
  - `> 75`: Good confidence
  - `> 70`: Decent confidence
  - `< 70`: Moderate confidence

### ⚡ Pattern Break
- **Condition**: `hook_type === "Contradiction"`
- **Meaning**: Opens with disagreement or counter-intuition
- **Styling**: Yellow/amber accent
- **Count**: Variable (depends on analysis)
- **Other Hook Types**:
  - Question
  - Curiosity Gap
  - Emotional
  - Authority/Proof

---

## Badge Logic (Frontend)

```javascript
// In templates/results_new.html
function renderBadges(clip) {
  const badges = [];
  
  // Badge 1: Best Pick
  if (clip.is_best) {
    badges.push({ text: '🏆 Best Pick', class: 'best' });
  }
  
  // Badge 2: High Confidence
  if (clip.confidence > 80) {
    badges.push({ text: '🔥 High Confidence', class: 'high-confidence' });
  }
  
  // Badge 3: Hook Type (if notable)
  if (clip.hook_type === 'Contradiction') {
    badges.push({ text: '⚡ Pattern Break', class: 'pattern-break' });
  }
  
  return badges;
}
```

---

## Customization

### Adjust Confidence Weights

Edit `utils/clip_schema.py`, function `create_viral_clip()`:

```python
# Current (conservative):
confidence = int(
    (hook_score * 0.40 +           # Hook most important
     retention_score * 0.35 +
     clarity_score * 0.15 +
     emotion_score * 0.10) * 100
)

# Alternative (hook-heavy):
confidence = int(
    (hook_score * 0.50 +           # More aggressive
     retention_score * 0.30 +
     clarity_score * 0.12 +
     emotion_score * 0.08) * 100
)

# Alternative (balanced):
confidence = int(
    (hook_score * 0.25 +           # All equal
     retention_score * 0.25 +
     clarity_score * 0.25 +
     emotion_score * 0.25) * 100
)
```

### Add New Badge Type

Edit `templates/results_new.html`:

```javascript
// Add new condition
if (clip.duration < 10) {
  badges.push({ text: '⚡ Quick Hit', class: 'quick' });
}

// Add new CSS in <style>
.badge.quick {
  background: rgba(59, 130, 246, 0.2);  /* Blue */
  border-color: #3b82f6;
  color: #3b82f6;
}
```

### Adjust High Confidence Threshold

Edit `templates/results_new.html`:

```javascript
// Current (80):
if (clip.confidence > 80) {
  badges.push({ text: '🔥 High Confidence', class: 'high-confidence' });
}

// More selective (85+):
if (clip.confidence > 85) {
  badges.push({ text: '🔥 Exceptional', class: 'exceptional' });
}

// Less selective (75+):
if (clip.confidence > 75) {
  badges.push({ text: '🔥 Strong', class: 'strong' });
}
```

---

## Visual Design

### Confidence Bar
```
Full: ████████████████████ 100%
High: ████████████████░░░░░ 82%
Good: █████████████░░░░░░░░░ 75%
Low:  ███████░░░░░░░░░░░░░░░░ 45%
```

### Badge Appearance

**Best Pick** (Gold)
```
┌──────────────┐
│ 🏆 Best Pick │  ← Slightly larger, prominent glow
└──────────────┘
```

**High Confidence** (Green)
```
┌─────────────────────┐
│ 🔥 High Confidence  │  ← Clear success indication
└─────────────────────┘
```

**Pattern Break** (Amber)
```
┌──────────────────┐
│ ⚡ Pattern Break │  ← Shows hook type
└──────────────────┘
```

---

## FAQ

**Q: Why is my confidence score lower than expected?**
A: Check the component scores. If retention is low, it will drag down confidence. This is intentional — we want only truly high-confidence clips highlighted.

**Q: Can I make confidence always > 80?**
A: Technically yes, but you're lying to the user. The badge loses meaning. Better to show real confidence and improve the analysis.

**Q: What if all clips have low confidence?**
A: The UI still works. No "🔥 High Confidence" badges shown, but the system is honest. User knows the analysis was weak.

**Q: Can I show more than one badge?**
A: Yes! A clip can show both "🏆 Best Pick" and "🔥 High Confidence" and "⚡ Pattern Break". All badges based on data.

**Q: Should I show confidence as decimal (0.82) or percentage (82)?**
A: Percentage (82%) is more intuitive for end users. Decimals are for backend engineers.

---

## Best Practices

1. **Always show confidence**: Users want to know how sure the system is
2. **Use meaningful thresholds**: Don't badge everything (it becomes noise)
3. **Show badges on hover** (optional): Tooltip explaining badge meaning
4. **Update badges dynamically**: If scores change, badges change
5. **Prefer simplicity**: 1-3 badges per clip max
6. **Colors matter**: 
   - Gold = premium/best
   - Green = success/high quality
   - Yellow = warning/notable
   - Blue = informational

---

## Example: Full Clip Card with Badges & Confidence

```html
<article class="clip-card is-best">
  <div class="clip-preview">
    <video src="/static/outputs/clip_1.mp4"></video>
    
    <!-- Badges -->
    <div class="badge-group">
      <div class="badge best">🏆 Best Pick</div>
      <div class="badge high-confidence">🔥 High Confidence</div>
      <div class="badge pattern-break">⚡ Pattern Break</div>
    </div>
  </div>

  <div class="clip-content">
    <div class="clip-title">Most people learn coding wrong</div>
    <div class="hook-label">Contradiction</div>
    
    <!-- Confidence Bar -->
    <div class="confidence-container">
      <div class="confidence-bar">
        <div class="confidence-fill" style="width: 82%"></div>
      </div>
      <div class="confidence-value">82%</div>
    </div>
    
    <!-- Actions -->
    <div class="clip-actions">
      <button class="btn">👁 View Reasons</button>
      <button class="btn">⬇ Download</button>
    </div>
  </div>
</article>
```

This communicates:
- ✅ Best clip in the carousel
- ✅ 82% confidence (very high)
- ✅ Uses a contradiction hook
- ✅ Very likely to stop scrollers
