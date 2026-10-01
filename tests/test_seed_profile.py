import os
import random
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

os.environ.setdefault("POSTGRES_URL", "postgresql://unused:unused@localhost/unused")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "segmentation"))

from seed_and_run import generate_day_events
from seed_and_run import is_already_seeded
from segment import segment_vehicle


@pytest.mark.parametrize("fuel_type", ["petrol", "diesel", "hybrid", "ev"])
def test_seeded_shift_has_plausible_routes_and_consumption(fuel_type):
    random.seed(20260930)
    events = generate_day_events(
        "TESTVIN0000000001",
        fuel_type,
        datetime(2026, 9, 1, tzinfo=timezone.utc),
        seq_offset=0,
        odo_start=65000,
    )

    timestamps = [datetime.fromisoformat(event["ts"]) for event in events]
    assert timestamps == sorted(timestamps)
    assert (timestamps[-1] - timestamps[0]).total_seconds() <= 600 * 60
    assert 2 <= sum(event["evt"] == "TRIP_START" for event in events) <= 4

    odometers = [event["odo_km"] for event in events]
    assert odometers == sorted(odometers)
    assert 40 <= odometers[-1] - odometers[0] <= 160

    rows = [{**event, "ts": datetime.fromisoformat(event["ts"])} for event in events]
    trips, idles = segment_vehicle(rows, "TESTVIN0000000001", fuel_type)
    assert 2 <= len(trips) <= 4
    assert 40 <= sum(trip["distance_km"] for trip in trips) <= 160
    assert 1 <= sum(trip["duration_min"] for trip in trips) <= 600
    assert idles

    if fuel_type == "ev":
        assert all((trip["energy_used_kwh"] or 0) > 0 for trip in trips)
    else:
        assert all((trip["fuel_used_l"] or 0) > 0 for trip in trips)


def test_segmented_fuel_usage_uses_vehicle_tank_capacity():
    events = [
        {
            "ts": datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc),
            "lat": 13.0, "lon": 80.0, "speed_kmh": 0,
            "odo_km": 1000, "ignition_status": True,
            "fuel_level_pct": 80, "soc_pct": None, "evt": "TRIP_START",
        },
        {
            "ts": datetime(2026, 9, 1, 8, 10, tzinfo=timezone.utc),
            "lat": 13.1, "lon": 80.1, "speed_kmh": 30,
            "odo_km": 1010, "ignition_status": True,
            "fuel_level_pct": 60, "soc_pct": None, "evt": None,
        },
        {
            "ts": datetime(2026, 9, 1, 8, 20, tzinfo=timezone.utc),
            "lat": 13.2, "lon": 80.2, "speed_kmh": 0,
            "odo_km": 1020, "ignition_status": False,
            "fuel_level_pct": 40, "soc_pct": None, "evt": "TRIP_END",
        },
    ]
    trips, _ = segment_vehicle(
        events, "TESTVIN0000000001", "petrol", tank_capacity_l=Decimal("40")
    )

    assert len(trips) == 1
    assert trips[0]["fuel_used_l"] == pytest.approx(16)


@pytest.mark.parametrize(
    ("seed_state", "expected"),
    [
        ((True, True, True), True),
        ((False, False, False), False),
        ((True, True, False), False),
        ((True, False, True), False),
    ],
)
def test_seed_is_skipped_only_when_core_data_is_present(seed_state, expected):
    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def execute(self, _query):
            pass

        def fetchone(self):
            return seed_state

    class Connection:
        def cursor(self):
            return Cursor()

    assert is_already_seeded(Connection()) is expected
