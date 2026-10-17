import csv
import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest

from transit_demand.data.contracts import COUNT_FIELDS, FIELDS
from transit_demand.data.quality import (
    select_as_of,
    timestamp,
    validate_catalog,
    validate_delivery,
)


@pytest.fixture
def delivery(tmp_path):
    path = tmp_path / "synthetic.csv"
    rows = [
        dict(
            zip(
                FIELDS,
                ["SYN_L", "SYN_A", "Synthetic Alpha", "2026-01-05", "06:00:00", 10, 2, 3, 100, 50],
            )
        )
    ]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    catalog = {
        "version": "SYN_V1",
        "stations": [
            {
                "line_id": "SYN_L",
                "station_id": "SYN_A",
                "name": "Synthetic Alpha",
                "valid_from": "2026-01-05T00:00:00-06:00",
                "valid_to": "2026-01-06T00:00:00-06:00",
            }
        ],
    }
    manifest = {
        "delivery_id": "SYN_D_V1",
        "partition_id": "SYN_D",
        "version": 1,
        "supersedes": None,
        "filename": path.name,
        "sha256": sha256(path.read_bytes()).hexdigest(),
        "start": "2026-01-05T06:00:00-06:00",
        "end": "2026-01-05T06:30:00-06:00",
        "scope": [{"line_id": "SYN_L", "station_id": "SYN_A"}],
        "catalog_version": "SYN_V1",
        "extracted_at": "2026-01-06T02:00:00-06:00",
        "available_at": "2026-01-06T02:00:00-06:00",
        "status": "partial",
        "zero_policy": "explicit",
        "row_count": 1,
        "totals": {c: rows[0][c] for c in COUNT_FIELDS},
        "gaps": [],
        "rules_version": "SYN_RULES_V1",
    }
    return path, manifest, catalog


def test_missing_is_not_zero_and_target_excludes_exit_and_zero(delivery):
    path, manifest, catalog = delivery
    report = validate_delivery(path, manifest, catalog)
    assert [r["y_observed"] for r in report["grid"]] == [15, None]
    assert report["status_counts"] == {"observed": 1, "unknown": 1}


def test_only_verified_complete_sparse_export_fills_zero(delivery):
    path, manifest, catalog = delivery
    manifest.update(status="complete", zero_policy="verified_sparse")
    report = validate_delivery(path, manifest, catalog)
    assert report["grid"][1]["y_observed"] == 0
    assert report["grid"][1]["status"] == "verified_zero"
    manifest["status"] = "partial"
    assert validate_delivery(path, manifest, catalog)["grid"][1]["y_observed"] is None


def test_complete_explicit_export_cannot_hide_missing_rows(delivery):
    path, manifest, catalog = delivery
    manifest["status"] = "complete"
    with pytest.raises(ValueError, match="missing intervals"):
        validate_delivery(path, manifest, catalog)


def test_capture_outage_is_unknown_even_with_sparse_policy(delivery):
    path, manifest, catalog = delivery
    manifest["zero_policy"] = "verified_sparse"
    manifest["gaps"] = [
        {
            "line_id": "SYN_L",
            "station_id": "SYN_A",
            "start": "2026-01-05T06:15:00-06:00",
            "end": manifest["end"],
            "reason": "capture_outage",
        }
    ]
    report = validate_delivery(path, manifest, catalog)
    assert report["grid"][1]["status"] == "capture_outage"
    assert report["grid"][1]["y_observed"] is None
    manifest["gaps"][0]["start"] = manifest["start"]
    with pytest.raises(ValueError, match="conflicts"):
        validate_delivery(path, manifest, catalog)


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda m: m.update(sha256="0" * 64), "checksum"),
        (lambda m: m.update(row_count=2), "Row count"),
        (lambda m: m["totals"].update(TX_0_OTRO=0), "totals"),
        (lambda m: m.update(catalog_version="wrong"), "Catalog version"),
        (lambda m: m.update(available_at="2026-01-05T00:00:00-06:00"), "precede"),
        (lambda m: m.update(start="2026-01-05T06:01:00-06:00"), "aligned"),
        (lambda m: m.update(filename="../synthetic.csv"), "basename"),
        (lambda m: m.update(row_count=True), "row_count"),
    ],
)
def test_failed_delivery_controls(delivery, mutation, match):
    path, manifest, catalog = delivery
    mutation(manifest)
    with pytest.raises(ValueError, match=match):
        validate_delivery(path, manifest, catalog)


def test_catalog_membership_is_dated_and_line_scoped(delivery):
    path, manifest, catalog = delivery
    member = catalog["stations"][0]
    other_line = {**member, "line_id": "SYN_L2"}
    catalog["stations"].append(other_line)
    validate_catalog(catalog)  # Same station id in another line is allowed.
    member["valid_to"] = "2026-01-05T06:15:00-06:00"
    assert validate_delivery(path, manifest, catalog)["expected_intervals"] == 1
    catalog["stations"].append(dict(member))
    with pytest.raises(ValueError, match="Overlapping"):
        validate_catalog(catalog)


def test_revisions_respect_availability_and_are_not_concatenated(delivery):
    _, original, _ = delivery
    revision = deepcopy(original)
    revision.update(
        delivery_id="SYN_D_V2",
        version=2,
        supersedes=original["delivery_id"],
        available_at="2026-01-08T02:00:00-06:00",
        extracted_at="2026-01-08T02:00:00-06:00",
    )
    manifests = [revision, original]
    assert select_as_of(manifests, timestamp("2026-01-06T01:59:00-06:00")) == []
    assert select_as_of(manifests, timestamp("2026-01-07T03:00:00-06:00")) == [original]
    assert select_as_of(manifests, timestamp("2026-01-08T02:00:00-06:00")) == [revision]
    revision["supersedes"] = "nonexistent"
    with pytest.raises(ValueError, match="chain"):
        select_as_of(manifests, timestamp("2026-01-09T03:00:00-06:00"))


def test_overlapping_partitions_cannot_double_count(delivery):
    _, original, _ = delivery
    other = deepcopy(original)
    other.update(partition_id="OTHER", delivery_id="OTHER_V1")
    with pytest.raises(ValueError, match="Overlapping selected"):
        select_as_of([original, other], timestamp("2026-01-07T03:00:00-06:00"))


def test_complete_sparse_empty_file_is_verified_zero_not_parser_failure(delivery):
    path, manifest, catalog = delivery
    path.write_text(",".join(FIELDS) + "\n", encoding="utf-8")
    manifest.update(
        status="complete",
        zero_policy="verified_sparse",
        row_count=0,
        sha256=sha256(path.read_bytes()).hexdigest(),
        totals={c: 0 for c in COUNT_FIELDS},
    )
    result = validate_delivery(path, manifest, catalog)
    assert result["status_counts"] == {"verified_zero": 2}


def test_committed_example_checksum_and_control_totals():
    root = Path(__file__).resolve().parents[1] / "data/examples"
    manifest = json.loads((root / "delivery-manifest.json").read_text())
    catalog = json.loads((root / "station-catalog.json").read_text())
    result = validate_delivery(root / "validations.csv", manifest, catalog)
    assert result["status_counts"] == {"observed": 3, "unknown": 1}
