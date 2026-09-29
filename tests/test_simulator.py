import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../simulator')))

from data_simulator import (
    gen_vin, gen_fleets, gen_vehicles, haversine_km, inject_noise,
    simulate_vehicle_day, random_point
)
import pandas as pd
from datetime import datetime, timezone

def test_vin_length_and_characters():
    vin = gen_vin()
    assert len(vin) == 17
    # VIN should not contain I, O, Q
    assert 'I' not in vin
    assert 'O' not in vin
    assert 'Q' not in vin

def test_gen_fleets_returns_dataframe():
    fleets = gen_fleets(3)
    assert isinstance(fleets, pd.DataFrame)
    assert len(fleets) == 3
    assert 'fleet_id' in fleets.columns
    assert 'fleet_name' in fleets.columns

def test_gen_vehicles_returns_correct_count():
    fleets = gen_fleets(1)
    vehicles = gen_vehicles(10, fleets)
    assert len(vehicles) == 10
    assert 'vin' in vehicles.columns
    assert 'fuel_type' in vehicles.columns

def test_haversine_zero_distance():
    dist = haversine_km(12.0, 77.0, 12.0, 77.0)
    assert dist == 0.0

def test_haversine_known_distance():
    # Chennai to Bangalore ~280 km
    dist = haversine_km(13.0827, 80.2707, 12.9716, 77.5946)
    assert 250 < dist < 320

def test_random_point_in_bounds():
    for _ in range(100):
        lat, lon = random_point()
        assert 12.90 <= lat <= 13.20
        assert 80.10 <= lon <= 80.30

def test_simulate_vehicle_day_returns_events():
    day = datetime(2026, 9, 1, tzinfo=timezone.utc)
    events, odo, fuel = simulate_vehicle_day('TESTVIN0000000001', 'petrol', day, 1000.0, 80.0)
    assert len(events) > 0
    assert odo >= 1000.0
    assert 0 < fuel <= 100.0

def test_inject_noise_preserves_most_events():
    events = [{'vin': 'TEST', 'seq': i} for i in range(100)]
    noisy = inject_noise(events)
    # Should preserve ~95%+ of events (drop rate is 0.5%)
    assert len(noisy) >= 80

def test_inject_noise_can_add_duplicates():
    events = [{'vin': 'TEST', 'seq': i} for i in range(1000)]
    noisy = inject_noise(events, dup_rate=0.1, drop_rate=0, reorder_rate=0)
    # With 10% dup rate, should have more events than original
    assert len(noisy) > len(events)

def test_ev_vehicle_has_battery_capacity():
    fleets = gen_fleets(1)
    vehicles = gen_vehicles(100, fleets)
    ev_vehicles = vehicles[vehicles['fuel_type'] == 'ev']
    if len(ev_vehicles) > 0:
        assert ev_vehicles['battery_capacity_kwh'].notna().all()
        assert ev_vehicles['tank_capacity_l'].isna().all()
