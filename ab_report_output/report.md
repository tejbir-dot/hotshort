# A/B Comparison Report: Legacy vs. Delta/Contrast Engine

Generated from 6 candidate windows.

## Headline numbers

- Legacy selected: **6** clips
- New engine selected: **6** clips
- Both agreed on: **6** clips
- Agreement rate: **100.0%**
- Legacy-only (potential regressions): **0**
- New-only (potential new catches): **0**

## Score distributions

- Legacy: {'min': 0.3357, 'max': 0.435, 'mean': 0.3523}
- New: {'min': 0.5986, 'max': 1.0, 'mean': 0.9331}

## Timing

- legacy_total_time: 48.92s
- new_total_time: 23.29s

## ⚠️ Legacy-only clips (new engine dropped these -- check first)

None -- no regressions detected in this sample.


## ✅ New-only clips (potential wins)

None found in this sample.


## Manual review required

This report shows what changed mechanically. It does NOT tell you which system actually picked better clips -- a human needs to watch the legacy-only and new-only clips above and judge them. Per the test plan, do not ship the new engine unless new-only wins outnumber legacy-only regressions on manual review.
