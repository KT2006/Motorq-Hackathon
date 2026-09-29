import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../services/segmentation')))

from config import (
    SPEED_THRESHOLD_KMH, MIN_IDLE_DURATION_SEC, MIN_TRIP_DISTANCE_KM,
    MIN_TRIP_DURATION_SEC, MAX_IN_TRIP_IDLE_SEC, IDLE_BURN_RATE,
    INSERT_BATCH_SIZE, TELEMETRY_FETCH_LIMIT
)

def test_speed_threshold_positive():
    assert SPEED_THRESHOLD_KMH > 0

def test_idle_duration_threshold_positive():
    assert MIN_IDLE_DURATION_SEC > 0

def test_min_trip_distance_positive():
    assert MIN_TRIP_DISTANCE_KM > 0

def test_min_trip_duration_positive():
    assert MIN_TRIP_DURATION_SEC > 0

def test_max_idle_greater_than_min():
    assert MAX_IN_TRIP_IDLE_SEC > MIN_IDLE_DURATION_SEC

def test_burn_rates_all_fuel_types():
    for ft in ['petrol', 'diesel', 'hybrid', 'ev']:
        assert ft in IDLE_BURN_RATE
        assert IDLE_BURN_RATE[ft] > 0

def test_burn_rate_ordering():
    # EV climate-control draw > petrol > diesel > hybrid
    assert IDLE_BURN_RATE['ev'] > IDLE_BURN_RATE['petrol']
    assert IDLE_BURN_RATE['petrol'] > IDLE_BURN_RATE['diesel']
    assert IDLE_BURN_RATE['diesel'] > IDLE_BURN_RATE['hybrid']

def test_batch_size_positive():
    assert INSERT_BATCH_SIZE > 0

def test_fetch_limit_positive():
    assert TELEMETRY_FETCH_LIMIT > 0

