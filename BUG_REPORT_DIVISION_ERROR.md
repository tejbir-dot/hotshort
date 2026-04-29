# Bug Report: "unsupported operand type(s) for /: 'str' and 'float'" in idea_graph.py

## Error Details
- **Error Message**: `unsupported operand type(s) for /: 'str' and 'float'`
- **Context**: Occurs during idea graph building phase, manifests as "[ORCH] idea graph degraded" warning
- **File**: [viral_finder/idea_graph.py](viral_finder/idea_graph.py)
- **Line**: [2553](viral_finder/idea_graph.py#L2553)

## Root Cause

### Problem Location
The bug occurs in the `coalesce_nodes()` function when merging two IdeaNode objects. The code attempts to average all metrics from both nodes without type checking:

```python
# Line 2550-2553 in viral_finder/idea_graph.py
for k in set(prev.metrics.keys()) | set(n.metrics.keys()):
    a = prev.metrics.get(k, 0.0)
    b = n.metrics.get(k, 0.0)
    metrics[k] = round((a + b) / 2.0, 4)  # ← ERROR HERE
```

### Why It Fails

The `metrics` dictionary contains **mixed data types**, including:

1. **Numeric values** (correct):
   - `metrics["audio_mean"]` = float (line 2098)
   - `metrics["motion_mean"]` = float (line 2104)
   - `metrics["visual_confidence"]` = float (line 2129)

2. **String values** (problematic):
   - `metrics["visual_label"]` = string (line 2128)
   ```python
   active_visual = "unknown"  # Line 2118 (default string)
   active_visual = v.get("visual_label", "unknown")  # Line 2123 (fetches string)
   metrics["visual_label"] = active_visual  # Line 2128 (stores string)
   ```

### Failure Sequence

When merging two nodes at line 2553:
1. If both nodes have `"visual_label"` in their metrics
2. `a = prev.metrics.get("visual_label", 0.0)` returns `"unknown"` (string, not the default)
3. `b = n.metrics.get("visual_label", 0.0)` returns `"unknown"` (string, not the default)
4. Attempting `("unknown" + "unknown") / 2.0` raises: **`TypeError: unsupported operand type(s) for /: 'str' and 'float'`**

## Solution

Wrap the division in a type-safe conversion that:
1. Skips string/non-numeric values during averaging
2. Explicitly converts numeric values to float

### Fix Code (Line 2550-2553)

**Current (Broken):**
```python
for k in set(prev.metrics.keys()) | set(n.metrics.keys()):
    a = prev.metrics.get(k, 0.0)
    b = n.metrics.get(k, 0.0)
    metrics[k] = round((a + b) / 2.0, 4)
```

**Fixed:**
```python
for k in set(prev.metrics.keys()) | set(n.metrics.keys()):
    a = prev.metrics.get(k, 0.0)
    b = n.metrics.get(k, 0.0)
    # Skip non-numeric values during averaging
    if isinstance(a, str) or isinstance(b, str):
        # For string values, prefer non-default or first value
        metrics[k] = a if a != 0.0 else b
    else:
        # For numeric values, average them
        try:
            metrics[k] = round((float(a) + float(b)) / 2.0, 4)
        except (ValueError, TypeError):
            # Fallback if conversion fails
            metrics[k] = prev.metrics.get(k, n.metrics.get(k, 0.0))
```

## Testing
After applying the fix:
1. Verify that idea graph building completes without the division error
2. Confirm "[ORCH] idea graph degraded" warning no longer appears
3. Check that merged nodes preserve correct visual label and confidence values

## Related Metrics to Watch
- String keys that should NOT be averaged:
  - `"visual_label"` (string: "unknown", "gameplay", etc.)
  - Any other string-based classifications added in future code
  
- Numeric keys that should be averaged:
  - `"audio_mean"` (float)
  - `"motion_mean"` (float)
  - `"visual_confidence"` (float)
