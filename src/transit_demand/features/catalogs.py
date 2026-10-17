"""Known-at-aware calendar and incident flags; no counterfactual target imputation."""

from datetime import date, datetime

from transit_demand.data.quality import ZONE, timestamp


def validate_calendar(records: list[dict]) -> None:
    seen = set()
    for row in records:
        if set(row) != {
            "date",
            "is_holiday",
            "is_bridge_day",
            "is_school_break",
            "known_at",
            "source",
        }:
            raise ValueError("Invalid calendar fields")
        day = date.fromisoformat(row["date"])
        if day.isoformat() != row["date"] or day in seen:
            raise ValueError("Duplicate or noncanonical calendar date")
        seen.add(day)
        timestamp(row["known_at"])
        if not isinstance(row["source"], str) or not row["source"].strip():
            raise ValueError("Calendar requires source")
        if any(
            type(row[f]) is not bool for f in ("is_holiday", "is_bridge_day", "is_school_break")
        ):
            raise ValueError("Calendar flags must be boolean")


def validate_incidents(records: list[dict], station_keys: set[tuple[str, str]]) -> None:
    seen = set()
    for row in records:
        if set(row) != {
            "incident_id",
            "scope",
            "line_id",
            "station_id",
            "start",
            "end",
            "known_at",
            "kind",
            "source",
        }:
            raise ValueError("Invalid incident fields")
        if (
            not isinstance(row["incident_id"], str)
            or not row["incident_id"].strip()
            or row["incident_id"] in seen
        ):
            raise ValueError("Invalid or duplicate incident id")
        seen.add(row["incident_id"])
        if timestamp(row["end"]) <= timestamp(row["start"]):
            raise ValueError("Incident end must follow start")
        timestamp(row["known_at"])
        if row["kind"] not in {"station_closure", "short_turn", "traffic_delay"}:
            raise ValueError("Unknown incident kind")
        if not isinstance(row["source"], str) or not row["source"].strip():
            raise ValueError("Incident requires source")
        scope, line, station = row["scope"], row["line_id"], row["station_id"]
        if scope == "station":
            valid = (line, station) in station_keys
        elif scope == "line":
            valid = station is None and line in {k[0] for k in station_keys}
        elif scope == "system":
            valid = line is None and station is None
        else:
            valid = False
        if not valid:
            raise ValueError("Incident scope does not match catalog")


def flags_at(
    calendar: list[dict],
    incidents: list[dict],
    line: str,
    station: str,
    start: datetime,
    end: datetime,
    origin: datetime,
) -> dict:
    """Half-open overlap supports cross-midnight and unaligned incident boundaries.

    Caller validates full catalogs first. Missing calendar is unknown, not ordinary.
    """
    if any(t.tzinfo is None for t in (start, end, origin)) or end <= start:
        raise ValueError("Require aware timestamps and a positive interval")
    start, end, origin = (t.astimezone(ZONE) for t in (start, end, origin))
    candidates = [
        r
        for r in calendar
        if r["date"] == start.date().isoformat() and timestamp(r["known_at"]) <= origin
    ]
    result = {"calendar_known": bool(candidates)}
    for name in ("is_holiday", "is_bridge_day", "is_school_break"):
        result[name] = candidates[0][name] if candidates else None
    for kind in ("station_closure", "short_turn", "traffic_delay"):
        result[kind] = any(
            r["kind"] == kind
            and timestamp(r["known_at"]) <= origin
            and timestamp(r["start"]) < end
            and timestamp(r["end"]) > start
            and (
                r["scope"] == "system"
                or (r["line_id"] == line and (r["scope"] == "line" or r["station_id"] == station))
            )
            for r in incidents
        )
    return result
