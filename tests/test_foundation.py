import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from transit_demand import __version__
from transit_demand.data.contracts import FIELDS, validate_csv

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "data/examples/validations.csv"


def test_package_and_entry_policy():
    assert __version__ == "0.2.0"
    rows = validate_csv(EXAMPLE)
    assert [r["y_observed"] for r in rows] == [25, 40, 0]
    assert rows[0]["TX_0_OTRO"] == 1
    assert rows[0]["TX_300_SALIDA"] == 8


@pytest.mark.parametrize("field,value", [
    ("TX_3_INGRESO", "-1"), ("TX_4_GRATUIDAD", "1.5"),
    ("HORA_15MIN", "06:07:00"), ("FECHA", "2026-02-30"),
    ("LINEA", ""),
])
def test_invalid_records_fail(tmp_path, field, value):
    with EXAMPLE.open() as stream:
        row = next(csv.DictReader(stream))
    row[field] = value
    path = tmp_path / "invalid.csv"
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerow(row)
    with pytest.raises(ValueError):
        validate_csv(path)


def test_duplicate_rejected(tmp_path):
    lines = EXAMPLE.read_text().splitlines()
    path = tmp_path / "duplicate.csv"
    path.write_text("\n".join([lines[0], lines[1], lines[1]]))
    with pytest.raises(ValueError, match="duplicate"):
        validate_csv(path)


def test_cli_success_and_missing_file():
    result = subprocess.run(
        [sys.executable, "-m", "transit_demand", "validate", str(EXAMPLE)],
        check=False, capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "observed entries=65" in result.stdout
    missing = subprocess.run(
        [sys.executable, "-m", "transit_demand", "validate", "does-not-exist.csv"],
        check=False, capture_output=True, text=True,
    )
    assert missing.returncode == 2


@pytest.mark.parametrize("name", ["calendar", "incidents", "validations"])
def test_schemas_and_synthetic_examples(name):
    schema = json.loads((ROOT / f"schemas/{name}.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    if name == "validations":
        records = validate_csv(EXAMPLE)
        for row in records:
            row.pop("y_observed")
    else:
        records = json.loads((ROOT / f"data/examples/{name}.json").read_text())
    for record in records:
        validator.validate(record)
