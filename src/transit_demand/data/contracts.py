"""Validate the agreed aggregate CSV without inferring missing observations."""
import csv
from datetime import datetime
from pathlib import Path

COUNT_FIELDS = (
    "TX_3_INGRESO", "TX_4_GRATUIDAD", "TX_7_TRANSBORDO", "TX_300_SALIDA", "TX_0_OTRO"
)
FIELDS = ("LINEA", "ID_ESTACION", "ESTACION", "FECHA", "HORA_15MIN", *COUNT_FIELDS)


def validate_csv(path: str | Path, *, allow_empty: bool = False) -> list[dict]:
    """Reject malformed, negative, duplicate and non-aligned records."""
    records, seen = [], set()
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != list(FIELDS):
            raise ValueError(f"Expected columns in order: {', '.join(FIELDS)}")
        for number, row in enumerate(reader, start=2):
            if None in row or any(value is None or not value.strip() for value in row.values()):
                raise ValueError(f"Row {number}: missing or excess fields")
            stamp = datetime.strptime(row["FECHA"] + " " + row["HORA_15MIN"], "%Y-%m-%d %H:%M:%S")
            if stamp.strftime("%Y-%m-%d %H:%M:%S") != row["FECHA"] + " " + row["HORA_15MIN"]:
                raise ValueError(f"Row {number}: noncanonical timestamp")
            if stamp.minute % 15 or stamp.second:
                raise ValueError(f"Row {number}: timestamp is not aligned to 15 minutes")
            key = (row["LINEA"], row["ID_ESTACION"], stamp)
            if key in seen:
                raise ValueError(f"Row {number}: duplicate station interval")
            seen.add(key)
            for field in COUNT_FIELDS:
                if not row[field].isascii() or not row[field].isdigit():
                    raise ValueError(f"Row {number}: {field} must be a nonnegative integer")
                row[field] = int(row[field])
            row["y_observed"] = sum(row[field] for field in COUNT_FIELDS[:3])
            records.append(row)
    if not records and not allow_empty:
        raise ValueError("No observations supplied")
    return records
