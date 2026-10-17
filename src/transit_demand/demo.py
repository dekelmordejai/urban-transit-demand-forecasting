"""Offline, deterministic synthetic quality and backtesting demonstration."""

import csv
import html
import json
import random
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from importlib.metadata import version

from transit_demand.data.contracts import COUNT_FIELDS, FIELDS
from transit_demand import __version__
from transit_demand.data.quality import STEP, ZONE, select_as_of, validate_delivery
from transit_demand.evaluation.backtest import metrics, spatial_rollup, temporal_rollup
from transit_demand.features.catalogs import flags_at, validate_calendar, validate_incidents
from transit_demand.models.baselines import SeasonalBaseline

SEED = 1729
STATIONS = [("SYN_L1", "SYN_A"), ("SYN_L1", "SYN_B"), ("SYN_L2", "SYN_C"), ("SYN_L2", "SYN_D")]
START = datetime(2026, 1, 5, tzinfo=ZONE)
DAYS = 63


def write_json(path: Path, data) -> None:
    path.write_text(
        json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def write_csv(path: Path, records: list[dict], fields: list | tuple) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)


def generate(output: Path) -> tuple[list[dict], dict]:
    """Generate files, including a late revision, sparse zero, gap and unknown bucket."""
    rng = random.Random(SEED)
    catalog = {
        "version": "synthetic-catalog-v1",
        "stations": [
            {
                "line_id": line,
                "station_id": station,
                "name": "Synthetic " + station,
                "valid_from": START.isoformat(),
                "valid_to": (START + timedelta(days=DAYS)).isoformat(),
            }
            for line, station in STATIONS
        ],
    }
    manifests = []
    day10 = None
    for day in range(DAYS):
        start, rows, gaps = START + timedelta(days=day), [], []
        for index, (line, station) in enumerate(STATIONS):
            for slot in range(96):
                ds = start + slot * STEP
                if day == 12 and index == 0 and slot == 0:
                    continue  # Documented complete sparse export: verified zero.
                if (day, index, slot) in {(20, 0, 28), (30, 1, 32)}:
                    if day == 20:
                        gaps.append(
                            {
                                "line_id": line,
                                "station_id": station,
                                "start": ds.isoformat(),
                                "end": (ds + STEP).isoformat(),
                                "reason": "capture_outage",
                            }
                        )
                    continue
                y = (
                    0
                    if slot < 20
                    else max(
                        0,
                        35
                        + index * 9
                        + (18 if ds.weekday() < 5 else -10)
                        + (35 if 28 <= slot < 36 or 68 <= slot < 76 else 0)
                        + rng.randint(-6, 6),
                    )
                )
                free, transfers = y // 10, y // 5
                rows.append(
                    dict(
                        zip(
                            FIELDS,
                            [
                                line,
                                station,
                                "Synthetic " + station,
                                ds.date().isoformat(),
                                ds.strftime("%H:%M:%S"),
                                y - free - transfers,
                                free,
                                transfers,
                                y // 2,
                                rng.randint(0, 2),
                            ],
                        )
                    )
                )
        name = f"synthetic_day_{day:02d}_v1.csv"
        path = output / name
        write_csv(path, rows, FIELDS)
        available = start + timedelta(days=1, hours=2)
        manifest = {
            "delivery_id": f"SYN_DAY_{day:02d}_V1",
            "partition_id": f"SYN_DAY_{day:02d}",
            "version": 1,
            "supersedes": None,
            "filename": name,
            "sha256": sha256(path.read_bytes()).hexdigest(),
            "start": start.isoformat(),
            "end": (start + timedelta(days=1)).isoformat(),
            "scope": [{"line_id": a, "station_id": b} for a, b in STATIONS],
            "catalog_version": catalog["version"],
            "extracted_at": available.isoformat(),
            "available_at": available.isoformat(),
            "status": "partial" if day in {20, 30} else "complete",
            "zero_policy": "verified_sparse" if day == 12 else "explicit",
            "row_count": len(rows),
            "totals": {c: sum(r[c] for r in rows) for c in COUNT_FIELDS},
            "gaps": gaps,
            "rules_version": "synthetic-rules-v1",
        }
        manifests.append(manifest)
        write_json(output / name.replace(".csv", ".manifest.json"), manifest)
        if day == 10:
            day10 = ([dict(row) for row in rows], dict(manifest))
    rows, revision = day10
    rows[28]["TX_3_INGRESO"] += 5
    path = output / "synthetic_day_10_v2.csv"
    write_csv(path, rows, FIELDS)
    revision.update(
        {
            "delivery_id": "SYN_DAY_10_V2",
            "version": 2,
            "supersedes": "SYN_DAY_10_V1",
            "filename": path.name,
            "sha256": sha256(path.read_bytes()).hexdigest(),
            "extracted_at": (START + timedelta(days=52, hours=2)).isoformat(),
            "available_at": (START + timedelta(days=52, hours=2)).isoformat(),
            "totals": {c: sum(r[c] for r in rows) for c in COUNT_FIELDS},
        }
    )
    manifests.append(revision)
    write_json(output / "synthetic_day_10_v2.manifest.json", revision)
    write_json(output / "manifests.json", manifests)
    write_json(output / "station_catalog.json", catalog)
    return manifests, catalog


def run_demo(output: str | Path) -> dict:
    """Run without network or external data; output directory must be new or empty."""
    output = Path(output)
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("Demo output directory must be new or empty; choose another path")
    output.mkdir(parents=True, exist_ok=True)
    source = output / "synthetic_input"
    source.mkdir()
    manifests, catalog = generate(source)
    validated = {
        m["delivery_id"]: validate_delivery(source / m["filename"], m, catalog) for m in manifests
    }
    quality = [{k: v for k, v in r.items() if k != "grid"} for r in validated.values()]
    write_json(output / "quality.json", quality)
    calendar = [
        {
            "date": (START + timedelta(days=day)).date().isoformat(),
            "is_holiday": False,
            "is_bridge_day": False,
            "is_school_break": False,
            "known_at": START.isoformat(),
            "source": "synthetic, not official",
        }
        for day in range(DAYS)
    ]
    incident = [
        {
            "incident_id": "SYN_CROSS_MIDNIGHT",
            "scope": "line",
            "line_id": "SYN_L1",
            "station_id": None,
            "start": (START + timedelta(days=20, hours=23, minutes=50)).isoformat(),
            "end": (START + timedelta(days=21, minutes=10)).isoformat(),
            "known_at": (START + timedelta(days=22)).isoformat(),
            "kind": "traffic_delay",
            "source": "synthetic, not an institutional incident",
        }
    ]
    validate_calendar(calendar)
    validate_incidents(incident, set(STATIONS))
    write_json(source / "calendar.json", calendar)
    write_json(source / "incidents.json", incident)
    final = select_as_of(manifests, START + timedelta(days=90))
    truth = {
        (r["line_id"], r["station_id"], r["ds"]): r["y_observed"]
        for m in final
        for r in validated[m["delivery_id"]]["grid"]
    }
    leaves, replay = [], []
    for day in (49, 51, 53, 55, 57):
        origin = START + timedelta(days=day, hours=3)
        selected = select_as_of(manifests, origin)
        history = [r for m in selected for r in validated[m["delivery_id"]]["grid"]]
        replay.append(
            {
                "origin": origin.isoformat(),
                "selected_deliveries": [m["delivery_id"] for m in selected],
                "last_observed_day": max(r["ds"] for r in history),
                "history_unknown_buckets": sum(r["y_observed"] is None for r in history),
            }
        )
        for method in ("seasonal_naive", "weekday_slot_mean"):
            model = SeasonalBaseline(method).fit(history, origin)
            for offset in (1, 2, 3):
                for slot in range(96):
                    target = (origin + timedelta(days=offset)).replace(
                        hour=0, minute=0
                    ) + slot * STEP
                    for line, station in STATIONS:
                        leaves.append(
                            {
                                "origin": origin.isoformat(),
                                "model": method,
                                "day_offset": offset,
                                "ds": target.isoformat(),
                                "line_id": line,
                                "station_id": station,
                                "prediction": model.predict(line, station, target),
                                "actual": truth[line, station, target.isoformat()],
                            }
                        )
    rolled = spatial_rollup(leaves, set(STATIONS))
    forecasts = [r for minutes in (15, 60, 1440) for r in temporal_rollup(rolled, minutes)]
    write_csv(output / "forecasts.csv", forecasts, tuple(forecasts[0]))
    grouped = defaultdict(list)
    for r in forecasts:
        grouped[r["model"], r["day_offset"], r["level"], r["interval_minutes"]].append(r)
    scores = [
        {
            "model": model,
            "day_offset": day,
            "level": level,
            "interval_minutes": minutes,
            **metrics(rows),
        }
        for (model, day, level, minutes), rows in sorted(grouped.items())
    ]
    flag = flags_at(
        calendar,
        incident,
        "SYN_L1",
        "SYN_A",
        START + timedelta(days=21),
        START + timedelta(days=21, minutes=15),
        START + timedelta(days=23),
    )
    summary = {
        "provenance": "SYNTHETIC ONLY: invented counts and catalogs; no institutional data",
        "seed": SEED,
        "days": DAYS,
        "stations": len(STATIONS),
        "origins": replay,
        "software": {
            "package": __version__,
            "python": sys.version.split()[0],
            "tzdata": version("tzdata"),
            "jsonschema": version("jsonschema"),
        },
        "day_offsets": [1, 2, 3],
        "target_definition": "Full next local days; first bucket is 21h after 03:00 origin",
        "truth_policy": "Latest synthetic revision as of day 90; never used for fitting before availability",
        "calendar_incident_smoke": flag,
        "scores": scores,
        "limitations": [
            "No real-data acceptance",
            "No ML or existing calibration comparison",
            "No predictive intervals, MinT, causal lag healing or operational claims",
            "Fixed synthetic station scope and 2026 local-time grid; no clock-change policy",
            "Overlapping forecast origins are not independent samples",
            "Synthetic error metrics do not estimate institutional forecasting accuracy",
        ],
    }
    write_json(output / "metrics.json", summary)
    write_json(output / "replay.json", replay)
    render_report(output, summary, forecasts)
    hashes = {
        p.relative_to(output).as_posix(): sha256(p.read_bytes()).hexdigest()
        for p in sorted(output.rglob("*"))
        if p.is_file()
    }
    write_json(output / "checksums.json", hashes)
    return summary


def render_report(output: Path, summary: dict, forecasts: list[dict]) -> None:
    rows = [
        r for r in summary["scores"] if r["level"] == "system" and r["interval_minutes"] == 1440
    ]
    lines = [
        "# Synthetic transit demand demonstration",
        "",
        "**SYNTHETIC ONLY — not institutional performance.**",
        "",
        "Deterministic seed 1729; 63 days, 4 fictional stations, 2 lines; 5 replayed origins.",
        "",
        "Two statistical baselines; full local forecast days +1/+2/+3, at 15-minute/hourly/daily resolution.",
        "",
        "## Quality evidence",
        "",
        "All 64 deliveries passed checksum, row-count and per-code reconciliation.",
        "Sparse day 12: one verified zero. Day 20: one capture outage. Day 30: one unknown bucket.",
        "Day 10 revision V2 is visible only after its availability on day 52. Missing history stays unknown.",
        "",
        "## System daily scores",
        "",
        "| Model | Day offset | MAE | WAPE | Coverage |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        wape = "undefined" if row["wape"] is None else f"{row['wape']:.2%}"
        mae = "undefined" if row["mae"] is None else f"{row['mae']:.2f}"
        lines.append(
            f"| {row['model']} | +{row['day_offset']} | {mae} | {wape} | {row['scored']}/{row['expected']} |"
        )
    lines += [
        "",
        "MAE is measured in recorded entries per system-day. WAPE is undefined when actual total is zero.",
        "All metrics by station/line/system and 15/60/1440 minutes are in metrics.json.",
        "",
        "## Limits and institutional gate",
        "",
        *["- " + item for item in summary["limitations"]],
        "",
        "A real pilot requires an authorized channel, source-team confirmations and external secure storage.",
        "Run the same controls against that pilot before training any institutional model.",
        "",
    ]
    markdown = "\n".join(lines)
    (output / "report.md").write_text(markdown, encoding="utf-8", newline="\n")
    table = ""
    for r in rows:
        cells = [
            r["model"],
            f"+{r['day_offset']}",
            f"{r['mae']:.2f}",
            f"{r['wape']:.2%}" if r["wape"] is not None else "undefined",
            f"{r['scored']}/{r['expected']}",
        ]
        table += "<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in cells) + "</tr>"
    example = [
        r
        for r in forecasts
        if r["level"] == "system"
        and r["model"] == "seasonal_naive"
        and r["day_offset"] == 1
        and r["interval_minutes"] == 15
        and r["origin"] == summary["origins"][0]["origin"]
    ]
    example.sort(key=lambda r: r["ds"])
    ceiling = max(max(r["actual"], r["prediction"]) for r in example) * 1.1
    chart = '<svg viewBox="0 0 960 310" role="img" aria-label="Synthetic actual and seasonal naive system entries by quarter hour"><title>Synthetic system entries per 15 minutes</title>'
    for fraction in (0, 0.5, 1):
        y = 260 - 220 * fraction
        chart += f'<line x1="60" x2="920" y1="{y}" y2="{y}" stroke="#d8e1e8"/><text x="5" y="{y + 5}" font-size="13" fill="#50677c">{ceiling * fraction:.0f}</text>'
    for field, color, dash in [
        ("actual", "#126a75", ""),
        ("prediction", "#b35725", 'stroke-dasharray="6 4"'),
    ]:
        points = " ".join(
            f"{60 + 860 * i / 95:.2f},{260 - 220 * r[field] / ceiling:.2f}"
            for i, r in enumerate(example)
        )
        chart += (
            f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2.5" {dash}/>'
        )
    for slot, label in [(0, "00:00"), (24, "06:00"), (48, "12:00"), (72, "18:00"), (95, "23:45")]:
        chart += f'<text x="{60 + 860 * slot / 95}" y="288" text-anchor="middle" font-size="13" fill="#50677c">{label}</text>'
    chart += "</svg>"
    limitations = "".join(f"<li>{html.escape(item)}</li>" for item in summary["limitations"])
    document = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Synthetic Transit Demo</title>
<style>body{font:16px/1.6 system-ui;max-width:1080px;margin:48px auto;padding:0 24px;color:#183047;background:#f5f8fb}
h1{font-size:38px;line-height:1.16;margin:10px 0 20px}h2{font-size:23px;margin-top:0}h3{font-size:17px}
.tag{color:#8a3300;font-weight:700;letter-spacing:.06em;font-size:13px}.lede{max-width:800px;color:#50677c}
section{padding:28px;background:white;border:1px solid #dde5ec;border-radius:12px;margin:24px 0}
.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.card{padding:16px;background:#e7eff5;border-radius:8px}
.card b{display:block;font-size:26px}table{border-collapse:collapse;width:100%;font-size:14px}
td,th{text-align:left;padding:12px 8px;border-bottom:1px solid #dde5ec}th{color:#50677c}svg{width:100%;height:auto}
.legend{display:flex;gap:24px;font-size:14px}.note{color:#50677c;font-size:14px}a{color:#126a75}
@media(max-width:650px){.cards{grid-template-columns:repeat(2,1fr)}h1{font-size:30px}section{padding:16px}.tablewrap{overflow:auto}}
</style><header><div class="tag">SYNTHETIC DATA · REPRODUCIBLE ENGINEERING DEMO</div>
<h1>Urban Transit Demand Forecasting</h1><p class="lede">From versioned data deliveries to availability-aware baseline evaluation.
All counts, stations and incidents are fictional. These results do not estimate institutional forecasting accuracy.</p></header>
<div class="cards"><div class="card"><b>63</b>synthetic days</div><div class="card"><b>4</b>fictional stations</div>
<div class="card"><b>5</b>forecast origins</div><div class="card"><b>2</b>statistical baselines</div></div>
<section><h2>Data quality and historical availability</h2><p>64 deliveries pass checksum, row-count and transaction-total reconciliation.</p>
<ul><li>Day 12: one verified sparse zero, supported by a complete-delivery declaration.</li>
<li>Day 20: one capture outage; day 30: one unknown bucket. Neither becomes a zero.</li>
<li>Day 10 revision: V2 becomes available on day 52. Earlier origins retain V1.</li></ul>
<p class="note">Missingness, catalog scope and revision selection remain explicit in the experiment outputs.</p></section>
<section><h2>One synthetic day, at 15-minute resolution</h2>
<p class="note">System totals · first forecast origin · next local day · recorded entries per bucket</p>"""
    document += (
        chart
        + """<div class="legend"><span style="color:#126a75">━ Synthetic actual</span>
<span style="color:#b35725">┄ Seasonal naive prediction</span></div></section>
<section><h2>System daily baseline results</h2><div class="tablewrap"><table><thead><tr>
<th>Model</th><th>Day offset</th><th>MAE</th><th>WAPE</th><th>Scored / expected</th></tr></thead><tbody>"""
    )
    document += (
        table
        + """</tbody></table></div><p class="note">MAE: recorded entries per system-day.
Day offsets +1/+2/+3 are full next local days, not exact 24/48/72-hour lead times.
Scores pool five origins. Overlapping origins are not independent samples. WAPE is undefined if the actual total is zero.</p></section>
<section><h2>What is implemented — and what remains</h2><p>Normalized delivery controls, calendar/incident validation,
seasonal naive and weekday-slot mean baselines, D−1 replay, and bottom-up spatial/temporal point sums.</p><ul>"""
    )
    document += (
        limitations
        + """</ul><p>Next institutional gate: an authorized pilot extract, source-team confirmations and a controlled storage environment.</p></section>
<footer><p>Inspect the evidence: <a href="metrics.json">all 54 score groups</a> · <a href="quality.json">quality controls</a> ·
<a href="replay.json">availability replay</a> · <a href="forecasts.csv">forecast rows</a> · <a href="checksums.json">SHA-256 checksums</a></p>
<p class="note">Seed 1729 · Offline after installation · No institutional data · No trained ML model</p></footer></html>"""
    )
    (output / "report.html").write_text(document, encoding="utf-8", newline="\n")
