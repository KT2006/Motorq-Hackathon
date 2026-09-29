# M4: Trip & Idle Segmentation — Algorithm Design Document

> **Module**: `services/segmentation/`
> **Author**: Kshitij Totawar
> **Satisfies**: Solution Document Section 9 — Algorithm / DP Explanation

---

## 1. Problem Statement

Raw `telemetry_events` is a wall of GPS pings — thousands per vehicle per day, each with a timestamp, speed, ignition status, odometer, and fuel level. This data is useless to a fleet manager in its raw form. They need:

- **Trips** — coherent "vehicle went from A to B" records with distance, duration, fuel consumed
- **Idle Events** — periods where the vehicle was stationary with the engine on, classified by type:
  - `in_trip` — red-light stops, traffic jams (mid-journey)
  - `pre_trip` — warming up before driving
  - `depot` — parked at base, engine idling
  - `unauthorized` — idling at an unexpected location (v2, requires geofence data)

The segmentation engine is the **single transformation** that turns raw telemetry into these structured events. Every downstream feature — cost calculation, utilisation metrics, the dashboard, the AI agent — depends on this being correct.

---

## 2. Algorithm: Single-Pass State Machine (O(n) per vehicle)

### 2.1 Approach

For each vehicle (identified by `vin`), we:

1. Fetch all telemetry rows ordered by `(ts ASC, seq ASC)`
2. Walk through them **once** in a single linear pass, maintaining a finite state machine with 3 states
3. Emit `trip` and `idle_event` records as state transitions occur

This is an **online, streaming-compatible** algorithm — each row's classification depends only on:
- The current state (one of 3 values)
- The currently-open trip/idle event (bounded metadata)
- The current row's fields

No lookback, no lookahead, no sorting within the walk. This is the key **dynamic programming insight**: the optimal classification at row `i` is fully determined by the state carried forward from row `i-1`, not by the entire history.

### 2.2 State Machine

```
                    TRIP_START event
                    OR speed > threshold
    ┌────────────┐ ──────────────────────> ┌──────────┐
    │ NOT_IN_TRIP│                         │ DRIVING  │
    └────────────┘ <────────────────────── └──────────┘
                    TRIP_END event               │  ▲
                    OR ignition off               │  │
                    OR idle too long              │  │
                                    speed ≈ 0    │  │ speed > threshold
                                    ignition on  │  │
                                                 ▼  │
                                          ┌──────────────┐
                                          │ IN_TRIP_IDLE │
                                          └──────────────┘
```

### 2.3 Transition Rules

| From | Condition | To | Action |
|------|-----------|-----|--------|
| `NOT_IN_TRIP` | `evt == 'TRIP_START'` OR (`speed > 3 km/h` AND `ignition == true`) | `DRIVING` | Open new trip |
| `NOT_IN_TRIP` | `speed ≤ 3 km/h` AND `ignition == true` | `NOT_IN_TRIP` | Open/continue depot idle |
| `DRIVING` | `speed ≤ 3 km/h` AND `ignition == true` | `IN_TRIP_IDLE` | Open in-trip idle event |
| `DRIVING` | `evt == 'TRIP_END'` OR `ignition == false` | `NOT_IN_TRIP` | Close trip |
| `IN_TRIP_IDLE` | `speed > 3 km/h` | `DRIVING` | Close idle event |
| `IN_TRIP_IDLE` | Idle duration > 15 min OR `ignition == false` OR `evt == 'TRIP_END'` | `NOT_IN_TRIP` | Close idle + close trip |

### 2.4 Pseudocode

```
state ← NOT_IN_TRIP
current_trip ← null
current_idle ← null

for each row in telemetry_events (ordered by ts ASC):
    match state:
        NOT_IN_TRIP:
            if should_start_trip(row):
                current_trip ← new Trip(row)
                state ← DRIVING
            elif stationary_with_ignition(row):
                track_depot_idle(row)

        DRIVING:
            accumulate_speed(row)
            if should_end_trip(row):
                close_trip(current_trip, row)
                emit(current_trip)
                state ← NOT_IN_TRIP
            elif stationary_with_ignition(row):
                current_idle ← new IdleEvent(row, type='in_trip')
                state ← IN_TRIP_IDLE

        IN_TRIP_IDLE:
            if idle_too_long(row) or should_end_trip(row):
                close_idle(current_idle, row)
                close_trip(current_trip, row)
                emit(current_trip, current_idle)
                state ← NOT_IN_TRIP
            elif speed_above_threshold(row):
                close_idle(current_idle, row)
                emit(current_idle)
                state ← DRIVING
```

---

## 3. Threshold Selection & Rationale

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| **Speed threshold** | 3.0 km/h | GPS noise on stationary vehicles reports 1–3 km/h. Below this, the vehicle is effectively stopped. |
| **Min idle duration** | 60 seconds | A 5-second stop at a traffic light isn't operationally meaningful. Operators care about *minutes* of wasted fuel. |
| **Min trip distance** | 0.1 km (100 m) | Filters phantom micro-trips from GPS drift. A real trip covers at least 100 meters. |
| **Min trip duration** | 30 seconds | Prevents GPS noise blips from registering as trips. |
| **Max in-trip idle** | 900 seconds (15 min) | If a vehicle is motionless for >15 min during a "trip", the trip is effectively over. Real traffic jams rarely pin you completely motionless this long. |

All thresholds are defined in [`config.py`](../services/segmentation/config.py) and can be adjusted based on spot-check validation.

---

## 4. Complexity Analysis

| Dimension | Complexity | Explanation |
|-----------|-----------|-------------|
| **Time** per vehicle | **O(n)** | Single linear pass through `n` telemetry rows. No nested loops, no sorting (data arrives pre-sorted via `ORDER BY ts ASC`). |
| **Space** per vehicle | **O(1)** working memory | Only the current state enum + 2 open event dicts. The output lists grow with the number of trips/idles, but working memory is constant. |
| **Total time** | **O(N)** | Where N = total telemetry events across all vehicles. Each vehicle is independent — embarrassingly parallel if needed. |
| **Database I/O** | **O(N/B)** | B = batch size (500). We use `psycopg2.extras.execute_values` for bulk inserts, not row-by-row. |

For the hackathon seed data (~100K events), this completes in seconds. For production scale (100K vehicles × 30 days), shard across a process pool — each worker handles a slice of VINs independently.

---

## 5. Idempotency

The engine is **safely re-runnable**. Before inserting results for a VIN, it:

```sql
DELETE FROM idle_events WHERE vin = %s;
DELETE FROM trips WHERE vin = %s;
```

This delete-then-insert approach is simpler to reason about than `ON CONFLICT` upserts, since trips and idle events don't have a natural unique constraint beyond their generated UUIDs.

---

## 6. Derived Field Calculations

### Fuel/Energy Used (per trip)
- **ICE**: `fuel_used_l = (fuel_start_pct - fuel_end_pct) / 100 × 50 L` (reference tank capacity)
- **EV**: `energy_used_kwh = (soc_start - soc_end) / 100 × 60 kWh` (reference battery capacity)

### Idle Fuel/Energy Burned (per idle event)
- Calculated from burn rate × duration: `IDLE_BURN_RATE[fuel_type] × hours`
- Burn rates match the simulator's assumptions for internal consistency

### Distance
- `distance_km = odo_end - odo_start` (odometer delta, not GPS haversine — odometer is more accurate for road distance)

### Average Speed
- Running mean of all speed readings during the trip's DRIVING state (excludes in-trip idle readings)

---

## 7. Idle Type Classification (v1 → v2 upgrade path)

**v1 (current):**
- `in_trip` — idle event occurs within an active trip window
- `pre_trip` — idle occurs immediately before a trip starts
- `depot` — all other idle events (default)
- `unauthorized` — not classified in v1

**v2 (when geofence data is available):**
- Add a `depot_locations` table with lat/lon + radius per fleet
- During `_close_idle()`, compute haversine distance from idle location to nearest depot
- If distance > radius → classify as `unauthorized` instead of `depot`

---

## 8. Files (M4)

| File | Purpose |
|------|---------|
| [`services/segmentation/segment.py`](../services/segmentation/segment.py) | Core engine — state machine + DB I/O |
| [`services/segmentation/config.py`](../services/segmentation/config.py) | All tunable thresholds with rationale |
| [`services/segmentation/requirements.txt`](../services/segmentation/requirements.txt) | Python dependencies |

---
---

# M5: Cost & Utilisation Calculation — Algorithm Design Document

> **Module**: `services/segmentation/cost_engine.py`
> **Satisfies**: Solution Document Section 7 (ML/Rules approach) + Section 9 (Top-K algorithm)

---

## 9. Cost Rollup: Daily Aggregation

For each `(vehicle_id, summary_date)`, we compute:

| Field | Formula | Source |
|-------|---------|--------|
| `total_distance_km` | `SUM(trips.distance_km)` for that day | trips (M4) |
| `total_drive_min` | `SUM(trips.duration_min)` | trips (M4) |
| `total_idle_min` | `SUM(idle_events.duration_min)` | idle_events (M4) |
| `available_min` | `1440` (24h) | configurable shift window |
| `fuel_cost` | `total_fuel_used_l × price_per_unit` | fuel_price_reference |
| `idle_cost` | `total_idle_fuel_burned_l × price_per_unit` | idle_burn_rate_reference + fuel_price_reference |
| `utilisation_pct` | `total_drive_min / available_min × 100` | derived |

The rollup uses a single SQL query with CTEs (`trip_daily`, `idle_daily`, `combined`) joined against `vehicles`, `fleets`, and `fuel_price_reference` (via `LATERAL` subquery for closest effective date). Result is upserted via `ON CONFLICT (vehicle_id, summary_date) DO UPDATE`.

### Complexity
- **Time**: O(T + I) where T = trip rows, I = idle rows — single pass via SQL aggregation
- **I/O**: Single query + single batch upsert — 2,280 rows for 85 vehicles × ~27 days

### 9.1 Fuel Prices and Idle Burn Rates Assumptions
- **Fuel prices used in the system** (from `schema.sql` seed data):
  - Petrol: ₹103.44/L (Indian Oil Chennai, Sep 2026)
  - Diesel: ₹92.72/L (Indian Oil Chennai, Sep 2026)
  - EV electricity: ₹8.00/kWh (BESCOM residential tariff)
- **Idle burn rates** (from `config.py`):
  - Petrol: 0.6 L/h, Diesel: 0.5 L/h, Hybrid: 0.3 L/h, EV: 0.9 kWh/h
- **Source citations:** Indian Oil retail price list, BESCOM tariff schedule.
- *Label: All prices are synthetic estimates for demonstration purposes.*

---

## 10. Top-K Idle Offender Scoring

### 10.1 The Problem

Identify the "worst offender" vehicles — those wasting the most money through idling — from `cost_summary_daily`. This is conceptually a **top-K / max-heap problem**.

### 10.2 Naive Baseline

Flag any vehicle where `AVG(total_idle_min) > threshold` (default: 60 min/day).

**Weakness**: A vehicle that drives 10 hours and idles 65 minutes looks the same as one that barely leaves the depot and idles 65 minutes. The raw threshold ignores:
- Idle time *relative* to total active time
- Actual *cost* of that idle time (diesel burns more than hybrid)

### 10.3 Weighted Score (Our Approach)

Each vehicle gets a composite score from three normalized components:

```
score = w₁ × norm(idle_cost) + w₂ × (idle_pct / 100) + w₃ × norm(idle_min)
```

Where:
- `norm(x) = x / max(x)` — min-max normalization to [0, 1] across the fleet
- `idle_pct = idle_min / (idle_min + drive_min) × 100` — idle as fraction of active time
- Weights: `w₁ = w₂ = w₃ = 1.0` (equal weights — defensible starting point; tunable)

This captures three distinct dimensions:
1. **Absolute cost** (w₁) — catches expensive idlers (diesel trucks)
2. **Relative inefficiency** (w₂) — catches vehicles that are *mostly* idling
3. **Raw time waste** (w₃) — catches high-volume idlers regardless of cost

### 10.4 Implementation

PostgreSQL's `ORDER BY score DESC LIMIT K` implements top-K efficiently:
- The database engine does NOT sort the entire table
- It maintains a bounded heap of size K during the scan
- **Complexity**: O(n log K) where n = number of vehicles — heap insertion is O(log K) per vehicle

### 10.5 Baseline vs Weighted — Real Disagreements

From our seed data (85 vehicles, 27 days), using a 500 min/day naive threshold:

| Vehicle | Fuel | Avg Idle | Idle % | Idle Cost | Naive | Weighted |
|---------|------|----------|--------|-----------|-------|----------|
| `CJ75H2TD679HJHGHE` | diesel | 487.0 min | **83.2%** | ₹1,217 | ❌ MISSED | ✅ Caught |
| `NW32EDJMZ55WDBBXU` | petrol | 479.3 min | **82.5%** | ₹1,438 | ❌ MISSED | ✅ Caught |
| `PS289YNHS5478VUV6` | petrol | 511.4 min | 80.5% | ₹15,342 | ✅ Flagged | ✅ Caught |

**Key insight**: Vehicle `CJ75H2TD679HJHGHE` was MISSED by the naive threshold (487 min < 500 min cutoff) but is **83.2% idle** — the vast majority of its active time is wasted idling. The weighted score catches this because `idle_pct` is a first-class scoring component.

### Weighted vs Naive Ranking — Concrete Example

| Vehicle | Idle Min | Total Active Min | Idle Cost (₹) | Naive Flag (>60 min) | Weighted Score |
|---------|----------|------------------|---------------|---------------------|---------------|
| A       | 58       | 150              | 800           | ✗ (below threshold) | 1.47          |
| B       | 65       | 800              | 300           | ✓ (above threshold) | 0.63          |

**Analysis:** Vehicle A has 38.7% idle time and ₹800 waste but is missed by the naive threshold.
Vehicle B has only 8.1% idle time and ₹300 waste but is flagged by the naive approach.
The weighted score correctly identifies Vehicle A as the worse offender.

**Test evidence:** `tests/test_cost_calc.py::test_baseline_vs_weighted_score_disagree_on_edge_case`

---

## 11. ADR: Rules-Based vs ML-Based Scoring

Rules-based scoring was chosen over a trained classifier because labeled ground truth for "wasteful idling" does not exist without fabricating it ourselves. A transparent, tunable, auditable rule (three weighted components, each independently meaningful) is more defensible for a cost-facing metric a fleet manager needs to **trust and act on financially**, versus an opaque model score they cannot interrogate. The weights are configurable and the components are individually interpretable — a fleet manager can understand "this vehicle ranked high because 83% of its active time was idle" in a way they cannot understand "the model assigned score 0.87".

---

## 12. Fleet-Wide Results (Seed Data)

| Metric | Value |
|--------|-------|
| Total fuel cost | ₹5,32,869 |
| Total idle cost | ₹6,65,427 |
| **Idle waste as % of total cost** | **55.5%** |
| Avg daily utilisation | 9.2% |

> The fleet loses more money to idling than to driving. This is the actionable insight the product delivers.

---

## 13. Files (M5)

| File | Purpose |
|------|---------|
| [`services/segmentation/cost_engine.py`](../services/segmentation/cost_engine.py) | Daily rollup + top-K scoring + comparison |
