# Implementation status

| Component | Status | Evidence |
| --- | --- | --- |
| CSV contract and observed-entry convention | Implemented | data/contracts.py and synthetic examples |
| Reconciliation, catalog grid and completeness | Implemented | data/quality.py and negative-case tests |
| Partition revisions and as-of selection | Implemented | Replacement chains, late-correction replay and overlap rejection |
| Calendar/incident controls | Implemented separately from forecasting | features/catalogs.py, scope/known_at/cross-midnight tests |
| Seasonal naive and weekday-slot mean | Implemented | models/baselines.py; no ML training |
| Spatial/time point aggregation | Implemented | Conservative bottom-up sums with incomplete-group checks |
| Synthetic out-of-time evaluation | Implemented | Five origins, three target-day offsets, MAE/WAPE/coverage |
| Real-source validation and external calibration | Future work | No real data or internal calibration implementation included |
| ML, healed lags, quantile forecasts and MinT | Future work | No performance or deployment claims |
| Forecast service and live operations | Future work | No deployed API, alerts or operational automation |

The source snapshot supports a reproducible software portfolio. It does not establish institutional acceptance, calibrated uncertainty or real-world predictive accuracy.
