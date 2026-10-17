# Reproducible synthetic demonstration

This is a synthetic data-quality and statistical baseline demonstration. It does not constitute real-data acceptance, existing calibration integration, ML training or production deployment.

## Run from a clean clone

Use Python 3.11 or 3.12. Install the package in a virtual environment:

```sh
python -m venv .venv
# Activate for your platform
python -m pip install -c requirements-demo.txt -e ".[dev]"
python -m pytest
python -m transit_demand quality data/examples/validations.csv --manifest data/examples/delivery-manifest.json --catalog data/examples/station-catalog.json
python -m transit_demand demo --output artifacts/synthetic-demo
```

Open `artifacts/synthetic-demo/report.html` or `report.md`. Every report is marked SYNTHETIC ONLY. The output directory must be new or empty; a second run should use another empty directory. The demo does not overwrite an existing run. It runs offline after dependency installation; it has no database client or network requests.

Runtime dependencies are pinned in requirements-demo.txt to reproduce the verified environment; development tools retain the compatible ranges in pyproject.toml. Seed 1729, dates, scope and all source data are fixed in the generator. Tests run the demo twice and compare SHA-256 hashes for every generated file. Input counts are produced by Python's seeded pseudo-random generator, not sampled from institutional records. Cross-version CI validates behavior on 3.11/3.12; byte identity is tested between runs in each environment, not claimed across all future Python releases.

## What the demonstration exercises

- 63 synthetic local days from January 5, 2026, four invented stations in two lines, 96 base buckets per day.
- 64 deliveries: 63 original daily files and one revised partition. SHA-256, row counts and five transaction totals reconcile against manifests before use.
- A complete sparse export has one omitted verified zero. Partial exports retain a capture-outage interval and an unexplained missing interval as null observations. True observed zeros remain observed.
- A dated, versioned line–station catalog controls valid membership. A cross-midnight incident with unaligned boundaries tests half-open overlap, line scope and knowledge time. A known calendar is validated separately.
- Five forecast origins at 03:00 local time on synthetic days 49, 51, 53, 55 and 57. Each chooses only deliveries available by origin, excluding same-day observations. Each file arrives at 02:00 on its following day; these times are invented, not an institutional service agreement.
- A correction to day 10 is released on day 52. Earlier origins retain V1; later origins choose V2 rather than adding it to V1. Final evaluation truth uses the latest synthetic version as of day 90, independently of the fitting snapshot.
- Two reference methods: latest available same-weekday/time-slot observation (seasonal naive) and mean of available same-weekday/time-slot observations. Unknown training targets are skipped; absent analogues yield no prediction. No healed lags are created.
- Full next local days +1/+2/+3 relative to origin date, **not lead times of exactly 24/48/72 hours**. The first target bucket starts 21 hours after origin. For a three-day horizon, all predictions use the same origin-available history, never tomorrow's observed lag.
- Bottom-up station → line → system sums; temporal sums at 15/60/1440 minutes. Incomplete leaf scopes and temporal groups fail validation. Unknown actuals propagate to parent actuals. This is deterministic aggregation, not covariance-based MinT or probabilistic reconciliation.
- MAE, WAPE and scored/expected coverage for each model, day offset, spatial level and temporal resolution. WAPE is null when the actual sum is zero. Groups pool series at the stated level; they are not per-station individual scores. Overlapping origins are not independent samples.

## Output inventory

| Artifact | Purpose |
| --- | --- |
| `synthetic_input/` | Generated CSVs, per-delivery manifests, complete manifest list, station catalog, calendar and incident fixtures |
| `quality.json` | Reconciliation and grid status counts for each delivery |
| `replay.json` | Exact selected delivery IDs and history cutoff for each forecast origin |
| `forecasts.csv` | Actuals, point predictions, origin, model, day offset, series level and interval size |
| `metrics.json` | Experiment configuration, 54 score groups, replay and limitations |
| `report.md`, `report.html` | Readable summary, with explicit synthetic provenance |
| `checksums.json` | Hashes of all other generated artifacts; no self-referential hash |

Generated artifacts are ignored by Git. A small reviewed [report snapshot](demo-results.md) is tracked for repository review; it is not evidence of institutional performance. .gitattributes preserves LF line endings so the committed small fixture matches its checksum on Windows and Linux.

## Remaining institutional and research gates

Any future real-data validation requires source-approved semantics, authorized access/storage, coverage evidence and independently reviewed acceptance. No real source is connected in this portfolio.

Neither baseline uses calendar/incident flags as predictors: those catalog controls are demonstrated independently. Existing calibration is external and unverified. LightGBM/MLForecast, backtested lag healing, uncertainty bands, covariance reconciliation, capacity modeling and live operations remain planned. Synthetic metrics must never appear in the CV as real-world forecasting accuracy.
