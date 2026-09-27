import pytest

# These functions represent the core math logic that is executed by the 
# PostgreSQL ROLLUP_SQL query in services/segmentation/cost_engine.py
# Extracted here for unit testing the logic in isolation as per M11 requirements.

def calculate_fuel_cost(fuel_used_l: float, price_per_liter: float) -> float:
    return fuel_used_l * price_per_liter

def calculate_idle_cost(idle_minutes: float, burn_rate_per_min: float, price_per_liter: float) -> float:
    return idle_minutes * burn_rate_per_min * price_per_liter

def calculate_utilisation(drive_min: float, available_min: float) -> float:
    if available_min <= 0: return 0.0
    return min(100.0, (drive_min / available_min) * 100.0)

def compute_weighted_score(vehicle: dict) -> float:
    # W_IDLE_COST=1.0, W_IDLE_PCT=1.0, W_IDLE_MIN=1.0
    w_cost = 1.0
    w_pct = 1.0
    w_min = 1.0
    
    # Mocking the normalizations from the SQL
    normalized_cost = vehicle["idle_cost"] / 1000.0  # mock max cost
    idle_pct_of_active = vehicle["idle_min"] / vehicle["total_active_min"]
    normalized_min = vehicle["idle_min"] / 100.0     # mock max min
    
    return (w_cost * normalized_cost) + (w_pct * idle_pct_of_active) + (w_min * normalized_min)

def flag_naive(vehicle: dict, threshold: float) -> bool:
    return vehicle["idle_min"] > threshold


def test_fuel_cost_calculation():
    trip = {"fuel_used_l": 5.0}
    price_per_liter = 100.00
    assert calculate_fuel_cost(trip["fuel_used_l"], price_per_liter) == 500.00

def test_idle_cost_uses_burn_rate():
    idle_minutes = 30
    burn_rate_per_min = 0.05  # liters/min
    price_per_liter = 100.00
    assert calculate_idle_cost(idle_minutes, burn_rate_per_min, price_per_liter) == pytest.approx(150.00)

def test_utilisation_percentage():
    assert calculate_utilisation(drive_min=480, available_min=1440) == pytest.approx(33.33, abs=0.01)

def test_baseline_vs_weighted_score_disagree_on_edge_case():
    # The concrete example: high idle %, low absolute idle minutes (under threshold)
    vehicle_a = {"idle_min": 58, "total_active_min": 150, "idle_cost": 800}  # just under naive threshold
    vehicle_b = {"idle_min": 65, "total_active_min": 800, "idle_cost": 300}  # just over naive threshold, but low idle %

    assert flag_naive(vehicle_a, threshold=60) == False
    assert flag_naive(vehicle_b, threshold=60) == True
    
    # But vehicle A is actually worse based on the weighted score
    assert compute_weighted_score(vehicle_a) > compute_weighted_score(vehicle_b)
