"""Auditable seasonal baselines fitted only on origin-available D-1 history."""

from collections import defaultdict
from datetime import datetime
from statistics import mean

from transit_demand.data.quality import STEP, ZONE, timestamp


class SeasonalBaseline:
    """Latest weekly analogue or mean of past weekday/time-slot analogues.

    No fallback invents observations. Missing training analogues yield None.
    These are statistical references, not a trained ML module.
    """

    def __init__(self, method: str = "seasonal_naive"):
        if method not in {"seasonal_naive", "weekday_slot_mean"}:
            raise ValueError("Unknown baseline method")
        self.method = method
        self.groups = None

    def fit(self, history: list[dict], origin: datetime) -> "SeasonalBaseline":
        if origin.tzinfo is None:
            raise ValueError("Origin requires timezone")
        origin = origin.astimezone(ZONE)
        groups, seen = defaultdict(list), set()
        for row in history:
            ds, available = timestamp(row["ds"]), timestamp(row["available_at"])
            if available > origin or ds + STEP > origin or ds.date() >= origin.date():
                raise ValueError("History violates D-1 availability at origin")
            key = row["line_id"], row["station_id"], ds
            if key in seen:
                raise ValueError("Duplicate history bucket; select revisions before fitting")
            seen.add(key)
            value = row["y_observed"]
            if value is not None:
                if value < 0:
                    raise ValueError("Negative target")
                group = row["line_id"], row["station_id"], ds.weekday(), ds.hour, ds.minute
                groups[group].append((ds, value))
        for values in groups.values():
            values.sort()
        self.groups, self.origin = groups, origin
        return self

    def predict(self, line: str, station: str, target: datetime) -> float | None:
        if self.groups is None:
            raise ValueError("Fit baseline before prediction")
        if target.tzinfo is not None:
            target = target.astimezone(ZONE)
        if (
            target.tzinfo is None
            or target < self.origin
            or target.minute % 15
            or target.second
            or target.microsecond
        ):
            raise ValueError("Invalid forecast target")
        values = self.groups.get((line, station, target.weekday(), target.hour, target.minute), [])
        if not values:
            return None
        if self.method == "seasonal_naive":
            return float(values[-1][1])
        return mean(value for _, value in values)
