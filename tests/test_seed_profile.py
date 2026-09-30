import os
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

os.environ.setdefault("POSTGRES_URL", "postgresql://unused:unused@localhost/unused")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "segmentation"))

from seed_and_run import generate_day_events
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
