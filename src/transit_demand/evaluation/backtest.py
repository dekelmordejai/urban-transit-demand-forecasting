"""Origin-replayed evaluation and conservative coherent aggregation."""

from collections import defaultdict
from math import isfinite

from transit_demand.data.quality import timestamp


def metrics(rows: list[dict]) -> dict:
    """MAE/WAPE on finite prediction/truth pairs; report missing coverage explicitly."""
    pairs = [
        (r["actual"], r["prediction"])
        for r in rows
        if r["actual"] is not None and r["prediction"] is not None
    ]
    if any(not isfinite(a) or not isfinite(p) or a < 0 or p < 0 for a, p in pairs):
        raise ValueError("Scores require finite nonnegative values")
    absolute_error = sum(abs(a - p) for a, p in pairs)
    denominator = sum(a for a, _ in pairs)
    return {
        "expected": len(rows),
        "scored": len(pairs),
        "coverage": len(pairs) / len(rows) if rows else None,
        "mae": absolute_error / len(pairs) if pairs else None,
        "wape": absolute_error / denominator if denominator else None,
    }


def complete_sum(values: list) -> float | None:
    return None if any(value is None for value in values) else sum(values)


def spatial_rollup(rows: list[dict], station_keys: set[tuple[str, str]]) -> list[dict]:
    """Bottom-up sums at each bucket. Unknown leaves propagate to parent totals."""
    if not station_keys:
        raise ValueError("Expected station scope cannot be empty")
    buckets = defaultdict(list)
    for row in rows:
        buckets[row["origin"], row["model"], row["day_offset"], row["ds"]].append(row)
    result = []
    for key, members in sorted(buckets.items()):
        keys = [(r["line_id"], r["station_id"]) for r in members]
        if len(keys) != len(set(keys)) or set(keys) != station_keys:
            raise ValueError("Rollup requires exactly the expected leaves per bucket")
        origin, model, day, ds = key
        base = {"origin": origin, "model": model, "day_offset": day, "ds": ds}
        for member in members:
            result.append(
                {
                    **base,
                    "level": "station",
                    "series": member["line_id"] + "/" + member["station_id"],
                    "actual": member["actual"],
                    "prediction": member["prediction"],
                }
            )
        for line in sorted({k[0] for k in station_keys}):
            group = [r for r in members if r["line_id"] == line]
            result.append(
                {
                    **base,
                    "level": "line",
                    "series": line,
                    "actual": complete_sum([r["actual"] for r in group]),
                    "prediction": complete_sum([r["prediction"] for r in group]),
                }
            )
        result.append(
            {
                **base,
                "level": "system",
                "series": "SYN_SYSTEM",
                "actual": complete_sum([r["actual"] for r in members]),
                "prediction": complete_sum([r["prediction"] for r in members]),
            }
        )
    return result


def temporal_rollup(rows: list[dict], minutes: int) -> list[dict]:
    """Local calendar buckets; reject incomplete or duplicated bucket sets.

    Only deterministic point forecasts and observed counts are summed, never quantiles.
    The demo operates in 2026; historical clock-change days require a separate policy.
    """
    if type(minutes) is not int or minutes < 15 or 1440 % minutes or minutes % 15:
        raise ValueError("Interval must divide a local day and be a multiple of 15 minutes")
    groups = defaultdict(list)
    for row in rows:
        ds = timestamp(row["ds"])
        if ds.minute % 15 or ds.second or ds.microsecond:
            raise ValueError("Input must be aligned to base grid")
        slot = (ds.hour * 60 + ds.minute) // minutes * minutes
        start = ds.replace(hour=slot // 60, minute=slot % 60, second=0, microsecond=0)
        groups[
            row["origin"], row["model"], row["day_offset"], row["level"], row["series"], start
        ].append(row)
    result = []
    for key, members in sorted(groups.items()):
        if len(members) != minutes // 15 or len({r["ds"] for r in members}) != len(members):
            raise ValueError("Incomplete or duplicate temporal group")
        origin, model, day, level, series, start = key
        result.append(
            {
                "origin": origin,
                "model": model,
                "day_offset": day,
                "level": level,
                "series": series,
                "ds": start.isoformat(),
                "interval_minutes": minutes,
                "actual": complete_sum([r["actual"] for r in members]),
                "prediction": complete_sum([r["prediction"] for r in members]),
            }
        )
    return result
