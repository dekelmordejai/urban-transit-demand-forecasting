from copy import deepcopy
from datetime import timezone

import pytest

from transit_demand.data.quality import timestamp
from transit_demand.evaluation.backtest import metrics, spatial_rollup, temporal_rollup
from transit_demand.features.catalogs import flags_at, validate_calendar, validate_incidents
from transit_demand.models.baselines import SeasonalBaseline


def incident(**kwargs):
    return {
        "incident_id": "SYN_I",
        "scope": "line",
        "line_id": "SYN_L",
        "station_id": None,
        "start": "2026-01-05T23:50:00-06:00",
        "end": "2026-01-06T00:10:00-06:00",
        "known_at": "2026-01-06T02:00:00-06:00",
        "kind": "station_closure",
        "source": "synthetic",
        **kwargs,
    }


def test_incident_half_open_cross_midnight_and_availability():
    events = [incident()]
    validate_incidents(events, {("SYN_L", "SYN_A"), ("SYN_L", "SYN_B")})
    a, b = timestamp("2026-01-06T00:00:00-06:00"), timestamp("2026-01-06T00:15:00-06:00")
    before, after = timestamp("2026-01-06T01:00:00-06:00"), timestamp("2026-01-06T03:00:00-06:00")
    assert not flags_at([], events, "SYN_L", "SYN_A", a, b, before)["station_closure"]
    assert flags_at([], events, "SYN_L", "SYN_B", a, b, after)["station_closure"]
    assert not flags_at([], events, "OTHER", "SYN_A", a, b, after)["station_closure"]
    events[0]["end"] = a.isoformat()
    assert not flags_at([], events, "SYN_L", "SYN_A", a, b, after)["station_closure"]


@pytest.mark.parametrize(
    "changes",
    [
        {"end": "2026-01-05T22:00:00-06:00"},
        {"scope": "line", "station_id": "SYN_A"},
        {"scope": "station", "station_id": "nonexistent"},
        {"known_at": "2026-01-05T00:00:00"},
    ],
)
def test_invalid_incident_scope_or_time(changes):
    with pytest.raises(ValueError):
        validate_incidents([incident(**changes)], {("SYN_L", "SYN_A")})


def test_calendar_unknown_is_not_ordinary_and_flags_may_overlap():
    calendar = [
        {
            "date": "2026-01-06",
            "is_holiday": True,
            "is_bridge_day": False,
            "is_school_break": True,
            "known_at": "2026-01-05T00:00:00-06:00",
            "source": "synthetic",
        }
    ]
    validate_calendar(calendar)
    a, b = timestamp("2026-01-06T06:00:00-06:00"), timestamp("2026-01-06T06:15:00-06:00")
    unknown = flags_at(calendar, [], "SYN_L", "SYN_A", a, b, timestamp("2026-01-04T00:00:00-06:00"))
    assert unknown["is_holiday"] is None
    known = flags_at(calendar, [], "SYN_L", "SYN_A", a, b, timestamp("2026-01-05T00:00:00-06:00"))
    assert known["is_holiday"] and known["is_school_break"]
    with pytest.raises(ValueError, match="Duplicate"):
        validate_calendar(calendar + calendar)


def training_row(value=10, **kwargs):
    return {
        "line_id": "SYN_L",
        "station_id": "SYN_A",
        "ds": "2026-01-05T06:00:00-06:00",
        "available_at": "2026-01-06T02:00:00-06:00",
        "y_observed": value,
        **kwargs,
    }


def test_baselines_never_use_future_truth_or_late_corrections():
    origin = timestamp("2026-01-12T03:00:00-06:00")
    target = timestamp("2026-01-12T06:00:00-06:00")
    model = SeasonalBaseline().fit([training_row()], origin)
    assert model.predict("SYN_L", "SYN_A", target) == 10
    assert model.predict("SYN_L", "UNKNOWN", target) is None
    with pytest.raises(ValueError, match="availability"):
        model.fit([training_row(999, available_at="2026-01-13T02:00:00-06:00")], origin)
    with pytest.raises(ValueError, match="availability"):
        model.fit([training_row(999, ds="2026-01-12T00:00:00-06:00")], origin)
    with pytest.raises(ValueError, match="Duplicate"):
        model.fit([training_row(), training_row()], origin)


def test_weekday_mean_has_hand_calculated_value_and_skips_unknown():
    history = [
        training_row(10),
        training_row(20, ds="2026-01-12T06:00:00-06:00", available_at="2026-01-13T02:00:00-06:00"),
        training_row(
            None, ds="2026-01-19T06:00:00-06:00", available_at="2026-01-20T02:00:00-06:00"
        ),
    ]
    origin = timestamp("2026-01-26T03:00:00-06:00")
    target = timestamp("2026-01-26T06:00:00-06:00")
    assert (
        SeasonalBaseline("weekday_slot_mean").fit(history, origin).predict("SYN_L", "SYN_A", target)
        == 15
    )
    assert SeasonalBaseline().fit(history, origin).predict("SYN_L", "SYN_A", target) == 20


def test_scores_report_missing_coverage_and_zero_denominator():
    result = metrics(
        [
            {"actual": 10, "prediction": 8},
            {"actual": 20, "prediction": 24},
            {"actual": None, "prediction": 3},
        ]
    )
    assert result["mae"] == 3 and result["wape"] == 0.2 and result["coverage"] == 2 / 3
    assert metrics([{"actual": 0, "prediction": 1}])["wape"] is None
    assert metrics([])["mae"] is None


def test_baseline_normalizes_utc_to_local_weekday_and_slot():
    origin = timestamp("2026-01-12T03:00:00-06:00").astimezone(timezone.utc)
    target = timestamp("2026-01-12T06:00:00-06:00").astimezone(timezone.utc)
    model = SeasonalBaseline().fit([training_row()], origin)
    assert model.predict("SYN_L", "SYN_A", target) == 10


def test_hierarchy_conservation_and_missing_propagation():
    rows = [
        {
            "origin": "2026-01-05T03:00:00-06:00",
            "model": "test",
            "day_offset": 1,
            "ds": "2026-01-06T06:00:00-06:00",
            "line_id": "SYN_L",
            "station_id": station,
            "actual": actual,
            "prediction": pred,
        }
        for station, actual, pred in [("SYN_A", 10, 12), ("SYN_B", None, 5)]
    ]
    result = spatial_rollup(rows, {("SYN_L", "SYN_A"), ("SYN_L", "SYN_B")})
    system = next(r for r in result if r["level"] == "system")
    assert system["prediction"] == 17 and system["actual"] is None
    with pytest.raises(ValueError, match="expected leaves"):
        spatial_rollup(rows[:1], {("SYN_L", "SYN_A"), ("SYN_L", "SYN_B")})


def test_hourly_aggregation_requires_all_four_base_buckets():
    rows = [
        {
            "origin": "2026-01-05T03:00:00-06:00",
            "model": "test",
            "day_offset": 1,
            "ds": f"2026-01-06T06:{minute:02d}:00-06:00",
            "level": "system",
            "series": "SYN",
            "actual": 10,
            "prediction": 11,
        }
        for minute in (0, 15, 30, 45)
    ]
    result = temporal_rollup(rows, 60)
    assert result[0]["actual"] == 40 and result[0]["prediction"] == 44
    with pytest.raises(ValueError, match="Incomplete"):
        temporal_rollup(rows[:3], 60)
    duplicate = deepcopy(rows)
    duplicate[3] = duplicate[0]
    with pytest.raises(ValueError, match="duplicate"):
        temporal_rollup(duplicate, 60)
