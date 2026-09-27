import sys
import os
import pytest
from datetime import datetime, timezone

# Add the services/segmentation directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../services/segmentation')))

from segment import segment_vehicle

def test_segmentation_detects_simple_trip():
    # A single continuous trip with no in-trip idle > threshold
    events = [
        {"ts": datetime(2026, 9, 1, 8, 0, 0, tzinfo=timezone.utc), "lat": 12.0, "lon": 77.0, "speed_kmh": 0, "ignition_status": True, "odo_km": 100.0, "fuel_level_pct": 50, "soc_pct": None, "evt": "TRIP_START"},
        {"ts": datetime(2026, 9, 1, 8, 0, 10, tzinfo=timezone.utc), "lat": 12.0, "lon": 77.01, "speed_kmh": 30, "ignition_status": True, "odo_km": 100.1, "fuel_level_pct": 49.9, "soc_pct": None, "evt": None},
        {"ts": datetime(2026, 9, 1, 8, 5, 0, tzinfo=timezone.utc), "lat": 12.0, "lon": 77.05, "speed_kmh": 40, "ignition_status": True, "odo_km": 103.5, "fuel_level_pct": 48.0, "soc_pct": None, "evt": None},
        {"ts": datetime(2026, 9, 1, 8, 10, 0, tzinfo=timezone.utc), "lat": 12.0, "lon": 77.10, "speed_kmh": 0, "ignition_status": True, "odo_km": 105.0, "fuel_level_pct": 47.0, "soc_pct": None, "evt": None},
        {"ts": datetime(2026, 9, 1, 8, 10, 30, tzinfo=timezone.utc), "lat": 12.0, "lon": 77.10, "speed_kmh": 0, "ignition_status": False, "odo_km": 105.0, "fuel_level_pct": 47.0, "soc_pct": None, "evt": "TRIP_END"},
    ]
    trips, idle_events = segment_vehicle(events, vin="TESTVIN0000000001", fuel_type="petrol")
    
    assert len(trips) == 1
    assert trips[0]["distance_km"] == pytest.approx(5.0, abs=0.1)
    # The 30 seconds at the end is an idle but < MIN_IDLE_DURATION_SEC (60s), so it shouldn't be recorded
    assert len(idle_events) == 0


def test_segmentation_detects_in_trip_idle():
    # A trip that includes a long stop mid-trip (90 seconds)
    events = [
        {"ts": datetime(2026, 9, 1, 8, 0, 0, tzinfo=timezone.utc), "lat": 12.0, "lon": 77.0, "speed_kmh": 0, "ignition_status": True, "odo_km": 100.0, "fuel_level_pct": 50, "soc_pct": None, "evt": "TRIP_START"},
        {"ts": datetime(2026, 9, 1, 8, 1, 0, tzinfo=timezone.utc), "lat": 12.0, "lon": 77.01, "speed_kmh": 30, "ignition_status": True, "odo_km": 101.0, "fuel_level_pct": 49.5, "soc_pct": None, "evt": None},
        # Stops for 90 seconds (in-trip idle)
        {"ts": datetime(2026, 9, 1, 8, 2, 0, tzinfo=timezone.utc), "lat": 12.0, "lon": 77.02, "speed_kmh": 0, "ignition_status": True, "odo_km": 101.5, "fuel_level_pct": 49.0, "soc_pct": None, "evt": None},
        {"ts": datetime(2026, 9, 1, 8, 3, 30, tzinfo=timezone.utc), "lat": 12.0, "lon": 77.02, "speed_kmh": 30, "ignition_status": True, "odo_km": 101.5, "fuel_level_pct": 48.5, "soc_pct": None, "evt": None},
        # Ends trip
        {"ts": datetime(2026, 9, 1, 8, 5, 0, tzinfo=timezone.utc), "lat": 12.0, "lon": 77.05, "speed_kmh": 0, "ignition_status": False, "odo_km": 105.0, "fuel_level_pct": 47.0, "soc_pct": None, "evt": "TRIP_END"},
    ]
    trips, idle_events = segment_vehicle(events, vin="TESTVIN0000000002", fuel_type="diesel")
    
    assert len(trips) == 1
    assert len(idle_events) == 1
    assert idle_events[0]["idle_type"] == "in_trip"
    assert idle_events[0]["duration_min"] == pytest.approx(1.5, abs=0.1)


def test_segmentation_ignores_short_stops():
    # A trip that includes a short stop mid-trip (30 seconds, less than 60s threshold)
    events = [
        {"ts": datetime(2026, 9, 1, 8, 0, 0, tzinfo=timezone.utc), "lat": 12.0, "lon": 77.0, "speed_kmh": 0, "ignition_status": True, "odo_km": 100.0, "fuel_level_pct": 50, "soc_pct": None, "evt": "TRIP_START"},
        {"ts": datetime(2026, 9, 1, 8, 1, 0, tzinfo=timezone.utc), "lat": 12.0, "lon": 77.01, "speed_kmh": 30, "ignition_status": True, "odo_km": 101.0, "fuel_level_pct": 49.5, "soc_pct": None, "evt": None},
        # Stops for 30 seconds
        {"ts": datetime(2026, 9, 1, 8, 2, 0, tzinfo=timezone.utc), "lat": 12.0, "lon": 77.02, "speed_kmh": 0, "ignition_status": True, "odo_km": 101.5, "fuel_level_pct": 49.0, "soc_pct": None, "evt": None},
        {"ts": datetime(2026, 9, 1, 8, 2, 30, tzinfo=timezone.utc), "lat": 12.0, "lon": 77.02, "speed_kmh": 30, "ignition_status": True, "odo_km": 101.5, "fuel_level_pct": 48.8, "soc_pct": None, "evt": None},
        # Ends trip
        {"ts": datetime(2026, 9, 1, 8, 5, 0, tzinfo=timezone.utc), "lat": 12.0, "lon": 77.05, "speed_kmh": 0, "ignition_status": False, "odo_km": 105.0, "fuel_level_pct": 47.0, "soc_pct": None, "evt": "TRIP_END"},
    ]
    trips, idle_events = segment_vehicle(events, vin="TESTVIN0000000003", fuel_type="hybrid")
    
    assert len(trips) == 1
    assert len(idle_events) == 0  # No idle events should be created


def test_segmentation_depot_idle():
    # Vehicle idles without ever starting a trip (e.g. warming up in the depot)
    events = [
        # Ignition turns on, but speed is 0
        {"ts": datetime(2026, 9, 1, 8, 0, 0, tzinfo=timezone.utc), "lat": 12.0, "lon": 77.0, "speed_kmh": 0, "ignition_status": True, "odo_km": 100.0, "fuel_level_pct": 50, "soc_pct": None, "evt": "IDLE_START"},
        {"ts": datetime(2026, 9, 1, 8, 5, 0, tzinfo=timezone.utc), "lat": 12.0, "lon": 77.0, "speed_kmh": 0, "ignition_status": True, "odo_km": 100.0, "fuel_level_pct": 49.5, "soc_pct": None, "evt": None},
        # Ignition turns off, still 0 speed
        {"ts": datetime(2026, 9, 1, 8, 10, 0, tzinfo=timezone.utc), "lat": 12.0, "lon": 77.0, "speed_kmh": 0, "ignition_status": False, "odo_km": 100.0, "fuel_level_pct": 49.0, "soc_pct": None, "evt": "IDLE_END"},
    ]
    trips, idle_events = segment_vehicle(events, vin="TESTVIN0000000004", fuel_type="diesel")
    
    assert len(trips) == 0
    assert len(idle_events) == 1
    assert idle_events[0]["idle_type"] == "depot"
    assert idle_events[0]["duration_min"] == pytest.approx(10.0, abs=0.1)


def test_segmentation_edge_case_no_ignition_off():
    # A trip that abruptly stops without an ignition-off marker or TRIP_END, just ends
    events = [
        {"ts": datetime(2026, 9, 1, 8, 0, 0, tzinfo=timezone.utc), "lat": 12.0, "lon": 77.0, "speed_kmh": 0, "ignition_status": True, "odo_km": 100.0, "fuel_level_pct": 50, "soc_pct": None, "evt": "TRIP_START"},
        {"ts": datetime(2026, 9, 1, 8, 5, 0, tzinfo=timezone.utc), "lat": 12.0, "lon": 77.05, "speed_kmh": 40, "ignition_status": True, "odo_km": 103.5, "fuel_level_pct": 48.0, "soc_pct": None, "evt": None},
        {"ts": datetime(2026, 9, 1, 8, 10, 0, tzinfo=timezone.utc), "lat": 12.0, "lon": 77.10, "speed_kmh": 40, "ignition_status": True, "odo_km": 105.0, "fuel_level_pct": 47.0, "soc_pct": None, "evt": None},
    ]
    trips, idle_events = segment_vehicle(events, vin="TESTVIN0000000005", fuel_type="ev")
    
    assert len(trips) == 1
    assert trips[0]["distance_km"] == pytest.approx(5.0, abs=0.1)
    assert trips[0]["end_ts"] == datetime(2026, 9, 1, 8, 10, 0, tzinfo=timezone.utc)
