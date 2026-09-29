"""API contract tests — validate request/response shapes without a running server.

These test the core logic functions and Pydantic models used by the API.
"""
import sys
import os
import pytest
from datetime import datetime, timezone
from pydantic import ValidationError

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../services/ingestion')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../services/segmentation')))

from consumer import TelemetryEvent


class TestTelemetryEventValidation:
    """Validates the Pydantic schema used by the ingestion consumer."""

    def test_valid_event(self):
        evt = TelemetryEvent(
            vin="A" * 17,
            ts=datetime(2026, 9, 1, tzinfo=timezone.utc),
            seq=1,
            lat=12.9716,
            lon=77.5946,
            speed_kmh=30.0,
            odo_km=1000.0,
            ignition_status=True,
        )
        assert evt.vin == "A" * 17
        assert evt.speed_kmh == 30.0

    def test_invalid_vin_too_short(self):
        with pytest.raises(ValidationError):
            TelemetryEvent(
                vin="SHORT",
                ts=datetime(2026, 9, 1, tzinfo=timezone.utc),
                seq=1, lat=12.0, lon=77.0,
                speed_kmh=30.0, odo_km=1000.0,
                ignition_status=True,
            )

    def test_invalid_lat_out_of_range(self):
        with pytest.raises(ValidationError):
            TelemetryEvent(
                vin="A" * 17,
                ts=datetime(2026, 9, 1, tzinfo=timezone.utc),
                seq=1, lat=200.0, lon=77.0,
                speed_kmh=30.0, odo_km=1000.0,
                ignition_status=True,
            )

    def test_invalid_negative_speed(self):
        with pytest.raises(ValidationError):
            TelemetryEvent(
                vin="A" * 17,
                ts=datetime(2026, 9, 1, tzinfo=timezone.utc),
                seq=1, lat=12.0, lon=77.0,
                speed_kmh=-5.0, odo_km=1000.0,
                ignition_status=True,
            )

    def test_invalid_fuel_level_over_100(self):
        with pytest.raises(ValidationError):
            TelemetryEvent(
                vin="A" * 17,
                ts=datetime(2026, 9, 1, tzinfo=timezone.utc),
                seq=1, lat=12.0, lon=77.0,
                speed_kmh=30.0, odo_km=1000.0,
                ignition_status=True,
                fuel_level_pct=150.0,
            )

    def test_valid_ev_event_with_soc(self):
        evt = TelemetryEvent(
            vin="B" * 17,
            ts=datetime(2026, 9, 1, tzinfo=timezone.utc),
            seq=42,
            lat=-33.8688,
            lon=151.2093,
            speed_kmh=0.0,
            odo_km=50000.0,
            ignition_status=False,
            soc_pct=85.5,
        )
        assert evt.soc_pct == 85.5
        assert evt.fuel_level_pct is None

    def test_valid_event_types(self):
        for evt_type in ["TRIP_START", "TRIP_END", "IDLE_START", "IDLE_END", "HARSH_BRAKE", "HARSH_ACCELERATION", None]:
            evt = TelemetryEvent(
                vin="C" * 17,
                ts=datetime(2026, 9, 1, tzinfo=timezone.utc),
                seq=1, lat=12.0, lon=77.0,
                speed_kmh=30.0, odo_km=1000.0,
                ignition_status=True,
                evt=evt_type,
            )
            assert evt.evt == evt_type

    def test_invalid_event_type(self):
        with pytest.raises(ValidationError):
            TelemetryEvent(
                vin="D" * 17,
                ts=datetime(2026, 9, 1, tzinfo=timezone.utc),
                seq=1, lat=12.0, lon=77.0,
                speed_kmh=30.0, odo_km=1000.0,
                ignition_status=True,
                evt="INVALID_EVENT",
            )


class TestSegmentationEdgeCases:
    """Additional edge case tests for segmentation."""

    def test_empty_events(self):
        from segment import segment_vehicle
        trips, idles = segment_vehicle([], vin="EMPTYVIN000000001", fuel_type="petrol")
        assert trips == []
        assert idles == []

    def test_single_event(self):
        from segment import segment_vehicle
        events = [{
            "ts": datetime(2026, 9, 1, 8, 0, 0, tzinfo=timezone.utc),
            "lat": 12.0, "lon": 77.0, "speed_kmh": 50,
            "ignition_status": True, "odo_km": 100.0,
            "fuel_level_pct": 50, "soc_pct": None, "evt": "TRIP_START",
        }]
        trips, idles = segment_vehicle(events, vin="SINGLEVIN00000001", fuel_type="petrol")
        # Single event can't form a valid trip (no distance)
        assert len(trips) == 0

    def test_midnight_boundary_trip(self):
        """Trip that spans midnight boundary."""
        from segment import segment_vehicle
        events = [
            {"ts": datetime(2026, 9, 1, 23, 55, 0, tzinfo=timezone.utc), "lat": 12.0, "lon": 77.0, "speed_kmh": 0, "ignition_status": True, "odo_km": 100.0, "fuel_level_pct": 50, "soc_pct": None, "evt": "TRIP_START"},
            {"ts": datetime(2026, 9, 1, 23, 58, 0, tzinfo=timezone.utc), "lat": 12.01, "lon": 77.01, "speed_kmh": 40, "ignition_status": True, "odo_km": 102.0, "fuel_level_pct": 49, "soc_pct": None, "evt": None},
            {"ts": datetime(2026, 9, 2, 0, 5, 0, tzinfo=timezone.utc), "lat": 12.02, "lon": 77.02, "speed_kmh": 35, "ignition_status": True, "odo_km": 105.0, "fuel_level_pct": 48, "soc_pct": None, "evt": None},
            {"ts": datetime(2026, 9, 2, 0, 10, 0, tzinfo=timezone.utc), "lat": 12.03, "lon": 77.03, "speed_kmh": 0, "ignition_status": False, "odo_km": 108.0, "fuel_level_pct": 47, "soc_pct": None, "evt": "TRIP_END"},
        ]
        trips, idles = segment_vehicle(events, vin="MIDNIGHTVIN000001", fuel_type="diesel")
        assert len(trips) == 1
        assert trips[0]["distance_km"] == pytest.approx(8.0, abs=0.1)

    def test_ev_segmentation(self):
        """EV vehicle uses soc_pct and energy_used_kwh."""
        from segment import segment_vehicle
        events = [
            {"ts": datetime(2026, 9, 1, 8, 0, 0, tzinfo=timezone.utc), "lat": 12.0, "lon": 77.0, "speed_kmh": 0, "ignition_status": True, "odo_km": 100.0, "fuel_level_pct": None, "soc_pct": 90.0, "evt": "TRIP_START"},
            {"ts": datetime(2026, 9, 1, 8, 5, 0, tzinfo=timezone.utc), "lat": 12.01, "lon": 77.01, "speed_kmh": 40, "ignition_status": True, "odo_km": 105.0, "fuel_level_pct": None, "soc_pct": 85.0, "evt": None},
            {"ts": datetime(2026, 9, 1, 8, 10, 0, tzinfo=timezone.utc), "lat": 12.02, "lon": 77.02, "speed_kmh": 0, "ignition_status": False, "odo_km": 110.0, "fuel_level_pct": None, "soc_pct": 80.0, "evt": "TRIP_END"},
        ]
        trips, idles = segment_vehicle(events, vin="EVTESTVIN00000001", fuel_type="ev")
        assert len(trips) == 1
        assert trips[0]["fuel_used_l"] is None
        assert trips[0]["energy_used_kwh"] is not None
        assert trips[0]["energy_used_kwh"] > 0

    def test_multiple_fuel_types(self):
        """Verify cost calculation uses correct burn rate per fuel type."""
        from config import IDLE_BURN_RATE
        assert IDLE_BURN_RATE["petrol"] == 0.6
        assert IDLE_BURN_RATE["diesel"] == 0.5
        assert IDLE_BURN_RATE["hybrid"] == 0.3
        assert IDLE_BURN_RATE["ev"] == 0.9
