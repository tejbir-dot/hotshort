# 🧪 Single Pass vs Dual Pass Comparison Test

## What are the Passes?

The clip selection system uses **2 selection passes**:

### 🔴 **Pass 1: STRICT (High Quality)**
- Full quality thresholds (high bar)
- Curiosity, Punch, Semantic scores must meet baseline
- Weight: 1.0x (no penalty)
- Typical clips found: **3-5 high-quality clips**

### 🟢 **Pass 2: RELAXED (More Permissive)**
- Lowered quality thresholds
- Relaxes curiosity, punch, semantic requirements
- Weight: 0.85x (slight quality penalty)
- Only triggers if strict pass doesn't find enough clips
- Typical clips found: **+2-3 additional clips**

---

## How to Test

### **TEST 1: Single Pass (Strict Only)**

```bash
# Edit .env to disable relaxed pass:
HS_SELECTOR_RELAX_CURIO_DELTA=0.0
HS_SELECTOR_RELAX_PUNCH_DELTA=0.0
HS_SELECTOR_RELAX_SEM_FLOOR=0.45
```

Then:
1. Go to dashboard
2. Upload a YouTube video
3. Wait for analysis
4. **Note DOWN:**
   - ⏱️ Time taken (check Network tab in DevTools)
   - 📊 Number of clips found
   - ⭐ Score of each clip
   - 📊 Quality badge

### **TEST 2: Dual Pass (Strict + Relaxed)**

```bash
# Edit .env to enable relaxed pass:
HS_SELECTOR_RELAX_CURIO_DELTA=0.08
HS_SELECTOR_RELAX_PUNCH_DELTA=0.08
HS_SELECTOR_RELAX_SEM_FLOOR=0.45
```

Then:
1. Go to dashboard
2. **Upload the SAME video**
3. Wait for analysis
4. **Compare with TEST 1:**
   - ⏱️ Time taken
   - 📊 Number of clips found
   - ⭐ Score differences
   - 📊 Quality badges

---

## Expected Results

| Metric | Single Pass | Dual Pass | Difference |
|--------|------------|-----------|-----------|
| **Clips Found** | 3-5 | 5-8 | +40-60% more |
| **Time Taken** | 30-45s | 32-48s | +2-5% slower |
| **Avg Score** | 0.78-0.85 | 0.72-0.82 | -5-8% lower |
| **User Choice** | Limited | More options | ✅ Better |

---

## Key Configuration Parameters

### Current Settings in `.env`:

```env
# Relaxation deltas (how much to lower thresholds for pass 2)
HS_SELECTOR_RELAX_CURIO_DELTA=0.08       # Curiosity threshold reduction
HS_SELECTOR_RELAX_PUNCH_DELTA=0.08       # Punch threshold reduction

# Quality floors for relaxed pass
HS_SELECTOR_RELAX_SEM_FLOOR=0.45         # Semantic quality minimum

# Pass weights (scoring multipliers)
HS_DIVERSITY_STRICT_PASS_WEIGHT=1.0      # Strict pass: full score
HS_DIVERSITY_RELAX_PASS_WEIGHT=0.85      # Relaxed pass: 85% score
```

### To Test:

**Single Pass (Strict Only):**
```env
HS_SELECTOR_RELAX_CURIO_DELTA=0.0
HS_SELECTOR_RELAX_PUNCH_DELTA=0.0
```

**Dual Pass (Strict + Relaxed):**
```env
HS_SELECTOR_RELAX_CURIO_DELTA=0.08
HS_SELECTOR_RELAX_PUNCH_DELTA=0.08
```

---

## How to Modify Settings

### **Quick Edit Method:**

1. Open `.env` file in VS Code
2. Find the lines:
   ```
   HS_SELECTOR_RELAX_CURIO_DELTA=0.08
   HS_SELECTOR_RELAX_PUNCH_DELTA=0.08
   HS_SELECTOR_RELAX_SEM_FLOOR=0.45
   ```
3. Change values and save
4. Restart the app (or it picks up on next request)

### **Command Line Method (PowerShell):**

```powershell
# For Single Pass:
(gc .env) -replace "HS_SELECTOR_RELAX_CURIO_DELTA=.*", "HS_SELECTOR_RELAX_CURIO_DELTA=0.0" | sc .env
(gc .env) -replace "HS_SELECTOR_RELAX_PUNCH_DELTA=.*", "HS_SELECTOR_RELAX_PUNCH_DELTA=0.0" | sc .env

# For Dual Pass (restore):
(gc .env) -replace "HS_SELECTOR_RELAX_CURIO_DELTA=.*", "HS_SELECTOR_RELAX_CURIO_DELTA=0.08" | sc .env
(gc .env) -replace "HS_SELECTOR_RELAX_PUNCH_DELTA=.*", "HS_SELECTOR_RELAX_PUNCH_DELTA=0.08" | sc .env
```

---

## What to Look For

### 📊 In the Results Page:

1. **Number of Clips**
   - Single Pass: Usually 3-5
   - Dual Pass: Usually 5-8+

2. **Clip Scores**
   - Single Pass: 0.78+ (high)
   - Dual Pass: Mix of 0.78+ (strict) and 0.65-0.75 (relaxed)

3. **Quality Badges**
   - Single Pass: All showing high confidence
   - Dual Pass: Some showing medium confidence (from relaxed pass)

4. **Time Taken (Network tab)**
   - Typically: <5% difference
   - Most time is downloading/transcribing video

---

## Example Output Comparison

### ❌ Single Pass Results
```
Total Clips: 4
├─ Clip 1: Score 0.82 (Strict, Hook)
├─ Clip 2: Score 0.79 (Strict, Punch)
├─ Clip 3: Score 0.76 (Strict, Transition)
└─ Clip 4: Score 0.74 (Strict, Ending)
Time: 42s
Quality: Excellent but limited
```

### ✅ Dual Pass Results
```
Total Clips: 7
├─ Clip 1: Score 0.82 (Strict, Hook)
├─ Clip 2: Score 0.79 (Strict, Punch)
├─ Clip 3: Score 0.76 (Strict, Transition)
├─ Clip 4: Score 0.74 (Strict, Ending)
├─ Clip 5: Score 0.68 (Relaxed, Hook variant)
├─ Clip 6: Score 0.65 (Relaxed, Curiosity)
└─ Clip 7: Score 0.63 (Relaxed, Outro)
Time: 44s
Quality: Good selection with more options
```

---

## Code Reference

The two-pass logic is implemented in:
- **File:** `viral_finder/idea_graph.py`
- **Function:** `_select_candidate_clips_v2()` (lines ~2600-2850)
- **Key code:**
  ```python
  # Strict pass
  strict_candidates = _build_candidates(
      curio_cutoff=selected_curio_cutoff,
      punch_cutoff=selected_punch_cutoff,
      pass_name="strict"
  )
  
  # Relaxed pass (if needed)
  if len(strict_candidates) < target_count:
      relaxed_candidates = _build_candidates(
          curio_cutoff=selected_curio_cutoff - relax_curio_delta,  # Lower threshold
          punch_cutoff=selected_punch_cutoff - relax_punch_delta,  # Lower threshold
          pass_name="relaxed"
      )
  ```

---

## Summary Table

| Aspect | Single Pass | Dual Pass | When to Use |
|--------|------------|-----------|-----------|
| **Quality** | High ⭐⭐⭐ | Good ⭐⭐ | High quality preferred |
| **Quantity** | 3-5 clips | 5-8+ clips | More options needed |
| **Speed** | Faster ⚡ | Slightly slower ⚡⚡ | Not significant |
| **User UX** | Limited choice | Better selection | Dual recommended |
| **Default** | ❌ No | ✅ Yes | Currently enabled |

---

## 🚀 Next Steps

1. **Backup current `.env`**: `copy .env .env.backup`
2. **Test Single Pass**: Set deltas to 0.0, run analysis
3. **Test Dual Pass**: Set deltas back to 0.08, run same analysis
4. **Compare Results**: Note down clips, quality, timing
5. **Decide**: Which mode works better for your use case?

---

*Last Updated: April 7, 2026*
