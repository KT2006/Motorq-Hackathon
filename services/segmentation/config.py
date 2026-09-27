"""
Segmentation Engine — Configuration & Thresholds
==================================================
All tunable parameters for the Trip & Idle state machine live here.
Each constant is documented with its rationale so it can be cited in
docs/algorithms.md (Section 9 of the solution document).

Adjust these based on spot-check results against the test seed data.
"""

# ---------------------------------------------------------------------------
# 1. Speed threshold (km/h)
# ---------------------------------------------------------------------------
# GPS noise on a stationary vehicle rarely reports exactly 0.0 km/h.
# Consumer-grade GPS can drift 1-3 km/h while parked. A threshold of 3 km/h
# avoids false "driving" detections from noise while still catching very slow
# crawling motion (parking lots, traffic jams) as movement.
SPEED_THRESHOLD_KMH: float = 3.0

# ---------------------------------------------------------------------------
# 2. Minimum idle duration to record (seconds)
# ---------------------------------------------------------------------------
# A 5-second stop at a traffic light is not operationally meaningful.
# We only persist idle events lasting >= this many seconds. 60 seconds
# is a reasonable floor — operators care about minutes of wasted fuel,
# not seconds.
MIN_IDLE_DURATION_SEC: int = 60

# ---------------------------------------------------------------------------
# 3. Minimum trip distance / duration to count as a real trip
# ---------------------------------------------------------------------------
# GPS blips can produce phantom micro-trips (vehicle "moves" 20 m then
# "stops"). These filters remove them.
MIN_TRIP_DISTANCE_KM: float = 0.1   # 100 meters
MIN_TRIP_DURATION_SEC: int = 30      # half a minute

# ---------------------------------------------------------------------------
# 4. Maximum in-trip idle before trip is considered ended (seconds)
# ---------------------------------------------------------------------------
# If the vehicle sits idle (speed ≈ 0, ignition on) for longer than this
# during what we thought was a trip, we treat it as "the trip is over and
# this is now depot/pre_trip idle". 15 minutes is a good default — a
# real traffic jam rarely pins you motionless for more than that.
MAX_IN_TRIP_IDLE_SEC: int = 900  # 15 minutes

# ---------------------------------------------------------------------------
# 5. Idle burn rates (litres/hour for ICE, kWh/hour for EV)
# ---------------------------------------------------------------------------
# These match the simulator's assumptions so our cost numbers agree.
# In production, pull these from `idle_burn_rate_reference` in Supabase.
IDLE_BURN_RATE = {
    "petrol":  0.6,   # L/h
    "diesel":  0.5,   # L/h
    "hybrid":  0.3,   # L/h
    "ev":      0.9,   # kWh/h
}

# ---------------------------------------------------------------------------
# 6. Database batch sizes
# ---------------------------------------------------------------------------
INSERT_BATCH_SIZE: int = 500        # rows per INSERT … VALUES batch
TELEMETRY_FETCH_LIMIT: int = 500_000  # max rows fetched per vehicle query
                                       # (safety valve; should never be hit)

# ---------------------------------------------------------------------------
# 7. Idle type classification defaults (v1)
# ---------------------------------------------------------------------------
# In v1 we don't have geofence data, so all out-of-trip idle is "depot".
# When geofence tables are added, we can upgrade to classify "unauthorized".
DEFAULT_OUT_OF_TRIP_IDLE_TYPE: str = "depot"
