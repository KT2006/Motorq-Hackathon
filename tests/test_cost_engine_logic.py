import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../services/segmentation')))

from cost_engine import W_IDLE_COST, W_IDLE_PCT, W_IDLE_MIN, AVAILABLE_MIN_PER_DAY

def test_scoring_weights_positive():
    assert W_IDLE_COST > 0
    assert W_IDLE_PCT > 0
    assert W_IDLE_MIN > 0

def test_available_minutes_per_day():
    assert AVAILABLE_MIN_PER_DAY == 1440  # 24 * 60

def test_equal_weights():
    """Default weights should be equal for fair multi-factor scoring."""
    assert W_IDLE_COST == W_IDLE_PCT == W_IDLE_MIN
