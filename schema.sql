-- ============================================================
-- FUEL, IDLING & UTILISATION COST
-- Supabase PostgreSQL 17
-- No TimescaleDB dependency
-- ============================================================


-- ============================================================
-- 1. EXTENSIONS
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";


-- ============================================================
-- 2. MASTER / REFERENCE DATA
-- ============================================================

CREATE TABLE IF NOT EXISTS fleets (
    fleet_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fleet_name      TEXT NOT NULL,
    operator_name   TEXT NOT NULL,

    fleet_type      TEXT NOT NULL
        CHECK (fleet_type IN (
            'commercial',
            'rental',
            'lender',
            'dealership'
        )),

    region          TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);


CREATE TABLE IF NOT EXISTS vehicles (
    vehicle_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    vin                     CHAR(17) NOT NULL UNIQUE,

    fleet_id                UUID NOT NULL
        REFERENCES fleets(fleet_id)
        ON DELETE CASCADE,

    make                    TEXT NOT NULL,
    model                   TEXT NOT NULL,

    model_year              SMALLINT NOT NULL
        CHECK (model_year BETWEEN 1980 AND 2100),

    fuel_type               TEXT NOT NULL
        CHECK (fuel_type IN (
            'petrol',
            'diesel',
            'hybrid',
            'ev'
        )),

    engine_displacement_l   NUMERIC(3,1),
    battery_capacity_kwh    NUMERIC(6,2),
    tank_capacity_l         NUMERIC(6,2),

    odometer_km_baseline    NUMERIC(10,1) NOT NULL DEFAULT 0
        CHECK (odometer_km_baseline >= 0),

    status                  TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN (
            'active',
            'maintenance',
            'retired'
        )),

    onboarded_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);


CREATE INDEX IF NOT EXISTS idx_vehicles_fleet
ON vehicles(fleet_id);


CREATE TABLE IF NOT EXISTS drivers (
    driver_id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    fleet_id                UUID NOT NULL
        REFERENCES fleets(fleet_id)
        ON DELETE CASCADE,

    name                    TEXT NOT NULL,

    license_no              TEXT NOT NULL,

    assigned_vehicle_id     UUID
        REFERENCES vehicles(vehicle_id)
        ON DELETE SET NULL,

    hire_date               DATE NOT NULL DEFAULT CURRENT_DATE
);


CREATE INDEX IF NOT EXISTS idx_drivers_fleet
ON drivers(fleet_id);


CREATE INDEX IF NOT EXISTS idx_drivers_vehicle
ON drivers(assigned_vehicle_id);


-- ============================================================
-- 3. REFERENCE / ASSUMPTION DATA
-- ============================================================

CREATE TABLE IF NOT EXISTS fuel_price_reference (

    fuel_type       TEXT NOT NULL,

    price_per_unit  NUMERIC(8,4) NOT NULL
        CHECK (price_per_unit >= 0),

    currency        TEXT NOT NULL DEFAULT 'INR',

    region          TEXT NOT NULL,

    effective_date  DATE NOT NULL,

    PRIMARY KEY (
        fuel_type,
        region,
        effective_date
    )
);


CREATE TABLE IF NOT EXISTS idle_burn_rate_reference (

    vehicle_class      TEXT PRIMARY KEY,

    idle_burn_rate     NUMERIC(8,3) NOT NULL
        CHECK (idle_burn_rate >= 0),

    source_citation    TEXT NOT NULL
);


-- ============================================================
-- 4. HIGH-VOLUME TELEMETRY DATA
--
-- Normal PostgreSQL table.
-- For ~100k / few million rows this is completely fine.
-- ============================================================

CREATE TABLE IF NOT EXISTS telemetry_events (

    event_id            BIGSERIAL PRIMARY KEY,

    vin                 CHAR(17) NOT NULL,

    ts                  TIMESTAMPTZ NOT NULL,

    lat                 DOUBLE PRECISION NOT NULL
        CHECK (lat BETWEEN -90 AND 90),

    lon                 DOUBLE PRECISION NOT NULL
        CHECK (lon BETWEEN -180 AND 180),

    speed_kmh           REAL NOT NULL
        CHECK (speed_kmh >= 0),

    odo_km              NUMERIC(10,1) NOT NULL
        CHECK (odo_km >= 0),

    ignition_status     BOOLEAN NOT NULL,

    fuel_level_pct      REAL
        CHECK (
            fuel_level_pct IS NULL
            OR fuel_level_pct BETWEEN 0 AND 100
        ),

    soc_pct             REAL
        CHECK (
            soc_pct IS NULL
            OR soc_pct BETWEEN 0 AND 100
        ),

    dtc                 TEXT[],

    evt                  TEXT
        CHECK (
            evt IS NULL
            OR evt IN (
                'HARSH_BRAKE',
                'HARSH_ACCELERATION',
                'IDLE_START',
                'IDLE_END',
                'TRIP_START',
                'TRIP_END'
            )
        ),

    seq                 BIGINT NOT NULL
);


-- Important indexes for telemetry queries

CREATE INDEX IF NOT EXISTS idx_telemetry_vin_ts
ON telemetry_events (vin, ts DESC);


CREATE INDEX IF NOT EXISTS idx_telemetry_ts
ON telemetry_events (ts DESC);


CREATE INDEX IF NOT EXISTS idx_telemetry_evt
ON telemetry_events (evt)
WHERE evt IS NOT NULL;


-- Prevent duplicate telemetry packets
CREATE UNIQUE INDEX IF NOT EXISTS idx_telemetry_unique_packet
ON telemetry_events (vin, ts, seq);


-- ============================================================
-- 5. TRIPS
-- ============================================================

CREATE TABLE IF NOT EXISTS trips (

    trip_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    vin                 CHAR(17) NOT NULL,

    driver_id           UUID
        REFERENCES drivers(driver_id)
        ON DELETE SET NULL,

    start_ts            TIMESTAMPTZ NOT NULL,

    end_ts              TIMESTAMPTZ NOT NULL,

    start_lat           DOUBLE PRECISION NOT NULL,

    start_lon           DOUBLE PRECISION NOT NULL,

    end_lat             DOUBLE PRECISION NOT NULL,

    end_lon             DOUBLE PRECISION NOT NULL,

    distance_km         NUMERIC(10,2) NOT NULL DEFAULT 0
        CHECK (distance_km >= 0),

    duration_min        NUMERIC(10,2) NOT NULL DEFAULT 0
        CHECK (duration_min >= 0),

    avg_speed_kmh       NUMERIC(8,2) NOT NULL DEFAULT 0
        CHECK (avg_speed_kmh >= 0),

    fuel_used_l         NUMERIC(10,3),

    energy_used_kwh     NUMERIC(10,3),

    idle_duration_min   NUMERIC(10,2) NOT NULL DEFAULT 0
        CHECK (idle_duration_min >= 0),

    CONSTRAINT trips_valid_time
        CHECK (end_ts >= start_ts)
);


CREATE INDEX IF NOT EXISTS idx_trips_vin_start
ON trips (vin, start_ts DESC);


CREATE INDEX IF NOT EXISTS idx_trips_driver
ON trips (driver_id);


-- ============================================================
-- 6. IDLE EVENTS
-- ============================================================

CREATE TABLE IF NOT EXISTS idle_events (

    idle_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    vin                 CHAR(17) NOT NULL,

    trip_id             UUID
        REFERENCES trips(trip_id)
        ON DELETE SET NULL,

    start_ts            TIMESTAMPTZ NOT NULL,

    end_ts              TIMESTAMPTZ NOT NULL,

    duration_min        NUMERIC(10,2) NOT NULL DEFAULT 0
        CHECK (duration_min >= 0),

    lat                 DOUBLE PRECISION NOT NULL,

    lon                 DOUBLE PRECISION NOT NULL,

    fuel_burned_l       NUMERIC(10,3),

    energy_burned_kwh   NUMERIC(10,3),

    idle_type           TEXT NOT NULL
        CHECK (
            idle_type IN (
                'in_trip',
                'pre_trip',
                'depot',
                'unauthorized'
            )
        ),

    CONSTRAINT idle_valid_time
        CHECK (end_ts >= start_ts)
);


CREATE INDEX IF NOT EXISTS idx_idle_vin_start
ON idle_events (vin, start_ts DESC);


CREATE INDEX IF NOT EXISTS idx_idle_type
ON idle_events (idle_type);


-- ============================================================
-- 7. DAILY ROLLUP
--
-- Dashboard/API should query this instead of scanning
-- telemetry_events repeatedly.
-- ============================================================

CREATE TABLE IF NOT EXISTS cost_summary_daily (

    vehicle_id          UUID NOT NULL
        REFERENCES vehicles(vehicle_id)
        ON DELETE CASCADE,

    summary_date        DATE NOT NULL,

    total_distance_km   NUMERIC(10,2) NOT NULL DEFAULT 0,

    total_drive_min     NUMERIC(10,2) NOT NULL DEFAULT 0,

    total_idle_min      NUMERIC(10,2) NOT NULL DEFAULT 0,

    available_min       NUMERIC(10,2) NOT NULL
        CHECK (available_min >= 0),

    fuel_cost           NUMERIC(12,2) NOT NULL DEFAULT 0,

    idle_cost           NUMERIC(12,2) NOT NULL DEFAULT 0,

    utilisation_pct     NUMERIC(6,2) NOT NULL DEFAULT 0
        CHECK (
            utilisation_pct BETWEEN 0 AND 100
        ),

    PRIMARY KEY (
        vehicle_id,
        summary_date
    )
);


CREATE INDEX IF NOT EXISTS idx_cost_summary_date
ON cost_summary_daily (summary_date DESC);


-- ============================================================
-- 8. USEFUL DASHBOARD INDEXES
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_idle_vin
ON idle_events(vin);

CREATE INDEX IF NOT EXISTS idx_trips_vin
ON trips(vin);


-- ============================================================
-- 9. AI AGENT AUDIT LOG
-- ============================================================

CREATE TABLE IF NOT EXISTS agent_logs (
    log_id              BIGSERIAL PRIMARY KEY,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_question       TEXT NOT NULL,
    tool_calls_json     JSONB,
    final_answer        TEXT
);

CREATE INDEX IF NOT EXISTS idx_agent_logs_created
ON agent_logs (created_at DESC);


-- ============================================================
-- 10. MONTHLY FLEET COST MATERIALIZED VIEW
--
-- Pre-aggregated by (fleet_id, month) for the /fleet/summary
-- headline KPI endpoint. Refresh after each daily cost rollup.
-- ============================================================

CREATE MATERIALIZED VIEW IF NOT EXISTS monthly_fleet_cost AS
SELECT
    v.fleet_id,
    date_trunc('month', cs.summary_date)::date    AS month,
    SUM(cs.fuel_cost)                              AS total_fuel_cost,
    SUM(cs.idle_cost)                              AS total_idle_cost,
    ROUND(AVG(cs.utilisation_pct)::numeric, 2)    AS avg_utilisation_pct,
    SUM(cs.total_idle_min)                         AS total_idle_min,
    COUNT(DISTINCT cs.vehicle_id)                  AS vehicle_count
FROM cost_summary_daily cs
JOIN vehicles v ON v.vehicle_id = cs.vehicle_id
GROUP BY v.fleet_id, date_trunc('month', cs.summary_date)::date;


-- Unique index enables REFRESH CONCURRENTLY and fast lookups
CREATE UNIQUE INDEX IF NOT EXISTS idx_monthly_fleet_cost_pk
ON monthly_fleet_cost (fleet_id, month);

CREATE INDEX IF NOT EXISTS idx_monthly_fleet_cost_month
ON monthly_fleet_cost (month DESC);


-- ============================================================
-- 11. OPTIONAL: BASIC SEED DATA
-- ============================================================
-- You can delete this section if you don't want sample data.


INSERT INTO fuel_price_reference
    (fuel_type, price_per_unit, currency, region, effective_date)
VALUES
    ('petrol', 100.00, 'INR', 'India', CURRENT_DATE),
    ('diesel', 92.00, 'INR', 'India', CURRENT_DATE),
    ('hybrid', 100.00, 'INR', 'India', CURRENT_DATE),
    ('ev', 10.00, 'INR', 'India', CURRENT_DATE)
ON CONFLICT DO NOTHING;

INSERT INTO idle_burn_rate_reference
    (vehicle_class, idle_burn_rate, source_citation)
VALUES
    ('light_commercial', 0.800, 'US DOE AFDC: Idling Reduction for Commercial Vehicles (2015), Table 2'),
    ('heavy_commercial', 1.600, 'US DOE AFDC: Idling Reduction for Commercial Vehicles (2015), Table 2'),
    ('passenger',        0.500, 'Natural Resources Canada: Idling Guide (2021)'),
    ('electric',         0.000, 'EVs draw negligible energy at idle (HVAC only, ~0.5 kWh/h)')
ON CONFLICT DO NOTHING;


-- ============================================================
-- DONE
-- ============================================================