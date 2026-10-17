import json
from hashlib import sha256

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pathlib import Path

from transit_demand.demo import run_demo


def test_demo_replays_versions_preserves_unknowns_and_reproduces_bytes(tmp_path):
    a, b = tmp_path / "run_a", tmp_path / "run_b"
    result = run_demo(a)
    run_demo(b)
    checksums = json.loads((a / "checksums.json").read_text())
    assert checksums == json.loads((b / "checksums.json").read_text())
    for name, digest in checksums.items():
        assert sha256((a / name).read_bytes()).hexdigest() == digest
    assert "SYN_DAY_10_V1" in result["origins"][0]["selected_deliveries"]
    assert "SYN_DAY_10_V2" not in result["origins"][0]["selected_deliveries"]
    assert "SYN_DAY_10_V2" in result["origins"][2]["selected_deliveries"]
    quality = {r["delivery_id"]: r for r in json.loads((a / "quality.json").read_text())}
    assert quality["SYN_DAY_12_V1"]["status_counts"]["verified_zero"] == 1
    assert quality["SYN_DAY_20_V1"]["status_counts"]["capture_outage"] == 1
    assert quality["SYN_DAY_30_V1"]["status_counts"]["unknown"] == 1
    assert len(result["scores"]) == 54
    assert result["calendar_incident_smoke"]["traffic_delay"]
    schemas = Path(__file__).resolve().parents[1] / "schemas"
    for name, source in [
        ("delivery-manifest", "synthetic_day_10_v2.manifest.json"),
        ("station-catalog", "station_catalog.json"),
    ]:
        schema = json.loads((schemas / f"{name}.schema.json").read_text())
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(
            json.loads((a / "synthetic_input" / source).read_text())
        )
    with pytest.raises(ValueError, match="new or empty"):
        run_demo(a)
