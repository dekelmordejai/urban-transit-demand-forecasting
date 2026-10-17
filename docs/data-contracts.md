# Illustrative data contracts

## Aggregate CSV

UTF-8, comma-separated, with the exact header order shown in data/examples/validations.csv. FECHA is YYYY-MM-DD; HORA_15MIN is HH:MM:SS with minute 00/15/30/45 and second 00. Counts must be nonnegative integers, names nonempty, and `(LINEA, ID_ESTACION, FECHA, HORA_15MIN)` unique. Missing or excess fields fail validation.

The demo interprets local timestamps in America/Mexico_City and uses half-open [start, end) buckets. Observed entries equal TX_3_INGRESO + TX_4_GRATUIDAD + TX_7_TRANSBORDO; TX_300_SALIDA and TX_0_OTRO are retained separately. These labels and numbers are illustrative interface conventions, not an authoritative transaction mapping for any organization. No card identifiers or personal records are included.

## Delivery metadata and dated catalog

delivery-manifest.schema.json specifies the normalized metadata: exact filename/hash, partition identity, version and supersedes link, period and station scope, extraction/availability times, rules/catalog versions, row count, per-code totals, completeness and known capture gaps. station-catalog.schema.json specifies line-scoped IDs, display names, dated membership and a version.

The executable controls reject checksum or total mismatches, duplicate or overlapping catalog memberships, records outside active scope, broken revision chains and overlap across selected partitions. A revision preserves period and scope. Repartitioning is not supported. Selection uses actual available_at timestamps, never the date a correction describes.

Grid statuses are observed, verified_zero, unknown and capture_outage. Only complete + verified_sparse can fill absent active buckets with zero. Partial exports retain missing values even with sparse policy. Complete explicit exports with missing active intervals fail. Header-only sparse files require a complete manifest with reconciled zero totals; the standalone CSV validator rejects empty observation sets. Capture gaps cannot overlap observations or other gaps.

## Calendar and incident fixtures

Calendar flags can overlap. Unknown or not-yet-known dates produce null calendar flags. Incidents have station/line/system scope, half-open start/end timestamps and known_at. Validation checks scope, duplicate IDs and positive intervals; overlap supports cross-midnight and unaligned boundaries. An absent incident flag means no known recorded overlap, not proof that no disruption occurred. These controls do not impute observed targets or reconstruct latent demand.

## Limits

The grid covers supplied active catalog intervals; it does not infer an operating timetable. The demonstration uses fixed 2026 dates and fixed station scope; clock-change days require a separate policy. Partitions are materialized in memory, so source scale and memory must be benchmarked before real use. Metadata reconciliation checks agreement with the declared controls, not the independent truth of a source database.
