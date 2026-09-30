import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../services/segmentation')))

from cost_engine import (
    AVAILABLE_MIN_PER_DAY,
    DEFAULT_ELECTRICITY_PRICE_INR_PER_KWH,
    DEFAULT_FUEL_PRICE_INR_PER_LITRE,
    ROLLUP_SQL,
    W_IDLE_COST,
    W_IDLE_MIN,
    W_IDLE_PCT,
)

def test_scoring_weights_positive():
    assert W_IDLE_COST > 0
    assert W_IDLE_PCT > 0
    assert W_IDLE_MIN > 0

def test_available_minutes_per_day():
    assert AVAILABLE_MIN_PER_DAY == 600  # 10-hour scheduled shift

def test_rollup_uses_inr_prices_only():
    assert DEFAULT_FUEL_PRICE_INR_PER_LITRE == 103.0
    assert DEFAULT_ELECTRICITY_PRICE_INR_PER_KWH == 8.0
    assert "fpr.currency = 'INR'" in ROLLUP_SQL

def test_equal_weights():
    """Default weights should be equal for fair multi-factor scoring."""
    assert W_IDLE_COST == W_IDLE_PCT == W_IDLE_MIN
