# Synthetic transit demand demonstration

**SYNTHETIC ONLY — not institutional performance.**

Deterministic seed 1729; 63 days, 4 fictional stations, 2 lines; 5 replayed origins.

Two statistical baselines; full local forecast days +1/+2/+3, at 15-minute/hourly/daily resolution.

## Quality evidence

All 64 deliveries passed checksum, row-count and per-code reconciliation.
Sparse day 12: one verified zero. Day 20: one capture outage. Day 30: one unknown bucket.
Day 10 revision V2 is visible only after its availability on day 52. Missing history stays unknown.

## System daily scores

| Model | Day offset | MAE | WAPE | Coverage |
| --- | --- | --- | --- | --- |
| seasonal_naive | +1 | 40.60 | 0.20% | 5/5 |
| seasonal_naive | +2 | 59.40 | 0.29% | 5/5 |
| seasonal_naive | +3 | 48.80 | 0.24% | 5/5 |
| weekday_slot_mean | +1 | 46.97 | 0.23% | 5/5 |
| weekday_slot_mean | +2 | 87.07 | 0.42% | 5/5 |
| weekday_slot_mean | +3 | 53.53 | 0.26% | 5/5 |

MAE is measured in recorded entries per system-day. WAPE is undefined when actual total is zero.
All metrics by station/line/system and 15/60/1440 minutes are in metrics.json.

## Limits and institutional gate

- No real-data acceptance
- No ML or existing calibration comparison
- No predictive intervals, MinT, causal lag healing or operational claims
- Fixed synthetic station scope and 2026 local-time grid; no clock-change policy
- Overlapping forecast origins are not independent samples
- Synthetic error metrics do not estimate institutional forecasting accuracy

A real pilot requires an authorized channel, source-team confirmations and external secure storage.
Run the same controls against that pilot before training any institutional model.
