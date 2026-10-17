"""M1 versioned delivery controls; absent observations never silently become zero."""

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo

from transit_demand.data.contracts import COUNT_FIELDS, validate_csv

ZONE = ZoneInfo("America/Mexico_City")
STEP = timedelta(minutes=15)


def timestamp(value: str) -> datetime:
    """Require an explicit offset and normalize to the project timezone."""
    result = datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Timestamp requires a UTC offset")
    return result.astimezone(ZONE)


def aligned(value: str) -> datetime:
    result = timestamp(value)
    if result.minute % 15 or result.second or result.microsecond:
        raise ValueError("Boundary must be aligned to 15 minutes")
    return result


def window(start: str, end: str) -> tuple[datetime, datetime]:
    left, right = aligned(start), aligned(end)
    if right <= left:
        raise ValueError("End must follow start")
    return left, right


def validate_catalog(catalog: dict) -> list[dict]:
    """Reject overlapping memberships; station identity includes its line."""
    if (
        set(catalog) != {"version", "stations"}
        or not isinstance(catalog.get("version"), str)
        or not catalog["version"].strip()
        or not isinstance(catalog.get("stations"), list)
    ):
        raise ValueError("Catalog needs version and stations")
    periods = defaultdict(list)
    for station in catalog["stations"]:
        if set(station) != {"line_id", "station_id", "name", "valid_from", "valid_to"}:
            raise ValueError("Invalid catalog fields")
        for field in ("line_id", "station_id", "name"):
            if not isinstance(station.get(field), str) or not station[field].strip():
                raise ValueError(f"Catalog requires {field}")
        left, right = window(station["valid_from"], station["valid_to"])
        periods[station["line_id"], station["station_id"]].append((left, right))
    if not periods:
        raise ValueError("Catalog cannot be empty")
    for ranges in periods.values():
        ranges.sort()
        if any(a[1] > b[0] for a, b in zip(ranges, ranges[1:])):
            raise ValueError("Overlapping catalog membership")
    return catalog["stations"]


def validate_manifest(manifest: dict) -> None:
    """Check delivery metadata independently of the source CSV."""
    required = {
        "delivery_id",
        "partition_id",
        "version",
        "supersedes",
        "filename",
        "sha256",
        "start",
        "end",
        "scope",
        "catalog_version",
        "extracted_at",
        "available_at",
        "status",
        "zero_policy",
        "row_count",
        "totals",
        "gaps",
        "rules_version",
    }
    if set(manifest) != required:
        raise ValueError("Manifest fields do not match the M1 contract")
    for field in ("delivery_id", "partition_id", "catalog_version", "rules_version"):
        if not isinstance(manifest[field], str) or not manifest[field].strip():
            raise ValueError(f"Manifest requires {field}")
    for field in ("version", "row_count"):
        if type(manifest[field]) is not int or manifest[field] < (1 if field == "version" else 0):
            raise ValueError(f"Invalid {field}")
    if manifest["version"] == 1:
        if manifest["supersedes"] is not None:
            raise ValueError("First version cannot supersede a delivery")
    elif not isinstance(manifest["supersedes"], str) or not manifest["supersedes"].strip():
        raise ValueError("Revision must identify the superseded delivery")
    digest = manifest["sha256"]
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(c not in "0123456789abcdef" for c in digest)
    ):
        raise ValueError("Invalid SHA-256")
    filename = manifest["filename"]
    if (
        not isinstance(filename, str)
        or not filename
        or "/" in filename
        or "\\" in filename
        or filename in {".", ".."}
    ):
        raise ValueError("Manifest filename must be a basename")
    left, right = window(manifest["start"], manifest["end"])
    extracted, available = timestamp(manifest["extracted_at"]), timestamp(manifest["available_at"])
    if extracted < right or available < extracted:
        raise ValueError("Delivery cannot precede its period or extraction")
    if manifest["status"] not in {"complete", "partial"}:
        raise ValueError("Invalid completeness status")
    if manifest["zero_policy"] not in {"explicit", "verified_sparse"}:
        raise ValueError("Invalid zero policy")
    scope = manifest["scope"]
    if not isinstance(scope, list) or not scope:
        raise ValueError("Scope cannot be empty")
    keys = []
    for member in scope:
        if set(member) != {"line_id", "station_id"} or any(
            not isinstance(v, str) or not v.strip() for v in member.values()
        ):
            raise ValueError("Invalid scope member")
        keys.append((member["line_id"], member["station_id"]))
    if len(set(keys)) != len(keys):
        raise ValueError("Duplicate scope member")
    totals = manifest["totals"]
    if set(totals) != set(COUNT_FIELDS) or any(
        type(v) is not int or v < 0 for v in totals.values()
    ):
        raise ValueError("Invalid control totals")
    if not isinstance(manifest["gaps"], list):
        raise ValueError("Gaps must be a list")
    for gap in manifest["gaps"]:
        if set(gap) != {"line_id", "station_id", "start", "end", "reason"}:
            raise ValueError("Invalid gap fields")
        a, b = window(gap["start"], gap["end"])
        if (gap["line_id"], gap["station_id"]) not in keys or not left <= a < b <= right:
            raise ValueError("Gap outside delivery scope")
        if gap["reason"] not in {"capture_outage", "unknown"}:
            raise ValueError("Invalid gap reason")
    if manifest["status"] == "complete" and manifest["gaps"]:
        raise ValueError("Complete delivery cannot declare capture gaps")


def select_as_of(manifests: list[dict], origin: datetime) -> list[dict]:
    """Choose one revision per partition using actual availability at origin."""
    if origin.tzinfo is None:
        raise ValueError("Origin requires a timezone")
    groups, ids = defaultdict(list), set()
    for item in manifests:
        validate_manifest(item)
        if item["delivery_id"] in ids:
            raise ValueError("Duplicate delivery id")
        ids.add(item["delivery_id"])
        groups[item["partition_id"]].append(item)
    chosen = []
    for versions in groups.values():
        versions.sort(key=lambda item: item["version"])
        first = versions[0]
        if first["version"] != 1:
            raise ValueError("Revision history must start at 1")
        previous = None
        for item in versions:
            if (timestamp(item["start"]), timestamp(item["end"]), item["scope"]) != (
                timestamp(first["start"]),
                timestamp(first["end"]),
                first["scope"],
            ):
                raise ValueError("Revision changes partition bounds or scope")
            if previous and (
                item["version"] != previous["version"] + 1
                or item["supersedes"] != previous["delivery_id"]
                or timestamp(item["available_at"]) < timestamp(previous["available_at"])
            ):
                raise ValueError("Broken revision chain")
            previous = item
        eligible = [item for item in versions if timestamp(item["available_at"]) <= origin]
        if eligible:
            chosen.append(eligible[-1])
    for i, a in enumerate(chosen):
        for b in chosen[i + 1 :]:
            scope_a = {(x["line_id"], x["station_id"]) for x in a["scope"]}
            scope_b = {(x["line_id"], x["station_id"]) for x in b["scope"]}
            if scope_a & scope_b and max(timestamp(a["start"]), timestamp(b["start"])) < min(
                timestamp(a["end"]), timestamp(b["end"])
            ):
                raise ValueError("Overlapping selected partitions")
    return sorted(chosen, key=lambda item: (timestamp(item["start"]), item["partition_id"]))


def validate_delivery(path: str | Path, manifest: dict, catalog: dict) -> dict:
    """Return a scoped grid with explicit provenance for observed, zero and unknown."""
    validate_manifest(manifest)
    stations = validate_catalog(catalog)
    if manifest["catalog_version"] != catalog["version"]:
        raise ValueError("Catalog version mismatch")
    path = Path(path)
    if (
        path.name != manifest["filename"]
        or sha256(path.read_bytes()).hexdigest() != manifest["sha256"]
    ):
        raise ValueError("Filename or checksum mismatch")
    rows = validate_csv(path, allow_empty=True)
    if len(rows) != manifest["row_count"]:
        raise ValueError("Row count reconciliation failed")
    if any(sum(r[c] for r in rows) != manifest["totals"][c] for c in COUNT_FIELDS):
        raise ValueError("Transaction totals reconciliation failed")
    left, right = window(manifest["start"], manifest["end"])
    scope = {(x["line_id"], x["station_id"]) for x in manifest["scope"]}
    expected = {}
    for line, station in sorted(scope):
        memberships = [s for s in stations if (s["line_id"], s["station_id"]) == (line, station)]
        if not memberships:
            raise ValueError("Scope station absent from catalog")
        for member in memberships:
            a = max(left, timestamp(member["valid_from"]))
            b = min(right, timestamp(member["valid_to"]))
            while a < b:
                expected[line, station, a] = member["name"]
                a += STEP
    if not expected:
        raise ValueError("No active catalog intervals in scope")
    observed = {}
    for row in rows:
        stamp = datetime.fromisoformat(row["FECHA"] + "T" + row["HORA_15MIN"]).replace(tzinfo=ZONE)
        key = row["LINEA"], row["ID_ESTACION"], stamp
        if key not in expected or row["ESTACION"] != expected[key]:
            raise ValueError("Record outside active catalog or station name mismatch")
        observed[key] = row["y_observed"]
    gaps = {}
    for gap in manifest["gaps"]:
        a, b = window(gap["start"], gap["end"])
        while a < b:
            key = gap["line_id"], gap["station_id"], a
            if key not in expected or key in gaps:
                raise ValueError("Gap outside active catalog or overlapping gaps")
            if key in observed:
                raise ValueError("Observed record conflicts with declared capture gap")
            gaps[key] = gap["reason"]
            a += STEP
    grid = []
    for key in sorted(expected):
        line, station, stamp = key
        if key in observed:
            y, status = observed[key], "observed"
        elif key in gaps:
            y, status = None, gaps[key]
        elif manifest["status"] == "complete" and manifest["zero_policy"] == "verified_sparse":
            y, status = 0, "verified_zero"
        else:
            y, status = None, "unknown"
        grid.append(
            {
                "line_id": line,
                "station_id": station,
                "ds": stamp.isoformat(),
                "y_observed": y,
                "status": status,
                "delivery_id": manifest["delivery_id"],
                "available_at": manifest["available_at"],
            }
        )
    if manifest["status"] == "complete" and any(r["y_observed"] is None for r in grid):
        raise ValueError("Complete explicit delivery has missing intervals")
    return {
        "delivery_id": manifest["delivery_id"],
        "rows_received": len(rows),
        "expected_intervals": len(grid),
        "status_counts": dict(Counter(r["status"] for r in grid)),
        "grid": grid,
    }
